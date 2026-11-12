import pytest
from pathlib import Path
from PIL import Image
from starlette.testclient import TestClient

from src.common.config import settings
from src.common.viral_pack import viral_pack_engine, ViralPackEngine
from src.common.models import ViralMomentCandidate, ViralityBreakdown
from src.api_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_viral_pack_engine_singleton():
    assert viral_pack_engine is not None
    assert viral_pack_engine.max_concurrent_renders == 3


def test_generate_vertical_thumbnail(tmp_path):
    # Crear un frame de prueba 1920x1080
    test_frame = tmp_path / "frame.jpg"
    img = Image.new("RGB", (1920, 1080), color=(30, 60, 90))
    img.save(test_frame)

    cand = ViralMomentCandidate(
        id="cand_test_01",
        start_time=10.0,
        end_time=35.0,
        duration=25.0,
        title="TITULO VIRAL IMPACTANTE",
        hook_text="NO VAS A CREER ESTO",
        context_text="Contexto de prueba",
        virality_score=92.5,
        breakdown=ViralityBreakdown(),
        category="impacto",
        reasoning="Alto impacto emocional",
        social_description="Mira este clip",
        hashtags=["#viral", "#shorts", "#tendencia"],
        status="pending",
        engine="heuristic"
    )

    out_thumb = tmp_path / "thumb_01.jpg"
    thumb_path = viral_pack_engine.generate_vertical_thumbnail(
        video_or_frame_path=test_frame,
        candidate=cand,
        output_path=out_thumb,
        badge_text="VIRAL 92%"
    )

    assert Path(thumb_path).exists()
    assert Path(thumb_path).stat().st_size > 1000

    # Verificar resolución 9:16 (1080x1920)
    with Image.open(thumb_path) as im:
        assert im.size == (1080, 1920)


def test_multiplatform_social_metadata():
    cand = ViralMomentCandidate(
        id="cand_test_social",
        start_time=0.0,
        end_time=30.0,
        duration=30.0,
        title="Consejo Millonario",
        hook_text="El secreto de la disciplina",
        context_text="Contexto",
        virality_score=88.0,
        breakdown=ViralityBreakdown(),
        category="motivacion",
        reasoning="Razon",
        social_description="Aprende cómo lograr el éxito con disciplina diaria",
        hashtags=["#exito", "#disciplina", "#negocios"],
        status="pending",
        engine="heuristic"
    )

    meta = viral_pack_engine.generate_social_metadata(cand, clip_idx=1)
    assert "yt_title" in meta
    assert "tk_title" in meta
    assert "fb_title" in meta
    assert "ig_title" in meta
    assert "pinned_comment" in meta
    assert "#shorts" in meta["yt_title"].lower() or "#shorts" in meta.get("hashtags", "").lower()
    assert meta["pinned_comment"] != ""


def test_viral_pack_api_endpoints(client, tmp_path, monkeypatch):
    # 1. Status de pack inexistente
    resp = client.get("/api/viral_pack/non_existent_pack/status")
    assert resp.status_code == 404

    # 2. Cancelar clip en pack inexistente
    resp = client.post("/api/viral_pack/non_existent_pack/cancel/1")
    assert resp.status_code == 404

    # 3. Editar miniatura de clip inexistente
    resp = client.post("/api/clips/cand_fake/edit_thumbnail", json={"title_line1": "NUEVO TITULO"})
    assert resp.status_code == 404

    # 4. Modificar framing de clip inexistente
    resp = client.post("/api/clips/cand_fake/framing", json={"layout_mode": "split"})
    assert resp.status_code == 404


def test_transcription_caching(tmp_path):
    from src.agents.agent1_transcription.transcriber import AudioTranscriber
    from src.common.models import TranscriptResult

    transcriber = AudioTranscriber()
    dummy_audio = tmp_path / "sample.wav"
    dummy_audio.write_bytes(b"RIFFdummydataWAVEfmt ")

    cache_file = transcriber.get_cache_path(dummy_audio)
    dummy_result = TranscriptResult(
        video_path=str(dummy_audio),
        language="es",
        duration=10.0,
        segments=[]
    )
    cache_file.write_text(dummy_result.model_dump_json(), encoding="utf-8")

    # Al tener cache, transcribe() resuelve inmediatamente sin llamar a whisper
    loaded = transcriber.transcribe(str(dummy_audio), use_cache=True)
    assert loaded.duration == 10.0
    assert loaded.language == "es"

    # Limpiar archivo de prueba
    if cache_file.exists():
        cache_file.unlink()
