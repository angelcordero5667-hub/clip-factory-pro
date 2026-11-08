from pathlib import Path
import pytest
from src.common.config import settings
from src.common.youtube_downloader import _base_opts
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.api_server import app
from starlette.testclient import TestClient


@pytest.fixture
def maker():
    return VerticalClipMaker()


def test_base_opts_acceleration():
    opts = _base_opts(None)
    assert opts.get("concurrent_fragment_downloads") == 4
    assert opts.get("buffersize") == 1024 * 1024
    assert opts.get("http_chunk_size") == 10485760


def test_speed_mode_presets(maker):
    cmd_turbo = maker.build_ffmpeg_cmd(
        Path("in.mp4"), Path("out.mp4"), 0.0, 10.0, "F", "[combined]",
        encoder="libx264", speed_mode="turbo"
    )
    assert cmd_turbo[cmd_turbo.index("-preset") + 1] == "superfast"

    cmd_studio = maker.build_ffmpeg_cmd(
        Path("in.mp4"), Path("out.mp4"), 0.0, 10.0, "F", "[combined]",
        encoder="libx264", speed_mode="studio"
    )
    assert cmd_studio[cmd_studio.index("-preset") + 1] == "medium"

    cmd_fast = maker.build_ffmpeg_cmd(
        Path("in.mp4"), Path("out.mp4"), 0.0, 10.0, "F", "[combined]",
        encoder="libx264", speed_mode="fast"
    )
    assert cmd_fast[cmd_fast.index("-preset") + 1] == "veryfast"


def test_hook_zoom_filter(maker):
    filter_str, label = maker.build_filter_complex(1080, 1920, hook_zoom=True)
    assert "split=2[v_base][v_hook]" in filter_str
    assert "crop=w=iw/1.08:h=ih/1.08,scale=1080:1920[v_punch]" in filter_str
    assert "overlay=x=0:y=0:enable='between(t,0,2.5)'[v_hooked]" in filter_str
    assert label == "[v_hooked]"


def test_hook_zoom_with_subtitles(maker, tmp_path):
    ass = tmp_path / "test.ass"
    ass.write_text("dummy", encoding="utf-8")
    filter_str, label = maker.build_filter_complex(1080, 1920, ass_path=ass, hook_zoom=True)
    assert "overlay=x=0:y=0:enable='between(t,0,2.5)'[v_hooked]" in filter_str
    assert "subtitles='" in filter_str
    assert label == "[v_subbed]"


def test_api_speed_mode_validation(monkeypatch):
    from src import api_server
    monkeypatch.setattr(api_server, "_expected_token", lambda: "")
    client = TestClient(app)

    # Válido turbo
    r = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "speed_mode": "turbo",
        "hook_zoom": True
    })
    assert r.status_code == 200
    assert "job_id" in r.json()

    # Válido studio
    r2 = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "speed_mode": "studio",
        "hook_zoom": False
    })
    assert r2.status_code == 200

    # Inválido
    r3 = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "speed_mode": "ultra_mega_warp"
    })
    assert r3.status_code == 400
    assert "Modo de velocidad inválido" in r3.json()["detail"]


def test_subtitles_bounce_and_watermark(tmp_path):
    from src.common.models import TranscriptSegment, WordTimestamp
    from src.agents.agent3_clip_generator.subtitles import SubtitleGenerator

    words = [
        WordTimestamp(word="Hola", start=0.0, end=0.5),
        WordTimestamp(word="mundo", start=0.6, end=1.0)
    ]
    segs = [TranscriptSegment(id=0, start=0.0, end=1.0, text="Hola mundo", words=words)]
    gen = SubtitleGenerator()
    out = gen.generate_ass(
        0.0, 1.0, segs, tmp_path / "bounce.ass",
        style_preset="bounce", watermark_text="@mi_canal"
    )
    content = out.read_text(encoding="utf-8")
    assert "@mi_canal" in content
    assert "\\t(0,70,\\fscx125\\fscy125)" in content

