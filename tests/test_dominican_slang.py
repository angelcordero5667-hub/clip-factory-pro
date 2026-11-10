import pytest
from src.agents.agent1_transcription.dominican_slang import (
    DOMINICAN_INITIAL_PROMPT,
    correct_dominican_text,
    normalize_dominican_segments,
    COMPILED_RULES
)
from src.common.models import TranscriptSegment, WordTimestamp

def test_dominican_initial_prompt_contains_key_terms():
    assert "klk" in DOMINICAN_INITIAL_PROMPT
    assert "ta' tó" in DOMINICAN_INITIAL_PROMPT
    assert "Alofoke" in DOMINICAN_INITIAL_PROMPT
    assert "Rochy RD" in DOMINICAN_INITIAL_PROMPT
    assert "Yailin" in DOMINICAN_INITIAL_PROMPT
    assert "wawawa" in DOMINICAN_INITIAL_PROMPT

def test_correct_dominican_text_slang_replacements():
    # Common Whisper errors in Dominican Republic
    assert "ta' tó" in correct_dominican_text("me entiendes tano")
    assert "ta' tó" in correct_dominican_text("bueno tató mi hermano")
    assert "klk" in correct_dominican_text("dime keloke con eso")
    assert "wawawa" in correct_dominican_text("el sonido guaguagua en el bloque")
    assert "pámpara" in correct_dominican_text("prendieron la lámpara")
    assert "Alofoke" in correct_dominican_text("lo vi en alofo que anoche")
    assert "Rochy RD" in correct_dominican_text("rochi rd es el líder")
    assert "Kreizy K" in correct_dominican_text("entrevista con creysi k")
    assert "Yailin" in correct_dominican_text("preguntaron por jailin")

def test_normalize_dominican_segments_preserves_timestamps():
    words = [
        WordTimestamp(word="me", start=1.0, end=1.2, probability=0.9),
        WordTimestamp(word="entiendes", start=1.2, end=1.5, probability=0.9),
        WordTimestamp(word="tano", start=1.5, end=1.8, probability=0.8),
    ]
    seg = TranscriptSegment(
        id=0,
        start=1.0,
        end=1.8,
        text="me entiendes tano",
        words=words
    )
    
    normalized = normalize_dominican_segments([seg], use_llm=False)
    assert len(normalized) == 1
    res_seg = normalized[0]
    assert "ta' tó" in res_seg.text
    assert res_seg.words[2].word == "ta' tó"
    assert res_seg.words[2].start == 1.5
    assert res_seg.words[2].end == 1.8

def test_empty_or_none_segments():
    assert normalize_dominican_segments([]) == []
    assert correct_dominican_text("") == ""
    assert correct_dominican_text(None) == ""

def test_dominicanize_endpoint(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.api_server import app, settings, db
    from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp, ViralMomentCandidate

    client = TestClient(app)
    
    vid_id = "vid_dom_test"
    clip_id = "clip_dom_test"
    db.save_video(vid_id, "test.mp4", str(tmp_path / "test.mp4"), 60.0, "es", "url")
    cand = ViralMomentCandidate(
        id=clip_id,
        start_time=0.0,
        end_time=10.0,
        duration=10.0,
        title="Momento dominicano",
        hook_text="tano",
        context_text="ctx",
        virality_score=90,
        category="humor",
        reasoning="r",
        engine="llm"
    )
    db.save_candidates(vid_id, [cand])
    
    # Create fake transcript in cache
    t_file = settings.cache_dir / "transcripts" / f"{clip_id}_edited.json"
    t_file.parent.mkdir(parents=True, exist_ok=True)
    seg = TranscriptSegment(
        id=0,
        start=0.0,
        end=5.0,
        text="dimelo tano en alofoque con creysi k",
        words=[
            WordTimestamp(word="dimelo", start=0.0, end=1.0, probability=0.9),
            WordTimestamp(word="tano", start=1.0, end=2.0, probability=0.9),
            WordTimestamp(word="en", start=2.0, end=2.5, probability=0.9),
            WordTimestamp(word="alofoque", start=2.5, end=3.5, probability=0.9),
            WordTimestamp(word="con", start=3.5, end=4.0, probability=0.9),
            WordTimestamp(word="creysi", start=4.0, end=4.5, probability=0.9),
            WordTimestamp(word="k", start=4.5, end=5.0, probability=0.9),
        ]
    )
    res = TranscriptResult(
        video_path=str(tmp_path / "test.mp4"),
        language="es",
        duration=60.0,
        segments=[seg],
        full_text=seg.text
    )
    t_file.write_text(res.model_dump_json(), encoding="utf-8")
    
    # Call dominicanize
    resp = client.post(f"/api/clips/{clip_id}/dominicanize")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    
    # Check updated transcript
    edited_data = TranscriptResult.model_validate_json(t_file.read_text(encoding="utf-8"))
    assert "ta' tó" in edited_data.segments[0].text
    assert "Alofoke" in edited_data.segments[0].text
    assert "Kreizy K" in edited_data.segments[0].text
