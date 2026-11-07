import wave
import math
import struct
from pathlib import Path
from src.agents.agent1_transcription.transcriber import AudioTranscriber

def test_live_transcription():
    # 2 seconds of 16kHz audio
    audio_path = Path("tests/synthetic_speech.wav")
    with wave.open(str(audio_path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        for i in range(16000 * 2):
            val = int(32767.0 * 0.05 * math.sin(2.0 * math.pi * 440.0 * i / 16000))
            f.writeframes(struct.pack("<h", val))

    print(f"Generated test audio at {audio_path}")
    transcriber = AudioTranscriber(model_size="tiny", device="cpu", compute_type="int8", cpu_threads=4)
    result = transcriber.transcribe(str(audio_path))
    
    print("SUCCESS: Faster-Whisper loaded and executed on CPU (INT8)!")
    print(f"Language: {result.language}, Duration: {result.duration}s")
    
    if audio_path.exists():
        audio_path.unlink()

if __name__ == "__main__":
    test_live_transcription()
