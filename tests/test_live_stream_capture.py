from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.api_server import JobBody
from src.common import youtube_downloader as dl
from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline
from src.common.models import TranscriptResult, TranscriptSegment, ViralMomentCandidate


def test_jobbody_accepts_live_record_minutes():
    body = JobBody(
        source="https://youtube.com/watch?v=live123",
        live_record_minutes=5.0
    )
    assert body.live_record_minutes == 5.0
    dumped = body.model_dump()
    assert dumped["live_record_minutes"] == 5.0


def test_capture_live_stream_configures_ffmpeg_args(tmp_path):
    mock_ydl = MagicMock()
    mock_ydl.__enter__.return_value.extract_info.return_value = {
        "title": "Stream de Prueba",
        "id": "live999"
    }
    mock_ydl.__enter__.return_value.prepare_filename.return_value = str(tmp_path / "live_capture_live999.mp4")

    # Create dummy output file
    target_file = tmp_path / "live_capture_live999.mp4"
    target_file.write_text("dummy video")

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl) as ctor:
        out_file, title = dl.capture_live_stream(
            "https://youtube.com/watch?v=live999",
            duration_seconds=300.0,
            output_dir=tmp_path
        )
        assert "[EN VIVO]" in title
        assert "Stream de Prueba" in title
        assert Path(out_file).exists()

        # Check ydl configuration
        opts = ctor.call_args[0][0]
        assert opts.get("external_downloader") == "ffmpeg"
        assert opts.get("external_downloader_args") == {"ffmpeg_i": ["-t", "300"]}
        assert "ffmpeg_location" in opts


def test_pipeline_uses_capture_live_stream_when_flag_present(tmp_path):
    pipeline = ClipFactoryPipeline()
    dummy_video = tmp_path / "live_recorded.mp4"
    dummy_video.write_bytes(b"dummy mp4 content")

    dummy_transcript = TranscriptResult(
        video_path=str(dummy_video),
        segments=[
            TranscriptSegment(id=0, start=0.0, end=10.0, text="Bochinche en vivo en la casa"),
            TranscriptSegment(id=1, start=10.0, end=30.0, text="Increible pelea momento viral")
        ],
        language="es",
        duration=30.0
    )

    with patch("src.agents.agent5_qa_optimizer.pipeline.capture_live_stream", return_value=(str(dummy_video), "[EN VIVO] Alofoke 3")) as mock_cap, \
         patch.object(pipeline.transcriber, "transcribe", return_value=dummy_transcript), \
         patch("src.agents.agent5_qa_optimizer.pipeline.compute_energy_profile", return_value=None), \
         patch.object(pipeline.detector, "detect_moments", return_value=[
             ViralMomentCandidate(
                 id="c1", start_time=2.0, end_time=25.0, duration=23.0,
                 title="Momento caliente", hook="Pelea total", hook_text="Pelea total",
                 context_text="Bochinche", reasoning="Drama en vivo", virality_score=95.0,
                 reason="Drama", transcript_excerpt="Bochinche", category="debate"
             )
         ]), \
         patch.object(pipeline.clip_maker, "generate_clips_parallel", side_effect=lambda v, cands, *a, **k: {c.id: tmp_path / f"{c.id}.mp4" for c in cands}), \
         patch("src.agents.agent5_qa_optimizer.pipeline.download_youtube_video") as mock_dl_vid:

        vid_id, cands = pipeline.run_pipeline(
            video_input="https://youtube.com/watch?v=live123",
            live_record_minutes=5.0,
            use_cache=False,
            render_clips=True
        )

        # Verified: capture_live_stream was called for 300 seconds
        mock_cap.assert_called_once()
        assert mock_cap.call_args[1]["duration_seconds"] == 300.0

        # Verified: standard download_youtube_video was NOT called because it was already captured
        mock_dl_vid.assert_not_called()
        assert len(cands) == 1
        assert cands[0].virality_score == 95.0
