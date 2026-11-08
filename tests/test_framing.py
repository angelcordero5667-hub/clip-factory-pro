import subprocess
from pathlib import Path

import pytest

from src.common.config import settings
from src.common.models import ViralMomentCandidate
from src.agents.agent3_clip_generator import clip_maker as cm
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.agents.agent3_clip_generator.face_tracker import FaceTracker
from src.agents.agent3_clip_generator.framing import (
    FaceSample, Framing, build_x_expr, choose_framing, decimate_keyframes,
    detect_two_speakers, fill_gaps, moving_average, smooth_track,
)


def samples(xs_list):
    return [FaceSample(t=float(i), xs=xs) for i, xs in enumerate(xs_list)]


def test_media_movil_suaviza():
    out = moving_average([0, 10, 0, 10, 0], 3)
    assert out[2] == pytest.approx(20 / 3)
    assert max(out) < 10


def test_fill_gaps():
    assert fill_gaps([None, 0.4, None, None, 0.8]) == [0.4, 0.4, 0.4, 0.8, 0.8]
    assert fill_gaps([None, None]) == [0.5, 0.5]


def test_keyframes_zona_muerta():
    pts = [(float(i), 100.0 + (i % 2)) for i in range(20)]  # ruido de 1 px
    assert len(decimate_keyframes(pts, tolerance=5)) == 2    # cámara quieta: solo extremos
    ramp = [(float(i), i * 50.0) for i in range(10)]
    assert len(decimate_keyframes(ramp, tolerance=5)) == 2   # rampa lineal: 2 keyframes
    step = [(float(i), 100.0 if i < 5 else 400.0) for i in range(10)]
    assert len(decimate_keyframes(step, tolerance=5)) >= 3   # salto: más keyframes


def test_expresion_x():
    expr = build_x_expr([(0.0, 100.0), (4.0, 300.0)])
    assert "lt(t,4.00)" in expr and "100.0" in expr and "300.0" in expr
    assert build_x_expr([(0.0, 50.0)]) == "50.0"
    assert build_x_expr([]) == "0"


def test_sin_rostro_mantiene_blur():
    f = choose_framing(samples([[], [], [], []]), 1280, 720, 1080, 1920)
    assert f.mode == "blur"


def test_rostro_inestable_mantiene_blur():
    f = choose_framing(samples([[0.5], [], [], [], [], [], []]), 1280, 720, 1080, 1920)
    assert f.mode == "blur"


def test_fuente_vertical_no_recorta():
    f = choose_framing(samples([[0.5]] * 5), 720, 1280, 1080, 1920)
    assert f.mode == "blur"


def test_un_hablante_recorta_9_16_centrado():
    s = samples([[0.30]] * 10)
    f = choose_framing(s, 1280, 720, 1080, 1920)
    assert f.mode == "crop"
    assert f.crop_w == 404            # 720 * 9/16 = 405 -> par
    # x = 0.30*1280 - 202 = 182
    assert "182" in f.x_expr


def test_recorte_se_mantiene_dentro_de_la_imagen():
    f = choose_framing(samples([[0.99]] * 6), 1280, 720, 1080, 1920)
    assert f.mode == "crop"
    assert f"{1280 - f.crop_w:.1f}" in f.x_expr   # clamp al borde derecho


def test_trayectoria_sigue_al_hablante():
    s = samples([[0.2]] * 5 + [[0.8]] * 5)
    track = smooth_track(s, window=3)
    assert track[0][1] == pytest.approx(0.2) and track[-1][1] == pytest.approx(0.8)
    assert 0.2 < track[5][1] < 0.8     # transición suave, no salto


def test_dos_hablantes_pantalla_dividida():
    s = samples([[0.25, 0.75]] * 8)
    assert detect_two_speakers(s) == (0.25, 0.75)
    f = choose_framing(s, 1280, 720, 1080, 1920)
    assert f.mode == "split"
    assert f.split_xs[0] < f.split_xs[1]
    # no se divide en horizontal
    assert choose_framing(s, 1280, 720, 1080, 1080, allow_split=False).mode == "crop"


def test_dos_rostros_juntos_no_dividen():
    assert detect_two_speakers(samples([[0.45, 0.55]] * 8)) is None


def test_filtros_por_modo():
    maker = VerticalClipMaker()
    f_crop, _ = maker.build_filter_complex(1080, 1920, framing=Framing("crop", 404, "if(lt(t,2.00),10.0,50.0)"))
    assert "crop=w=404:h=ih:x='if(lt(t,2.00),10.0,50.0)':y=0,scale=1080:1920" in f_crop
    f_split, label = maker.build_filter_complex(1080, 1920, framing=Framing("split", 810, "", (100, 300)))
    assert "vstack=inputs=2" in f_split and "scale=1080:960" in f_split and label == "[combined]"
    f_broll, b_label = maker.build_filter_complex(1080, 1920, framing=Framing("broll", 810, "", (100, 0)))
    assert "vstack=inputs=2" in f_broll and "cam_top" in f_broll and "broll_bot" in f_broll and b_label == "[combined]"
    f_blur, _ = maker.build_filter_complex(1080, 1920, framing=Framing("blur"))
    assert "boxblur" in f_blur


def test_choose_framing_broll():
    s = samples([[0.40]] * 6)
    f = choose_framing(s, 1280, 720, 1080, 1920, layout_mode="broll")
    assert f.mode == "broll"
    assert "b-roll" in f.reason.lower()


def _synthetic(tmp_path: Path) -> Path:
    src = tmp_path / "src.mp4"
    subprocess.run([settings.ffmpeg_exe, "-y", "-f", "lavfi", "-i", "testsrc=duration=6:size=1280x720:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-c:a", "aac", str(src)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return src


def _render_with_detector(tmp_path, monkeypatch, detector_factory, cid):
    src = _synthetic(tmp_path)
    monkeypatch.setattr(cm, "pick_encoder", lambda: "libx264")
    monkeypatch.setattr(settings, "outputs_dir", tmp_path)
    maker = VerticalClipMaker()
    maker.face_tracker = FaceTracker(detector_factory)
    cand = ViralMomentCandidate(id=cid, start_time=0.0, end_time=6.0, duration=6.0, hook_text="h",
                                context_text="c", virality_score=80, category="humor", reasoning="r")
    out = maker.generate_clip(str(src), cand, [], with_subtitles=False, use_scene_detection=False, smart_framing=True)
    probe = subprocess.run([str(Path(settings.ffmpeg_exe).with_name("ffprobe.exe")), "-v", "error", "-select_streams",
                            "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    return probe


def test_render_real_crop_dinamico(tmp_path, monkeypatch):
    # hablante que se mueve de izquierda a derecha
    state = {"i": 0}

    def factory(w, h):
        def detect(frame):
            state["i"] += 1
            return [(min(0.9, 0.2 + 0.1 * state["i"]), 0.15)]
        return detect

    assert _render_with_detector(tmp_path, monkeypatch, factory, "crop1") == "1080,1920"


def test_render_real_split(tmp_path, monkeypatch):
    factory = lambda w, h: (lambda frame: [(0.25, 0.15), (0.75, 0.15)])
    assert _render_with_detector(tmp_path, monkeypatch, factory, "split1") == "1080,1920"


def test_render_real_sin_rostro_usa_blur(tmp_path, monkeypatch):
    factory = lambda w, h: (lambda frame: [])
    assert _render_with_detector(tmp_path, monkeypatch, factory, "blur1") == "1080,1920"
