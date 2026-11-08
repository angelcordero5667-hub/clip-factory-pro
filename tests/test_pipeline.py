import unittest
from unittest.mock import ANY, MagicMock, patch
from pathlib import Path
from src.common.models import TranscriptResult, TranscriptSegment, ViralMomentCandidate
from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline
from src.agents.agent5_qa_optimizer.optimizer import MemoryOptimizer

class TestPipeline(unittest.TestCase):

    def setUp(self):
        self.mock_transcriber = MagicMock()
        self.mock_detector = MagicMock()
        self.mock_clip_maker = MagicMock()
        self.optimizer = MemoryOptimizer(max_ram_gb=24.0)

        self.pipeline = ClipFactoryPipeline(
            transcriber=self.mock_transcriber,
            detector=self.mock_detector,
            clip_maker=self.mock_clip_maker,
            optimizer=self.optimizer
        )

    def test_memory_optimizer_check(self):
        used = self.optimizer.get_memory_usage_gb()
        self.assertGreater(used, 0.0)
        self.assertTrue(self.optimizer.check_memory_safe())

    def test_full_pipeline_flow(self):
        # Mock transcript
        seg = TranscriptSegment(id=0, start=0.0, end=25.0, text="Texto de prueba viral")
        self.mock_transcriber.transcribe.return_value = TranscriptResult(
            video_path="dummy_video.mp4",
            language="es",
            duration=30.0,
            segments=[seg],
            full_text="Texto de prueba viral"
        )

        # Mock candidate
        cand = ViralMomentCandidate(
            id="c_test_1",
            start_time=0.0,
            end_time=22.0,
            duration=22.0,
            hook_text="Texto de prueba",
            context_text="Contexto",
            virality_score=91.0,
            category="humor",
            reasoning="Razón",
            status="pending"
        )
        self.mock_detector.detect_moments.return_value = [cand]
        self.mock_clip_maker.detect_scene_cuts_near.return_value = [1.0, 2.0]
        self.mock_clip_maker.generate_clips_parallel.side_effect = lambda *a, **k: {c.id: Path("dummy_rendered_clip.mp4") for c in k.get("candidates", a[1])}

        # Create dummy file to satisfy existence check
        dummy_video = Path("tests/dummy_pipeline_input.mp4")
        dummy_video.parent.mkdir(exist_ok=True)
        dummy_video.write_text("video dummy")

        try:
            steps_logged = []
            def callback(msg):
                steps_logged.append(msg)

            vid_id, candidates = self.pipeline.run_pipeline(
                str(dummy_video),
                max_candidates=1,
                render_clips=True,
                use_cache=False,
                progress_callback=callback
            )

            self.assertTrue(vid_id.startswith("vid_"))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].virality_score, 91.0)
            self.assertGreater(len(steps_logged), 3)
            self.mock_transcriber.transcribe.assert_called_once()
            self.mock_detector.detect_moments.assert_called_once()
            # cortes de escena una sola vez por video, render en lote
            self.mock_clip_maker.detect_scene_cuts_near.assert_called_once()
            self.mock_clip_maker.detect_scene_cuts.assert_not_called()
            self.mock_clip_maker.generate_clips_parallel.assert_called_once()
            self.assertEqual(
                self.mock_clip_maker.generate_clips_parallel.call_args.kwargs["scene_cuts"], [1.0, 2.0])
            self.assertTrue(candidates[0].id.startswith(vid_id))
        finally:
            if dummy_video.exists():
                dummy_video.unlink()

    def test_scene_detection_is_skipped_when_clips_are_pause_aligned(self):
        seg = TranscriptSegment(id=0, start=0.0, end=25.0, text="Texto de prueba viral")
        self.mock_transcriber.transcribe.return_value = TranscriptResult(
            video_path="dummy.mp4", language="es", duration=30.0, segments=[seg], full_text="x")
        cand = ViralMomentCandidate(
            id="c_aligned", start_time=0.0, end_time=22.0, duration=22.0, hook_text="h", context_text="c",
            virality_score=90.0, category="humor", reasoning="r", pause_aligned=True)
        self.mock_detector.detect_moments.return_value = [cand]
        self.mock_clip_maker.generate_clips_parallel.side_effect = lambda *a, **k: {c.id: Path("x.mp4") for c in a[1]}

        dummy_video = Path("tests/dummy_pipeline_aligned.mp4")
        dummy_video.write_text("video dummy")
        try:
            self.pipeline.run_pipeline(str(dummy_video), max_candidates=1, render_clips=True, use_cache=False)
        finally:
            dummy_video.unlink(missing_ok=True)

        self.mock_clip_maker.detect_scene_cuts.assert_not_called()
        self.mock_clip_maker.detect_scene_cuts_near.assert_not_called()
        self.assertEqual(self.mock_clip_maker.generate_clips_parallel.call_args.kwargs["scene_cuts"], [])

    @patch("src.agents.agent5_qa_optimizer.pipeline.download_youtube_audio")
    @patch("src.agents.agent5_qa_optimizer.pipeline.download_youtube_video")
    def test_youtube_pipeline_downloads_once(self, mock_dl_video, mock_dl_audio):
        dummy_audio = Path("tests/dummy_yt_audio.m4a")
        dummy_video = Path("tests/dummy_yt_video.mp4")
        dummy_audio.write_text("audio")
        dummy_video.write_text("video")

        mock_dl_audio.return_value = (str(dummy_audio), "Test YT Video")
        mock_dl_video.return_value = (str(dummy_video), "Test YT Video")

        seg = TranscriptSegment(id=0, start=0.0, end=25.0, text="Texto viral youtube")
        self.mock_transcriber.transcribe.return_value = TranscriptResult(
            video_path=str(dummy_audio),
            language="es",
            duration=30.0,
            segments=[seg],
            full_text="Texto viral youtube"
        )

        c1 = ViralMomentCandidate(id="c1", start_time=0.0, end_time=15.0, duration=15.0,
                                  hook_text="Hook 1", context_text="Ctx 1", virality_score=88.0, category="humor", reasoning="R1")
        c2 = ViralMomentCandidate(id="c2", start_time=15.0, end_time=30.0, duration=15.0,
                                  hook_text="Hook 2", context_text="Ctx 2", virality_score=85.0, category="humor", reasoning="R2")
        self.mock_detector.detect_moments.return_value = [c1, c2]
        self.mock_clip_maker.detect_scene_cuts_near.return_value = [5.0]
        self.mock_clip_maker.generate_clips_parallel.side_effect = lambda *a, **k: {c.id: Path("clip.mp4") for c in k.get("candidates", a[1])}

        try:
            vid_id, candidates = self.pipeline.run_pipeline(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                max_candidates=2,
                render_clips=True,
                use_cache=False,
            )

            # Validar que el audio se descargó exactamente 1 vez
            mock_dl_audio.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ", progress=ANY)
            # Validar que el video 720p se descargó exactamente 1 vez para TODOS los clips
            mock_dl_video.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ", progress=ANY)
            # Cortes de escena: 1 sola vez, solo alrededor del inicio y fin de los clips (no el video entero)
            self.mock_clip_maker.detect_scene_cuts_near.assert_called_once_with(
                str(dummy_video), [0.0, 15.0, 15.0, 30.0])
            self.mock_clip_maker.detect_scene_cuts.assert_not_called()
            # Ambos clips renderizados en lote desde la misma fuente 720p local
            self.assertEqual(len(candidates), 2)
            self.assertEqual(self.mock_clip_maker.generate_clips_parallel.call_args[0][0], str(dummy_video))
        finally:
            if dummy_audio.exists():
                dummy_audio.unlink()
            if dummy_video.exists():
                dummy_video.unlink()

if __name__ == "__main__":
    unittest.main()

