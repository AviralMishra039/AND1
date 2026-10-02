from typing import List, Literal
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


class Turn(BaseModel):
    speaker: Literal["play_by_play", "color"] = Field(..., description="Which booth voice speaks this turn")
    text: str = Field(..., description="The spoken text for this turn")


class BoothSegment(BaseModel):
    timestamp_seconds: float = Field(..., description="Timestamp of the segment in seconds")
    persona: Literal["analytical", "roaster"] = Field(..., description="Color commentator persona")
    turns: List[Turn] = Field(default_factory=list, description="Ordered booth dialogue turns")
    duration_hint_seconds: float = Field(..., description="Rough spoken duration of all turns (words / 2.5)")


class BoothOutput(BaseModel):
    commentary_segments: List[BoothSegment] = Field(default_factory=list, description="List of booth commentary segments")
