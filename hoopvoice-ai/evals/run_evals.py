"""HoopVoice eval harness.

Usage (from the hoopvoice-ai folder):
  python -m evals.run_evals                       # all suites, all golden clips
  python -m evals.run_evals --suite scout         # scout | writer | full | all
  python -m evals.run_evals --clip original_clip  # single clip

Free-tier friendly: cached stages cost 0 API calls; the only fresh call is usually
the persona judge (one flash-lite call per unique result, then cached).
With LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY configured, results are also synced
to a Langfuse dataset run; otherwise a local scorecard is printed.
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from agents.scout_agent import analyze_video
from clients.gemini_client import request_summary
from engine.video_engine import assemble_final_video
from evals.judges import judge_persona_adherence
from evals.metrics import duration_compliance, event_metrics
from observability.tracing import flush, langfuse_client
from state.graph import run_pipeline
from utils import config

DATASET_FILE = Path(__file__).resolve().parent / "dataset" / "golden_clips.json"
SUITES = ("scout", "writer", "full")


def _calls_delta(before: dict) -> dict:
    after = request_summary()
    delta = {}
    for area, count in after.items():
        used = count - before.get(area, 0)
        if used > 0:
            delta[area] = used
    return delta


def execute_suite_task(suite: str, clip: dict) -> dict:
    """Run one suite against one golden clip; returns metrics + run artifacts."""
    clip_path = str(config.REPO_ROOT / clip["path"])
    persona = clip.get("persona", "roaster")
    golden_events = clip.get("golden_events", [])

    results = {"suite": suite, "clip": clip["name"], "persona": persona}
    calls_before = request_summary()
    t_start = time.perf_counter()

    if suite == "scout":
        scout = analyze_video(clip_path)
        events = scout.get("events", [])
        results["event_metrics"] = event_metrics(events, golden_events)
        results["predicted_events"] = len(events)
        results["clip_duration_seconds"] = scout.get("clip_duration_seconds")
    else:
        state = run_pipeline(clip_path, persona)
        events = state.get("events", [])
        segments = state.get("commentary_segments", [])
        duration = state.get("clip_duration_seconds", clip.get("clip_duration_seconds", 30.0))
        results["event_metrics"] = event_metrics(events, golden_events)
        results["predicted_events"] = len(events)
        results["segments"] = len(segments)
        results["duration_compliance"] = duration_compliance(segments, duration)
        results["persona_judge"] = judge_persona_adherence(segments, persona)
        if suite == "full":
            temp_dir = config.BASE_DIR / "temp" / f"eval_{clip['name']}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            eval_input = temp_dir / "input.mp4"
            shutil.copyfile(clip_path, eval_input)
            output_path = temp_dir / "output.mp4"
            assemble_final_video(str(eval_input), segments, str(output_path), str(temp_dir))
            results["output_bytes"] = output_path.stat().st_size if output_path.exists() else 0

    results["latency_s"] = round(time.perf_counter() - t_start, 2)
    results["api_calls"] = _calls_delta(calls_before)
    return results


def _fmt(value, pattern="{:.4f}"):
    return "n/a" if value is None else pattern.format(value)


def _mean(values):
    values = [v for v in values if v is not None]
    return (sum(values) / len(values)) if values else None


def print_scorecard(results, langfuse_on: bool):
    print()
    print("=" * 64)
    print(" HOOPVOICE EVAL SCORECARD")
    print(f" langfuse: {'on' if langfuse_on else 'off (set LANGFUSE_* keys to enable)'}")
    print("=" * 64)
    for r in results:
        print(f"\nSuite: {r['suite']} | Clip: {r['clip']} | Persona: {r['persona']}")
        em = r.get("event_metrics") or {}
        if em:
            print(f"  event_precision      : {_fmt(em.get('precision'))}  (TP {em.get('tp')} / FP {em.get('fp')} / FN {em.get('fn')})")
            print(f"  event_recall         : {_fmt(em.get('recall'))}")
            print(f"  event_f1             : {_fmt(em.get('f1'))}")
            print(f"  timestamp_mae_s      : {_fmt(em.get('timestamp_mae_s'), '{:.3f}')}")
        dc = r.get("duration_compliance") or {}
        if dc:
            print(f"  duration_compliance  : {dc.get('compliant')}/{dc.get('total')} ({_fmt(dc.get('rate'))})")
        pj = r.get("persona_judge") or {}
        if pj:
            print(f"  persona_adherence    : {pj.get('score') if pj.get('score') is not None else 'n/a'}/10  {str(pj.get('reason', ''))[:70]}")
        if r.get("output_bytes") is not None:
            print(f"  output_bytes         : {r.get('output_bytes')}")
        print(f"  latency_s            : {r.get('latency_s')}")
        print(f"  api_calls            : {r.get('api_calls')}")

    print()
    print(" TOTALS (mean across clips)")
    by_suite = {}
    for r in results:
        by_suite.setdefault(r["suite"], []).append(r)
    for suite, rs in sorted(by_suite.items()):
        ems = [r.get("event_metrics") or {} for r in rs]
        dcs = [r.get("duration_compliance") or {} for r in rs]
        pjs = [r.get("persona_judge") or {} for r in rs]
        print(f"  [{suite}]")
        print(f"    event_f1           : {_fmt(_mean([e.get('f1') for e in ems]))}")
        print(f"    timestamp_mae_s    : {_fmt(_mean([e.get('timestamp_mae_s') for e in ems]), '{:.3f}')}")
        if any(dcs):
            print(f"    duration_compliance: {_fmt(_mean([d.get('rate') for d in dcs if d]))}")
        if any(pjs):
            print(f"    persona_adherence  : {_fmt(_mean([p.get('score') for p in pjs if p]), '{:.1f}')}")
        print(f"    latency_s          : {_fmt(_mean([r.get('latency_s') for r in rs]), '{:.2f}')}")
    print("=" * 64)


def _ensure_langfuse_dataset(client, golden, clips):
    dataset_name = golden["dataset_name"]
    known = set()
    try:
        dataset = client.get_dataset(dataset_name)
        for item in dataset.items:
            if isinstance(item.input, dict):
                known.add(item.input.get("clip"))
    except Exception:
        try:
            client.create_dataset(name=dataset_name, description=golden.get("description"))
        except Exception as e:
            print(f"[evals] Could not create Langfuse dataset: {e}")

    for clip in clips:
        if clip["name"] in known:
            continue
        try:
            client.create_dataset_item(
                dataset_name=dataset_name,
                input={"clip": clip["name"], "clip_spec": clip},
                expected_output={"golden_events": clip.get("golden_events", [])},
                metadata={"persona": clip.get("persona")},
            )
            print(f"[evals] Created Langfuse dataset item for clip '{clip['name']}'.")
        except Exception as e:
            print(f"[evals] Could not create dataset item for '{clip['name']}': {e}")


def make_task(suite):
    def task(*, item, **kwargs):
        clip = item.input.get("clip_spec") if isinstance(item.input, dict) else None
        if clip is None:
            raise ValueError("Dataset item input is missing 'clip_spec'.")
        return execute_suite_task(suite, clip)

    return task


def make_evaluator():
    def evaluator(*, output, expected_output=None, **kwargs):
        entries = []
        em = (output or {}).get("event_metrics") or {}
        for key in ("precision", "recall", "f1"):
            if em.get(key) is not None:
                entries.append({"name": f"event_{key}", "value": round(em[key], 4)})
        if em.get("timestamp_mae_s") is not None:
            entries.append({"name": "timestamp_mae_s", "value": round(em["timestamp_mae_s"], 3)})
        dc = (output or {}).get("duration_compliance") or {}
        if dc.get("rate") is not None:
            entries.append({"name": "duration_compliance_rate", "value": round(dc["rate"], 4)})
        pj = (output or {}).get("persona_judge") or {}
        if pj.get("score") is not None:
            entries.append({"name": "persona_adherence", "value": pj["score"]})
        if (output or {}).get("latency_s") is not None:
            entries.append({"name": "latency_s", "value": output["latency_s"]})
        return entries

    return evaluator


def run_langfuse_experiments(client, golden, suites, clips):
    dataset_name = golden["dataset_name"]
    _ensure_langfuse_dataset(client, golden, clips)
    for suite in suites:
        try:
            dataset = client.get_dataset(dataset_name)
            if not dataset.items:
                print(f"[evals] Langfuse dataset '{dataset_name}' has no items; skipping {suite}.")
                continue
            result = dataset.run_experiment(
                name=f"hoopvoice-{suite}",
                task=make_task(suite),
                evaluators=[make_evaluator()],
                max_concurrency=1,
                metadata={"suite": suite, "mode": "eval"},
            )
            url = getattr(result, "dataset_run_url", None)
            if url is None and isinstance(result, dict):
                url = result.get("dataset_run_url")
            print(f"[evals] Langfuse dataset run for suite '{suite}': {url}")
            fmt = getattr(result, "format", None)
            if callable(fmt):
                print(fmt())
        except Exception as e:
            print(f"[evals] Langfuse experiment for '{suite}' failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="HoopVoice eval harness")
    parser.add_argument("--suite", choices=["scout", "writer", "full", "all"], default="all")
    parser.add_argument("--clip", default="all", help="Clip name or 'all'")
    args = parser.parse_args()

    golden = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    clips = golden.get("clips", [])
    if args.clip != "all":
        clips = [c for c in clips if c.get("name") == args.clip]
        if not clips:
            known = [c.get("name") for c in golden.get("clips", [])]
            print(f"No golden clip named '{args.clip}'. Known: {known}")
            raise SystemExit(1)

    suites = list(SUITES) if args.suite == "all" else [args.suite]

    client = langfuse_client()
    if client is not None:
        run_langfuse_experiments(client, golden, suites, clips)
        flush()
        return

    results = []
    for suite in suites:
        for clip in clips:
            print(f"[evals] Running suite '{suite}' on clip '{clip.get('name')}' ...")
            results.append(execute_suite_task(suite, clip))
    print_scorecard(results, langfuse_on=False)
    flush()


if __name__ == "__main__":
    main()
