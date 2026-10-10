"""Gemini Live API: real-time commentary session manager.

A thin, separate path (not through LangGraph): browser frames go in via the
FastAPI websocket, commentary audio comes back in real time.
"""

import asyncio
import base64
import json
import time

from google.genai import types

from clients.gemini_client import get_client
from observability.tracing import observe, tag_trace
from utils.config import BOOTH_VOICE_MAP, LIVE_MAX_SESSION_SECONDS, LIVE_MODEL

LIVE_PERSONA_RULES = {
    "play_by_play": (
        "You are a legendary, high-energy streetball announcer — an AND1 Mixtape Tour "
        "hype man — providing LIVE commentary on a basketball game you are watching "
        "through a live video feed. Keep your commentary punchy and short (1-3 sentences "
        "at a time) and react instantly to what you see: made shots, misses, blocks, "
        "steals, rebounds, handles, the crowd, the vibe. Use authentic basketball slang: "
        "'caught a body!', 'from the logo!', 'put him in a blender!', 'posterized!', "
        "'he's heating up!'. When the feed is quiet, briefly hype the atmosphere or set "
        "the scene. Never mention being an AI. You are the voice of the court."
    ),
    "analytical": (
        "You are a calm, tactical ESPN-style basketball analyst providing LIVE commentary "
        "on a basketball game you are watching through a live video feed. Keep your "
        "remarks short (1-3 sentences at a time) and grounded in what you actually see: "
        "spacing, angles, shot selection, defensive rotation. When the feed is quiet, add "
        "brief context rather than filler. Never mention being an AI."
    ),
    "roaster": (
        "You are a savage-but-lovable basketball roaster providing LIVE commentary on a "
        "basketball game you are watching through a live video feed. React with short "
        "(1-3 sentences) sarcastic jabs and playful trash talk about what you see: "
        "bricks, travels, questionable handles, defenders in the wrong zip code. Keep it "
        "funny, never cruel. When the feed is quiet, roast the empty gym or the "
        "camerawork. Never mention being an AI."
    ),
}

_active = False


def _system_instruction(persona: str) -> str:
    rule = LIVE_PERSONA_RULES.get(persona, LIVE_PERSONA_RULES["play_by_play"])
    return rule + " Audio is your only output; keep each turn short and natural."


async def _send(websocket, payload: dict):
    try:
        await websocket.send_text(json.dumps(payload))
    except Exception:
        pass


@observe(name="live")
async def run_live_session(websocket, persona: str) -> None:
    """Bridge the browser websocket and the Gemini Live session for one live run."""
    global _active
    if _active:
        raise RuntimeError("A live session is already active. One at a time on the free tier.")

    _active = True
    started = time.time()
    try:
        client = get_client()
        voice = BOOTH_VOICE_MAP.get(persona, BOOTH_VOICE_MAP["play_by_play"])
        tag_trace(input={"mode": "live", "persona": persona, "voice": voice, "model": LIVE_MODEL})

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=_system_instruction(persona),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        )

        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await _send(websocket, {
                "type": "started",
                "persona": persona,
                "voice": voice,
                "model": LIVE_MODEL,
                "max_seconds": LIVE_MAX_SESSION_SECONDS,
            })

            async def gemini_to_browser():
                async for message in session.receive():
                    server_content = getattr(message, "server_content", None)
                    if server_content is not None:
                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn is not None:
                            for part in model_turn.parts or []:
                                inline = getattr(part, "inline_data", None)
                                if inline is not None and inline.data:
                                    await _send(websocket, {
                                        "type": "audio",
                                        "mime": inline.mime_type or "audio/pcm;rate=24000",
                                        "data": base64.b64encode(inline.data).decode("ascii"),
                                    })
                                elif part.text:
                                    await _send(websocket, {"type": "transcript", "text": part.text})
                        transcription = getattr(server_content, "output_transcription", None)
                        if transcription is not None and getattr(transcription, "text", None):
                            await _send(websocket, {
                                "type": "transcript",
                                "text": transcription.text,
                            })

                    if getattr(message, "go_away", None):
                        await _send(websocket, {
                            "type": "warning",
                            "message": "The Live API session is nearing its limit and will close soon.",
                        })
                        return
                    if getattr(message, "turn_complete", False):
                        await _send(websocket, {"type": "turn_complete"})
                    if getattr(message, "interruption", False):
                        await _send(websocket, {"type": "interrupted"})

            async def browser_to_gemini():
                while True:
                    raw = await websocket.receive_text()
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    kind = msg.get("type")
                    if kind == "frame" and msg.get("data"):
                        jpeg = base64.b64decode(msg["data"])
                        await session.send_realtime_input(
                            video=types.Blob(mime_type="image/jpeg", data=jpeg)
                        )
                    elif kind == "text" and str(msg.get("text", "")).strip():
                        await session.send_realtime_input(text=str(msg["text"]))
                    elif kind == "stop":
                        return

            gemini_task = asyncio.create_task(gemini_to_browser())
            browser_task = asyncio.create_task(browser_to_gemini())
            try:
                done, pending = await asyncio.wait(
                    [gemini_task, browser_task],
                    timeout=LIVE_MAX_SESSION_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                elapsed = round(time.time() - started, 1)
                if browser_task in done:
                    reason = "stopped"
                elif not done:
                    reason = "timeout"
                else:
                    reason = "completed"
                for task in pending:
                    task.cancel()
                for task in done:
                    if not task.cancelled():
                        exc = task.exception()
                        if exc is not None:
                            raise exc
                await _send(websocket, {"type": "ended", "reason": reason, "elapsed_s": elapsed})
            finally:
                for task in (gemini_task, browser_task):
                    if not task.done():
                        task.cancel()
    finally:
        _active = False
