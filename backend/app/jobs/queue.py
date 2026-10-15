"""Asyncio job queue with SQLite-backed checkpoints (spec §4.2, FR-7.3).

One in-process worker drains queued jobs sentence by sentence, persisting
progress to JobSentence rows so jobs survive restarts.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.db import get_engine
from app.engines.base import SynthesisSettings
from app.models.tables import Job, JobSentence

log = logging.getLogger("jobs.queue")

MAX_ATTEMPTS = 3

_queue: asyncio.Queue[str] | None = None
_worker_task: asyncio.Task | None = None
_current_cancel: asyncio.Event | None = None
_current_pause: asyncio.Event | None = None


_queue_loop: asyncio.AbstractEventLoop | None = None


def _get_queue() -> asyncio.Queue:
    """Lazy-create the queue inside the running loop (avoids cross-loop binding)."""
    global _queue, _queue_loop
    loop = asyncio.get_event_loop()
    if _queue is None or _queue_loop is not loop:
        _queue = asyncio.Queue()
        _queue_loop = loop
    return _queue


def create_job(kind: str, voice_id: str | None, settings: dict,
               chapters: list[dict], sentences: list[dict],
               export_options: dict) -> Job:
    """Persist a job + its sentences. sentences: [{chapter_index, sentence_index, text}]."""
    job = Job(id=uuid.uuid4().hex, kind=kind, voice_id=voice_id,
              settings=settings, chapters=chapters,
              export_options=export_options, total_sentences=len(sentences))
    with Session(get_engine()) as session:
        session.add(job)
        session.flush()
        for s in sentences:
            session.add(JobSentence(
                job_id=job.id, chapter_index=s["chapter_index"],
                sentence_index=s["sentence_index"], text=s["text"]))
        session.commit()
        session.refresh(job)
    return job


def resume_incomplete_jobs() -> int:
    """On startup: requeue jobs that were running/queued when we stopped."""
    with Session(get_engine()) as session:
        rows = session.exec(select(Job).where(
            Job.status.in_(["queued", "running", "paused"])  # type: ignore[attr-defined]
        )).all()
        for r in rows:
            if r.status == "running":
                r.status = "queued"
                session.add(r)
            if r.status == "queued":
                _get_queue().put_nowait(r.id)
        session.commit()
        return len(rows)


async def start_worker(synthesize_fn) -> None:
    """synthesize_fn(text, voice_id, settings) -> (wav_bytes, duration_s)."""
    global _worker_task
    _worker_task = asyncio.create_task(_worker(synthesize_fn))


async def stop_worker() -> None:
    if _worker_task:
        _worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker_task


async def enqueue(job_id: str) -> None:
    await _get_queue().put(job_id)


def queue_length() -> int:
    return _queue.qsize() if _queue is not None else 0


def _job_audio_dir(job_id: str) -> Path:
    d = get_settings().data_dir / "jobs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _worker(synthesize_fn) -> None:
    from app.core.audio import save_wav  # local import: heavy deps

    global _current_cancel, _current_pause
    while True:
        job_id = await _get_queue().get()
        _current_cancel = asyncio.Event()
        _current_pause = asyncio.Event()
        try:
            await _run_job(job_id, synthesize_fn, save_wav)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            with Session(get_engine()) as session:
                job = session.get(Job, job_id)
                if job:
                    job.status = "failed"
                    job.error = str(e)[:2000]
                    session.add(job)
                    session.commit()
        finally:
            _current_cancel = None
            _current_pause = None
            _get_queue().task_done()


async def _run_job(job_id: str, synthesize_fn, save_wav) -> None:
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if job is None or job.status in ("cancelled", "completed"):
            return
        if job.kind == "clone_finetune":
            job.status = "failed"
            job.error = ("clone fine-tuning is not implemented yet — "
                         "use mode='quick' for zero/few-shot cloning")
            session.add(job)
            session.commit()
            return
        job.status = "running"
        session.add(job)
        session.commit()
        voice_id, settings = job.voice_id, SynthesisSettings(**(job.settings or {}))

    pending = True
    while pending:
        if _current_cancel and _current_cancel.is_set():
            _set_status(job_id, "cancelled")
            return
        if _current_pause and _current_pause.is_set():
            await asyncio.sleep(0.5)
            continue
        with Session(get_engine()) as session:
            sent = session.exec(
                select(JobSentence)
                .where(JobSentence.job_id == job_id)
                .where(JobSentence.status.in_(["pending", "failed"]))  # type: ignore[attr-defined]
                .where(JobSentence.attempts < MAX_ATTEMPTS)
                .order_by(JobSentence.chapter_index, JobSentence.sentence_index)
            ).first()
            if sent is None:
                pending = False
                break
            sent.attempts += 1
            sent.status = "pending"
            session.add(sent)
            session.commit()
            sent_id, text = sent.id, sent.text
            ch_idx = sent.chapter_index

        try:
            start = time.perf_counter()
            samples, sr = await synthesize_fn(text, voice_id, settings)
            path = _job_audio_dir(job_id) / f"ch{ch_idx:03d}_s{sent_id:06d}.wav"
            save_wav(path, samples, sr)
            dur = len(samples) / sr
            with Session(get_engine()) as session:
                sent = session.get(JobSentence, sent_id)
                sent.status = "done"
                sent.audio_path = str(path)
                sent.duration_s = dur
                session.add(sent)
                job = session.get(Job, job_id)
                job.done_sentences += 1
                job.updated_at = datetime.now(UTC)
                session.add(job)
                session.commit()
            log.info("job %s sentence %s done in %.2fs", job_id, sent_id,
                     time.perf_counter() - start)
        except Exception as e:  # noqa: BLE001
            log.warning("job %s sentence %s failed (attempt): %s", job_id, sent_id, e)
            with Session(get_engine()) as session:
                sent = session.get(JobSentence, sent_id)
                sent.status = "failed" if sent.attempts >= MAX_ATTEMPTS else "pending"
                session.add(sent)
                session.commit()

    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        failed = session.exec(select(JobSentence).where(
            JobSentence.job_id == job_id, JobSentence.status == "failed")).all()
        job.status = "failed" if failed else "completed"
        if failed:
            job.error = f"{len(failed)} sentences failed"
        session.add(job)
        session.commit()
        completed = job.status == "completed"
    if completed:
        from app.jobs.exporters import export_job
        await export_job(job_id)


def _set_status(job_id: str, status: str) -> None:
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if job:
            job.status = status
            session.add(job)
            session.commit()


async def pause(job_id: str) -> None:
    _set_status(job_id, "paused")
    if _current_pause:
        _current_pause.set()


async def resume(job_id: str) -> None:
    _set_status(job_id, "queued")
    await _get_queue().put(job_id)


async def cancel(job_id: str) -> None:
    if _current_cancel:
        _current_cancel.set()
    _set_status(job_id, "cancelled")


async def retry_failed(job_id: str) -> int:
    with Session(get_engine()) as session:
        rows = session.exec(select(JobSentence).where(
            JobSentence.job_id == job_id, JobSentence.status == "failed")).all()
        for r in rows:
            r.status = "pending"
            r.attempts = 0
            session.add(r)
        job = session.get(Job, job_id)
        if job:
            job.status = "queued"
            session.add(job)
        session.commit()
        n = len(rows)
    if n:
        await _get_queue().put(job_id)
    return n
