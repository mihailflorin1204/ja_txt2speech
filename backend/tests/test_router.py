"""Engine router tests — catalog availability vs LRU residency (FR-2.4).

Regression tests for a bug where `all_voices()` routed through the
evicting `ensure_running()`, so with more engines than
`max_resident_engines` the first-listed engine was evicted mid-catalog
and its voices were wrongly marked unavailable.
"""

import asyncio
from collections import OrderedDict

import pytest
from sqlmodel import Session, select

from app.core.db import get_engine, init_db
from app.engines.base import EngineHealth, EngineUnavailableError, Feature, VoiceInfo
from app.engines.router import EngineRouter
from app.models.tables import Voice

pytestmark = pytest.mark.asyncio


class FakeEngine:
    def __init__(self, eng_id: str, up: bool = True):
        self.id = eng_id
        self._up = up
        self.stops = 0
        self.starts = 0

    async def start(self):
        self.starts += 1
        self._up = True

    async def stop(self):
        self.stops += 1
        self._up = False

    async def health(self):
        return EngineHealth(status="ok" if self._up else "offline")

    async def list_voices(self):
        if not self._up:
            raise EngineUnavailableError(f"{self.id} offline")
        return [VoiceInfo(id=f"{self.id}:1", engine=self.id,
                          engine_voice_id="1", name=f"{self.id} voice",
                          features=[Feature.SPEED])]

    def supports(self, feature):
        return True

    async def synthesize(self, utterance, voice_id, settings):
        raise NotImplementedError


def _make_router(engines: dict[str, FakeEngine]) -> EngineRouter:
    r = EngineRouter.__new__(EngineRouter)
    r._engines = dict(engines)
    r._locks = {k: asyncio.Lock() for k in engines}
    r._resident = OrderedDict()
    r._engine_health = {}
    r._supervisor_task = None
    return r


def _clean_voice_rows() -> None:
    """The test DB is shared across tests — start from a clean Voice table."""
    init_db()
    with Session(get_engine()) as session:
        for r in session.exec(select(Voice)).all():
            session.delete(r)
        session.commit()


async def test_catalog_does_not_evict_or_mark_unavailable():
    """3 engines, cap=2: catalog must not evict; all live voices available."""
    _clean_voice_rows()
    engines = {k: FakeEngine(k) for k in ("voicevox", "sbv2", "gptsovits")}
    router = _make_router(engines)

    voices = await router.all_voices()

    assert {v.id for v in voices} == {"voicevox:1", "sbv2:1", "gptsovits:1"}
    assert all(v.available for v in voices), [
        (v.id, v.available) for v in voices]
    # a read endpoint must not stop engines
    assert all(e.stops == 0 for e in engines.values())


async def test_catalog_starts_offline_engine_and_lists_voices():
    _clean_voice_rows()
    engines = {"a": FakeEngine("a", up=True), "b": FakeEngine("b", up=False)}
    router = _make_router(engines)

    voices = await router.all_voices()

    assert engines["b"].starts == 1
    assert all(v.available for v in voices)


async def test_catalog_keeps_unlistable_engine_voices_unavailable():
    """An engine that fails start+list leaves its DB voices unavailable."""
    _clean_voice_rows()

    class DeadEngine(FakeEngine):
        async def start(self):
            raise EngineUnavailableError("dead")

    engines = {"a": FakeEngine("a", up=True), "b": DeadEngine("b", up=False)}
    router = _make_router(engines)

    # persist a stale voice row for engine b (as if listed earlier)
    with Session(get_engine()) as session:
        session.add(Voice(id="b:9", engine="b", engine_voice_id="9",
                          name="old b voice", styles=[], features=["speed"]))
        session.commit()

    voices = {v.id: v for v in await router.all_voices()}
    assert voices["a:1"].available is True
    assert voices["b:9"].available is False


async def test_health_reflects_live_state_not_cache():
    """health() must report current reachability for every engine."""
    engines = {"a": FakeEngine("a", up=True), "b": FakeEngine("b", up=False)}
    router = _make_router(engines)
    router._resident["a"] = 1.0  # only a resident

    h = await router.health()
    assert h["a"].status == "ok"
    assert h["b"].status == "offline"
