import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent1_transcription.transcriber import AudioTranscriber
from src.agents.agent1_transcription.dominican_slang import (
    correct_dominican_text,
    get_low_confidence_segments,
    normalize_dominican_segments,
    CATEGORIZED_DICTIONARY
)
from src.agents.agent1_transcription.hybrid_verifier import (
    HybridTranscriptionVerifier,
    QualityReviewReport
)


def test_categorized_dictionary_structure():
    assert "expresiones_urbanas" in CATEGORIZED_DICTIONARY
    assert "artistas_y_apodos" in CATEGORIZED_DICTIONARY
    assert "fonetica_contextual" in CATEGORIZED_DICTIONARY


def test_phonetic_corrections_dominican():
    # Aspiración de S en Papá Dios
    assert "Papá Dios" in correct_dominican_text("las parejas que papá dio le manda a uno")
    # Elisión en están salvos
    assert "están salvos" in correct_dominican_text("porque tan salvo no van a ir")
    # Fusión acústica en cantan canciones
    assert "cantan canciones" in correct_dominican_text("unos cantaciones que tal vez")
    # Artistas urbanos
    assert "Dilon" in correct_dominican_text("Dillon tiene su novia")
    assert "Alofoke" in correct_dominican_text("en vivo por alofoque")


def test_low_confidence_detection_flags_uncertainty():
    words = [
        WordTimestamp(word="bueno", start=0.0, end=0.4, probability=0.98),
        WordTimestamp(word="guadolmín", start=0.4, end=0.9, probability=0.32),
        WordTimestamp(word="sola", start=0.9, end=1.3, probability=0.95),
    ]
    seg = TranscriptSegment(id=0, start=0.0, end=1.3, text="bueno guadolmín sola", words=words)
    
    dubious = get_low_confidence_segments([seg], threshold=0.70)
    assert len(dubious) == 1
    assert dubious[0]["word"] == "guadolmín"
    assert dubious[0]["probability"] == 0.32
    assert dubious[0]["segment_id"] == 0


def test_no_fabrication_on_high_confidence():
    words = [
        WordTimestamp(word="yo", start=0.0, end=0.2, probability=0.95),
        WordTimestamp(word="estoy", start=0.2, end=0.5, probability=0.91),
        WordTimestamp(word="aquí", start=0.5, end=0.8, probability=0.89),
    ]
    seg = TranscriptSegment(id=0, start=0.0, end=0.8, text="yo estoy aquí", words=words)
    dubious = get_low_confidence_segments([seg], threshold=0.70)
    assert len(dubious) == 0


def test_hybrid_verifier_produces_quality_report():
    verifier = HybridTranscriptionVerifier(confidence_threshold=0.75, enable_cloud=False)
    words = [
        WordTimestamp(word="dime", start=0.0, end=0.3, probability=0.9),
        WordTimestamp(word="tano", start=0.3, end=0.6, probability=0.5),
    ]
    seg = TranscriptSegment(id=0, start=0.0, end=0.6, text="dime tano", words=words)
    res = TranscriptResult(video_path="dummy.mp4", language="es", duration=0.6, segments=[seg], full_text="dime tano")
    
    verified, report = verifier.process_and_verify(res, "dummy.mp4", apply_dominican_rules=True)
    assert isinstance(report, QualityReviewReport)
    assert report.total_words == 2
    assert len(report.low_confidence_words) == 1
    assert report.low_confidence_words[0]["word"] == "tano"
    assert "ta' tó" in verified.segments[0].text
    assert verified.segments[0].words[1].word == "ta' tó"
    assert verified.segments[0].words[1].start == 0.3


def test_transcriber_model_selection_and_beam():
    trans = AudioTranscriber(model_size="large-v3-turbo", beam_size=3, confidence_threshold=0.8)
    assert trans.model_size == "large-v3-turbo"
    assert trans.beam_size == 3
    assert trans.confidence_threshold == 0.8
