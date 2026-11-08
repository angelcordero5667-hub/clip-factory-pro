"""Dashboard único de Clip Factory: FastAPI + src/web/index.html.

Arranque: python -m src.api_server   (escucha solo en 127.0.0.1:8501)
Token opcional: variable de entorno CLIP_API_TOKEN.
"""
import io
import ipaddress
import os
import re
import requests
import secrets
import socket
import subprocess
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse
import psutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.database import db
from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.jobs import JobWorker

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
WEB_DIR = Path(__file__).resolve().parent / "web"
OUTPUTS_DIR = settings.outputs_dir
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

SUBTITLE_STYLES = (
    "hormozi", "limpio", "karaoke", "minimal",
    "hormozi_classic", "hormozi_neon", "beast", "mrbeast",
    "gaming", "podcast", "clean", "classic", "neon", "minimal_white",
    "bounce", "glow", "pop", "bouncing"
)
ASPECT_RATIOS = ("9:16", "1:1", "16:9")
LAYOUT_MODES = ("auto", "gaming", "blur")
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
app.mount("/clips_media", StaticFiles(directory=str(OUTPUTS_DIR)), name="clips_media")


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

    video_url = thumb_url = download_url = ""
    c_path = c.get("clip_path")
    if c_path and Path(c_path).exists():
        clip_file = Path(c_path)
        video_url = f"/clips_media/{clip_file.name}"
        download_url = f"/api/clips/{c['id']}/download"
        thumb_path = clip_file.with_suffix(".jpg")
        generate_thumbnail(clip_file, thumb_path)
        if thumb_path.exists():
            thumb_url = f"/clips_media/{thumb_path.name}"

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
    return html_file.read_text(encoding="utf-8")


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
        return {"source_title": "", "duration": "", "video_id": None, "clips": []}

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
    aspect: str = "9:16",
    position: str = "bottom",
    size: str = "medium",
    fontsize: Optional[int] = None,
):
    _get_clip_or_404(clip_id)
    if style not in SUBTITLE_STYLES or aspect not in ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail="Estilo o formato inválido.")
    job_id = db.create_job(source=clip_id, kind="rerender", candidate_id=clip_id,
                           options={
                               "subtitle_style": style,
                               "aspect_ratio": aspect,
                               "subtitle_position": position,
                               "subtitle_size": size,
                               "custom_fontsize": fontsize,
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
            fc = format_clip(c)
            copys.append(f"## {c.get('title')}  (puntaje {fc['score']}/100)\n" +
                         "\n\n".join(f"[{net}]\n{txt}\n{tags}" for net, (txt, tags) in fc["copy"].items()))
        zf.writestr("copys.txt", "\n\n----------------\n\n".join(copys))
    buf.seek(0)
    name = re.sub(r"[^\w-]", "_", _clean_title(video["filename"]))[:50] or video_id
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}_clips.zip"'})


# ------------------------------------------------------------------------------- trabajos
class JobBody(BaseModel):
    source: str
    max_clips: int = Field(default=5, ge=1, le=20)
    fast: bool = False
    language: Optional[str] = Field(default=None, max_length=8)
    target_duration: Optional[str] = "medium"
    min_clip_duration: Optional[float] = None
    max_clip_duration: Optional[float] = None
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

            return {
                "valid": True,
                "title": info.get("title") or f"Directo / Video de {platform}",
                "duration": dur,
                "uploader": uploader,
                "thumbnail": thumbnail,
                "is_stream": is_stream,
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
    target_model = getattr(settings.ollama, "model", "llama3.2:3b")
    ollama_info = {
        "accessible": False,
        "model_loaded": False,
        "model_name": target_model,
        "message": "Ollama no responde: se usará el motor heurístico"
    }
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=1.5)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            loaded = any(target_model in m for m in models)
            if loaded:
                ollama_info = {
                    "accessible": True,
                    "model_loaded": True,
                    "model_name": target_model,
                    "message": f"Ollama accesible y modelo {target_model} cargado"
                }
            else:
                ollama_info = {
                    "accessible": True,
                    "model_loaded": False,
                    "model_name": target_model,
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

    return {
        "ffmpeg": ffmpeg_info,
        "encoder": encoder_info,
        "ollama": ollama_info,
        "whisper": whisper_info,
        "yunet": yunet_info
    }


@app.get("/api/health/deps")
def get_health_deps():
    """Informe de estado de dependencias del sistema (solo lectura, sin rutas sensibles ni tokens)."""
    return check_dependencies()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api_server:app", host="127.0.0.1", port=8501, reload=False)
