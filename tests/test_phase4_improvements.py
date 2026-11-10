import pytest
from src.agents.agent2_viral_detector.analysis import trim_filler_words
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.agents.agent2_viral_detector.audio_energy import EnergyProfile
from src.common.models import WordTimestamp, ViralMomentCandidate, TranscriptResult, TranscriptSegment
from src.common.config import settings
import numpy as np

def test_trim_filler_words_trims_dead_start():
    words = [
        WordTimestamp(word="Ok,", start=10.0, end=10.5),
        WordTimestamp(word="bueno,", start=10.8, end=11.3),
        WordTimestamp(word="mira", start=11.5, end=11.9),
        WordTimestamp(word="cuando", start=12.5, end=13.0),
        WordTimestamp(word="yo", start=13.1, end=13.3),
        WordTimestamp(word="firmé", start=13.4, end=13.8),
        WordTimestamp(word="el", start=13.9, end=14.0),
        WordTimestamp(word="contrato", start=14.1, end=14.6),
    ]
    start, end = 10.0, 45.0
    new_start, new_hook, trimmed = trim_filler_words(start, end, words, min_duration=20.0)
    
    assert trimmed is True
    # Should advance to just before "cuando" (start ~12.4s)
    assert 12.3 <= new_start <= 12.5
    assert new_hook.startswith("cuando yo firmé")

def test_trim_filler_words_preserves_substantive_start():
    words = [
        WordTimestamp(word="¡Pérate!", start=10.0, end=10.8),
        WordTimestamp(word="o", start=11.0, end=11.2),
        WordTimestamp(word="sea", start=11.3, end=11.5),
        WordTimestamp(word="que", start=11.6, end=11.8),
        WordTimestamp(word="la", start=11.9, end=12.0),
        WordTimestamp(word="mujer", start=12.1, end=12.5),
    ]
    start, end = 10.0, 45.0
    new_start, new_hook, trimmed = trim_filler_words(start, end, words, min_duration=20.0)
    
    assert trimmed is False
    assert new_start == 10.0
    assert new_hook is None

def test_apply_energy_penalizes_loud_noise_without_words():
    # Candidate with duration 30s but only 3 words (0.1 wps) and high energy (0.85)
    cand = ViralMomentCandidate(
        id="clip_noise",
        start_time=10.0,
        end_time=40.0,
        duration=30.0,
        title="Grito o Ruido Fuerte 🔥",
        hook_text="Grito ininteligible",
        context_text="Gritos y ruidos sin contenido.",
        category="sorpresa",
        reasoning="Pico acústico alto.",
        virality_score=80.0
    )
    
    # Fake energy profile with 0.85 norm
    profile = EnergyProfile(hop=0.5, norm=np.full(100, 0.85, dtype=np.float32))
    
    transcript = TranscriptResult(
        video_path="test.mp4",
        language="es",
        duration=60.0,
        segments=[
            TranscriptSegment(id=0, start=15.0, end=16.5, text="Ahhh grito fuerte")
        ],
        full_text="Ahhh grito fuerte"
    )
    
    results = ViralMomentDetector._apply_energy([cand], profile, transcript=transcript)
    res_cand = results[0]
    
    # Should receive penalty (-4.0 pts) instead of bonus
    assert res_cand.virality_score == 76.0
    assert "Penalización por ruido/gritos" in res_cand.reasoning

def test_ollama_config_and_detector_window():
    detector = ViralMomentDetector()
    assert detector.window_sec == 240.0
    assert settings.ollama.timeout_seconds == 180
