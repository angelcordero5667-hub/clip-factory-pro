import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import numpy as np

from src.common.models import parse_time_str, TranscriptResult, TranscriptSegment
from src.agents.agent3_clip_generator.framing import choose_framing, FaceSample
from src.agents.agent2_viral_detector.audio_energy import EnergyProfile, find_hype_moments
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.api_server import JobBody, validate_url
from src.jobs import JobWorker


class TestStreamOptimizations(unittest.TestCase):

    def test_parse_time_str(self):
        self.assertEqual(parse_time_str("01:25:30"), 5130.0)
        self.assertEqual(parse_time_str("15:00"), 900.0)
        self.assertEqual(parse_time_str("45"), 45.0)
        self.assertEqual(parse_time_str(120), 120.0)
        self.assertIsNone(parse_time_str(""))
        self.assertIsNone(parse_time_str("invalid:time:format:extra"))

    def test_job_body_stream_options(self):
        body = JobBody(
            source="https://twitch.tv/videos/12345678",
            time_range_start="01:10:00",
            time_range_end="01:30:00",
            layout="gaming"
        )
        self.assertEqual(body.time_range_start, "01:10:00")
        self.assertEqual(body.time_range_end, "01:30:00")
        self.assertEqual(body.layout, "gaming")

    def test_choose_framing_gaming_mode(self):
        samples = [FaceSample(t=1.0, xs=[0.8])]
        framing = choose_framing(samples, src_w=1920, src_h=1080, out_w=1080, out_h=1920, layout_mode="gaming")
        self.assertEqual(framing.mode, "gaming")
        self.assertGreater(framing.crop_w, 0)
        self.assertTrue(framing.split_xs[0] >= 0)

    def test_choose_framing_blur_mode(self):
        samples = [FaceSample(t=1.0, xs=[0.5])]
        framing = choose_framing(samples, src_w=1920, src_h=1080, out_w=1080, out_h=1920, layout_mode="blur")
        self.assertEqual(framing.mode, "blur")
        self.assertIn("desenfoque solicitado", framing.reason)

    def test_find_hype_moments_extracts_peaks(self):
        # 100 segundos con pico de energía en t = 40..50
        norm = np.full(200, 0.2, dtype=np.float32)
        norm[80:100] = 0.95  # t = 40..50s
        profile = EnergyProfile(hop=0.5, norm=norm)
        peaks = find_hype_moments(profile, min_duration=10.0, max_duration=20.0, top_n=3)
        self.assertTrue(len(peaks) >= 1)
        best_peak = max(peaks, key=lambda x: x[2])
        start, end, score = best_peak
        self.assertEqual(start, 40.0)
        self.assertEqual(end, 50.0)
        self.assertGreater(score, 0.8)

    def test_detector_incorporates_hype_peaks(self):
        detector = ViralMomentDetector()
        seg1 = TranscriptSegment(id=1, start=0.0, end=15.0, text="Intro tranquila del directo")
        seg2 = TranscriptSegment(id=2, start=15.0, end=35.0, text="Grito brutal golazo increíble reacción")
        seg3 = TranscriptSegment(id=3, start=35.0, end=50.0, text="Volvemos a jugar normal")
        transcript = TranscriptResult(
            video_path="test.mp4", language="es", duration=50.0, segments=[seg1, seg2, seg3]
        )
        norm = np.full(100, 0.1, dtype=np.float32)
        norm[30:70] = 0.99  # t = 15..35s
        energy = EnergyProfile(hop=0.5, norm=norm)
        candidates = detector.detect_moments(transcript, use_llm=False, energy=energy, include_hype=True)
        self.assertTrue(len(candidates) > 0)
        self.assertTrue(any(c.virality_score >= 80 for c in candidates))

    def test_job_worker_passes_stream_options(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run_pipeline.return_value = ("vid_123", [])

        mock_db = MagicMock()
        mock_db.get_job.return_value = {"status": "running"}

        worker = JobWorker(database=mock_db, pipeline_factory=lambda: mock_pipeline)
        job = {
            "id": 42,
            "source": "https://twitch.tv/videos/999",
            "kind": "video",
            "options": {
                "max_clips": 3,
                "time_range_start": "00:10:00",
                "time_range_end": "00:25:00",
                "layout": "gaming"
            }
        }
        worker.run_job(job)
        mock_pipeline.run_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.run_pipeline.call_args
        self.assertEqual(kwargs.get("time_range"), (600.0, 1500.0))
        self.assertEqual(kwargs.get("layout_mode"), "gaming")

    @patch("yt_dlp.YoutubeDL")
    def test_validate_url_detects_streams(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            "title": "Directo Épico de Twitch",
            "duration": 7200,
            "uploader": "StreamerPro"
        }
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        res = validate_url("https://www.twitch.tv/videos/123456")
        self.assertTrue(res["valid"])
        self.assertTrue(res["is_stream"])
        self.assertEqual(res["platform"], "Twitch")

    def test_api_jobs_accepts_stream_fields(self):
        from fastapi.testclient import TestClient
        from src.api_server import app
        client = TestClient(app)
        res = client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "time_range_start": "00:10:00",
            "time_range_end": "00:20:00",
            "layout": "gaming"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "queued")

    def test_api_jobs_rejects_invalid_layout(self):
        from fastapi.testclient import TestClient
        from src.api_server import app
        client = TestClient(app)
        res = client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "layout": "invalid_layout_xyz"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("inválido", res.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
