import numpy as np

from src.agents.agent2_viral_detector.audio_energy import build_profile, energy_bonus, SAMPLE_RATE
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.agents.agent3_clip_generator.trimming import (
    build_keep_ranges, is_filler, kept_duration, remap_segments, remap_time, select_expr,
)
from src.common.models import TranscriptSegment, WordTimestamp


def W(word, start, end):
    return WordTimestamp(word=word, start=start, end=end)


def speech(gap_after_ten=3.0):
    """30 palabras seguidas (0-15 s), una pausa larga, y 30 más: ~34 s en total."""
    words = [W(f"p{i}", i * 0.5, i * 0.5 + 0.4) for i in range(30)]
    shift = 15.0 + gap_after_ten
    words += [W(f"q{i}", shift + i * 0.5, shift + i * 0.5 + 0.4) for i in range(30)]
    return words


# ----------------------------------------------------------------- muletillas / silencios
def test_is_filler_only_matches_clear_hesitation_sounds():
    assert is_filler("Eh,") and is_filler("mmm") and is_filler("Ém")
    assert not is_filler("este") and not is_filler("pues") and not is_filler("hemos")


def test_long_pause_is_shortened_not_removed():
    words = speech(gap_after_ten=3.0)
    keep = build_keep_ranges(words, 0.0, 33.9)
    assert len(keep) == 2
    gap_left = keep[1][0] - keep[0][1]
    assert gap_left > 2.0                                  # se quitó un tramo
    new_total = kept_duration(keep)
    assert 30.0 < new_total < 33.0                         # y quedó una pausa corta (~0.25 s)


def test_no_cut_when_nothing_to_trim():
    words = [W(f"p{i}", i * 0.5, i * 0.5 + 0.45) for i in range(60)]
    assert build_keep_ranges(words, 0.0, 30.0) == []


def test_filler_words_are_cut():
    words = speech(gap_after_ten=0.1)
    words[10] = W("eh", 5.0, 5.9)
    keep = build_keep_ranges(words, 0.0, 30.0, min_saved=0.5)
    assert keep and any(abs(b - a - 0.0) > 0 for a, b in keep)
    assert remap_time(5.9, keep) < 5.9


def test_refuses_to_destroy_the_clip():
    words = [W("a", 0, 0.3), W("b", 30, 30.3)]
    assert build_keep_ranges(words, 0.0, 31.0) == []       # cortaría > 35 %


def test_remap_time_collapses_removed_ranges():
    keep = [(0.0, 10.0), (13.0, 20.0)]
    assert remap_time(5.0, keep) == 5.0
    assert remap_time(11.5, keep) == 10.0
    assert remap_time(15.0, keep) == 12.0
    assert remap_time(99.0, keep) == 17.0


def test_remap_segments_drops_fillers_and_shifts_words():
    keep = [(0.0, 10.0), (13.0, 20.0)]
    seg = TranscriptSegment(id=1, start=9.0, end=15.0, text="x",
                            words=[W("hola", 9.0, 9.5), W("eh", 11.0, 11.4), W("mundo", 13.5, 14.0)])
    out = remap_segments([seg], keep)
    assert [w.word for w in out[0].words] == ["hola", "mundo"]
    assert out[0].words[1].start == 10.5                  # 13.5 - 3 s quitados


def test_select_expr_is_relative_to_clip_start():
    expr = select_expr([(100.0, 110.0), (113.0, 120.0)], offset=100.0)
    assert expr == "between(t,0.000,10.000)+between(t,13.000,20.000)"


def test_ffmpeg_cmd_and_filter_include_the_cut():
    maker = VerticalClipMaker.__new__(VerticalClipMaker)    # sin cargar FaceTracker ni fuentes
    expr = "between(t,0.000,10.000)+between(t,13.000,20.000)"
    flt, label = VerticalClipMaker.build_filter_complex(maker, 1080, 1920, None, None, cut_expr=expr)
    assert "select='" + expr + "',setpts=N/FRAME_RATE/TB[v_cut]" in flt
    assert label == "[v_cut]"
    cmd = VerticalClipMaker.build_ffmpeg_cmd(maker, "in.mp4", "out.mp4", 0, 17, flt, label, cut_expr=expr)
    af = cmd[cmd.index("-af") + 1]
    assert af.startswith("aselect='") and "asetpts=N/SR/TB" in af and "loudnorm" in af


def test_no_cut_keeps_old_command_unchanged():
    maker = VerticalClipMaker.__new__(VerticalClipMaker)
    flt, label = VerticalClipMaker.build_filter_complex(maker, 1080, 1920)
    assert "select=" not in flt and label == "[combined]"
    cmd = VerticalClipMaker.build_ffmpeg_cmd(maker, "in.mp4", "out.mp4", 0, 17, flt, label)
    assert cmd[cmd.index("-af") + 1] == "loudnorm=I=-14:LRA=7:TP=-1"


# ----------------------------------------------------------------- energía de audio
def _tone(seconds, amp):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * 32767 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def test_loud_section_scores_higher_than_quiet_one():
    audio = np.concatenate([_tone(20, 0.02), _tone(20, 0.6)])
    prof = build_profile(audio)
    assert prof.window_score(25, 35) > prof.window_score(2, 12) + 0.3


def test_flat_audio_is_neutral_and_short_audio_is_ignored():
    prof = build_profile(_tone(30, 0.3))
    assert abs(prof.window_score(5, 15) - 0.5) < 0.01
    assert build_profile(_tone(1, 0.3)) is None


def test_energy_bonus_range():
    assert energy_bonus(1.0) == 8.0 and energy_bonus(0.0) == -8.0 and energy_bonus(0.5) == 0.0
    assert energy_bonus(5.0) == 8.0                         # se recorta al rango
