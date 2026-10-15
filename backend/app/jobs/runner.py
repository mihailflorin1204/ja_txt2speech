"""Adapter between the job queue and the synthesis pipeline.

synthesize_for_job(text, voice_id, settings) -> (float32 PCM @44.1kHz, sr)
"""

import numpy as np

from app.core.audio import TARGET_SR, resample
from app.engines.base import SynthesisSettings
from app.engines.router import get_router
from app.text.analyzer import analyze_sentence


async def synthesize_for_job(
    text: str, voice_id: str, settings: SynthesisSettings
) -> tuple[np.ndarray, int]:
    utterance = analyze_sentence(text)
    chunk = await get_router().synthesize(utterance, voice_id, settings)
    samples = resample(chunk.to_float32(), chunk.sample_rate, TARGET_SR)
    return samples, TARGET_SR
