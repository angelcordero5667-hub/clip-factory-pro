import unittest
import os
import subprocess
from pathlib import Path
from src.common.models import ViralMomentCandidate, TranscriptSegment, WordTimestamp
from src.agents.agent3_clip_generator.subtitles import SubtitleGenerator
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.common.config import settings

class TestAgent3ClipMaker(unittest.TestCase):

    def setUp(self):
        self.clip_maker = VerticalClipMaker(target_width=1080, target_height=1920, threads=4)
        self.sub_gen = SubtitleGenerator()

    def test_subtitle_ass_generation(self):
        segments = [
            TranscriptSegment(
                id=0,
                start=2.0,
                end=6.0,
                text="Este es un momento viral",
                words=[
                    WordTimestamp(word="Este", start=2.0, end=2.8),
                    WordTimestamp(word="es", start=2.8, end=3.2),
                    WordTimestamp(word="un", start=3.2, end=3.5),
                    WordTimestamp(word="momento", start=3.5, end=4.5),
                    WordTimestamp(word="viral", start=4.5, end=5.8),
                ]
            )
        ]
        out_ass = settings.cache_dir / "test_subs.ass"
        res_path = self.sub_gen.generate_ass(clip_start=2.0, clip_end=6.0, segments=segments, output_path=out_ass)

        self.assertTrue(res_path.exists())
        content = res_path.read_text(encoding="utf-8")
        self.assertIn("[Script Info]", content)
        self.assertIn("Dialogue:", content)
        self.assertIn("MOMENTO", content)
        out_ass.unlink()

    def test_no_overwrite_unique_path(self):
        # Create a dummy file to verify unique version incrementing
        p1 = self.clip_maker.get_unique_output_path("video_test.mp4", "cand_1")
        p1.write_text("dummy")
        
        # Calling again should produce v2, not overwrite
        p2 = self.clip_maker.get_unique_output_path("video_test.mp4", "cand_1")
        self.assertNotEqual(str(p1), str(p2))
        self.assertTrue(str(p2).endswith("_v2.mp4"))

        # Clean up
        if p1.exists():
            p1.unlink()

    def test_snap_to_natural_boundary(self):
        cuts = [10.2, 25.4, 40.0]
        # Close to 10.2
        snapped = self.clip_maker.snap_to_natural_boundary(10.5, cuts, tolerance=0.8)
        self.assertEqual(snapped, 10.2)
        # Far from any cut
        not_snapped = self.clip_maker.snap_to_natural_boundary(18.0, cuts, tolerance=0.8)
        self.assertEqual(not_snapped, 18.0)

    def test_live_ffmpeg_render_synthetic_clip(self):
        # Create 3s synthetic MP4 video
        synthetic_video = settings.cache_dir / "synthetic_test.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-c:a", "aac",
            str(synthetic_video.resolve())
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        self.assertTrue(synthetic_video.exists())

        cand = ViralMomentCandidate(
            id="test_cand",
            start_time=0.5,
            end_time=2.5,
            duration=2.0,
            hook_text="Synthetic Hook",
            context_text="Synthetic Context",
            virality_score=8.5,
            category="humor",
            reasoning="Testing ffmpeg rendering",
            status="pending"
        )
        
        segments = [
            TranscriptSegment(
                id=0, start=0.5, end=2.5, text="PRUEBA VERTICAL",
                words=[
                    WordTimestamp(word="PRUEBA", start=0.5, end=1.4),
                    WordTimestamp(word="VERTICAL", start=1.5, end=2.4)
                ]
            )
        ]

        rendered_clip = self.clip_maker.generate_clip(
            video_path=str(synthetic_video),
            candidate=cand,
            transcript_segments=segments,
            with_subtitles=True,
            use_scene_detection=False
        )

        self.assertTrue(rendered_clip.exists())
        self.assertGreater(rendered_clip.stat().st_size, 1000)

        # Cleanup
        if synthetic_video.exists():
            synthetic_video.unlink()
        if rendered_clip.exists():
            rendered_clip.unlink()

if __name__ == "__main__":
    unittest.main()
