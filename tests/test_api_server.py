import io
import json
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
    assert "hooks" in c and len(c["hooks"]) == 3
    assert "Gancho A" in c["hooks"][0]["label"]


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
    r = client.post("/api/clips/v1_clip_1/rerender?style=limpio&aspect=1:1&position=bottom_low&size=small")
    assert r.status_code == 200
    job = tdb.get_job(r.json()["job_id"])
    assert job["kind"] == "rerender" and job["status"] == "queued"
    assert job["options"]["subtitle_style"] == "limpio"
    assert job["options"]["subtitle_position"] == "bottom_low"
    assert job["options"]["subtitle_size"] == "small"
    assert client.post("/api/clips/v1_clip_1/rerender?style=zzz").status_code == 400


def test_descarga_de_clip(tdb):
    r = client.get("/api/clips/v1_clip_1/download")
    assert r.status_code == 200 and r.content == b"mp4data"
    assert "attachment" in r.headers["content-disposition"]


def test_zip_por_video(tdb):
    # Simular transcripción para que genere subtítulos .srt en el zip
    tpath = api_server.settings.cache_dir / "transcripts" / "v1_clip_1_edited.json"
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tdata = {
        "video_path": "vid.mp4", "language": "es", "duration": 100.0,
        "segments": [{"id": 0, "start": 12.0, "end": 20.0, "text": "Hola mundo", "words": []}],
        "full_text": "Hola mundo"
    }
    tpath.write_text(json.dumps(tdata), encoding="utf-8")

    r = client.get("/api/videos/v1/zip")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any(n.endswith(".mp4") for n in names) and any(n.endswith(".jpg") for n in names) and "copys.txt" in names
    assert any(n.endswith(".srt") for n in names)
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
    assert client.post("/api/jobs", json={"source": "https://www.youtube.com/watch?v=abc", "layout": "split"}).status_code == 200
    assert client.post("/api/jobs", json={"source": "https://www.youtube.com/watch?v=abc", "layout": "invalido"}).status_code == 400
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


def test_validate_url_ssrf_protection():
    # URL privada/local rechazada
    r = client.get("/api/validate_url", params={"url": "http://127.0.0.1:8080/secret"})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert "local o privada" in data["message"]


def test_validate_url_success_with_thumbnail(monkeypatch):
    class FakeYDL:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {
                "title": "Mi Video Asombroso",
                "duration": 600,
                "uploader": "Canal Pro",
                "thumbnail": "https://img.youtube.com/vi/test/maxresdefault.jpg",
            }

    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    r = client.get("/api/validate_url", params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["title"] == "Mi Video Asombroso"
    assert data["duration"] == 600
    assert data["uploader"] == "Canal Pro"
    assert data["thumbnail"] == "https://img.youtube.com/vi/test/maxresdefault.jpg"
    assert data["is_live"] is False
    assert data["is_upcoming"] is False


def test_validate_url_detects_live_stream(monkeypatch):
    class FakeLiveYDL:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            return {
                "title": "Directo en Vivo Gamer",
                "duration": None,
                "uploader": "Streamer Pro",
                "live_status": "is_live",
                "is_live": True,
            }
    import yt_dlp
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeLiveYDL)
    r = client.get("/api/validate_url", params={"url": "https://www.youtube.com/watch?v=live123"})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["is_live"] is True


def test_list_jobs_includes_video_duration(tdb):
    # En tdb hay un video guardado v1 con duracion 600.0
    jid = tdb.create_job(source="https://ejemplo.com/v", options={}, kind="process")
    tdb.update_job(jid, video_id="v1", status="done")
    jobs = client.get("/api/jobs").json()
    job_item = next((j for j in jobs if j["id"] == jid), None)
    assert job_item is not None
    assert job_item.get("video_duration") == 600.0


