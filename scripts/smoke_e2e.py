"""End-to-end smoke test against a RUNNING jp-tts backend.

Usage (with `python scripts/run_dev.ps1` or uvicorn running on :8000):

    python scripts/smoke_e2e.py [--base http://127.0.0.1:8000]

Exercises the spec surface end to end and exits non-zero on failure.
Requires at least one engine (VOICEVOX or SBV2) online for synth checks;
analyze/dictionary/presets run regardless.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import wave

import httpx

FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global FAIL
    mark = "PASS" if cond else "FAIL"
    if not cond:
        FAIL += 1
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=180.0)

    # -- system ---------------------------------------------------------------
    h = c.get("/api/v1/health").json()
    check("health", h["status"] == "ok")
    engines = {k: v["status"] for k, v in h["engines"].items()}
    print("  engines:", engines)
    m = c.get("/api/v1/metrics")
    check("metrics", m.status_code == 200)

    # -- voices ----------------------------------------------------------------
    v = c.get("/api/v1/voices").json()
    check("voices listed", len(v["voices"]) > 0, str(len(v["voices"])))
    avail = [x for x in v["voices"] if x["available"]]
    check("at least one available voice", len(avail) > 0)
    if not avail:
        print("no engine online — synth checks skipped")
        sys.exit(1)
    vid = avail[0]["id"]
    check("voice detail", c.get(f"/api/v1/voices/{vid}").status_code == 200)
    check("favorite toggle",
          c.patch(f"/api/v1/voices/{vid}", json={"is_favorite": True}).status_code == 200)
    c.patch(f"/api/v1/voices/{vid}", json={"is_favorite": False})

    # -- text pipeline ----------------------------------------------------------
    a = c.post("/api/v1/analyze", json={"text": "今日はいい天気ですね。"})
    check("analyze", a.status_code == 200 and len(a.json()["sentences"]) >= 1)
    first = a.json()["sentences"][0]
    mora_kana = [m["kana"] for ph in first["accent_phrases"] for m in ph["moras"]]
    check("readings present", len(mora_kana) >= 3 and "キョ" in mora_kana,
          str(mora_kana))

    # -- synthesize ---------------------------------------------------------------
    t0 = time.perf_counter()
    s = c.post("/api/v1/synthesize", json={
        "text": "こんにちは。世界。",
        "voice_id": vid, "format": "wav",
    })
    dt = time.perf_counter() - t0
    check("synthesize wav", s.status_code == 200 and len(s.content) > 1000,
          f"{s.status_code} {len(s.content)}B")
    if s.status_code == 200:
        wav = wave.open(io.BytesIO(s.content))
        audio_s = wav.getnframes() / wav.getframerate()
        print(f"  synth: {dt:.2f}s wall, {audio_s:.2f}s audio, RTF {dt / audio_s:.2f}")
        check("rtf < 3", dt / audio_s < 3)

    # mp3
    s2 = c.post("/api/v1/synthesize", json={
        "text": "テスト。", "voice_id": vid, "format": "mp3"})
    check("synthesize mp3", s2.status_code == 200 and s2.content[:3] == b"ID3"
          or s2.content[:2] == b"\xff\xfb", f"{len(s2.content)}B")

    # -- openai-compatible --------------------------------------------------------
    o = c.post("/v1/audio/speech", json={
        "input": "テスト。", "voice": vid, "response_format": "mp3"})
    check("openai speech", o.status_code == 200 and len(o.content) > 1000,
          f"{o.status_code} {len(o.content)}B")

    # -- streaming -----------------------------------------------------------------
    ws_base = str(c.base_url).replace("http://", "ws://").replace("https://", "wss://")
    check("ws stream", _ws_stream(ws_base, vid))

    # -- dictionary ------------------------------------------------------------------
    d = c.post("/api/v1/dictionary", json={
        "surface": "便利", "reading": "カイトテキ"})
    check("dictionary add", d.status_code == 201)
    entries = c.get("/api/v1/dictionary").json()["entries"]
    hit = next((e for e in entries if e["surface"] == "便利"), None)
    check("dictionary listed", hit is not None)
    a2 = c.post("/api/v1/analyze", json={"text": "便利な物です。"})
    joined = "".join(
        m["kana"] for s_ in a2.json()["sentences"]
        for ph in s_["accent_phrases"] for m in ph["moras"])
    check("dictionary applied", "カイトテキ" in joined, joined)
    if hit:
        c.delete(f"/api/v1/dictionary/{hit['id']}")

    # -- presets ---------------------------------------------------------------------
    p = c.post("/api/v1/presets", json={
        "name": f"smoke-{int(time.time())}", "voice_id": vid,
        "settings": {"speed": 1.2}})
    check("preset add", p.status_code in (200, 201))
    pid = p.json().get("id") if p.status_code in (200, 201) else None
    if pid:
        c.delete(f"/api/v1/presets/{pid}")

    # -- history ----------------------------------------------------------------------
    hh = c.get("/api/v1/history").json()
    check("history", hh["generations"] and
          hh["generations"][0]["audio_url"].startswith("/api/v1/files/"))
    check("audio file served",
          c.get(hh["generations"][0]["audio_url"]).status_code == 200)

    # -- jobs --------------------------------------------------------------------------
    j = c.post("/api/v1/jobs", json={
        "text": "第一章 短い。\nテストです。",
        "voice_id": vid,
        "export_options": {"format": "wav", "mode": "per_chapter",
                           "srt": True, "m4b": False}})
    if j.status_code != 201:
        check("job create", False, f"{j.status_code} {j.text[:200]}")
    else:
        jid = j.json()["job_id"]
        for _ in range(90):
            st = c.get(f"/api/v1/jobs/{jid}").json()
            if st["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(1)
        check("job completes", st["status"] == "completed", st.get("error"))
        outs = c.get(f"/api/v1/jobs/{jid}/outputs").json()["outputs"]
        check("job outputs wav+srt",
              any(o["name"].endswith(".wav") for o in outs) and
              any(o["name"].endswith(".srt") for o in outs),
              str([o["name"] for o in outs]))

    print()
    print("=" * 40)
    print("SMOKE:", "PASS" if FAIL == 0 else f"FAIL ({FAIL} failures)")
    sys.exit(0 if FAIL == 0 else 1)


def _ws_stream(ws_base: str, voice_id: str) -> bool:
    try:
        import websockets
    except ImportError:
        try:
            import asyncio
            import websockets  # noqa: F401
        except ImportError:
            print("  (websockets pkg missing — skipping)")
            return True
    import asyncio

    async def go() -> bool:
        got_format = got_sentence = got_pcm = got_done = False
        async with websockets.connect(f"{ws_base}/api/v1/stream") as ws:
            await ws.send(json.dumps({
                "type": "start", "text": "短い文。もう一つ。",
                "voice_id": voice_id, "settings": {}, "format": "pcm16"}))
            async for raw in ws:
                if isinstance(raw, bytes):
                    if len(raw) > 100:
                        got_pcm = True
                    continue
                m = json.loads(raw)
                t = m.get("type")
                if t == "format":
                    got_format = True
                elif t == "sentence":
                    got_sentence = True
                elif t == "done":
                    got_done = True
                    break
                elif t == "error":
                    print("  stream error:", m.get("message"))
                    return False
        return got_format and got_sentence and got_pcm and got_done

    return asyncio.run(go())


if __name__ == "__main__":
    main()
