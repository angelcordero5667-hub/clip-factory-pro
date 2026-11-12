from src.agents.agent1_transcription.transcriber import (
    AudioTranscriber, transcript_cache_key, TRANSCRIPT_CACHE_VERSION)


def _audio(tmp_path, name="clip.wav", data=b"abc"):
    f = tmp_path / name
    f.write_bytes(data)
    return f


def test_key_is_stable_for_same_inputs(tmp_path):
    f = _audio(tmp_path)
    assert transcript_cache_key(f, "es", True, "small", "int8", 1) == transcript_cache_key(f, "es", True, "small", "int8", 1)


def test_key_changes_with_model_language_mode_and_beam(tmp_path):
    f = _audio(tmp_path)
    base = transcript_cache_key(f, "es", True, "small", "int8", 1)
    assert transcript_cache_key(f, "es", True, "large-v3-turbo", "int8", 1) != base   # el caso que fallaba
    assert transcript_cache_key(f, "en", True, "small", "int8", 1) != base
    assert transcript_cache_key(f, "es", False, "small", "int8", 1) != base
    assert transcript_cache_key(f, "es", True, "small", "float32", 1) != base
    assert transcript_cache_key(f, "es", True, "small", "int8", 5) != base
    assert transcript_cache_key(f, None, True, "small", "int8", 1) != base


def test_key_changes_when_file_content_changes_even_with_same_name(tmp_path):
    a = _audio(tmp_path, "same.wav", b"aaa")
    ka = transcript_cache_key(a, "es", True, "small", "int8", 1)
    a.write_bytes(b"aaaaaaaa")   # otro tamaño, mismo nombre
    assert transcript_cache_key(a, "es", True, "small", "int8", 1) != ka


def test_key_is_filesystem_safe(tmp_path):
    f = _audio(tmp_path, "mi video: #1 (final) ñandú.wav")
    k = transcript_cache_key(f, "es", True, "<Mock id='1'>", None, None)   # también con valores raros / mocks
    assert all(c.isalnum() or c in "_" for c in k) and len(k) < 100


def test_cache_version_is_part_of_the_key(tmp_path, monkeypatch):
    from src.agents.agent1_transcription import transcriber as t
    f = _audio(tmp_path)
    k1 = t.transcript_cache_key(f, "es", True, "small", "int8", 1)
    monkeypatch.setattr(t, "TRANSCRIPT_CACHE_VERSION", TRANSCRIPT_CACHE_VERSION + 1)
    assert t.transcript_cache_key(f, "es", True, "small", "int8", 1) != k1


def test_transcriber_cache_path_depends_on_model(tmp_path):
    f = _audio(tmp_path)
    p_small = AudioTranscriber(model_size="small").get_cache_path(f, "es", True)
    p_turbo = AudioTranscriber(model_size="large-v3-turbo").get_cache_path(f, "es", True)
    assert p_small != p_turbo and p_small.name.startswith("tx_")
