import hashlib

from google.genai import types

from clients.gemini_client import generate_content, get_or_upload_video, make_cache_key
from observability.tracing import observe
from utils.config import MOCK_LLM, SCOUT_MODEL, SCOUT_PROMPT_VERSION
from utils.schemas import ScoutOutput


def _video_hash(video_path: str) -> str:
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:24]


@observe(name="scout")
def analyze_video(video_path: str) -> dict:
    """Upload the clip via the Files API and extract a structured event log in one call."""
    if MOCK_LLM:
        return ScoutOutput.model_validate({
            "clip_duration_seconds": 15.0,
            "events": [
                {
                    "timestamp_seconds": 4.5,
                    "play_type": "dunk",
                    "description": "Mock: player drives baseline and throws down a two-hand slam",
                    "intensity": 8,
                    "players_involved": ["Player A"],
                },
                {
                    "timestamp_seconds": 12.0,
                    "play_type": "three_pointer",
                    "description": "Mock: deep transition three from the wing",
                    "intensity": 7,
                    "players_involved": ["Player B"],
                },
            ],
        }).model_dump()

    video_hash = _video_hash(video_path)

    prompt = """
    You are an expert basketball scout. Watch the attached basketball clip from start to finish.
    Identify all major plays (dunks, three_pointers, blocks, steals, assists, misses, fouls, or other).

    For each play provide:
    - the EXACT timestamp in seconds on the video's own timeline (do not guess loosely),
    - a short description of what happened,
    - intensity (1-10),
    - players involved (jersey numbers or names if visible).

    If the clip is longer than 30 seconds, only cover the first 30 seconds.
    Set clip_duration_seconds to the total duration of the video in seconds.

    Return the result as JSON matching the provided response schema (ScoutOutput):
    clip_duration_seconds and a list of events, each with timestamp_seconds, play_type,
    description, intensity and players_involved.
    """

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ScoutOutput,
    )
    cache_key = make_cache_key("scout", SCOUT_PROMPT_VERSION, SCOUT_MODEL, video_hash)

    try:
        video_file = get_or_upload_video(video_path, video_hash)
        output_txt = generate_content(
            model=SCOUT_MODEL,
            contents=[prompt, video_file],
            config=config,
            area="scout",
            cache_key=cache_key,
        )
        return ScoutOutput.model_validate_json(output_txt).model_dump()
    except Exception as e:
        print(f"Scout Agent error: {e}")
        # Fallback empty list if error
        return ScoutOutput(clip_duration_seconds=30.0, events=[]).model_dump()
