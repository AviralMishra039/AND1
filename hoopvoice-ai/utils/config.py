import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Locate .env: prefer cwd, then hoopvoice-ai/, then repo root
for _candidate in [Path.cwd() / ".env", BASE_DIR / ".env", REPO_ROOT / ".env"]:
    if _candidate.exists():
        load_dotenv(_candidate)
        break

# --- Feature flags ---
MOCK_LLM = os.getenv("MOCK_LLM", "0") == "1"
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1") == "1"
TRACING_ENABLED = (
    os.getenv("TRACING_ENABLED", "1") == "1"
    and bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
    and bool(os.getenv("LANGFUSE_SECRET_KEY"))
)

# --- Disk cache ---
CACHE_DIR = BASE_DIR / "cache"

# --- Models (verify names after any change: python verify_models.py) ---
SCOUT_MODEL = os.getenv("SCOUT_MODEL", "gemini-2.5-flash")
WRITER_MODEL = os.getenv("WRITER_MODEL", "gemini-2.5-flash")
WRITER_FALLBACK_MODEL = os.getenv("WRITER_FALLBACK_MODEL", "gemini-2.5-flash-lite")
TTS_MODEL = os.getenv("TTS_MODEL", "gemini-2.5-flash-preview-tts")

# --- Free-tier request budget ---
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))
RETRY_BACKOFF_BASE_SECONDS = float(os.getenv("RETRY_BACKOFF_BASE_SECONDS", "15"))
MAX_REQUESTS_PER_RUN = int(os.getenv("MAX_REQUESTS_PER_RUN", "40"))
TTS_MAX_SEGMENTS = int(os.getenv("TTS_MAX_SEGMENTS", "8"))

# --- Files API video upload ---
FILES_POLL_INTERVAL_SECONDS = float(os.getenv("FILES_POLL_INTERVAL_SECONDS", "2"))
FILES_POLL_TIMEOUT_SECONDS = float(os.getenv("FILES_POLL_TIMEOUT_SECONDS", "180"))

# Bump when prompts change (invalidates the scout/writer disk cache)
PROMPT_VERSION = "phase1-v1"

# --- Persona voices (Gemini prebuilt TTS voices) ---
PERSONA_VOICE_MAP = {
    "hype": "Fenrir",
    "analytical": "Charon",
    "roaster": "Puck",
}

PERSONA_STYLE_DIRECTIVE = {
    "hype": "Say like an explosive streetball hype-man announcer, maximum energy:",
    "analytical": "Say like a calm, measured ESPN-style tactical analyst:",
    "roaster": "Say like a savage, sarcastic trash-talking commentator:",
}

# --- Edge-TTS fallback voices (used when Gemini TTS quota is exhausted) ---
EDGE_VOICE_MAP = {
    "hype": "en-US-ChristopherNeural",
    "analytical": "en-US-SteffanNeural",
    "roaster": "en-US-GuyNeural",
}

# --- Gemini TTS audio format ---
TTS_SAMPLE_RATE = 24000
TTS_SAMPLE_WIDTH = 2
TTS_CHANNELS = 1


def ensure_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
