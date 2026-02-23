import os
import shutil
import time
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from utils.schemas import ScoutOutput, WriterOutput
from state.graph import build_graph
from engine.video_engine import assemble_final_video

app = FastAPI(title="HoopVoice AI API")

# Allow the frontend file to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "temp"
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")

def cleanup_temp():
    """Clear and recreate the temporary directory."""
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
        except Exception as e:
            print(f"Warning on cleanup: {e}")
    os.makedirs(TEMP_DIR, exist_ok=True)

@app.post("/generate")
async def generate_commentary(
    video_file: UploadFile = File(...),
    persona: str = Form("hype")
):
    print(f"Received request for persona: {persona}")
    cleanup_temp()
    
    video_path = os.path.join(TEMP_DIR, "input_video.mp4")
    
    # Save uploaded file
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(video_file.file, buffer)
        
    workflow = build_graph()
    state_dict = {
        "video_path": video_path,
        "selected_persona": persona
    }
    
    print("Starting LangGraph workflow execution...")
    try:
        # Run graph synchronously 
        final_output = workflow.invoke(state_dict)
        final_state = final_output
        
        events = final_state.get("events", [])
        commentary_segments = final_state.get("commentary_segments", [])
        
        print(f"Detected {len(events)} events.")
        
        output_video_path = os.path.join(TEMP_DIR, "output_hoopvoice.mp4")
        
        print("Assembling final video with ducking...")
        assemble_final_video(video_path, commentary_segments, output_video_path, TEMP_DIR)
        
        print("Success! File ready for download.")
        # Return the generated file URL and LangGraph logs back to the browser
        return {
            "video_url": f"http://localhost:8000/temp/output_hoopvoice.mp4?t={int(time.time())}",
            "events": events,
            "commentary_segments": commentary_segments
        }
        
    except Exception as e:
        print(f"Pipeline failed: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Make sure this runs from inside the hoopvoice-ai folder
    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=8000, reload=True)
