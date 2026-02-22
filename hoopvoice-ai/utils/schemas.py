from typing import List, Literal, Optional
from pydantic import BaseModel, Field

class Event(BaseModel):
    timestamp_seconds: float = Field(..., description="Timestamp of the event in seconds")
    play_type: Literal["dunk", "three_pointer", "block", "steal", "assist", "miss", "foul", "other"] = Field(..., description="Type of the play")
    description: str = Field(..., description="Description of the event")
    intensity: int = Field(..., ge=1, le=10, description="Intensity of the play from 1 to 10")
    players_involved: List[str] = Field(default_factory=list, description="List of players involved")

class ScoutOutput(BaseModel):
    clip_duration_seconds: float = Field(..., description="Total duration of the clip in seconds")
    events: List[Event] = Field(default_factory=list, description="List of detected events")

class CommentarySegment(BaseModel):
    timestamp_seconds: float = Field(..., description="Timestamp of the commentary in seconds")
    persona: Literal["hype", "analytical", "roaster"] = Field(..., description="Persona used for the commentary")
    script: str = Field(..., description="Plain text version of the commentary")
    ssml: str = Field(..., description="SSML version of the commentary")
    duration_hint_seconds: float = Field(..., description="Duration hint for the commentary (words / 2.5)")

class WriterOutput(BaseModel):
    commentary_segments: List[CommentarySegment] = Field(default_factory=list, description="List of commentary segments")
