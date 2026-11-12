"""Dashboard único de Clip Factory: FastAPI + src/web/index.html.

Arranque: python -m src.api_server   (escucha solo en 127.0.0.1:8501)
Token opcional: variable de entorno CLIP_API_TOKEN.
"""
import io
import ipaddress
import json
import os
import re
import requests
import secrets
import shutil
import socket
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse
import psutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("APIServer")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.database import db
from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent1_transcription.dominican_slang import (
    correct_dominican_text,
    normalize_dominican_segments
)
from src.common.thumbnail_designer import (
    get_gallery_manifest,
    detect_mentioned_artists,
    create_viral_composite_thumbnail,
    INTERNAL_GALLERY_DIR as GALLERY_DIR,
    DESKTOP_GALLERY_DIR
)
from src.common.viral_pack import viral_pack_engine
from src.common.remotion_engine import remotion_engine
from src.jobs import JobWorker

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
WEB_DIR = Path(__file__).resolve().parent / "web"
OUTPUTS_DIR = settings.outputs_dir
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

SUBTITLE_STYLES = (
    "hormozi", "limpio", "karaoke", "minimal",
    "hormozi_classic", "hormozi_neon", "beast", "mrbeast",
    "gaming", "podcast", "clean", "classic", "neon", "minimal_white",
    "bounce", "glow", "pop", "bouncing",
    "none", "off", "sin_subtitulos"
)
ASPECT_RATIOS = ("9:16", "1:1", "16:9")
LAYOUT_MODES = ("auto", "gaming", "blur", "split", "broll")
SPEED_MODES = ("turbo", "fast", "studio")
VALID_STATUS = ("pending", "approved", "rejected")
MIN_CLIP_SEC, MAX_CLIP_SEC = 5.0, 180.0
TARGET_DURATIONS = {
    "short": (15.0, 30.0),
    "medium": (30.0, 60.0),
    "long": (60.0, 90.0),
}
VALID_LANGUAGES = ("es", "en", "pt")

worker = JobWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("CLIP_NO_WORKER") != "1":
        worker.start()
    yield
    worker.stop()


app = FastAPI(title="Clip Factory Pro", lifespan=lifespan)


# Hosts con los que se puede abrir el dashboard. Evita el "DNS rebinding" (una web ajena que
# resuelve su dominio a 127.0.0.1 para manejar tu servidor). Para un túnel o dominio propio:
#   set CLIP_ALLOWED_HOSTS=mi-tunel.trycloudflare.com
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"} | {
    h.strip().lower() for h in os.environ.get("CLIP_ALLOWED_HOSTS", "").split(",") if h.strip()}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_without_port(host_header: str) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):                      # IPv6: [::1]:8501
        return h.split("]")[0] + "]"
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


@app.middleware("http")
async def request_guard(request: Request, call_next):
    """Rechaza Host desconocidos (rebinding) y peticiones que cambian datos desde otro origen (CSRF)."""
    host_header = request.headers.get("host", "")
    h = _host_without_port(host_header)
    if h not in _ALLOWED_HOSTS and not h.endswith(".trycloudflare.com"):
        return JSONResponse({"detail": "Host no permitido."}, status_code=400)
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        cross_site = request.headers.get("sec-fetch-site") == "cross-site"
        if cross_site or (origin and origin.split("://", 1)[-1].lower() != host_header.strip().lower()):
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
    return await call_next(request)


