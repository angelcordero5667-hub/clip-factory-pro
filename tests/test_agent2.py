import unittest
from unittest.mock import patch, MagicMock
from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp, ViralMomentCandidate
from src.agents.agent2_viral_detector.detector import ViralMomentDetector

class TestAgent2ViralDetector(unittest.TestCase):

    def setUp(self):
        self.detector = ViralMomentDetector(min_duration=10.0, max_duration=30.0, max_candidates=5)

        # Create dummy transcript of 40 seconds
        segments = [
            TranscriptSegment(id=0, start=0.0, end=5.0, text="¿Sabías cuál es el peor error financiero?"),
            TranscriptSegment(id=1, start=5.0, end=12.0, text="Mucha gente gasta todo su dinero en cosas innecesarias jaja."),
            TranscriptSegment(id=2, start=12.0, end=20.0, text="El secreto está en invertir antes de gastar."),
            TranscriptSegment(id=3, start=20.0, end=28.0, text="Es brutal ver cómo cambia tu vida con esta regla."),
            TranscriptSegment(id=4, start=28.0, end=35.0, text="Nadie te enseña este método en la universidad."),
            TranscriptSegment(id=5, start=35.0, end=40.0, text="Empieza hoy mismo y verás la diferencia.")
        ]
        self.sample_transcript = TranscriptResult(
            video_path="dummy.mp4",
            language="es",
            duration=40.0,
            segments=segments,
            full_text="¿Sabías cuál es el peor error financiero? Mucha gente gasta todo su dinero en cosas innecesarias jaja. El secreto está en invertir antes de gastar. Es brutal ver cómo cambia tu vida con esta regla. Nadie te enseña este método en la universidad. Empieza hoy mismo y verás la diferencia."
        )

    def test_deduplicate_candidates(self):
        # Two candidates overlapping by > 50%
        c1 = ViralMomentCandidate(
            id="c1", start_time=5.0, end_time=25.0, duration=20.0,
            hook_text="hook 1", context_text="ctx 1", virality_score=8.5,
            category="discusion", reasoning="reason"
        )
        c2 = ViralMomentCandidate(
            id="c2", start_time=6.0, end_time=26.0, duration=20.0,
            hook_text="hook 2", context_text="ctx 2", virality_score=7.0,
            category="discusion", reasoning="reason"
        )
        c3 = ViralMomentCandidate(
            id="c3", start_time=28.0, end_time=38.0, duration=10.0,
            hook_text="hook 3", context_text="ctx 3", virality_score=9.0,
            category="sorpresa", reasoning="reason"
        )

        deduped = self.detector.deduplicate_candidates([c1, c2, c3], overlap_threshold=0.5)
        # c2 should be removed because c1 has higher score (8.5 vs 7.0) and overlaps heavily
        self.assertEqual(len(deduped), 2)
        ids = [c.id for c in deduped]
        self.assertIn("c3", ids)
        self.assertIn("c1", ids)
        self.assertNotIn("c2", ids)

    def test_heuristic_detection(self):
        candidates = self.detector._detect_heuristic(self.sample_transcript)
        self.assertGreater(len(candidates), 0)
        top = candidates[0]
        self.assertGreaterEqual(top.virality_score, 50.0)
        self.assertLessEqual(top.virality_score, 100.0)
        self.assertIn(top.category, ["humor", "discusion", "reaccion", "sorpresa", "ensenanza"])

    @patch("requests.post")
    def test_detect_with_ollama_mock(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": """[
                {
                    "start_time": 0.0,
                    "end_time": 20.0,
                    "hook_text": "¿Sabías cuál es el peor error financiero?",
                    "context_text": "Explicación sobre gastos innecesarios e inversión",
                    "virality_score": 9.5,
                    "category": "ensenanza",
                    "reasoning": "Apertura magnética con gancho y consejo aplicable"
                }
            ]"""
        }
        mock_post.return_value = mock_response

        results = self.detector.detect_moments(self.sample_transcript)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].virality_score, 95.0)
        self.assertEqual(results[0].category, "ensenanza")

if __name__ == "__main__":
    unittest.main()
