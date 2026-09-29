import json

from google.genai import types

from clients.gemini_client import generate_content, make_cache_key
from observability.tracing import observe
from utils.config import (
    MOCK_LLM,
    PROMPT_VERSION,
    WRITER_FALLBACK_MODEL,
    WRITER_MODEL,
)
from utils.schemas import WriterOutput


@observe(name="writer")
def generate_commentary(writer_input: dict) -> dict:
    """Takes events and context and generates SSML commentary matching the persona."""
    events = writer_input.get("events", [])
    persona = writer_input.get("persona", "hype")
    context = writer_input.get("context", "")
    clip_duration = writer_input.get("clip_duration_seconds", 30.0)

    if MOCK_LLM:
        return WriterOutput.model_validate({
            "commentary_segments": [
                {
                    "timestamp_seconds": events[0]["timestamp_seconds"] if events else 0.5,
                    "persona": persona,
                    "script": "Mock: OH MY GOODNESS, what a play!",
                    "ssml": "<speak>Mock: <emphasis level='strong'>OH MY GOODNESS</emphasis>, what a play!</speak>",
                    "duration_hint_seconds": 3.0,
                },
                {
                    "timestamp_seconds": events[-1]["timestamp_seconds"] if len(events) > 1 else 8.0,
                    "persona": persona,
                    "script": "Mock: He is heating up, folks.",
                    "ssml": "<speak>Mock: He is heating up, folks.</speak>",
                    "duration_hint_seconds": 2.5,
                },
            ]
        }).model_dump()

    if not events:
        # Fallback if no major plays detected
        return WriterOutput(commentary_segments=[{
            "timestamp_seconds": 0.5,  # Right at the start of video
            "persona": persona,
            "script": "No major plays detected in this run. It's a quiet stretch.",
            "ssml": "<speak><prosody rate='medium'>No major plays detected in this run. It's a quiet stretch.</prosody></speak>",
            "duration_hint_seconds": 9.0 / 2.5
        }]).model_dump()

    # System instruction tailored to the persona
    persona_rules = {
        "hype": "You are a legendary, high-energy streetball announcer and NBA hype-man! Think AND1 Tour mixed with Kevin Harlan on steroids. Be explosive, absolutely lose your mind safely on big plays, use authentic basketball slang (e.g., 'caught a body!', 'from the logo!', 'put him in a blender!', 'posterized!'). Use lots of <emphasis level='strong'>, high pitches, and fast <prosody rate='fast' pitch='high'>. Keep it punchy, rhythmic, and incredibly hyped!",
        "analytical": "Calm, ESPN-style, tactical. Use measured pace with <prosody rate='medium'> and focus on facts.",
        "roaster": "Savage, funny, trash-talk. Use dramatic pauses like <break time='500ms'/>, sarcasm, and slow <prosody rate='slow'> for impact."
    }

    rule = persona_rules.get(persona, persona_rules["analytical"])

    prompt = f"""
    You are a professional basketball commentator. Your persona is "{persona}":
    {rule}

    Context: {context}
    The total video is ONLY {clip_duration:.1f} seconds long.

    You must output exactly one commentary segment per event provided below.
    CRITICAL CONSTRAINT: You MUST keep your script short enough so it finishes BEFORE the video ends!
    A normal speaking rate is 2.5 words per second.
    Count your words. If an event happens at {clip_duration - 2.0:.1f}s on a {clip_duration:.1f}s video, your script CANNOT be more than 4 words!

    Make sure your SSML is completely valid (no unclosed tags) and enclosed in <speak>.
    Calculate `duration_hint_seconds` roughly as word count divided by 2.5.

    Events to cover:
    """

    for i, event in enumerate(events):
        prompt += f"\n- [{event['timestamp_seconds']}s] Type: {event['play_type']} | Desc: {event['description']} | Intensity: {event['intensity']}"

    prompt += """

    Return the result as JSON matching the provided response schema (WriterOutput):
    commentary_segments, exactly one per event, each with timestamp_seconds, persona,
    script, ssml and duration_hint_seconds.
    """

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=WriterOutput,
    )

    cache_key = make_cache_key(
        "writer", PROMPT_VERSION, WRITER_MODEL, persona, context,
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
        return WriterOutput.model_validate_json(output_txt).model_dump()
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
                return WriterOutput.model_validate_json(output_txt).model_dump()
            except Exception as fallback_error:
                print(f"Writer Agent fallback model also failed: {fallback_error}")
        # Final canned fallback
        return WriterOutput(commentary_segments=[{
            "timestamp_seconds": events[0]["timestamp_seconds"] if events else 0.5,
            "persona": persona,
            "script": "Wow, what a play!",
            "ssml": "<speak>Wow, what a play!</speak>",
            "duration_hint_seconds": 4.0 / 2.5
        }]).model_dump()
