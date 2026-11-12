"""
Puente de Integración Remotion ↔ Python para Clip Factory Pro.
Orquesta:
1. Conversión de metadatos, candidatos y transcripciones de Python a props estructurados de Remotion.
2. Ejecución headless con @remotion/renderer vía Node.js con reporte de progreso en tiempo real.
3. Gestión de concurrencia, cancelación y limpieza de archivos temporales.
4. Exportación de props para previsualización en vivo en @remotion/player.

Responsable: Claude (ver docs/COORDINACION_STREAMS.md). Cambios del 12-nov: cancelación que mata TODO el árbol de
procesos (npx → node → Chromium → FFmpeg), tiempo máximo configurable, stderr unido a stdout (antes podía
bloquear el render al llenarse la tubería) y archivo de props único por render.
"""

import json
import queue
import re
import shutil
import logging
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

import psutil

from src.common.config import settings
from src.common.models import ViralMomentCandidate, TranscriptSegment, WordTimestamp

logger = logging.getLogger("RemotionEngine")

REMOTION_DIR = settings.base_dir / "src" / "remotion"
REMOTION_RENDER_SCRIPT = REMOTION_DIR / "render.mjs"
DEFAULT_TIMEOUT_S = 1800.0


def kill_process_tree(pid: int, grace_s: float = 2.0) -> int:
    """Termina un proceso y TODOS sus descendientes (en Windows `proc.terminate()` solo mata el `npx.cmd`
    y deja node/Chromium abiertos). Devuelve cuántos procesos se terminaron."""
    try:
        root = psutil.Process(pid)
    except psutil.Error:
        return 0
    victims = root.children(recursive=True) + [root]
    for p in victims:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(victims, timeout=grace_s)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=grace_s)
    return len(victims)


