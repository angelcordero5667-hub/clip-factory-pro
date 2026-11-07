import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from src import api_server
from src.api_server import app
from src.common.database import Database
from src.common.models import ViralMomentCandidate

client = TestClient(app)


# ---------------------------------------------------------------- /api/clips (mocks)
def test_clips_vacio_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setattr(api_server.db, "get_all_videos", lambda: [])
    r = client.get("/api/clips")
    assert r.status_code == 200
    body = r.json()
    assert body["clips"] == []


def test_clips_con_datos(monkeypatch, tmp_path):
    clip = tmp_path / "v_clip_1_v1.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(api_server.db, "get_all_videos", lambda: [
        {"id": "vid_1", "filename": "Mi_Podcast.mp4", "duration": 3700.0},
    ])
    monkeypatch.setattr(api_server.db, "get_candidates_by_video", lambda vid: [{
        "id": "clip_1", "start_time": 10.0, "end_time": 52.0, "duration": 42.0,
        "title": "Título", "hook_text": "gancho", "virality_score": 91,
        "hashtags": ["#a"], "clip_path": str(clip), "status": "pending", "engine": "llm",
    }])
    monkeypatch.setattr(api_server, "generate_thumbnail", lambda *a, **k: None)
    body = client.get("/api/clips").json()
    assert body["duration"] == "1h 1m"
    assert len(body["clips"]) == 1
    c = body["clips"][0]
    assert c["score"] == 91 and c["dur"] == "0:42" and c["ts"] == "0:10 – 0:52"
    assert c["video_url"] == f"/clips_media/{clip.name}"
    assert c["engine"] == "llm"
    assert c["download_url"] == "/api/clips/clip_1/download"


# ---------------------------------------------------------------- token
def test_token_requerido_si_esta_definido(monkeypatch):
    monkeypatch.setenv("CLIP_API_TOKEN", "secreto")
    monkeypatch.setattr(api_server.db, "get_all_videos", lambda: [])
    assert client.get("/api/clips").status_code == 401
    assert client.get("/api/clips", headers={"X-API-Token": "secreto"}).status_code == 200
    assert client.get("/api/clips", headers={"Authorization": "Bearer malo"}).status_code == 401


def test_sin_token_configurado_es_libre(monkeypatch):
    monkeypatch.delenv("CLIP_API_TOKEN", raising=False)
    monkeypatch.setattr(api_server.db, "get_all_videos", lambda: [])
    assert client.get("/api/clips").status_code == 200


# ---------------------------------------------------------------- con base de datos temporal
@pytest.fixture
def tdb(monkeypatch, tmp_path):
    database = Database(db_path=tmp_path / "t.sqlite")
    monkeypatch.setattr(api_server, "db", database)
    monkeypatch.setattr(api_server, "generate_thumbnail", lambda *a, **k: None)
    monkeypatch.delenv("CLIP_API_TOKEN", raising=False)
    clip = tmp_path / "clip1.mp4"
    clip.write_bytes(b"mp4data")
    clip.with_suffix(".jpg").write_bytes(b"jpg")
    database.save_video("v1", "Podcast_abc.mp4", str(tmp_path / "Podcast_abc.mp4"), 600.0, "es")
    cand = ViralMomentCandidate(id="v1_clip_1", start_time=10, end_time=50, duration=40, title="Gran momento",
                                hook_text="gancho", context_text="ctx", virality_score=88, category="humor",
                                reasoning="r", engine="llm")
    database.save_candidates("v1", [cand], clip_paths={"v1_clip_1": str(clip)})
    return database


def test_aprobar_y_descartar(tdb):
    assert client.post("/api/clips/v1_clip_1/status", json={"status": "approved"}).status_code == 200
    assert tdb.get_candidate("v1_clip_1")["status"] == "approved"
    assert client.post("/api/clips/v1_clip_1/status", json={"status": "basura"}).status_code == 400
    assert client.post("/api/clips/nope/status", json={"status": "approved"}).status_code == 404


def test_editar_titulo_y_tiempos(tdb):
    r = client.patch("/api/clips/v1_clip_1", json={"title": "Nuevo título", "start_time": 12, "end_time": 55})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Nuevo título" and body["dirty"] is True and body["start"] == 12
    # validaciones
    assert client.patch("/api/clips/v1_clip_1", json={"start_time": 50, "end_time": 40}).status_code == 400
    assert client.patch("/api/clips/v1_clip_1", json={"start_time": 0, "end_time": 3}).status_code == 400
    assert client.patch("/api/clips/v1_clip_1", json={"start_time": 0, "end_time": 9999}).status_code == 400
    assert client.patch("/api/clips/v1_clip_1", json={"title": "  "}).status_code == 400


