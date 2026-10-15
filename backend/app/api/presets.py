from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.tables import Preset

router = APIRouter(tags=["presets"])


class PresetIn(BaseModel):
    name: str
    voice_id: str
    settings: dict = {}


@router.get("/presets")
def list_presets(session: Session = Depends(get_session)):
    rows = session.exec(select(Preset).order_by(Preset.name)).all()
    return {"presets": rows}


@router.post("/presets")
def create_preset(body: PresetIn, session: Session = Depends(get_session)):
    row = Preset(**body.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.put("/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetIn,
                  session: Session = Depends(get_session)):
    row = session.get(Preset, preset_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "preset not found"})
    row.name, row.voice_id, row.settings = body.name, body.voice_id, body.settings
    session.add(row)
    session.commit()
    return row


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, session: Session = Depends(get_session)):
    row = session.get(Preset, preset_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "preset not found"})
    session.delete(row)
    session.commit()
    return {"deleted": preset_id}
