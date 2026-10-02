import hashlib
import json
import os
import random
import threading
import time

from google import genai
from google.genai import types

from utils.config import (
    CACHE_ENABLED,
    CACHE_DIR,
    FILES_POLL_INTERVAL_SECONDS,
    FILES_POLL_TIMEOUT_SECONDS,
    MAX_REQUESTS_PER_RUN,
    RETRY_ATTEMPTS,
    RETRY_BACKOFF_BASE_SECONDS,
    TTS_MODEL,
    ensure_dirs,
)

_client = None
_client_lock = threading.Lock()

_request_counts = {}
_request_lock = threading.Lock()


class BudgetExceededError(RuntimeError):
    """Raised when a run exceeds MAX_REQUESTS_PER_RUN Gemini calls."""


def get_client():
    """Singleton genai.Client — the only place the API key is read."""
    global _client
    with _client_lock:
        if _client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in environment variables.")
            _client = genai.Client(api_key=api_key)
        return _client


def make_cache_key(*parts) -> str:
    """Stable cache key from arbitrary parts (prompt version, model, inputs...)."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]


def _cache_file(key: str):
    return CACHE_DIR / f"llm_{key}.json"


def _read_cache(key):
    try:
        with open(_cache_file(key), "r", encoding="utf-8") as f:
            return json.load(f).get("text")
    except Exception:
        return None


def _write_cache(key, text):
    try:
        ensure_dirs()
        with open(_cache_file(key), "w", encoding="utf-8") as f:
            json.dump({"text": text}, f)
    except Exception as e:
        print(f"[gemini-client] Cache write skipped: {e}")


def _count_request(area: str):
    with _request_lock:
        _request_counts[area] = _request_counts.get(area, 0) + 1
        total = sum(_request_counts.values())
        if total > MAX_REQUESTS_PER_RUN:
            raise BudgetExceededError(
                f"Request budget exceeded ({total} > {MAX_REQUESTS_PER_RUN}). "
                "Raise MAX_REQUESTS_PER_RUN or rely on cache."
            )
        return total


def _is_rate_limit_error(exc) -> bool:
    code = getattr(exc, "code", None)
    if code is not None and str(code) == "429":
        return True
    text = str(exc).lower()
    return "quota" in text or "resource_exhausted" in text or "rate limit" in text or "429" in text


def _state_str(state) -> str:
    # Normalizes both enum values and str() forms (e.g. "FileState.PROCESSING")
    value = getattr(state, "value", state)
    return str(value).upper().split(".")[-1]


def _video_ref_path(video_hash: str):
    return CACHE_DIR / f"video_{video_hash}.json"


def _read_video_ref(video_hash: str):
    try:
        with open(_video_ref_path(video_hash), "r", encoding="utf-8") as f:
            return json.load(f).get("name")
    except Exception:
        return None


def _write_video_ref(video_hash, name):
    try:
        ensure_dirs()
        with open(_video_ref_path(video_hash), "w", encoding="utf-8") as f:
            json.dump({"name": name}, f)
    except Exception as e:
        print(f"[gemini-client] Video ref write skipped: {e}")


def get_or_upload_video(video_path: str, video_hash: str):
    """Reuse an uploaded Files-API video when possible; otherwise upload and poll to ACTIVE."""
    client = get_client()

    name = _read_video_ref(video_hash)
    if name:
        try:
            existing = client.files.get(name=name)
            if _state_str(existing.state) == "ACTIVE":
                print(f"[gemini-client] Reusing uploaded video {name}")
                return existing
        except Exception:
            pass  # file expired or was deleted; fall through to a fresh upload

    last_error = None
    for attempt in (1, 2):
        try:
            print(f"[gemini-client] Uploading video for analysis (attempt {attempt}/2)...")
            video_file = client.files.upload(file=video_path)
            elapsed = 0.0
            while _state_str(video_file.state) == "PROCESSING":
                if elapsed >= FILES_POLL_TIMEOUT_SECONDS:
                    raise TimeoutError(
                        f"Video processing timed out after {FILES_POLL_TIMEOUT_SECONDS:.0f}s"
                    )
                time.sleep(FILES_POLL_INTERVAL_SECONDS)
                elapsed += FILES_POLL_INTERVAL_SECONDS
                video_file = client.files.get(name=video_file.name)
            if _state_str(video_file.state) != "ACTIVE":
                raise RuntimeError(f"Uploaded video ended in state {_state_str(video_file.state)}")
            _write_video_ref(video_hash, video_file.name)
            return video_file
        except Exception as exc:
            last_error = exc
            print(f"[gemini-client] Video upload failed: {exc}")
            if attempt == 1:
                time.sleep(2.0)
    raise last_error


def generate_content(model, contents, config=None, area="default", cache_key=None) -> str:
    """Funnel for all text Gemini calls: budget guard + retry/backoff + disk cache."""
    if cache_key and CACHE_ENABLED:
        cached = _read_cache(cache_key)
        if cached is not None:
            print(f"[gemini-client] Cache hit for {area}")
            return cached

    client = get_client()
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            _count_request(area)
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            text = response.text
            if cache_key and CACHE_ENABLED and text:
                _write_cache(cache_key, text)
            return text
        except BudgetExceededError:
            raise
        except Exception as exc:
            last_error = exc
            if _is_rate_limit_error(exc) and attempt < RETRY_ATTEMPTS:
                sleep_for = RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 5)
                print(
                    f"[gemini-client] Rate limited on {model} "
                    f"(attempt {attempt}/{RETRY_ATTEMPTS}), retrying in {sleep_for:.0f}s"
                )
                time.sleep(sleep_for)
            else:
                break
    raise last_error


def _tts_generate(prompt, tts_config, model=TTS_MODEL, area="tts"):
    """Shared TTS call: budget guard + retry on transient/empty responses."""
    client = get_client()
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            _count_request(area)
            response = client.models.generate_content(
                model=model, contents=prompt, config=tts_config
            )
            # Transient empty responses happen on the preview TTS models; treat as retryable
            part = None
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    part = candidate.content.parts[0]
            if part is None or not getattr(part, "inline_data", None) or not part.inline_data.data:
                raise ValueError("TTS response contained no audio data")
            return part.inline_data.data, (part.inline_data.mime_type or "")
        except BudgetExceededError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < RETRY_ATTEMPTS:
                if _is_rate_limit_error(exc):
                    sleep_for = RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 5)
                else:
                    sleep_for = 2.0 + random.uniform(0, 3)
                print(
                    f"[gemini-client] TTS attempt {attempt}/{RETRY_ATTEMPTS} failed "
                    f"({exc.__class__.__name__}), retrying in {sleep_for:.0f}s"
                )
                time.sleep(sleep_for)
    raise last_error


def generate_speech(text, voice_name, style_directive="", model=TTS_MODEL, area="tts"):
    """Gemini native single-speaker TTS. Returns (pcm_bytes, mime_type)."""
    prompt = f"{style_directive} {text}".strip()
    tts_config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
    )
    return _tts_generate(prompt, tts_config, model=model, area=area)


def generate_speech_multi(speaker_voices, transcript, style_directive="", model=TTS_MODEL, area="tts"):
    """Gemini native multi-speaker TTS (exactly 2 speakers).

    speaker_voices: list of (speaker_label, voice_name) pairs; labels must match the transcript.
    Returns (pcm_bytes, mime_type).
    """
    prompt = f"{style_directive}\n{transcript}".strip()
    tts_config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(
                        speaker=label,
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        ),
                    )
                    for label, voice in speaker_voices
                ]
            )
        ),
    )
    return _tts_generate(prompt, tts_config, model=model, area=area)


def request_summary() -> dict:
    """Snapshot of Gemini API calls made this process, per budget area."""
    with _request_lock:
        return dict(_request_counts)
