import hashlib
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from pydub import AudioSegment

from clients.gemini_client import generate_speech
from observability.tracing import observe
from utils.config import (
    CACHE_ENABLED,
    CACHE_DIR,
    EDGE_VOICE_MAP,
    MOCK_LLM,
    PERSONA_STYLE_DIRECTIVE,
    PERSONA_VOICE_MAP,
    TTS_CHANNELS,
    TTS_MODEL,
    TTS_SAMPLE_RATE,
    TTS_SAMPLE_WIDTH,
    ensure_dirs,
)
from utils.helpers import calculate_audio_duration, strip_ssml


def _tts_cache_path(text: str, voice: str, directive: str) -> Path:
    key = hashlib.sha256(f"{text}|{voice}|{directive}|{TTS_MODEL}".encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"tts_{key}.wav"


def _write_pcm_wav(pcm: bytes, path: str, sample_rate: int = TTS_SAMPLE_RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(TTS_CHANNELS)
        w.setsampwidth(TTS_SAMPLE_WIDTH)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


def _write_silent_wav(path: str, seconds: float):
    frames = int(max(0.5, seconds) * TTS_SAMPLE_RATE)
    _write_pcm_wav(b"\x00" * frames * TTS_SAMPLE_WIDTH * TTS_CHANNELS, path)


def _sample_rate_from_mime(mime: str) -> int:
    # e.g. "audio/L16;codec=pcm;rate=24000"
    for part in (mime or "").split(";"):
        part = part.strip()
        if part.startswith("rate="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                break
    return TTS_SAMPLE_RATE


def _edge_tts(text: str, persona: str, output_path: str):
    """Free Edge-TTS fallback (writes mp3, converts to wav)."""
    clean_text = text.replace("'", "").replace('"', "")
    voice = EDGE_VOICE_MAP.get(persona, "en-US-ChristopherNeural")

    temp_mp3 = str(Path(output_path).with_suffix(".mp3"))
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", voice,
        "--text", clean_text,
        "--write-media", temp_mp3,
    ]
    try:
        subprocess.run(cmd, check=True)
        AudioSegment.from_file(temp_mp3).export(output_path, format="wav")
    finally:
        if Path(temp_mp3).exists():
            Path(temp_mp3).unlink()


@observe(name="tts")
def generate_voice_audio(text: str, persona: str, output_path: str) -> str:
    """Render one commentary line to a WAV file.

    Order: disk cache -> Gemini native TTS -> Edge-TTS fallback -> silence.
    """
    clean_text = strip_ssml(text)
    voice = PERSONA_VOICE_MAP.get(persona, PERSONA_VOICE_MAP["analytical"])
    directive = PERSONA_STYLE_DIRECTIVE.get(persona, "")

    cache_file = _tts_cache_path(clean_text, voice, directive)

    if CACHE_ENABLED and cache_file.exists():
        shutil.copyfile(cache_file, output_path)
        print(f"[tts] Cache hit for persona '{persona}'")
        return output_path

    if MOCK_LLM:
        _write_silent_wav(output_path, calculate_audio_duration(clean_text))
        return output_path

    # 1. Gemini native TTS (single speaker)
    try:
        pcm, mime = generate_speech(clean_text, voice, directive)
        _write_pcm_wav(pcm, output_path, _sample_rate_from_mime(mime))
        if CACHE_ENABLED:
            ensure_dirs()
            shutil.copyfile(output_path, str(cache_file))
        return output_path
    except Exception as e:
        print(f"Gemini TTS failed: {e}. Falling back to Edge-TTS.")

    # 2. Edge-TTS fallback
    try:
        _edge_tts(clean_text, persona, output_path)
    except Exception as e:
        print(f"Edge-TTS also failed: {e}. Writing silence.")
        _write_silent_wav(output_path, 2.0)

    return output_path
