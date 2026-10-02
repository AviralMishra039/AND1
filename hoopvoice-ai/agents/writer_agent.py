import json

from google.genai import types

from clients.gemini_client import generate_content, make_cache_key
from observability.tracing import observe
from utils.config import (
    MOCK_LLM,
    WRITER_FALLBACK_MODEL,
    WRITER_MODEL,
    WRITER_PROMPT_VERSION,
)
from utils.schemas import BoothOutput

WORDS_PER_SECOND = 2.5
MAX_TURNS_PER_SEGMENT = 4

BOOTH_ROLES = {
    "play_by_play": (
        "PLAY-BY-PLAY, a legendary high-energy streetball announcer with AND1 Mixtape Tour "
        "hype-man energy. Calls the action with explosive slang ('caught a body!', "
        "'from the logo!', 'posterized!')."
    ),
    "analytical": (
        "COLOR COMMENTATOR, calm and tactical in an ESPN style. Reacts with measured "
        "insight, facts, and context."
    ),
    "roaster": (
        "COLOR COMMENTATOR, savage and funny. Reacts with trash talk, sarcasm "
        "and dramatic pauses."
    ),
}


def _color_persona(persona: str) -> str:
    return persona if persona in ("analytical", "roaster") else "roaster"


def _word_budget(clip_duration: float, timestamp: float) -> int:
    available = clip_duration - timestamp - 0.5
    return max(4, int(available * WORDS_PER_SECOND))


def _enforce_word_budget(segments, clip_duration):
    """Hard cap: the SUM of words across a segment's turns must fit before the clip ends."""
    for seg in segments:
        max_words = _word_budget(clip_duration, seg.get("timestamp_seconds", 0.0))
        kept, used = [], 0
        for turn in (seg.get("turns") or [])[:MAX_TURNS_PER_SEGMENT]:
            words = len(str(turn.get("text", "")).split())
            if used + words <= max_words or not kept:
                kept.append(turn)
                used += words
            else:
                print(
                    f"[writer] Dropped turn over word budget ({used + words} > {max_words} "
                    f"words) at {seg.get('timestamp_seconds')}s"
                )
                break
        seg["turns"] = kept
    return segments


def _finalize(booth_output: BoothOutput, clip_duration: float) -> dict:
    data = booth_output.model_dump()
    data["commentary_segments"] = _enforce_word_budget(data["commentary_segments"], clip_duration)
    return data


@observe(name="writer")
def generate_commentary(writer_input: dict) -> dict:
    """Takes events and context and generates two-voice booth banter."""
    events = writer_input.get("events", [])
    persona = _color_persona(writer_input.get("persona", "roaster"))
    context = writer_input.get("context", "")
    clip_duration = writer_input.get("clip_duration_seconds", 30.0)

    if MOCK_LLM:
        first_ts = events[0]["timestamp_seconds"] if events else 0.5
        second_ts = events[-1]["timestamp_seconds"] if len(events) > 1 else min(8.0, first_ts + 4.0)
        return _finalize(BoothOutput.model_validate({
            "commentary_segments": [
                {
                    "timestamp_seconds": first_ts,
                    "persona": persona,
                    "duration_hint_seconds": 4.0,
                    "turns": [
                        {"speaker": "play_by_play", "text": "Mock: OH MY GOODNESS, what a play!"},
                        {"speaker": "color", "text": "Mock: I told you he was heating up."},
                    ],
                },
                {
                    "timestamp_seconds": second_ts,
                    "persona": persona,
                    "duration_hint_seconds": 4.0,
                    "turns": [
                        {"speaker": "color", "text": "Mock: And there it is again."},
                        {"speaker": "play_by_play", "text": "Mock: He is NOT messing around today!"},
                    ],
                },
            ]
        }), clip_duration)

    if not events:
        # Fallback if no major plays detected
        return _finalize(BoothOutput.model_validate({
            "commentary_segments": [{
                "timestamp_seconds": 0.5,
                "persona": persona,
                "duration_hint_seconds": 4.0,
                "turns": [
                    {"speaker": "play_by_play", "text": "No major plays detected in this run. It's a quiet stretch."},
                    {"speaker": "color", "text": "Patience. The game wakes up eventually."},
                ],
            }]
        }), clip_duration)

    pbp_rule = BOOTH_ROLES["play_by_play"]
    color_rule = BOOTH_ROLES[persona]

    prompt = f"""
    You are writing dialogue for a two-person basketball commentary booth.
    - PLAY-BY-PLAY: {pbp_rule}
    - COLOR: {color_rule}

    The two voices riff off each other: reactions, quick analysis, jokes, callbacks to earlier plays.

    Context: {context}
    The total video is ONLY {clip_duration:.1f} seconds long.

    You must output exactly one commentary segment per event provided below.
    Each segment is a short exchange of 1-3 alternating turns between the two voices,
    starting with play_by_play.
    CRITICAL CONSTRAINT: a normal speaking rate is 2.5 words per second. The SUM of all
    turn texts in a segment must finish BEFORE the video ends.
    Count your words. If an event happens at {clip_duration - 2.0:.1f}s on a {clip_duration:.1f}s
    video, the whole exchange CANNOT be more than 4 words total!

    Events to cover:
    """

    for event in events:
        prompt += f"\n- [{event['timestamp_seconds']}s] Type: {event['play_type']} | Desc: {event['description']} | Intensity: {event['intensity']}"

    prompt += f"""

    Return the result as JSON matching the provided response schema (BoothOutput):
    commentary_segments, exactly one per event, each with timestamp_seconds, persona ("{persona}"),
    turns (ordered list of speaker + text) and duration_hint_seconds.
    """

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=BoothOutput,
    )

    cache_key = make_cache_key(
        "writer", WRITER_PROMPT_VERSION, WRITER_MODEL, persona, context,
        json.dumps(events, sort_keys=True), clip_duration,
    )

    try:
        output_txt = generate_content(
            model=WRITER_MODEL,
            contents=prompt,
            config=config,
            area="writer",
            cache_key=cache_key,
        )
        return _finalize(BoothOutput.model_validate_json(output_txt), clip_duration)
    except Exception as primary_error:
        print(f"Writer Agent error on {WRITER_MODEL}: {primary_error}")
        if WRITER_FALLBACK_MODEL and WRITER_FALLBACK_MODEL != WRITER_MODEL:
            try:
                print(f"Writer Agent retrying on fallback model {WRITER_FALLBACK_MODEL}...")
                output_txt = generate_content(
                    model=WRITER_FALLBACK_MODEL,
                    contents=prompt,
                    config=config,
                    area="writer-fallback",
                )
                return _finalize(BoothOutput.model_validate_json(output_txt), clip_duration)
            except Exception as fallback_error:
                print(f"Writer Agent fallback model also failed: {fallback_error}")
        # Final canned fallback
        return _finalize(BoothOutput.model_validate({
            "commentary_segments": [{
                "timestamp_seconds": events[0]["timestamp_seconds"] if events else 0.5,
                "persona": persona,
                "duration_hint_seconds": 2.0,
                "turns": [{"speaker": "play_by_play", "text": "Wow, what a play!"}],
            }]
        }), clip_duration)
