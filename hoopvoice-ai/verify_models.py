"""Sanity-check model names + API key after the SDK migration. Costs ~3 tiny API calls.

Run from the hoopvoice-ai folder:  python verify_models.py
"""
from PIL import Image

from clients.gemini_client import generate_speech, get_client
from google.genai import types
from utils import config
from utils.schemas import Event


def check_text_model(client):
    print(f"[1/3] Text model {config.SCOUT_MODEL} ... ", end="")
    resp = client.models.generate_content(
        model=config.SCOUT_MODEL,
        contents="Reply with the single word: OK",
    )
    print(f"OK -> {resp.text.strip()[:30]!r}")


def check_structured_output(client):
    print(f"[2/3] Structured output (+ image part) on {config.SCOUT_MODEL} ... ", end="")
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
    print(f"[3/3] TTS model {config.TTS_MODEL} ... ", end="")
    pcm, mime = generate_speech(
        "Say in an excited commentator voice: Swish!",
        voice_name=config.PERSONA_VOICE_MAP["hype"],
        style_directive=config.PERSONA_STYLE_DIRECTIVE["hype"],
    )
    import wave

    wav_path = "temp_verify_tts.wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TTS_SAMPLE_RATE)
        w.writeframes(pcm)
    import os

    print(f"OK -> {len(pcm)} PCM bytes, mime {mime!r}, wav {os.path.getsize(wav_path)} bytes")
    os.remove(wav_path)


def main():
    client = get_client()
    check_text_model(client)
    check_structured_output(client)
    check_tts_model(client)
    print("\nAll model names and the API key are working.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nFAILED: {exc}")
        print("If a model name is wrong, override it via env vars (SCOUT_MODEL, TTS_MODEL, ...) and re-run.")
        raise SystemExit(1)
