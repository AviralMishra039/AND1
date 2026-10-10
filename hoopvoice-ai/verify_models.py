"""Sanity-check model names + API key after the SDK migration. Costs ~5 tiny API calls
(includes one short Gemini Live session).

Run from the hoopvoice-ai folder:  python verify_models.py
"""
import asyncio
import io

from PIL import Image

from clients.gemini_client import generate_speech, generate_speech_multi, get_client
from google.genai import types
from utils import config
from utils.schemas import Event


def check_text_model(client):
    print(f"[1/5] Text model {config.SCOUT_MODEL} ... ", end="")
    resp = client.models.generate_content(
        model=config.SCOUT_MODEL,
        contents="Reply with the single word: OK",
    )
    print(f"OK -> {resp.text.strip()[:30]!r}")


def check_structured_output(client):
    print(f"[2/5] Structured output (+ image part) on {config.SCOUT_MODEL} ... ", end="")
    img = Image.new("RGB", (64, 64), color=(210, 180, 120))
    resp = client.models.generate_content(
        model=config.SCOUT_MODEL,
        contents=[
            "This is a placeholder image. Return one fictional basketball event at 4.5s.",
            "Frame taken at 4.5 seconds:",
            img,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Event,
        ),
    )
    event = Event.model_validate_json(resp.text)
    print(f"OK -> {event.play_type} @ {event.timestamp_seconds}s, intensity {event.intensity}")


def check_tts_model(client):
    print(f"[3/5] Single-speaker TTS model {config.TTS_MODEL} ... ", end="")
    pcm, mime = generate_speech(
        "Say in an excited commentator voice: Swish!",
        voice_name=config.BOOTH_VOICE_MAP["play_by_play"],
    )
    import os
    import wave

    wav_path = "temp_verify_tts.wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TTS_SAMPLE_RATE)
        w.writeframes(pcm)
    print(f"OK -> {len(pcm)} PCM bytes, mime {mime!r}, wav {os.path.getsize(wav_path)} bytes")
    os.remove(wav_path)


def check_multi_speaker_tts(client):
    print(f"[4/5] Multi-speaker TTS on {config.TTS_MODEL} ... ", end="")
    pcm, mime = generate_speech_multi(
        speaker_voices=[
            ("Speaker 1", config.BOOTH_VOICE_MAP["play_by_play"]),
            ("Speaker 2", config.BOOTH_VOICE_MAP["roaster"]),
        ],
        transcript=(
            "Speaker 1: Swish! From the logo!\n"
            "Speaker 2: Cold-blooded. That is what practice looks like."
        ),
        style_directive=config.BOOTH_STYLE_DIRECTIVE,
    )
    import os
    import wave

    wav_path = "temp_verify_booth.wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TTS_SAMPLE_RATE)
        w.writeframes(pcm)
    print(f"OK -> {len(pcm)} PCM bytes, mime {mime!r}, wav {os.path.getsize(wav_path)} bytes")
    os.remove(wav_path)


def check_live_model(client):
    print(f"[5/5] Live model {config.LIVE_MODEL} (video in / audio out) ... ", end="")

    async def run():
        img = Image.new("RGB", (320, 180), color=(120, 90, 60))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)

        async with client.aio.live.connect(
            model=config.LIVE_MODEL,
            config=types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=(
                    "You are testing a live basketball commentator link. "
                    "Say one short excited basketball phrase."
                ),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=config.BOOTH_VOICE_MAP["play_by_play"]
                        )
                    )
                ),
            ),
        ) as session:
            await session.send_realtime_input(
                video=types.Blob(mime_type="image/jpeg", data=buf.getvalue())
            )
            received = 0
            async for message in session.receive():
                server_content = getattr(message, "server_content", None)
                if server_content is not None:
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn is not None:
                        for part in model_turn.parts or []:
                            inline = getattr(part, "inline_data", None)
                            if inline is not None and inline.data:
                                received += len(inline.data)
                if received and getattr(message, "turn_complete", False):
                    break
            return received

    received = asyncio.run(asyncio.wait_for(run(), timeout=30))
    if not received:
        raise RuntimeError("Live session connected but returned no audio")
    print(f"OK -> {received} PCM bytes received live")


def main():
    client = get_client()
    check_text_model(client)
    check_structured_output(client)
    check_tts_model(client)
    check_multi_speaker_tts(client)
    check_live_model(client)
    print("\nAll model names and the API key are working.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nFAILED: {exc}")
        print("If a model name is wrong, override it via env vars (SCOUT_MODEL, TTS_MODEL, LIVE_MODEL, ...) and re-run.")
        raise SystemExit(1)
