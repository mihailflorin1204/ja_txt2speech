"""Audio encode/decode helpers: PCM handling, WAV/MP3 output via ffmpeg."""

import asyncio
import io
import logging
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from app.core.config import get_settings
from app.engines.base import AudioChunk

log = logging.getLogger("core.audio")

TARGET_SR = 44100


def resample(samples: np.ndarray, src_sr: int, dst_sr: int = TARGET_SR) -> np.ndarray:
    if src_sr == dst_sr:
        return samples
    # linear interpolation resample - adequate for speech; engines give 24-48k
    ratio = dst_sr / src_sr
    out_len = int(round(len(samples) * ratio))
    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=out_len, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def chunks_to_pcm(chunks: list[AudioChunk], pause_ms: int = 0) -> tuple[np.ndarray, int]:
    """Concatenate chunks (resampled to 44.1k mono) with optional inter-chunk pause."""
    parts = []
    for chunk in chunks:
        samples = chunk.to_float32()
        samples = resample(samples, chunk.sample_rate)
        parts.append(samples)
        if pause_ms:
            parts.append(np.zeros(int(TARGET_SR * pause_ms / 1000), dtype=np.float32))
    if parts and pause_ms:
        parts.pop()
    pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return pcm, TARGET_SR


def encode_wav(samples: np.ndarray, sample_rate: int = TARGET_SR) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _find_ffmpeg() -> str:
    exe = get_settings().ffmpeg_path
    if exe.exists():
        return str(exe)
    return "ffmpeg"  # hope it's on PATH


async def encode_mp3(samples: np.ndarray, sample_rate: int = TARGET_SR,
                     bitrate: str = "192k") -> bytes:
    wav = encode_wav(samples, sample_rate)
    proc = await asyncio.create_subprocess_exec(
        _find_ffmpeg(), "-y", "-f", "wav", "-i", "pipe:0",
        "-codec:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate(wav)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg mp3 encode failed")
    return out


def encode_mp3_sync(samples: np.ndarray, sample_rate: int = TARGET_SR,
                    bitrate: str = "192k") -> bytes:
    wav = encode_wav(samples, sample_rate)
    proc = subprocess.run(
        [_find_ffmpeg(), "-y", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", "pipe:1"],
        input=wav, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mp3 encode failed: {proc.stderr[:500]}")
    return proc.stdout


def save_wav(path: Path, samples: np.ndarray, sample_rate: int = TARGET_SR) -> Path:
    sf.write(str(path), samples, sample_rate, format="WAV", subtype="PCM_16")
    return path


async def pitch_shift_pcm(chunk: AudioChunk, semitones: float) -> AudioChunk:
    """Pitch-shift via ffmpeg asetrate+atempo (tempo preserved). Used for
    engines without a native pitch parameter (SBV2, GPT-SoVITS)."""
    factor = 2.0 ** (semitones / 12.0)
    samples = chunk.to_float32()
    wav = encode_wav(samples, chunk.sample_rate)
    proc = await asyncio.create_subprocess_exec(
        _find_ffmpeg(), "-y", "-f", "wav", "-i", "pipe:0",
        "-af",
        f"asetrate={chunk.sample_rate}*{factor:.6f},"
        f"aresample={chunk.sample_rate},atempo={1 / factor:.6f}",
        "-f", "wav", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate(wav)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg pitch shift failed")
    shifted, _ = sf.read(io.BytesIO(out), dtype="float32")
    return AudioChunk.from_float32(shifted, chunk.sample_rate, chunk.sentence_index)
