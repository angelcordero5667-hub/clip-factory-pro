import pytest
from pathlib import Path
from starlette.testclient import TestClient

from src.api_server import app
from src.common.config import settings


@pytest.fixture
def client():
    return TestClient(app)


def test_download_valid_file_in_allowed_directory(client, tmp_path):
    # Crear un archivo dentro de cache_dir (permitido)
    test_f = settings.cache_dir / "security_test_file.txt"
    test_f.write_text("Contenido seguro de prueba", encoding="utf-8")

    try:
        resp = client.get(f"/api/files/download?path={str(test_f.resolve())}")
        assert resp.status_code == 200
        assert resp.text == "Contenido seguro de prueba"
    finally:
        test_f.unlink(missing_ok=True)


def test_download_blocks_path_traversal(client):
    # Intentar descargar un archivo fuera de los directorios autorizados (ej. archivo de Windows)
    forbidden_targets = [
        r"C:\Windows\System32\drivers\etc\hosts",
        r"C:\Windows\win.ini",
        r"..\..\..\..\Windows\win.ini",
        r"/etc/passwd",
        r"C:\Users\Angel\.ssh\id_rsa"
    ]

    for target in forbidden_targets:
        resp = client.get(f"/api/files/download?path={target}")
        assert resp.status_code in (403, 400), f"Falló protección para: {target}"
        if resp.status_code == 403:
            assert "Acceso denegado" in resp.json().get("detail", "")


def test_download_nonexistent_in_allowed_directory(client):
    nonexistent = settings.outputs_dir / "definitely_does_not_exist_9999.mp4"
    resp = client.get(f"/api/files/download?path={str(nonexistent.resolve())}")
    assert resp.status_code == 404
    assert "no encontrado" in resp.json().get("detail", "").lower()
