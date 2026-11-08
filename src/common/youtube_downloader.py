"""Descarga de videos/audio desde cualquier sitio que soporte yt-dlp (YouTube, Vimeo, X, TikTok, Twitch...).

Los nombres `download_youtube_*` se mantienen por compatibilidad con el resto del proyecto.
"""
import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.common.config import settings
from src.common.stream_guard import guard_url

logger = logging.getLogger("WebDownloader")

DEFAULT_RETRIES = 3
SOCKET_TIMEOUT = 30

ProgressFn = Optional[Callable[[float], None]]  # fracción 0-1 de la descarga actual


def _base_opts(progress: ProgressFn) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'noplaylist': True,          # un enlace con &list=... descarga solo el video
        'retries': DEFAULT_RETRIES,
        'fragment_retries': DEFAULT_RETRIES,
        'socket_timeout': SOCKET_TIMEOUT,
        'concurrent_fragment_downloads': 4,
        'buffersize': 1024 * 1024,
        'http_chunk_size': 10485760,
    }
    if progress:
        def hook(d):
            try:
                if d.get('status') == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    if total:
                        progress(min(1.0, d.get('downloaded_bytes', 0) / total))
                elif d.get('status') == 'finished':
                    progress(1.0)
            except Exception:  # el progreso nunca debe romper la descarga
                pass
        opts['progress_hooks'] = [hook]
    return opts


def _friendly_error(url: str, exc: Exception) -> RuntimeError:
    msg = str(exc).replace("ERROR: ", "").strip()
    lowered = msg.lower()
    if "unsupported url" in lowered:
        return RuntimeError(f"Ese sitio o enlace no tiene un video descargable: {url}")
    if "private" in lowered or "sign in" in lowered or "login" in lowered:
        return RuntimeError("El video es privado o exige iniciar sesión; no se puede descargar.")
    if "unavailable" in lowered or "not available" in lowered:
        return RuntimeError("El video no está disponible (borrado o bloqueado en tu región).")
    return RuntimeError(f"No se pudo descargar el video: {msg[:300]}")


def _resolve_file(ydl, info) -> str:
    filename = ydl.prepare_filename(info)
    if not Path(filename).exists():
        alt = Path(filename).with_suffix('.mp4')
        if alt.exists():
            return str(alt)
    return filename


def download_youtube_video(url: str, output_dir: Path = settings.inputs_dir, max_height: int = 720,
                           progress: ProgressFn = None,
                           time_range: Optional[Tuple[float, float]] = None) -> Tuple[str, str]:
    """Descarga el video UNA sola vez (por defecto 720p). Si time_range=(start, end), descarga quirúrgica."""
    guard_url(url, time_range)  # directos en vivo / videos enormes sin tramo -> error claro antes de descargar
    output_dir.mkdir(parents=True, exist_ok=True)
    import yt_dlp

    ydl_opts = _base_opts(progress)
    range_tag = ""
    if time_range and len(time_range) == 2 and time_range[1] > time_range[0]:
        start_s, end_s = time_range
        ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(start_s, end_s)])
        ydl_opts['force_keyframes_at_cuts'] = True
        range_tag = f"_range_{int(start_s)}_{int(end_s)}"

    ydl_opts.update({
        'format': (f'bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/'
                   f'best[height<={max_height}][ext=mp4]/best[height<={max_height}]/best'),
        'merge_output_format': 'mp4',
        'outtmpl': str(output_dir / f'%(title)s_%(id)s{range_tag}_video.%(ext)s'),
    })
    logger.info(f"Descargando video {max_height}p: {url} {range_tag}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = _resolve_file(ydl, info)
            title = info.get('title') or 'Video'
    except Exception as e:
        raise _friendly_error(url, e) from e
    return filename, title


def download_youtube_audio(url: str, output_dir: Path = settings.inputs_dir,
                           progress: ProgressFn = None,
                           time_range: Optional[Tuple[float, float]] = None) -> Tuple[str, str]:
    """
    Descarga únicamente el audio en formato ligero (m4a/mp3).
    Si time_range=(start, end), solo descarga ese rango específico del stream.
    """
    guard_url(url, time_range)  # directos en vivo / videos enormes sin tramo -> error claro antes de descargar
    output_dir.mkdir(parents=True, exist_ok=True)
    import yt_dlp

    ydl_opts = _base_opts(progress)
    range_tag = ""
    if time_range and len(time_range) == 2 and time_range[1] > time_range[0]:
        start_s, end_s = time_range
        ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(start_s, end_s)])
        ydl_opts['force_keyframes_at_cuts'] = True
        range_tag = f"_range_{int(start_s)}_{int(end_s)}"

    ydl_opts.update({
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': str(output_dir / f'%(title)s_%(id)s{range_tag}_audio.%(ext)s'),
    })
    logger.info(f"Descargando audio ligero: {url} {range_tag}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            title = info.get('title') or 'Audio'
    except Exception as e:
        raise _friendly_error(url, e) from e

    logger.info(f"Audio descargado: {filename}")
    return filename, title
