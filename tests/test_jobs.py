from pathlib import Path

from src.common.database import Database
from src.jobs import JobWorker
from src.agents.agent5_qa_optimizer.pipeline import STEPS


class FakePipeline:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def run_pipeline(self, video_input, step_callback=None, **kw):
        self.calls.append((video_input, kw))
        if self.fail:
            raise RuntimeError("boom")
        for i in range(len(STEPS)):
            step_callback(i, 0.5, f"paso {i}")
        return "vid_x", [object(), object()]

    def rerender_candidate(self, candidate_id, **kw):
        self.calls.append(("rerender", candidate_id, kw))
        return Path("x.mp4")


def make(tmp_path, fail=False):
    d = Database(db_path=tmp_path / "j.sqlite")
    fp = FakePipeline(fail)
    return d, fp, JobWorker(database=d, pipeline_factory=lambda: fp)


def test_cola_fifo_y_reclamo_atomico(tmp_path):
    d, _, _ = make(tmp_path)
    a = d.create_job("https://a")
    b = d.create_job("https://b")
    assert d.claim_next_job()["id"] == a
    assert d.claim_next_job()["id"] == b
    assert d.claim_next_job() is None
    assert d.get_job(a)["status"] == "running"


def test_trabajo_completo_actualiza_pasos_y_estado(tmp_path):
    d, fp, w = make(tmp_path)
    jid = d.create_job("https://a", {"fast": True, "max_clips": 3, "subtitle_style": "limpio"})
    w.run_job(d.claim_next_job())
    job = d.get_job(jid)
    assert job["status"] == "done" and job["video_id"] == "vid_x" and job["progress"] == 1.0
    assert job["step_label"] == STEPS[-1] and "2 clips" in job["message"]
    kw = fp.calls[0][1]
    assert kw["fast"] is True and kw["max_candidates"] == 3 and kw["subtitle_style"] == "limpio"


def test_error_se_registra_sin_tumbar_el_worker(tmp_path):
    d, _, w = make(tmp_path, fail=True)
    jid = d.create_job("https://a")
    w.run_job(d.claim_next_job())
    job = d.get_job(jid)
    assert job["status"] == "error" and "boom" in job["error"]


def test_rerender_job(tmp_path):
    d, fp, w = make(tmp_path)
    jid = d.create_job("c1", {"subtitle_style": "karaoke"}, kind="rerender", candidate_id="c1")
    w.run_job(d.claim_next_job())
    assert d.get_job(jid)["status"] == "done"
    assert fp.calls[0][0] == "rerender" and fp.calls[0][2]["subtitle_style"] == "karaoke"


def test_trabajos_interrumpidos_pasan_a_error(tmp_path):
    d, _, _ = make(tmp_path)
    jid = d.create_job("https://a")
    d.claim_next_job()
    assert d.reset_stale_jobs() == 1
    assert d.get_job(jid)["status"] == "error"


def test_cancelar_solo_en_cola(tmp_path):
    d, _, _ = make(tmp_path)
    a = d.create_job("https://a")
    assert d.cancel_job(a) is True
    assert d.claim_next_job() is None   # un trabajo cancelado no se procesa
    b = d.create_job("https://b")
    d.claim_next_job()
    assert d.cancel_job(b) is False


def test_migracion_agrega_columnas(tmp_path):
    import sqlite3
    p = tmp_path / "old.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE videos (id TEXT PRIMARY KEY, filename TEXT NOT NULL, filepath TEXT NOT NULL, duration REAL, language TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    con.commit(); con.close()
    d = Database(db_path=p)
    d.save_video("v", "f.mp4", "/f.mp4", 10, "es", source="https://x", transcript_path="/t.json")
    assert d.get_video("v")["transcript_path"] == "/t.json"
