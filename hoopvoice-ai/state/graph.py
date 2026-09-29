from typing import TypedDict, List, Dict
from langgraph.graph import StateGraph, END
from agents.analyst_agent import compute_game_metrics
from agents.scout_agent import analyze_video
from agents.writer_agent import generate_commentary

class GameState(TypedDict):
    events: List[Dict]                    # From Scout Agent
    momentum: str                         # "rising" | "falling" | "neutral"
    scoring_streak: int                   # Consecutive scoring plays
    intensity_trend: List[int]            # Last 5 intensity scores
    dominant_play_type: str               # Most frequent play type so far
    commentary_context: str               # Rolling natural-language summary
    selected_persona: str                 # "hype" | "analytical" | "roaster"
    writer_input: Dict                    # Enriched payload for Writer Agent
    commentary_segments: List[Dict]       # Final output from Writer Agent
    video_path: str                       # Input video path
    clip_duration_seconds: float          # Physical length of clip

def ingest_events(state: GameState) -> GameState:
    """Analyze the video and populate events from Scout."""
    video_path = state.get("video_path")
    if not video_path:
        state["events"] = []
        state["clip_duration_seconds"] = 30.0
        return state
        
    scout_output = analyze_video(video_path)
    state["events"] = scout_output.get("events", [])
    state["clip_duration_seconds"] = scout_output.get("clip_duration_seconds", 30.0)
    return state

def analyze_momentum(state: GameState) -> GameState:
    """Calculate momentum and trends from events (logic lives in agents/analyst_agent.py)."""
    state.update(compute_game_metrics(state.get("events", [])))
    return state

def build_writer_input(state: GameState) -> GameState:
    """Compile context for the Writer Agent."""
    events = state.get("events", [])
    momentum = state.get("momentum", "neutral")
    streak = state.get("scoring_streak", 0)
    
    if len(events) == 0:
        context = "No major plays detected in this run. It's a quiet stretch."
    else:
        context = f"The momentum is {momentum}. There's been {streak} major scoring plays recently. The crowd is feeling it."
        
    state["commentary_context"] = context
    
    state["writer_input"] = {
        "events": events,
        "context": context,
        "persona": state.get("selected_persona", "analytical"),
        "clip_duration_seconds": state.get("clip_duration_seconds", 30.0)
    }
    return state

def call_writer_agent(state: GameState) -> GameState:
    """Calls the Writer Agent with the prepared context."""
    writer_input = state.get("writer_input", {})
    writer_output = generate_commentary(writer_input)
    state["commentary_segments"] = writer_output.get("commentary_segments", [])
    return state

def build_graph() -> StateGraph:
    """Build and compile the LangGraph workflow."""
    workflow = StateGraph(GameState)
    
    workflow.add_node("ingest_events", ingest_events)
    workflow.add_node("analyze_momentum", analyze_momentum)
    workflow.add_node("build_writer_input", build_writer_input)
    workflow.add_node("call_writer_agent", call_writer_agent)
    
    workflow.set_entry_point("ingest_events")
    workflow.add_edge("ingest_events", "analyze_momentum")
    workflow.add_edge("analyze_momentum", "build_writer_input")
    workflow.add_edge("build_writer_input", "call_writer_agent")
    workflow.add_edge("call_writer_agent", END)
    
    return workflow.compile()
