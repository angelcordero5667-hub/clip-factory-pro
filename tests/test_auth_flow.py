import os
import pytest
from fastapi.testclient import TestClient

def test_auth_verify_and_login_flow(monkeypatch):
    monkeypatch.setenv("CLIP_API_TOKEN", "test_secret_token_abc123")
    from src.api_server import app
    client = TestClient(app)

    # 1. Sin token -> 401
    res = client.get("/api/auth/verify")
    assert res.status_code == 401

    # 2. Con token por header -> 200
    res = client.get("/api/auth/verify", headers={"X-API-Token": "test_secret_token_abc123"})
    assert res.status_code == 200
    assert res.json()["valid"] is True

    # 3. Login con token falso -> 401
    res = client.post("/api/auth/login", json={"token": "falso"})
    assert res.status_code == 401

    # 4. Login con token correcto -> 200 y set-cookie
    res = client.post("/api/auth/login", json={"token": "test_secret_token_abc123"})
    assert res.status_code == 200
    assert "clip_token" in res.cookies
