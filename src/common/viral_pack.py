"""
Módulo del Pack Viral 1-Clic para Clip Factory Pro.
Orquesta de extremo a extremo:
1. Validación y extracción de audio/metadatos.
2. Transcripción con Faster-Whisper cuantizado y caché.
3. Detección de los 3 mejores momentos con IA y perfiles de energía.
4. Extracción de segmentos quirúrgicos con HTTP Range / FFmpeg.
5. Renderizado concurrente de clips verticales 9:16 (Smart Framing, Split-Screen, Hormozi Subs, Punch Zoom, SFX).
6. Generación de miniaturas verticales 9:16 de alto CTR.
7. Generación de metadatos optimizados para YouTube Shorts, TikTok, Facebook Reels e Instagram Reels.
8. Empaquetado automático organizado en Downloads/Clip_Factory_Pro/Pack_Viral_[fecha]/ con ZIP listo.
"""

import os
import sys
import time
import json
import zipfile
import shutil
import logging
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common.config import settings
from src.common.models import ViralMomentCandidate, TranscriptResult, TranscriptSegment
from src.common.youtube_downloader import download_youtube_audio, download_youtube_segment_stream
from src.agents.agent1_transcription.transcriber import AudioTranscriber
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.agents.agent2_viral_detector.audio_energy import compute_energy_profile
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.common.remotion_engine import remotion_engine
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

logger = logging.getLogger("ViralPack")

# Rutas estándar del sistema
DOWNLOADS_DIR = Path(os.environ.get("USERPROFILE", "C:/Users/Angel")) / "Downloads"
EXPORT_ROOT = DOWNLOADS_DIR / "Clip_Factory_Pro"
FONT_IMPACT = "C:/Windows/Fonts/impact.ttf"
FONT_ARIAL_BOLD = "C:/Windows/Fonts/arialbd.ttf"


class ClipProgressTracker:
    """Rastreador de progreso individual por clip para el panel de 3 tarjetas."""
    def __init__(self, clip_idx: int, title: str = "Preparando..."):
        self.clip_idx = clip_idx
        self.title = title
        self.stage = "En cola"
        self.percent = 0.0
        self.start_time = time.time()
        self.elapsed_sec = 0.0
        self.is_done = False
        self.error: Optional[str] = None
        self.video_url: Optional[str] = None
        self.thumb_url: Optional[str] = None
        self.cancel_event = threading.Event()

    def update(self, percent: float, stage: str):
        self.percent = min(1.0, max(0.0, percent))
        self.stage = stage
        self.elapsed_sec = time.time() - self.start_time

    def finish(self, video_path: str, thumb_path: Optional[str] = None):
        self.percent = 1.0
        self.stage = "Completado"
        self.is_done = True
        self.elapsed_sec = time.time() - self.start_time
        self.video_url = f"/api/files/download?path={Path(video_path).resolve()}"
        if thumb_path and Path(thumb_path).exists():
            self.thumb_url = f"/api/files/download?path={Path(thumb_path).resolve()}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_idx": self.clip_idx,
            "title": self.title,
            "stage": self.stage,
            "percent": round(self.percent * 100, 1),
            "elapsed_sec": round(self.elapsed_sec, 1),
            "is_done": self.is_done,
            "error": self.error,
            "video_url": self.video_url,
            "thumb_url": self.thumb_url,
            "is_cancelled": self.cancel_event.is_set()
        }


