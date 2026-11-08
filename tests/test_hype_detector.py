import numpy as np
import pytest

from src.agents.agent2_viral_detector.audio_energy import build_profile, SAMPLE_RATE
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.common.models import TranscriptResult, TranscriptSegment, ViralMomentCandidate


def _tone(seconds, amp):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * 32767 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def _make_sample_transcript():
    # 60s transcript
    segments = [
        TranscriptSegment(id=0, start=0.0, end=10.0, text="Bienvenidos a este episodio de podcast sobre economía."),
        TranscriptSegment(id=1, start=10.0, end=20.0, text="Hoy analizaremos las tendencias del mercado bursátil."),
        TranscriptSegment(id=2, start=20.0, end=35.0, text="¡No puede ser qué jugada increíble dios mío!"),
        TranscriptSegment(id=3, start=35.0, end=45.0, text="Miren cómo remontamos la partida en el último segundo."),
        TranscriptSegment(id=4, start=45.0, end=60.0, text="Gracias por ver y no olviden suscribirse."),
    ]
    return TranscriptResult(
        video_path="dummy.mp4",
        language="es",
        duration=60.0,
        segments=segments,
        full_text=" ".join(s.text for s in segments)
    )


def test_hype_not_active_in_regular_podcasts():
    detector = ViralMomentDetector(min_duration=10.0, max_duration=25.0)
    transcript = _make_sample_transcript()
    # Audio con pico fuerte entre 20s y 35s
    audio = np.concatenate([_tone(20, 0.05), _tone(15, 0.95), _tone(25, 0.05)])
    profile = build_profile(audio)

    # layout=None / "auto": no debe activar hype peaks
    clips = detector.detect_moments(transcript, use_llm=False, energy=profile, layout="auto")
    hype_clips = [c for c in clips if c.engine == "audio_energy"]
    assert len(hype_clips) == 0
    # Tampoco debe mencionar hype en reasoning
    assert not any("pico de energía acústica" in c.reasoning.lower() for c in clips)


def test_hype_active_in_gaming_layout():
    detector = ViralMomentDetector(min_duration=10.0, max_duration=25.0)
    transcript = _make_sample_transcript()
    # Audio con pico fuerte entre 20s y 35s
    audio = np.concatenate([_tone(20, 0.05), _tone(15, 0.95), _tone(25, 0.05)])
    profile = build_profile(audio)

    clips = detector.detect_moments(transcript, use_llm=False, energy=profile, layout="gaming")
    # En gaming, el momento de 20s a 35s debe registrar el pico de energía
    has_hype_reasoning = any("pico de energía acústica" in c.reasoning.lower() for c in clips)
    has_hype_engine = any(c.engine == "audio_energy" for c in clips)
    assert has_hype_reasoning or has_hype_engine


def test_hype_creates_dedicated_clip_when_not_covered_by_previous():
    detector = ViralMomentDetector(min_duration=10.0, max_duration=25.0)
    transcript = _make_sample_transcript()
    # Pico de energía al final (40s a 60s)
    audio = np.concatenate([_tone(40, 0.05), _tone(20, 0.95)])
    profile = build_profile(audio)

    # Simulamos que el LLM solo encontró un clip al inicio (0-15s)
    candidate_early = ViralMomentCandidate(
        id="clip_llm_early",
        start_time=0.0,
        end_time=15.0,
        duration=15.0,
        title="Inicio del Podcast 🎙️",
        hook_text="Bienvenidos a este episodio",
        context_text="Introducción de economía",
        virality_score=80.0,
        category="ensenanza",
        reasoning="Introducción.",
        engine="llm"
    )
    detector._detect_with_ollama = lambda t, focus_prompt=None: [candidate_early]

    clips = detector.detect_moments(transcript, use_llm=True, energy=profile, include_hype=True)
    hype_clips = [c for c in clips if c.engine == "audio_energy"]
    assert len(hype_clips) > 0

    h = hype_clips[0]
    # No debe ser el título plano "Momento Épico en Directo 🔥"
    assert h.title != "Momento Épico en Directo 🔥"
    # Debe ser dinámico y tener copy contextual
    assert len(h.title) > 3
    assert len(h.social_description) > 10


def test_hype_avoids_duplicate_when_overlapping():
    detector = ViralMomentDetector(min_duration=10.0, max_duration=25.0)
    transcript = _make_sample_transcript()
    audio = np.concatenate([_tone(20, 0.05), _tone(15, 0.95), _tone(25, 0.05)])
    profile = build_profile(audio)

    # Simulamos que el LLM ya devolvió un clip de 20s a 35s
    existing_candidate = ViralMomentCandidate(
        id="clip_llm_1",
        start_time=20.0,
        end_time=35.0,
        duration=15.0,
        title="La Gran Jugada 💥",
        hook_text="¡No puede ser!",
        context_text="Jugada increíble",
        virality_score=85.0,
        category="reaccion",
        reasoning="Momento detectado por LLM.",
        engine="llm"
    )

    detector._detect_with_ollama = lambda t, focus_prompt=None: [existing_candidate]

    clips = detector.detect_moments(transcript, use_llm=True, energy=profile, include_hype=True)

    # No debe duplicar el clip en ese mismo rango
    hype_overlapping = [c for c in clips if c.engine == "audio_energy" and abs(c.start_time - 20.0) < 5.0]
    assert len(hype_overlapping) == 0

    # Y el candidato existente debe haber sido reforzado con la información del pico de audio
    llm_clip = next(c for c in clips if c.id == "clip_llm_1")
    assert "pico de energía acústica" in llm_clip.reasoning.lower()
