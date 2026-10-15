import csv
import io
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.tables import DictionaryEntry

log = logging.getLogger("api.dictionary")
router = APIRouter(tags=["dictionary"])


class EntryIn(BaseModel):
    surface: str
    reading: str
    accent_type: int | None = None
    pos: str = ""
    priority: int = 0


@router.get("/dictionary")
def list_entries(
    session: Session = Depends(get_session),
    q: str | None = Query(default=None),
    offset: int = 0,
    limit: int = Query(default=100, le=500),
):
    stmt = select(DictionaryEntry)
    if q:
        stmt = stmt.where(DictionaryEntry.surface.contains(q))
    stmt = stmt.order_by(DictionaryEntry.surface).offset(offset).limit(limit)
    rows = session.exec(stmt).all()
    total = session.exec(select(DictionaryEntry)).all()
    return {"entries": rows, "total": len(total)}


@router.post("/dictionary", status_code=201)
def create_entry(body: EntryIn, session: Session = Depends(get_session)):
    row = DictionaryEntry(**body.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.put("/dictionary/{entry_id}")
def update_entry(entry_id: int, body: EntryIn,
                 session: Session = Depends(get_session)):
    row = session.get(DictionaryEntry, entry_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "entry not found"})
    for f, v in body.model_dump().items():
        setattr(row, f, v)
    row.updated_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    return row


@router.delete("/dictionary/{entry_id}")
def delete_entry(entry_id: int, session: Session = Depends(get_session)):
    row = session.get(DictionaryEntry, entry_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "entry not found"})
    session.delete(row)
    session.commit()
    return {"deleted": entry_id}


@router.post("/dictionary/import")
async def import_entries(file: UploadFile,
                         session: Session = Depends(get_session)):
    """Import CSV or JSON. CSV columns: surface,reading,accent_type,pos,priority."""
    raw = await file.read()
    name = (file.filename or "").lower()
    created = 0
    try:
        if name.endswith(".json"):
            items = json.loads(raw.decode("utf-8"))
            if isinstance(items, dict):
                items = items.get("entries", [])
            entries = [EntryIn(**i) for i in items]
        else:
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            entries = [
                EntryIn(
                    surface=r["surface"], reading=r["reading"],
                    accent_type=int(r["accent_type"]) if r.get("accent_type") else None,
                    pos=r.get("pos", ""), priority=int(r.get("priority") or 0),
                )
                for r in reader
            ]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, detail={"code": "BAD_IMPORT",
                                       "message": f"could not parse file: {e}"}) from e

    for e in entries:
        existing = session.exec(
            select(DictionaryEntry).where(DictionaryEntry.surface == e.surface)
        ).first()
        if existing:
            for f, v in e.model_dump().items():
                setattr(existing, f, v)
            session.add(existing)
        else:
            session.add(DictionaryEntry(**e.model_dump()))
        created += 1
    session.commit()
    return {"imported": created}


@router.get("/dictionary/export")
def export_entries(format: str = "csv",
                   session: Session = Depends(get_session)):
    rows = session.exec(
        select(DictionaryEntry).order_by(DictionaryEntry.surface)).all()
    if format == "json":
        data = json.dumps(
            {"entries": [r.model_dump(exclude={"id"}) for r in rows]},
            ensure_ascii=False, indent=2).encode("utf-8")
        return Response(data, media_type="application/json",
                        headers={"Content-Disposition":
                                 "attachment; filename=dictionary.json"})
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["surface", "reading", "accent_type", "pos", "priority"])
    for r in rows:
        writer.writerow([r.surface, r.reading,
                         r.accent_type if r.accent_type is not None else "",
                         r.pos, r.priority])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=dictionary.csv"})