class ViralPackEngine:
    """Motor central de generación del Pack Viral 1-Clic."""

    def __init__(self):
        self.transcriber = AudioTranscriber()
        self.detector = ViralMomentDetector()
        self.clip_maker = VerticalClipMaker()
        self.max_concurrent_renders: int = settings.render.parallel_clips or 3
        self.active_packs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def generate_social_metadata(self, cand: ViralMomentCandidate, clip_idx: int = 1) -> Dict[str, Any]:
        """Genera títulos, hashtags, descripciones y comentario fijado adaptados a cada plataforma."""
        return self._generate_social_metadata(cand, clip_idx)

    def generate_vertical_thumbnail(
        self,
        video_or_frame_path: Any,
        candidate: ViralMomentCandidate,
        output_path: Optional[Path] = None,
        clip_idx: int = 0,
        badge_text: Optional[str] = None
    ) -> Optional[Path]:
        """Genera una miniatura vertical 9:16 de alto impacto visual y CTR."""
        out_dir = output_path.parent if output_path else settings.outputs_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        res = self._generate_viral_thumbnail(str(video_or_frame_path), candidate, clip_idx, out_dir)
        if res and output_path and Path(res) != Path(output_path):
            shutil.copy2(res, output_path)
            return output_path
        return res

    def get_pack_status(self, pack_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            p = self.active_packs.get(pack_id)
            if not p:
                return None
            cards = [t.to_dict() for t in p["trackers"]]
            return {
                "pack_id": pack_id,
                "status": p.get("status", "processing"),
                "overall_percent": round(p.get("overall_percent", 0.0) * 100, 1),
                "message": p.get("message", ""),
                "cards": cards,
                "export_folder": p.get("export_folder"),
                "zip_path": p.get("zip_path"),
                "metadata": p.get("social_metadata", [])
            }

    def cancel_clip(self, pack_id: str, clip_idx: int) -> bool:
        with self._lock:
            p = self.active_packs.get(pack_id)
            if p and 0 <= clip_idx < len(p["trackers"]):
                tracker = p["trackers"][clip_idx]
                tracker.cancel_event.set()
                tracker.stage = "Cancelado"
                tracker.error = "Cancelado por el usuario"
                logger.info(f"Clip {clip_idx + 1} de pack {pack_id} cancelado individualmente.")
                return True
        return False

    def generate_pack_async(
        self,
        youtube_url: str,
        pack_id: str,
        options: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> str:
        """Inicia el proceso en segundo plano en un hilo independiente."""
        opts = options or {}
        trackers = [
            ClipProgressTracker(0, "Clip 1: Detección..."),
            ClipProgressTracker(1, "Clip 2: Detección..."),
            ClipProgressTracker(2, "Clip 3: Detección...")
        ]
        with self._lock:
            self.active_packs[pack_id] = {
                "status": "processing",
                "overall_percent": 0.05,
                "message": "Iniciando análisis del video...",
                "trackers": trackers,
                "social_metadata": [],
                "options": opts,
                "start_time": time.time()
            }

        worker_thread = threading.Thread(
            target=self._run_pack_pipeline,
            args=(youtube_url, pack_id, opts, callback),
            daemon=True
        )
        worker_thread.start()
        return pack_id

    def _run_pack_pipeline(
        self,
        youtube_url: str,
        pack_id: str,
        opts: Dict[str, Any],
        callback: Optional[Callable[[Dict[str, Any]], None]]
    ):
        pack = self.active_packs[pack_id]
        trackers: List[ClipProgressTracker] = pack["trackers"]

        def notify(msg: str, overall: float):
            pack["message"] = msg
            pack["overall_percent"] = overall
            if callback:
                try:
                    callback(self.get_pack_status(pack_id))
                except Exception:
                    pass

        try:
            # 1. Obtener audio y transcripción rápida
            notify("⚡ Extrayendo audio y transcribiendo con Whisper...", 0.10)
            for t in trackers:
                t.update(0.15, "Transcribiendo audio...")

            audio_file, raw_title = download_youtube_audio(youtube_url)
            clean_title = "".join(c for c in raw_title if c.isalnum() or c in (" ", "_", "-")).strip()
            
            transcript: TranscriptResult = self.transcriber.transcribe(
                audio_file,
                dominican_mode=opts.get("dominican_mode", True),
                use_cache=True
            )
            notify(f"✅ Audio transcrito ({transcript.duration:.0f}s). Buscando momentos de oro...", 0.30)

            # 2. Análisis de energía y detección de los 3 mejores momentos
            energy = compute_energy_profile(audio_file, settings.ffmpeg_exe)
            candidates: List[ViralMomentCandidate] = self.detector.detect_moments(
                transcript,
                energy=energy,
                use_llm=True
            )

            if not candidates:
                # Fallback de seguridad si no hay candidatos
                candidates = [
                    ViralMomentCandidate(
                        id=f"cand_0", start_time=0.0, end_time=min(55.0, transcript.duration),
                        duration=min(55.0, transcript.duration), title="Momento Destacado",
                        hook_text="Momento inicial del video", context_text=transcript.full_text[:200],
                        virality_score=90.0, category="general"
                    )
                ]

            # Tomar los mejores 3
            selected_cands = candidates[:3]
            while len(selected_cands) < 3 and len(selected_cands) > 0:
                # Duplicar con desplazamiento si el video era muy corto
                last = selected_cands[-1]
                st = min(last.end_time, max(0.0, transcript.duration - 45.0))
                et = min(transcript.duration, st + 45.0)
                selected_cands.append(
                    ViralMomentCandidate(
                        id=f"cand_{len(selected_cands)}", start_time=st, end_time=et,
                        duration=et - st, title=f"Clip {len(selected_cands) + 1}",
                        hook_text=last.hook_text, context_text=last.context_text,
                        virality_score=88.0, category="general"
                    )
                )

            # Asignar nombres a los trackers
            for i, cand in enumerate(selected_cands):
                trackers[i].title = cand.title
                trackers[i].update(0.35, "Extrayendo segmento en HD...")

            notify("🎬 Extrayendo los 3 segmentos y renderizando en paralelo...", 0.40)

            # 3. Preparar carpeta de exportación organizada en Descargas
            timestamp_str = time.strftime("%Y%m%d_%H%M%S")
            folder_name = f"Pack_Viral_{clean_title[:30].strip()}_{timestamp_str}"
            pack_export_dir = EXPORT_ROOT / folder_name
            pack_export_dir.mkdir(parents=True, exist_ok=True)
            pack["export_folder"] = str(pack_export_dir.resolve())

            # 4. Renderizado concurrente de los 3 clips
            results_clips = [None] * len(selected_cands)
            results_thumbs = [None] * len(selected_cands)
            social_metadata_list = []

            def process_single_clip(idx: int, cand: ViralMomentCandidate):
                tracker = trackers[idx]
                if tracker.cancel_event.is_set():
                    return None, None, None

                # A) Extracción rápida de segmento
                raw_seg_path, _ = download_youtube_segment_stream(
                    youtube_url,
                    start_s=cand.start_time,
                    end_s=cand.end_time,
                    output_dir=settings.inputs_dir,
                    output_filename=f"{pack_id}_raw_{idx}_{int(cand.start_time)}_{int(cand.end_time)}.mp4"
                )
                if tracker.cancel_event.is_set():
                    return None, None, None

                tracker.update(0.50, "Encuadrando y generando subtítulos...")

                # B) Subtítulos y recorte
                sub_segments = [
                    s for s in transcript.segments
                    if s.end >= cand.start_time and s.start <= cand.end_time
                ]
                
                # Ajustar tiempos relativos a 0 para el clip pre-cortado
                rel_segments = []
                for s in sub_segments:
                    rel_s = TranscriptSegment(
                        start=max(0.0, s.start - cand.start_time),
                        end=max(0.0, s.end - cand.start_time),
                        text=s.text,
                        words=[
                            type(w)(
                                word=w.word,
                                start=max(0.0, w.start - cand.start_time),
                                end=max(0.0, w.end - cand.start_time),
                                probability=w.probability
                            ) for w in (s.words or [])
                        ]
                    )
                    rel_segments.append(rel_s)

                tracker.update(0.70, "Renderizando video 9:16 vertical...")

                # C) Render del clip vertical con Hormozi y Punch-Zoom
                if opts.get("render_engine") == "remotion" and remotion_engine.is_available():
                    tracker.update(0.70, "Renderizando con Remotion (Composición React 9:16)...")
                    props = remotion_engine.build_props(
                        video_path=raw_seg_path,
                        candidate=cand,
                        transcript_segments=rel_segments,
                        options=opts,
                        fps=int(opts.get("fps", 30))
                    )
                    out_clip = remotion_engine.render_clip(
                        props=props,
                        output_path=pack_export_dir / f"Clip_{idx+1:02d}.mp4",
                        on_progress=lambda p, st: tracker.update(0.60 + p * 0.25, st),
                        cancel_event=tracker.cancel_event,
                        concurrency=2,
                        fps=int(opts.get("fps", 30))
                    )
                else:
                    out_clip = self.clip_maker.generate_clip(
                        video_path=raw_seg_path,
                        candidate=cand,
                        transcript_segments=rel_segments,
                        with_subtitles=bool(opts.get("with_subtitles", True)),
                        subtitle_style=opts.get("subtitle_style", "hormozi"),
                        aspect_ratio="9:16",
                        is_pretrimmed=True,
                        punch_zooms=bool(opts.get("punch_zooms", True)),
                        auto_sfx=bool(opts.get("auto_sfx", True)),
                        speed_mode="fast"
                    )

                if tracker.cancel_event.is_set():
                    return None, None, None

                tracker.update(0.85, "Creando miniatura viral 9:16...")

                # D) Generar Miniatura 9:16
                thumb_path = self._generate_viral_thumbnail(
                    video_path=str(out_clip),
                    cand=cand,
                    clip_idx=idx + 1,
                    out_dir=pack_export_dir
                )

                # E) Guardar Clip en carpeta organizada
                clip_filename = f"Clip_{idx + 1:02d}_{clean_title[:20].strip()}.mp4"
                final_clip_path = pack_export_dir / clip_filename
                shutil.copy2(out_clip, final_clip_path)

                # F) Generar Metadatos para Redes
                meta_filename = f"Metadata_{idx + 1:02d}.txt"
                meta_dict = self._generate_social_metadata(cand, raw_title)
                meta_file_path = pack_export_dir / meta_filename
                with open(meta_file_path, "w", encoding="utf-8") as mf:
                    mf.write(meta_dict["full_text"])

                tracker.finish(str(final_clip_path), str(thumb_path) if thumb_path else None)
                return final_clip_path, thumb_path, meta_dict

            # Ejecutar hasta 3 en paralelo (concurrencia total en 16 hilos)
            max_workers = min(3, len(selected_cands))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(process_single_clip, i, c): i
                    for i, c in enumerate(selected_cands)
                }
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        c_path, t_path, m_dict = fut.result()
                        results_clips[idx] = c_path
                        results_thumbs[idx] = t_path
                        if m_dict:
                            social_metadata_list.append(m_dict)
                    except Exception as e:
                        logger.error(f"Error procesando clip {idx + 1}: {e}")
                        trackers[idx].error = str(e)
                        trackers[idx].stage = "Error"

            # 5. Crear Pack_Completo.zip con todos los archivos
            notify("📦 Empaquetando Pack_Completo.zip...", 0.92)
            zip_filename = pack_export_dir / f"Pack_Completo_{timestamp_str}.zip"
            with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_p in pack_export_dir.iterdir():
                    if file_p.is_file() and file_p != zip_filename:
                        zf.write(file_p, arcname=file_p.name)

            pack["zip_path"] = str(zip_filename.resolve())
            pack["social_metadata"] = social_metadata_list
            pack["status"] = "done"
            notify("🎉 ¡Pack Viral 1-Clic completado y listo en Descargas!", 1.0)

        except Exception as e:
            logger.exception(f"Error en Pack Viral {pack_id}: {e}")
            pack["status"] = "error"
            pack["message"] = f"Error: {e}"
            for t in trackers:
                if not t.is_done:
                    t.error = str(e)
                    t.stage = "Error"
            if callback:
                callback(self.get_pack_status(pack_id))

    def _generate_viral_thumbnail(
        self,
        video_path: str,
        cand: ViralMomentCandidate,
        clip_idx: int,
        out_dir: Path
    ) -> Optional[Path]:
        """Crea una miniatura vertical 9:16 de alta conversión y contraste."""
        try:
            # Si el archivo ya es una imagen, usarlo directamente; si es video, extraer frame a los 2.0s
            vpath = Path(video_path)
            if vpath.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                tmp_frame = vpath
            else:
                tmp_frame = out_dir / f"temp_frame_{clip_idx}.jpg"
                cmd = [
                    settings.ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", "00:00:02", "-i", str(vpath),
                    "-vframes", "1", "-q:v", "2",
                    str(tmp_frame.resolve())
                ]
                import subprocess
                subprocess.run(cmd, capture_output=True)
                if not tmp_frame.exists():
                    return None

            frame = Image.open(tmp_frame).convert("RGBA")
            W, H = 1080, 1920
            canvas = Image.new("RGBA", (W, H), (12, 12, 18, 255))

            # Fondo desenfocado y oscuro
            bg_ratio = max(W / frame.width, H / frame.height)
            bw, bh = int(frame.width * bg_ratio), int(frame.height * bg_ratio)
            bg_sc = frame.resize((bw, bh), Image.Resampling.LANCZOS)
            cx, cy = (bw - W) // 2, (bh - H) // 2
            bg_crop = bg_sc.crop((cx, cy, cx + W, cy + H))
            bg_blur = bg_crop.filter(ImageFilter.GaussianBlur(radius=38))
            bg_dark = ImageEnhance.Brightness(bg_blur).enhance(0.35)
            canvas.paste(bg_dark, (0, 0))

            # Gradientes
            grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gdraw = ImageDraw.Draw(grad)
            for y in range(350):
                gdraw.line([(0, y), (W, y)], fill=(0, 0, 0, int(220 * (1 - y / 350))))
            for y in range(1450, H):
                gdraw.line([(0, y), (W, y)], fill=(0, 0, 0, int(240 * ((y - 1450) / (H - 1450)))))
            canvas = Image.alpha_composite(canvas, grad)

            # Tarjeta de acción central con resplandor neón
            card_w = 1000
            card_h = int(card_w * (frame.height / frame.width))
            card_img = frame.resize((card_w, card_h), Image.Resampling.LANCZOS)

            glow_pad = 30
            glow_box = Image.new("RGBA", (card_w + glow_pad * 2, card_h + glow_pad * 2), (0, 0, 0, 0))
            ImageDraw.Draw(glow_box).rounded_rectangle(
                [glow_pad, glow_pad, card_w + glow_pad, card_h + glow_pad],
                radius=26, fill=(255, 215, 0, 175)
            )
            glow_blur = glow_box.filter(ImageFilter.GaussianBlur(radius=20))
            card_x = (W - card_w) // 2
            card_y = (H - card_h) // 2 - 30
            canvas.paste(glow_blur, (card_x - glow_pad, card_y - glow_pad), glow_blur)

            mask = Image.new("L", (card_w, card_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w, card_h], radius=26, fill=255)
            card_b = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
            card_b.paste(card_img, (0, 0), mask)
            ImageDraw.Draw(card_b).rounded_rectangle([1, 1, card_w - 2, card_h - 2], radius=26, outline=(255, 215, 0, 255), width=4)
            canvas.paste(card_b, (card_x, card_y), card_b)

            # Textos y Badges
            font_impact_top = ImageFont.truetype(FONT_IMPACT, 44)
            font_impact_big = ImageFont.truetype(FONT_IMPACT, 78)
            font_impact_sub = ImageFont.truetype(FONT_IMPACT, 68)
            font_arial_sub = ImageFont.truetype(FONT_ARIAL_BOLD, 36)

            # Top Badge
            badge_text = "🔴 EXCLUSIVA | VIRAL SHORTS"
            dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            bb = dummy_draw.textbbox((0, 0), badge_text, font=font_impact_top)
            bw, bh = (bb[2] - bb[0]) + 48, (bb[3] - bb[1]) + 24
            badge_img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            ImageDraw.Draw(badge_img).rounded_rectangle([0, 0, bw, bh], radius=20, fill=(220, 20, 20, 255))
            ImageDraw.Draw(badge_img).text((bw // 2, bh // 2), badge_text, font=font_impact_top, fill=(255, 255, 255), anchor="mm")
            canvas.paste(badge_img, ((W - bw) // 2, 170), badge_img)

            # Título principal dividido
            words = (cand.title or "MOMENTO VIRAL").upper().split()
            mid = len(words) // 2 if len(words) > 2 else len(words)
            l1 = " ".join(words[:mid])
            l2 = " ".join(words[mid:]) if mid < len(words) else "¡MIRA ESTO! 🔥"

            draw = ImageDraw.Draw(canvas)
            self._draw_outlined_text(draw, l1, (W // 2, 1420), font_impact_big, (255, 255, 255), (0, 0, 0), 6)
            self._draw_outlined_text(draw, l2, (W // 2, 1515), font_impact_sub, (255, 220, 0), (0, 0, 0), 6)

            # Bottom CTA
            cta_text = "👇 TOCA PARA VER COMPLETO"
            bb_c = dummy_draw.textbbox((0, 0), cta_text, font=font_arial_sub)
            cw, ch = (bb_c[2] - bb_c[0]) + 52, (bb_c[3] - bb_c[1]) + 26
            cta_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            ImageDraw.Draw(cta_img).rounded_rectangle([0, 0, cw, ch], radius=28, fill=(20, 20, 20, 240))
            ImageDraw.Draw(cta_img).text((cw // 2, ch // 2), cta_text, font=font_arial_sub, fill=(255, 255, 255), anchor="mm")
            canvas.paste(cta_img, ((W - cw) // 2, 1640), cta_img)

            out_thumb = out_dir / f"Miniatura_{clip_idx:02d}.jpg"
            canvas.convert("RGB").save(out_thumb, quality=95)
            if tmp_frame.exists():
                tmp_frame.unlink(missing_ok=True)
            return out_thumb

        except Exception as e:
            logger.warning(f"Error generando miniatura viral {clip_idx}: {e}")
            return None

    def _draw_outlined_text(self, draw, text, pos, font, fill_color, outline_color, width=5):
        x, y = pos
        for dx in range(-width, width + 1):
            for dy in range(-width, width + 1):
                if dx * dx + dy * dy <= width * width:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_color, anchor="mm")
        draw.text((x, y), text, font=font, fill=fill_color, anchor="mm")

    def _generate_social_metadata(self, cand: ViralMomentCandidate, original_title: str) -> Dict[str, Any]:
        """Crea títulos, hashtags, descripciones y comentarios fijados adaptados a cada red social."""
        clean_cand_title = (cand.title or "Momento Viral").strip()
        tags_yt = "#shorts #faranduladominicana #republicadominicana #podcast"
        tags_tk = "#parati #fyp #viral #dominicano #chisme"
        tags_reels = "#reelsrd #viralvideos #farandulard #humordominicano"

        yt_title = f"¡{clean_cand_title.upper()}! 😱🔥 {tags_yt}"
        tk_title = f"{clean_cand_title} 👀 {tags_tk}"
        fb_title = f"¡ATENCIÓN! {clean_cand_title}. ¿Qué opinas tú de esto? 👇"
        ig_title = f"Imperdible: {clean_cand_title} 🔥 Etiqueta a alguien que necesite ver esto. {tags_reels}"
        pinned_comment = f"¿Tú qué opinas de lo que pasó aquí? Déjame tu comentario abajo y suscríbete para la parte 2 👇🔥"

        full_text = f"""==================================================
METADATOS DEL CLIP — CLIP FACTORY PRO
Título Original: {original_title}
Clip: {clean_cand_title}
==================================================

[ YOUTUBE SHORTS ]
Título:
{yt_title}

Descripción:
{cand.hook_text or clean_cand_title}
Suscríbete al canal para no perderte las mejores exclusivas y debates de farándula.

Comentario Fijado (Pin Comment):
{pinned_comment}


[ TIKTOK ]
Descripción / Caption:
{tk_title}


[ FACEBOOK REELS ]
Título / Copy:
{fb_title}


[ INSTAGRAM REELS ]
Copy:
{ig_title}
"""
        return {
            "clip_id": cand.id,
            "title": clean_cand_title,
            "yt_title": yt_title,
            "tk_title": tk_title,
            "fb_title": fb_title,
            "ig_title": ig_title,
            "pinned_comment": pinned_comment,
            "full_text": full_text
        }


# Instancia única global
viral_pack_engine = ViralPackEngine()
