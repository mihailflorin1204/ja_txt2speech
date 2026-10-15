import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from app.core.audio import chunks_to_pcm, encode_mp3, encode_wav, save_wav
from app.core.config import get_settings
from app.core.db import get_session
from app.engines.base import SynthesisSettings, Utterance
from app.engines.router import get_router
from app.models.tables import Generation
from app.text.analyzer import analyze_text
from app.text.dictionary import apply_user_dictionary

log = logging.getLogger("api.synth")
router = APIRouter(tags=["synthesis"])


class AnalyzeRequest(BaseModel):
    text: str
    voice_id: str | None = None


class SynthesizeRequest(BaseModel):
    text: str | None = None
    utterances: list[Utterance] | None = None
    voice_id: str
    settings: SynthesisSettings = SynthesisSettings()
    format: str = "wav"  # wav | mp3


def _utterance_view(utt: Utterance) -> dict:
    return utt.model_dump()


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    utterances = analyze_text(req.text)
    utterances = apply_user_dictionary(utterances)
    return {"sentences": [_utterance_view(u) for u in utterances]}


@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest, session: Session = Depends(get_session)):
    settings = get_settings()
    if req.utterances:
        utterances = req.utterances
        text = "".join(u.text for u in utterances)
    elif req.text:
        if len(req.text) > settings.max_interactive_chars:
            raise HTTPException(422, detail={
                "code": "LONG_TEXT",
                "message": f"Interactive synthesis is limited to "
                           f"{settings.max_interactive_chars} characters; "
                           f"create a long-text job instead.",
            })
        text = req.text
        utterances = apply_user_dictionary(analyze_text(req.text))
    else:
        raise HTTPException(400, detail={"code": "EMPTY_INPUT",
                                       "message": "provide text or utterances"})

    router = get_router()
    start = time.perf_counter()
    chunks = []
    for i, utt in enumerate(utterances):
        eff = req.settings.merged_with(utt.settings)
        chunk = await router.synthesize(utt, req.voice_id, eff)
        chunk.sentence_index = i
        chunks.append(chunk)
    elapsed = time.perf_counter() - start

    pause_ms = 0  # engine handles intra-query pauses; inter-sentence pause below
    pcm, sr = chunks_to_pcm(chunks, pause_ms=pause_ms)
    duration = len(pcm) / sr
    log.info("synthesized %d sentences in %.2fs (rtf=%.2f)", len(chunks), elapsed,
             elapsed / max(duration, 1e-3),
             extra={"engine": req.voice_id.split(":")[0], "voice": req.voice_id,
                    "duration_s": round(elapsed, 3)})

    fmt = req.format.lower()
    if fmt == "mp3":
        data = await encode_mp3(pcm, sr)
        media_type = "audio/mpeg"
    elif fmt == "wav":
        data = encode_wav(pcm, sr)
        media_type = "audio/wav"
    else:
        raise HTTPException(422, detail={"code": "BAD_FORMAT",
                                       "message": f"unsupported format: {fmt}"})

    # history record
    audio_path = settings.audio_dir / f"{uuid.uuid4().hex}.wav"
    save_wav(audio_path, pcm, sr)
    session.add(Generation(text=text, voice_id=req.voice_id,
                           settings=req.settings.model_dump(),
                           audio_path=str(audio_path), format=fmt,
                           duration_s=duration))
    session.commit()

    return Response(data, media_type=media_type)
