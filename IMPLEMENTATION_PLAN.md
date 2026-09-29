# HoopVoice AI — Modernization Implementation Plan

**Scope of this upgrade:** native video understanding, `google-genai` SDK migration, two-commentator "Booth Mode", Gemini-native TTS (replacing ElevenLabs), full observability + evals, and real-time Live commentary — all designed to run on a **free Gemini API key**.

---

## 1. Design Principles (the "why" behind every decision)

1. **Free-tier-first engineering.** Every design choice minimizes request count. The pipeline is budgeted to **~8 API calls per video** (1 scout + 1 writer + ~6 TTS), with aggressive disk caching so re-runs during development cost **0 calls**.
2. **Config-driven models.** Model names and rate limits change every few months. Nothing is hardcoded — everything lives in one config file so a model rename is a one-line edit.
3. **Don't break what works.** The LangGraph state machine, the ducking/assembly engine, and both frontends are solid. We surgically replace the perception, writing, and voice layers — the orchestration skeleton stays.
4. **Evals are not optional.** The scout rewrite is validated against a golden dataset *before* we build Live mode on top of it.

---

## 2. Key Decisions & Justification

### D1 — Kill frame extraction, use native video input
**What:** Delete the OpenCV 2fps frame-sampling + manual timestamp interleaving in `scout_agent.py`. Upload the mp4 directly via the Gemini Files API and ask for timestamped events in one call.

**Why:**
- Gemini's video understanding is natively temporal — it returns timestamps grounded in the actual video instead of inferring time from our injected labels. Fewer hallucinations, catches plays our 15-frame sample missed.
- Deletes ~60 lines of brittle code (frame extraction, batching, downsampling math).
- **One request instead of one giant multi-image payload** — better for both quota and latency.

### D2 — Migrate `google-generativeai` → `google-genai` (mandatory, do first)
**Why:** The old SDK is deprecated. The new unified SDK is also the *only* way to get Files API video upload, native TTS, and the Live API — every other item in this plan depends on it. While migrating, switch to **native structured outputs**: pass `ScoutOutput` / new Pydantic schemas directly as `response_schema` instead of prompt-engineering JSON and praying it parses. This eliminates an entire class of fallback-path failures.

### D3 — Booth Mode: one writer call, one multi-speaker TTS call per segment
**What:** A two-voice commentary team — a **Play-by-Play** voice (always the Hype Man energy) and a **Color Commentator** (user picks Analyst or Roaster) — who banter across turns within each segment.

