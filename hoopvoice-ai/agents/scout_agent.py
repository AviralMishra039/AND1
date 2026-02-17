import google.generativeai as genai
import json
import os
from dotenv import load_dotenv

load_dotenv()

class ScoutAgent:
    def __init__(self):
        # Configure Gemini 1.5 Flash for speed and cost-efficiency
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def analyze_clip(self, video_path):
        """
        Uploads a basketball clip to Gemini and extracts a structured event log.
        """
        print(f"🚀 Scout Agent is watching: {video_path}...")
        
        # Upload the file to Google's servers
        video_file = genai.upload_file(path=video_path)
        
        # The prompt is the most important part of the 'Scout'
        prompt = """
        Analyze this basketball clip as a professional scout. 
        Output ONLY a JSON array of events. Do not include any text before or after the JSON.
        
        For each event, provide:
        - timestamp: The time in the video (MM:SS)
        - event_type: (e.g., 'dunk', 'steal', 'crossover', 'missed_shot', 'block')
        - player_description: Physical description of the player (e.g., 'Player in Red #10')
        - intensity: A scale from 1-10 based on the crowd vibe or athleticism.
        - success: Boolean (true/false)
        """

        response = self.model.generate_content([video_file, prompt])
        
        # Clean the response to ensure it's valid JSON
        try:
            # Removing markdown formatting if present
            raw_json = response.text.replace('```json', '').replace('```', '').strip()
            event_log = json.loads(raw_json)
            return event_log
        except Exception as e:
            print(f"❌ Error parsing Scout data: {e}")
            return None

# --- Quick Test ---
if __name__ == "__main__":
    scout = ScoutAgent()
    # Replace with your actual path for testing
    events = scout.analyze_clip("assets/raw_clips/test_dunk.mp4")
    print(json.dumps(events, indent=2))
