"""GPT-SoVITS adapter — voice-cloning engine (spec §4.3, M5).

Runs `api_v2.py` as a subprocess in its own venv. Each CloneSample row in the
DB becomes a voice (id `gptsovits:<sample_id>`); synthesis posts the sample's
audio path + transcript as the reference to POST /tts.
"""

import asyncio
import logging
import sys

import httpx
import numpy as np
import soundfile as sf
from sqlmodel import Session, select

from app.core.audio import TARGET_SR, resample
from app.core.config import get_settings
from app.core.db import get_engine
from app.engines.base import (
    AudioChunk,
    EngineHealth,
    EngineUnavailableError,
    Feature,
    SynthesisSettings,
    Utterance,
    VoiceInfo,
)
from app.models.tables import CloneSample

log = logging.getLogger("engine.gptsovits")


class GPTSoVITSEngine:
    id = "gptsovits"
    name = "gptsovits"
    display_name = "GPT-SoVITS (voice clone)"

    def supports(self, feature: Feature) -> bool:
        return feature in {Feature.CLONING, Feature.SPEED}

    def __init__(self) -> None:
        s = get_settings()
        self._base = f"http://{s.gptsovits_host}:{s.gptsovits_port}"
        self._enabled = s.gptsovits_enabled
        self._exe = s.gptsovits_repo
        self._proc: asyncio.subprocess.Process | None = None
        self._client = httpx.AsyncClient(base_url=self._base, timeout=300.0)
        self._starting = False

    async def _is_up(self) -> bool:
        try:
            r = await self._client.get("/tts", params={
                "text": "テスト", "text_lang": "ja",
                "ref_audio_path": "x.wav", "prompt_lang": "ja"}, timeout=3.0)
            return r.status_code in (200, 400, 422)  # server reachable
        except httpx.HTTPError:
            return False

    async def health(self) -> EngineHealth:
        if not self._enabled:
            return EngineHealth(status="offline", detail="disabled")
        return EngineHealth(
            status="ok" if await self._is_up() else "offline", detail="")

    async def start(self) -> None:
        if not self._enabled:
            raise EngineUnavailableError("gptsovits: disabled")
        if await self._is_up():
            return
        if self._starting:
            for _ in range(90):
                if await self._is_up():
                    return
                await asyncio.sleep(1)
            raise EngineUnavailableError("gptsovits: startup timed out")
        self._starting = True
        try:
            if self._proc is None or self._proc.returncode is not None:
                api = self._exe / "api_v2.py"
                conf_py = get_settings().gptsovits_python
                venv_py = (conf_py if conf_py.exists()
                           else (self._exe / "venv" / "Scripts" / "python.exe"
                                 if sys.platform == "win32"
                                 else self._exe / "venv" / "bin" / "python"))
                if not api.exists() or not venv_py.exists():
                    raise EngineUnavailableError(
                        "gptsovits: engine not installed "
                        f"(need {venv_py})")
                log.info("starting GPT-SoVITS: %s %s", venv_py, api)
                self._proc = await asyncio.create_subprocess_exec(
                    str(venv_py), str(api), "-a", "127.0.0.1",
                    "-p", str(get_settings().gptsovits_port),
                    cwd=str(self._exe),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
            for _ in range(120):
                if await self._is_up():
                    log.info("GPT-SoVITS up on %s", self._base)
                    return
                if self._proc.returncode is not None:
                    raise EngineUnavailableError(
                        f"gptsovits: exited code {self._proc.returncode}")
                await asyncio.sleep(1)
            raise EngineUnavailableError("gptsovits: startup timed out")
        finally:
            self._starting = False

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except TimeoutError:
                self._proc.kill()
        self._proc = None

    async def list_voices(self) -> list[VoiceInfo]:
        """Clone voices come from the DB, not the engine itself."""
        if not await self._is_up():
            raise EngineUnavailableError("gptsovits offline")
        from app.models.tables import Voice
        with Session(get_engine()) as session:
            samples = session.exec(select(CloneSample)).all()
            voice_map = {
                v.id: v for v in session.exec(
                    select(Voice).where(Voice.engine == self.name)).all()
            }
        out = []
        for s in samples:
            v = voice_map.get(f"{self.name}:{s.id}")
            if v is None or not s.quality_report.get("ok"):
                continue
            out.append(VoiceInfo(
                id=v.id, engine=self.name, engine_voice_id=s.id,
                name=v.name, gender=v.gender,
                styles=["clone"], features=[Feature.CLONING],
                credit="GPT-SoVITS", is_cloned=True,
                is_favorite=v.is_favorite))
        return out

    def _sample(self, engine_voice_id: str) -> CloneSample:
        with Session(get_engine()) as session:
            s = session.get(CloneSample, engine_voice_id)
            if s is None or not s.quality_report.get("ok"):
                raise EngineUnavailableError("gptsovits: clone sample not ready")
            return s

    async def synthesize(self, utterance: Utterance, engine_voice_id: str,
                         settings: SynthesisSettings) -> AudioChunk:
        sample = self._sample(engine_voice_id)
        body = {
            "text": utterance.text,
            "text_lang": "ja",
            "ref_audio_path": sample.audio_path,
            "prompt_text": sample.transcript or "",
            "prompt_lang": "ja",
            "media_type": "wav",
            "streaming_mode": False,
            # speed_factor exists in api_v2
            "speed_factor": max(0.25, min(settings.speed, 4.0)),
        }
        try:
            r = await self._client.post("/tts", json=body, timeout=300.0)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise EngineUnavailableError(f"gptsovits: {e}") from e
        data, sr = sf.read(__import__("io").BytesIO(r.content), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return AudioChunk.from_float32(
            resample(np.asarray(data, dtype=np.float32), int(sr)), TARGET_SR)

    async def synthesize_stream(self, utterance, engine_voice_id, settings):
        # api_v2 supports streaming_mode; keep simple chunk for now
        yield await self.synthesize(utterance, engine_voice_id, settings)
