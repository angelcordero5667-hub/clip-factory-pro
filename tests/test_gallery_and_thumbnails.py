import pytest
from pathlib import Path
from src.common.thumbnail_designer import (
    get_gallery_manifest,
    detect_mentioned_artists,
    create_viral_composite_thumbnail
)

def test_gallery_manifest_loads():
    items = get_gallery_manifest()
    assert isinstance(items, list)
    assert len(items) > 0
    ids = [it["id"] for it in items]
    assert "yailin" in ids or "kreizy_k" in ids

def test_detect_mentioned_artists():
    text = "bueno el tema con yailin y rochy rd fue por los millones"
    matches = detect_mentioned_artists(text)
    match_ids = [m["id"] for m in matches]
    assert "yailin" in match_ids or "rochy_rd" in match_ids or "dinero_millones" in match_ids

def test_create_viral_composite_thumbnail(tmp_path):
    base_frame = tmp_path / "base.jpg"
    out_thumb = tmp_path / "thumb.jpg"
    
    # Run creation
    res = create_viral_composite_thumbnail(
        base_frame_path=base_frame,
        output_path=out_thumb,
        main_title="¡TITULO VIRAL DE PRUEBA!",
        subtitle="SUBTITULO TEST",
        gallery_asset_filename="dinero_millones.jpg",
        top_badge="💰 TEST BADGE"
    )
    assert res.exists()
    assert res.stat().st_size > 1000

def test_gallery_api_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.api_server import app
    
    client = TestClient(app)
    
    # 1. GET /api/gallery
    resp = client.get("/api/gallery")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) > 0
    
    # 2. Upload asset
    dummy_img = tmp_path / "artista_test.jpg"
    dummy_img.write_bytes(b"dummy image data")
    
    with open(dummy_img, "rb") as f:
        resp_up = client.post(
            "/api/gallery/upload",
            data={"name": "Artista Test", "category": "artista", "tags": "test,musica"},
            files={"file": ("artista_test.jpg", f, "image/jpeg")}
        )
    assert resp_up.status_code == 200
    up_data = resp_up.json()
    assert up_data["ok"] is True
    assert up_data["item"]["id"] == "artista_test"
