import subprocess
import pytest
from pathlib import Path
from src.common.viral_enhancements import build_audio_filter_chain
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.agents.agent3_clip_generator.smart_sfx import SFXItem
from src.common.config import settings

def test_audio_profiles_filter_chain():
    # 1. Profile 'social'
    social_chain = build_audio_filter_chain(
        duration=30.0,
        normalize_audio=True,
        audio_profile="social",
        target_lufs=-14.0,
        target_lra=11.0,
        target_tp=-1.5,
        master_limiter=True,
        true_peak_limit=0.79
    )
    assert any("loudnorm=I=-14.0:LRA=11.0:TP=-1.5" in f for f in social_chain)
    assert any("highpass=f=25" in f for f in social_chain)
    assert any("alimiter=level_in=1:level_out=1:limit=0.7900:attack=0.5:release=50:asc=0:level=disabled" in f for f in social_chain)

    # 2. Profile 'original' (no loudnorm, only limiter)
    orig_chain = build_audio_filter_chain(
        duration=30.0,
        normalize_audio=True,
        audio_profile="original",
        master_limiter=True,
        true_peak_limit=0.79
    )
    assert not any("loudnorm" in f for f in orig_chain)
    assert any("highpass=f=25" in f for f in orig_chain)
    assert any("alimiter=" in f for f in orig_chain)

    # 3. Profile 'custom'
    custom_chain = build_audio_filter_chain(
        duration=30.0,
        normalize_audio=True,
        audio_profile="custom",
        target_lufs=-16.0,
        target_lra=8.5,
        target_tp=-2.0,
        master_limiter=True,
        true_peak_limit=0.80
    )
    assert any("loudnorm=I=-16.0:LRA=8.5:TP=-2.0" in f for f in custom_chain)
    assert any("limit=0.8000" in f for f in custom_chain)

    # 4. Limiter disabled
    no_limiter_chain = build_audio_filter_chain(
        duration=30.0,
        normalize_audio=True,
        audio_profile="social",
        master_limiter=False
    )
    assert any("loudnorm" in f for f in no_limiter_chain)
    assert not any("alimiter" in f for f in no_limiter_chain)

def test_ffmpeg_amix_weights_and_master_limiter():
    maker = VerticalClipMaker()
    sfx_dummy = Path("data/assets/sfx/whoosh.wav")
    if not sfx_dummy.exists():
        sfx_dummy.parent.mkdir(parents=True, exist_ok=True)
        # Crear un wav mínimo si no existiera
        subprocess.run([
            settings.ffmpeg_exe, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            str(sfx_dummy)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    item = SFXItem(
        id="sfx_test_1",
        name="whoosh",
        category="transition",
        time=2.0,
        sfx_file="whoosh.wav",
        sfx_path=str(sfx_dummy),
        sfx_url="/assets/whoosh.wav",
        volume=0.35,
        reason="test"
    )

    cmd = maker.build_ffmpeg_cmd(
        input_path=Path("dummy_input.mp4"),
        output_file=Path("dummy_out.mp4"),
        start_time=10.0,
        duration=20.0,
        filter_str="[0:v]scale=1080:1920[v_out]",
        final_label="[v_out]",
        seamless_loop=True,
        sfx_items=[item],
        audio_profile="social",
        target_lufs=-14.0,
        master_limiter=True,
        true_peak_limit=0.79
    )

    cmd_str = " ".join(cmd)
    # Verificar amix con weights explícitos
    assert "weights='1.0 0.70'" in cmd_str
    # Verificar que el post_mix tiene loudnorm, highpass y alimiter
    assert "loudnorm=I=-14.0:LRA=11.0:TP=-1.5" in cmd_str
    assert "highpass=f=25" in cmd_str
    assert "alimiter=level_in=1:level_out=1:limit=0.7900" in cmd_str
    assert "level=disabled" in cmd_str
    assert "[a_final]" in cmd_str
    assert "-map [a_final]" in cmd_str
    assert "-c:a aac -b:a 160k" in cmd_str

def test_true_peak_limiting_on_explosive_audio():
    clip_2 = Path("qa_acceptance/exports/prueba_a_clip_2.mp4")
    if not clip_2.exists():
        pytest.skip("prueba_a_clip_2.mp4 not found for benchmark")

    out_test = Path("qa_acceptance/exports/test_mastered_clip_2.mp4")
    # Aplicar el alimiter
    cmd = [
        settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(clip_2.resolve()),
        "-c:v", "copy",
        "-af", "highpass=f=25,alimiter=level_in=1:level_out=1:limit=0.79:attack=0.5:release=50:asc=0:level=disabled",
        "-c:a", "aac", "-b:a", "160k",
        str(out_test.resolve())
    ]
    subprocess.run(cmd, check=True)

    # Medir ebur128
    ebur_cmd = [
        settings.ffmpeg_exe, "-hide_banner", "-i", str(out_test.resolve()),
        "-af", "ebur128=peak=true", "-f", "null", "-"
    ]
    res = subprocess.run(ebur_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out_log = res.stderr

    import re
    m_tp = re.search(r"Peak:\s+([-\d.]+)\s+dBFS", out_log)
    assert m_tp is not None
    true_peak = float(m_tp.group(1))

    # Medir volumedetect
    vol_cmd = [
        settings.ffmpeg_exe, "-hide_banner", "-i", str(out_test.resolve()),
        "-af", "volumedetect", "-f", "null", "-"
    ]
    res_vol = subprocess.run(vol_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m_max = re.search(r"max_volume:\s+([-\d.]+)\s+dB", res_vol.stderr)
    assert m_max is not None
    max_vol = float(m_max.group(1))

    # Asegurar que no hay clipping:
    # 1. True Peak <= -1.0 dBTP
    # 2. Max volume < 0.0 dBFS
    # 3. No histogram_0db
    assert true_peak <= -1.0, f"True Peak was {true_peak} dBFS, expected <= -1.0 dBTP"
    assert max_vol <= -1.0, f"Max volume was {max_vol} dB, expected <= -1.0 dBFS"
    assert "histogram_0db" not in res_vol.stderr

    if out_test.exists():
        out_test.unlink()
