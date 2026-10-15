"""Benchmarks per spec §12: RTF, time-to-first-audio, /analyze latency.

Run with the server up:  python scripts/bench.py [voice_id]
"""

import asyncio
import statistics
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
TEXT = "今日はいい天気ですね。明日も晴れるでしょう。"
LONG = "これはストリーミングのベンチマークです。" * 5


async def main() -> int:
    voice = sys.argv[1] if len(sys.argv) > 1 else None
    async with httpx.AsyncClient(base_url=BASE, timeout=180) as c:
        if voice is None:
            voices = (await c.get("/api/v1/voices")).json()["voices"]
            avail = [v for v in voices if v["available"]]
            if not avail:
                print("no voices available — start engines first")
                return 1
            voice = avail[0]["id"]
            print(f"voice: {voice}")

        # /analyze latency
        lat = []
        for _ in range(5):
            t = time.perf_counter()
            await c.post("/api/v1/analyze", json={"text": TEXT})
            lat.append(time.perf_counter() - t)
        print(f"/analyze latency: median {statistics.median(lat)*1000:.0f} ms "
              f"(target <200ms GPU)")

        # RTF via /synthesize
        rtfs = []
        for _ in range(3):
            t = time.perf_counter()
            r = await c.post("/api/v1/synthesize", json={
                "text": TEXT, "voice_id": voice, "format": "wav",
                "settings": {}})
            dt = time.perf_counter() - t
            audio_s = len(r.content) / (44100 * 2)  # 16-bit mono
            rtfs.append(dt / audio_s)
            print(f"  synth {dt:.2f}s for {audio_s:.2f}s audio -> RTF {dt/audio_s:.2f}")
        print(f"RTF median: {statistics.median(rtfs):.2f} (target <0.3 GPU)")

        # TTFA via stream
        import websockets
        ttfa = []
        for _ in range(3):
            t = time.perf_counter()
            async with websockets.connect(f"ws://127.0.0.1:8000/api/v1/stream") as ws:
                await ws.send(__import__("json").dumps(
                    {"type": "start", "text": LONG, "voice_id": voice,
                     "settings": {}}))
                first_audio = None
                async for msg in ws:
                    if isinstance(msg, bytes) and first_audio is None:
                        first_audio = time.perf_counter() - t
                    elif isinstance(msg, str) and '"done"' in msg:
                        break
                ttfa.append(first_audio or -1)
        print(f"TTFA median: {statistics.median(ttfa)*1000:.0f} ms "
              f"(target <1000ms GPU)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
