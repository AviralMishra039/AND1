"""Pure metric functions for the HoopVoice eval harness. No API calls."""

TOLERANCE_SECONDS = 1.5
WORDS_PER_SECOND = 2.5


def match_events(predicted, golden, tolerance_s: float = TOLERANCE_SECONDS):
    """Greedy one-to-one matching: same play_type, closest timestamp within tolerance."""
    used = [False] * len(golden)
    pairs = []
    for p in sorted(predicted, key=lambda e: float(e.get("timestamp_seconds", 0))):
        best_idx, best_delta = None, tolerance_s + 1e-9
        for i, g in enumerate(golden):
            if used[i]:
                continue
            if g.get("play_type") != p.get("play_type"):
                continue
            delta = abs(
                float(g.get("timestamp_seconds", 0)) - float(p.get("timestamp_seconds", 0))
            )
            if delta < best_delta:
                best_idx, best_delta = i, delta
        if best_idx is not None:
            used[best_idx] = True
            pairs.append((p, golden[best_idx], best_delta))
    false_positives = len(predicted) - len(pairs)
    return pairs, false_positives


def event_metrics(predicted, golden, tolerance_s: float = TOLERANCE_SECONDS):
    """Precision / recall / F1 (play_type + time window) and timestamp MAE."""
    pairs, fp = match_events(predicted, golden, tolerance_s)
    tp = len(pairs)
    fn = len(golden) - tp
    precision = (tp / (tp + fp)) if (tp + fp) else (1.0 if not golden else 0.0)
    recall = (tp / (tp + fn)) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    mae = (sum(d for _, _, d in pairs) / len(pairs)) if pairs else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "timestamp_mae_s": mae,
    }


def duration_compliance(segments, clip_duration_seconds: float):
    """Share of booth segments whose estimated speech fits before the clip ends."""
    ok, total = 0, 0
    for seg in segments:
        words = sum(len(str(t.get("text", "")).split()) for t in seg.get("turns", []))
        est = (words / WORDS_PER_SECOND) + 0.3
        total += 1
        if est <= (clip_duration_seconds - float(seg.get("timestamp_seconds", 0))):
            ok += 1
    return {"compliant": ok, "total": total, "rate": (ok / total) if total else None}
