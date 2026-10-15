"""API tests with engines mocked out (no real TTS needed in CI)."""

import io
import wave
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.engines.base import AudioChunk, EngineHealth, Feature, VoiceInfo
from app.main import app


def _wav_chunk(sr: int = 44100, seconds: float = 0.1) -> AudioChunk:
    samples = np.zeros(int(sr * seconds), dtype=np.float32)
    return AudioChunk.from_float32(samples, sr)


class FakeRouter:
    async def all_voices(self):
        return [
            VoiceInfo(id="voicevox:1", engine="voicevox", engine_voice_id="1",
                      name="ずんだもん（ノーマル）", styles=["ノーマル"],
                      features=[Feature.SPEED, Feature.PITCH],
                      credit="VOICEVOX:ずんだもん"),
            VoiceInfo(id="sbv2:amitaro", engine="sbv2", engine_voice_id="amitaro",
                      name="amitaro", styles=["Neutral"],
                      features=[Feature.STYLE, Feature.SPEED],
                      credit="Style-Bert-VITS2"),
        ]

    async def synthesize(self, utterance, voice_id, settings):
        return _wav_chunk()

    async def health(self):
        return {"voicevox": EngineHealth(status="ok")}

    def start_supervisor(self):
        pass

    async def stop_all(self):
        pass

    def supports(self, voice_id, feature):
        return True


@pytest.fixture
def client():
    with patch("app.engines.router.get_router", return_value=FakeRouter()), \
         patch("app.main.get_router", return_value=FakeRouter()), \
         patch("app.api.voices.get_router", return_value=FakeRouter()), \
         patch("app.api.synth.get_router", return_value=FakeRouter()), TestClient(app) as c:
        yield c


def test_voices_list(client):
    r = client.get("/api/v1/voices")
    assert r.status_code == 200
    voices = r.json()["voices"]
    assert len(voices) == 2
    assert any(v["engine"] == "voicevox" for v in voices)
    assert any(v["engine"] == "sbv2" for v in voices)


def test_voices_filter_engine(client):
    r = client.get("/api/v1/voices", params={"engine": "sbv2"})
    voices = r.json()["voices"]
    assert len(voices) == 1 and voices[0]["engine"] == "sbv2"


def test_synthesize_wav(client):
    r = client.post("/api/v1/synthesize", json={
        "text": "今日はいい天気ですね。", "voice_id": "voicevox:1", "format": "wav"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    # valid wav
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 44100


def test_synthesize_long_text_redirect(client):
    r = client.post("/api/v1/synthesize", json={
        "text": "あ" * 501, "voice_id": "voicevox:1"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "LONG_TEXT"


def test_analyze(client):
    r = client.post("/api/v1/analyze", json={"text": "こんにちは。"})
    assert r.status_code == 200
    assert "sentences" in r.json()


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_error_envelope(client):
    r = client.get("/api/v1/voices/nope:x")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body and "code" in body["error"]


def test_patch_unknown_voice_404(client):
    """PATCH on a voice id that exists nowhere must 404, not create a row."""
    import uuid
    vid = f"ghost:{uuid.uuid4().hex[:8]}"
    r = client.patch(f"/api/v1/voices/{vid}", json={"is_favorite": True})
    assert r.status_code == 404


def test_delete_cloned_voice_removes_files(client, tmp_path):
    """FR-5.6: deleting a cloned voice removes the sample row + audio file."""
    import uuid

    from sqlmodel import Session

    from app.core.config import get_settings
    from app.core.db import get_engine
    from app.models.tables import CloneSample, Voice

    sid = uuid.uuid4().hex[:12]
    sample_path = get_settings().samples_dir / f"{sid}.wav"
    get_settings().samples_dir.mkdir(parents=True, exist_ok=True)
    sample_path.write_bytes(b"RIFFfake")
    with Session(get_engine()) as session:
        session.add(CloneSample(id=sid, audio_path=str(sample_path),
                                transcript="x", duration_s=10.0,
                                quality_report={"ok": True}))
        session.add(Voice(id=f"gptsovits:{sid}", engine="gptsovits",
                          engine_voice_id=sid, name="del me",
                          is_cloned=True))
        session.commit()

    r = client.delete(f"/api/v1/voices/gptsovits:{sid}")
    assert r.status_code == 200
    assert not sample_path.exists()
    with Session(get_engine()) as session:
        assert session.get(Voice, f"gptsovits:{sid}") is None
        assert session.get(CloneSample, sid) is None


def test_delete_noncloned_voice_forbidden(client):
    r = client.delete("/api/v1/voices/voicevox:1")
    assert r.status_code == 403
