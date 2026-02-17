# 🏀 HoopVoice AI: The Voice of the Local Court
### HoopVoice AI is an end-to-end, stateful multi-agent system that autonomously generates professional-grade, personality-driven commentary for amateur basketball footage. By bridging the gap between raw video and professional broadcasting, we turn every local game into a "Sportscenter" highlight reel.

# Team: AND1  
## Member: Aviral Mishra
## Category: The Fan Experience / Open Innovation


## The Vision
### In a world where 99% of sports are played in silence, HoopVoice AI democratizes the professional broadcast experience. Whether it's a high school tournament or a pickup game at the park, our system uses Multimodal Agentic AI to understand the narrative, track the momentum, and speak the language of the game.

## Tech Stack
### Vision Engine: Gemini 1.5 Pro (Multimodal event extraction)

### Orchestration: LangGraph (Stateful Agentic workflow)

### Brain: Gemini 3 Flash / GPT-4o (Scripting & Narrative reasoning)

### Voice Synthesis: ElevenLabs (Emotive TTS with Turbo v2.5)

### AV Processing: MoviePy & FFmpeg (Audio ducking and sync)

### UI/UX: Streamlit

## Agentic Architecture
### Unlike simple "video-to-text" tools, HoopVoice uses a Stateful Pipeline:

### - The Scout (Perception): Analyzes the video stream to extract structured JSON logs of plays, player descriptions, and intensity levels.

### - The Analyst (Memory): Uses LangGraph to maintain a "Game State." It tracks scoring streaks, "clutch" moments, and player performance over time.

### - The Hype-Writer (Narrative): Converts raw data into personality-driven scripts. Supports multiple personas: The Professional, The Hype-Man, and The Roaster.

### - The Director (Production): Generates the audio and automatically "ducks" (lowers) the original game volume to ensure the commentary is crisp and professional.

##  Project Structure

```
hoopvoice-ai/
├── agents/           # Scout, Analyst, and Writer logic
├── engine/           # ElevenLabs & MoviePy processing
├── state/            # LangGraph workflow & Game State
├── assets/           # Raw clips and generated output
├── app.py            # Streamlit Dashboard
└── requirements.txt  # Project dependencies
```

# Note:
### - This is the github repository of the project. The project is still in development and is not ready for production use. 

### - For the first round, I have added this repo's link to the presentation and will be merging code here to make the project prototype.