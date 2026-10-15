# jp-tts

A fully local Japanese text-to-speech web app. Converts Japanese text into
natural-sounding speech on your own machine — no cloud APIs, no telemetry.

See `SPEC.md` for the full specification. License: **AGPL-3.0** (required by
Style-Bert-VITS2). Per-voice credits are shown in the voice catalog and must
be preserved in derivative works (e.g. `VOICEVOX:ずんだもん`).

**Voice cloning ethics:** cloning a person's voice without their explicit
permission, impersonation, and fraud are prohibited. Exported audio is tagged
as synthetic.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, SQLModel/SQLite, pyopenjtalk-plus + fugashi |
| Frontend | React, TypeScript, Vite, Tailwind, TanStack Query, Zustand |
| Engines | VOICEVOX Engine (HTTP subprocess), Style-Bert-VITS2 (own venv + API server), GPT-SoVITS (M5) |

## Setup (Windows)

Prerequisites: Python 3.11 (`py -3.11`), Git, NVIDIA GPU optional.
Node.js and ffmpeg are fetched automatically into `tools/`, or install your own
and put them on PATH.

```powershell
# 1. Engine binaries + Style-Bert-VITS2 venv (large downloads)
powershell -File scripts\setup_engines.ps1

# 2. Backend deps
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -e "backend[dev]"

# 3. Frontend deps
set PATH=%CD%\tools\node;%PATH%
cd frontend && pnpm install && cd ..
```

## Run (dev)

```powershell
powershell -File scripts\run_dev.ps1
# UI: http://localhost:5173   API: http://127.0.0.1:8000/api/v1
```

Production: `pnpm build` in `frontend/`, then run uvicorn — the API serves
`frontend/dist` directly.

## Layout

```
backend/app/    FastAPI app (api/, core/, text/, engines/, jobs/, models/)
frontend/src/   React app (pages/, components/, api/)
external/       engine binaries/repos (gitignored)
models/         downloaded weights (gitignored)
data/           sqlite db, generated audio, clone samples (gitignored)
tools/          node, ffmpeg, 7zr (gitignored)
scripts/        setup + dev scripts
```

## Tests

```bash
backend/.venv/Scripts/python -m pytest backend/tests
cd frontend && pnpm test   # Vitest
```

## Milestones

M1 foundation · M2 controls+streaming · M3 accent/dictionary · M4 long-text
jobs · M5 voice cloning · M6 hardening — see `SPEC.md` §11.
