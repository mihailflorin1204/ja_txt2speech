from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.db import get_session
from app.models.tables import Generation

router = APIRouter(tags=["history"])


@router.get("/history")
def history(session: Session = Depends(get_session), limit: int = 50):
    limit = min(limit, get_settings().history_limit)
    rows = session.exec(
        select(Generation).order_by(Generation.id.desc()).limit(limit)
    ).all()
    return {
        "generations": [
            {
                "id": r.id,
                "text": r.text,
                "voice_id": r.voice_id,
                "settings": r.settings,
                "format": r.format,
                "duration_s": r.duration_s,
                "audio_url": f"/api/v1/files/{Path(r.audio_path).name}",
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }


@router.delete("/history/{gen_id}")
def delete_history(gen_id: int, session: Session = Depends(get_session)):
    row = session.get(Generation, gen_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "generation not found"})
    Path(row.audio_path).unlink(missing_ok=True)
    session.delete(row)
    session.commit()
    return {"deleted": gen_id}


@router.get("/files/{filename}")
def serve_file(filename: str):
    path = get_settings().audio_dir / Path(filename).name
    if not path.exists() or path.suffix.lower() not in {".wav", ".mp3"}:
        raise HTTPException(404, detail={"code": "FILE_NOT_FOUND",
                                       "message": "no such file"})
    media = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media, filename=path.name)
