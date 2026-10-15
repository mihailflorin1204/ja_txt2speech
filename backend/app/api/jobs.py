"""Long-text job endpoints (spec §5.6). Accepts multipart file upload or JSON."""

import json as _json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.db import get_session
from app.jobs import queue as jq
from app.jobs.input import parse_input
from app.models.tables import Job, JobSentence
from app.text.splitter import split_sentences

log = logging.getLogger("api.jobs")
router = APIRouter(tags=["jobs"])

MAX_TEXT_CHARS = 1_000_000


class JobCreateJSON(BaseModel):
    text: str | None = None
    voice_id: str
    settings: dict = {}
    export_options: dict = {"format": "mp3", "mode": "per_chapter",
                            "m4b": False, "srt": True}
    chapters: list[dict] | None = None  # manual splits [{title, text}]


async def _parse_job_input(request: Request) -> tuple[list[dict], dict]:
    """Returns (chapters[{title,text}], fields{voice_id,settings,export_options,...})."""
    ct = request.headers.get("content-type", "")
    if ct.startswith("multipart/"):
        form = await request.form()
        file = form.get("file")
        fields = {
            "voice_id": form.get("voice_id"),
            "settings": _json.loads(str(form.get("settings") or "{}")),
            "export_options": _json.loads(
                str(form.get("export_options") or "{}")),
        }
        if file is None:
            text = form.get("text")
            if text is None:
                raise HTTPException(400, detail={"code": "EMPTY_INPUT",
                                               "message": "no file or text"})
            chapters = parse_input(None, None, str(text))
        else:
            chapters = parse_input(getattr(file, "filename", None),
                                   await file.read(), None)
        return ([{"title": c.title, "text": c.text} for c in chapters], fields)

    body = _json.loads(await request.body())
    req = JobCreateJSON(**body)
    if req.chapters:
        chapters = req.chapters
    elif req.text is not None:
        if len(req.text) > MAX_TEXT_CHARS:
            raise HTTPException(422, detail={"code": "TOO_LONG",
                                           "message": "max 1,000,000 characters"})
        chapters = [{"title": c.title, "text": c.text}
                    for c in parse_input(None, None, req.text)]
    else:
        raise HTTPException(400, detail={"code": "EMPTY_INPUT",
                                       "message": "provide text or chapters"})
    return chapters, {
        "voice_id": req.voice_id,
        "settings": req.settings,
        "export_options": req.export_options,
    }


@router.post("/jobs/preview")
async def preview_splits(request: Request):
    """Detect chapter splits for review before creating a job (FR-7.2)."""
    chapters, _ = await _parse_job_input(request)
    n_sent = sum(len(split_sentences(c["text"], keep_punct=False))
                 for c in chapters)
    return {
        "chapters": [{"title": c["title"],
                      "text": c["text"][:200] + ("…" if len(c["text"]) > 200 else ""),
                      "chars": len(c["text"])} for c in chapters],
        "total_chars": sum(len(c["text"]) for c in chapters),
        "total_sentences": n_sent,
    }


@router.post("/jobs", status_code=201)
async def create_job(request: Request):
    chapters, fields = await _parse_job_input(request)
    voice_id = fields.get("voice_id")
    if not voice_id:
        raise HTTPException(400, detail={"code": "NO_VOICE",
                                       "message": "voice_id required"})
    sentences = []
    for ci, ch in enumerate(chapters):
        for si, s in enumerate(split_sentences(ch["text"], keep_punct=False)):
            sentences.append({"chapter_index": ci, "sentence_index": si,
                              "text": s})
    job = jq.create_job("long_text", voice_id, fields.get("settings", {}),
                        chapters, sentences, fields.get("export_options", {}))
    await jq.enqueue(job.id)
    return {"job_id": job.id, "total_sentences": job.total_sentences}


@router.get("/jobs")
def list_jobs(session: Session = Depends(get_session)):
    rows = session.exec(select(Job).order_by(Job.created_at.desc()).limit(100)).all()
    return {"jobs": [_job_view(j) for j in rows]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "job not found"})
    failed = session.exec(select(JobSentence).where(
        JobSentence.job_id == job_id, JobSentence.status == "failed")).all()
    eta = None
    if job.status == "running" and job.done_sentences > 0:
        done_rows = session.exec(select(JobSentence).where(
            JobSentence.job_id == job_id, JobSentence.status == "done")).all()
        avg = sum(s.duration_s or 0 for s in done_rows) / max(len(done_rows), 1)
        eta = round((job.total_sentences - job.done_sentences) * avg, 1)
    return {**_job_view(job),
            "eta_seconds": eta,
            "failed_sentences": [{"id": s.id, "text": s.text,
                                  "attempts": s.attempts} for s in failed]}


def _job_view(j: Job) -> dict:
    return {
        "id": j.id, "kind": j.kind, "status": j.status,
        "voice_id": j.voice_id,
        "progress": {"done": j.done_sentences, "total": j.total_sentences},
        "error": j.error, "created_at": j.created_at, "updated_at": j.updated_at,
    }


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    await jq.pause(job_id)
    return {"status": "paused"}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    await jq.resume(job_id)
    return {"status": "queued"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    await jq.cancel(job_id)
    return {"status": "cancelled"}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    n = await jq.retry_failed(job_id)
    return {"requeued": n}


@router.get("/jobs/{job_id}/outputs")
def job_outputs(job_id: str):
    out_dir = get_settings().data_dir / "jobs" / job_id / "outputs"
    if not out_dir.exists():
        return {"outputs": []}
    return {"outputs": [{"name": f.name,
                         "url": f"/api/v1/jobs/{job_id}/outputs/{f.name}",
                         "size": f.stat().st_size}
                        for f in sorted(out_dir.iterdir())
                        if f.name not in ("concat.txt", "chapters.ffmeta")
                        and not f.name.startswith("_tmp_")]}


@router.get("/jobs/{job_id}/outputs/{filename}")
def download_output(job_id: str, filename: str):
    out_dir = get_settings().data_dir / "jobs" / job_id / "outputs"
    path = out_dir / Path(filename).name
    if not path.exists():
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                       "message": "no such output"})
    media = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4b": "audio/mp4",
             "srt": "text/plain", "vtt": "text/vtt"}.get(
        path.suffix.lower().lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)
