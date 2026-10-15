"""OpenAI-compatible POST /v1/audio/speech endpoint (spec §5.7).

Accepts any jp-tts voice id in `voice`; OpenAI voice names map to
configurable defaults. `stream: true` returns chunked audio.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.core.audio import TARGET_SR, chunks_to_pcm, encode_mp3, encode_wav, resample
from app.core.config import get_settings
from app.engines.base import SynthesisSettings
from app.engines.router import get_router
from app.text.analyzer import analyze_text
from app.text.dictionary import apply_user_dictionary

log = logging.getLogger("api.openai")
router = APIRouter(tags=["openai-compat"])

FORMATS = {"mp3", "wav", "opus", "flac", "pcm"}

# OpenAI voice names -> jp-tts voice ids (configurable via JPTTS_VOICE_ALIASES?)
DEFAULT_VOICE_ALIASES: dict[str, str] = {}


class SpeechRequest(BaseModel):
    model: str = "jp-tts"
    input: str
    voice: str = ""
    response_format: str = "mp3"
    speed: float = 1.0
    stream: bool = False
    # extra jp-tts settings (ignored by standard clients)
    style: str | None = None
    style_intensity: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0
    intonation: float = 1.0
    pause_scale: float = 1.0


async def _resolve_voice(voice: str) -> str:
    if ":" in voice:
        return voice
    aliases = DEFAULT_VOICE_ALIASES | getattr(get_settings(), "voice_aliases", {})
    if voice in aliases:
        return aliases[voice]
    voices = await get_router().all_voices()
    avail = [v for v in voices if v.available]
    if not avail:
        raise HTTPException(503, detail={"code": "ENGINE_UNAVAILABLE",
                                       "message": "no TTS engines available"})
    return avail[0].id


async def _encode(pcm, sr, fmt: str) -> bytes:
    if fmt == "mp3":
        return await encode_mp3(pcm, sr)
    if fmt == "wav":
        return encode_wav(pcm, sr)
    if fmt == "pcm":
        return (pcm.clip(-1, 1) * 32767).astype("int16").tobytes()
    # opus / flac via ffmpeg
    import asyncio
    wav = encode_wav(pcm, sr)
    codec = "libopus" if fmt == "opus" else "flac"
    proc = await asyncio.create_subprocess_exec(
        str(get_settings().ffmpeg_path), "-y", "-f", "wav", "-i", "pipe:0",
        "-codec:a", codec, "-f", "ogg" if fmt == "opus" else "flac", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate(wav)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg {fmt} encode failed")
    return out


_MEDIA = {"mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg",
          "flac": "audio/flac", "pcm": "application/octet-stream"}


@router.post("/audio/speech")
async def speech(req: SpeechRequest):
    if req.response_format not in FORMATS:
        raise HTTPException(422, detail={"code": "BAD_FORMAT",
                                       "message": f"format must be one of {sorted(FORMATS)}"})
    voice_id = await _resolve_voice(req.voice)
    settings = SynthesisSettings(
        speed=req.speed, pitch=req.pitch, volume=req.volume,
        intonation=req.intonation, pause_scale=req.pause_scale,
        style=req.style, style_intensity=req.style_intensity,
    )
    utterances = apply_user_dictionary(analyze_text(req.input))
    router = get_router()

    if req.stream:
        async def gen():
            for utt in utterances:
                chunk = await router.synthesize(utt, voice_id, settings)
                samples = resample(chunk.to_float32(), chunk.sample_rate, TARGET_SR)
                yield (samples.clip(-1, 1) * 32767).astype("int16").tobytes()
        return StreamingResponse(gen(), media_type="application/octet-stream")

    chunks = [await router.synthesize(u, voice_id, settings) for u in utterances]
    pcm, sr = chunks_to_pcm(chunks)
    data = await _encode(pcm, sr, req.response_format)
    return Response(data, media_type=_MEDIA[req.response_format])
