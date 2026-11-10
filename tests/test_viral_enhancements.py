import pytest
from pathlib import Path
from src.common.viral_enhancements import (
    detect_contextual_sticker,
    get_sfx_path,
    build_audio_filter_chain
)

def test_detect_contextual_stickers():
    # Test keywords
    assert detect_contextual_sticker("habló de los millones y el dinero") is not None
    assert detect_contextual_sticker("esta confesión fue censurada por peligro") is not None
    assert detect_contextual_sticker("tenemos una bomba exclusiva de bochinche") is not None
    assert detect_contextual_sticker("habló sobre yailin la más viral") is not None
    assert detect_contextual_sticker("un saludo a todos") is None

def test_sfx_paths():
    assert get_sfx_path("whoosh") is not None
    assert get_sfx_path("impact") is not None
    assert get_sfx_path("ding") is not None
    assert get_sfx_path("non_existent_sfx") is None

def test_build_audio_filter_chain():
    # Standard chain with seamless loop and loudnorm
    chain = build_audio_filter_chain(duration=30.0, normalize_audio=True, seamless_loop=True)
    assert any("loudnorm" in f for f in chain)
    assert any("afade=t=out" in f for f in chain)
    
    # Without seamless loop
    chain_no_loop = build_audio_filter_chain(duration=30.0, normalize_audio=True, seamless_loop=False)
    assert not any("afade=t=out" in f for f in chain_no_loop)
