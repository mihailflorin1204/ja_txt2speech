# jp-tts backend — CPU or CUDA (nvidia runtime required for GPU)
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml backend/README.md* ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlmodel alembic \
    numpy soundfile librosa httpx pydantic-settings pyopenjtalk-plus \
    fugashi unidic-lite jaconv pykakasi ebooklib beautifulsoup4 lxml \
    pytest pytest-asyncio ruff websockets faster-whisper

COPY backend/app ./app
COPY backend/tests ./tests

ENV JPTTS_HOST=0.0.0.0 JPTTS_PORT=8000 JPTTS_ALLOW_NON_LOOPBACK=1 \
    JPTTS_DATA_DIR=/data JPTTS_FFMPEG_PATH=/usr/bin/ffmpeg
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
