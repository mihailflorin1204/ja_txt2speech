from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Protocol

import numpy as np
from pydantic import BaseModel


class Feature(StrEnum):
    STYLE = "style"
    ACCENT_EDIT = "accent_edit"
    PITCH = "pitch"
    SPEED = "speed"
    INTONATION = "intonation"
    STREAMING = "streaming"
    CLONING = "cloning"


class Mora(BaseModel):
    """A single mora within an accent phrase."""

    text: str  # surface text this mora belongs to (the word's surface)
    kana: str  # mora reading in katakana, e.g. "キョ"
    consonant: str | None = None
    vowel: str = ""
    pitch: float = 0.0  # relative pitch (engine-specific interpretation)


class AccentPhrase(BaseModel):
    moras: list[Mora]
    accent: int  # accent nucleus position (1-based mora index; len(moras) => flat)
    pause_after_ms: int = 0
    is_interrogative: bool = False


class SynthesisSettings(BaseModel):
    speed: float = 1.0  # 0.5 - 2.0
    pitch: float = 0.0  # semitones, -12..+12
    volume: float = 1.0  # 0.0 - 2.0
    intonation: float = 1.0  # 0.0 - 2.0
    pause_scale: float = 1.0  # 0.0 - 3.0
    style: str | None = None  # e.g. "happy"
    style_intensity: float = 1.0  # 0.0 - 1.0

    def merged_with(self, override: "SynthesisSettings | None") -> "SynthesisSettings":
        """Per-sentence override: fields explicitly set on override win."""
        if override is None:
            return self
        base = self.model_dump()
        for f, v in override.model_dump(exclude_unset=True).items():
            base[f] = v
        return SynthesisSettings(**base)


class Utterance(BaseModel):
    """Engine-neutral unit of synthesis: one sentence."""

    text: str
    accent_phrases: list[AccentPhrase] = []
    settings: SynthesisSettings | None = None  # per-sentence override (FR-3.3)


class VoiceInfo(BaseModel):
    id: str  # "{engine}:{engine_voice_id}"
    engine: str
    engine_voice_id: str
    name: str
    gender: str = "unknown"
    styles: list[str] = []
    features: list[Feature] = []
    credit: str = ""
    is_cloned: bool = False
    is_favorite: bool = False
    available: bool = True


class EngineHealth(BaseModel):
    status: str  # "ok" | "starting" | "offline" | "error"
    detail: str = ""


class AudioChunk(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    pcm: bytes  # PCM s16le mono
    sample_rate: int
    sentence_index: int = 0

    def to_float32(self) -> np.ndarray:
        return np.frombuffer(self.pcm, dtype=np.int16).astype(np.float32) / 32768.0

    @classmethod
    def from_float32(cls, samples: np.ndarray, sample_rate: int, sentence_index: int = 0):
        clipped = np.clip(samples, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16).tobytes()
        return cls(pcm=pcm, sample_rate=sample_rate, sentence_index=sentence_index)


class EngineUnavailableError(RuntimeError):
    pass


class TTSEngine(Protocol):
    id: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> EngineHealth: ...
    async def list_voices(self) -> list[VoiceInfo]: ...
    def supports(self, feature: Feature) -> bool: ...
    async def synthesize(
        self, utterance: Utterance, voice_id: str, settings: SynthesisSettings
    ) -> AudioChunk: ...
    def synthesize_stream(
        self, utterances: list[Utterance], voice_id: str, settings: SynthesisSettings
    ) -> AsyncIterator[AudioChunk]: ...
