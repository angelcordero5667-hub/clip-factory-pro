import subprocess
from pathlib import Path

import pytest

from src.common.config import settings
from src.common.models import ViralMomentCandidate
from src.agents.agent3_clip_generator import clip_maker as cm
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker


@pytest.fixture
def maker():
    return VerticalClipMaker()


def test_filtro_blur_a_baja_resolucion(maker):
    f, label = maker.build_filter_complex(1080, 1920)
    # el fondo se reduce a 270x480, se desenfoca ahí y se reescala a 1080x1920
    assert "scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur" in f
    assert "boxblur=8:2,scale=1080:1920[bg_blur]" in f
    assert "overlay=(W-w)/2:(H-h)/2[combined]" in f
    assert label == "[combined]"


def test_filtro_con_subtitulos(maker, tmp_path):
    ass = tmp_path / "s.ass"
    ass.write_text("x", encoding="utf-8")
    f, label = maker.build_filter_complex(1080, 1920, ass)
    assert "subtitles='" in f and label == "[v_subbed]"


def test_comando_libx264(maker, tmp_path):
    cmd = maker.build_ffmpeg_cmd(Path("in.mp4"), tmp_path / "o.mp4", 12.0, 30.0, "F", "[combined]", encoder="libx264")
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-preset") + 1] == "veryfast"
    assert cmd[cmd.index("-crf") + 1] == "24"
    assert cmd[cmd.index("-threads") + 1] == str(settings.render.threads_per_clip)
    assert cmd[cmd.index("-ss") + 1] == "12.000"


def test_comando_amf_y_pretrimmed(maker, tmp_path):
    cmd = maker.build_ffmpeg_cmd(Path("in.mp4"), tmp_path / "o.mp4", 12.0, 30.0, "F", "[combined]",
                                 encoder="h264_amf", is_pretrimmed=True)
    assert cmd[cmd.index("-c:v") + 1] == "h264_amf"
    assert "-preset" not in cmd
    assert cmd[cmd.index("-ss") + 1] == "0.0"


def test_pick_encoder_respeta_config(monkeypatch):
    monkeypatch.setattr(cm, "available_encoders", lambda: frozenset({"libx264", "h264_amf"}))
    monkeypatch.setattr(settings.render, "use_hw_encoder", True)
    assert cm.pick_encoder() == "h264_amf"
    monkeypatch.setattr(settings.render, "use_hw_encoder", False)
    assert cm.pick_encoder() == "libx264"
    monkeypatch.setattr(settings.render, "use_hw_encoder", True)
    monkeypatch.setattr(cm, "available_encoders", lambda: frozenset({"libx264"}))
    assert cm.pick_encoder() == "libx264"


def test_fallback_a_libx264_si_falla_amf(maker, monkeypatch):
    monkeypatch.setattr(cm, "pick_encoder", lambda: "h264_amf")
    llamadas = []

    class R:
        def __init__(self, rc): self.returncode, self.stderr = rc, "boom"

    def fake_run(cmd, **kw):
        llamadas.append(cmd)
        return R(1 if "h264_amf" in cmd else 0)

    monkeypatch.setattr(cm.subprocess, "run", fake_run)
    maker._run_ffmpeg(lambda enc: ["ffmpeg", "-c:v", enc])
    assert [c[-1] for c in llamadas] == ["h264_amf", "libx264"]


def test_ffmpeg_exe_existe():
    assert Path(settings.ffmpeg_exe).exists() or settings.ffmpeg_exe == "ffmpeg"


@pytest.mark.parametrize("encoder", ["libx264", "h264_amf"])
def test_render_real_con_cada_encoder(maker, tmp_path, monkeypatch, encoder):
    if encoder not in cm.available_encoders():
        pytest.skip(f"{encoder} no disponible")
    src = tmp_path / "src.mp4"
    subprocess.run([settings.ffmpeg_exe, "-y", "-f", "lavfi", "-i", "testsrc=duration=6:size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-c:a", "aac", str(src)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    monkeypatch.setattr(cm, "pick_encoder", lambda: encoder)
    monkeypatch.setattr(settings, "outputs_dir", tmp_path)
    cand = ViralMomentCandidate(id=f"t_{encoder}", start_time=0.0, end_time=6.0, duration=6.0, hook_text="h",
                                context_text="c", virality_score=80, category="humor", reasoning="r")
    out = maker.generate_clip(str(src), cand, [], with_subtitles=False, use_scene_detection=False)
    probe = subprocess.run([str(Path(settings.ffmpeg_exe).with_name("ffprobe.exe")), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,codec_name", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == "h264,1080,1920"