def test_editar_solo_titulo_no_marca_dirty(tdb):
    r = client.patch("/api/clips/v1_clip_1", json={"title": "Solo título"})
    assert r.json()["dirty"] is False


def test_rerender_crea_trabajo_en_cola(tdb):
    r = client.post("/api/clips/v1_clip_1/rerender?style=limpio&aspect=1:1")
    assert r.status_code == 200
    job = tdb.get_job(r.json()["job_id"])
    assert job["kind"] == "rerender" and job["status"] == "queued" and job["options"]["subtitle_style"] == "limpio"
    assert client.post("/api/clips/v1_clip_1/rerender?style=zzz").status_code == 400


def test_descarga_de_clip(tdb):
    r = client.get("/api/clips/v1_clip_1/download")
    assert r.status_code == 200 and r.content == b"mp4data"
    assert "attachment" in r.headers["content-disposition"]


def test_zip_por_video(tdb):
    r = client.get("/api/videos/v1/zip")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any(n.endswith(".mp4") for n in names) and any(n.endswith(".jpg") for n in names) and "copys.txt" in names
    # solo aprobados: ninguno aprobado -> 404
    assert client.get("/api/videos/v1/zip?only=approved").status_code == 404
    tdb.update_candidate_status("v1_clip_1", "approved")
    assert client.get("/api/videos/v1/zip?only=approved").status_code == 200
    assert client.get("/api/videos/otro/zip").status_code == 404


def test_clips_por_video_y_lista_de_videos(tdb):
    vids = client.get("/api/videos").json()
    assert vids[0]["id"] == "v1" and vids[0]["clips"] == 1
    body = client.get("/api/clips?video_id=v1").json()
    assert body["video_id"] == "v1"
    assert body["clips"][0]["img"].endswith(".jpg")
    assert client.get("/api/clips?video_id=zzz").status_code == 404


# ---------------------------------------------------------------- trabajos
def test_crear_listar_y_cancelar_trabajos(tdb):
    r = client.post("/api/jobs", json={"source": "https://www.youtube.com/watch?v=abc", "fast": True})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    jobs = client.get("/api/jobs").json()
    assert jobs[0]["id"] == jid and jobs[0]["options"]["fast"] is True and jobs[0]["status"] == "queued"
    assert client.get(f"/api/jobs/{jid}").status_code == 200
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 409
    assert client.get("/api/jobs/9999").status_code == 404


def test_trabajos_validan_entrada(tdb):
    assert client.post("/api/jobs", json={"source": "C:/Windows/system.ini"}).status_code == 400
    assert client.post("/api/jobs", json={"source": "https://x.com/v", "subtitle_style": "feo"}).status_code == 400
    assert client.post("/api/jobs", json={"source": "https://x.com/v", "aspect_ratio": "4:3"}).status_code == 400
    assert client.post("/api/jobs", json={"source": "../../etc/passwd"}).status_code == 400


def test_subida_de_archivo(tdb, monkeypatch, tmp_path):
    monkeypatch.setattr(api_server.settings, "inputs_dir", tmp_path)
    r = client.post("/api/upload", files={"file": ("mi video.mp4", b"abc", "video/mp4")})
    assert r.status_code == 200
    name = r.json()["source"]
    assert (tmp_path / name).read_bytes() == b"abc"
    # un segundo archivo con el mismo nombre no sobrescribe
    r2 = client.post("/api/upload", files={"file": ("mi video.mp4", b"xyz", "video/mp4")})
    assert r2.json()["source"] != name
    assert client.post("/api/upload", files={"file": ("malo.exe", b"x", "application/octet-stream")}).status_code == 400
    # y ahora se puede encolar ese archivo
    assert client.post("/api/jobs", json={"source": name}).status_code == 200


def test_pagina_principal_en_espanol():
    r = client.get("/")
    assert r.status_code == 200 and 'lang="es"' in r.text and "Tus clips" in r.text


def test_system_metrics_endpoint():
    r = client.get("/api/system/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("online", "error")
    assert "cpu_percent" in data and "ram_percent" in data
    assert "encoder" in data and "gpu_status" in data
