"""WebSocket stream protocol + OpenAI endpoint tests (engines mocked)."""

import io
import struct
import wave
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.engines.base import AudioChunk, VoiceInfo
from app.main import app


def _chunk(sr: int = 44100) -> AudioChunk:
    return AudioChunk.from_float32(np.zeros(int(sr * 0.05), dtype=np.float32), sr)


class FakeRouter:
    async def all_voices(self):
        return [VoiceInfo(id="voicevox:1", engine="voicevox", engine_voice_id="1",
                          name="test", credit="VOICEVOX:test")]

    async def synthesize(self, utterance, voice_id, settings):
        return _chunk()

    async def health(self):
        return {}

    def start_supervisor(self):
        pass

    async def stop_all(self):
        pass

    def supports(self, voice_id, feature):
        return True


@pytest.fixture
def client():
    fake = FakeRouter()
    with patch("app.engines.router.get_router", return_value=fake), \
         patch("app.main.get_router", return_value=fake), \
         patch("app.api.stream.get_router", return_value=fake), \
         patch("app.api.openai.get_router", return_value=fake), TestClient(app) as c:
        yield c


def test_stream_protocol(client):
    import json

    with client.websocket_connect("/api/v1/stream") as ws:
        ws.send_json({"type": "start", "text": "こんにちは。元気です。",
                      "voice_id": "voicevox:1", "settings": {}})
        types: list[str] = []
        binary_frames = 0
        for _ in range(20):
            m = ws.receive()
            if m.get("text"):
                types.append(json.loads(m["text"])["type"])
                if types[-1] == "done":
                    break
            elif m.get("bytes"):
                binary_frames += 1
                idx = struct.unpack("<I", m["bytes"][:4])[0]
                assert idx < 10
        assert types[0] == "format"
        assert "sentence" in types
        assert binary_frames >= 1
        assert types[-1] == "done"


def test_openai_speech(client):
    r = client.post("/v1/audio/speech", json={
        "model": "jp-tts", "input": "こんにちは。",
        "voice": "voicevox:1", "response_format": "wav"})
    assert r.status_code == 200
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getnchannels() == 1


def test_openai_speech_bad_format(client):
    r = client.post("/v1/audio/speech", json={
        "input": "x", "voice": "voicevox:1", "response_format": "exe"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "BAD_FORMAT"


def test_openai_voice_alias(client):
    r = client.post("/v1/audio/speech", json={
        "input": "こんにちは。", "voice": "alloy", "response_format": "wav"})
    assert r.status_code == 200  # falls back to first available voice
