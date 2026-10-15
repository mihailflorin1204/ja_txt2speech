"""Job output exporters (spec FR-7.4): combined or per-chapter MP3/WAV,
M4B audiobook with chapter markers, SRT/VTT subtitles."""

import asyncio
import logging
from pathlib import Path

import numpy as np
import soundfile as sf
from sqlmodel import Session, select

from app.core.audio import TARGET_SR, encode_mp3, resample, save_wav
from app.core.config import get_settings
from app.core.db import get_engine
from app.models.tables import Job, JobSentence

log = logging.getLogger("jobs.exporters")


def _ffmpeg() -> str:
    exe = get_settings().ffmpeg_path
    return str(exe) if exe.exists() else "ffmpeg"


def _read_wav(path: str) -> np.ndarray:
    samples, sr = sf.read(path, dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return resample(np.asarray(samples, dtype=np.float32), sr)


async def _run_ffmpeg(args: list[str], stdin: bytes | None = None) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg(), *args,
        stdin=asyncio.subprocess.PIPE if stdin else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(stdin)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()[:800]}")
    return out


def _chapter_sentences(job_id: str) -> dict[int, list[JobSentence]]:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(JobSentence)
            .where(JobSentence.job_id == job_id)
            .where(JobSentence.status == "done")
            .order_by(JobSentence.chapter_index, JobSentence.sentence_index)
        ).all()
    by_ch: dict[int, list[JobSentence]] = {}
    for r in rows:
        by_ch.setdefault(r.chapter_index, []).append(r)
    return by_ch


def _concat_chapter(sents: list[JobSentence]) -> np.ndarray:
    parts = [_read_wav(s.audio_path) for s in sents if s.audio_path]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


async def export_job(job_id: str) -> list[str]:
    """Produce all requested outputs for a completed job. Returns file paths."""
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        chapters = job.chapters
        opts = job.export_options or {}
    fmt = opts.get("format", "mp3")
    mode = opts.get("mode", "combined")  # combined | per_chapter
    make_m4b = opts.get("m4b", False)
    make_srt = opts.get("srt", False)

    by_ch = _chapter_sentences(job_id)
    out_dir = _job_out_dir(job_id)
    outputs: list[str] = []

    chapter_pcm: list[tuple[str, np.ndarray]] = []
    for ci in sorted(by_ch):
        title = chapters[ci]["title"] if ci < len(chapters) else f"chapter {ci}"
        chapter_pcm.append((title, _concat_chapter(by_ch[ci])))

    if mode == "per_chapter":
        for title, pcm in chapter_pcm:
            fname = f"{_safe(title)}.{fmt}"
            await _write_audio(out_dir / fname, pcm, fmt)
            outputs.append(fname)
    else:
        all_pcm = np.concatenate([p for _, p in chapter_pcm]) if chapter_pcm else np.zeros(0)
        fname = f"combined.{fmt}"
        await _write_audio(out_dir / fname, all_pcm, fmt)
        outputs.append(fname)

    if make_srt:
        outputs.append(await _write_srt(job_id, by_ch, out_dir))
    if make_m4b:
        outputs.append(await _write_m4b(job_id, chapter_pcm, out_dir))
    return outputs


def _job_out_dir(job_id: str) -> Path:
    d = get_settings().data_dir / "jobs" / job_id / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    ok = "-_ .　"
    return "".join(c if c.isalnum() or c in ok else "_" for c in name)[:60].strip() or "chapter"


async def _write_audio(path: Path, pcm: np.ndarray, fmt: str) -> None:
    if fmt == "wav":
        save_wav(path, pcm, TARGET_SR)
    else:
        path.write_bytes(await encode_mp3(pcm, TARGET_SR))


async def _write_srt(job_id: str, by_ch: dict[int, list[JobSentence]],
                     out_dir: Path) -> str:
    lines, t = [], 0.0
    for ci in sorted(by_ch):
        for s in by_ch[ci]:
            dur = s.duration_s or 0.0
            lines.append(f"{len(lines)+1}\n{_ts(t)} --> {_ts(t+dur)}\n{s.text}\n")
            t += dur
    path = out_dir / "subtitles.srt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return "subtitles.srt"


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def _write_m4b(job_id: str,
                     chapter_pcm: list[tuple[str, np.ndarray]],
                     out_dir: Path) -> str:
    """M4B = AAC in mp4 container + chapter metadata (ffmetadata)."""
    path = out_dir / "audiobook.m4b"
    # build ffmetadata chapter file
    meta_lines = [";FFMETADATA1"]
    cursor = 0.0
    for title, pcm in chapter_pcm:
        start_ms = int(cursor * 1000)
        cursor += len(pcm) / TARGET_SR
        end_ms = int(cursor * 1000)
        meta_lines.append("[CHAPTER]")
        meta_lines.append("TIMEBASE=1/1000")
        meta_lines.append(f"START={start_ms}")
        meta_lines.append(f"END={end_ms}")
        meta_lines.append(f"title={title}")
    meta_path = out_dir / "chapters.ffmeta"
    meta_path.write_text("\n".join(meta_lines), encoding="utf-8")

    concat_list = out_dir / "concat.txt"
    tmp_wavs = []
    for i, (_, pcm) in enumerate(chapter_pcm):
        tw = out_dir / f"_tmp_ch{i}.wav"
        save_wav(tw, pcm, TARGET_SR)
        tmp_wavs.append(tw)
    concat_list.write_text(
        "\n".join(f"file '{tw.name}'" for tw in tmp_wavs), encoding="utf-8")

    await _run_ffmpeg_cwd(
        ["-y", "-f", "concat", "-safe", "0", "-i", concat_list.name,
         "-i", meta_path.name, "-map_metadata", "1",
         "-codec:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         "-f", "mp4", path.name],
        cwd=out_dir)
    for tw in tmp_wavs:
        tw.unlink(missing_ok=True)
    return "audiobook.m4b"


async def _run_ffmpeg_cwd(args: list[str], cwd: Path) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg(), *args, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()[:800]}")
    return b""


def estimate_seconds(job_id: str) -> float:
    """Rough ETA based on chars (for UI estimate before starting)."""
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        return job.total_sentences * 2.0 if job else 0.0
