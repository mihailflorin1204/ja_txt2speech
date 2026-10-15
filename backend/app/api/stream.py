"""Streaming synthesis over WebSocket (spec §5.3).

Client -> {"type":"start","text","voice_id","settings"} | {"type":"stop"}
Server -> {"type":"format",...} then per sentence {"type":"sentence",...}
followed by one binary frame (4-byte LE sentence index + PCM s16le),
then {"type":"done"} or {"type":"error",...}.
"""

import asyncio
import logging
import struct

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.audio import TARGET_SR, resample
from app.core.config import get_settings
from app.engines.base import SynthesisSettings
from app.engines.router import get_router
from app.text.analyzer import analyze_text
from app.text.dictionary import apply_user_dictionary

log = logging.getLogger("api.stream")
router = APIRouter(tags=["stream"])


async def _stream_synth(ws: WebSocket, start: dict, stop_event: asyncio.Event) -> None:
    text = start.get("text", "")
    voice_id = start.get("voice_id")
    settings = SynthesisSettings(**(start.get("settings") or {}))
    if not text or not voice_id:
        await ws.send_json({"type": "error", "code": "VALIDATION_ERROR",
                            "message": "start requires text and voice_id"})
        return
    if len(text) > get_settings().max_interactive_chars:
        await ws.send_json({"type": "error", "code": "LONG_TEXT",
                            "message": "use a long-text job for input over "
                                       f"{get_settings().max_interactive_chars} chars"})
        return

    router = get_router()
    utterances = apply_user_dictionary(analyze_text(text))

    await ws.send_json({"type": "format", "sample_rate": TARGET_SR,
                        "channels": 1, "encoding": "pcm_s16le"})
    for i, utt in enumerate(utterances):
        if stop_event.is_set():
            break
        try:
            chunk = await router.synthesize(utt, voice_id,
                                            settings.merged_with(utt.settings))
        except Exception as e:  # noqa: BLE001
            await ws.send_json({"type": "error", "code": "ENGINE_ERROR",
                                "message": str(e)})
            return
        samples = resample(chunk.to_float32(), chunk.sample_rate, TARGET_SR)
        pcm = (samples.clip(-1, 1) * 32767).astype("int16").tobytes()
        await ws.send_json({"type": "sentence", "index": i, "text": utt.text})
        await ws.send_bytes(struct.pack("<I", i) + pcm)
    await ws.send_json({"type": "done"})


@router.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    stop_event = asyncio.Event()
    synth_task: asyncio.Task | None = None
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "start":
                stop_event.clear()
                if synth_task and not synth_task.done():
                    synth_task.cancel()
                synth_task = asyncio.create_task(_stream_synth(ws, msg, stop_event))
            elif mtype == "stop":
                stop_event.set()
                if synth_task and not synth_task.done():
                    synth_task.cancel()
                    synth_task = None
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        if synth_task and not synth_task.done():
            synth_task.cancel()
