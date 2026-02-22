import os
from typing import Dict, List
import google.generativeai as genai
from pydantic import ValidationError

from utils.schemas import WriterOutput

def initialize_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)

def generate_commentary(writer_input: Dict) -> dict:
    """Takes events and context and generates SSML commentary matching the persona."""
    initialize_gemini()
    
    events = writer_input.get("events", [])
    persona = writer_input.get("persona", "hype")
    context = writer_input.get("context", "")
    clip_duration = writer_input.get("clip_duration_seconds", 30.0)
    
    if not events:
        # Fallback if no major plays detected
        return WriterOutput(commentary_segments=[{
            "timestamp_seconds": 0.5, # Right at the start of video
            "persona": persona,
            "script": "No major plays detected in this run. It's a quiet stretch.",
            "ssml": "<speak><prosody rate='medium'>No major plays detected in this run. It's a quiet stretch.</prosody></speak>",
            "duration_hint_seconds": 9.0 / 2.5
        }]).model_dump()

    # System instruction tailored to the persona
    persona_rules = {
        "hype": "You are a legendary, high-energy streetball announcer and NBA hype-man! Think AND1 Tour mixed with Kevin Harlan on steroids. Be explosive, absolutely lose your mind safely on big plays, use authentic basketball slang (e.g., 'caught a body!', 'from the logo!', 'put him in a blender!', 'posterized!'). Use lots of <emphasis level='strong'>, high pitches, and fast <prosody rate='fast' pitch='high'>. Keep it punchy, rhythmic, and incredibly hyped!",
        "analytical": "Calm, ESPN-style, tactical. Use measured pace with <prosody rate='medium'> and focus on facts.",
        "roaster": "Savage, funny, trash-talk. Use dramatic pauses like <break time='500ms'/>, sarcasm, and slow <prosody rate='slow'> for impact."
    }
    
    rule = persona_rules.get(persona, persona_rules["analytical"])
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
    You are a professional basketball commentator. Your persona is "{persona}":
    {rule}
    
    Context: {context}
    The total video is ONLY {clip_duration:.1f} seconds long.
    
    You must output exactly one commentary segment per event provided below.
    CRITICAL CONSTRAINT: You MUST keep your script short enough so it finishes BEFORE the video ends! 
    A normal speaking rate is 2.5 words per second. 
    Count your words. If an event happens at {clip_duration - 2.0:.1f}s on a {clip_duration:.1f}s video, your script CANNOT be more than 4 words!
    
    Make sure your SSML is completely valid (no unclosed tags) and enclosed in <speak>.
    Calculate `duration_hint_seconds` roughly as word count divided by 2.5.
    
    Events to cover:
    """
    
    for i, event in enumerate(events):
        prompt += f"\n- [{event['timestamp_seconds']}s] Type: {event['play_type']} | Desc: {event['description']} | Intensity: {event['intensity']}"
        
    prompt += """
    
    Output exactly in this JSON format:
    {
      "commentary_segments": [
        {
          "timestamp_seconds": 4.5,
          "persona": "hype",
          "script": "Plain text version",
          "ssml": "<speak>...</speak>",
          "duration_hint_seconds": 3.5
        }
      ]
    }
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        output_txt = response.text
        writer_data = WriterOutput.model_validate_json(output_txt)
        return writer_data.model_dump()
        
    except Exception as e:
        print(f"Writer Agent error: {e}")
        # Fallback 
        return WriterOutput(commentary_segments=[{
            "timestamp_seconds": events[0]['timestamp_seconds'] if events else 0.5,
            "persona": persona,
            "script": "Wow, what a play!",
            "ssml": "<speak>Wow, what a play!</speak>",
            "duration_hint_seconds": 4.0 / 2.5
        }]).model_dump()
