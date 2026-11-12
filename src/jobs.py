"""Cola de trabajos persistente (tabla `jobs` en SQLite) con un worker en segundo plano.

Un solo hilo procesa los trabajos en orden de llegada (la CPU ya se aprovecha dentro de cada
trabajo con render en paralelo). El estado vive en la base de datos, no en variables globales,
así que el dashboard puede recargarse o reiniciarse sin perder la cola.
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from src.common.database import Database, db as default_db
from src.agents.agent5_qa_optimizer.pipeline import STEPS

logger = logging.getLogger("JobWorker")


class JobWorker:
    def __init__(self, database: Optional[Database] = None,
                 pipeline_factory: Optional[Callable[[], Any]] = None, poll_seconds: float = 1.0):
        self.db = database or default_db
        self._pipeline_factory = pipeline_factory
        self._pipeline = None
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------ ciclo de vida
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        stale = self.db.reset_stale_jobs()
        if stale:
            logger.warning(f"{stale} trabajo(s) interrumpidos marcados como error.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            job = None
            try:
                job = self.db.claim_next_job()
            except Exception as e:  # base de datos bloqueada, etc.
                logger.error(f"No se pudo leer la cola: {e}")
            if job is None:
                self._stop.wait(self._poll)
                continue
            self.run_job(job)

    # ------------------------------------------------------------------ trabajos
    def _get_pipeline(self):
        if self._pipeline is None:
            if self._pipeline_factory:
                self._pipeline = self._pipeline_factory()
            else:
                from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline
                self._pipeline = ClipFactoryPipeline()
        return self._pipeline

    def run_job(self, job: Dict[str, Any]):
        job_id = job["id"]
        opts = job.get("options") or {}
        try:
            pipeline = self._get_pipeline()

            def on_step(index: int, fraction: float, msg: str):
                index = max(0, min(index, len(STEPS) - 1))
                cur_job = self.db.get_job(job_id)
                if cur_job and cur_job.get("status") == "cancelled":
                    raise RuntimeError("Trabajo cancelado por el usuario.")
                self.db.update_job(
                    job_id, step_index=index, step_label=STEPS[index], message=msg,
                    progress=round((index + max(0.0, min(1.0, fraction))) / len(STEPS), 3))

            if job["kind"] == "rerender":
                self.db.update_job(job_id, step_index=3, step_label=STEPS[3], message="Re-renderizando clip...", progress=0.5)
                # Cancelar un render en marcha (?force=true): este vigilante convierte "cancelado" en la base
                # de datos en una señal que mata el árbol de procesos de Remotion. Con FFmpeg no se puede
                # interrumpir (llamada bloqueante), y se ve en el estado final. Termina solo cuando el
                # trabajo deja de estar "running".
                cancel_event = threading.Event()

                def _watch_cancel():
                    while True:
                        time.sleep(1.0)
                        cur = self.db.get_job(job_id)
                        if not cur or cur.get("status") != "running":
                            if cur and cur.get("status") == "cancelled":
                                cancel_event.set()
                            return

                threading.Thread(target=_watch_cancel, name=f"cancel-watch-{job_id}", daemon=True).start()
                pipeline.rerender_candidate(
                    job["candidate_id"],
                    visual_engine=opts.get("visual_engine", "ffmpeg"),
                    cancel_event=cancel_event,
                    progress_callback=lambda m: self.db.update_job(job_id, message=str(m)[:200]),
                    with_subtitles=bool(opts.get("with_subtitles", True)),
                    subtitle_style=opts.get("subtitle_style", "hormozi"),
                    aspect_ratio=opts.get("aspect_ratio", "9:16"),
                    subtitle_position=opts.get("subtitle_position", "bottom"),
                    custom_fontsize=opts.get("custom_fontsize"),
                    subtitle_size=opts.get("subtitle_size"),
                    custom_highlight=opts.get("custom_highlight"),
                    progress_bar=bool(opts.get("progress_bar", False)),
                    color_filter=opts.get("color_filter", "none"),
                    dynamic_zoom=bool(opts.get("dynamic_zoom", False)),
                    punch_zooms=bool(opts.get("punch_zooms", False)),
                    split_glow=opts.get("split_glow"),
                    hook_headline=opts.get("hook_headline"),
                    broll_theme=opts.get("broll_theme", "gameplay"),
                    seamless_loop=bool(opts.get("seamless_loop", True)),
                    auto_broll=bool(opts.get("auto_broll", True)),
                    auto_sfx=bool(opts.get("auto_sfx", True)),
                    sfx_intensity=opts.get("sfx_intensity", "normal"),
                    broll_mode=opts.get("broll_mode", "smart_face_avoid"),
                    broll_density=opts.get("broll_density", "medium"),
                    framing_mode=opts.get("framing_mode", "auto"),
                    trim_silences=bool(opts.get("trim_silences", True)),
                    audio_profile=opts.get("audio_profile", "social"),
                    master_limiter=bool(opts.get("master_limiter", True)),
                )
                self.db.update_job(job_id, status="done", progress=1.0, message="Clip actualizado.")
                return

            from src.common.models import parse_time_str
            time_range = None
            t_start = parse_time_str(opts.get("time_range_start"))
            t_end = parse_time_str(opts.get("time_range_end"))
            if t_start is not None and t_end is not None and t_end > t_start:
                time_range = (t_start, t_end)
            elif t_start is not None and t_end is None:
                time_range = (t_start, t_start + 1800.0)

            layout_mode = opts.get("layout") or opts.get("layout_mode") or "auto"
            speed_mode = opts.get("speed_mode") or "turbo"
            hook_zoom = bool(opts.get("hook_zoom", True)) if "hook_zoom" in opts else True
            watermark_text = opts.get("watermark_text") or opts.get("watermark") or None
            focus_prompt = opts.get("focus_prompt") or None
            live_record_minutes = opts.get("live_record_minutes")

            min_clip_dur = opts.get("min_clip_duration")
            max_clip_dur = opts.get("max_clip_duration")
            if min_clip_dur is None or max_clip_dur is None:
                td = (opts.get("target_duration") or "medium").lower()
                if td == "short":
                    min_clip_dur, max_clip_dur = 15.0, 30.0
                elif td == "long":
                    min_clip_dur, max_clip_dur = 60.0, 90.0
                else:
                    min_clip_dur, max_clip_dur = 30.0, 60.0

            video_id, cands = pipeline.run_pipeline(
                video_input=job["source"],
                max_candidates=int(opts.get("max_clips", 5)),
                with_subtitles=bool(opts.get("with_subtitles", True)),
                subtitle_style=opts.get("subtitle_style", "hormozi"),
                aspect_ratio=opts.get("aspect_ratio", "9:16"),
                include_emojis=bool(opts.get("include_emojis", True)),
                fast=bool(opts.get("fast", False)),
                language=opts.get("language") or None,
                layout_mode=layout_mode,
                speed_mode=speed_mode,
                hook_zoom=hook_zoom,
                watermark_text=watermark_text,
                focus_prompt=focus_prompt,
                time_range=time_range,
                min_clip_duration=float(min_clip_dur) if min_clip_dur is not None else None,
                max_clip_duration=float(max_clip_dur) if max_clip_dur is not None else None,
                step_callback=on_step,
                subtitle_position=opts.get("subtitle_position", "bottom"),
                custom_fontsize=opts.get("custom_fontsize"),
                subtitle_size=opts.get("subtitle_size"),
                custom_highlight=opts.get("custom_highlight"),
                progress_bar=bool(opts.get("progress_bar", False)),
                color_filter=opts.get("color_filter", "none"),
                dynamic_zoom=bool(opts.get("dynamic_zoom", False)),
                split_glow=opts.get("split_glow"),
                hook_headline=opts.get("hook_headline"),
                broll_theme=opts.get("broll_theme", "gameplay"),
                dominican_mode=bool(opts.get("dominican_mode", True)),
                seamless_loop=bool(opts.get("seamless_loop", True)),
                auto_broll=bool(opts.get("auto_broll", True)),
                    auto_sfx=bool(opts.get("auto_sfx", True)),
                    sfx_intensity=opts.get("sfx_intensity", "normal"),
                    broll_mode=opts.get("broll_mode", "smart_face_avoid"),
                    broll_density=opts.get("broll_density", "medium"),
                    framing_mode=opts.get("framing_mode"),
                trim_silences=bool(opts.get("trim_silences", True)),
                audio_profile=opts.get("audio_profile", "social"),
                master_limiter=bool(opts.get("master_limiter", True)),
                live_record_minutes=float(live_record_minutes) if live_record_minutes is not None else None,
            )
            self.db.update_job(job_id, status="done", progress=1.0, video_id=video_id,
                               step_index=len(STEPS) - 1, step_label=STEPS[-1],
                               message=f"¡Completado! {sum(1 for c in cands if getattr(c, 'clip_path', None)) or len(cands)} clips listos.")
        except Exception as e:
            if "cancelado por el usuario" in str(e).lower():
                logger.info(f"Trabajo {job_id} detenido por cancelación.")
                self.db.update_job(job_id, status="cancelled", message="Trabajo cancelado por el usuario.")
            else:
                logger.exception(f"Trabajo {job_id} falló")
                self.db.update_job(job_id, status="error", error=str(e), message=f"Error: {e}")
