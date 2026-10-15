import logging
import sys
from contextlib import asynccontextmanager, suppress

for stream in (sys.stdout, sys.stderr):
    with suppress(AttributeError, OSError):
        stream.reconfigure(encoding="utf-8")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import init_db  # noqa: E402
from app.core.logging import new_request_id, setup_logging  # noqa: E402
from app.engines.base import EngineUnavailableError  # noqa: E402
from app.engines.router import get_router  # noqa: E402

log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()
    router = get_router()
    router.start_supervisor()
    from app.jobs.queue import resume_incomplete_jobs, start_worker
    from app.jobs.runner import synthesize_for_job
    await start_worker(synthesize_for_job)
    n = resume_incomplete_jobs()
    if n:
        log.info("resumed %d incomplete jobs", n)
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.allow_non_loopback:
        log.warning("host %s is not loopback; refusing to bind without "
                    "JPTTS_ALLOW_NON_LOOPBACK=1", settings.host)
        raise RuntimeError("non-loopback bind requires allow_non_loopback")
    log.info("jp-tts backend ready on %s:%s", settings.host, settings.port)
    yield
    from app.jobs.queue import stop_worker
    await stop_worker()
    await router.stop_all()


app = FastAPI(title="jp-tts", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    new_request_id()
    return await call_next(request)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


@app.exception_handler(EngineUnavailableError)
async def engine_unavailable_handler(request: Request, exc: EngineUnavailableError):
    return _error(503, "ENGINE_UNAVAILABLE", str(exc))


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return _error(exc.status_code, detail["code"], detail.get("message", ""))
    return _error(exc.status_code, "HTTP_ERROR", str(detail))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return _error(422, "VALIDATION_ERROR", "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()))


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled error")
    return _error(500, "INTERNAL_ERROR", str(exc))


from app.api import clone, dictionary, history, jobs, openai, presets, stream, synth, system, voices  # noqa: E402

for r in (voices.router, synth.router, system.router, history.router,
          presets.router, stream.router, dictionary.router, jobs.router,
          clone.router):
    app.include_router(r, prefix="/api/v1")

# OpenAI-compatible surface lives outside /api/v1
app.include_router(openai.router, prefix="/v1")


# serve built frontend when present (production mode)
settings = get_settings()
if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True),
              name="frontend")
