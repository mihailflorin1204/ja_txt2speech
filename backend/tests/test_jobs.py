"""Job queue tests — synthesis mocked, verifies checkpointing/retry/resume."""

import asyncio
import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlmodel import Session, select

from app.core.db import get_engine
from app.jobs import queue as jq
from app.models.tables import Job, JobSentence

pytestmark = pytest.mark.asyncio


async def fake_synth(text: str, voice_id: str, settings) -> tuple[np.ndarray, int]:
    return np.zeros(4410, dtype=np.float32), 44100


async def test_job_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    sentences = [{"chapter_index": 0, "sentence_index": i, "text": f"文{i}。"}
                 for i in range(5)]
    job = jq.create_job("long_text", "v:1", {}, [{"title": "t", "text": "x"}],
                        sentences, {"format": "wav", "mode": "combined",
                                    "srt": True})
    await jq.start_worker(fake_synth)
    try:
        await jq.enqueue(job.id)
        await jq._get_queue().join()
    finally:
        await jq.stop_worker()

    with Session(get_engine()) as session:
        j = session.get(Job, job.id)
        assert j.status == "completed"
        assert j.done_sentences == 5
        rows = session.exec(select(JobSentence).where(JobSentence.job_id == job.id)).all()
        assert all(r.status == "done" and r.audio_path for r in rows)
        for r in rows:
            assert Path(r.audio_path).exists()


async def test_retry_gives_up_after_max_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    async def bad_synth(text, voice_id, settings):
        raise RuntimeError("boom")

    sentences = [{"chapter_index": 0, "sentence_index": 0, "text": "失敗。"}]
    job = jq.create_job("long_text", "v:1", {}, [{"title": "t", "text": "x"}],
                        sentences, {})
    await jq.start_worker(bad_synth)
    try:
        await jq.enqueue(job.id)
        await asyncio.wait_for(jq._get_queue().join(), timeout=30)
    finally:
        await jq.stop_worker()

    with Session(get_engine()) as session:
        j = session.get(Job, job.id)
        assert j.status == "failed"
        sent = session.exec(select(JobSentence).where(
            JobSentence.job_id == job.id)).first()
        assert sent.status == "failed"
        assert sent.attempts == jq.MAX_ATTEMPTS


async def test_pause_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    job = jq.create_job("long_text", "v:1", {}, [],
                        [{"chapter_index": 0, "sentence_index": 0,
                          "text": "テスト。"}], {})
    await jq.pause(job.id)
    with Session(get_engine()) as session:
        assert session.get(Job, job.id).status == "paused"
    await jq.cancel(job.id)
    with Session(get_engine()) as session:
        assert session.get(Job, job.id).status == "cancelled"
    _ = uuid.uuid4()  # keep import
