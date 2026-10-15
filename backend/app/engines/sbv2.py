import asyncio
import io
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from app.core.audio import pitch_shift_pcm
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

log = logging.getLogger("engine.sbv2")

FEATURES = [
    Feature.STYLE,
    Feature.ACCENT_EDIT,
    Feature.PITCH,
    Feature.SPEED,
]


def _voice_ref(model_name: str, speaker: str | None) -> str:
    return f"{model_name}:{speaker}" if speaker else model_name


class Sbv2Engine:
    """Style-Bert-VITS2 via its bundled server_fastapi.py, run in the engine's
    own venv as a subprocess (it pins torch<2.4, incompatible with backend)."""

    id = "sbv2"

    def __init__(self) -> None:
        s = get_settings()
        self._base = f"http://{s.sbv2_host}:{s.sbv2_port}"
        self._repo = s.sbv2_repo
        self._python = s.sbv2_python
        self._proc: asyncio.subprocess.Process | None = None
        self._client = httpx.AsyncClient(base_url=self._base, timeout=180.0)
        self._starting = False

    async def start(self) -> None:
        if await self._is_up():
            return
        if not self._python.exists() or not (self._repo / "server_fastapi.py").exists():
            raise EngineUnavailableError(
                f"Style-Bert-VITS2 not installed (expected {self._python} and "
                f"{self._repo / 'server_fastapi.py'})"
            )
        self._starting = True
        try:
            self._proc = await asyncio.create_subprocess_exec(
                str(self._python), "server_fastapi.py",
                cwd=str(self._repo),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            log.info("spawned SBV2 server pid=%s", self._proc.pid)
            await self._wait_ready(timeout=180.0)
            await self._client.post("/models/refresh")
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
            r = await self._client.get("/status", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def _wait_ready(self, timeout: float) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                raise EngineUnavailableError(
                    f"SBV2 server exited with code {self._proc.returncode}")
            if await self._is_up():
                return
            await asyncio.sleep(2.0)
        raise EngineUnavailableError("SBV2 server did not become ready in time")

    async def health(self) -> EngineHealth:
        if self._starting:
            return EngineHealth(status="starting")
        if await self._is_up():
            return EngineHealth(status="ok")
        return EngineHealth(status="offline", detail="SBV2 server not responding")

    def supports(self, feature: Feature) -> bool:
        return feature in FEATURES

    async def _models_info(self) -> dict:
        r = await self._client.get("/models/info")
        r.raise_for_status()
        return r.json()

    async def list_voices(self) -> list[VoiceInfo]:
        if not await self._is_up():
            raise EngineUnavailableError("SBV2 offline")
        voices: list[VoiceInfo] = []
        for meta in (await self._models_info()).values():
            # model name = directory name under model_assets (config.json's parent)
            model_name = Path(meta["config_path"]).parent.name
            styles = list((meta.get("style2id") or {}).keys())
            speakers = list((meta.get("spk2id") or {}).keys())
            if len(speakers) <= 1:
                voices.append(VoiceInfo(
                    id=f"sbv2:{model_name}", engine=self.id,
                    engine_voice_id=_voice_ref(model_name, None),
                    name=model_name, styles=styles, features=FEATURES,
                    credit="Style-Bert-VITS2",
                ))
            else:
                for spk in speakers:
                    voices.append(VoiceInfo(
                        id=f"sbv2:{_voice_ref(model_name, spk)}",
                        engine=self.id,
                        engine_voice_id=_voice_ref(model_name, spk),
                        name=f"{model_name}（{spk}）",
                        styles=styles, features=FEATURES,
                        credit="Style-Bert-VITS2",
                    ))
        return voices

    async def synthesize(
        self, utterance: Utterance, voice_id: str, settings: SynthesisSettings
    ) -> AudioChunk:
        model_name, _, speaker = voice_id.partition(":")
        params: dict[str, str | float | int] = {
            "text": utterance.text,
            "encoding": "utf-8",
            "model_name": model_name,
            "sdp_ratio": 0.2,
            "noise": 0.6,
            "noisew": 0.8,
            "length": 1.0 / max(settings.speed, 1e-3),
            "language": "JP",
            "auto_split": True,
            "split_interval": 0.5,
            "assist_text_weight": 0.0,
            "style": settings.style or "Neutral",
            "style_weight": settings.style_intensity,
        }
        if speaker:
            params["speaker_name"] = speaker
        else:
            params["speaker_id"] = 0
        r = await self._client.post("/voice", params=params)
        r.raise_for_status()
        chunk = self._decode_wav(r.content)
        if settings.pitch != 0.0:
            chunk = await pitch_shift_pcm(chunk, settings.pitch)
        return chunk

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
