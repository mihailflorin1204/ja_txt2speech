import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from app.core.audio import encode_mp3
from app.core.config import get_settings
from app.core.db import get_session
from app.engines.base import SynthesisSettings
from app.engines.router import get_router, split_voice_id
from app.models.tables import CloneSample, Voice

log = logging.getLogger("api.voices")
router = APIRouter(tags=["voices"])


class VoicePatch(BaseModel):
    name: str | None = None
    is_favorite: bool | None = None


async def _catalog() -> dict:
    return {v.id: v for v in await get_router().all_voices()}


def _row_for(voice_id: str, session: Session, info=None) -> Voice:
    row = session.get(Voice, voice_id)
    if row is None:
        engine, evoice = split_voice_id(voice_id)
        row = Voice(
            id=voice_id, engine=engine, engine_voice_id=evoice,
            name=info.name if info else voice_id,
            styles=[{"name": s} for s in (info.styles if info else [])],
            features=[f.value for f in (info.features if info else [])],
            credit=info.credit if info else "",
        )
        session.add(row)
    return row


@router.get("/voices")
async def list_voices(
    engine: str | None = None,
    gender: str | None = None,
    style: str | None = None,
    cloned: bool | None = None,
):
    voices = await get_router().all_voices()
    if engine:
        voices = [v for v in voices if v.engine == engine]
    if gender:
        voices = [v for v in voices if v.gender == gender]
    if style:
        voices = [v for v in voices if style in v.styles]
    if cloned is not None:
        voices = [v for v in voices if v.is_cloned == cloned]
    voices.sort(key=lambda v: (not v.is_favorite, v.engine, v.name))
    return {"voices": [v.model_dump() for v in voices]}


@router.get("/voices/{voice_id}")
async def get_voice(voice_id: str):
    info = (await _catalog()).get(voice_id)
    if info is None:
        raise HTTPException(404, detail={"code": "VOICE_NOT_FOUND",
                                       "message": f"unknown voice: {voice_id}"})
    return info.model_dump()


@router.get("/voices/{voice_id}/preview")
async def voice_preview(voice_id: str, session: Session = Depends(get_session)):
    settings = get_settings()
    preview_path = settings.previews_dir / f"{voice_id.replace(':', '_')}.mp3"
    if preview_path.exists():
        return Response(preview_path.read_bytes(), media_type="audio/mpeg")

    info = (await _catalog()).get(voice_id)
    if info is None:
        raise HTTPException(404, detail={"code": "VOICE_NOT_FOUND",
                                       "message": f"unknown voice: {voice_id}"})
    if not info.available:
        raise HTTPException(503, detail={"code": "ENGINE_UNAVAILABLE",
                                       "message": f"engine {info.engine} is offline"})

    from app.text.analyzer import analyze_sentence

    utterance = analyze_sentence(settings.preview_text)
    chunk = await get_router().synthesize(utterance, voice_id, SynthesisSettings())
    mp3 = await encode_mp3(chunk.to_float32(), chunk.sample_rate)
    preview_path.write_bytes(mp3)
    return Response(mp3, media_type="audio/mpeg")


@router.patch("/voices/{voice_id}")
async def patch_voice(voice_id: str, patch: VoicePatch,
                      session: Session = Depends(get_session)):
    info = (await _catalog()).get(voice_id)
    if info is None and session.get(Voice, voice_id) is None:
        raise HTTPException(404, detail={"code": "VOICE_NOT_FOUND",
                                       "message": f"unknown voice: {voice_id}"})
    row = _row_for(voice_id, session, info)
    if patch.name is not None:
        if not row.is_cloned:
            raise HTTPException(403, detail={"code": "RENAME_FORBIDDEN",
                                           "message": "only cloned voices can be renamed"})
        row.name = patch.name
    if patch.is_favorite is not None:
        row.is_favorite = patch.is_favorite
    session.add(row)
    session.commit()
    return {"id": voice_id, "name": row.name, "is_favorite": row.is_favorite}


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str, session: Session = Depends(get_session)):
    row = session.get(Voice, voice_id)
    if row is None or not row.is_cloned:
        raise HTTPException(403, detail={"code": "DELETE_FORBIDDEN",
                                       "message": "only cloned voices can be deleted"})
    # FR-5.6: deleting a cloned voice removes all associated files
    sample = session.get(CloneSample, row.engine_voice_id)
    if sample is not None:
        Path(sample.audio_path).unlink(missing_ok=True)
        session.delete(sample)
    if row.model_path:
        Path(row.model_path).unlink(missing_ok=True)
    preview = (get_settings().previews_dir
               / f"{voice_id.replace(':', '_')}.mp3")
    preview.unlink(missing_ok=True)
    session.delete(row)
    session.commit()
    return {"deleted": voice_id}
