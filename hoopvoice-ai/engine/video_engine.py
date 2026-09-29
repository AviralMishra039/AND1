import os
from typing import List, Dict

from moviepy import VideoFileClip, AudioFileClip
from pydub import AudioSegment

from engine.tts_engine import generate_voice_audio
from observability.tracing import observe
from utils.config import TTS_MAX_SEGMENTS
from utils.helpers import calculate_audio_duration, test_duration_calculation  # noqa: F401 (re-exported for app.py)

# Ducking Parameters
DUCK_PRE_BUFFER = 0.2   # Start ducking 0.2s before commentary
DUCK_POST_BUFFER = 0.3  # Hold duck 0.3s after commentary ends
DUCK_AMOUNT_DB = -18    # Decrease original audio by 18 dB
DUCK_FADE_IN = 0.3      # Fade out original audio over 0.3s (duck start)
DUCK_FADE_OUT = 0.5     # Fade in original audio over 0.5s (duck end)


@observe(name="director")
def assemble_final_video(video_path: str, commentary_segments: List[Dict], output_path: str, temp_dir: str):
    """Overlay audio with precise ducking and export the final video."""
    # Ensure standard duration
    video_clip_orig = VideoFileClip(video_path)
    if video_clip_orig.duration > 30.0:
        print("Video exceeded 30.0s (trimming down).")
        video_clip = video_clip_orig.subclipped(0, 30.0)
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

    # Process each commentary segment
    for i, seg in enumerate(commentary_segments):
        if i >= TTS_MAX_SEGMENTS:
            print(f"[budget] Skipping TTS for segment {i} (cap is {TTS_MAX_SEGMENTS}).")
            continue

        ssml_script = seg.get("ssml", "")
        persona = seg.get("persona", "hype")
        start_time_sec = seg.get("timestamp_seconds", 0)

        chunk_path = os.path.join(temp_dir, f"comm_audio_{i}.wav")
        generate_voice_audio(ssml_script, persona, chunk_path)

        # Load generated commentary via pydub
        try:
            comm_audio = AudioSegment.from_file(chunk_path)
        except Exception as e:
            print(f"Failed to read generated chunk {chunk_path}: {e}")
            comm_audio = AudioSegment.silent(duration=3000)  # 3s fallback silent

        # Normalize to base audio format (pydub overlay does not resample; Gemini TTS is 24kHz mono)
        comm_audio = (
            comm_audio
            .set_frame_rate(base_audio.frame_rate)
            .set_channels(base_audio.channels)
            .set_sample_width(base_audio.sample_width)
        )

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
        mixed_audio_clip = mixed_audio_clip_orig.subclipped(0, video_clip.duration)
    else:
        mixed_audio_clip = mixed_audio_clip_orig

    final_video = video_clip.with_audio(mixed_audio_clip)

    # Export final
    fps_to_use = video_clip.fps if video_clip.fps is not None else 30
    final_video.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        logger=None,
        fps=fps_to_use,
    )

    # Explicitly close all clips to release Windows file handles
    final_video.close()
    video_clip.close()
    if video_clip is not video_clip_orig:
        video_clip_orig.close()
    mixed_audio_clip.close()
    if mixed_audio_clip is not mixed_audio_clip_orig:
        mixed_audio_clip_orig.close()