**Why this shape and not two agent calls:**
- Two alternating LLM calls per segment = 2× quota burn and worse coherence (agents can't hear each other mid-thought). One writer call producing a structured **dialogue turn list** keeps banter coherent and costs exactly the same as today's writer.
- Gemini's multi-speaker TTS takes a transcript with speaker labels (`Speaker1: ... / Speaker2: ...`) and a 2-voice config, rendering both voices in **one call with natural turn-taking prosody** — far better than stitching two single-voice clips.
- This *strengthens* the LangGraph story: the Analyst node's momentum/streak state now drives callbacks ("THIRD dunk in a row!") that the two voices react to.

### D4 — Gemini native TTS replaces ElevenLabs; Edge-TTS stays as the free safety net
**Why:** One key for everything (no ELEVENLABS_API_KEY), generous voice catalog (30 prebuilt voices), native multi-speaker support (required for D3), and audio returns as 24kHz PCM WAV — which `pydub` already handles, so the ducking engine needs **zero changes** to its mixing logic. ElevenLabs code is removed; `edge-tts` remains the zero-quota fallback when the free TTS daily cap is hit.

### D5 — Langfuse for observability (over LangSmith)
**Why this over LangSmith:** LangSmith's magic is auto-tracing *LangChain-native* LLM calls — but our Gemini calls are raw SDK calls inside LangGraph nodes, so we'd hand-instrument either way. Langfuse gives us: `@observe()` decorators that wrap any function, trace-per-pipeline-run, **datasets + scoring built-in** (needed for the eval harness), a free cloud tier, and a self-host option that is free forever with no trace caps. No vendor lock-in to LangChain.

### D6 — Live Mode is a separate thin path, built last
**Why last and separate:** Live (Gemini Live API) is bidirectional streaming with hard free-tier session limits — architecturally different from the batch pipeline. It reuses D1's prompts and D4's voice personas but does not go through LangGraph (a stateful post-game render doesn't make sense mid-stream). Building it after the core is rebuilt and eval'd means Live inherits a validated perception layer instead of doubling our debugging surface.

---

## 3. Rate-Limit & Quota Strategy (free key survival kit)

Approximate free-tier ceilings (verify current numbers at implementation time — they change): Flash ~10 RPM / ~250 requests-day; TTS and Live have their own, tighter caps.

The strategy is four layers:

1. **Central client wrapper** (`clients/gemini_client.py`) — the *only* module that talks to Google. Provides: retry with exponential backoff + jitter on 429s, a per-run request counter with a hard budget guard, and a model downgrade chain (e.g., writer falls back to a lighter Flash variant when the primary is exhausted).
2. **Disk cache** (`cache/`, gitignored):
   - Scout/Writer outputs keyed by `sha256(video_bytes + prompt_version)` → during dev, re-running the same clip 50 times costs 1 run's quota.
   - TTS audio keyed by `sha256(text + voice + model)` → editing one segment's script never re-renders the others.
3. **Mock mode** (`MOCK_LLM=1`) — returns canned scout/writer/TTS fixtures so frontend and ducking work burns **zero** API calls.
4. **Per-video call budget:** 1 scout + 1 writer + ≤8 TTS segments ≈ 10 calls/run → ~20 full runs/day of headroom even before caching.

---

## 4. Target Architecture (after the upgrade)

```
hoopvoice-ai/
├── clients/
│   └── gemini_client.py     # NEW — central SDK client, retry/backoff, budget guard, disk cache
├── agents/
│   ├── scout_agent.py       # REWRITE — Files API video upload + structured output (D1, D2)
│   ├── writer_agent.py      # REWRITE — booth dialogue schema, two-speaker turns (D3)
│   └── analyst_agent.py     # FILL — move momentum/streak logic out of graph.py into here
├── engine/
│   ├── tts_engine.py        # NEW — Gemini single + multi-speaker TTS, cache, edge-tts fallback (D4)
│   └── video_engine.py      # EDIT — drop ElevenLabs, call tts_engine; MoviePy v2 imports
├── live/
│   └── live_session.py      # NEW (Phase 4) — Live API session manager (D6)
├── observability/
│   └── tracing.py           # NEW — Langfuse setup + decorators (D5)
├── utils/
│   ├── schemas.py           # EDIT — add BoothScript/Turn models
│   └── config.py            # FILL — model names, RPM budgets, voice maps, feature flags
├── app.py / fastapi_app.py  # EDIT — persona picker becomes "color commentator" picker; Live endpoint
└── evals/                   # NEW — golden dataset + metrics + Langfuse logging
```

---

## 5. Phased Implementation

### Phase 0 — Foundation (SDK + plumbing) — ✅ COMPLETE (verified end-to-end: 5 API calls/run, 66s total)
- Swap dependency `google-generativeai` → `google-genai`; remove `elevenlabs`; add `langfuse`; pin `moviepy>=2`.
- Build `clients/gemini_client.py` (retry, budget, cache) and fill `utils/config.py` (all model names/limits/voices).
- Delete dead files or fill them (`analyst_agent.py`, `audio_engine.py`, `helpers.py`); fix MoviePy v2 imports (`from moviepy import ...`).
- **Acceptance:** existing pipeline runs end-to-end on the new SDK with zero behavior change.

### Phase 1 — Native Video Scout (D1) — ✅ COMPLETE (4 events vs 3 from frames, jersey names detected, rerun = 0 quota / 16s)
- Rewrite `scout_agent.py`: upload video via Files API → poll until `ACTIVE` → one `generate_content` call with `response_schema=ScoutOutput` → validated Pydantic result. Ask for timestamps as `MM:SS`-or-seconds (config); keep the 30s cap.
- Wire cache + mock mode.
- **Acceptance:** same clip → richer event list than the old frame sampler; 1 API call; cache hit on rerun.

### Phase 2 — Booth Mode + Gemini TTS (D3, D4)
- Extend `schemas.py`: `Turn{speaker, text}` and `BoothSegment{timestamp_seconds, turns[], duration_hint_seconds}`.
- Rewrite `writer_agent.py`: prompt gets momentum/streak context + event list, outputs banter turns; hard word-budget math stays (now split across two mouths).
- Build `tts_engine.py`: single-speaker and `multi_speaker_voice_config` paths → PCM→WAV → cache → edge-tts fallback on quota errors.
- Update `video_engine.py`: consume `BoothSegment`s, per-segment TTS file, existing ducking untouched.
- UI: persona picker becomes "Color Commentator: Analyst | Roaster" (PBP Hype voice is constant).
- **Acceptance:** output video has two distinct voices riffing; total calls ≤ budget; fallback fires correctly when quota is simulated.

### Phase 3 — Observability + Eval Harness (D5) — *before* Live
- `observability/tracing.py`: Langfuse init from env; `@observe()` on scout/writer/TTS/assemble; one trace per run, tagged with mode (batch/live) + color persona.
- `evals/`:
  - **Golden dataset:** 3–5 short clips + hand-labeled events (timestamp ± type).
  - **Metrics:** event precision/recall with ±1.5s match window, timestamp MAE, duration-compliance rate (script must fit before clip end), persona-adherence via LLM-as-judge (1 cheap Flash-Lite call, eval-runs only), latency + call count.
  - `run_evals.py` runs the suite, logs scores to a Langfuse dataset run.
- **Acceptance:** `python -m evals.run_evals` prints a scorecard and every metric is visible in Langfuse.

### Phase 4 — Live Mode (D6)
- `live/live_session.py`: Live API session (native-audio model; name from config — verify current name at build time). Two input modes: **webcam** (real demo) and **simulated-live** (stream an mp4's frames at real-time pace — same wow, no camera needed, also used for evals).
- Browser: WS bridge in `fastapi_app.py`; simple "Go Live" page in the frontend; commentary audio plays live in the browser.
- Free-tier reality: sessions are capped (short 30–60s demos; one session at a time). Document this; simulated-live mode keeps demos deterministic.
- **Acceptance:** 30s webcam session produces intelligible real-time commentary in-browser; graceful error when session quota is exhausted.

### Phase 5 — Polish
- Update `README.md` (architecture, Booth/Live modes, evals section, new run instructions) and this plan's checkboxes.
- Root `requirements.txt` / `pyproject.toml` reconciliation.

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| TTS daily cap on free tier is small | Disk cache + edge-tts fallback + ≤8 segments/video + mock mode |
| Model names/limits changed since planning | All names in `utils/config.py`; Phase 0 includes a `--verify-models` sanity script |
| Live API session limits make demos flaky | Simulated-live-from-file mode as the deterministic demo path |
| Banter writer blows the duration budget (2 voices = 2× words) | Word budget enforced per *segment* (sum of both turns) in the schema validation + prompt math, exactly like today's constraint |
| Langfuse adds latency to every call | Async ingestion by design; `TRACING_ENABLED=0` killswitch |

## 7. Explicitly Out of Scope (for now)
Crowd SFX/music, multi-language picker, player jersey tracking, highlight auto-clipping, cloud deployment, Next.js rewrite. All noted in the backlog; none block this plan.

---

### Execution order summary
**P0 SDK/plumbing → P1 native video scout → P2 booth + Gemini TTS → P3 tracing + evals → P4 Live → P5 docs.**
Each phase ends green and demo-able on its own; every phase after P0 routes all Google calls through the cached central client.
