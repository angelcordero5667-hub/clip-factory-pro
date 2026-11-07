import unittest
from pathlib import Path
from src.common.database import Database
from src.common.models import ViralMomentCandidate

class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("tests/test_db.sqlite")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = Database(db_path=self.test_db_path)

    def tearDown(self):
        import gc
        gc.collect()
        for suffix in ("", "-wal", "-shm"):   # el modo WAL crea archivos auxiliares
            p = Path(str(self.test_db_path) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except PermissionError:
                    pass

    def test_indexes_and_wal_mode(self):
        import sqlite3
        conn = sqlite3.connect(str(self.test_db_path))
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_candidates_video", names)
            self.assertIn("idx_jobs_status", names)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        finally:
            conn.close()

    def test_save_and_retrieve_video_and_candidates(self):
        self.db.save_video(
            video_id="v_100",
            filename="test_video.mp4",
            filepath="/dummy/test_video.mp4",
            duration=120.5,
            language="es"
        )
        videos = self.db.get_all_videos()
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["id"], "v_100")

        cand = ViralMomentCandidate(
            id="c_1",
            start_time=10.0,
            end_time=35.0,
            duration=25.0,
            hook_text="Hook inicial",
            context_text="Contexto general",
            virality_score=8.7,
            category="humor",
            reasoning="Chiste bien estructurado",
            status="pending"
        )
        self.db.save_candidates("v_100", [cand], clip_paths={"c_1": "/dummy/clip.mp4"})
        cands = self.db.get_candidates_by_video("v_100")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["virality_score"], 8.7)
        self.assertEqual(cands[0]["status"], "pending")

        # Test status update
        self.db.update_candidate_status("c_1", "approved")
        cands_updated = self.db.get_candidates_by_video("v_100")
        self.assertEqual(cands_updated[0]["status"], "approved")

        stats = self.db.get_stats()
        self.assertEqual(stats["total_videos"], 1)
        self.assertEqual(stats["approved_clips"], 1)
        self.assertEqual(stats["pending_clips"], 0)

if __name__ == "__main__":
    unittest.main()
