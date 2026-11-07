import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import api_server
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.api_server import _host_without_port, _is_public_url, _with_idle, app
from src.common.config import settings

client = TestClient(app)


# ----------------------------------------------------------------- Host (DNS rebinding)
def test_host_without_port():
    assert _host_without_port("127.0.0.1:8501") == "127.0.0.1"
    assert _host_without_port("LOCALHOST") == "localhost"
    assert _host_without_port("[::1]:8501") == "[::1]"


@pytest.mark.parametrize("host", ["127.0.0.1:8501", "localhost:8501", "localhost"])
def test_known_hosts_are_allowed(host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8501", "127.0.0.1.evil.example"])
def test_unknown_host_is_rejected(host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 400


# ----------------------------------------------------------------- CSRF / Origin
def test_cross_origin_post_is_blocked_even_without_body():
    r = client.post("/api/jobs/999999/cancel", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_sec_fetch_site_cross_site_is_blocked():
    r = client.post("/api/jobs/999999/cancel", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_and_non_browser_posts_pass_the_guard():
    # 404 = llegó al manejador (el trabajo no existe), no lo frenó la protección
    same = client.post("/api/jobs/999999/cancel", headers={"Host": "127.0.0.1:8501", "Origin": "http://127.0.0.1:8501"})
    assert same.status_code == 404
    assert client.post("/api/jobs/999999/cancel").status_code == 404   # curl / scripts sin Origin


def test_cross_origin_get_is_not_blocked_but_cannot_be_read_by_other_sites():
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


# ----------------------------------------------------------------- borrado masivo
def test_clear_all_clips_needs_confirmation():
    assert client.delete("/api/clips").status_code == 400
    assert client.delete("/api/clips?confirm=maybe").status_code == 400


# ----------------------------------------------------------------- SSRF
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8501/api/health", "http://localhost/x", "http://10.0.0.5/v", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://0.0.0.0/",
])
def test_private_addresses_are_not_public(url):
    assert _is_public_url(url) is False


def test_public_address_and_unresolvable_host_are_allowed(monkeypatch):
    assert _is_public_url("http://8.8.8.8/video") is True
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("no resuelve")))
    assert _is_public_url("https://no-existe.invalid/v") is True       # yt-dlp dará su propio error


def test_jobs_and_validate_url_refuse_local_targets():
    r = client.post("/api/jobs", json={"source": "http://127.0.0.1:8501/api/health"})
    assert r.status_code == 400 and "local" in r.json()["detail"]
    v = client.get("/api/validate_url", params={"url": "http://10.1.2.3/video"}).json()
    assert v["valid"] is False and "local" in v["message"]


# ----------------------------------------------------------------- subidas
def test_upload_over_limit_is_rejected_and_leaves_no_file(monkeypatch):
    monkeypatch.setenv("CLIP_MAX_UPLOAD_MB", "0.0001")                 # ~100 bytes
    name = f"limite_{int(time.time() * 1000)}.mp4"
    r = client.post("/api/upload", files={"file": (name, b"x" * 5000, "video/mp4")})
    assert r.status_code == 413
    assert not (settings.inputs_dir / name).exists()


# ----------------------------------------------------------------- inactividad del trabajo
def test_idle_seconds_only_for_running_jobs():
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    assert 290 <= _with_idle({"status": "running", "updated_at": old})["idle_seconds"] <= 320
    assert _with_idle({"status": "done", "updated_at": old})["idle_seconds"] is None
    assert _with_idle({"status": "running", "updated_at": "basura"})["idle_seconds"] is None


# ----------------------------------------------------------------- token (archivo o variable)
def test_token_from_file_protects_without_env(monkeypatch, tmp_path):
    f = tmp_path / "tok.txt"
    f.write_text("de-archivo\n", encoding="utf-8")
    monkeypatch.setenv("CLIP_TOKEN_FILE", str(f))
    monkeypatch.delenv("CLIP_API_TOKEN", raising=False)
    monkeypatch.setattr(api_server.db, "get_all_videos", lambda: [])
    assert client.get("/api/clips").status_code == 401
    assert client.get("/api/clips", headers={"X-API-Token": "de-archivo"}).status_code == 200
    assert client.get("/api/clips", headers={"X-API-Token": "otro"}).status_code == 401
    assert client.post("/api/jobs", json={"source": "https://8.8.8.8/v"}).status_code == 401


def test_env_token_wins_over_file_and_health_stays_open(monkeypatch, tmp_path):
    f = tmp_path / "tok.txt"
    f.write_text("archivo", encoding="utf-8")
    monkeypatch.setenv("CLIP_TOKEN_FILE", str(f))
    monkeypatch.setenv("CLIP_API_TOKEN", "entorno")
    assert client.get("/api/clips", headers={"X-API-Token": "archivo"}).status_code == 401
    h = client.get("/api/health")
    assert h.status_code == 200 and h.json()["auth"] is True


def test_missing_or_empty_token_file_means_no_auth(monkeypatch, tmp_path):
    monkeypatch.delenv("CLIP_API_TOKEN", raising=False)
    monkeypatch.setenv("CLIP_TOKEN_FILE", str(tmp_path / "no_existe.txt"))
    assert client.get("/api/health").json()["auth"] is False
    (tmp_path / "vacio.txt").write_text("  \n", encoding="utf-8")
    monkeypatch.setenv("CLIP_TOKEN_FILE", str(tmp_path / "vacio.txt"))
    assert client.get("/api/health").json()["auth"] is False


def test_cookie_is_set_only_with_valid_token_and_secure_over_https(monkeypatch):
    monkeypatch.setenv("CLIP_API_TOKEN", "abc123")
    bad = client.get("/?token=mal")
    assert "clip_token" not in bad.headers.get("set-cookie", "")
    ok = client.get("/?token=abc123", headers={"X-Forwarded-Proto": "https"})
    cookie = ok.headers.get("set-cookie", "")
    assert "clip_token=abc123" in cookie and "Secure" in cookie and "HttpOnly" in cookie


# ----------------------------------------------------------------- cancelar durante el render
def test_cancel_during_render_skips_pending_clips():
    maker = VerticalClipMaker.__new__(VerticalClipMaker)
    started = []
    lock = threading.Lock()

    def fake_generate(video_path, cand, segments, **options):
        with lock:
            started.append(cand.id)
        time.sleep(0.15)
        return f"{cand.id}.mp4"

    maker.generate_clip = fake_generate
    cands = [SimpleNamespace(id=f"c{i}", title="t") for i in range(6)]

    def cancel_on_first(done, total, cand):
        raise RuntimeError("Trabajo cancelado por el usuario.")

    with pytest.raises(RuntimeError, match="cancelado"):
        maker.generate_clips_parallel("v.mp4", cands, [], workers=1, progress=cancel_on_first,
                                      use_scene_detection=False)
    assert len(started) < len(cands)          # no se renderizaron todos
