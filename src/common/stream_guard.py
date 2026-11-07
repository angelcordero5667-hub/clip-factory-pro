"""Protecciones para streams y videos enormes antes de descargar con yt-dlp.

- Un directo que sigue EN VIVO no tiene fin: la descarga no terminaría nunca y el trabajo quedaría colgado.
- Un video de varias horas sin tramo ocupa muchísimo disco y tiempo; se pide "Desde/Hasta".
La comprobación es de mejor esfuerzo: si no se puede consultar el enlace, no se bloquea nada
(el descargador dará su propio error).
"""
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("StreamGuard")

PROBE_TTL_SECONDS = 600
_probe_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


def max_full_seconds() -> float:
    """Duración máxima que se descarga entera sin tramo (CLIP_MAX_FULL_HOURS, 2 h por defecto)."""
    try:
        return float(os.environ.get("CLIP_MAX_FULL_HOURS", "2")) * 3600.0
    except ValueError:
        return 7200.0


def _fmt_hours(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h} h {rem // 60} min" if h else f"{rem // 60} min"


def probe_url(url: str) -> Optional[Dict[str, Any]]:
    """Metadatos ligeros (sin descargar): título, duración y estado en vivo. None si no se pudo consultar."""
    now = time.time()
    cached = _probe_cache.get(url)
    if cached and now - cached[0] < PROBE_TTL_SECONDS:
        return cached[1]
    info: Optional[Dict[str, Any]] = None
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 20}
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
        if isinstance(raw, dict):
            info = {
                "title": raw.get("title"),
                "duration": raw.get("duration"),
                "live_status": raw.get("live_status"),
                "is_live": bool(raw.get("is_live")),
            }
    except Exception as e:
        logger.debug(f"No se pudo consultar {url}: {e}")
    _probe_cache[url] = (now, info)
    return info


def check_stream(info: Dict[str, Any], time_range: Optional[Tuple[float, float]] = None) -> None:
    """Lanza RuntimeError con un mensaje claro si el enlace no se debe descargar tal cual."""
    status = info.get("live_status")
    if info.get("is_live") or status == "is_live":
        raise RuntimeError(
            "Ese directo sigue EN VIVO y no tiene final: la descarga no terminaría. "
            "Espera a que acabe (YouTube/Twitch lo guardan como video) y pega el enlace del VOD.")
    if status == "is_upcoming":
        raise RuntimeError("Ese directo aún no ha empezado. Vuelve cuando termine y pega el enlace del VOD.")

    duration = info.get("duration")
    has_range = bool(time_range and len(time_range) == 2 and time_range[1] > time_range[0])
    if duration and has_range and time_range[0] >= duration:
        raise RuntimeError(
            f"El tramo empieza en el minuto {int(time_range[0] // 60)}, pero el video dura solo {_fmt_hours(duration)}.")
    if duration and not has_range and duration > max_full_seconds():
        raise RuntimeError(
            f"Es un video de {_fmt_hours(duration)}. Descargarlo entero tarda mucho y ocupa mucho disco: "
            "indica un tramo en 'Desde / Hasta' (por ejemplo 00:30:00 a 00:50:00).")


def guard_url(url: str, time_range: Optional[Tuple[float, float]] = None) -> Optional[Dict[str, Any]]:
    """Consulta el enlace y aplica `check_stream`. Devuelve los metadatos (o None si no se pudieron obtener)."""
    info = probe_url(url)
    if info:
        check_stream(info, time_range)
    return info
