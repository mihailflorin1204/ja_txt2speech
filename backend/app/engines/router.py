import asyncio
import logging
import time
from collections import OrderedDict

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.db import get_engine
from app.engines.base import (
    AudioChunk,
    EngineHealth,
    EngineUnavailableError,
    Feature,
    SynthesisSettings,
    TTSEngine,
    Utterance,
    VoiceInfo,
)
from app.engines.sbv2 import Sbv2Engine
from app.engines.voicevox import VoicevoxEngine
from app.models.tables import Voice

log = logging.getLogger("engine.router")

VOICE_SEP = ":"


def split_voice_id(voice_id: str) -> tuple[str, str]:
    if VOICE_SEP not in voice_id:
        raise EngineUnavailableError(f"invalid voice id: {voice_id}")
    return tuple(voice_id.split(VOICE_SEP, 1))  # type: ignore[return-value]


class EngineRouter:
    """Maps voice ids to engine adapters, manages engine lifecycles and GPU memory."""

    def __init__(self) -> None:
        s = get_settings()
        self._engines: dict[str, TTSEngine] = {}
        if s.voicevox_enabled:
            self._engines["voicevox"] = VoicevoxEngine()
        if s.sbv2_enabled:
            self._engines["sbv2"] = Sbv2Engine()
        if s.gptsovits_enabled:
            from app.engines.gptsovits import GPTSoVITSEngine
            self._engines["gptsovits"] = GPTSoVITSEngine()
        self._locks: dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in self._engines}
        self._resident: OrderedDict[str, float] = OrderedDict()  # engine id -> last used
        self._engine_health: dict[str, EngineHealth] = {}
        self._supervisor_task: asyncio.Task | None = None

    # -- lifecycle -----------------------------------------------------------

    def start_supervisor(self) -> None:
        self._supervisor_task = asyncio.create_task(self._supervise())

    async def stop_all(self) -> None:
        if self._supervisor_task:
            self._supervisor_task.cancel()
        for eng in list(self._resident):
            await self._unload(eng)

    async def _supervise(self) -> None:
        """Periodically health-check resident engines and restart dead ones."""
        while True:
            await asyncio.sleep(10)
            for eng_id in list(self._resident):
                try:
                    health = await self._engines[eng_id].health()
                except Exception as e:  # noqa: BLE001
                    health = EngineHealth(status="error", detail=str(e))
                self._engine_health[eng_id] = health
                if health.status not in ("ok", "starting"):
                    log.warning("engine %s unhealthy (%s); restarting", eng_id, health.detail)
                    try:
                        async with self._locks[eng_id]:
                            await self._engines[eng_id].start()
                    except Exception as e:  # noqa: BLE001
                        log.error("engine %s restart failed: %s", eng_id, e)
                        self._engine_health[eng_id] = EngineHealth(status="error", detail=str(e))

    async def ensure_running(self, engine_id: str) -> TTSEngine:
        if engine_id not in self._engines:
            raise EngineUnavailableError(f"unknown engine: {engine_id}")
        async with self._locks[engine_id]:
            await self._evict_if_needed(engine_id)
            eng = self._engines[engine_id]
            health = await eng.health()
            if health.status in ("offline", "error"):
                await eng.start()
            self._resident[engine_id] = time.monotonic()
            self._resident.move_to_end(engine_id)
            return eng

    async def _ensure_started(self, engine_id: str) -> TTSEngine:
        """Start an engine if needed and mark it resident — without evicting.

        Used by catalog listing: a read-only operation must not unload
        engines (LRU eviction is synthesis-time GPU memory management).
        """
        eng = self._engines[engine_id]
        async with self._locks[engine_id]:
            health = await eng.health()
            if health.status in ("offline", "error"):
                await eng.start()
            self._resident[engine_id] = time.monotonic()
            self._resident.move_to_end(engine_id)
            return eng

    async def _evict_if_needed(self, incoming: str) -> None:
        s = get_settings()
        resident = [e for e in self._resident if e != incoming]
        while len(resident) >= max(1, s.max_resident_engines):
            victim = resident.pop(0)
            await self._unload(victim)

    async def _unload(self, engine_id: str) -> None:
        try:
            await self._engines[engine_id].stop()
        except Exception as e:  # noqa: BLE001
            log.warning("failed to stop engine %s: %s", engine_id, e)
        self._resident.pop(engine_id, None)

    # -- catalog -------------------------------------------------------------

    async def health(self) -> dict[str, EngineHealth]:
        """Live health of every enabled engine (cheap ping — always fresh)."""
        out = {}
        for eng_id, eng in self._engines.items():
            try:
                out[eng_id] = await eng.health()
            except Exception as e:  # noqa: BLE001
                out[eng_id] = EngineHealth(status="error", detail=str(e))
            self._engine_health[eng_id] = out[eng_id]
        return out

    async def all_voices(self) -> list[VoiceInfo]:
        """Catalog = live engine voices + DB rows (favorites, clones, availability).

        Successfully listed voices are persisted to the Voice table so voices
        of a currently-offline engine still appear as unavailable (FR-2.4).
        """
        voices: dict[str, VoiceInfo] = {}
        live: set[str] = set()
        for eng_id, eng in self._engines.items():
            try:
                await self._ensure_started(eng_id)
                for v in await eng.list_voices():
                    voices[v.id] = v
                live.add(eng_id)
            except EngineUnavailableError as e:
                log.warning("catalog: engine %s unavailable: %s", eng_id, e)
            except Exception as e:  # noqa: BLE001
                log.error("catalog: engine %s error: %s", eng_id, e)

        with Session(get_engine()) as session:
            # upsert live voices for offline-catalog persistence
            for v in voices.values():
                row = session.get(Voice, v.id)
                if row is None:
                    session.add(Voice(
                        id=v.id, engine=v.engine, engine_voice_id=v.engine_voice_id,
                        name=v.name, gender=v.gender,
                        styles=[{"name": s} for s in v.styles],
                        features=[f.value for f in v.features],
                        credit=v.credit,
                    ))
                else:
                    row.styles = [{"name": s} for s in v.styles]
                    row.features = [f.value for f in v.features]
                    row.credit = v.credit or row.credit
                    session.add(row)
            session.commit()
            rows = session.exec(select(Voice)).all()
        db_voices = {r.id: r for r in rows}

        for vid, row in db_voices.items():
            if vid in voices:
                # listed live: merge DB-side fields (favorites, clone renames)
                voices[vid].is_favorite = row.is_favorite
                voices[vid].is_cloned = row.is_cloned
                if row.name and row.name != voices[vid].name:
                    voices[vid].name = row.name
            else:
                # engine offline or voice removed upstream: still listed
                voices[vid] = VoiceInfo(
                    id=row.id, engine=row.engine, engine_voice_id=row.engine_voice_id,
                    name=row.name, gender=row.gender,
                    styles=[s.get("name", "") for s in row.styles],
                    features=[Feature(f) for f in row.features],
                    credit=row.credit, is_cloned=row.is_cloned,
                    is_favorite=row.is_favorite,
                    available=False,
                )

        for v in voices.values():
            if v.engine not in live:
                v.available = False
        return list(voices.values())

    # -- synthesis -----------------------------------------------------------

    async def synthesize(
        self, utterance: Utterance, voice_id: str, settings: SynthesisSettings
    ) -> AudioChunk:
        eng_id, evoice = split_voice_id(voice_id)
        eng = await self.ensure_running(eng_id)
        async with self._locks[eng_id]:
            self._resident[eng_id] = time.monotonic()
            self._resident.move_to_end(eng_id)
            t0 = time.perf_counter()
            try:
                chunk = await eng.synthesize(utterance, evoice, settings)
            except Exception:
                from app.core import metrics
                metrics.record_error("SYNTH_FAILED", f"{eng_id}:{evoice}")
                raise
            from app.core import metrics
            metrics.record_synth(eng_id, time.perf_counter() - t0,
                                 len(chunk.pcm) / 2 / chunk.sample_rate,
                                 len(utterance.text))
            return chunk

    def supports(self, voice_id: str, feature: Feature) -> bool:
        eng_id, _ = split_voice_id(voice_id)
        eng = self._engines.get(eng_id)
        return eng is not None and eng.supports(feature)


_router: EngineRouter | None = None


def get_router() -> EngineRouter:
    global _router
    if _router is None:
        _router = EngineRouter()
    return _router
