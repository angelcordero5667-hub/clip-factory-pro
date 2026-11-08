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


def test_focus_prompt_heuristic():
    from src.common.models import TranscriptResult, TranscriptSegment
    from src.agents.agent2_viral_detector.detector import ViralMomentDetector

    segs = [
        TranscriptSegment(id=0, start=0.0, end=15.0, text="Hablamos sobre cómo ganar dinero y hacer negocios rentables."),
        TranscriptSegment(id=1, start=15.0, end=30.0, text="Luego fuimos a comer una hamburguesa deliciosa en el parque.")
    ]
    transcript = TranscriptResult(
        video_path="dummy.mp4",
        text="Hablamos sobre ganar dinero y luego comimos una hamburguesa.",
        duration=30.0,
        language="es",
        segments=segs
    )
    detector = ViralMomentDetector(min_duration=10.0, max_duration=20.0)

    cands_focused = detector._detect_heuristic(transcript, focus_prompt="negocios e inversiones de dinero")
    assert any("Alineado con el tema solicitado" in c.reasoning for c in cands_focused)
    cand_focused = next(c for c in cands_focused if "Alineado con el tema solicitado" in c.reasoning)
    assert cand_focused.virality_score >= 80


def test_clip_transcript_and_srt_export(tmp_path, monkeypatch):
    from src import api_server
    from src.common.database import db
    from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp, ViralMomentCandidate, ViralityBreakdown
    monkeypatch.setattr(api_server, "_expected_token", lambda: "")
    client = TestClient(app)

    vid_id = "test_vid_transcript"
    t_file = tmp_path / "trans.json"
    t_res = TranscriptResult(
        video_path="dummy.mp4",
        language="es",
        duration=60.0,
        segments=[
            TranscriptSegment(
                id=0, start=10.0, end=15.0, text="Prueba de transcripción",
                words=[
                    WordTimestamp(word="Prueba", start=10.0, end=11.0),
                    WordTimestamp(word="de", start=11.1, end=12.0),
                    WordTimestamp(word="transcripción", start=12.1, end=15.0),
                ]
            )
        ]
    )
    t_file.write_text(t_res.model_dump_json(), encoding="utf-8")

    dummy_clip = tmp_path / "dummy_clip.mp4"
    dummy_clip.write_bytes(b"dummy")
    db.save_video(vid_id, "test.mp4", str(tmp_path / "test.mp4"), 60.0, "es", "local", transcript_path=str(t_file))
    c = ViralMomentCandidate(
        id="test_clip_trans_1",
        start_time=10.0,
        end_time=15.0,
        duration=5.0,
        title="Clip Trans",
        hook_text="Prueba de transcripción",
        context_text="Ctx",
        virality_score=85.0,
        breakdown=ViralityBreakdown(),
        category="sorpresa",
        reasoning="r",
        social_description="desc",
        hashtags=["#test"],
        status="pending",
        engine="heuristic"
    )
    db.save_candidates(vid_id, [c], {"test_clip_trans_1": str(dummy_clip)})

    # Limpiar cualquier cache previo
    edited_cache = settings.cache_dir / "transcripts" / "test_clip_trans_1_edited.json"
    if edited_cache.exists():
        edited_cache.unlink()

    # 1. GET /api/clips/{id}/transcript
    r = client.get("/api/clips/test_clip_trans_1/transcript")
    assert r.status_code == 200
    data = r.json()
    assert len(data["segments"]) == 1
    assert data["segments"][0]["words"][0]["rel_start"] == 0.0
    assert data["segments"][0]["words"][0]["word"] == "Prueba"

    # 2. PUT /api/clips/{id}/transcript (edit word to "Demostración")
    seg_data = data["segments"][0]
    seg_data["words"][0]["word"] = "Demostración"
    seg_data["text"] = "Demostración de transcripción"
    r_put = client.put("/api/clips/test_clip_trans_1/transcript", json={"segments": [seg_data]})
    assert r_put.status_code == 200
    assert r_put.json()["ok"] is True

    # 3. GET /api/clips/{id}/export_srt
    r_srt = client.get("/api/clips/test_clip_trans_1/export_srt")
    assert r_srt.status_code == 200
    assert "00:00:00,000 --> 00:00:05,000" in r_srt.text
    assert "Demostración de transcripción" in r_srt.text

