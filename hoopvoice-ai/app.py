import streamlit as st
import os
import shutil
import json
import time
from dotenv import load_dotenv

load_dotenv()

from utils.schemas import ScoutOutput, WriterOutput
from state.graph import build_graph
from engine.video_engine import test_duration_calculation, assemble_final_video

TEMP_DIR = "temp"

def cleanup_temp():
    """Clear and recreate the temporary directory."""
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

st.set_page_config(page_title="HoopVoice AI", layout="wide")

st.title("🏀 HoopVoice AI — Orchestrator Prototype")

# Ensure Temp directory initially
cleanup_temp()

# Test calculation locally to ensure formulas run smoothly
try:
    test_duration_calculation()
except Exception as e:
    st.sidebar.warning(f"Duration Calculation Warning: {e}")

st.sidebar.header("Settings")
selected_persona_label = st.sidebar.radio("Select Commentary Persona:", ["🔥 Hype Man", "📊 Analyst", "😤 Roaster"])

persona_mapper = {
    "🔥 Hype Man": "hype",
    "📊 Analyst": "analytical",
    "😤 Roaster": "roaster"
}
persona = persona_mapper[selected_persona_label]

uploaded_file = st.file_uploader("Upload Raw Basketball Clip (.mp4, max 50MB, 30s recommended)", type=["mp4"])

if uploaded_file is not None:
    if st.button("Generate Commentary"):
        # Clean before processing
        cleanup_temp()
        
        video_path = os.path.join(TEMP_DIR, "input_video.mp4")
        with open(video_path, "wb") as f:
            f.write(uploaded_file.read())
            
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        workflow = build_graph()
        state_dict = {
            "video_path": video_path,
            "selected_persona": persona
        }
        
        # 1. Scouting
        status_text.text("1. Scouting...")
        progress_bar.progress(20)
        
        # Actually calling graph nodes individually or via invoke for UI progress representation
        # It's better to stream the graph to update UI dynamically
        
        try:
            for output in workflow.stream(state_dict):
                # output is a dict of the node name: state
                if "ingest_events" in output:
                     status_text.text("2. Analyzing Momentum...")
                     progress_bar.progress(40)
                elif "analyze_momentum" in output:
                     # State after momentum
                     pass 
                elif "build_writer_input" in output:
                     status_text.text("3. Writing Commentary...")
                     progress_bar.progress(60)
                elif "call_writer_agent" in output:
                     status_text.text("4. Generating Audio (ElevenLabs)...")
                     progress_bar.progress(80)
                     
            # Final state
            final_state = output[list(output.keys())[0]] # Get final node state usually call_writer_agent
            
            # Extract outputs for displaying
            events = final_state.get("events", [])
            commentary_segments = final_state.get("commentary_segments", [])
            
            if len(events) == 0:
                 st.warning("No major plays detected. Generating fallback commentary.")
            
            # Proceed to final rendering manually out of graph scope (Graph focuses on LLM logic)
            status_text.text("5. Assembling Video...")
            output_video_path = os.path.join(TEMP_DIR, "output_hoopvoice.mp4")
            
            # The director engine
            assemble_final_video(video_path, commentary_segments, output_video_path, TEMP_DIR)
            
            progress_bar.progress(100)
            status_text.text("✅ Process Complete!")
            time.sleep(1) # Visual hold
            status_text.empty()
            progress_bar.empty()
            
            # Side-by-side Players
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Original Video")
                st.video(video_path)
            with col2:
                st.subheader(f"HoopVoice Output ({selected_persona_label})")
                st.video(output_video_path)
            
            # Expandables
            with st.expander("View Event Log (Scout Output)"):
                st.json({
                    "clip_duration_seconds": 30.0,
                    "events": events
                })
                
            with st.expander("View Commentary Script (Writer Output)"):
                st.json({
                    "commentary_segments": commentary_segments
                })
                
        except Exception as e:
            st.error(f"An error occurred during pipeline execution: {e}")
            