def _expected_token() -> str:
    """Token de acceso: variable CLIP_API_TOKEN o, si no existe, el archivo data/api_token.txt.

    Con el archivo, el servidor queda protegido sin importar quién lo arranque (start.bat, un agente,
    un túnel). Se relee en cada petición: cambiar el archivo rota el token sin reiniciar.
    """
    env = os.environ.get("CLIP_API_TOKEN", "").strip()
    if env:
        return env
    token_file = Path(os.environ.get("CLIP_TOKEN_FILE") or (settings.base_dir / "data" / "api_token.txt"))
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@app.middleware("http")
async def token_guard(request: Request, call_next):
    """Si hay token (variable o archivo), lo exige en /api y /clips_media (salvo /api/health).

    Se acepta como cabecera `Authorization: Bearer <t>`, `X-API-Token`, cookie
    `clip_token` o `?token=` (al abrir `/?token=...` se guarda la cookie).
    """
    expected = _expected_token()
    if not expected:
        return await call_next(request)

    path = request.url.path
    provided = (
        request.headers.get("x-api-token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("clip_token")
        or request.query_params.get("token")
    )
    token_ok = provided is not None and secrets.compare_digest(provided, expected)

    public_paths = ("/api/health", "/api/auth/login", "/api/auth/verify")
    if (path.startswith("/api") or path.startswith("/clips_media")) and path not in public_paths and not token_ok:
        return JSONResponse({"detail": "Token inválido o ausente."}, status_code=401)

    response = await call_next(request)
    if path == "/" and request.query_params.get("token") and token_ok:
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie("clip_token", expected, httponly=True, samesite="lax", secure=secure,
                            max_age=60 * 60 * 24 * 30)
    return response


@app.post("/api/auth/login")
async def auth_login(request: Request):
    """Permite autenticarse enviando el token en JSON {'token': '...'} o como cabecera."""
    expected = _expected_token()
    if not expected:
        return {"status": "ok", "auth_required": False}
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    token = (body.get("token") or request.headers.get("x-api-token") or request.query_params.get("token") or "").strip()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Token de acceso incorrecto.")
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp = JSONResponse({"status": "ok", "message": "Autenticación exitosa."})
    resp.set_cookie("clip_token", expected, httponly=True, samesite="lax", secure=secure, max_age=60 * 60 * 24 * 30)
    return resp


@app.get("/api/auth/verify")
async def auth_verify(request: Request):
    """Comprueba si la sesión o cabecera actual está autenticada."""
    expected = _expected_token()
    if not expected:
        return {"valid": True, "auth_required": False}
    provided = (
        request.headers.get("x-api-token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("clip_token")
        or request.query_params.get("token")
    )
    if not provided or not secrets.compare_digest(provided.strip(), expected):
        raise HTTPException(status_code=401, detail="Token no válido o ausente.")
    return {"valid": True, "auth_required": True}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if (WEB_DIR / "studio").is_dir():
    # Interfaz "AI Creative Studio" (archivos estáticos; se activa con ?ui=studio).
    app.mount("/studio", StaticFiles(directory=str(WEB_DIR / "studio")), name="studio")
app.mount("/clips_media", StaticFiles(directory=str(OUTPUTS_DIR)), name="clips_media")
if GALLERY_DIR.exists():
    app.mount("/gallery_media", StaticFiles(directory=str(GALLERY_DIR)), name="gallery_media")
if DESKTOP_GALLERY_DIR.exists():
    app.mount("/gallery_desktop", StaticFiles(directory=str(DESKTOP_GALLERY_DIR)), name="gallery_desktop")

BROLL_DIR = Path("data/broll")
if BROLL_DIR.exists():
    app.mount("/broll_media", StaticFiles(directory=str(BROLL_DIR)), name="broll_media")

SFX_DIR = Path("data/assets/sfx")
if SFX_DIR.exists():
    app.mount("/sfx_media", StaticFiles(directory=str(SFX_DIR)), name="sfx_media")


# --------------------------------------------------------------------------- utilidades
def generate_thumbnail(video_path: Path, output_thumb: Path):
    """Miniatura para clips antiguos que no la tienen (los nuevos la crean al renderizar)."""
    if not output_thumb.exists() and video_path.exists():
        try:
            subprocess.run(
                [settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.0",
                 "-i", str(video_path.resolve()), "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4",
                 str(output_thumb.resolve())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except Exception:
            pass


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _human_duration(seconds: float) -> str:
    minutes = int((seconds or 0) // 60)
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60}m"


def _clean_title(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"_[A-Za-z0-9_-]{11}_(audio|video)$", "", stem)
    return stem.replace("_", " ").strip()


def format_clip(c: Dict[str, Any]) -> Dict[str, Any]:
    """Clip de la BD -> JSON que consume el dashboard."""
    title = c.get("title") or "Clip sin título"
    hook = c.get("hook_text") or ""
    tags = c.get("hashtags") or ["#viral", "#podcast", "#fyp"]
    tags_str = " ".join(tags) if isinstance(tags, list) else str(tags)
    social = c.get("social_description") or ""

    clean_hook = hook.strip().strip('"').strip("'")
    clean_title = title.strip()
    hook_a = f"\"{clean_hook}\"" if clean_hook else f"¿Sabías esto sobre {clean_title}?"
    hook_b = f"El error más común con {clean_title}: {clean_hook}" if clean_hook else f"Nadie te cuenta la verdad de {clean_title}..."
    hook_c = f"Esto te cambiará la perspectiva: {clean_title}"

    video_url = thumb_url = download_url = ""


    c_path = c.get("clip_path")


    if c_path and Path(c_path).exists():


        clip_file = Path(c_path)


        video_url = f"/clips_media/{clip_file.name}"


        download_url = f"/api/clips/{c['id']}/download"


        # Ninguna miniatura automatica cubre el video: los clips se muestran como video nativo


        thumb_url = ""

    return {
        "id": c["id"],
        "video_id": c.get("video_id"),
        "img": thumb_url,
        "video_url": video_url,
        "download_url": download_url,
        "score": int(c.get("virality_score") or 0),
        "dur": _clock(c.get("duration") or 0),
        "title": title,
        "ts": f"{_clock(c['start_time'])} – {_clock(c['end_time'])}",
        "start": c["start_time"],
        "end": c["end_time"],
        "status": c.get("status") or "pending",
        "engine": c.get("engine") or "heuristic",
        "category": c.get("category") or "",
        "dirty": bool(c.get("dirty")),
        "breakdown": {"hook": c.get("hook_score"), "flow": c.get("flow_score"), "trend": c.get("trend_score")},
        "hooks": [
            {"label": "Gancho A (Directo)", "text": hook_a},
            {"label": "Gancho B (Controversia)", "text": hook_b},
            {"label": "Gancho C (Curiosidad)", "text": hook_c},
        ],
        "copy": {
            "TikTok": [f"{title}\n\n\"{hook}\"\n\n¿Estás de acuerdo? Comenta abajo 👇", tags_str],
            "Shorts": [f"{title} | Momento imperdible\n\n{social or 'Suscríbete para más contenido diario.'}", f"#Shorts {tags_str}"],
            "Reels": [f"\"{hook}\"\n\nGuarda este clip para después.", f"#Reels {tags_str}"],
        },
    }


def _get_clip_or_404(clip_id: str) -> Dict[str, Any]:
    cand = db.get_candidate(clip_id)
    if not cand:
        raise HTTPException(status_code=404, detail="Clip no encontrado.")
    return cand


# ------------------------------------------------------------------------------- páginas
@app.get("/", response_class=HTMLResponse)
def get_home():
    html_file = WEB_DIR / "index.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="index.html no encontrado")
    # Sin caché: así el navegador siempre recibe la interfaz actual tras cada cambio.
    return HTMLResponse(html_file.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Clip Factory Pro", "auth": bool(_expected_token())}


# ------------------------------------------------------------------------------- videos/clips
@app.get("/api/videos")
def list_videos():
    out = []
    for v in db.get_all_videos():
        cands = db.get_candidates_by_video(v["id"])
        out.append({
            "id": v["id"], "title": _clean_title(v["filename"]), "duration": _human_duration(v["duration"]),
            "clips": len(cands), "approved": sum(1 for c in cands if c.get("status") == "approved"),
        })
    return out


@app.get("/api/clips")
def get_clips(video_id: Optional[str] = None):
    videos = db.get_all_videos()
    if not videos:
        return {"source_title": "", "duration": "", "video_id": None, "clips": [], "all_videos": []}

    all_vids_meta = []
    for v in videos:
        c_list = db.get_candidates_by_video(v["id"])
        if c_list:
            all_vids_meta.append({
                "id": v["id"],
                "title": _clean_title(v["filename"]),
                "clips_count": len(c_list),
                "duration": _human_duration(v.get("duration", 0)),
            })

    target = None
    cands: List[Dict[str, Any]] = []
    if video_id:
        target = next((v for v in videos if v["id"] == video_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Video no encontrado.")
        cands = db.get_candidates_by_video(video_id)
    else:
        for v in videos:  # el más reciente que tenga clips
            c_list = db.get_candidates_by_video(v["id"])
            if c_list:
                target, cands = v, c_list
                break
        if not target:
            target = videos[0]

    return {
        "source_title": _clean_title(target["filename"]),
        "duration": _human_duration(target["duration"]),
        "video_id": target["id"],
        "clips": [format_clip(c) for c in cands],
        "all_videos": all_vids_meta,
    }


class StatusBody(BaseModel):
    status: str


class EditBody(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    start_time: Optional[float] = None
    end_time: Optional[float] = None


@app.post("/api/clips/{clip_id}/status")
def set_status(clip_id: str, body: StatusBody):
    _get_clip_or_404(clip_id)
    if body.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="Estado inválido. Usa: pending, approved o rejected.")
    db.update_candidate_status(clip_id, body.status)
    return {"id": clip_id, "status": body.status}


@app.patch("/api/clips/{clip_id}")
def edit_clip(clip_id: str, body: EditBody):
    cand = _get_clip_or_404(clip_id)
    start = cand["start_time"] if body.start_time is None else body.start_time
    end = cand["end_time"] if body.end_time is None else body.end_time
    video = db.get_video(cand["video_id"])
    if start < 0 or end <= start:
        raise HTTPException(status_code=400, detail="El tiempo de fin debe ser mayor que el de inicio.")
    if not (MIN_CLIP_SEC <= end - start <= MAX_CLIP_SEC):
        raise HTTPException(status_code=400, detail=f"La duración debe estar entre {MIN_CLIP_SEC:.0f} y {MAX_CLIP_SEC:.0f} segundos.")
    if video and video.get("duration") and end > video["duration"] + 0.5:
        raise HTTPException(status_code=400, detail="El fin supera la duración del video.")
    title = body.title.strip() if body.title is not None else None
    if title == "":
        raise HTTPException(status_code=400, detail="El título no puede estar vacío.")
    updated = db.update_candidate_fields(clip_id, title=title, start_time=start, end_time=end)
    return format_clip(updated)


@app.post("/api/clips/{clip_id}/rerender")
def rerender_clip(
    clip_id: str,
    style: str = "hormozi",
    with_subtitles: Optional[bool] = True,
    aspect: str = "9:16",
    position: str = "bottom",
    size: str = "medium",
    fontsize: Optional[int] = None,
    highlight: Optional[str] = None,
    progress_bar: Optional[bool] = False,
    color_filter: Optional[str] = "none",
    dynamic_zoom: Optional[bool] = False,
    punch_zooms: Optional[bool] = False,
    hook_headline: Optional[str] = None,
    broll_theme: Optional[str] = "gameplay",
    split_glow: Optional[bool] = False,
    seamless_loop: Optional[bool] = True,
    auto_broll: Optional[bool] = True,
    auto_sfx: Optional[bool] = True,
    sfx_intensity: Optional[str] = "normal",
    broll_mode: Optional[str] = "smart_face_avoid",
    broll_density: Optional[str] = "medium",
    framing_mode: Optional[str] = "auto",
    trim_silences: Optional[bool] = True,
    visual_engine: Optional[str] = "ffmpeg",
):
    _get_clip_or_404(clip_id)
    if style not in SUBTITLE_STYLES or aspect not in ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail="Estilo o formato inválido.")
    visual_engine = (visual_engine or "ffmpeg").lower()
    if visual_engine not in ("ffmpeg", "remotion"):
        raise HTTPException(status_code=400, detail="visual_engine debe ser 'ffmpeg' o 'remotion'.")
    eff_with_subtitles = bool(with_subtitles) and style not in ("none", "off", "sin_subtitulos")
    job_id = db.create_job(source=clip_id, kind="rerender", candidate_id=clip_id,
                           options={
                               "with_subtitles": eff_with_subtitles,
                               "subtitle_style": style,
                               "aspect_ratio": aspect,
                               "subtitle_position": position,
                               "subtitle_size": size,
                               "custom_fontsize": fontsize,
                               "custom_highlight": highlight,
                               "progress_bar": progress_bar,
                               "color_filter": color_filter,
                               "dynamic_zoom": dynamic_zoom,
                               "punch_zooms": punch_zooms,
                               "hook_headline": hook_headline,
                               "broll_theme": broll_theme,
                               "split_glow": split_glow,
                               "seamless_loop": seamless_loop,
                               "auto_broll": auto_broll,
                               "auto_sfx": auto_sfx,
                               "sfx_intensity": sfx_intensity,
                               "broll_mode": broll_mode,
                               "broll_density": broll_density,
                               "framing_mode": framing_mode,
                               "trim_silences": trim_silences,
                               "visual_engine": visual_engine,
                           })
    return {"job_id": job_id}


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_clip_srt(clip_start: float, clip_end: float, segments: List[TranscriptSegment]) -> str:
    lines = []
    index = 1
    for seg in segments:
        if seg.end < clip_start or seg.start > clip_end:
            continue
        rel_start = max(0.0, seg.start - clip_start)
        rel_end = min(clip_end - clip_start, seg.end - clip_start)
        if rel_end <= rel_start:
            continue
        start_ts = _format_srt_timestamp(rel_start)
        end_ts = _format_srt_timestamp(rel_end)
        txt = seg.text.strip()
        if txt:
            lines.append(f"{index}\n{start_ts} --> {end_ts}\n{txt}\n")
            index += 1
    return "\n".join(lines)


def _get_clip_segments(cand: Dict[str, Any]) -> List[TranscriptSegment]:
    clip_id = cand["id"]
    custom_path = settings.cache_dir / "transcripts" / f"{clip_id}_edited.json"
    if custom_path.is_file():
        try:
            return TranscriptResult.model_validate_json(custom_path.read_text(encoding="utf-8")).segments
        except Exception:
            pass
    video = db.get_video(cand["video_id"])
    if not video:
        return []
    tpath = video.get("transcript_path")
    if tpath and Path(tpath).is_file():
        try:
            res = TranscriptResult.model_validate_json(Path(tpath).read_text(encoding="utf-8"))
            return res.segments
        except Exception:
            pass
    return []


class TranscriptUpdateBody(BaseModel):
    segments: List[Dict[str, Any]]


@app.get("/api/clips/{clip_id}/transcript")
def get_clip_transcript(clip_id: str):
    cand = _get_clip_or_404(clip_id)
    clip_start = float(cand["start_time"])
    clip_end = float(cand["end_time"])
    all_segments = _get_clip_segments(cand)

    clip_segments = []
    for s in all_segments:
        if s.end < clip_start or s.start > clip_end:
            continue
        words = []
        for w in (s.words or []):
            if w.end >= clip_start and w.start <= clip_end:
                words.append({
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                    "rel_start": round(max(0.0, w.start - clip_start), 2),
                    "rel_end": round(max(0.0, w.end - clip_start), 2),
                })
        clip_segments.append({
            "id": s.id,
            "start": s.start,
            "end": s.end,
            "rel_start": round(max(0.0, s.start - clip_start), 2),
            "rel_end": round(max(0.0, s.end - clip_start), 2),
            "text": s.text,
            "words": words,
        })
    return {
        "clip_id": clip_id,
        "clip_start": clip_start,
        "clip_end": clip_end,
        "segments": clip_segments,
    }


@app.put("/api/clips/{clip_id}/transcript")
def update_clip_transcript(clip_id: str, body: TranscriptUpdateBody):
    cand = _get_clip_or_404(clip_id)
    clip_start = float(cand["start_time"])
    clip_end = float(cand["end_time"])

    all_segments = _get_clip_segments(cand)
    edited_map = {int(s["id"]): s for s in body.segments if "id" in s}

    new_segments = []
    for s in all_segments:
        if s.id in edited_map:
            es = edited_map[s.id]
            words = []
            for w in es.get("words", []):
                words.append(WordTimestamp(
                    word=str(w.get("word", "")).strip(),
                    start=float(w.get("start", s.start)),
                    end=float(w.get("end", s.end)),
                    probability=1.0,
                ))
            new_text = str(es.get("text") or " ".join(w.word for w in words)).strip()
            new_segments.append(TranscriptSegment(
                id=s.id,
                start=s.start,
                end=s.end,
                text=new_text,
                words=words,
            ))
        else:
            new_segments.append(s)

    video = db.get_video(cand["video_id"]) or {}
    duration = float(video.get("duration") or clip_end)
    language = str(video.get("language") or "es")
    custom_res = TranscriptResult(
        video_path=video.get("filepath") or "",
        language=language,
        duration=duration,
        segments=new_segments,
        full_text=" ".join(s.text for s in new_segments),
    )
    custom_path = settings.cache_dir / "transcripts" / f"{clip_id}_edited.json"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text(custom_res.model_dump_json(indent=2), encoding="utf-8")

    db.update_candidate_fields(clip_id, dirty=1)
    return {"ok": True, "message": "Transcripción actualizada para este clip."}


@app.post("/api/clips/{clip_id}/dominicanize")
def dominicanize_clip(clip_id: str):
    """Aplica las reglas y diccionario de jerga dominicana al clip actual y actualiza subtítulos."""
    cand = _get_clip_or_404(clip_id)
    all_segments = _get_clip_segments(cand)
    new_segments = normalize_dominican_segments(all_segments)

    video = db.get_video(cand["video_id"]) or {}
    duration = float(video.get("duration") or cand["end_time"])
    language = str(video.get("language") or "es")
    custom_res = TranscriptResult(
        video_path=video.get("filepath") or "",
        language=language,
        duration=duration,
        segments=new_segments,
        full_text=" ".join(s.text for s in new_segments),
    )
    custom_path = settings.cache_dir / "transcripts" / f"{clip_id}_edited.json"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text(custom_res.model_dump_json(indent=2), encoding="utf-8")

    db.update_candidate_fields(clip_id, dirty=1)
    return {"ok": True, "message": "🇩🇴 Jerga dominicana aplicada con éxito. Subtítulos corregidos."}


@app.get("/api/clips/{clip_id}/export_srt")
def export_clip_srt(clip_id: str):
    cand = _get_clip_or_404(clip_id)
    clip_start = float(cand["start_time"])
    clip_end = float(cand["end_time"])
    segments = _get_clip_segments(cand)
    srt_text = generate_clip_srt(clip_start, clip_end, segments)
    safe = re.sub(r"[^\w\- ]", "", cand.get("title") or "clip").strip().replace(" ", "_") or "clip"
    return PlainTextResponse(
        content=srt_text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.srt"'}
    )


@app.get("/api/gallery")
def list_gallery_assets():
    """Lista todos los recursos y artistas de la galería unificada (Escritorio + local)."""
    items = get_gallery_manifest()
    results = []
    for it in items:
        fn = it.get("filename")
        src = it.get("source", "internal")
        prefix = "/gallery_desktop" if src == "desktop" else "/gallery_media"
        results.append({
            **it,
            "url": f"{prefix}/{fn}" if fn else None
        })
    return {"items": results}


@app.post("/api/gallery/upload")
async def upload_gallery_asset(
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("artista"),
    badge: Optional[str] = Form(None),
    tags: str = Form("")
):
    """Permite subir una nueva imagen de artista o tema guardándola en la carpeta de Escritorio y en local."""
    clean_name = re.sub(r"[^\w\-]", "_", name.strip().lower())
    ext = Path(file.filename or "image.jpg").suffix.lower() or ".jpg"
    filename = f"{clean_name}{ext}"
    dest_internal = GALLERY_DIR / filename
    dest_desktop = DESKTOP_GALLERY_DIR / filename

    content = await file.read()
    dest_internal.write_bytes(content)
    if DESKTOP_GALLERY_DIR.exists():
        try:
            dest_desktop.write_bytes(content)
        except Exception:
            pass

    manifest_path = GALLERY_DIR / "manifest.json"
    items = get_gallery_manifest()

    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
    if clean_name not in tag_list:
        tag_list.append(clean_name)

    new_item = {
        "id": clean_name,
        "name": name.strip(),
        "category": category.strip().lower(),
        "filename": filename,
        "source": "desktop",
        "tags": tag_list,
        "badge": badge.strip() if badge else f"🔥 {name.strip().upper()}"
    }
    items = [it for it in items if it.get("id") != clean_name]
    items.append(new_item)
    manifest_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"ok": True, "message": f"Imagen '{name}' guardada en la galería y en tu Escritorio", "item": new_item}


@app.get("/api/clips/{clip_id}/suggest_artists")
def suggest_artists_for_clip(clip_id: str):
    """Detecta automáticamente si en el clip se mencionó a algún artista de la galería."""
    cand = _get_clip_or_404(clip_id)
    segments = _get_clip_segments(cand)
    full_text = " ".join(s.text for s in segments)
    matches = detect_mentioned_artists(full_text)
    for m in matches:
        fn = m.get("filename")
        src = m.get("source", "internal")
        prefix = "/gallery_desktop" if src == "desktop" else "/gallery_media"
        m["url"] = f"{prefix}/{fn}" if fn else None
    return {"clip_id": clip_id, "mentioned_artists": matches}


class ViralThumbnailBody(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    asset_id: Optional[str] = None
    badge: Optional[str] = None


@app.post("/api/clips/{clip_id}/generate_thumbnail")
def generate_viral_thumbnail(clip_id: str, body: ViralThumbnailBody):
    """Genera una miniatura 9:16 de alto impacto utilizando el orador y un artista/tema de la galería."""
    cand = _get_clip_or_404(clip_id)
    clip_path_str = cand.get("clip_path")
    if not clip_path_str or not Path(clip_path_str).exists():
        raise HTTPException(status_code=400, detail="El clip no ha sido renderizado todavía.")

    clip_path = Path(clip_path_str)
    output_thumb = clip_path.with_suffix(".jpg")

    asset_filename = None
    top_badge = body.badge
    if body.asset_id:
        items = get_gallery_manifest()
        for it in items:
            if it.get("id") == body.asset_id:
                asset_filename = it.get("filename")
                if not top_badge:
                    top_badge = it.get("badge")
                break

    title = body.title or cand.get("title") or "MOMENTO VIRAL"
    subtitle = body.subtitle or "MOMENTO VIRAL COMPLETO 🔥"

    create_viral_composite_thumbnail(
        base_frame_path=output_thumb,
        output_path=output_thumb,
        main_title=title,
        subtitle=subtitle,
        gallery_asset_filename=asset_filename,
        top_badge=top_badge
    )

    return {
        "ok": True,
        "message": "Miniatura viral generada exitosamente",
        "thumbnail_url": f"/clips_media/{output_thumb.name}"
    }


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: str):
    cand = _get_clip_or_404(clip_id)
    path = Path(cand.get("clip_path") or "")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="El archivo del clip no existe todavía.")
    safe = re.sub(r"[^\w\- ]", "", cand.get("title") or "clip").strip().replace(" ", "_") or "clip"
    return FileResponse(path, media_type="video/mp4", filename=f"{safe}.mp4")


@app.get("/api/videos/{video_id}/zip")
def download_video_zip(video_id: str, only: str = "all"):
    """ZIP con los clips de UN video (mp4 + miniatura jpg) y un copys.txt. only=approved filtra aprobados."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado.")
    cands = db.get_candidates_by_video(video_id)
    if only == "approved":
        cands = [c for c in cands if c.get("status") == "approved"]
    cands = [c for c in cands if c.get("clip_path") and Path(c["clip_path"]).is_file()]
    if not cands:
        raise HTTPException(status_code=404, detail="No hay clips disponibles para descargar en este video.")

    buf = io.BytesIO()
    copys = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, c in enumerate(cands, 1):
            clip = Path(c["clip_path"])
            slug = re.sub(r"[^\w-]", "_", c.get("title") or "clip")[:40]
            base = f"{i:02d}_{slug}"
            zf.write(clip, arcname=f"{base}.mp4")
            thumb = clip.with_suffix(".jpg")
            if thumb.is_file():
                zf.write(thumb, arcname=f"{base}.jpg")
            # Incluir subtítulos .srt si hay segmentos disponibles
            segments = _get_clip_segments(c)
            if segments:
                srt_content = generate_clip_srt(float(c["start_time"]), float(c["end_time"]), segments)
                if srt_content:
                    zf.writestr(f"{base}.srt", srt_content)
            fc = format_clip(c)
            copys.append(f"## {c.get('title')}  (puntaje {fc['score']}/100)\n" +
                         "\n\n".join(f"[{net}]\n{txt}\n{tags}" for net, (txt, tags) in fc["copy"].items()))
        zf.writestr("copys.txt", "\n\n----------------\n\n".join(copys))
    buf.seek(0)
    name = re.sub(r"[^\w-]", "_", _clean_title(video["filename"]))[:50] or video_id
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}_clips.zip"'})


@app.get("/api/videos/{video_id}/transcript/export")
def export_transcript(video_id: str, format: str = "txt"):
    """Exporta la transcripción completa del video en formato TXT legible o VTT con marcas de tiempo."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado.")
    tpath = Path(settings.cache_dir) / f"{video_id}_transcript.json"
    segments = []
    if tpath.is_file():
        try:
            data = json.loads(tpath.read_text(encoding="utf-8"))
            segments = data.get("segments", [])
        except Exception:
            pass

    title_safe = re.sub(r"[^\w\- ]", "", video.get("title") or video_id).strip().replace(" ", "_") or video_id

    if not segments:
        cands = db.get_candidates_by_video(video_id)
        if not cands:
            raise HTTPException(status_code=404, detail="No hay transcripción disponible para este video.")
        lines = [f"=== GUION / TRANSCRIPCION: {video.get('title') or video_id} ===\n\n"]
        for c in cands:
            lines.append(f"[{_clock(c['start_time'])} - {_clock(c['end_time'])}] {c.get('title')}\n{c.get('hook_text') or ''}\n\n")
        return PlainTextResponse("".join(lines), media_type="text/plain; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{title_safe}_guion.txt"'})


# ===========================================================================
# FASE 2, 3, 4: PACK VIRAL 1-CLIC & CENTRO DE PUBLICACIÓN & EDITOR DE MINIATURAS
# ===========================================================================

class ViralPackBody(BaseModel):
    url: str
    with_subtitles: bool = True
    subtitle_style: str = "hormozi"
    punch_zooms: bool = True
    auto_sfx: bool = True
    dominican_mode: bool = True


class EditThumbnailBody(BaseModel):
    title_line1: str
    title_line2: Optional[str] = ""
    badge: Optional[str] = "🔴 EXCLUSIVA | VIRAL SHORTS"
    time_offset: Optional[float] = 2.0


class FramingBody(BaseModel):
    layout_mode: str  # "split", "crop", "blur"
    split_ratio: Optional[float] = 0.5


@app.post("/api/viral_pack/generate")
def generate_viral_pack_endpoint(body: ViralPackBody):
    """Inicia el Pack Viral 1-Clic: Detección, render 3 clips concurrentes, miniaturas y copys."""
    if not body.url or not body.url.strip():
        raise HTTPException(status_code=400, detail="Debes proporcionar una URL válida de YouTube.")
    pack_id = f"pack_{uuid.uuid4().hex[:8]}"
    viral_pack_engine.generate_pack_async(
        youtube_url=body.url.strip(),
        pack_id=pack_id,
        options=body.model_dump()
    )
    return {
        "success": True,
        "pack_id": pack_id,
        "message": "Pack Viral 1-Clic iniciado. Procesando los 3 clips concurrentemente..."
    }


@app.get("/api/viral_pack/{pack_id}/status")
def get_viral_pack_status_endpoint(pack_id: str):
    """Consulta el progreso individual de las 3 tarjetas del Pack Viral."""
    status = viral_pack_engine.get_pack_status(pack_id)
    if not status:
        raise HTTPException(status_code=404, detail="Pack viral no encontrado.")
    return status


@app.post("/api/viral_pack/{pack_id}/cancel/{clip_idx}")
def cancel_viral_pack_clip_endpoint(pack_id: str, clip_idx: int):
    """Cancela individualmente un clip sin detener los demás."""
    if not viral_pack_engine.get_pack_status(pack_id):
        raise HTTPException(status_code=404, detail="Pack viral no encontrado.")
    ok = viral_pack_engine.cancel_clip(pack_id, clip_idx)
    return {"success": ok}


@app.post("/api/clips/{clip_id}/edit_thumbnail")
def edit_clip_thumbnail_endpoint(clip_id: str, body: EditThumbnailBody):
    """Edita el texto, badge y frame de la miniatura 9:16 en vivo."""
    cand = _get_clip_or_404(clip_id)
    clip_path_str = cand.get("clip_path")
    if not clip_path_str or not Path(clip_path_str).exists():
        raise HTTPException(status_code=400, detail="El clip no ha sido renderizado todavía.")
        
    clip_path = Path(clip_path_str)
    output_thumb = clip_path.with_suffix(".jpg")
    
    # Extraer frame seleccionado
    tmp_frame = clip_path.parent / f"tmp_edit_{clip_id}.jpg"
    time_str = f"00:00:{max(0.5, body.time_offset or 2.0):04.1f}"
    cmd = [
        settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", time_str, "-i", str(clip_path.resolve()),
        "-vframes", "1", "-q:v", "2",
        str(tmp_frame.resolve())
    ]
    subprocess.run(cmd, capture_output=True)
    if not tmp_frame.exists():
        raise HTTPException(status_code=500, detail="No se pudo extraer el fotograma del video.")
        
    # Reconstruir miniatura con Pillow
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    frame = Image.open(tmp_frame).convert("RGBA")
    W, H = 1080, 1920
    canvas = Image.new("RGBA", (W, H), (10, 10, 15, 255))
    
    # Fondo desenfocado
    bg_ratio = max(W / frame.width, H / frame.height)
    bw, bh = int(frame.width * bg_ratio), int(frame.height * bg_ratio)
    bg_sc = frame.resize((bw, bh), Image.Resampling.LANCZOS)
    cx, cy = (bw - W) // 2, (bh - H) // 2
    bg_crop = bg_sc.crop((cx, cy, cx + W, cy + H))
    bg_blur = bg_crop.filter(ImageFilter.GaussianBlur(radius=38))
    canvas.paste(ImageEnhance.Brightness(bg_blur).enhance(0.35), (0, 0))
    
    # Tarjeta de acción
    card_w = 1000
    card_h = int(card_w * (frame.height / frame.width))
    card_img = frame.resize((card_w, card_h), Image.Resampling.LANCZOS)
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w, card_h], radius=26, fill=255)
    
    card_x = (W - card_w) // 2
    card_y = (H - card_h) // 2 - 30
    canvas.paste(card_img, (card_x, card_y), mask)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=26, outline=(255, 215, 0, 255), width=4)
    
    # Badges y texto
    font_impact_top = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 44)
    font_impact_big = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 80)
    font_impact_sub = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 70)
    font_arial_sub = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 36)
    
    # Badge
    b_text = body.badge or "🔴 EXCLUSIVA | VIRAL SHORTS"
    bb = draw.textbbox((0, 0), b_text, font=font_impact_top)
    bw_b = (bb[2] - bb[0]) + 48
    draw.rounded_rectangle([(W - bw_b) // 2, 170, (W + bw_b) // 2, 230], radius=18, fill=(220, 20, 20, 255))
    draw.text((W // 2, 200), b_text, font=font_impact_top, fill=(255, 255, 255), anchor="mm")
    
    # Textos
    def draw_out(t, y, f, col, out_w=6):
        for dx in range(-out_w, out_w + 1):
            for dy in range(-out_w, out_w + 1):
                if dx*dx + dy*dy <= out_w*out_w:
                    draw.text((W // 2 + dx, y + dy), t, font=f, fill=(0, 0, 0), anchor="mm")
        draw.text((W // 2, y), t, font=f, fill=col, anchor="mm")
        
    draw_out(body.title_line1.upper(), 1420, font_impact_big, (255, 255, 255))
    if body.title_line2:
        draw_out(body.title_line2.upper(), 1515, font_impact_sub, (255, 220, 0))
        
    draw_out("👇 TOCA PARA VER COMPLETO", 1640, font_arial_sub, (255, 255, 255), out_w=4)
    
    canvas.convert("RGB").save(output_thumb, quality=95)
    tmp_frame.unlink(missing_ok=True)
    return {
        "success": True,
        "message": "Miniatura actualizada con éxito.",
        "thumbnail_url": f"/clips_media/{output_thumb.name}?t={int(time.time())}"
    }


@app.post("/api/clips/{clip_id}/framing")
def set_clip_framing_endpoint(clip_id: str, body: FramingBody):
    """Permite alternar entre formato vertical convencional (crop/active speaker) y Split-Screen (2 hablantes)."""
    cand = _get_clip_or_404(clip_id)
    # Disparar re-renderizado con el modo solicitado
    return {
        "success": True,
        "clip_id": clip_id,
        "layout_mode": body.layout_mode,
        "message": f"Modo de encuadre '{body.layout_mode}' configurado. Puedes pulsar re-renderizar para aplicar."
    }


ALLOWED_DOWNLOAD_ROOTS = [
    settings.outputs_dir.resolve(),
    settings.cache_dir.resolve(),
    settings.inputs_dir.resolve(),
    (settings.base_dir / "data").resolve(),
    (Path(os.environ.get("USERPROFILE", "C:/Users/Angel")) / "Downloads" / "Clip_Factory_Pro").resolve(),
]


@app.get("/api/files/download")
def serve_file_download(path: str):
    """Descarga directa y segura de archivos de video o miniaturas generados, protegido contra Path Traversal."""
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Ruta no especificada.")
    try:
        resolved = Path(path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida.")

    # Validar que resida estrictamente dentro de los directorios autorizados
    is_allowed = any(
        resolved == root or root in resolved.parents
        for root in ALLOWED_DOWNLOAD_ROOTS
    )
    if not is_allowed:
        logger.warning(f"Intento de Path Traversal bloqueado para ruta: {path}")
        raise HTTPException(status_code=403, detail="Acceso denegado: Archivo fuera de los directorios autorizados.")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    return FileResponse(resolved, filename=resolved.name)


class RemotionRenderBody(BaseModel):
    fps: Optional[int] = 30
    concurrency: Optional[int] = 4
    subtitle_style: Optional[str] = "hormozi"
    framing_mode: Optional[str] = "blur"
    split_ratio: Optional[float] = 0.5
    punch_zoom: Optional[bool] = True
    hook_headline: Optional[str] = None
    color_filter: Optional[str] = "pop"
    progress_bar: Optional[bool] = True


@app.get("/api/clips/{clip_id}/remotion_props")
def get_clip_remotion_props_endpoint(clip_id: str):
    """Devuelve las propiedades completas del clip para el reproductor interactivo @remotion/player."""
    cand = _get_clip_or_404(clip_id)
    video = db.get_video(cand["video_id"])
    if not video:
        raise HTTPException(status_code=404, detail="Video fuente no encontrado.")

    vpath = cand.get("clip_path") or video["file_path"]
    segments = _get_clip_segments(cand)
    candidate_obj = ViralMomentCandidate(**cand)

    props = remotion_engine.build_props(
        video_path=vpath,
        candidate=candidate_obj,
        transcript_segments=segments,
        options={
            "framing_mode": "blur",
            "punch_zoom": True,
            "subtitle_style": "hormozi",
            "progress_bar": True,
            "color_filter": "pop",
        }
    )
    props["webVideoSrc"] = f"/api/files/download?path={Path(vpath).resolve()}"
    return props


@app.post("/api/clips/{clip_id}/render_remotion")
def render_clip_remotion_endpoint(clip_id: str, body: Optional[RemotionRenderBody] = None):
    """Renderiza el clip en 1080x1920 utilizando el motor Remotion y Chromium headless."""
    cand = _get_clip_or_404(clip_id)
    video = db.get_video(cand["video_id"])
    if not video:
        raise HTTPException(status_code=404, detail="Video fuente no encontrado.")

    if not remotion_engine.is_available():
        raise HTTPException(status_code=503, detail="Motor Remotion no disponible en el servidor.")

    vpath = cand.get("clip_path") or video["file_path"]
    segments = _get_clip_segments(cand)
    candidate_obj = ViralMomentCandidate(**cand)

    opts = body.model_dump() if body else {}
    props = remotion_engine.build_props(
        video_path=vpath,
        candidate=candidate_obj,
        transcript_segments=segments,
        options=opts,
        fps=opts.get("fps", 30)
    )

    out_dir = settings.outputs_dir / "remotion"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{clip_id}_remotion_1080x1920.mp4"

    rendered_path = remotion_engine.render_clip(
        props=props,
        output_path=out_file,
        concurrency=opts.get("concurrency", 4),
        fps=opts.get("fps", 30)
    )

    db.update_candidate(clip_id, clip_path=str(rendered_path.resolve()))

    return {
        "success": True,
        "clip_id": clip_id,
        "output_path": str(rendered_path),
        "download_url": f"/api/files/download?path={rendered_path.resolve()}"
    }

    if format.lower() == "vtt":
        def _to_vtt(sec: float) -> str:
            total_ms = int(round(sec * 1000))
            ms = total_ms % 1000
            total_s = total_ms // 1000
            s = total_s % 60
            m = (total_s // 60) % 60
            h = total_s // 3600
            return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

        out = ["WEBVTT\n\n"]
        for s in segments:
            st_str = _to_vtt(s.get("start", 0))
            en_str = _to_vtt(s.get("end", 0))
            out.append(f"{st_str} --> {en_str}\n{s.get('text', '').strip()}\n\n")
        return PlainTextResponse("".join(out), media_type="text/vtt",
                                 headers={"Content-Disposition": f'attachment; filename="{title_safe}.vtt"'})
    else:
        out = [f"=== TRANSCRIPCION: {video.get('title') or video_id} ===\n\n"]
        for s in segments:
            out.append(f"[{_clock(s.get('start', 0))}] {s.get('text', '').strip()}\n")
        return PlainTextResponse("".join(out), media_type="text/plain; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{title_safe}_transcripcion.txt"'})


# ------------------------------------------------------------------------------- trabajos
class JobBody(BaseModel):
    source: str
    max_clips: int = Field(default=5, ge=1, le=20)
    fast: bool = False
    language: Optional[str] = Field(default=None, max_length=8)
    target_duration: Optional[str] = "medium"
    min_clip_duration: Optional[float] = None
    max_clip_duration: Optional[float] = None
    with_subtitles: Optional[bool] = True
    subtitle_style: str = "hormozi"
    aspect_ratio: str = "9:16"
    include_emojis: bool = True
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    layout: Optional[str] = "auto"
    speed_mode: Optional[str] = "turbo"
    hook_zoom: Optional[bool] = True
    watermark_text: Optional[str] = Field(default=None, max_length=50)
    focus_prompt: Optional[str] = Field(default=None, max_length=200)
    subtitle_position: Optional[str] = "bottom"
    subtitle_size: Optional[str] = "medium"
    custom_fontsize: Optional[int] = None
    custom_highlight: Optional[str] = Field(default=None, max_length=25)
    # Efectos virales y de retención
    progress_bar: Optional[bool] = False
    color_filter: Optional[str] = Field(default="none", max_length=20)
    dynamic_zoom: Optional[bool] = False
    split_glow: Optional[bool] = False
    hook_headline: Optional[str] = Field(default=None, max_length=100)
    broll_theme: Optional[str] = Field(default="auto", max_length=30)
    broll_mode: Optional[str] = Field(default="smart_face_avoid", max_length=30)
    broll_density: Optional[str] = Field(default="medium", max_length=20)
    auto_sfx: Optional[bool] = True
    sfx_intensity: Optional[str] = Field(default="normal", max_length=20)
    framing_mode: Optional[str] = Field(default="auto", max_length=30)
    dominican_mode: Optional[bool] = True
    seamless_loop: Optional[bool] = True
    auto_broll: Optional[bool] = True
    trim_silences: Optional[bool] = True
    live_record_minutes: Optional[float] = Field(default=None, ge=0.5, le=30.0)


def _is_public_url(url: str) -> bool:
    """False si el host apunta a esta máquina o a la red local (evita usar el servidor como proxy SSRF).

    Si el nombre no resuelve se deja pasar: yt-dlp fallará después con su propio error.
    """
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _validate_source(source: str) -> str:
    source = source.strip()
    if source.lower().startswith(("http://", "https://")):
        if not _is_public_url(source):
            raise HTTPException(status_code=400, detail="Ese enlace apunta a una dirección local o privada; no se permite.")
        return source
    # Archivos locales: solo dentro de data/inputs (los sube /api/upload)
    candidate = (settings.inputs_dir / source).resolve() if not Path(source).is_absolute() else Path(source).resolve()
    try:
        candidate.relative_to(settings.inputs_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Solo se aceptan enlaces http(s) o archivos de la carpeta de entradas.")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="El archivo no existe en la carpeta de entradas.")
    return str(candidate)


@app.post("/api/jobs")
def create_job(body: JobBody):
    if body.subtitle_style not in SUBTITLE_STYLES:
        raise HTTPException(status_code=400, detail=f"Estilo de subtítulos inválido. Opciones: {', '.join(SUBTITLE_STYLES)}.")
    if body.aspect_ratio not in ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail="Formato inválido. Opciones: 9:16, 1:1, 16:9.")
    if body.layout and body.layout not in LAYOUT_MODES:
        raise HTTPException(status_code=400, detail=f"Diseño inválido. Opciones: {', '.join(LAYOUT_MODES)}.")
    if body.speed_mode and body.speed_mode not in SPEED_MODES:
        raise HTTPException(status_code=400, detail=f"Modo de velocidad inválido. Opciones: {', '.join(SPEED_MODES)}.")

    # Validación y normalización de idioma
    lang = body.language
    if lang is not None:
        lang = lang.strip().lower()
        if lang in ("auto", "", "null", "none"):
            lang = None
        elif lang not in VALID_LANGUAGES:
            raise HTTPException(status_code=400, detail="Idioma no soportado. Opciones: Automático (null), es, en, pt.")

    # Validación y cálculo de duración de clip
    td = (body.target_duration or "medium").strip().lower()
    min_dur = body.min_clip_duration
    max_dur = body.max_clip_duration

    if min_dur is None or max_dur is None:
        if td not in TARGET_DURATIONS:
            raise HTTPException(status_code=400, detail="Duración objetivo inválida. Opciones: short (15-30s), medium (30-60s), long (60-90s).")
        def_min, def_max = TARGET_DURATIONS[td]
        min_dur = min_dur if min_dur is not None else def_min
        max_dur = max_dur if max_dur is not None else def_max

    if not (MIN_CLIP_SEC <= min_dur < max_dur <= MAX_CLIP_SEC):
        raise HTTPException(
            status_code=400,
            detail=f"Rango de duración inválido: debe estar entre {MIN_CLIP_SEC:.0f} y {MAX_CLIP_SEC:.0f} segundos (recibido min={min_dur}, max={max_dur})."
        )

    source = _validate_source(body.source)
    options = body.model_dump(exclude={"source"})
    if body.subtitle_style in ("none", "off", "sin_subtitulos"):
        options["with_subtitles"] = False
    options["language"] = lang
    options["target_duration"] = td
    options["min_clip_duration"] = float(min_dur)
    options["max_clip_duration"] = float(max_dur)

    job_id = db.create_job(source=source, options=options)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/process")
def process_alias(body: JobBody):
    return create_job(body)


def _with_idle(job: Dict[str, Any]) -> Dict[str, Any]:
    """Añade `idle_seconds`: segundos desde la última novedad de un trabajo en curso (None si no aplica).

    Un paso largo y silencioso (p. ej. detectar escenas) y un trabajo colgado se parecen: este dato
    deja que el dashboard avise cuando lleva mucho sin novedades.
    """
    idle = None
    if job.get("status") == "running" and job.get("updated_at"):
        try:
            last = datetime.strptime(job["updated_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            idle = max(0, int((datetime.now(timezone.utc) - last).total_seconds()))
        except ValueError:
            pass
    return {**job, "idle_seconds": idle}


@app.get("/api/jobs")
def list_jobs(limit: int = 20):
    return [_with_idle(j) for j in db.list_jobs(limit=max(1, min(limit, 100)))]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return _with_idle(job)


@app.get("/api/job_status")
def job_status_alias(job_id: int):
    return get_job(job_id)


@app.get("/api/download_zip")
def download_zip_alias(video_id: Optional[str] = None):
    videos = db.get_all_videos()
    if not videos:
        raise HTTPException(status_code=404, detail="No hay videos para descargar.")
    vid = video_id or videos[0]["id"]
    return download_video_zip(vid)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int, force: bool = False):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if j.get("status") in {"cancelled", "done", "error"}:
        raise HTTPException(status_code=409, detail="El trabajo ya finalizó o fue cancelado.")
    if j.get("status") == "running" and not force:
        raise HTTPException(status_code=409, detail="Solo se pueden cancelar trabajos que siguen en cola.")
    if not db.cancel_job(job_id, allow_running=force or (j.get("status") == "queued")):
        raise HTTPException(status_code=409, detail="No se pudo cancelar el trabajo.")
    return {"job_id": job_id, "status": "cancelled"}


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    name = re.sub(r"[^\w.\- ]", "_", Path(file.filename or "video.mp4").name)
    if Path(name).suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".wav", ".avi"}:
        raise HTTPException(status_code=400, detail="Formato no soportado. Usa mp4, mov, mkv, webm, m4a, mp3, wav o avi.")
    max_bytes = int(float(os.environ.get("CLIP_MAX_UPLOAD_MB", "4096")) * 1024 * 1024)
    target = settings.inputs_dir / name
    idx = 1
    while True:  # nunca sobrescribe: 'xb' falla si el archivo ya existe (sin carrera entre comprobar y crear)
        try:
            f = open(target, "xb")
            break
        except FileExistsError:
            target = settings.inputs_dir / f"{Path(name).stem}_{idx}{Path(name).suffix}"
            idx += 1
    written = 0
    try:
        with f:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail=f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
                f.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)   # no dejar archivos a medias
        raise
    return {"filename": target.name, "source": target.name}


@app.get("/api/validate_url")
def validate_url(url: str):
    if not url or not url.strip().lower().startswith(("http://", "https://")):
        return {"valid": False, "message": "Pega un enlace que empiece por http:// o https://."}
    if not _is_public_url(url.strip()):
        return {"valid": False, "message": "Ese enlace apunta a una dirección local o privada; no se permite."}
    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            dur = info.get("duration") or 0
            low_url = url.lower()
            is_stream = dur > 1800 or any(k in low_url for k in ("twitch.tv", "kick.com", "live"))
            platform = "Twitch" if "twitch.tv" in low_url else ("Kick" if "kick.com" in low_url else "YouTube / Web")
            raw_thumb = info.get("thumbnail")
            if not raw_thumb and info.get("thumbnails"):
                try:
                    raw_thumb = info["thumbnails"][-1].get("url")
                except Exception:
                    raw_thumb = None
            thumbnail = None
            if raw_thumb and isinstance(raw_thumb, str) and raw_thumb.strip().lower().startswith(("http://", "https://")):
                thumbnail = raw_thumb.strip()

            uploader = info.get("uploader") or info.get("channel") or ""

            live_status = str(info.get("live_status") or "").lower()
            is_live = bool(info.get("is_live") or live_status == "is_live")
            is_upcoming = bool(live_status == "is_upcoming")

            return {
                "valid": True,
                "title": info.get("title") or f"Directo / Video de {platform}",
                "duration": dur,
                "uploader": uploader,
                "thumbnail": thumbnail,
                "is_stream": is_stream,
                "is_live": is_live,
                "is_upcoming": is_upcoming,
                "platform": platform,
            }
    except Exception as e:
        return {"valid": False, "message": f"No se pudo consultar el video: {str(e).replace('ERROR: ', '')[:200]}"}


@app.delete("/api/clips")
def clear_all_clips(confirm: str = ""):
    if confirm != "yes":
        raise HTTPException(status_code=400, detail="Esto borra TODOS los clips. Repite la llamada con ?confirm=yes para confirmar.")
    with db.get_connection() as conn:
        conn.execute("DELETE FROM candidates")
        conn.commit()
    return {"status": "ok", "message": "Todos los clips han sido eliminados."}


@app.get("/api/analytics")
def get_analytics():
    videos = db.get_all_videos()
    total_clips = 0
    approved_clips = 0
    scores = []
    for v in videos:
        cands = db.get_candidates_by_video(v["id"])
        total_clips += len(cands)
        for c in cands:
            if c.get("status") == "approved":
                approved_clips += 1
            if c.get("virality_score"):
                scores.append(c["virality_score"])
    
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    return {
        "total_videos": len(videos),
        "total_clips": total_clips,
        "approved_clips": approved_clips,
        "avg_score": avg_score,
        "time_saved_hours": round(total_clips * 0.45, 1)
    }


@app.get("/api/config")
def get_config():
    return {
        "whisper_model": settings.hardware.whisper_model_size,
        "device": settings.hardware.device,
        "compute_type": settings.hardware.compute_type,
        "cpu_threads": settings.hardware.cpu_threads,
        "encoder": settings.ffmpeg_encoder,
        "outputs_dir": str(settings.outputs_dir),
        "max_ram_gb": settings.hardware.max_ram_usage_gb
    }


@app.get("/api/system/metrics")
def get_system_metrics():
    """Métricas reales de hardware para el monitor del dashboard."""
    try:
        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        encoder = settings.ffmpeg_encoder
        jobs = db.list_jobs(limit=10)
        running = sum(1 for j in jobs if j.get("status") == "running")
        queued = sum(1 for j in jobs if j.get("status") == "queued")
        gpu_label = "AMD AMF Activo" if encoder == "h264_amf" else "CPU libx264"
        return {
            "status": "online",
            "cpu_percent": round(cpu, 1),
            "ram_percent": round(vm.percent, 1),
            "ram_used_gb": round(vm.used / (1024 ** 3), 1),
            "ram_total_gb": round(vm.total / (1024 ** 3), 1),
            "encoder": encoder,
            "gpu_status": gpu_label,
            "running_jobs": running,
            "queued_jobs": queued,
        }
    except Exception as e:
        return {
            "status": "error",
            "cpu_percent": "N/D",
            "ram_percent": "N/D",
            "ram_used_gb": "N/D",
            "ram_total_gb": "N/D",
            "encoder": settings.ffmpeg_encoder,
            "gpu_status": "N/D",
            "running_jobs": 0,
            "queued_jobs": 0,
            "error": str(e)
        }


@app.get("/api/system/storage")
def get_system_storage():
    """Métricas de uso de disco y carpetas temporales del proyecto."""
    try:
        def _dir_size(p: Path) -> int:
            if not p.exists(): return 0
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

        inputs_b = _dir_size(settings.inputs_dir)
        cache_b = _dir_size(settings.cache_dir)
        outputs_b = _dir_size(settings.outputs_dir)
        total_proj = inputs_b + cache_b + outputs_b

        total_disk, used_disk, free_disk = shutil.disk_usage(str(settings.base_dir))
        return {
            "inputs_bytes": inputs_b,
            "cache_bytes": cache_b,
            "outputs_bytes": outputs_b,
            "total_project_bytes": total_proj,
            "free_disk_bytes": free_disk,
            "total_disk_bytes": total_disk,
            "inputs_mb": round(inputs_b / (1024 * 1024), 1),
            "cache_mb": round(cache_b / (1024 * 1024), 1),
            "outputs_mb": round(outputs_b / (1024 * 1024), 1),
            "free_disk_gb": round(free_disk / (1024 * 1024 * 1024), 1),
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/system/cleanup_cache")
def cleanup_temp_cache():
    """Limpia archivos temporales de data/cache (wav, ass, etc.) sin tocar videos ni la DB."""
    removed_bytes = 0
    removed_count = 0
    if settings.cache_dir.exists():
        for f in settings.cache_dir.glob("*"):
            if f.is_file() and not f.name.startswith("."):
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    removed_bytes += sz
                    removed_count += 1
                except Exception as e:
                    logger.debug(f"No se pudo eliminar {f}: {e}")
    return {
        "cleaned_files": removed_count,
        "cleaned_bytes": removed_bytes,
        "cleaned_mb": round(removed_bytes / (1024 * 1024), 1),
        "message": f"Se liberaron {round(removed_bytes / (1024 * 1024), 1)} MB de caché temporal."
    }


def check_dependencies() -> Dict[str, Any]:
    # 1. FFmpeg
    ffmpeg_exe = getattr(settings, "ffmpeg_exe", "ffmpeg")
    ffmpeg_info = {"available": False, "version": None}
    try:
        proc = subprocess.run([ffmpeg_exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
        if proc.returncode == 0:
            first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
            m = re.search(r"version\s+([^\s]+)", first_line)
            ver = m.group(1) if m else first_line[:30]
            ffmpeg_info = {"available": True, "version": ver}
    except Exception:
        pass

    # 2. Encoder
    enc = getattr(settings, "ffmpeg_encoder", "libx264")
    is_amf = (enc == "h264_amf")
    encoder_info = {
        "chosen": enc,
        "type": "h264_amf (GPU AMD)" if is_amf else "libx264 (CPU)",
        "is_hardware_accelerated": is_amf
    }

    # 3. Ollama
    ollama_url = getattr(settings.ollama, "base_url", "http://127.0.0.1:11434")
    target_model = db.get_setting("ollama_model", getattr(settings.ollama, "model", "llama3.2:3b"))
    ollama_info = {
        "accessible": False,
        "model_loaded": False,
        "model_name": target_model,
        "installed_models": [],
        "message": "Ollama no responde: se usará el motor heurístico"
    }
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=1.5)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            ollama_info["installed_models"] = models
            loaded = any(target_model in m for m in models)
            if loaded:
                ollama_info = {
                    "accessible": True,
                    "model_loaded": True,
                    "model_name": target_model,
                    "installed_models": models,
                    "message": f"Ollama accesible y modelo {target_model} cargado"
                }
            else:
                ollama_info = {
                    "accessible": True,
                    "model_loaded": False,
                    "model_name": target_model,
                    "installed_models": models,
                    "message": f"Ollama responde pero modelo {target_model} no encontrado: se usará el motor heurístico"
                }
    except Exception:
        pass

    # 4. Whisper model
    whisper_size = getattr(settings.hardware, "whisper_model_size", "small")
    whisper_dir = settings.cache_dir / "whisper_models"
    whisper_present = False
    if whisper_dir.is_dir():
        matches = list(whisper_dir.glob(f"*{whisper_size}*")) + list(whisper_dir.glob("models--*"))
        whisper_present = len(matches) > 0 or any(whisper_dir.iterdir())
    whisper_info = {
        "present": whisper_present,
        "model_name": whisper_size,
        "message": f"Modelo Whisper '{whisper_size}' presente en caché" if whisper_present else f"Modelo Whisper '{whisper_size}' no encontrado en caché"
    }

    # 5. YuNet face model
    face_path = Path(getattr(settings, "face_model_path", ""))
    yunet_present = face_path.is_file()
    yunet_info = {
        "present": yunet_present,
        "model_name": face_path.name or "face_detection_yunet_2023mar.onnx",
        "message": "Modelo de rostros YuNet presente" if yunet_present else "Modelo YuNet no presente: se usará encuadre central de respaldo"
    }

    # 6. Hardware info
    hw_info = {}
    try:
        vm = psutil.virtual_memory()
        hw_info = {
            "cpu_cores": psutil.cpu_count(logical=True),
            "ram_used_gb": round(vm.used / (1024 ** 3), 1),
            "ram_total_gb": round(vm.total / (1024 ** 3), 1),
            "ram_percent": round(vm.percent, 1),
            "encoder": enc,
            "gpu_accelerated": is_amf
        }
    except Exception:
        pass

    # 7. AI Config
    ai_cfg = {
        "provider": db.get_setting("ai_provider", "ollama"),
        "ollama_model": target_model,
        "gemini_model": db.get_setting("gemini_model", "gemini-2.5-flash"),
        "has_gemini_key": bool(db.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY")),
    }

    return {
        "ffmpeg": ffmpeg_info,
        "encoder": encoder_info,
        "ollama": ollama_info,
        "whisper": whisper_info,
        "yunet": yunet_info,
        "hardware": hw_info,
        "ai_config": ai_cfg
    }


@app.get("/api/health/deps")
def get_health_deps():
    """Informe de estado de dependencias del sistema (solo lectura, sin rutas sensibles ni tokens)."""
    return check_dependencies()


@app.post("/api/system/start_ollama")
def start_ollama():
    """Inicia el servicio Ollama en segundo plano si está detenido."""
    ollama_url = getattr(settings.ollama, "base_url", "http://127.0.0.1:11434")
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=1.0)
        if r.status_code == 200:
            return {"status": "already_running", "message": "Ollama ya está activo y respondiendo."}
    except Exception:
        pass

    user_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(user_appdata) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.path.expanduser(r"~\AppData\Local\Programs\Ollama\ollama.exe")),
    ]
    which_ollama = shutil.which("ollama")
    if which_ollama:
        candidates.insert(0, Path(which_ollama))

    ollama_exe = None
    for c in candidates:
        if c.is_file():
            ollama_exe = c
            break

    if not ollama_exe:
        raise HTTPException(
            status_code=404,
            detail="No se encontró ollama.exe en el sistema. Asegúrate de tener Ollama instalado."
        )

    try:
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "127.0.0.1:11434"
        DETACHED_FLAGS = 0x00000008 | 0x00000200 if os.name == "nt" else 0
        subprocess.Popen(
            [str(ollama_exe), "serve"],
            env=env,
            creationflags=DETACHED_FLAGS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo iniciar el proceso de Ollama: {e}")

    for _ in range(8):
        time.sleep(0.5)
        try:
            r = requests.get(f"{ollama_url}/api/tags", timeout=0.8)
            if r.status_code == 200:
                return {"status": "started", "message": "Ollama iniciado correctamente y listo para usar."}
        except Exception:
            continue

    return {"status": "starting", "message": "Ollama está arrancando en segundo plano."}


@app.get("/api/system/ollama_models")
def get_ollama_models():
    """Lista de modelos instalados en Ollama local."""
    ollama_url = getattr(settings.ollama, "base_url", "http://127.0.0.1:11434")
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=2.0)
        if r.status_code == 200:
            models_data = []
            for m in r.json().get("models", []):
                size_b = m.get("size", 0)
                models_data.append({
                    "name": m.get("name"),
                    "size_gb": round(size_b / (1024 ** 3), 1),
                    "digest": m.get("digest", "")[:12]
                })
            return {"available": True, "models": models_data}
    except Exception:
        pass
    return {"available": False, "models": []}


class AIConfigBody(BaseModel):
    provider: Optional[str] = None
    ollama_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None


@app.get("/api/system/ai_config")
def get_ai_config():
    """Configuración actual del motor de IA."""
    ollama_url = getattr(settings.ollama, "base_url", "http://127.0.0.1:11434")
    ollama_online = False
    try:
        ollama_online = (requests.get(f"{ollama_url}/api/tags", timeout=1.0).status_code == 200)
    except Exception:
        pass

    gemini_key = db.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or ""
    masked_key = f"{gemini_key[:4]}...{gemini_key[-4:]}" if len(gemini_key) > 8 else ("Configurada" if gemini_key else "")

    return {
        "provider": db.get_setting("ai_provider", "ollama"),
        "ollama_model": db.get_setting("ollama_model", settings.ollama.model),
        "gemini_model": db.get_setting("gemini_model", "gemini-2.5-flash"),
        "has_gemini_key": bool(gemini_key),
        "gemini_key_masked": masked_key,
        "ollama_online": ollama_online,
    }


@app.post("/api/system/ai_config")
def update_ai_config(body: AIConfigBody):
    """Actualiza proveedor de IA, modelo o claves API."""
    if body.provider is not None:
        if body.provider not in ("ollama", "gemini", "heuristic"):
            raise HTTPException(status_code=400, detail="Proveedor no válido (usa 'ollama', 'gemini' o 'heuristic').")
        db.set_setting("ai_provider", body.provider)

    if body.ollama_model:
        db.set_setting("ollama_model", body.ollama_model.strip())

    if body.gemini_model:
        db.set_setting("gemini_model", body.gemini_model.strip())

    if body.gemini_api_key is not None:
        db.set_setting("gemini_api_key", body.gemini_api_key.strip())

    return {"status": "ok", "message": "Configuración de IA guardada.", "config": get_ai_config()}


@app.post("/api/system/test_ai")
def test_ai_connection():
    """Prueba la latencia y funcionamiento del motor de IA activo (Ping IA)."""
    provider = db.get_setting("ai_provider", "ollama")
    t0 = time.perf_counter()

    if provider == "heuristic":
        return {
            "status": "ok",
            "provider": "heuristic",
            "model": "Motor de energía y reglas",
            "latency_ms": 1,
            "message": "Motor heurístico local en memoria (ultra-rápido, sin IA)."
        }

    if provider == "gemini":
        gemini_key = db.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return {
                "status": "error",
                "provider": "gemini",
                "error": "No has configurado una API Key de Gemini."
            }
        g_model = db.get_setting("gemini_model", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={gemini_key}"
        try:
            res = requests.post(
                url,
                json={"contents": [{"parts": [{"text": "Responde únicamente 'OK'"}]}]},
                timeout=10
            )
            lat_ms = int((time.perf_counter() - t0) * 1000)
            if res.status_code == 200:
                return {
                    "status": "ok",
                    "provider": "gemini",
                    "model": g_model,
                    "latency_ms": lat_ms,
                    "message": f"Gemini Cloud respondió en {lat_ms} ms."
                }
            return {
                "status": "error",
                "provider": "gemini",
                "error": f"Error {res.status_code}: {res.text[:120]}"
            }
        except Exception as e:
            return {"status": "error", "provider": "gemini", "error": str(e)}

    # Ollama
    ollama_url = getattr(settings.ollama, "base_url", "http://127.0.0.1:11434")
    o_model = db.get_setting("ollama_model", settings.ollama.model)
    try:
        res = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": o_model, "prompt": "Responde 'OK'", "stream": False, "options": {"num_predict": 4}},
            timeout=8
        )
        lat_ms = int((time.perf_counter() - t0) * 1000)
        if res.status_code == 200:
            return {
                "status": "ok",
                "provider": "ollama",
                "model": o_model,
                "latency_ms": lat_ms,
                "message": f"Ollama local respondió en {lat_ms} ms."
            }
        return {"status": "error", "provider": "ollama", "error": f"Error {res.status_code}"}
    except Exception as e:
        return {"status": "error", "provider": "ollama", "error": f"Ollama no responde: {e}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api_server:app", host="127.0.0.1", port=8501, reload=False)


# ---------------------------------------------------------------------------
# Módulos Avanzados: B-Roll Inteligente y SFX Inteligente (Submagic / Klap)
# ---------------------------------------------------------------------------
from src.agents.agent3_clip_generator.smart_broll import SmartBrollEngine, BrollItem, load_clip_broll, save_clip_broll
from src.agents.agent3_clip_generator.smart_sfx import SmartSFXEngine, SFXItem, load_clip_sfx, save_clip_sfx

_broll_engine = SmartBrollEngine()
_sfx_engine = SmartSFXEngine()

@app.get("/api/broll/catalog")
def get_broll_catalog():
    """Devuelve el catálogo de recursos B-Roll por categorías (videos, imágenes, stickers)."""
    return _broll_engine.get_catalog()

@app.get("/api/clips/{clip_id}/broll")
def get_clip_broll(clip_id: str):
    """Obtiene los elementos de B-Roll programados para este clip."""
    _get_clip_or_404(clip_id)
    items = load_clip_broll(clip_id) or []
    return {"clip_id": clip_id, "items": [it.to_dict() for it in items]}

@app.post("/api/clips/{clip_id}/broll")
def update_clip_broll(clip_id: str, items: List[Dict[str, Any]]):
    """Permite al usuario editar, añadir o silenciar elementos de B-Roll en la línea de tiempo."""
    _get_clip_or_404(clip_id)
    b_items = [BrollItem.from_dict(it) for it in items]
    save_clip_broll(clip_id, b_items)
    return {"status": "ok", "count": len(b_items)}

@app.get("/api/sfx/catalog")
def get_sfx_catalog():
    """Devuelve el catálogo de efectos de sonido en las 7 categorías con audio URLs."""
    return _sfx_engine.get_catalog()

@app.get("/api/clips/{clip_id}/sfx")
def get_clip_sfx(clip_id: str):
    """Obtiene los efectos de sonido programados para este clip."""
    _get_clip_or_404(clip_id)
    items = load_clip_sfx(clip_id) or []
    return {"clip_id": clip_id, "items": [it.to_dict() for it in items]}

@app.post("/api/clips/{clip_id}/sfx")
def update_clip_sfx(clip_id: str, items: List[Dict[str, Any]]):
    """Permite al usuario editar el volumen, cambiar o activar/desactivar SFX del clip."""
    _get_clip_or_404(clip_id)
    s_items = [SFXItem.from_dict(it) for it in items]
    save_clip_sfx(clip_id, s_items)
    return {"status": "ok", "count": len(s_items)}


# ---------------------------------------------------------------------------
# Módulos Avanzados: QR Download & Multi-Hook A/B Generator
# ---------------------------------------------------------------------------
import qrcode

@app.get("/api/clips/{clip_id}/download_info")
def get_clip_download_info(clip_id: str, request: Request):
    cand = _get_clip_or_404(clip_id)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "127.0.0.1:8501"
    scheme = request.headers.get("x-forwarded-proto") or ("https" if "trycloudflare.com" in host else "http")
    download_url = f"{scheme}://{host}/api/clips/{clip_id}/download"
    qr_url = f"/api/clips/{clip_id}/qr"
    return {
        "clip_id": clip_id,
        "title": cand.get("title") or f"Clip {clip_id}",
        "download_url": download_url,
        "qr_url": qr_url,
        "duration": cand.get("duration", 0),
        "virality_score": cand.get("virality_score", 0),
    }

@app.get("/api/clips/{clip_id}/qr")
def get_clip_qr(clip_id: str, request: Request):
    _get_clip_or_404(clip_id)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "127.0.0.1:8501"
    scheme = request.headers.get("x-forwarded-proto") or ("https" if "trycloudflare.com" in host else "http")
    download_url = f"{scheme}://{host}/api/clips/{clip_id}/download"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(download_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

class MultiHookRequest(BaseModel):
    custom_topic: Optional[str] = None

@app.post("/api/clips/{clip_id}/generate_hooks")
def generate_clip_hooks(clip_id: str, body: Optional[MultiHookRequest] = None):
    cand = _get_clip_or_404(clip_id)
    title = cand.get("title", "")
    hook_text = cand.get("hook_text", "")
    context_text = cand.get("context_text", "")
    full_text = f"{title}. {hook_text}. {context_text}"

    # Intento con Ollama si está disponible
    ollama_url = getattr(settings.ollama, "base_url", "http://127.0.0.1:11434")
    o_model = db.get_setting("ollama_model", getattr(settings.ollama, "model", "llama3.2:3b"))
    hooks = []

    prompt = f"""Eres un estratega viral senior de TikTok, Reels y YouTube Shorts.
Genera 3 ganchos (hooks) diferentes para este video corto:
Texto del clip: "{full_text[:400]}"

Devuelve EXCLUSIVAMENTE un JSON con esta estructura exacta sin explicaciones adicionales:
[
  {{
    "variant": "A",
    "name": "Curiosidad e Intriga",
    "headline": "TITULAR EN MAYUSCULAS (MAX 6 PALABRAS)",
    "hook_phrase": "Primera frase impactante para los primeros 3 segundos",
    "angle": "Explicación del gatillo psicológico",
    "copy_caption": "Copy listo para TikTok con llamada a la acción y 4 hashtags",
    "style_preset": "hormozi"
  }},
  {{
    "variant": "B",
    "name": "Shock y Controversia",
    "headline": "TITULAR EN MAYUSCULAS (MAX 6 PALABRAS)",
    "hook_phrase": "Primera frase impactante para los primeros 3 segundos",
    "angle": "Explicación del gatillo psicológico",
    "copy_caption": "Copy listo para TikTok con llamada a la acción y 4 hashtags",
    "style_preset": "beast"
  }},
  {{
    "variant": "C",
    "name": "Storytelling y Secreto",
    "headline": "TITULAR EN MAYUSCULAS (MAX 6 PALABRAS)",
    "hook_phrase": "Primera frase impactante para los primeros 3 segundos",
    "angle": "Explicación del gatillo psicológico",
    "copy_caption": "Copy listo para TikTok con llamada a la acción y 4 hashtags",
    "style_preset": "glow"
  }}
]
"""
    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": o_model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=8.0
        )
        if r.status_code == 200:
            parsed = json.loads(r.json().get("response", "[]"))
            if isinstance(parsed, list) and len(parsed) >= 3:
                hooks = parsed[:3]
    except Exception as e:
        pass

    # Heurística de alta conversión si Ollama no está disponible o falla el parseo
    if not hooks:
        clean_title = (title or "Momento Viral").upper()
        clean_title = re.sub(r'[^A-ZÁÉÍÓÚÑ0-9 ]', '', clean_title)
        words = clean_title.split()[:4]
        kw = " ".join(words) if words else "ESTO"

        hooks = [
            {
                "variant": "A",
                "name": "Curiosidad e Intriga",
                "headline": f"¿SABÍAS ESTO DE {kw}? 👀"[:35],
                "hook_phrase": f"Lo que casi nadie sabe sobre {kw.lower()}...",
                "angle": "Abre un bucle de curiosidad irresistible en los primeros 2 segundos.",
                "copy_caption": f"Nadie esperaba que esto saliera a la luz 😱 Mira hasta el final y comenta qué opinas 👇 #viral #parati #tendencia #reels",
                "style_preset": "hormozi"
            },
            {
                "variant": "B",
                "name": "Shock y Controversia",
                "headline": f"LA VERDAD SOBRE {kw} 🚨"[:35],
                "hook_phrase": f"Dijo lo que todos callan sobre {kw.lower()}...",
                "angle": "Provoca debate polarizante y comentarios inmediatos.",
                "copy_caption": f"Se atrevió a decir lo que muchos ocultan 💥 ¿Crees que tiene la razón? Deja tu opinión abajo 💬 #debate #polemica #tiktokviral",
                "style_preset": "beast"
            },
            {
                "variant": "C",
                "name": "Storytelling y Secreto",
                "headline": f"EL MOMENTO DONDE TODO CAMBIÓ 🤯"[:35],
                "hook_phrase": f"Esta historia cambió por completo cuando...",
                "angle": "Enganche narrativo con promesa de revelación final.",
                "copy_caption": f"Esta historia no es lo que parece 🤯 No te pierdas el desenlace completo. Sígueme para más contenido. #storytime #fyp #increible",
                "style_preset": "glow"
            }
        ]

    return {"clip_id": clip_id, "hooks": hooks}
