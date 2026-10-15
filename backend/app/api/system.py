import asyncio
import logging

from fastapi import APIRouter

from app.core import metrics as core_metrics
from app.core.config import get_settings
from app.engines.router import get_router

log = logging.getLogger("api.system")
router = APIRouter(tags=["system"])


async def _gpu_status() -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        name, used, total, util = out.decode().strip().split(", ")
        return {"name": name, "memory_used_mb": int(used),
                "memory_total_mb": int(total), "utilization_pct": int(util)}
    except Exception:  # noqa: BLE001
        return {"name": None, "memory_used_mb": None,
                "memory_total_mb": None, "utilization_pct": None}


@router.get("/health")
async def health():
    engines = await get_router().health()
    gpu = await _gpu_status()
    return {
        "status": "ok",
        "engines": {k: v.model_dump() for k, v in engines.items()},
        "gpu": gpu,
        "device": get_settings().device,
    }


@router.get("/metrics")
async def metrics():
    engines = await get_router().health()
    gpu = await _gpu_status()
    from app.jobs.queue import queue_length
    return {
        **core_metrics.snapshot(),
        "queue_length": queue_length(),
        "engines": {k: v.status for k, v in engines.items()},
        "gpu": gpu,
    }
