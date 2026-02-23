import os
import re
from typing import List, Dict
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
from pydub import AudioSegment
from elevenlabs import save
import subprocess

# Ducking Parameters
DUCK_PRE_BUFFER = 0.2   # Start ducking 0.2s before commentary
DUCK_POST_BUFFER = 0.3  # Hold duck 0.3s after commentary ends
DUCK_AMOUNT_DB = -18    # Decrease original audio by 18 dB
DUCK_FADE_IN = 0.3      # Fade out original audio over 0.3s (duck start)
DUCK_FADE_OUT = 0.5     # Fade in original audio over 0.5s (duck end)

# Voice Mappings (Voice ID, Stability, Similarity Boost)
PERSONA_VOICE_MAP = {
    "hype":       {"id": "ErXwobaYiN019PkySvjV", "stability": 0.3, "similarity": 0.8}, # Antoni — energetic
    "analytical": {"id": "VR6AewLTigWG4xSOukaG", "stability": 0.8, "similarity": 0.75}, # Arnold — calm
    "roaster":    {"id": "pNInz6obpgDQGcFmaJgB", "stability": 0.4, "similarity": 0.9}   # Adam — expressive
}

# Edge TTS Mappings (High Quality Free Neural Voices)
EDGE_VOICE_MAP = {
    "hype": "en-US-ChristopherNeural", 
    "analytical": "en-US-SteffanNeural", 
    "roaster": "en-US-GuyNeural"
}

def calculate_audio_duration(ssml_text: str) -> float:
    """Strip SSML tags, count words, use formula duration = word_count / 2.5 + 0.3"""
    # Remove XML/SSML tags
    clean_text = re.sub(r'<[^>]+>', '', ssml_text)
    word_count = len(clean_text.split())
    
    duration = (word_count / 2.5) + 0.3
    return duration

def test_duration_calculation():
    """Test function for `calculate_audio_duration`"""
    sample_ssml = "<speak><emphasis level='strong'>OH WOW!</emphasis> <break time='200ms'/> What a shot.</speak>"
    duration = calculate_audio_duration(sample_ssml)
    # Expected words: "OH WOW! What a shot." = 5 words
    # 5 / 2.5 = 2.0 + 0.3 = 2.3 seconds
    assert abs(duration - 2.3) < 0.1, f"Expected ~2.3 seconds, got {duration}"
    return True

def fallback_tts(text: str, persona: str, output_path: str):
    """Use high-quality free Edge-TTS (Microsoft Neural Voices) if ElevenLabs fails."""
    # Strip SSML for offline fallback 
    clean_text = re.sub(r'<[^>]+>', '', text)
    # Strip quotes to avoid CLI command issues
    clean_text = clean_text.replace("'", "").replace('"', "")
    
    voice = EDGE_VOICE_MAP.get(persona, "en-US-ChristopherNeural")
    cmd = ["edge-tts", "--voice", voice, "--text", clean_text, "--write-media", output_path]
    
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        print(f"Edge-TTS also failed: {e}")

