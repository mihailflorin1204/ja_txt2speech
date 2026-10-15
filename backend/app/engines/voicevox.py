import asyncio
import io
import logging
from collections.abc import AsyncIterator

import httpx
import numpy as np
import soundfile as sf

from app.core.config import get_settings
from app.engines.base import (
    AudioChunk,
    EngineHealth,
    EngineUnavailableError,
    Feature,
    SynthesisSettings,
    Utterance,
    VoiceInfo,
)

log = logging.getLogger("engine.voicevox")

FEATURES = [
    Feature.STYLE,
    Feature.ACCENT_EDIT,
    Feature.PITCH,
    Feature.SPEED,
    Feature.INTONATION,
]


class VoicevoxEngine:
    id = "voicevox"

    def __init__(self) -> None:
        s = get_settings()
        self._base = f"http://{s.voicevox_host}:{s.voicevox_port}"
        self._exe = s.voicevox_exe
        self._use_gpu = s.voicevox_use_gpu and s.device != "cpu"
        self._proc: asyncio.subprocess.Process | None = None
        self._client = httpx.AsyncClient(base_url=self._base, timeout=120.0)
        self._starting = False

    async def start(self) -> None:
        if await self._is_up():
            return
        if not self._exe.exists():
            root = get_settings().external_dir
            matches = sorted(root.glob("**/run.exe")) if root.exists() else []
            if matches:
                self._exe = matches[0]
            else:
                log.warning("VOICEVOX executable not found at %s", self._exe)
                raise EngineUnavailableError(f"VOICEVOX exe not found: {self._exe}")
        self._starting = True
        args = [str(self._exe), "--host", "127.0.0.1", "--port", str(get_settings().voicevox_port)]
        args.append("--use_gpu" if self._use_gpu else "--no-use_gpu")
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self._exe.parent,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        log.info("spawned VOICEVOX engine pid=%s", self._proc.pid)
        try:
            await self._wait_ready(timeout=60.0)
        finally:
            self._starting = False

    async def stop(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except TimeoutError:
                self._proc.kill()
        self._proc = None

    async def _is_up(self) -> bool:
        try:
            r = await self._client.get("/version", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def _wait_ready(self, timeout: float) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                raise EngineUnavailableError(f"VOICEVOX exited with code {self._proc.returncode}")
            if await self._is_up():
                log.info("VOICEVOX engine ready")
                return
            await asyncio.sleep(1.0)
        raise EngineUnavailableError("VOICEVOX did not become ready in time")

    async def health(self) -> EngineHealth:
        if self._starting:
            return EngineHealth(status="starting")
        if await self._is_up():
            return EngineHealth(status="ok")
        return EngineHealth(status="offline", detail="engine process not responding")

    def supports(self, feature: Feature) -> bool:
        return feature in FEATURES

    async def list_voices(self) -> list[VoiceInfo]:
        if not await self._is_up():
            raise EngineUnavailableError("VOICEVOX offline")
        r = await self._client.get("/speakers")
        r.raise_for_status()
        voices: list[VoiceInfo] = []
        for sp in r.json():
            name = sp["name"]
            style_names = [st["name"] for st in sp.get("styles", [])]
            for st in sp.get("styles", []):
                voices.append(
                    VoiceInfo(
                        id=f"voicevox:{st['id']}",
                        engine=self.id,
                        engine_voice_id=str(st["id"]),
                        name=f"{name}（{st['name']}）",
                        styles=style_names,
                        features=FEATURES,
                        credit=f"VOICEVOX:{name}",
                    )
                )
        return voices

    def _apply_settings(self, query: dict, settings: SynthesisSettings) -> dict:
        query["speedScale"] = settings.speed
        query["pitchScale"] = settings.pitch * 0.01  # ~semitones to engine scale
        query["intonationScale"] = settings.intonation
        query["volumeScale"] = settings.volume
        query["outputSamplingRate"] = 44100
        query["outputStereo"] = False
        if settings.pause_scale != 1.0:
            query["pauseLengthScale"] = settings.pause_scale
        return query

    def _apply_accent_overrides(self, query: dict, utterance: Utterance) -> dict:
        """Replace query accent phrases with analyzed/edited ones when counts align."""
        if not utterance.accent_phrases:
            return query
        q_phrases = query.get("accent_phrases", [])
        u_phrases = utterance.accent_phrases
        if len(q_phrases) != len(u_phrases):
            return query
        for qp, up in zip(q_phrases, u_phrases, strict=True):
            qp["accent"] = up.accent
            if up.pause_after_ms:
                qp["pause_mora"] = {
                    "text": "、",
                    "consonant": None,
                    "vowel": "pau",
                    "pitch": 0.0,
                    "pause_length": round(up.pause_after_ms / 1000.0, 3),
                }
        return query

    async def _audio_query(self, text: str, speaker: int) -> dict:
        r = await self._client.post("/audio_query", params={"text": text, "speaker": speaker})
        r.raise_for_status()
        return r.json()

    async def synthesize(
        self, utterance: Utterance, voice_id: str, settings: SynthesisSettings
    ) -> AudioChunk:
        speaker = int(voice_id)
        query = self._apply_settings(await self._audio_query(utterance.text, speaker), settings)
        query = self._apply_accent_overrides(query, utterance)
        r = await self._client.post(
            "/synthesis", params={"speaker": speaker}, json=query,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return self._decode_wav(r.content)

    async def synthesize_stream(
        self, utterances: list[Utterance], voice_id: str, settings: SynthesisSettings
    ) -> AsyncIterator[AudioChunk]:
        for i, utt in enumerate(utterances):
            chunk = await self.synthesize(utt, voice_id, settings)
            chunk.sentence_index = i
            yield chunk

    @staticmethod
    def _decode_wav(data: bytes) -> AudioChunk:
        samples, sr = sf.read(io.BytesIO(data), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        return AudioChunk.from_float32(np.asarray(samples, dtype=np.float32), int(sr))
