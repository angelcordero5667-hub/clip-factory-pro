import pytest
from pathlib import Path
from src.agents.agent3_clip_generator.smart_sfx import (
    SmartSFXEngine,
    SFXItem,
    load_clip_sfx,
    save_clip_sfx,
    CATEGORIES
)
from src.common.models import TranscriptSegment, WordTimestamp

def test_sfx_catalog_all_7_categories():
    engine = SmartSFXEngine()
    catalog = engine.get_catalog()
    for cat in CATEGORIES:
        assert cat in catalog, f"Missing category {cat}"
        items = catalog[cat]["items"]
        assert len(items) > 0, f"Category {cat} has no sound items"
        assert all(it["exists"] for it in items), f"Some sound files do not exist in category {cat}"

def test_sfx_scheduling_and_cues():
    engine = SmartSFXEngine()
    segs = [
        TranscriptSegment(
            id=1, start=1.0, end=4.0,
            text="Nos pagaron tres millones de dólares en efectivo"
        ),
        TranscriptSegment(
            id=2, start=6.0, end=9.0,
            text="jajaja qué risa y qué mentiroso eres chercha"
        ),
        TranscriptSegment(
            id=3, start=12.0, end=15.0,
            text="Es un secreto y un grave peligro de muerte"
        ),
    ]

    sfx = engine.analyze_and_schedule(
        segs, clip_start=0.0, clip_end=20.0,
        hook_text="Gancho brutal", virality_score=92.0,
        intensity="normal", has_dynamic_zoom=True
    )

    assert len(sfx) >= 3
    cats = [s.category for s in sfx]
    # Comprobar gancho inicial
    assert sfx[0].time <= 0.6
    # Comprobar dinero / risa
    assert "notification" in cats or "comedy" in cats or "cinematic" in cats or "whoosh" in cats

def test_sfx_intensity_scaling():
    engine = SmartSFXEngine()
    segs = [TranscriptSegment(id=1, start=2.0, end=5.0, text="dinero y risa")]
    soft = engine.analyze_and_schedule(segs, clip_start=0.0, clip_end=30.0, intensity="soft")
    aggr = engine.analyze_and_schedule(segs, clip_start=0.0, clip_end=30.0, intensity="aggressive")
    assert aggr[0].volume > soft[0].volume

def test_sfx_audio_mixing_args():
    engine = SmartSFXEngine()
    item = SFXItem(
        id="s1", name="Boom", category="impact", time=1.5,
        sfx_file="impact/impact.wav",
        sfx_path=str(Path("data/assets/sfx/impact/impact.wav").resolve()),
        sfx_url="/sfx_media/impact/impact.wav",
        volume=0.35, reason="test"
    )
    inputs, flt, out_label = engine.build_audio_mix_args([item], base_audio_label="0:a")
    assert len(inputs) == 2  # -i <path>
    assert "adelay=1500|1500" in flt
    assert "volume=0.35" in flt
    assert "amix=" in flt
    assert out_label == "[a_sfx_mix]"

def test_sfx_sidecar_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr("src.agents.agent3_clip_generator.smart_sfx.CACHE_SFX_DIR", tmp_path)
    item = SFXItem(
        id="sfx_test", name="Whoosh", category="whoosh", time=0.5,
        sfx_file="whoosh/whoosh.wav", sfx_path="whoosh.wav", sfx_url="/url",
        volume=0.3, reason="gancho"
    )
    p = save_clip_sfx("cand_sfx", [item])
    assert p.exists()
    loaded = load_clip_sfx("cand_sfx")
    assert loaded is not None and len(loaded) == 1
    assert loaded[0].name == "Whoosh"
