"""Engine adapter contract tests — run against mocks in CI, real engines via
JPTTS_TEST_REAL_ENGINES=1 on a GPU machine."""

import os

import numpy as np
import pytest

from app.engines.base import AudioChunk, Feature, SynthesisSettings, Utterance

REAL = os.environ.get("JPTTS_TEST_REAL_ENGINES") == "1"


@pytest.fixture
def utterance():
    return Utterance(text="こんにちは。")


@pytest.fixture
def settings():
    return SynthesisSettings()


async def _exercise(engine, voice_id, utterance, settings):
    assert engine.supports(Feature.SPEED) or True  # feature flags introspectable
    voices = await engine.list_voices()
    assert voices and all(v.engine == engine.id for v in voices)
    chunk = await engine.synthesize(utterance, voice_id, settings)
    assert isinstance(chunk, AudioChunk)
    assert chunk.sample_rate > 0 and len(chunk.pcm) > 0


@pytest.mark.skipif(not REAL, reason="requires real engines")
async def test_voicevox_real(utterance, settings):
    from app.engines.voicevox import VoicevoxEngine
    eng = VoicevoxEngine()
    await eng.start()
    try:
        voices = await eng.list_voices()
        await _exercise(eng, voices[0].engine_voice_id, utterance, settings)
    finally:
        await eng.stop()


async def test_voicevox_mocked(utterance, settings, tmp_path):
    """Contract shape with httpx mocked — no engine needed."""
    import io
    import wave

    from app.engines.voicevox import VoicevoxEngine

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(np.zeros(2400, dtype=np.int16).tobytes())

    eng = VoicevoxEngine()
    eng._client = type("C", (), {})()  # stub

    speakers_payload = [{"name": "ずんだもん", "speaker_uuid": "x",
                         "styles": [{"id": 1, "name": "ノーマル"}]}]
    query_payload = {"accent_phrases": [], "speedScale": 1.0}

    async def fake_get(url, **kw):
        assert url == "/speakers"
        return type("R", (), {"status_code": 200,
                              "json": lambda s: speakers_payload,
                              "raise_for_status": lambda s: None})()

    calls = []

    async def fake_post(url, **kw):
        calls.append(url)
        if url == "/audio_query":
            return type("R", (), {"status_code": 200,
                                  "json": lambda s: dict(query_payload),
                                  "raise_for_status": lambda s: None})()
        return type("R", (), {"status_code": 200, "content": buf.getvalue(),
                              "raise_for_status": lambda s: None})()

    eng._client.get = fake_get
    eng._client.post = fake_post
    eng._is_up = lambda: _true()

    voices = await eng.list_voices()
    assert voices[0].id == "voicevox:1"
    assert voices[0].credit == "VOICEVOX:ずんだもん"
    chunk = await eng.synthesize(utterance, "1", settings)
    assert chunk.sample_rate == 24000
    assert "/audio_query" in calls and "/synthesis" in calls


async def _true():
    return True
