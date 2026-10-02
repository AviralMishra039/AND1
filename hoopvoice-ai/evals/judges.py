"""LLM-as-judge for persona adherence. One cached flash-lite call per unique result."""

import json
from typing import Dict, List

from google.genai import types
from pydantic import BaseModel

from agents.writer_agent import BOOTH_ROLES
from clients.gemini_client import generate_content, make_cache_key
from observability.tracing import observe
from utils.config import MOCK_LLM, WRITER_FALLBACK_MODEL

JUDGE_VERSION = "judge-v1"


class JudgeScore(BaseModel):
    score: int
    reason: str


@observe(name="judge")
def judge_persona_adherence(segments: List[Dict], persona: str) -> Dict:
    """Grade how well the color commentator lines match the persona (1-10)."""
    if MOCK_LLM:
        return {"score": 7, "reason": "Mock judge score."}

    color_lines = [
        str(t.get("text", "")).strip()
        for seg in segments
        for t in seg.get("turns", [])
        if t.get("speaker") == "color" and str(t.get("text", "")).strip()
    ]
    if not color_lines:
        return {"score": None, "reason": "No color commentator lines to judge."}

    rule = BOOTH_ROLES.get(persona, BOOTH_ROLES["roaster"])
    lines_str = "\n".join(f"- {line}" for line in color_lines)
    prompt = f"""
    You are grading a basketball commentary booth's COLOR COMMENTATOR.
    The persona is defined as: {rule}

    Grade how well the lines below match this persona (style, energy, content)
    on a scale of 1-10.

    Color commentator lines:
    {lines_str}

    Return JSON matching the provided schema: score (1-10) and a one-sentence reason.
    """

    cache_key = make_cache_key(
        "judge", JUDGE_VERSION, WRITER_FALLBACK_MODEL, persona,
        json.dumps(segments, sort_keys=True),
    )
    try:
        out = generate_content(
            model=WRITER_FALLBACK_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=JudgeScore,
            ),
            area="eval-judge",
            cache_key=cache_key,
        )
        parsed = JudgeScore.model_validate_json(out)
        return {"score": parsed.score, "reason": parsed.reason}
    except Exception as e:
        print(f"[judge] Persona judge failed: {e}")
        return {"score": None, "reason": f"Judge error: {e}"}
