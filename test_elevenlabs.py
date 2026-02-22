import os
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings, save

load_dotenv('.env')
api_key = os.environ.get('ELEVENLABS_API_KEY')
print('Key snippet:', api_key[:10] if api_key else "None")

client = ElevenLabs(api_key=api_key)
audio = client.text_to_speech.convert(
    text='Hello test', 
    voice_id='ErXwobaYiN019PkySvjV', 
    model_id='eleven_multilingual_v2', 
    voice_settings=VoiceSettings(stability=0.3, similarity_boost=0.8)
)
save(audio, 'test.mp3')
print('success:', os.path.exists('test.mp3'))
