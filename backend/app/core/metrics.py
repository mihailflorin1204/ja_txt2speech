"""In-process metrics (spec M6): synthesis counts, latency, RTF, errors."""

import statistics
import threading
import time
from collections import deque

_lock = threading.Lock()
_synths: deque[dict] = deque(maxlen=200)
_errors: deque[dict] = deque(maxlen=200)
_started_at = time.time()


def record_synth(engine: str, latency_s: float, audio_s: float,
                 chars: int, streaming: bool = False) -> None:
    with _lock:
        _synths.append({
            "ts": time.time(), "engine": engine, "latency_s": latency_s,
            "audio_s": audio_s,
            "rtf": latency_s / audio_s if audio_s > 0 else 0,
            "chars": chars, "streaming": streaming,
        })


def record_error(code: str, detail: str = "") -> None:
    with _lock:
        _errors.append({"ts": time.time(), "code": code, "detail": detail[:200]})


def snapshot() -> dict:
    with _lock:
        synths = list(_synths)
        errors = list(_errors)
    rtf = [s["rtf"] for s in synths if s["rtf"] > 0]
    lat = [s["latency_s"] for s in synths]
    return {
        "uptime_s": round(time.time() - _started_at, 1),
        "total_synths": len(synths),
        "total_errors": len(errors),
        "rtf_median": round(statistics.median(rtf), 3) if rtf else None,
        "latency_median_ms": round(statistics.median(lat) * 1000) if lat else None,
        "recent_errors": errors[-20:],
        "per_engine": _per_engine(synths),
    }


def _per_engine(synths: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for s in synths:
        e = out.setdefault(s["engine"], {"count": 0, "rtfs": []})
        e["count"] += 1
        if s["rtf"] > 0:
            e["rtfs"].append(s["rtf"])
    return {k: {"count": v["count"],
                "rtf_median": round(statistics.median(v["rtfs"]), 3)
                if v["rtfs"] else None}
            for k, v in out.items()}
