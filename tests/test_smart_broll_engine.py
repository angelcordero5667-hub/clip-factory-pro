import pytest
from pathlib import Path
from src.agents.agent3_clip_generator.smart_broll import (
    SmartBrollEngine,
    BrollItem,
    load_clip_broll,
    save_clip_broll
)
from src.agents.agent3_clip_generator.framing import FaceSample
from src.common.models import TranscriptSegment, WordTimestamp

def test_broll_catalog():
    engine = SmartBrollEngine()
    cat = engine.get_catalog()
    assert "dinero" in cat
    assert "tech" in cat
    assert "autos" in cat
    assert "exito" in cat
    assert "alerta" in cat
    assert "musica" in cat
    assert "gameplay" in cat
    assert len(cat["dinero"]["items"]) > 0

def test_broll_keyword_detection_and_density():
    engine = SmartBrollEngine()
    segs = [
        TranscriptSegment(
            id=1, start=2.0, end=5.0,
            text="Hablando de los millones de dinero que se ganaron",
            words=[
                WordTimestamp(word="Hablando", start=2.0, end=2.4),
                WordTimestamp(word="de", start=2.4, end=2.5),
                WordTimestamp(word="los", start=2.5, end=2.6),
                WordTimestamp(word="millones", start=2.6, end=3.2),
                WordTimestamp(word="de", start=3.2, end=3.3),
                WordTimestamp(word="dinero", start=3.3, end=3.8),
            ]
        ),
        TranscriptSegment(
            id=2, start=12.0, end=16.0,
            text="La ciberseguridad y el código del servidor se cayeron",
            words=[
                WordTimestamp(word="La", start=12.0, end=12.2),
                WordTimestamp(word="ciberseguridad", start=12.2, end=13.0),
                WordTimestamp(word="y", start=13.0, end=13.1),
                WordTimestamp(word="el", start=13.1, end=13.2),
                WordTimestamp(word="código", start=13.2, end=13.8),
            ]
        ),
        TranscriptSegment(
            id=3, start=20.0, end=24.0,
            text="Iba en un automóvil de alta velocidad y carrera",
            words=[
                WordTimestamp(word="automóvil", start=20.0, end=20.8),
                WordTimestamp(word="velocidad", start=21.5, end=22.2),
            ]
        ),
    ]

    # Test density medium
    items = engine.analyze_and_schedule(segs, clip_start=0.0, clip_end=30.0, density="medium")
    assert len(items) >= 2
    cats = [it.category for it in items]
    assert "dinero" in cats or "tech" in cats

    # Test density low
    items_low = engine.analyze_and_schedule(segs, clip_start=0.0, clip_end=30.0, density="low")
    assert len(items_low) <= len(items)

def test_broll_face_avoidance_positioning():
    engine = SmartBrollEngine()
    segs = [
        TranscriptSegment(id=1, start=1.0, end=4.0, text="Todo el dinero del mundo", words=[WordTimestamp(word="dinero", start=1.5, end=2.5)])
    ]
    # Cara en la mitad derecha superior
    faces_right = [FaceSample(t=1.5, xs=[0.75]), FaceSample(t=2.0, xs=[0.80])]
    items_avoid = engine.analyze_and_schedule(segs, clip_start=0.0, clip_end=10.0, face_samples=faces_right)
    assert len(items_avoid) > 0
    # Al estar el rostro a la derecha, debe colocarse a la izquierda
    assert items_avoid[0].position == "bottom_left"

def test_broll_filter_generation():
    engine = SmartBrollEngine()
    dummy_item = BrollItem(
        id="broll_1", word="dinero", category="dinero",
        start=1.0, end=4.0,
        media_path=str(Path("data/broll/dinero/dinero_cash_flow.mp4").resolve()),
        media_url="/broll_media/dinero/dinero_cash_flow.mp4",
        media_type="video", layout="overlay", position="bottom_right",
        badge_text="$$$ DINERO"
    )
    filter_str, final_label = engine.build_broll_filters([dummy_item], 1080, 1920, "[combined]")
    assert "movie=" in filter_str
    assert "overlay=" in filter_str
    assert "between(t,1.00,4.00)" in filter_str
    assert final_label == "[v_broll_0]"

def test_broll_sidecar_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr("src.agents.agent3_clip_generator.smart_broll.CACHE_BROLL_DIR", tmp_path)
    item = BrollItem(
        id="b1", word="test", category="dinero", start=2.0, end=5.0,
        media_path="foo.mp4", media_url="/url", media_type="video",
        layout="overlay", position="bottom_right", badge_text="TEST"
    )
    p = save_clip_broll("test_cand", [item])
    assert p.exists()
    loaded = load_clip_broll("test_cand")
    assert loaded is not None and len(loaded) == 1
    assert loaded[0].word == "test"
