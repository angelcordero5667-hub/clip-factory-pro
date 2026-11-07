from unittest.mock import MagicMock, patch

import pytest

from src.common import youtube_downloader as dl


def test_friendly_error_unsupported_url():
    err = dl._friendly_error("https://x.test/a", Exception("ERROR: Unsupported URL: https://x.test/a"))
    assert "no tiene un video descargable" in str(err)


def test_friendly_error_private_video():
    err = dl._friendly_error("u", Exception("ERROR: Private video. Sign in if you've been granted access"))
    assert "privado" in str(err)


def test_friendly_error_generic_is_truncated():
    err = dl._friendly_error("u", Exception("boom " * 200))
    assert str(err).startswith("No se pudo descargar el video:")
    assert len(str(err)) < 400


def test_base_opts_has_retries_timeout_and_no_playlist():
    opts = dl._base_opts(None)
    assert opts["noplaylist"] is True
    assert opts["retries"] == dl.DEFAULT_RETRIES
    assert opts["socket_timeout"] == dl.SOCKET_TIMEOUT
    assert "progress_hooks" not in opts


def test_progress_hook_reports_fraction_and_never_raises():
    seen = []
    hook = dl._base_opts(seen.append)["progress_hooks"][0]
    hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200})
    hook({"status": "finished"})
    hook({"status": "downloading"})  # sin tamaño: se ignora
    hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 0, "bogus": object()})
    assert seen == [0.25, 1.0]


def test_download_audio_wraps_errors(tmp_path):
    fake = MagicMock()
    fake.__enter__.return_value.extract_info.side_effect = Exception("ERROR: Unsupported URL: https://x.test")
    with patch("yt_dlp.YoutubeDL", return_value=fake):
        with pytest.raises(RuntimeError, match="no tiene un video descargable"):
            dl.download_youtube_audio("https://x.test", output_dir=tmp_path)
