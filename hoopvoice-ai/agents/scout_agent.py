import os
import cv2
import time
from typing import List, Dict
import google.generativeai as genai
from pydantic import ValidationError
from PIL import Image

# Use relative imports when possible, but for Streamlit execution context we might need absolute or sys.path adjustments.
# Assuming execution from root directory via streamlit run.
from utils.schemas import ScoutOutput

def initialize_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)

def extract_frames(video_path: str, fps_target: int = 2) -> List[Image.Image]:
    """Extract frames from the video at the target FPS."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video file {video_path}")

    fps_original = cap.get(cv2.CAP_PROP_FPS)
    if fps_original <= 0:
        fps_original = 30 # default assumption
        
    frame_interval = max(1, int(fps_original / fps_target))
    frames = []
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_count % frame_interval == 0:
            # Convert BGR (OpenCV) to RGB (Pillow)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_frame)
            frames.append(pil_img)
            
        frame_count += 1
        
    cap.release()
    return frames

def analyze_video(video_path: str) -> dict:
    """Extract frames, send to Gemini, and return the structured JSON event log."""
    initialize_gemini()
    
    # 1. Extract frames
    frames = extract_frames(video_path, fps_target=2)
    
    if not frames:
        print("Scout Agent found 0 frames. Returning empty.")
        return ScoutOutput(clip_duration_seconds=30.0, events=[]).model_dump()
        
    # We will send images in batches to avoid overwhelming the token limit
    # For a 30s video at 2 fps = 60 frames. 
    # To keep it simple, we use the gemini-2.0-flash model which has a large context window.
    # We will sample 10 representative frames, or process in batches if needed.
    # Let's just send a maximum of 15 evenly spaced frames for cost/speed.
    step = max(1, len(frames) // 15)
    selected_frames = frames[::step][:15]

    actual_duration = len(frames) / 2.0
    
    # Use gemini-1.5-flash as the standard accepted version name from google-generativeai SDK
    model = genai.GenerativeModel("gemini-2.5-flash")    
    prompt = f"""
    You are an expert basketball scout. Analyze these sequential frames from a {actual_duration:.1f}-second basketball clip.
    Identify all major plays (dunks, three_pointers, blocks, steals, assists, misses, fouls, or other).
    For each play, provide the EXACT timestamp (using the frame time labels provided), 
    a description, intensity (1-10), and players involved.
    
    Output exactly in this JSON format matching this schema:
    {{
      "clip_duration_seconds": {actual_duration:.1f},
      "events": [
        {{
          "timestamp_seconds": 4.5,
          "play_type": "dunk | three_pointer | block | steal | assist | miss | foul | other",
          "description": "Player drives baseline and posterizes defender",
          "intensity": 8,
          "players_involved": ["Player A", "Player B"]
        }}
      ]
    }}
    """
    
    contents = [prompt]
    
    # Interleave timestamps text and PIL images so Gemini isn't forced to hallucinate timing
    for i in range(0, len(frames), step)[:15]:
        t_sec = i * 0.5  # because we extracted at 2 fps
        contents.append(f"Frame taken at {t_sec:.1f} seconds:")
        contents.append(frames[i])
    
    try:
        response = model.generate_content(
            contents,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        # Parse and validate with Pydantic
        output_txt = response.text
        scout_data = ScoutOutput.model_validate_json(output_txt)
        return scout_data.model_dump()
        
    except Exception as e:
        print(f"Scout Agent error: {e}")
        # Fallback empty list if error
        return ScoutOutput(clip_duration_seconds=30.0, events=[]).model_dump()
