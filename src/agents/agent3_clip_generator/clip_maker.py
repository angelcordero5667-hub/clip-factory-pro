import re
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.common.config import settings
from src.common.models import ViralMomentCandidate, TranscriptSegment
from src.agents.agent3_clip_generator.smart_broll import SmartBrollEngine, BrollItem, load_clip_broll, save_clip_broll
from src.agents.agent3_clip_generator.smart_sfx import SmartSFXEngine, SFXItem, load_clip_sfx, save_clip_sfx
from src.agents.agent3_clip_generator.subtitles import SubtitleGenerator, FONTS_DIR
from src.agents.agent3_clip_generator.face_tracker import FaceTracker
from src.common.viral_enhancements import (
    build_audio_filter_chain,
    detect_contextual_sticker,
    get_sfx_path,
)
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
        self.broll_engine = SmartBrollEngine()
        self.sfx_engine = SmartSFXEngine()

    def detect_scene_cuts(self, video_path: str, frame_skip: int = 8) -> List[float]:
        cuts = []
        try:
            from scenedetect import open_video, SceneManager, ContentDetector
            video = open_video(video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
            scene_manager.detect_scenes(video, frame_skip=frame_skip, show_progress=False)
            scene_list = scene_manager.get_scene_list()

            for scene in scene_list:
                cuts.append(round(scene[0].get_seconds(), 2))
                cuts.append(round(scene[1].get_seconds(), 2))
            cuts = sorted(list(set(cuts)))
        except Exception as e:
            logger.debug(f"Scene detection fallback: {e}")
        return cuts

    def detect_scene_cuts_near(self, video_path: str, times: List[float], margin: float = 2.5,
                               threshold: float = 0.3, timeout: int = 90) -> List[float]:
        """Cortes de escena SOLO alrededor de `times` (±margin s), sin recorrer el video entero.

        El ajuste a cortes (snap_to_natural_boundary) solo mira ±1.2-1.5 s del inicio/fin de cada clip,
        así que basta analizar esas ventanas: en un video de una hora pasa de decenas de minutos a segundos.
        Usa el filtro `scene` de FFmpeg con búsqueda directa (-ss antes de -i). Si algo falla devuelve [].
        """
        cuts = set()
        for t in sorted({round(float(x), 1) for x in times if x is not None}):
            t0 = max(0.0, t - margin)
            cmd = [
                settings.ffmpeg_exe, "-hide_banner", "-nostats", "-ss", f"{t0:.3f}", "-t", f"{2 * margin:.3f}",
                "-i", str(video_path), "-an", "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-",
            ]
            try:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                      timeout=timeout)
            except Exception as e:
                logger.debug(f"Cortes de escena cerca de {t:.1f}s: {e}")
                continue
            for m in re.finditer(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)", proc.stderr or ""):
                cuts.add(round(t0 + float(m.group(1)), 2))
        return sorted(cuts)

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
        if aspect_ratio == "4:5":
            return 1080, 1350
        return 1080, 1920  # 9:16 por defecto

    @staticmethod
    def _escape_filter_path(path) -> str:
        """Ruta de Windows apta para un filtro de FFmpeg entre comillas simples (C:\\x -> C\\:/x)."""
        return str(Path(path).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    def build_filter_complex(
        self, w: int, h: int, ass_path: Optional[Path] = None, framing: Optional[Framing] = None,
        cut_expr: Optional[str] = None, hook_zoom: bool = False,
        progress_bar: bool = False, clip_duration: float = 30.0,
        color_filter: Optional[str] = None, dynamic_zoom: bool = False,
        punch_zooms: bool = False,
        split_glow: bool = False, broll_theme: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Construye el filtro según el layout. Devuelve (filtro, etiqueta_final).

        - blur (por defecto): fondo desenfocado a 1/4 de resolución (270x480 en 9:16) reescalado.
        - crop: recorte centrado en el hablante con x dinámica (expresión en `t`).
        - split: 2 hablantes, mitad superior e inferior (solo vertical).
        - hook_zoom: punch-in sutil (1.08x) durante los primeros 2.5s para atrapar la mirada en TikTok/Reels.
        """
        framing = framing or Framing()
        if framing.mode == "crop" and framing.crop_w > 0:
            parts = [f"[0:v]crop=w={framing.crop_w}:h=ih:x='{framing.x_expr}':y=0,"
                     f"scale={w}:{h}:flags=lanczos+accurate_rnd[combined]"]
        elif framing.mode == "split" and framing.crop_w > 0:
            half = h // 2
            xa, xb = framing.split_xs
            parts = [
                "[0:v]split=2[sp_a][sp_b];",
                f"[sp_a]crop=w={framing.crop_w}:h=ih:x={xa}:y=0,scale={w}:{half}:flags=lanczos+accurate_rnd[sp_top];",
                f"[sp_b]crop=w={framing.crop_w}:h=ih:x={xb}:y=0,scale={w}:{half}:flags=lanczos+accurate_rnd[sp_bot];",
                "[sp_top][sp_bot]vstack=inputs=2[combined]",
            ]
            if split_glow:
                parts.append(
                    f";[combined]drawbox=x=0:y={half-4}:w=iw:h=8:color=0xa855f7@0.45:t=fill,"
                    f"drawbox=x=0:y={half-2}:w=iw:h=4:color=white@0.95:t=fill[sp_glow]"
                )
        elif framing.mode == "gaming":
            top_h = int(h * 0.38) // 2 * 2
            bot_h = h - top_h
            cw = framing.crop_w if framing.crop_w > 0 else int(w * 0.8)
            cx = framing.split_xs[0] if framing.split_xs else 0
            parts = [
                "[0:v]split=2[cam_src][game_src];",
                f"[cam_src]crop=w={cw}:h=ih:x={cx}:y=0,scale={w}:{top_h}:flags=lanczos+accurate_rnd[cam_top];",
                f"[game_src]scale=-1:{bot_h}:flags=lanczos+accurate_rnd,crop={w}:{bot_h}:(iw-{w})/2:0[game_bot];",
                "[cam_top][game_bot]vstack=inputs=2[combined]",
            ]
        elif framing.mode == "broll":
            top_h = int(h * 0.50) // 2 * 2
            bot_h = h - top_h
            cw = framing.crop_w if framing.crop_w > 0 else int(w * 0.8)
            cx = framing.split_xs[0] if framing.split_xs else 0
            broll_dir = settings.base_dir / "data" / "broll"
            broll_files = []
            if broll_dir.exists():
                all_vids = [f for f in broll_dir.iterdir() if f.is_file() and f.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]
                if broll_theme and broll_theme not in ("auto", "none"):
                    theme_matches = [f for f in all_vids if broll_theme.lower() in f.stem.lower()]
                    broll_files = theme_matches if theme_matches else all_vids
                else:
                    broll_files = all_vids
            if broll_files:
                broll_path = self._escape_filter_path(broll_files[0])
                parts = [
                    f"[0:v]crop=w={cw}:h=ih:x={cx}:y=0,scale={w}:{top_h}:flags=lanczos+accurate_rnd[cam_top];",
                    f"movie='{broll_path}':loop=0[broll_raw];",
                    f"[broll_raw]scale=-1:{bot_h}:flags=lanczos+accurate_rnd,crop={w}:{bot_h}:(iw-{w})/2:0[broll_bot];",
                    "[cam_top][broll_bot]vstack=inputs=2[combined]",
                ]
            else:
                parts = [
                    f"[0:v]crop=w={cw}:h=ih:x={cx}:y=0,scale={w}:{top_h}:flags=lanczos+accurate_rnd[cam_top];",
                    f"mandelbrot=s={w}x{bot_h}:r=30,format=yuv420p[broll_bot];",
                    "[cam_top][broll_bot]vstack=inputs=2[combined]",
                ]
        else:
            div = max(1, settings.render.bg_scale_div)
            bw, bh = max(2, (w // div) // 2 * 2), max(2, (h // div) // 2 * 2)
            parts = [
                "[0:v]split=2[v_bg][v_fg];",
                f"[v_bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},boxblur=8:2,scale={w}:{h}[bg_blur];",
                f"[v_fg]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos+accurate_rnd[fg_scaled];",
                "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[combined]",
            ]
        label = "[sp_glow]" if (framing.mode == "split" and split_glow) else "[combined]"
        if hook_zoom:
            parts.append(
                f";{label}split=2[v_base][v_hook];"
                f"[v_hook]crop=w=iw/1.08:h=ih/1.08,scale={w}:{h}:flags=lanczos+accurate_rnd[v_punch];"
                f"[v_base][v_punch]overlay=x=0:y=0:enable='between(t,0,2.5)'[v_hooked]"
            )
            label = "[v_hooked]"
        if dynamic_zoom:
            parts.append(
                f";{label}crop=w='if(between(mod(t,12),0,2.2),iw/1.12,iw)':"
                f"h='if(between(mod(t,12),0,2.2),ih/1.12,ih)':"
                f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
                f"scale={w}:{h}:flags=lanczos+accurate_rnd[v_dynzoom]"
            )
            label = "[v_dynzoom]"
        if punch_zooms:
            parts.append(
                f";{label}crop=w='if(between(mod(t,7.5),0,0.85),iw/1.14,iw)':"
                f"h='if(between(mod(t,7.5),0,0.85),ih/1.14,ih)':"
                f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',"
                f"scale={w}:{h}:flags=lanczos+accurate_rnd[v_pzooms]"
            )
            label = "[v_pzooms]"
        if color_filter and color_filter not in ("none", "natural", ""):
            cf = color_filter.lower().strip()
            cf_node = None
            if cf == "pop":
                cf_node = "eq=contrast=1.12:saturation=1.28:brightness=0.02"
            elif cf == "cinema":
                cf_node = "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rh=-0.05:gh=0.02:bh=0.08"
            elif cf == "vignette":
                cf_node = "vignette=angle=PI/5"
            elif cf == "warm":
                cf_node = "colorbalance=rs=0.09:gs=0.03:bs=-0.06"
            if cf_node:
                parts.append(f";{label}{cf_node}[v_color]")
                label = "[v_color]"
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
        if progress_bar:
            bar_h = 8 if h >= 1080 else 5
            cdur = max(0.5, float(clip_duration))
            parts.append(
                f";{label}drawbox=x=0:y=ih-{bar_h}:w=iw:h={bar_h}:color=white@0.22:t=fill,"
                f"drawbox=x=0:y=ih-{bar_h}:w='iw*min(1,t/{cdur:.3f})':h={bar_h}:color=0xa855f7@0.95:t=fill[v_prog]"
            )
            label = "[v_prog]"
        return "".join(parts), label

    @staticmethod
    def video_codec_args(encoder: str, speed_mode: Optional[str] = None) -> List[str]:
        r = settings.render
        mode = speed_mode or r.speed_mode
        if mode == "studio":
            preset = "slow"
            crf_val = min(17, r.crf)
        elif mode == "turbo":
            preset = "fast"
            crf_val = min(19, r.crf)
        else:
            preset = "medium"
            crf_val = r.crf  # 18 por defecto para calidad nítida sin pérdida visible

        if encoder == "h264_amf":
            # AMD AMF con máxima calidad visual: preset quality, perfil High, CQP ajustado y bitrate alto
            return [
                "-c:v", "h264_amf",
                "-usage", "high_quality",
                "-quality", "quality",
                "-profile:v", "high",
                "-rc", "cqp",
                "-qp_i", str(crf_val),
                "-qp_p", str(crf_val + 1),
                "-qp_b", str(crf_val + 2),
                "-maxrate", "20M",
                "-bufsize", "25M",
                "-pix_fmt", "yuv420p"
            ]
        return [
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf_val),
            "-profile:v", "high",
            "-level", "4.2",
            "-pix_fmt", "yuv420p"
        ]

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
        speed_mode: Optional[str] = None,
        seamless_loop: bool = False,
        sfx_items: Optional[List[Any]] = None,
        audio_profile: str = "social",
        target_lufs: float = -14.0,
        target_lra: float = 11.0,
        target_tp: float = -1.5,
        master_limiter: bool = True,
        true_peak_limit: float = 0.79,
    ) -> List[str]:
        seek_arg = ["-ss", "0.0"] if is_pretrimmed else ["-ss", f"{start_time:.3f}"]
        af_parts = build_audio_filter_chain(
            duration=duration,
            normalize_audio=normalize_audio,
            seamless_loop=seamless_loop,
            cut_expr=cut_expr,
            audio_profile=audio_profile,
            target_lufs=target_lufs,
            target_lra=target_lra,
            target_tp=target_tp,
            master_limiter=master_limiter,
            true_peak_limit=true_peak_limit,
        )
        audio_filter = ["-af", ",".join(af_parts)] if af_parts else []

        extra_inputs: List[str] = []
        extra_filter_complex = filter_str
        final_audio_map = "0:a?"

        active_sfx = [it for it in (sfx_items or []) if getattr(it, "enabled", True) and Path(getattr(it, "sfx_path", "")).exists()]
        if active_sfx:
            sfx_labels = []
            audio_filter_complex_parts = []
            for idx, item in enumerate(active_sfx):
                extra_inputs.extend(["-i", str(Path(item.sfx_path).resolve())])
                ms = max(0, int(item.time * 1000.0))
                vol = max(0.05, min(0.9, getattr(item, "volume", 0.30)))
                node = f"sfx_{idx}"
                in_idx = idx + 1
                audio_filter_complex_parts.append(f"[{in_idx}:a]adelay={ms}|{ms},volume={vol:.2f}[{node}]")
                sfx_labels.append(f"[{node}]")
            mix_label = "[a_sfx_mix]"
            # Preserva la voz original con peso 1.0; micro-SFX subordinados a la voz (peso 0.70)
            sfx_weights = "1.0 " + " ".join(["0.70"] * len(sfx_labels))
            audio_filter_complex_parts.append(
                f"[0:a]{''.join(sfx_labels)}amix=inputs={len(sfx_labels)+1}:duration=first:dropout_transition=2:weights='{sfx_weights}'{mix_label}"
            )
            if af_parts:
                post_mix = f"{mix_label}{','.join(af_parts)}[a_final]"
                audio_filter_complex_parts.append(post_mix)
                final_audio_map = "[a_final]"
            else:
                final_audio_map = mix_label
            extra_filter_complex = filter_str + ";" + ";".join(audio_filter_complex_parts)
            audio_filter = []

        return [
            settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
            *seek_arg,
            "-t", f"{duration:.3f}",
            "-i", str(Path(input_path).resolve()),
            *extra_inputs,
            "-filter_complex", extra_filter_complex,
            "-map", final_label,
            "-map", final_audio_map,
            *audio_filter,
            *self.video_codec_args(encoder, speed_mode=speed_mode),
            "-c:a", "aac", "-b:a", "256k",
            "-threads", str(settings.render.threads_per_clip),
            "-movflags", "+faststart",
            "-t", f"{duration:.3f}",
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
        watermark_text: Optional[str] = None,
        scene_cuts: Optional[List[float]] = None,
        smart_framing: Optional[bool] = None,
        trim_silences: Optional[bool] = None,
        layout_mode: Optional[str] = None,
        speed_mode: Optional[str] = None,
        hook_zoom: Optional[bool] = None,
        subtitle_size: Optional[str] = None,
        progress_bar: Optional[bool] = None,
        color_filter: Optional[str] = None,
        dynamic_zoom: Optional[bool] = None,
        punch_zooms: Optional[bool] = None,
        split_glow: Optional[bool] = None,
        hook_headline: Optional[str] = None,
        broll_theme: Optional[str] = None,
        seamless_loop: bool = True,
        auto_broll: bool = True,
        auto_sfx: bool = True,
        sfx_intensity: str = "normal",
        sfx_categories: Optional[List[str]] = None,
        broll_mode: str = "smart_face_avoid",
        broll_density: str = "medium",
        broll_items: Optional[List[Any]] = None,
        sfx_items: Optional[List[Any]] = None,
        audio_profile: str = "social",
        target_lufs: float = -14.0,
        target_lra: float = 11.0,
        target_tp: float = -1.5,
        master_limiter: bool = True,
        true_peak_limit: float = 0.79,
    ) -> Path:
        input_p = Path(video_path)
        if not input_p.exists():
            raise FileNotFoundError(f"Video original no encontrado: {video_path}")

        start_time = candidate.start_time
        end_time = candidate.end_time

        # Los cortes de escena se calculan UNA vez por video (pipeline) y se reutilizan aquí.
        if not is_pretrimmed:
            if scene_cuts is None and use_scene_detection:
                # Detección ultra-rápida local (solo analiza ±2.5s alrededor del inicio/fin del clip)
                scene_cuts = self.detect_scene_cuts_near(str(input_p), [start_time, end_time], margin=2.5)
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

        actual_sub_pos = "middle" if (layout_mode in ("gaming", "broll") and subtitle_position in ("bottom", "bottom_low", "lower")) else subtitle_position

        headline_text = None
        if isinstance(hook_headline, str) and hook_headline.strip():
            headline_text = hook_headline.strip()
        elif hook_headline is True:
            headline_text = getattr(candidate, "headline", None) or getattr(candidate, "title", None) or getattr(candidate, "hook_text", None)

        ass_path = None
        clean_sub_style = (subtitle_style or "").lower().strip()
        subtitles_enabled = bool(with_subtitles) and clean_sub_style not in ("none", "off", "sin_subtitulos", "sin_subtítulo", "sin_subtítulos", "false", "0")
        if subtitles_enabled and sub_segments:
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
                watermark_text=watermark_text,
                aspect_ratio=aspect_ratio,
                subtitle_size=subtitle_size,
                hook_headline=headline_text,
            )

        framing = Framing()
        if layout_mode == "blur":
            framing = Framing(mode="blur", reason="layout desenfoque solicitado")
        else:
            if smart_framing is None:
                smart_framing = settings.render.smart_framing
            if (smart_framing or layout_mode in ("gaming", "split", "broll")) and self.face_tracker.available:
                seek_for_face = 0.0 if is_pretrimmed else start_time
                samples, src_w, src_h = self.face_tracker.sample(str(input_p), seek_for_face, duration)
                framing = choose_framing(samples, src_w, src_h, w, h, allow_split=(aspect_ratio == "9:16"), layout_mode=layout_mode)
                logger.info(f"Encuadre de {candidate.id}: {framing.mode} ({framing.reason})")
            elif layout_mode == "gaming":
                framing = choose_framing([], 1920, 1080, w, h, allow_split=False, layout_mode="gaming")
            elif layout_mode == "split":
                framing = choose_framing([], 1920, 1080, w, h, allow_split=True, layout_mode="split")
            elif layout_mode == "broll":
                framing = choose_framing([], 1920, 1080, w, h, allow_split=False, layout_mode="broll")

        if hook_zoom is None:
            hook_zoom = settings.render.hook_zoom
        eff_prog = bool(progress_bar)
        eff_zoom = bool(dynamic_zoom)
        eff_split_glow = bool(split_glow) if split_glow is not None else (framing.mode == "split")

        stk = None
        if auto_broll:
            stk_text = f"{candidate.title} {candidate.hook_text} {candidate.context_text}"
            stk = detect_contextual_sticker(stk_text)

        filter_str, final_label = self.build_filter_complex(
            w, h, ass_path, framing, cut_expr=cut_expr, hook_zoom=hook_zoom,
            progress_bar=eff_prog, clip_duration=duration, color_filter=color_filter,
            dynamic_zoom=eff_zoom, split_glow=eff_split_glow, broll_theme=broll_theme
        )

        # Smart B-Roll Engine integration (Submagic-style)
        broll_scheduled = broll_items
        if broll_scheduled is None:
            saved_b = load_clip_broll(candidate.id)
            if saved_b is not None:
                broll_scheduled = saved_b
            elif auto_broll:
                broll_scheduled = self.broll_engine.analyze_and_schedule(
                    sub_segments, sub_start, sub_end,
                    face_samples=samples if 'samples' in locals() else None,
                    density=broll_density,
                    theme=broll_theme or "auto",
                    mode=broll_mode
                )
                save_clip_broll(candidate.id, broll_scheduled)

        if broll_scheduled:
            broll_filter, final_label = self.broll_engine.build_broll_filters(
                broll_scheduled, w, h, final_label
            )
            filter_str += broll_filter

        # Smart SFX Engine integration (Submagic-style)
        sfx_scheduled = sfx_items
        if sfx_scheduled is None:
            saved_s = load_clip_sfx(candidate.id)
            if saved_s is not None:
                sfx_scheduled = saved_s
            elif auto_sfx:
                sfx_scheduled = self.sfx_engine.analyze_and_schedule(
                    sub_segments, sub_start, sub_end,
                    hook_text=getattr(candidate, "hook_text", ""),
                    virality_score=getattr(candidate, "virality_score", 85.0),
                    intensity=sfx_intensity,
                    active_categories=sfx_categories,
                    has_dynamic_zoom=eff_zoom
                )
                save_clip_sfx(candidate.id, sfx_scheduled)

        logger.info(f"Renderizando clip {aspect_ratio}: {output_file.name} ({duration:.1f}s)")
        self._run_ffmpeg(lambda enc: self.build_ffmpeg_cmd(
            input_p, output_file, start_time, duration, filter_str, final_label,
            encoder=enc, is_pretrimmed=is_pretrimmed, cut_expr=cut_expr, speed_mode=speed_mode,
            seamless_loop=seamless_loop, sfx_items=sfx_scheduled,
            audio_profile=audio_profile, target_lufs=target_lufs, target_lra=target_lra,
            target_tp=target_tp, master_limiter=master_limiter, true_peak_limit=true_peak_limit,
        ))
        # Miniatura omitida: los clips se muestran como video nativo limpio
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

