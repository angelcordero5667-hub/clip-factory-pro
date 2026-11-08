import re
import uuid
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Callable

from src.common.config import settings
from src.common.database import db
from src.common.models import ViralMomentCandidate, TranscriptResult
from src.common.youtube_downloader import download_youtube_video, download_youtube_audio
from src.agents.agent1_transcription.transcriber import AudioTranscriber
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.agents.agent2_viral_detector.audio_energy import compute_energy_profile
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.agents.agent5_qa_optimizer.optimizer import MemoryOptimizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Agent5_Pipeline")

# Pasos con nombre que muestra el dashboard (índice usado por step_callback)
STEPS = ("Descarga", "Transcripción", "Análisis", "Renderizado", "Guardado")

StepCallback = Callable[[int, float, str], None]  # (índice_paso, fracción 0-1 dentro del paso, mensaje)


class ClipFactoryPipeline:
    """
    Agente 5: Orquestador. Soporta URLs de YouTube o archivos locales.
    Descarga -> Transcripción -> Detección (0-100) -> Renderizado en paralelo -> Base de datos.
    """

    def __init__(
        self,
        transcriber: Optional[AudioTranscriber] = None,
        detector: Optional[ViralMomentDetector] = None,
        clip_maker: Optional[VerticalClipMaker] = None,
        optimizer: Optional[MemoryOptimizer] = None
    ):
        self.transcriber = transcriber or AudioTranscriber()
        self.detector = detector or ViralMomentDetector()
        self.clip_maker = clip_maker or VerticalClipMaker()
        self.optimizer = optimizer or MemoryOptimizer(max_ram_gb=settings.hardware.max_ram_usage_gb)

    def run_pipeline(
        self,
        video_input: str,
        max_candidates: int = 5,
        render_clips: bool = True,
        subtitle_style: str = "hormozi",
        include_emojis: bool = True,
        aspect_ratio: str = "9:16",
        subtitle_position: str = "bottom",
        custom_fontsize: Optional[int] = None,
        custom_highlight: Optional[str] = None,
        uppercase: Optional[bool] = None,
        add_watermark: bool = False,
        watermark_text: Optional[str] = None,
        use_cache: bool = True,
        fast: bool = False,
        language: Optional[str] = None,
        layout_mode: Optional[str] = None,
        speed_mode: Optional[str] = None,
        hook_zoom: Optional[bool] = None,
        focus_prompt: Optional[str] = None,
        time_range: Optional[Tuple[float, float]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        step_callback: Optional[StepCallback] = None,
    ) -> Tuple[str, List[ViralMomentCandidate]]:
        video_id = f"vid_{uuid.uuid4().hex[:8]}"

        def log_step(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        def step(index: int, fraction: float, msg: str):
            log_step(msg)
            if step_callback:
                step_callback(index, fraction, msg)

        # 0. Enlace de YouTube o archivo local
        is_remote = video_input.startswith("http://") or video_input.startswith("https://")
        if is_remote:
            range_info = f" ({int(time_range[0]//60)}m-{int(time_range[1]//60)}m)" if time_range else ""
            step(0, 0.0, f"📥 Descargando audio del enlace{range_info}...")
            dl_audio_kwargs = {}
            if time_range:
                dl_audio_kwargs["time_range"] = time_range
            local_path, yt_title = download_youtube_audio(
                video_input,
                progress=lambda f: step_callback and step_callback(0, f, f"📥 Descargando audio... {f:.0%}"),
                **dl_audio_kwargs
            )
            path = Path(local_path)
            step(0, 1.0, f"✅ Audio descargado: {yt_title}{range_info}")
        else:
            path = Path(video_input)
            if not path.exists():
                raise FileNotFoundError(f"Video no encontrado: {video_input}")
            if time_range and len(time_range) == 2 and time_range[1] > time_range[0]:
                start_s, end_s = time_range
                dur_s = end_s - start_s
                trimmed_stem = f"{path.stem}_slice_{int(start_s)}_{int(end_s)}"
                trimmed_path = settings.inputs_dir / f"{trimmed_stem}{path.suffix}"
                if not trimmed_path.exists():
                    step(0, 0.5, f"✂️ Recortando rango local ({start_s:.0f}s - {end_s:.0f}s)...")
                    import subprocess
                    subprocess.run([
                        settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{start_s:.3f}", "-t", f"{dur_s:.3f}", "-i", str(path),
                        "-c", "copy", str(trimmed_path)
                    ], check=True)
                path = trimmed_path
                step(0, 1.0, f"📁 Archivo recortado: {path.name}")
            else:
                step(0, 1.0, f"📁 Archivo local: {path.name}")

        memory_ok = self.optimizer.check_memory_safe()
        if not memory_ok:
            log_step("⚠️ Memoria del proceso alta: se reducirá el paralelismo de render a 1 clip.")

        # FASE 1: transcripción con caché
        transcripts_cache_dir = settings.cache_dir / "transcripts"
        transcripts_cache_dir.mkdir(parents=True, exist_ok=True)
        clean_stem = re.sub(r"[^\w]", "_", path.stem)
        cached_transcript_path = transcripts_cache_dir / f"{clean_stem}.json"

        step(1, 0.0, "🎙️ Transcribiendo con Faster-Whisper (INT8 CPU)...")
        transcript = None
        if use_cache and cached_transcript_path.exists():
            try:
                transcript = TranscriptResult.model_validate_json(cached_transcript_path.read_text(encoding="utf-8"))
                log_step("⚡ Transcripción cargada desde caché.")
            except Exception as e:
                logger.warning(f"Error leyendo caché de transcripción: {e}. Re-transcribiendo...")
        if transcript is None:
            transcript = self.transcriber.transcribe(str(path), language=language)
            try:
                cached_transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug(f"No se pudo guardar caché: {e}")

        db.save_video(
            video_id=video_id,
            filename=path.name,
            filepath=str(path.resolve()),
            duration=transcript.duration,
            language=transcript.language,
            source=video_input,
            transcript_path=str(cached_transcript_path),
        )
        step(1, 1.0, f"✅ Audio procesado ({transcript.duration:.1f}s, idioma '{transcript.language}').")

        # FASE 2: detección viral (0-100)
        engine_label = "heurístico" if fast else "IA (Ollama) con respaldo heurístico"
        step(2, 0.0, f"🧠 Analizando ganchos y calculando el puntaje de viralidad (motor {engine_label})...")
        self.detector.max_candidates = max_candidates
        energy = None
        try:
            energy = compute_energy_profile(str(path), settings.ffmpeg_exe)
            if energy is not None:
                log_step("🔊 Energía del audio medida: se usará para puntuar los momentos.")
        except Exception as e:  # la energía es un extra: nunca debe romper el análisis
            logger.warning(f"Sin energía de audio: {e}")
        candidates = self.detector.detect_moments(transcript, use_llm=not fast, energy=energy, focus_prompt=focus_prompt)
        # IDs únicos por video: evita que INSERT OR REPLACE pise clips de otros videos
        for cand in candidates:
            cand.id = f"{video_id}_{cand.id}"
        step(2, 1.0, f"✅ {len(candidates)} clips candidatos con títulos y copys para redes.")

        if not candidates:
            step(4, 1.0, "⚠️ No se encontraron momentos virales con la duración configurada.")
            return video_id, []

        # FASE 3: renderizado en paralelo (cortes de escena una sola vez por video)
        clip_paths = {}
        if render_clips:
            render_source = path
            step(3, 0.0, "🎬 Preparando el renderizado...")
            if is_remote:
                range_info = f" [{int(time_range[0]//60)}m-{int(time_range[1]//60)}m]" if time_range else ""
                log_step(f"⚡ Descargando video 720p{range_info} (una sola vez)...")
                dl_video_kwargs = {}
                if time_range:
                    dl_video_kwargs["time_range"] = time_range
                local_video, _ = download_youtube_video(
                    video_input,
                    progress=lambda f: step_callback and step_callback(3, f * 0.15, f"⚡ Descargando video 720p... {f:.0%}"),
                    **dl_video_kwargs
                )
                render_source = Path(local_video)
                db.update_video_filepath(video_id, str(render_source.resolve()))

            step(3, 0.2, "🔎 Analizando cortes de escena...")
            # Los cortes de escena solo sirven para ajustar clips que NO se alinearon a pausas del habla.
            # Si todos ya están alineados, se salta este paso (en videos largos tardaba más de 10 min).
            if any(not c.pause_aligned for c in candidates):
                scene_cuts = self.clip_maker.detect_scene_cuts(str(render_source))
            else:
                scene_cuts = []
                log_step("⏭️ Cortes de escena omitidos: los clips ya están alineados a pausas del habla.")

            workers = settings.render.parallel_clips if memory_ok else 1
            total = len(candidates)
            step(3, 0.25, f"🎬 Renderizando {total} clips ({workers} en paralelo)...")
            results = self.clip_maker.generate_clips_parallel(
                str(render_source),
                candidates,
                transcript.segments,
                workers=workers,
                progress=lambda done, tot, cand: step(3, 0.25 + 0.75 * (done / max(1, tot)), f"🎬 Clip {done}/{tot} listo: \"{cand.title}\""),
                with_subtitles=True,
                subtitle_style=subtitle_style,
                include_emojis=include_emojis,
                aspect_ratio=aspect_ratio,
                use_scene_detection=False,
                is_pretrimmed=False,
                scene_cuts=scene_cuts,
                subtitle_position=subtitle_position,
                custom_fontsize=custom_fontsize,
                custom_highlight=custom_highlight,
                uppercase=uppercase,
                add_watermark=add_watermark,
                watermark_text=watermark_text,
                layout_mode=layout_mode,
                speed_mode=speed_mode,
                hook_zoom=hook_zoom,
            )
            for cand in candidates:
                res = results.get(cand.id)
                if isinstance(res, Path):
                    cand.clip_path = str(res.resolve())
                    clip_paths[cand.id] = cand.clip_path
                elif isinstance(res, Exception):
                    logger.error(f"Clip {cand.id} no se pudo renderizar: {res}")
        else:
            step(3, 1.0, "⏭️ Renderizado omitido.")

        # FASE 4: persistencia
        step(4, 0.0, "💾 Guardando clips y copys...")
        db.save_candidates(video_id=video_id, candidates=candidates, clip_paths=clip_paths)
        self.optimizer.collect_garbage()
        if render_clips and not clip_paths:
            raise RuntimeError("Se detectaron momentos, pero ningún clip se pudo renderizar. Revisa FFmpeg y los logs.")
        if render_clips and len(clip_paths) < len(candidates):
            step(4, 1.0, f"⚠️ {len(clip_paths)} de {len(candidates)} clips renderizados (el resto falló).")
        else:
            step(4, 1.0, f"🎉 ¡Listo! {len(candidates)} clips generados.")

        return video_id, candidates

    def rerender_candidate(
        self,
        candidate_id: str,
        subtitle_style: str = "hormozi",
        aspect_ratio: str = "9:16",
        include_emojis: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Vuelve a renderizar un clip con los tiempos/título actuales de la base de datos."""
        cand_row = db.get_candidate(candidate_id)
        if not cand_row:
            raise ValueError(f"Clip no encontrado: {candidate_id}")
        video = db.get_video(cand_row["video_id"])
        if not video or not Path(video["filepath"]).exists():
            raise FileNotFoundError("El archivo de video original ya no está disponible.")

        segments = []
        tpath = video.get("transcript_path")
        if tpath and Path(tpath).exists():
            segments = TranscriptResult.model_validate_json(Path(tpath).read_text(encoding="utf-8")).segments

        cand = ViralMomentCandidate(
            id=cand_row["id"], start_time=cand_row["start_time"], end_time=cand_row["end_time"],
            duration=cand_row["duration"], title=cand_row.get("title") or "", hook_text=cand_row.get("hook_text") or "",
            context_text=cand_row.get("context_text") or "", virality_score=cand_row["virality_score"],
            category=cand_row.get("category") or "sorpresa", reasoning=cand_row.get("reasoning") or "",
            engine=cand_row.get("engine") or "heuristic",
            pause_aligned=True,  # el usuario eligió los tiempos: no se mueven a cortes de escena
        )
        if progress_callback:
            progress_callback("🎬 Renderizando el clip con los nuevos tiempos...")
        out = self.clip_maker.generate_clip(
            video_path=video["filepath"], candidate=cand, transcript_segments=segments,
            with_subtitles=True, subtitle_style=subtitle_style, include_emojis=include_emojis,
            aspect_ratio=aspect_ratio, use_scene_detection=False,
        )
        db.update_candidate_clip_path(candidate_id, str(out.resolve()), dirty=False)
        return out
