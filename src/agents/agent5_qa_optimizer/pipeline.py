import re
import uuid
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Callable

from src.common.config import settings
from src.common.database import db
from src.common.models import ViralMomentCandidate, TranscriptResult
from src.common.youtube_downloader import download_youtube_video, download_youtube_audio, capture_live_stream
from src.agents.agent1_transcription.transcriber import AudioTranscriber
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.agents.agent2_viral_detector.audio_energy import compute_energy_profile
from src.agents.agent2_viral_detector.chat_activity import parse_chat_messages, build_chat_profile
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
        with_subtitles: bool = True,
        subtitle_style: str = "hormozi",
        include_emojis: bool = True,
        aspect_ratio: str = "9:16",
        subtitle_position: str = "bottom",
        custom_fontsize: Optional[int] = None,
        subtitle_size: Optional[str] = None,
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
        min_clip_duration: Optional[float] = None,
        max_clip_duration: Optional[float] = None,
        progress_bar: bool = False,
        color_filter: Optional[str] = "none",
        dynamic_zoom: bool = False,
        split_glow: Optional[bool] = None,
        hook_headline: Optional[str] = None,
        broll_theme: Optional[str] = "gameplay",
        dominican_mode: bool = True,
        seamless_loop: bool = True,
        auto_broll: bool = True,
        auto_sfx: bool = True,
        sfx_intensity: str = "normal",
        broll_mode: str = "smart_face_avoid",
        broll_density: str = "medium",
        framing_mode: Optional[str] = None,
        trim_silences: bool = True,
        live_record_minutes: Optional[float] = None,
        audio_profile: str = "social",
        master_limiter: bool = True,
        target_lufs: float = -14.0,
        target_lra: float = 11.0,
        target_tp: float = -1.5,
        true_peak_limit: float = 0.84,
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
        is_live_record = bool(is_remote and live_record_minutes and live_record_minutes > 0)
        yt_title = None
        if is_live_record:
            rec_mins = float(live_record_minutes)
            rec_label = int(rec_mins) if rec_mins.is_integer() else rec_mins
            step(0, 0.0, f"🔴 Grabando {rec_label} min del directo en vivo...")
            local_path, yt_title = capture_live_stream(
                video_input,
                duration_seconds=rec_mins * 60.0,
                progress=lambda f: step_callback and step_callback(0, f, f"🔴 Grabando directo... {f:.0%}")
            )
            path = Path(local_path)
            step(0, 1.0, f"✅ Captura en vivo lista: {yt_title}")
        elif is_remote:
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
            transcript = self.transcriber.transcribe(str(path), language=language, dominican_mode=dominican_mode)
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
        if min_clip_duration is not None:
            self.detector.min_duration = float(min_clip_duration)
        if max_clip_duration is not None:
            self.detector.max_duration = float(max_clip_duration)
        energy = None
        try:
            energy = compute_energy_profile(str(path), settings.ffmpeg_exe)
            if energy is not None:
                log_step("🔊 Energía del audio medida: se usará para puntuar los momentos.")
        except Exception as e:  # la energía es un extra: nunca debe romper el análisis
            logger.warning(f"Sin energía de audio: {e}")

        chat_profile = None
        try:
            cand_chat_paths = [
                Path(path).with_suffix(".live_chat.json"),
                Path(path).with_suffix(".chat.json"),
                Path(path).with_name(f"{Path(path).stem}_chat.json"),
            ]
            for cp in cand_chat_paths:
                if cp.exists():
                    msgs = parse_chat_messages(cp)
                    if msgs:
                        chat_profile = build_chat_profile(msgs, duration=transcript.duration)
                        if chat_profile:
                            log_step(f"💬 Chat analizado ({len(msgs)} mensajes): señal de viralidad activada.")
                            break
        except Exception as e:
            logger.warning(f"Sin análisis de chat: {e}")

        candidates = self.detector.detect_moments(
            transcript, use_llm=not fast, energy=energy, layout=layout_mode,
            focus_prompt=focus_prompt, chat_profile=chat_profile,
        )
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
            if is_remote and not is_live_record:
                range_info = f" [{int(time_range[0]//60)}m-{int(time_range[1]//60)}m]" if time_range else ""
                log_step(f"⚡ Descargando video 720p{range_info} (una sola vez)...")
                dl_video_kwargs = {}
                if time_range:
                    dl_video_kwargs["time_range"] = time_range
                local_video, _ = download_youtube_video(
                    video_input,
                    progress=lambda f: step_callback and step_callback(3, f * 0.15, f"⚡ Descargando video 1080p Full HD... {f:.0%}"),
                    **dl_video_kwargs
                )
                render_source = Path(local_video)
                db.update_video_filepath(video_id, str(render_source.resolve()))
            elif is_live_record:
                render_source = path
                db.update_video_filepath(video_id, str(render_source.resolve()))

            # Los cortes de escena solo sirven para ajustar clips que NO se alinearon a pausas del habla, y solo
            # importan cerca de su inicio y fin: se analizan esas ventanas, no el video entero (antes, en un
            # video de una hora, este paso tardaba 10-40 min sin mostrar avance).
            unaligned = [c for c in candidates if not c.pause_aligned]
            if unaligned:
                step(3, 0.2, f"🔎 Buscando cortes de escena cerca de {len(unaligned)} clip(s)...")
                edges = [t for c in unaligned for t in (c.start_time, c.end_time)]
                scene_cuts = self.clip_maker.detect_scene_cuts_near(str(render_source), edges)
            else:
                scene_cuts = []
                log_step("⏭️ Cortes de escena omitidos: los clips ya están alineados a pausas del habla.")

            workers = settings.render.parallel_clips if memory_ok else 1
            total = len(candidates)
            step(3, 0.25, f"🎬 Renderizando {total} clips ({workers} en paralelo)...")
            clean_sub_style = (subtitle_style or "").lower().strip()
            eff_with_subs = bool(with_subtitles) and clean_sub_style not in ("none", "off", "sin_subtitulos", "sin_subtítulo", "sin_subtítulos", "false", "0")
            results = self.clip_maker.generate_clips_parallel(
                str(render_source),
                candidates,
                transcript.segments,
                workers=workers,
                progress=lambda done, tot, cand: step(3, 0.25 + 0.75 * (done / max(1, tot)), f"🎬 Clip {done}/{tot} listo: \"{cand.title}\""),
                with_subtitles=eff_with_subs,
                subtitle_style=subtitle_style,
                include_emojis=include_emojis,
                aspect_ratio=aspect_ratio,
                use_scene_detection=False,
                is_pretrimmed=False,
                scene_cuts=scene_cuts,
                subtitle_position=subtitle_position,
                custom_fontsize=custom_fontsize,
                subtitle_size=subtitle_size,
                custom_highlight=custom_highlight,
                uppercase=uppercase,
                add_watermark=add_watermark,
                watermark_text=watermark_text,
                layout_mode=layout_mode,
                speed_mode=speed_mode,
                hook_zoom=hook_zoom,
                progress_bar=progress_bar,
                color_filter=color_filter,
                dynamic_zoom=dynamic_zoom,
                split_glow=split_glow,
                hook_headline=hook_headline,
                broll_theme=broll_theme,
                seamless_loop=seamless_loop,
                auto_broll=auto_broll,
                auto_sfx=auto_sfx,
                sfx_intensity=sfx_intensity,
                broll_mode=broll_mode,
                broll_density=broll_density,
                trim_silences=trim_silences,
                audio_profile=audio_profile,
                master_limiter=master_limiter,
                target_lufs=target_lufs,
                target_lra=target_lra,
                target_tp=target_tp,
                true_peak_limit=true_peak_limit,
            )
            for cand in candidates:
                res = results.get(cand.id)
                if isinstance(res, Path):
                    cand.clip_path = str(res.resolve())
                    clip_paths[cand.id] = cand.clip_path
                    # Clip limpio sin miniatura automática impuesta
                    logger.debug(f"Clip renderizado en alta calidad: {res}")
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
        with_subtitles: bool = True,
        subtitle_style: str = "hormozi",
        aspect_ratio: str = "9:16",
        include_emojis: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
        subtitle_position: str = "bottom",
        custom_fontsize: Optional[int] = None,
        subtitle_size: Optional[str] = None,
        custom_highlight: Optional[str] = None,
        progress_bar: bool = False,
        color_filter: Optional[str] = "none",
        dynamic_zoom: bool = False,
        punch_zooms: bool = False,
        split_glow: Optional[bool] = None,
        hook_headline: Optional[str] = None,
        broll_theme: Optional[str] = "gameplay",
        seamless_loop: bool = True,
        auto_broll: bool = True,
        auto_sfx: bool = True,
        sfx_intensity: str = "normal",
        broll_mode: str = "smart_face_avoid",
        broll_density: str = "medium",
        framing_mode: Optional[str] = None,
        trim_silences: bool = True,
        audio_profile: str = "social",
        master_limiter: bool = True,
        **kwargs,
    ) -> Path:
        """Vuelve a renderizar un clip con los tiempos/título actuales de la base de datos."""
        cand_row = db.get_candidate(candidate_id)
        if not cand_row:
            raise ValueError(f"Clip no encontrado: {candidate_id}")
        video = db.get_video(cand_row["video_id"])
        if not video or not Path(video["filepath"]).exists():
            raise FileNotFoundError("El archivo de video original ya no está disponible.")

        segments = []
        custom_tpath = settings.cache_dir / "transcripts" / f"{candidate_id}_edited.json"
        if custom_tpath.is_file():
            try:
                segments = TranscriptResult.model_validate_json(custom_tpath.read_text(encoding="utf-8")).segments
                logger.info(f"Usando transcripción personalizada editada para clip {candidate_id}")
            except Exception as e:
                logger.warning(f"Error leyendo transcripción personalizada: {e}")
        if not segments:
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
        layout_mode = framing_mode if framing_mode else None
        clean_sub_style = (subtitle_style or "").lower().strip()
        eff_with_subs = bool(with_subtitles) and clean_sub_style not in ("none", "off", "sin_subtitulos", "sin_subtítulo", "sin_subtítulos", "false", "0")
        out = self.clip_maker.generate_clip(
            video_path=video["filepath"], candidate=cand, transcript_segments=segments,
            with_subtitles=eff_with_subs, subtitle_style=subtitle_style, include_emojis=include_emojis,
            aspect_ratio=aspect_ratio, use_scene_detection=False,
            subtitle_position=subtitle_position, custom_fontsize=custom_fontsize,
            subtitle_size=subtitle_size, custom_highlight=custom_highlight,
            progress_bar=progress_bar, color_filter=color_filter,
            dynamic_zoom=dynamic_zoom,
            punch_zooms=punch_zooms, split_glow=split_glow,
            hook_headline=hook_headline, broll_theme=broll_theme,
            seamless_loop=seamless_loop, auto_broll=auto_broll, trim_silences=trim_silences,
            layout_mode=layout_mode,
            auto_sfx=auto_sfx,
            sfx_intensity=sfx_intensity,
            broll_mode=broll_mode,
            broll_density=broll_density,
            audio_profile=audio_profile,
            master_limiter=master_limiter,
        )
        db.update_candidate_clip_path(candidate_id, str(out.resolve()), dirty=False)
        # Clip limpio sin miniatura automática impuesta
        logger.debug(f"Clip re-renderizado en alta calidad: {out}")
        return out
