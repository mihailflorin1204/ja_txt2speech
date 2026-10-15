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


async def test_pause_resume_running_job(tmp_path, monkeypatch):
    """A running job that is paused must be resumable (regression: the pause
    event was never cleared, so paused jobs hung forever)."""
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    gate = asyncio.Event()
    calls = 0

    async def gated_synth(text, voice_id, settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            await gate.wait()  # first sentence blocks so we can pause mid-run
        return np.zeros(4410, dtype=np.float32), 44100

    job = jq.create_job("long_text", "v:1", {}, [{"title": "t", "text": "x"}],
                        [{"chapter_index": 0, "sentence_index": i,
                          "text": f"文{i}。"} for i in range(3)],
                        {"format": "wav", "mode": "combined"})
    await jq.start_worker(gated_synth)
    try:
        await jq.enqueue(job.id)
        await asyncio.sleep(0.2)  # worker picks up the job, blocked in synth
        await jq.pause(job.id)
        gate.set()  # let the in-flight sentence finish; loop should then pause
        await asyncio.sleep(0.3)
        with Session(get_engine()) as session:
            j = session.get(Job, job.id)
            assert j.status == "paused"
            assert j.done_sentences == 1

        await jq.resume(job.id)
        await asyncio.wait_for(jq._get_queue().join(), timeout=15)
        # give the in-flight run a moment to finish if it wasn't requeued
        for _ in range(100):
            with Session(get_engine()) as session:
                if session.get(Job, job.id).status in ("completed", "failed"):
                    break
            await asyncio.sleep(0.1)

        with Session(get_engine()) as session:
            j = session.get(Job, job.id)
            assert j.status == "completed"
            assert j.done_sentences == 3
    finally:
        await jq.stop_worker()


async def test_cancel_queued_job_does_not_kill_running(tmp_path, monkeypatch):
    """Cancelling job B while job A is running must not cancel A."""
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    release = asyncio.Event()

    async def slow_synth(text, voice_id, settings):
        await release.wait()
        return np.zeros(4410, dtype=np.float32), 44100

    def mk():
        return jq.create_job("long_text", "v:1", {},
                             [{"title": "t", "text": "x"}],
                             [{"chapter_index": 0, "sentence_index": 0,
                               "text": "文。"}], {})

    job_a, job_b = mk(), mk()
    await jq.start_worker(slow_synth)
    try:
        await jq.enqueue(job_a.id)
        await jq.enqueue(job_b.id)
        await asyncio.sleep(0.2)  # A is now running (blocked in synth), B queued
        await jq.cancel(job_b.id)
        release.set()
        await asyncio.wait_for(jq._get_queue().join(), timeout=30)

        with Session(get_engine()) as session:
            assert session.get(Job, job_b.id).status == "cancelled"
            assert session.get(Job, job_a.id).status == "completed"
    finally:
        await jq.stop_worker()


async def test_pause_queued_job_stays_paused_until_resume(tmp_path, monkeypatch):
    """Pausing a queued (not yet started) job must prevent it running."""
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    gate = asyncio.Event()

    async def gated_synth(text, voice_id, settings):
        await gate.wait()
        return np.zeros(4410, dtype=np.float32), 44100

    job_a = jq.create_job("long_text", "v:1", {}, [{"title": "t", "text": "x"}],
                          [{"chapter_index": 0, "sentence_index": 0,
                            "text": "文。"}], {})
    job_b = jq.create_job("long_text", "v:1", {}, [{"title": "t", "text": "x"}],
                          [{"chapter_index": 0, "sentence_index": 0,
                            "text": "文。"}], {})
    await jq.start_worker(gated_synth)
    try:
        await jq.enqueue(job_a.id)
        await jq.enqueue(job_b.id)
        await asyncio.sleep(0.2)  # A running/blocked, B queued
        await jq.pause(job_b.id)
        gate.set()  # finish A; B gets dequeued while paused
        await asyncio.sleep(0.3)
        with Session(get_engine()) as session:
            assert session.get(Job, job_b.id).status == "paused"

        await jq.resume(job_b.id)
        await asyncio.wait_for(jq._get_queue().join(), timeout=30)
        with Session(get_engine()) as session:
            assert session.get(Job, job_b.id).status == "completed"
    finally:
        await jq.stop_worker()


async def test_srt_sequence_numbers(tmp_path, monkeypatch):
    """SRT subtitles must be numbered 1..N (regression: n//4+1 repeated)."""
    monkeypatch.setenv("JPTTS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.db import init_db
    init_db()

    job = jq.create_job("long_text", "v:1", {}, [{"title": "t", "text": "x"}],
                        [{"chapter_index": 0, "sentence_index": i,
                          "text": f"文{i}。"} for i in range(6)],
                        {"format": "wav", "mode": "combined", "srt": True})
    await jq.start_worker(fake_synth)
    try:
        await jq.enqueue(job.id)
        await asyncio.wait_for(jq._get_queue().join(), timeout=30)
    finally:
        await jq.stop_worker()

    from app.core.config import get_settings as gs
    srt = (gs().data_dir / "jobs" / job.id / "outputs" / "subtitles.srt")
    text = srt.read_text(encoding="utf-8")
    numbers = [ln.strip() for ln in text.splitlines() if ln.strip().isdigit()]
    assert numbers == [str(i) for i in range(1, 7)]
