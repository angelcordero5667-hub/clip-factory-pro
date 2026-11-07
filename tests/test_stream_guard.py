from unittest.mock import MagicMock, patch

import pytest

from src.common import stream_guard as sg
from src.common import youtube_downloader as dl


@pytest.fixture(autouse=True)
def _clear_cache():
    sg._probe_cache.clear()
    yield
    sg._probe_cache.clear()


def test_live_stream_is_rejected():
    with pytest.raises(RuntimeError, match="EN VIVO"):
        sg.check_stream({"is_live": True, "live_status": "is_live", "duration": None})


def test_upcoming_stream_is_rejected():
    with pytest.raises(RuntimeError, match="aún no ha empezado"):
        sg.check_stream({"live_status": "is_upcoming"})


def test_long_video_without_range_asks_for_a_range():
    with pytest.raises(RuntimeError, match="Desde / Hasta"):
        sg.check_stream({"duration": 5 * 3600})


def test_long_video_with_range_is_allowed():
    sg.check_stream({"duration": 5 * 3600}, time_range=(600.0, 1800.0))


def test_short_video_and_unknown_duration_are_allowed():
    sg.check_stream({"duration": 1800})
    sg.check_stream({"duration": None})


def test_range_after_the_end_is_rejected():
    with pytest.raises(RuntimeError, match="dura solo"):
        sg.check_stream({"duration": 1200}, time_range=(3000.0, 3600.0))


def test_limit_can_be_changed_with_env(monkeypatch):
    monkeypatch.setenv("CLIP_MAX_FULL_HOURS", "0.5")
    with pytest.raises(RuntimeError):
        sg.check_stream({"duration": 3600})
    monkeypatch.setenv("CLIP_MAX_FULL_HOURS", "basura")
    assert sg.max_full_seconds() == 7200.0


def _fake_ydl(info=None, error=None):
    ydl = MagicMock()
    if error:
        ydl.__enter__.return_value.extract_info.side_effect = error
    else:
        ydl.__enter__.return_value.extract_info.return_value = info
    return ydl


def test_probe_returns_none_instead_of_blocking_when_it_fails():
    with patch("yt_dlp.YoutubeDL", return_value=_fake_ydl(error=Exception("sin red"))):
        assert sg.probe_url("https://x.test/v") is None
        assert sg.guard_url("https://x.test/v") is None            # no bloquea


def test_probe_extracts_fields_and_is_cached():
    info = {"title": "Directo", "duration": 100, "live_status": "not_live", "is_live": False, "otro": "x"}
    fake = _fake_ydl(info=info)
    with patch("yt_dlp.YoutubeDL", return_value=fake) as ctor:
        a = sg.probe_url("https://x.test/a")
        b = sg.probe_url("https://x.test/a")
    assert a == b == {"title": "Directo", "duration": 100, "live_status": "not_live", "is_live": False}
    assert ctor.call_count == 1                                     # la segunda vez sale de la caché


def test_downloaders_stop_before_downloading_a_live_stream(tmp_path):
    live = _fake_ydl(info={"title": "En vivo", "duration": None, "is_live": True, "live_status": "is_live"})
    with patch("yt_dlp.YoutubeDL", return_value=live) as ctor:
        with pytest.raises(RuntimeError, match="EN VIVO"):
            dl.download_youtube_audio("https://twitch.tv/x", output_dir=tmp_path)
        with pytest.raises(RuntimeError, match="EN VIVO"):
            dl.download_youtube_video("https://twitch.tv/x", output_dir=tmp_path)
    # solo se consultó (extract_info con download=False), nunca se descargó
    calls = live.__enter__.return_value.extract_info.call_args_list
    assert calls and all(c.kwargs.get("download") is False for c in calls)
