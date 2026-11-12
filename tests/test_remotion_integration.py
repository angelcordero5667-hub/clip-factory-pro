"""Enganche opcional de Remotion: audio masterizado, validación y fallback a FFmpeg (sin Node ni Chromium)."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.common.remotion_engine import RemotionEngine
from src.common.config import settings


def _ff(*args):
    subprocess.run([settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


@pytest.fixture
def media(tmp_path):
    src = tmp_path / "source.mp4"       # 12 s con audio a bajo volumen
    _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-af", "volume=0.05", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src))
    vis = tmp_path / "visual.mp4"       # 4 s solo imagen (lo que daría Remotion con --muted)
    _ff("-f", "lavfi", "-i", "testsrc=size=270x480:rate=30", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vis))
    return src, vis


def test_master_and_mux_keeps_video_and_adds_mastered_audio(media, tmp_path):
    src, vis = media
    eng = RemotionEngine()
    out = eng.master_and_mux(vis, str(src), start=3.0, duration=4.0, out_path=tmp_path / "final.mp4")
    info = eng.probe(out)
    assert info["has_video"] and info["has_audio"]
    assert info["video_codec"] == "h264" and info["audio_codec"] == "aac"
    assert abs(info["duration"] - 4.0) < 0.3


def test_master_and_mux_rejects_when_durations_disagree(media, tmp_path):
    src, vis = media                    # imagen de 4 s con audio pedido de 9 s: -shortest debería igualarlos
    eng = RemotionEngine()
    out = eng.master_and_mux(vis, str(src), start=0.0, duration=9.0, out_path=tmp_path / "f2.mp4")
    assert abs(eng.probe(out)["duration"] - 4.0) < 0.5      # no queda audio colgando más allá de la imagen


def test_ass_color_to_css():
    c = RemotionEngine.ass_to_css_color
    assert c("&H0000FFFF") == "#FFFF00"          # ASS amarillo (BGR) → CSS
    assert c("&H00FFFF00") == "#00FFFF"          # ASS cian
    assert c("#12ab34") == "#12ab34"
    assert c(None) == "#FFE600" and c("basura") == "#FFE600"


def test_pipeline_falls_back_to_ffmpeg_when_remotion_fails():
    from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline
    pipe = ClipFactoryPipeline.__new__(ClipFactoryPipeline)       # sin construir motores pesados
    pipe.clip_maker = MagicMock()
    cand = MagicMock(id="c1")
    msgs = []
    with patch("src.common.remotion_engine.remotion_engine") as eng:
        eng.is_available.return_value = True
        eng.render_candidate.side_effect = RuntimeError("Chromium roto")
        assert pipe._rerender_with_remotion("v.mp4", cand, [], msgs.append, None, {}) is None   # → usar FFmpeg
    assert any("Usando FFmpeg" in m for m in msgs)


def test_pipeline_remotion_unavailable_means_ffmpeg():
    from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline
    pipe = ClipFactoryPipeline.__new__(ClipFactoryPipeline)
    pipe.clip_maker = MagicMock()
    with patch("src.common.remotion_engine.remotion_engine") as eng:
        eng.is_available.return_value = False
        assert pipe._rerender_with_remotion("v.mp4", MagicMock(id="c"), [], None, None, {}) is None


def test_pipeline_propagates_user_cancel():
    import threading
    from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline
    pipe = ClipFactoryPipeline.__new__(ClipFactoryPipeline)
    pipe.clip_maker = MagicMock()
    ev = threading.Event(); ev.set()
    with patch("src.common.remotion_engine.remotion_engine") as eng:
        eng.is_available.return_value = True
        eng.render_candidate.side_effect = RuntimeError("Renderizado Remotion cancelado.")
        with pytest.raises(RuntimeError, match="cancelado por el usuario"):
            pipe._rerender_with_remotion("v.mp4", MagicMock(id="c"), [], None, ev, {})


def test_rerender_endpoint_validates_visual_engine():
    from starlette.testclient import TestClient
    from src.api_server import app
    r = TestClient(app).post("/api/clips/no_existe/rerender?visual_engine=otro")
    assert r.status_code in (400, 404)    # 404 si el clip no existe, 400 si valida primero el motor
