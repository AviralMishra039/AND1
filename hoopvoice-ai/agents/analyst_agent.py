from typing import Dict, List

from observability.tracing import observe


@observe(name="analyst")
def compute_game_metrics(events: List[Dict]) -> Dict:
    """Derive momentum/streak metrics from the event log (moved from state/graph.py)."""
    intensity_trend = [event.get("intensity", 5) for event in events][-5:]

    # Calculate simple momentum based on trend slope
    if len(intensity_trend) >= 2:
        if intensity_trend[-1] > intensity_trend[0]:
            momentum = "rising"
        elif intensity_trend[-1] < intensity_trend[0]:
            momentum = "falling"
        else:
            momentum = "neutral"
    else:
        momentum = "neutral"

    scoring_streak = sum(1 for e in events if e.get("play_type") in ["dunk", "three_pointer"])

    play_types = [e.get("play_type", "other") for e in events]
    if play_types:
        dominant_play_type = max(set(play_types), key=play_types.count)
    else:
        dominant_play_type = "none"

    return {
        "intensity_trend": intensity_trend,
        "momentum": momentum,
        "scoring_streak": scoring_streak,
        "dominant_play_type": dominant_play_type,
    }
