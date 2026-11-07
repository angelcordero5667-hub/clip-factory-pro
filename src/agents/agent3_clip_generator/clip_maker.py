import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.common.config import settings
from src.common.models import ViralMomentCandidate, TranscriptSegment
from src.agents.agent3_clip_generator.subtitles import SubtitleGenerator, FONTS_DIR
from src.agents.agent3_clip_generator.face_tracker import FaceTracker
from src.agents.agent3_clip_generator.framing import Framing, choose_framing
from src.agents.agent3_clip_generator.trimming import (
    build_keep_ranges, kept_duration, remap_segments, select_expr,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Agent3_ClipMaker")

@lru_cache(maxsize=1)
def available_encoders() -> frozenset:
    """Encoders de video que expone el FFmpeg local (`ffmpeg -encoders`)."""
    try:
        out = subprocess.run([settings.ffmpeg_exe, "-hide_banner", "-encoders"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=20).stdout
    except Exception:
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.add(parts[1])
    return frozenset(names)


def pick_encoder() -> str:
    """h264_amf si existe y está habilitado en config; si no, libx264."""
    if settings.render.use_hw_encoder and "h264_amf" in available_encoders():
        return "h264_amf"
    return "libx264"

class VerticalClipMaker:
    """
    Agente 3: Motor de Generación de Clips Verticales estilo OpusClip.
    - Detección de cortes de escena naturales (PySceneDetect).
    - Auto-Encuadre Facial (Face Detection con OpenCV) para centrar al hablante.
    - Renderizado 1080x1920 con fondo desenfocado inteligente.
    - Subtítulos dinámicos con Emojis automáticos estilo Hormozi/MrBeast.
    - Garantía absoluta de no sobreescritura.
    """

    def __init__(
        self,
        target_width: int = 1080,
        target_height: int = 1920,
        threads: Optional[int] = None
    ):
        self.target_width = target_width
        self.target_height = target_height
        self.threads = threads or settings.render.threads_per_clip
        self.subtitle_generator = SubtitleGenerator()
        
        self.face_tracker = FaceTracker()

    def detect_scene_cuts(self, video_path: str) -> List[float]:
        cuts = []
        try:
            from scenedetect import open_video, SceneManager, ContentDetector
            video = open_video(video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
            scene_manager.detect_scenes(video, frame_skip=4, show_progress=False)
            scene_list = scene_manager.get_scene_list()

            for scene in scene_list:
                cuts.append(round(scene[0].get_seconds(), 2))
                cuts.append(round(scene[1].get_seconds(), 2))
            cuts = sorted(list(set(cuts)))
        except Exception as e:
            logger.debug(f"Scene detection fallback: {e}")
        return cuts

    def snap_to_natural_boundary(self, time_point: float, scene_cuts: List[float], tolerance: float = 1.5) -> float:
        for cut in scene_cuts:
            if abs(cut - time_point) <= tolerance:
                return cut
        return time_point

    def get_unique_output_path(self, base_name: str, candidate_id: str) -> Path:
        clean_name = Path(base_name).stem.replace(" ", "_")
        idx = 1
        output_dir = settings.outputs_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        candidate_file = output_dir / f"{clean_name}_{candidate_id}_v{idx}.mp4"
        while candidate_file.exists():
            idx += 1
            candidate_file = output_dir / f"{clean_name}_{candidate_id}_v{idx}.mp4"

        return candidate_file

    # ------------------------------------------------------------------
    # Construcción del comando FFmpeg (separada para poder probarla sin renderizar)
    # ------------------------------------------------------------------
    @staticmethod
    def output_size(aspect_ratio: str) -> Tuple[int, int]:
        if aspect_ratio == "1:1":
            return 1080, 1080
        if aspect_ratio == "16:9":
            return 1920, 1080
        return 1080, 1920  # 9:16 por defecto

    @staticmethod
    def _escape_filter_path(path) -> str:
        """Ruta de Windows apta para un filtro de FFmpeg entre comillas simples (C:\\x -> C\\:/x)."""
        return str(Path(path).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    def build_filter_complex(
        self, w: int, h: int, ass_path: Optional[Path] = None, framing: Optional[Framing] = None,
        cut_expr: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Construye el filtro según el layout. Devuelve (filtro, etiqueta_final).

        - blur (por defecto): fondo desenfocado a 1/4 de resolución (270x480 en 9:16) reescalado.
        - crop: recorte centrado en el hablante con x dinámica (expresión en `t`).
        - split: 2 hablantes, mitad superior e inferior (solo vertical).
        """
        framing = framing or Framing()
        if framing.mode == "crop" and framing.crop_w > 0:
            parts = [f"[0:v]crop=w={framing.crop_w}:h=ih:x='{framing.x_expr}':y=0,"
                     f"scale={w}:{h}:flags=bicubic[combined]"]
        elif framing.mode == "split" and framing.crop_w > 0:
            half = h // 2
            xa, xb = framing.split_xs
            parts = [
                "[0:v]split=2[sp_a][sp_b];",
                f"[sp_a]crop=w={framing.crop_w}:h=ih:x={xa}:y=0,scale={w}:{half}:flags=bicubic[sp_top];",
                f"[sp_b]crop=w={framing.crop_w}:h=ih:x={xb}:y=0,scale={w}:{half}:flags=bicubic[sp_bot];",
                "[sp_top][sp_bot]vstack=inputs=2[combined]",
            ]
        elif framing.mode == "gaming":
            top_h = int(h * 0.38) // 2 * 2
            bot_h = h - top_h
            cw = framing.crop_w if framing.crop_w > 0 else int(w * 0.8)
            cx = framing.split_xs[0] if framing.split_xs else 0
            parts = [
                "[0:v]split=2[cam_src][game_src];",
                f"[cam_src]crop=w={cw}:h=ih:x={cx}:y=0,scale={w}:{top_h}:flags=bicubic[cam_top];",
                f"[game_src]scale=-1:{bot_h}:flags=bicubic,crop={w}:{bot_h}:(iw-{w})/2:0[game_bot];",
                "[cam_top][game_bot]vstack=inputs=2[combined]",
            ]
        else:
            div = max(1, settings.render.bg_scale_div)
            bw, bh = max(2, (w // div) // 2 * 2), max(2, (h // div) // 2 * 2)
            parts = [
                "[0:v]split=2[v_bg][v_fg];",
                f"[v_bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},boxblur=8:2,scale={w}:{h}[bg_blur];",
                f"[v_fg]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg_scaled];",
                "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[combined]",
            ]
        label = "[combined]"
        if cut_expr:
            # El encuadre ya se aplicó sobre la línea de tiempo original; ahora se quitan las pausas
            # y se cierran los huecos. Los subtítulos (ya re-sincronizados) se queman después.
            parts.append(f";{label}select='{cut_expr}',setpts=N/FRAME_RATE/TB[v_cut]")
            label = "[v_cut]"
        if ass_path and Path(ass_path).exists():
            escaped_ass = self._escape_filter_path(ass_path)
            fonts_opt = ""
            if FONTS_DIR.exists():
                # fontsdir: libass usa las fuentes empaquetadas, sin depender del Windows del usuario
                fonts_opt = f":fontsdir='{self._escape_filter_path(FONTS_DIR)}'"
            parts.append(f";{label}subtitles='{escaped_ass}'{fonts_opt}[v_subbed]")
            label = "[v_subbed]"
        return "".join(parts), label

    @staticmethod
    def video_codec_args(encoder: str) -> List[str]:
        r = settings.render
        if encoder == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp",
                    "-qp_i", str(r.crf), "-qp_p", str(r.crf + 2), "-qp_b", str(r.crf + 2),
                    "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx264", "-preset", r.preset, "-crf", str(r.crf), "-pix_fmt", "yuv420p"]

    def build_ffmpeg_cmd(
        self,
        input_path: Path,
        output_file: Path,
        start_time: float,
        duration: float,
        filter_str: str,
        final_label: str,
        encoder: str = "libx264",
        is_pretrimmed: bool = False,
        normalize_audio: bool = True,
        cut_expr: Optional[str] = None,
    ) -> List[str]:
        seek_arg = ["-ss", "0.0"] if is_pretrimmed else ["-ss", f"{start_time:.3f}"]
        af_parts = []
        if cut_expr:
            af_parts.append(f"aselect='{cut_expr}',asetpts=N/SR/TB")
        if normalize_audio:
            af_parts.append("loudnorm=I=-14:LRA=7:TP=-1")
        audio_filter = ["-af", ",".join(af_parts)] if af_parts else []
        return [
            settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
            *seek_arg,
            "-t", f"{duration:.3f}",
            "-i", str(Path(input_path).resolve()),
            "-filter_complex", filter_str,
            "-map", final_label,
            "-map", "0:a?",
            *audio_filter,
            *self.video_codec_args(encoder),
            "-c:a", "aac", "-b:a", "160k",
            "-threads", str(settings.render.threads_per_clip),
            "-movflags", "+faststart",
            str(Path(output_file).resolve()),
        ]

    def _run_ffmpeg(self, cmd_for: "callable") -> None:
        """Ejecuta FFmpeg con el mejor encoder; si falla el acelerado por hardware, reintenta con libx264."""
        encoder = pick_encoder()
        result = subprocess.run(cmd_for(encoder), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0 and encoder != "libx264":
            logger.warning(f"{encoder} falló; reintentando con libx264. Detalle: {result.stderr[-200:]}")
            result = subprocess.run(cmd_for("libx264"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"Error renderizando clip en FFmpeg:\n{result.stderr[-800:]}")
            raise RuntimeError(f"FFmpeg falló al generar el clip: {result.stderr[-300:]}")

    def generate_clip(
        self,
        video_path: str,
        candidate: ViralMomentCandidate,
        transcript_segments: List[TranscriptSegment],
        with_subtitles: bool = True,
        subtitle_style: str = "hormozi",
        include_emojis: bool = True,
        aspect_ratio: str = "9:16",
        use_scene_detection: bool = True,
        is_pretrimmed: bool = False,
        subtitle_position: str = "bottom",
        custom_fontsize: Optional[int] = None,
        custom_highlight: Optional[str] = None,
        uppercase: Optional[bool] = None,   # None = lo define el estilo
        add_watermark: bool = False,
        scene_cuts: Optional[List[float]] = None,
        smart_framing: Optional[bool] = None,
        trim_silences: Optional[bool] = None,
        layout_mode: Optional[str] = None,
    ) -> Path:
        input_p = Path(video_path)
        if not input_p.exists():
            raise FileNotFoundError(f"Video original no encontrado: {video_path}")

        start_time = candidate.start_time
        end_time = candidate.end_time

        # Los cortes de escena se calculan UNA vez por video (pipeline) y se reutilizan aquí.
        if not is_pretrimmed:
            if scene_cuts is None and use_scene_detection:
                scene_cuts = self.detect_scene_cuts(str(input_p))
            # Si ya se alineó a pausas del habla, no se vuelve a mover a un corte de escena
            # (podría cortar a mitad de frase).
            if scene_cuts and not candidate.pause_aligned:
                start_time = self.snap_to_natural_boundary(start_time, scene_cuts, tolerance=1.2)
                end_time = self.snap_to_natural_boundary(end_time, scene_cuts, tolerance=1.5)

        duration = max(5.0, end_time - start_time)
        output_file = self.get_unique_output_path(input_p.name, candidate.id)
        w, h = self.output_size(aspect_ratio)

        # Recorte de pausas largas y muletillas (necesita timestamps por palabra)
        if trim_silences is None:
            trim_silences = settings.render.trim_silences
        keep_ranges = []
        sub_segments, sub_start, sub_end = transcript_segments, start_time, end_time
        if trim_silences and transcript_segments:
            all_words = [w for s in transcript_segments for w in s.words]
            keep_ranges = build_keep_ranges(all_words, start_time, end_time)
            if keep_ranges:
                new_total = kept_duration(keep_ranges)
                logger.info(f"Recorte de pausas en {candidate.id}: {end_time - start_time:.1f}s -> {new_total:.1f}s")
                sub_segments = remap_segments(transcript_segments, keep_ranges)
                sub_start, sub_end = 0.0, new_total
        cut_expr = select_expr(keep_ranges, start_time) if keep_ranges else None

        actual_sub_pos = "middle" if (layout_mode == "gaming" and subtitle_position == "bottom") else subtitle_position

        ass_path = None
        if with_subtitles and sub_segments:
            ass_path = settings.cache_dir / f"{candidate.id}_subtitles.ass"
            self.subtitle_generator.generate_ass(
                clip_start=sub_start,
                clip_end=sub_end,
                segments=sub_segments,
                output_path=ass_path,
                style_preset=subtitle_style,
                include_emojis=include_emojis,
                position=actual_sub_pos,
                custom_fontsize=custom_fontsize,
                custom_highlight=custom_highlight,
                uppercase=uppercase,
                add_watermark=add_watermark,
                aspect_ratio=aspect_ratio,
            )

        framing = Framing()
        if layout_mode == "blur":
            framing = Framing(mode="blur", reason="layout desenfoque solicitado")
        else:
            if smart_framing is None:
                smart_framing = settings.render.smart_framing
            if (smart_framing or layout_mode == "gaming") and self.face_tracker.available:
                seek_for_face = 0.0 if is_pretrimmed else start_time
                samples, src_w, src_h = self.face_tracker.sample(str(input_p), seek_for_face, duration)
                framing = choose_framing(samples, src_w, src_h, w, h, allow_split=(aspect_ratio == "9:16"), layout_mode=layout_mode)
                logger.info(f"Encuadre de {candidate.id}: {framing.mode} ({framing.reason})")
            elif layout_mode == "gaming":
                framing = choose_framing([], 1920, 1080, w, h, allow_split=False, layout_mode="gaming")

        filter_str, final_label = self.build_filter_complex(w, h, ass_path, framing, cut_expr=cut_expr)

        logger.info(f"Renderizando clip {aspect_ratio}: {output_file.name} ({duration:.1f}s)")
        self._run_ffmpeg(lambda enc: self.build_ffmpeg_cmd(
            input_p, output_file, start_time, duration, filter_str, final_label,
            encoder=enc, is_pretrimmed=is_pretrimmed, cut_expr=cut_expr,
        ))
        self.make_thumbnail(output_file)
        logger.info(f"Clip generado: {output_file}")
        return output_file

    @staticmethod
    def make_thumbnail(video_file: Path, width: int = 540) -> Optional[Path]:
        """Miniatura JPG real junto al clip (mismo nombre, extensión .jpg). No falla el render si no se puede."""
        thumb = Path(video_file).with_suffix(".jpg")
        try:
            subprocess.run(
                [settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.0",
                 "-i", str(Path(video_file).resolve()), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", "-q:v", "4", str(thumb.resolve())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except Exception as e:
            logger.debug(f"No se pudo crear la miniatura: {e}")
            return None
        return thumb if thumb.exists() else None

    def generate_clips_parallel(
        self,
        video_path: str,
        candidates: List[ViralMomentCandidate],
        transcript_segments: List[TranscriptSegment],
        workers: Optional[int] = None,
        progress: Optional[Callable[[int, int, ViralMomentCandidate], None]] = None,
        **options,
    ) -> Dict[str, object]:
        """Renderiza varios clips en paralelo. Devuelve {candidate_id: Path | Exception}.

        Los cortes de escena se calculan una sola vez para todo el video.
        """
        workers = max(1, workers or settings.render.parallel_clips)
        scene_cuts = options.pop("scene_cuts", None)
        if scene_cuts is None and options.get("use_scene_detection", True) and not options.get("is_pretrimmed", False):
            scene_cuts = self.detect_scene_cuts(str(video_path))

        results: Dict[str, object] = {}

        def work(cand: ViralMomentCandidate):
            return self.generate_clip(
                video_path, cand, transcript_segments, scene_cuts=scene_cuts, **options
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, c): c for c in candidates}
            done = 0
            for fut in as_completed(futures):
                cand = futures[fut]
                done += 1
                try:
                    results[cand.id] = fut.result()
                except Exception as e:  # un clip fallido no cancela los demás
                    logger.error(f"Error renderizando candidato {cand.id}: {e}")
                    results[cand.id] = e
                if progress:
                    try:
                        progress(done, len(candidates), cand)
                    except BaseException:
                        # El callback pidió parar (p. ej. el usuario canceló el trabajo): no se
                        # empiezan los clips pendientes; solo terminan los que ya están en marcha.
                        for pending in futures:
                            pending.cancel()
                        raise
        return results

