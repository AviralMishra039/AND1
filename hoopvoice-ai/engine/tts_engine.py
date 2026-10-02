import hashlib
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from pydub import AudioSegment

from clients.gemini_client import generate_speech_multi
from observability.tracing import observe
from utils.config import (
    BOOTH_STYLE_DIRECTIVE,
    BOOTH_VOICE_MAP,
    CACHE_ENABLED,
    CACHE_DIR,
    EDGE_BOOTH_VOICE_MAP,
    MOCK_LLM,
    TTS_CHANNELS,
    TTS_MODEL,
    TTS_SAMPLE_RATE,
    TTS_SAMPLE_WIDTH,
    ensure_dirs,
)
from utils.helpers import strip_ssml

PBP_LABEL = "Speaker 1"
COLOR_LABEL = "Speaker 2"
EDGE_TURN_GAP_MS = 120
WORDS_PER_SECOND = 2.5


def _segment_cache_path(transcript: str, color_persona: str) -> Path:
    voices = f"{BOOTH_VOICE_MAP['play_by_play']}|{BOOTH_VOICE_MAP.get(color_persona, 'Charon')}|{TTS_MODEL}"
    key = hashlib.sha256(f"{transcript}|{voices}".encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"booth_{key}.wav"


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


def _estimate_duration(turns) -> float:
    words = sum(len(str(t.get("text", "")).split()) for t in turns)
    return (words / WORDS_PER_SECOND) + 0.3


def _edge_render(turns, color_persona: str, output_path: str):
    """Free Edge-TTS fallback: render each turn with a distinct voice, concatenate."""
    parts = []
    temp_dir = Path(output_path).parent
    for idx, turn in enumerate(turns):
        text = strip_ssml(str(turn.get("text", ""))).replace("'", "").replace('"', "")
        if not text:
            continue
        if turn.get("speaker") == "play_by_play":
            voice = EDGE_BOOTH_VOICE_MAP["play_by_play"]
        else:
            voice = EDGE_BOOTH_VOICE_MAP.get(color_persona, EDGE_BOOTH_VOICE_MAP["analytical"])

        temp_mp3 = temp_dir / f"edge_turn_{idx}.mp3"
        cmd = [
            sys.executable, "-m", "edge_tts",
            "--voice", voice,
            "--text", text,
            "--write-media", str(temp_mp3),
        ]
        try:
            subprocess.run(cmd, check=True)
            seg = AudioSegment.from_file(str(temp_mp3))
            parts.append(
                seg.set_frame_rate(TTS_SAMPLE_RATE)
                .set_channels(TTS_CHANNELS)
                .set_sample_width(TTS_SAMPLE_WIDTH)
            )
        finally:
            if temp_mp3.exists():
                temp_mp3.unlink()

    if not parts:
        raise RuntimeError("Edge-TTS produced no audio for this segment")

    gap = AudioSegment.silent(duration=EDGE_TURN_GAP_MS, frame_rate=TTS_SAMPLE_RATE)
    gap = gap.set_channels(TTS_CHANNELS).set_sample_width(TTS_SAMPLE_WIDTH)
    mixed = parts[0]
    for part in parts[1:]:
        mixed += gap + part
    mixed.export(output_path, format="wav")


@observe(name="tts")
def render_segment(turns, color_persona: str, output_path: str) -> str:
    """Render one booth segment (list of {speaker, text} turns) to a single WAV.

    Order: disk cache -> Gemini multi-speaker TTS -> Edge-TTS fallback -> silence.
    """
    clean_turns = [
        {
            "speaker": t.get("speaker", "play_by_play"),
            "text": strip_ssml(str(t.get("text", ""))).strip(),
        }
        for t in turns
        if str(t.get("text", "")).strip()
    ]
    if not clean_turns:
        _write_silent_wav(output_path, 1.0)
        return output_path

    if color_persona not in BOOTH_VOICE_MAP:
        color_persona = "analytical"

    transcript = "\n".join(
        f"{PBP_LABEL if t['speaker'] == 'play_by_play' else COLOR_LABEL}: {t['text']}"
        for t in clean_turns
    )
    cache_file = _segment_cache_path(transcript, color_persona)

    if CACHE_ENABLED and cache_file.exists():
        shutil.copyfile(cache_file, output_path)
        print("[tts] Cache hit for booth segment")
        return output_path

    if MOCK_LLM:
        _write_silent_wav(output_path, _estimate_duration(clean_turns))
        return output_path

    # 1. Gemini multi-speaker TTS (both voices in one call)
    try:
        pcm, mime = generate_speech_multi(
            speaker_voices=[
                (PBP_LABEL, BOOTH_VOICE_MAP["play_by_play"]),
                (COLOR_LABEL, BOOTH_VOICE_MAP[color_persona]),
            ],
            transcript=transcript,
            style_directive=BOOTH_STYLE_DIRECTIVE,
        )
        _write_pcm_wav(pcm, output_path, _sample_rate_from_mime(mime))
        if CACHE_ENABLED:
            ensure_dirs()
            shutil.copyfile(output_path, str(cache_file))
        return output_path
    except Exception as e:
        print(f"Gemini multi-speaker TTS failed: {e}. Falling back to Edge-TTS.")

    # 2. Edge-TTS fallback (per-turn voices)
    try:
        _edge_render(clean_turns, color_persona, output_path)
    except Exception as e:
        print(f"Edge-TTS also failed: {e}. Writing silence.")
        _write_silent_wav(output_path, _estimate_duration(clean_turns))

    return output_path
