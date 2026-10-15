# Setup & Operations Guide

Fully local Japanese TTS. Three engine processes managed by the backend;
text/audio never leave this machine.

## Requirements

| Tool | Version | Where |
|---|---|---|
| Python | 3.11.x | `py -3.11` |
| Node.js + pnpm | 22+ / 10+ | `tools/node` (or PATH) |
| ffmpeg | 5+ | `tools/ffmpeg/bin` (or PATH) |
| GPU | optional; RTX 3060 12GB+ recommended | CUDA |

`scripts\setup_engines.ps1` automates engine downloads; it uses resumable
`curl -C -` for the multi-GB wheels — re-running is safe and resumes.

## Engines

### VOICEVOX (`external/voicevox/windows-nvidia/run.exe`)
- Windows-NVIDIA build 0.25.2; the split `.7z` is extracted with `tools/7zr.exe`.
- Launched lazily by the backend on :50021. Measured RTF ≈ 0.03, TTFA ≈ 77 ms.
- 127 voices; styles surfaced via `/audio_query` defaults.

### Style-Bert-VITS2 (`external/Style-Bert-VITS2/`)
- Own venv (`venv/Scripts/python.exe`) — pins torch `2.3.1+cu121` (can't share
  backend's).
- `transformers==4.46.3` is required — ≥4.50+/5.x needs torch ≥2.5. Accelerate
  is needed for `device_map`/`low_cpu_mem_usage`.
- `mkl`, `intel-openmp`, `tbb` provide torch's DLL dependencies on Windows.
- Models: JP BERT (`deberta-v2-large-japanese-char-wwm`) + default jvnv models
  under `model_assets/`. `initialize.py --only_infer` fetches all bert
  languages + training assets; for Japanese-only you need the jvnv files.
- Runs `server_fastapi.py` on :5000 (GET `/voice`, `/models/info`, `/status`).
  Subprocess log: `data/logs/sbv2-server.log`.
- jvnv voices expose styles `Neutral/Angry/Disgust/Fear/Happy/Sad/Surprise`.

### GPT-SoVITS (`external/GPT-SoVITS/`) — cloning (M5)
- Own venv; `api_v2.py` on :9880 (`POST /tts`, query or JSON).
- Pretrained models under `GPT_SoVITS/pretrained_models/` (downloaded from
  `lj1995/GPT-SoVITS` on HF): `chinese-roberta-wwm-ext-large`,
  `chinese-hubert-base`, `gsv-v2final-pretrained/`.
- Quirks handled by setup script: `jieba_fast` is shimmed onto `jieba` (no
  Windows wheel), `pytorch_model.bin` files are converted to
  `model.safetensors` (transformers ≥4.52 blocks `torch.load` on torch <2.6
  per CVE-2025-32434), `rotary_embedding_torch`/`x_transformers` install
  `--no-deps` to keep torch 2.3.1+cu121, fast_langdetect's `lid.176` model
  goes into `pretrained_models/fast_langdetect/`, `resampy` is needed at
  runtime.
- Config: `GPT_SoVITS/configs/tts_infer.yaml` (v2 custom profile uses GPU).
- Reference audio must be 3–10 s clean speech. Cloned voices appear as
  `gptsovits:<id>` in the catalog after quality checks pass.

## Env vars (`backend/.env` — see `.env.example`)

`JPTTS_DATA_DIR` (default `./data`) holds sqlite, audio, clone samples,
previews, engine logs. `JPTTS_DEVICE=cuda|cpu|auto`. Engine hosts/ports:
`JPTTS_VOICEVOX_HOST/PORT`, `JPTTS_SBV2_HOST/PORT`, `JPTTS_GPTSOVITS_*`.
`JPTTS_MAX_RESIDENT_ENGINES` (default 2) controls lazy loading/LRU.

## Run

```powershell
powershell -File scripts\run_dev.ps1      # backend :8000 + vite :5173
# production: pnpm build in frontend/, then uvicorn serves frontend/dist
```

## Verify

```bash
backend/.venv/Scripts/python -m pytest backend/tests -q   # 110 tests
PYTHONUTF8=1 backend/.venv/Scripts/python scripts/smoke_e2e.py  # live e2e
PYTHONUTF8=1 backend/.venv/Scripts/python scripts/bench.py      # perf
cd frontend && pnpm test && pnpm build
```

## Troubleshooting

- **`/api/v1/voices` empty or voice `available:false`** — engine offline; check
  `data/logs/` and `/api/v1/health`. Voices persist in sqlite even when their
  engine is down.
- **curl + Japanese text** — use `--data-binary @file.json`; Git Bash `-d`
  mangles UTF-8 (empty/mojibake → empty audio).
- **SBV2 500s after idle** — check `data/logs/sbv2-server.log`; GPU OOM is the
  usual cause (8GB VRAM: keep `max_resident_engines` at 2).
- **MP3 is 44 bytes** — text was empty/mojibake; see curl note.
- **HTTP engine ports are per-config** — change `JPTTS_*_PORT` on collisions.
