import pytest
from src.agents.agent3_clip_generator.framing import (
    FaceSample,
    Framing,
    choose_framing,
    smooth_track_ema,
    detect_two_speakers
)

def test_smooth_track_ema_deadband_stability():
    # Micro-oscilaciones alrededor de 0.50 (+/- 0.02)
    # El filtro deadband con tolerancia 0.035 debe mantener la cámara quieta
    samples = [
        FaceSample(t=0.0, xs=[0.50]),
        FaceSample(t=1.0, xs=[0.52]),
        FaceSample(t=2.0, xs=[0.49]),
        FaceSample(t=3.0, xs=[0.51]),
        FaceSample(t=4.0, xs=[0.50]),
    ]
    track = smooth_track_ema(samples, alpha=0.25, deadband=0.035)
    xs = [x for t, x in track]
    # Comprobar que no hay saltos bruscos
    for x in xs:
        assert 0.48 <= x <= 0.52

def test_smooth_track_ema_smooth_lateral_pan():
    # El sujeto camina de x=0.20 a x=0.80
    samples = [
        FaceSample(t=0.0, xs=[0.20]),
        FaceSample(t=1.0, xs=[0.40]),
        FaceSample(t=2.0, xs=[0.60]),
        FaceSample(t=3.0, xs=[0.80]),
    ]
    track = smooth_track_ema(samples, alpha=0.30, deadband=0.035)
    xs = [x for t, x in track]
    # Debe ser monótonamente creciente y suave
    for i in range(1, len(xs)):
        assert xs[i] >= xs[i-1]

def test_framing_modes_klap():
    samples_single = [FaceSample(t=0.0, xs=[0.45]), FaceSample(t=1.0, xs=[0.46])]
    samples_dual = [
        FaceSample(t=0.0, xs=[0.25, 0.75]),
        FaceSample(t=1.0, xs=[0.24, 0.76]),
        FaceSample(t=2.0, xs=[0.26, 0.74]),
    ]

    # 1. active_speaker
    f_active = choose_framing(samples_single, 1920, 1080, 1080, 1920, layout_mode="active_speaker")
    assert f_active.mode == "crop"
    assert "Klap EMA" in f_active.reason

    # 2. dual_speaker
    f_dual = choose_framing(samples_dual, 1920, 1080, 1080, 1920, layout_mode="dual_speaker")
    assert f_dual.mode == "split"
    assert len(f_dual.split_xs) == 2

    # 3. dynamic_crop
    f_dyn = choose_framing(samples_single, 1920, 1080, 1080, 1920, layout_mode="dynamic_crop")
    assert f_dyn.mode == "crop"

    # 4. podcast mode con 2 hablantes -> split
    f_pod_dual = choose_framing(samples_dual, 1920, 1080, 1080, 1920, layout_mode="podcast")
    assert f_pod_dual.mode == "split"

    # 5. podcast mode con 1 hablante -> crop
    f_pod_single = choose_framing(samples_single, 1920, 1080, 1080, 1920, layout_mode="podcast")
    assert f_pod_single.mode == "crop"
