import pytest
from pathlib import Path
from src.common.remotion_engine import remotion_engine
from src.common.models import ViralMomentCandidate, ViralityBreakdown, TranscriptSegment, WordTimestamp
from src.api_server import app
from starlette.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


def test_remotion_is_available():
    assert remotion_engine.is_available() is True
    assert remotion_engine.remotion_dir.exists()
    assert remotion_engine.render_script.exists()


def test_remotion_build_props():
    cand = ViralMomentCandidate(
        id="cand_remotion_test",
        start_time=5.0,
        end_time=15.0,
        duration=10.0,
        title="TITULO REMOTION",
        hook_text="NO VAS A CREER ESTO",
        context_text="Ctx",
        virality_score=90.0,
        breakdown=ViralityBreakdown(),
        category="impacto",
        reasoning="r",
        social_description="desc",
        hashtags=["#remotion"],
        status="pending",
        engine="heuristic"
    )

    segments = [
        TranscriptSegment(
            id=1,
            start=6.0,
            end=12.0,
            text="ESTE ES UN TEST DE REMOTION",
            words=[
                WordTimestamp(word="ESTE", start=6.0, end=7.0),
                WordTimestamp(word="ES", start=7.0, end=8.0),
                WordTimestamp(word="UN", start=8.0, end=9.0),
                WordTimestamp(word="TEST", start=9.0, end=10.0),
                WordTimestamp(word="DE", start=10.0, end=11.0),
                WordTimestamp(word="REMOTION", start=11.0, end=12.0),
            ]
        )
    ]

    props = remotion_engine.build_props(
        video_path="dummy.mp4",
        candidate=cand,
        transcript_segments=segments,
        options={
            "framing_mode": "split",
            "split_ratio": 0.5,
            "punch_zoom": True,
            "subtitle_style": "hormozi",
            "progress_bar": True,
        },
        fps=30
    )

    assert props["width"] == 1080
    assert props["height"] == 1920
    assert props["fps"] == 30
    assert props["durationInFrames"] == 300
    assert props["clipStartSec"] == 5.0
    assert props["clipEndSec"] == 15.0
    assert props["framingMode"] == "split"
    assert props["subtitleStyle"] == "hormozi"
    assert len(props["subtitles"]) == 1
    assert len(props["subtitles"][0]["words"]) == 6


def test_remotion_player_bundle_exists():
    bundle_path = Path(__file__).resolve().parent.parent / "static" / "js" / "remotion-player.js"
    assert bundle_path.exists()
    assert bundle_path.stat().st_size > 100 * 1024  # Al menos 100 KB compilado


def test_remotion_api_endpoints(client):
    # Probar endpoint de props con un clip inexistente
    resp = client.get("/api/clips/cand_fake/remotion_props")
    assert resp.status_code == 404

    # Probar endpoint de render con clip inexistente
    resp = client.post("/api/clips/cand_fake/render_remotion", json={"fps": 30})
    assert resp.status_code == 404