class RemotionEngine:
    def __init__(self):
        self.remotion_dir = REMOTION_DIR
        self.render_script = REMOTION_RENDER_SCRIPT
        self.cache_dir = settings.cache_dir / "remotion"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._node_exe = shutil.which("node") or "node"

    def is_available(self) -> bool:
        """Comprueba si Node.js y los módulos de Remotion están instalados y disponibles."""
        if not self.render_script.exists():
            return False
        node_modules = self.remotion_dir / "node_modules" / "@remotion" / "renderer"
        if not node_modules.exists():
            return False
        return True

    def build_props(
        self,
        video_path: str,
        candidate: ViralMomentCandidate,
        transcript_segments: Optional[List[TranscriptSegment]] = None,
        options: Optional[Dict[str, Any]] = None,
        fps: int = 30
    ) -> Dict[str, Any]:
        """
        Construye el payload de propiedades JSON para Remotion a partir de los datos de Python.
        """
        opts = options or {}
        clip_start = float(candidate.start_time)
        clip_end = float(candidate.end_time)
        duration_sec = max(1.0, clip_end - clip_start)
        duration_frames = int(duration_sec * fps)

        # Filtrar subtítulos en la ventana del clip
        sub_list = []
        if transcript_segments:
            for s in transcript_segments:
                if s.end >= clip_start and s.start <= clip_end:
                    words_data = []
                    for w in (s.words or []):
                        if w.end >= clip_start and w.start <= clip_end:
                            words_data.append({
                                "word": str(w.word).strip(),
                                "start": float(w.start),
                                "end": float(w.end),
                                "highlight": getattr(w, "probability", 1.0) > 0.85
                            })
                    sub_list.append({
                        "id": s.id,
                        "start": float(s.start),
                        "end": float(s.end),
                        "text": str(s.text).strip(),
                        "words": words_data
                    })

        # Mapear ruta de video (normalizada con barras hacia adelante para Node/Remotion)
        vpath_resolved = str(Path(video_path).resolve()).replace("\\", "/")

        return {
            "videoSrc": vpath_resolved,
            "title": candidate.title or "Clip Viral",
            "clipStartSec": clip_start,
            "clipEndSec": clip_end,
            "durationInFrames": duration_frames,
            "fps": fps,
            "width": 1080,
            "height": 1920,
            "subtitles": sub_list,
            "subtitleStyle": opts.get("subtitle_style", "hormozi"),
            "subtitlePosition": opts.get("subtitle_position", "bottom"),
            "subtitleFontSize": opts.get("subtitle_font_size", 62),
            "customHighlightColor": opts.get("custom_highlight", "#FFE600"),
            "framingMode": opts.get("framing_mode", "blur"),
            "splitRatio": float(opts.get("split_ratio", 0.5)),
            "splitXs": opts.get("split_xs", [0.25, 0.75]),
            "punchZoom": opts.get("punch_zoom", True),
            "punchZoomStartSec": 0.0,
            "punchZoomDurationSec": 2.5,
            "punchZoomScale": float(opts.get("punch_zoom_scale", 1.15)),
            "dynamicZoom": opts.get("dynamic_zoom", False),
            "hookHeadline": opts.get("hook_headline", candidate.hook_text or candidate.title),
            "colorFilter": opts.get("color_filter", "pop"),
            "progressBar": opts.get("progress_bar", True),
            "progressBarColor": opts.get("progress_bar_color", "#A855F7"),
            "soundEffects": opts.get("sound_effects", [{"type": "whoosh", "timeSec": clip_start + 0.1, "volume": 0.5}]),
            "enableSfx": opts.get("auto_sfx", True)
        }

    def render_clip(
        self,
        props: Dict[str, Any],
        output_path: Path,
        on_progress: Optional[Callable[[float, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        concurrency: int = 4,
        fps: int = 30,
        timeout_s: Optional[float] = DEFAULT_TIMEOUT_S,
        muted: bool = False,
    ) -> Path:
        """
        Ejecuta Remotion para producir el archivo MP4 final en 1080x1920.
        Lee los eventos de progreso en tiempo real, gestiona cancelaciones (matando todo el árbol de procesos)
        y aplica un tiempo máximo. Si algo falla, no deja procesos ni archivos temporales.
        """
        if not self.is_available():
            raise RuntimeError("El entorno Remotion no está instalado o listo en src/remotion.")

        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # Si videoSrc es un archivo absoluto dentro del sistema, asegurar que esté accesible
        # Para Remotion, copiamos o enlazamos el video en public/ si es un archivo local
        vsrc = props.get("videoSrc", "")
        if vsrc and not vsrc.startswith("http://") and not vsrc.startswith("https://") and not vsrc.startswith("data:"):
            local_p = Path(vsrc)
            if local_p.exists():
                public_dir = self.remotion_dir / "public"
                public_dir.mkdir(parents=True, exist_ok=True)
                public_dest = public_dir / local_p.name
                if not public_dest.exists() or public_dest.stat().st_size != local_p.stat().st_size:
                    try:
                        shutil.copy2(local_p, public_dest)
                    except Exception as e:
                        logger.debug(f"No se pudo copiar a public: {e}")
                props = dict(props, videoSrc=local_p.name)

        # Archivo de props único por render (dos renders simultáneos no se pisan)
        props_file = self.cache_dir / f"props_{uuid.uuid4().hex}.json"
        with open(props_file, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False, indent=2)

        # Usar npx remotion render para máxima estabilidad en Windows
        npx_exe = "npx.cmd" if sys.platform == "win32" else "npx"
        total_frames = int(props.get("durationInFrames", 30 * 30))
        frames_arg = f"--frames=0-{max(0, total_frames - 1)}"

        cmd = [
            npx_exe,
            "remotion",
            "render",
            "src/index.ts",
            "ViralShortComposition",
            str(out_file),
            f"--props={str(props_file.resolve())}",
            frames_arg,
            f"--concurrency={int(concurrency)}",
        ]
        if muted:
            cmd.append("--muted")   # solo imagen: el audio masterizado lo pone FFmpeg después

        logger.info(f"Iniciando render Remotion: {out_file.name} (concurrency={concurrency}, fps={fps})")
        if on_progress:
            on_progress(0.05, "Inicializando Remotion & Chromium...")

        rendered_re = re.compile(r"Rendered\s+(\d+)/(\d+)")
        bundling_re = re.compile(r"Bundling\s+(\d+)%")

        # stderr unido a stdout: una sola tubería que un hilo vacía siempre (evita bloqueos por tubería llena)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.remotion_dir),
            bufsize=1,
        )
        lines: "queue.Queue[Optional[str]]" = queue.Queue()

        def _reader():
            try:
                for raw in proc.stdout:
                    lines.put(raw)
            finally:
                lines.put(None)

        threading.Thread(target=_reader, name="remotion-stdout", daemon=True).start()

        started = time.monotonic()
        tail: List[str] = []
        failure: Optional[str] = None
        finished_reading = False

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    logger.warning(f"Render Remotion cancelado. Terminando árbol de procesos (PID raíz {proc.pid})...")
                    kill_process_tree(proc.pid)
                    raise RuntimeError("Renderizado Remotion cancelado.")
                if timeout_s and (time.monotonic() - started) > timeout_s:
                    logger.error(f"Render Remotion superó el tiempo máximo ({timeout_s:.0f}s). Terminando procesos.")
                    kill_process_tree(proc.pid)
                    raise RuntimeError(f"Renderizado Remotion cancelado por tiempo máximo ({timeout_s:.0f}s).")

                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None and finished_reading:
                        break
                    continue
                if line is None:
                    finished_reading = True
                    if proc.poll() is not None:
                        break
                    continue

                line_str = line.strip()
                if not line_str:
                    continue
                tail.append(line_str)
                if len(tail) > 40:
                    tail.pop(0)

                m_rend = rendered_re.search(line_str)
                m_bund = bundling_re.search(line_str)
                if m_rend:
                    current_f = int(m_rend.group(1))
                    total_f = int(m_rend.group(2))
                    pct = current_f / max(1, total_f)
                    if on_progress:
                        on_progress(0.15 + pct * 0.80, f"Renderizando frame {current_f}/{total_f} ({int(pct * 100)}%)")
                elif m_bund and on_progress:
                    pct = int(m_bund.group(1)) / 100.0
                    on_progress(0.05 + pct * 0.10, f"Empaquetando composición Remotion ({int(pct * 100)}%)")

            ret = proc.wait()
            if ret != 0:
                err_lines = [l for l in tail if ("Error" in l or "Exception" in l)] or tail[-5:]
                failure = "\n".join(err_lines) or f"Código de salida: {ret}"
                logger.error(f"Fallo en render Remotion: {failure}")
                raise RuntimeError(f"Error renderizando con Remotion: {failure}")

            if not out_file.exists() or out_file.stat().st_size == 0:
                raise RuntimeError("El archivo de video generado por Remotion está vacío o no se creó.")

            if on_progress:
                on_progress(1.0, "Render Remotion completado exitosamente.")

            logger.info(f"Video Remotion generado exitosamente: {out_file} ({out_file.stat().st_size / (1024*1024):.2f} MB)")
            return out_file

        except BaseException:
            # Cancelación, tiempo máximo o fallo: no dejar un MP4 a medias.
            out_file.unlink(missing_ok=True)
            raise
        finally:
            # Pase lo que pase: sin procesos huérfanos (Chromium incluido) ni props temporales.
            if proc.poll() is None:
                kill_process_tree(proc.pid)
            props_file.unlink(missing_ok=True)


    # ------------------------------------------------------------------ audio masterizado + ensamblado
    @staticmethod
    def _ffprobe_exe() -> str:
        exe = Path(settings.ffmpeg_exe)
        cand = exe.with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        return str(cand) if cand.exists() else (shutil.which("ffprobe") or "ffprobe")

    def probe(self, path: Path) -> Dict[str, Any]:
        """Datos reales del archivo (ffprobe): duración, si tiene video/audio y sus parámetros."""
        res = subprocess.run(
            [self._ffprobe_exe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"ffprobe no pudo leer {Path(path).name}: {res.stderr[-200:]}")
        data = json.loads(res.stdout or "{}")
        v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        return {
            "duration": float(data.get("format", {}).get("duration") or 0.0),
            "has_video": v is not None, "has_audio": a is not None,
            "width": (v or {}).get("width"), "height": (v or {}).get("height"), "video_codec": (v or {}).get("codec_name"),
            "audio_codec": (a or {}).get("codec_name"), "audio_rate": (a or {}).get("sample_rate"),
            "audio_channels": (a or {}).get("channels"),
        }

    def master_and_mux(
        self,
        visual_path: Path,
        source_video: str,
        start: float,
        duration: float,
        out_path: Path,
        audio_profile: str = "social",
        normalize_audio: bool = True,
        seamless_loop: bool = True,
        master_limiter: bool = True,
        timeout_s: float = 600.0,
    ) -> Path:
        """Une la imagen renderizada (sin audio) con el audio del original pasado por la MISMA cadena de
        masterización que usa el motor FFmpeg (loudnorm + limitador). La imagen se copia (`-c:v copy`):
        no hay segunda codificación de video. Valida el resultado con ffprobe."""
        from src.common.viral_enhancements import build_audio_filter_chain
        af_parts = build_audio_filter_chain(duration=duration, normalize_audio=normalize_audio, seamless_loop=seamless_loop,
                                            audio_profile=audio_profile, master_limiter=master_limiter)
        cmd = [settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(visual_path),
               "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}", "-i", str(source_video),
               "-map", "0:v:0", "-map", "1:a:0?"]
        if af_parts:
            cmd += ["-af", ",".join(af_parts)]
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path)]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
        if res.returncode != 0:
            Path(out_path).unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg falló al unir imagen y audio masterizado: {res.stderr[-300:]}")
        info = self.probe(out_path)
        if not info["has_video"] or not info["has_audio"]:
            Path(out_path).unlink(missing_ok=True)
            raise RuntimeError(f"El clip final no tiene {'video' if not info['has_video'] else 'audio'} (ffprobe).")
        vis = self.probe(visual_path)
        if abs(info["duration"] - vis["duration"]) > 0.5:
            Path(out_path).unlink(missing_ok=True)
            raise RuntimeError(f"Duración final {info['duration']:.2f}s no coincide con la imagen {vis['duration']:.2f}s.")
        return Path(out_path)

    @staticmethod
    def ass_to_css_color(value: Optional[str], default: str = "#FFE600") -> str:
        """Convierte el color de resaltado del pipeline (ASS `&HAABBGGRR`) al `#RRGGBB` que usa CSS."""
        if not value:
            return default
        v = str(value).strip()
        if v.startswith("#") and len(v) in (4, 7):
            return v
        m = re.fullmatch(r"&?[Hh]?([0-9A-Fa-f]{6,8})&?", v)
        if not m:
            return default
        h = m.group(1)[-6:]                    # BBGGRR (se ignora el canal alfa)
        return f"#{h[4:6]}{h[2:4]}{h[0:2]}".upper()

    def render_candidate(
        self,
        source_video: str,
        candidate: ViralMomentCandidate,
        transcript_segments: List[TranscriptSegment],
        out_path: Path,
        options: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[float, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        concurrency: int = 2,
        timeout_s: Optional[float] = DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Clip completo con Remotion: imagen sin audio → FFmpeg pone el audio masterizado → MP4 final validado.
        Siempre limpia el archivo temporal intermedio."""
        opts = dict(options or {})
        opts["custom_highlight"] = self.ass_to_css_color(opts.get("custom_highlight"))
        opts["punch_zoom"] = bool(opts.get("punch_zooms", opts.get("punch_zoom", True)))
        props = self.build_props(source_video, candidate, transcript_segments, opts)
        if not (opts.get("hook_headline") or "").strip():
            props["hookHeadline"] = ""          # sin titular inventado: solo si el usuario/pipeline lo da
        props["soundEffects"] = []              # los SFX del pipeline no están portados a este motor (pendiente)
        props["enableSfx"] = False

        out_path = Path(out_path)
        tmp_visual = self.cache_dir / f"visual_{uuid.uuid4().hex}.mp4"

        def _scaled(lo, hi):
            return (lambda p, m: on_progress(lo + (hi - lo) * p, m)) if on_progress else None

        try:
            self.render_clip(props, tmp_visual, on_progress=_scaled(0.0, 0.92), cancel_event=cancel_event,
                             concurrency=concurrency, timeout_s=timeout_s, muted=True)
            if on_progress:
                on_progress(0.93, "Aplicando audio masterizado (FFmpeg)...")
            duration = float(candidate.end_time) - float(candidate.start_time)
            self.master_and_mux(tmp_visual, source_video, float(candidate.start_time), duration, out_path,
                                audio_profile=opts.get("audio_profile", "social"),
                                seamless_loop=bool(opts.get("seamless_loop", True)),
                                master_limiter=bool(opts.get("master_limiter", True)))
            if on_progress:
                on_progress(1.0, "Clip Remotion listo.")
            return out_path
        finally:
            tmp_visual.unlink(missing_ok=True)


# Singleton
remotion_engine = RemotionEngine()