def test_create_job_language_and_duration_validation(tdb):
    # Idioma valido 'es', 'en', 'pt' y target_duration 'short', 'medium', 'long'
    r1 = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "language": "es",
        "target_duration": "short",
    })
    assert r1.status_code == 200
    j1 = tdb.get_job(r1.json()["job_id"])
    assert j1["options"]["language"] == "es"
    assert j1["options"]["min_clip_duration"] == 15.0
    assert j1["options"]["max_clip_duration"] == 30.0

    # Idioma 'auto' se normaliza a None
    r2 = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "language": "auto",
        "target_duration": "long",
    })
    assert r2.status_code == 200
    j2 = tdb.get_job(r2.json()["job_id"])
    assert j2["options"]["language"] is None
    assert j2["options"]["min_clip_duration"] == 60.0
    assert j2["options"]["max_clip_duration"] == 90.0

    # Idioma no soportado -> 400
    r_bad_lang = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "language": "fr",
    })
    assert r_bad_lang.status_code == 400
    assert "Idioma no soportado" in r_bad_lang.json()["detail"]

    # Target duration invalida -> 400
    r_bad_td = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "target_duration": "gigante",
    })
    assert r_bad_td.status_code == 400
    assert "Duración objetivo inválida" in r_bad_td.json()["detail"]

    # Rango manual invalido (min < MIN_CLIP_SEC) -> 400
    r_bad_range = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "min_clip_duration": 2.0,
        "max_clip_duration": 40.0,
    })
    assert r_bad_range.status_code == 400
    assert "Rango de duración inválido" in r_bad_range.json()["detail"]

    # Rango manual invalido (min >= max) -> 400
    r_bad_order = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "min_clip_duration": 50.0,
        "max_clip_duration": 30.0,
    })
    assert r_bad_order.status_code == 400


def test_health_deps_endpoint_structure():
    r = client.get("/api/health/deps")
    assert r.status_code == 200
    data = r.json()
    assert "ffmpeg" in data
    assert "encoder" in data
    assert "ollama" in data
    assert "whisper" in data
    assert "yunet" in data
    # No expone rutas sensibles de usuario ni tokens
    text = str(data)
    assert "api_token" not in text
    assert "Bearer" not in text


def test_health_deps_mocked_ollama_and_ffmpeg(monkeypatch, tmp_path):
    import subprocess
    import requests

    # Mock FFmpeg
    class FakeProc:
        returncode = 0
        stdout = "ffmpeg version 7.0.1-mock Copyright (c) 2000-2024"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())

    # Mock Ollama no responde
    class BadResp:
        status_code = 503
        def json(self): return {}

    monkeypatch.setattr(requests, "get", lambda *a, **k: BadResp())

    r = client.get("/api/health/deps")
    assert r.status_code == 200
    data = r.json()
    assert data["ffmpeg"]["available"] is True
    assert "7.0.1-mock" in data["ffmpeg"]["version"]
    assert data["ollama"]["accessible"] is False
    assert "Ollama no responde: se usará el motor heurístico" in data["ollama"]["message"]

    # Mock Ollama responde con modelo cargado
    class GoodResp:
        status_code = 200
        def json(self): return {"models": [{"name": "llama3.2:3b:latest"}]}

    monkeypatch.setattr(requests, "get", lambda *a, **k: GoodResp())

    r2 = client.get("/api/health/deps")
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["ollama"]["accessible"] is True
    assert data2["ollama"]["model_loaded"] is True
    assert "cargado" in data2["ollama"]["message"]


def test_trim_clip_workflow(tdb):
    # 1. Recortar clip a 15s - 35s (duración 20s)
    r = client.patch("/api/clips/v1_clip_1", json={"start_time": 15.0, "end_time": 35.0})
    assert r.status_code == 200
    clip = r.json()
    assert clip["start"] == 15.0
    assert clip["end"] == 35.0
    assert clip["dur"] == "0:20"
    assert clip["dirty"] is True

    # 2. Re-renderizar con el nuevo recorte
    r_re = client.post("/api/clips/v1_clip_1/rerender?style=hormozi&aspect=9:16&position=bottom&size=medium")
    assert r_re.status_code == 200
    job_id = r_re.json()["job_id"]
    job = tdb.get_job(job_id)
    assert job["kind"] == "rerender"
    assert job["candidate_id"] == "v1_clip_1"
    assert job["options"]["subtitle_style"] == "hormozi"


def test_create_job_layout_broll(tdb):
    r = client.post("/api/jobs", json={
        "source": "https://www.youtube.com/watch?v=broll12345",
        "aspect_ratio": "9:16",
        "layout": "broll",
        "max_clips": 3
    })
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    job = tdb.get_job(job_id)
    assert job["options"]["layout"] == "broll"