def generate_voice_audio(text: str, persona: str, output_path: str):
    """Generate TTS using ElevenLabs with fallback to Edge-TTS."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("Using offline voice (no API key).")
        fallback_tts(text, persona, output_path)
        return

    client = ElevenLabs(api_key=api_key)
    voice_config = PERSONA_VOICE_MAP.get(persona, PERSONA_VOICE_MAP["analytical"])
    
    try:
        # Use valid method for the new elevenlabs v1+ python SDK
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_config["id"],
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(
                stability=voice_config["stability"],
                similarity_boost=voice_config["similarity"],
            )
        )
        save(audio, output_path)
                
    except Exception as e:
        print(f"ElevenLabs failed: {e}. Retrying once...")
        try:
             # Retry once
             audio = client.text_to_speech.convert(
                text=text,
                voice_id=voice_config["id"],
                model_id="eleven_multilingual_v2",
                voice_settings=VoiceSettings(
                    stability=voice_config["stability"],
                    similarity_boost=voice_config["similarity"],
                )
             )
             save(audio, output_path)
        except Exception as retry_e:
            print(f"Retry failed too. Using offline voice: {retry_e}")
            fallback_tts(text, persona, output_path)

def assemble_final_video(video_path: str, commentary_segments: List[Dict], output_path: str, temp_dir: str):
    """Overlay audio with precise ducking and export the final video."""
    # Ensure standard duration
    video_clip_orig = VideoFileClip(video_path)
    if video_clip_orig.duration > 30.0:
        print(f"Video exceeded 30.0s (trimming down).")
        video_clip = video_clip_orig.subclip(0, 30.0)
    else:
        print(f"Video is {video_clip_orig.duration:.1f}s, which is fine (under or equal to 30s).")
        video_clip = video_clip_orig
    
    # Extract original audio to pydub
    original_audio_path = os.path.join(temp_dir, "original_audio.wav")
    if video_clip.audio:
         video_clip.audio.write_audiofile(original_audio_path, logger=None)
         base_audio = AudioSegment.from_file(original_audio_path)
    else:
         # Create silent audio track
         base_audio = AudioSegment.silent(duration=int(video_clip.duration * 1000))

    final_audio = base_audio
    generated_audio_clips = []
    
    # Process each commentary segment
    for i, seg in enumerate(commentary_segments):
        ssml_script = seg.get("ssml", "")
        persona = seg.get("persona", "hype")
        start_time_sec = seg.get("timestamp_seconds", 0)
        
        chunk_path = os.path.join(temp_dir, f"comm_audio_{i}.mp3")
        generate_voice_audio(ssml_script, persona, chunk_path)
        
        # Load generated commentary via pydub
        if os.path.exists(chunk_path):
            try:
                comm_audio = AudioSegment.from_file(chunk_path)
            except Exception as e:
                print(f"Failed to read generated chunk {chunk_path}: {e}")
                comm_audio = AudioSegment.silent(duration=3000) # 3s fallback silent
        else:
            print(f"Fallback: {chunk_path} does not exist, using silent audio.")
            comm_audio = AudioSegment.silent(duration=3000)

        comm_duration_ms = len(comm_audio)
        
        # Times in ms
        start_ms = int(start_time_sec * 1000)
        end_ms = start_ms + comm_duration_ms
        
        # Calculate Ducking bounds
        duck_start_ms = max(0, start_ms - int(DUCK_PRE_BUFFER * 1000))
        duck_end_ms = min(len(base_audio), end_ms + int(DUCK_POST_BUFFER * 1000))
        
        # Apply ducking to the base audio (if not silent)
        if video_clip.audio:
            # 1. Before Duck (Full volume)
            part1 = final_audio[:duck_start_ms]
            
            # 2. Duck Period (Lowered volume by DUCK_AMOUNT_DB)
            ducked_section = final_audio[duck_start_ms:duck_end_ms] + DUCK_AMOUNT_DB
            # Adding fades manually (fade in the duck = fade out the full volume)
            ducked_section = ducked_section.fade_in(int(DUCK_FADE_IN * 1000)).fade_out(int(DUCK_FADE_OUT * 1000))
            
            # 3. After Duck (Full volume)
            part3 = final_audio[duck_end_ms:]
            final_audio = part1 + ducked_section + part3
        
        # Overlay the commentary onto the newly ducked final_audio at start_ms
        final_audio = final_audio.overlay(comm_audio, position=start_ms)
        
        # Ensure that the overlay didn't extend the length of the final_audio past base_audio
        final_audio = final_audio[:len(base_audio)]

    # Export final audio mix back to MoviePy format
    final_mix_path = os.path.join(temp_dir, "final_mix.wav")
    final_audio.export(final_mix_path, format="wav")
    
    mixed_audio_clip_orig = AudioFileClip(final_mix_path)
    
    # Ensure audio duration does not extend past video duration (cut off cleanly)
    if mixed_audio_clip_orig.duration > video_clip.duration:
        mixed_audio_clip = mixed_audio_clip_orig.subclip(0, video_clip.duration)
    else:
        mixed_audio_clip = mixed_audio_clip_orig
        
    final_video = video_clip.set_audio(mixed_audio_clip)
    
    # Export final
    fps_to_use = video_clip.fps if video_clip.fps is not None else 30
    final_video.write_videofile(
        output_path, 
        codec='libx264', 
        audio_codec='aac',
        logger=None,
        fps=fps_to_use
    )
    
    # Explicitly close all clips to release Windows file handles
    final_video.close()
    video_clip.close()
    if video_clip != video_clip_orig:
        video_clip_orig.close()
    mixed_audio_clip.close()
    if mixed_audio_clip != mixed_audio_clip_orig:
        mixed_audio_clip_orig.close()
