from types import SimpleNamespace
from unittest.mock import patch

from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker


def _maker():
    return VerticalClipMaker.__new__(VerticalClipMaker)   # sin cargar FaceTracker ni fuentes


def _proc(stderr):
    return SimpleNamespace(stderr=stderr, returncode=0)


SHOWINFO = (
    "[Parsed_showinfo_1 @ 0x1] n:   0 pts:  90 pts_time:1.5 duration: 1 fmt:yuv420p\n"
    "[Parsed_showinfo_1 @ 0x1] n:   1 pts: 240 pts_time:4 duration: 1 fmt:yuv420p\n"
)


def test_cuts_are_offset_to_absolute_time_and_deduplicated():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _proc(SHOWINFO)

    with patch("subprocess.run", side_effect=fake_run):
        cuts = _maker().detect_scene_cuts_near("v.mp4", [100.0, 100.04, 200.0], margin=2.5)

    # 100.0 y 100.04 se redondean a 100.0 -> 2 ventanas, no 3
    assert len(calls) == 2
    # ventana en 100 s empieza en 97.5: 97.5+1.5=99.0 y 97.5+4=101.5; la de 200 s: 197.5 -> 199.0 y 201.5
    assert cuts == [99.0, 101.5, 199.0, 201.5]
    first = calls[0]
    assert first[first.index("-ss") + 1] == "97.500" and first[first.index("-t") + 1] == "5.000"
    assert first.index("-ss") < first.index("-i")            # búsqueda directa: no decodifica desde el inicio


def test_window_never_starts_before_zero():
    with patch("subprocess.run", return_value=_proc("pts_time:0.5")) as run:
        cuts = _maker().detect_scene_cuts_near("v.mp4", [1.0], margin=2.5)
    cmd = run.call_args[0][0]
    assert cmd[cmd.index("-ss") + 1] == "0.000"
    assert cuts == [0.5]


def test_failures_are_swallowed_and_other_windows_still_run():
    results = iter([TimeoutError("lento"), _proc("pts_time:2")])

    def fake_run(cmd, **kw):
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    with patch("subprocess.run", side_effect=fake_run):
        cuts = _maker().detect_scene_cuts_near("v.mp4", [50.0, 80.0], margin=2.5)
    assert cuts == [79.5]                                     # la 1.ª ventana falló, la 2.ª aportó su corte (77.5 + 2)


def test_no_times_means_no_ffmpeg_calls():
    with patch("subprocess.run") as run:
        assert _maker().detect_scene_cuts_near("v.mp4", []) == []
    run.assert_not_called()
