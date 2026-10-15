"""Voice cloning endpoints (spec §5.5): sample upload, quality checks,
transcript, consent gate, quick vs fine-tune modes."""

import io
import logging
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.db import get_engine, get_session
from app.models.tables import CloneSample

log = logging.getLogger("api.clone")
router = APIRouter(tags=["clone"])

MIN_S = 3.0
MAX_S = 30.0


def _quality_check(path: Path) -> dict:
    """Basic checks: duration, silence ratio, clipping, sample rate."""
    samples, sr = sf.read(str(path), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    dur = len(samples) / sr
    silence = float(np.mean(np.abs(samples) < 0.001)) if len(samples) else 1.0
    clip = float(np.mean(np.abs(samples) > 0.99)) if len(samples) else 0.0
    issues = []
    if dur < MIN_S:
        issues.append(f"too short ({dur:.1f}s, need >= {MIN_S}s)")
    if dur > MAX_S:
        issues.append(f"too long ({dur:.1f}s, need <= {MAX_S}s)")
    if silence > 0.5:
        issues.append("mostly silence")
    if clip > 0.01:
        issues.append("clipping detected")
    if sr < 16000:
        issues.append(f"sample rate too low ({sr} Hz)")
    return {"duration_s": round(dur, 2), "sample_rate": sr,
            "silence_pct": round(silence * 100, 1),
            "clipping_pct": round(clip * 100, 2),
            "ok": not issues, "issues": issues}


@router.post("/clone/samples", status_code=201)
async def upload_sample(
    file: UploadFile = File(...),
    name: str = Form("My clone"),
    transcript: str = Form(""),
    consent: bool = Form(False),
    session: Session = Depends(get_session),
):
    """Consent is required (spec FR-8.1): user must confirm they own rights."""
    if not consent:
        raise HTTPException(422, detail={
            "code": "CONSENT_REQUIRED",
            "message": "consent required: you must own the voice or have permission"})
    raw = await file.read()
    try:
        samples, sr = sf.read(io.BytesIO(raw), dtype="float32")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, detail={"code": "BAD_AUDIO",
                                       "message": f"not a readable audio file: {e}"}) from e

    cid = get_settings().data_dir / "clones"
    cid.mkdir(parents=True, exist_ok=True)
    path = cid / f"{__import__('uuid').uuid4().hex}.wav"
    save_wav32(path, samples, sr)

    qc = _quality_check(path)
    status = "ready" if qc["ok"] else "rejected"
    row = CloneSample(name=name, audio_path=str(path), transcript=transcript,
                      duration_s=qc["duration_s"], status=status,
                      quality=qc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "status": status, "quality": qc}


def save_wav32(path: Path, samples: np.ndarray, sr: int) -> None:
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    sf.write(str(path), samples, sr, subtype="PCM_16")


@router.get("/clone/samples")
def list_samples(session: Session = Depends(get_session)):
    rows = session.exec(select(CloneSample).order_by(CloneSample.id.desc())).all()
    return {"samples": rows}


@router.get("/clone/samples/{sample_id}/audio")
def sample_audio(sample_id: int, session: Session = Depends(get_session)):
    row = session.get(CloneSample, sample_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "sample not found"})
    return FileResponse(row.audio_path, media_type="audio/wav")


@router.delete("/clone/samples/{sample_id}")
def delete_sample(sample_id: int, session: Session = Depends(get_session)):
    row = session.get(CloneSample, sample_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "sample not found"})
    Path(row.audio_path).unlink(missing_ok=True)
    session.delete(row)
    session.commit()
    return {"deleted": sample_id}


@router.post("/clone/samples/{sample_id}/transcribe")
async def transcribe(sample_id: int, session: Session = Depends(get_session)):
    """Whisper transcription (FR-8.2) — run lazily on demand."""
    row = session.get(CloneSample, sample_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "sample not found"})
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise HTTPException(503, detail={
            "code": "NO_WHISPER",
            "message": "faster-whisper not installed in backend venv"}) from e
    model = WhisperModel("small", device="auto")
    segments, _ = model.transcribe(row.audio_path, language="ja")
    text = "".join(s.text for s in segments).strip()
    row.transcript = text
    session.add(row)
    session.commit()
    return {"transcript": text}


class CloneCreateBody(BaseModel):
    sample_id: int
    mode: str = "quick"  # quick | finetune
    voice_name: str | None = None


@router.post("/clone", status_code=201)
async def create_clone(body: CloneCreateBody):
    """Create a clone voice from a sample (spec FR-8.3).

    quick: zero/few-shot — voice becomes usable immediately.
    finetune: queued training job (M5 full implementation).
    """
    with Session(get_engine()) as session:
        sample = session.get(CloneSample, body.sample_id)
        if sample is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND",
                                           "message": "sample not found"})
        if sample.status != "ready":
            raise HTTPException(422, detail={"code": "SAMPLE_REJECTED",
                                           "message": "sample failed quality checks"})
        if body.mode == "quick":
            sample.status = "ready"  # usable via gptsovits engine voice
            if body.voice_name:
                sample.name = body.voice_name
            session.add(sample)
            session.commit()
            return {"sample_id": sample.id, "mode": "quick",
                    "voice_id": f"gptsovits:{sample.id}"}
        # finetune: register as a job
        from app.jobs import queue as jq
        job = jq.create_job(
            "clone_finetune", None, {},
            [], [{"chapter_index": 0, "sentence_index": 0,
                  "text": f"finetune:{sample.id}"}], {})
        sample.status = "queued"
        session.add(sample)
        session.commit()
        return {"sample_id": sample.id, "mode": "finetune", "job_id": job.id}
