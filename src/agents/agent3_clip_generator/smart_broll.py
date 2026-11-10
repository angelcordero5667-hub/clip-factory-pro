"""
Motor de B-Roll Inteligente (Smart B-Roll Engine) - Inspirado en Submagic.
Analiza la transcripción, detecta conceptos clave, busca recursos visuales relevantes,
los sincroniza en la línea de tiempo y evita cubrir el rostro del presentador.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.agents.agent3_clip_generator.framing import FaceSample
from src.common.config import settings
from src.common.models import TranscriptSegment

logger = logging.getLogger("Agent3_SmartBroll")

BROLL_DIR = Path("data/broll")
BROLL_MANIFEST = BROLL_DIR / "broll_manifest.json"
CACHE_BROLL_DIR = Path("data/cache/broll")
CACHE_BROLL_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_GALLERY_DIR = Path(r"C:\Users\Angel\Desktop\Galeria_Artistas")
INTERNAL_GALLERY_DIR = Path("data/gallery")


@dataclass
class BrollItem:
    id: str
    word: str
    category: str
    start: float  # relativo al inicio del clip (segundos)
    end: float    # relativo al inicio del clip (segundos)
    media_path: str
    media_url: str
    media_type: str  # "video" o "image"
    layout: str      # "overlay" (PiP card) | "cutaway" (pantalla completa/split) | "banner"
    position: str    # "bottom_right" | "top_right" | "bottom_left" | "top_left" | "center_cutaway"
    badge_text: str
    relevance_score: float = 1.0
    mime_type: str = "video/mp4"
    file_ext: str = ".mp4"
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrollItem":
        valid_keys = {
            "id", "word", "category", "start", "end", "media_path", "media_url",
            "media_type", "layout", "position", "badge_text", "relevance_score",
            "mime_type", "file_ext", "enabled"
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class SmartBrollEngine:
    def __init__(self):
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        if BROLL_MANIFEST.exists():
            try:
                return json.loads(BROLL_MANIFEST.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Error cargando broll_manifest.json: {e}")
        return {"categories": {}}

    def get_catalog(self) -> Dict[str, Any]:
        """Devuelve el catálogo de B-roll agrupado por categorías con URLs de acceso."""
        cat_data = self.manifest.get("categories", {})
        result = {}
        for cat_id, cat_info in cat_data.items():
            items = []
            for item in cat_info.get("items", []):
                items.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "type": item.get("type", "video"),
                    "url": f"/broll_media/{item.get('file')}",
                    "thumb_url": f"/broll_media/{item.get('thumb')}" if item.get("thumb") else None,
                    "rel_path": item.get("file")
                })
            result[cat_id] = {
                "name": cat_info.get("name"),
                "color": cat_info.get("color"),
                "badge": cat_info.get("badge"),
                "items": items
            }
        return result

    def _find_entity_media(self, text: str) -> Optional[Tuple[Path, str, str, str, str]]:
        """Busca si el texto menciona a un artista o tema especial en la galería del escritorio."""
        t = text.lower()
        # Escaneo en Desktop Gallery y local
        for gdir in [DESKTOP_GALLERY_DIR, INTERNAL_GALLERY_DIR]:
            if not gdir.exists():
                continue
            for f in gdir.iterdir():
                if f.is_file():
                    ext = f.suffix.lower()
                    if ext in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"):
                        stem = f.stem.lower().replace("_", " ")
                        tokens = [tok for tok in stem.split() if len(tok) >= 3]
                        if any(tok in t for tok in tokens) or stem in t:
                            badge = f"🔥 {f.stem.replace('_', ' ').upper()}"
                            mtype = "image" if ext in (".jpg", ".jpeg", ".png", ".webp") else "video"
                            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "video/mp4")
                            return f, mtype, badge, mime, ext
        return None

    def analyze_and_schedule(
        self,
        transcript_segments: List[TranscriptSegment],
        clip_start: float,
        clip_end: float,
        face_samples: Optional[Sequence[FaceSample]] = None,
        density: str = "medium",       # "low" | "medium" | "high" | "off"
        theme: str = "auto",           # "auto" o categoría específica
        mode: str = "smart_face_avoid" # "smart_face_avoid" | "overlay" | "cutaway"
    ) -> List[BrollItem]:
        """
        Analiza los segmentos correspondientes al clip, extrae palabras clave con alta relevancia,
        evita solapamientos y programa los B-Rolls con posición segura para no tapar rostros.
        """
        if density == "off" or clip_end <= clip_start:
            return []

        clip_duration = clip_end - clip_start
        # Parámetros según densidad
        if density == "low":
            max_items = max(1, int(clip_duration / 25.0))
            min_gap = 5.0
        elif density == "high":
            max_items = max(2, int(clip_duration / 8.0))
            min_gap = 2.5
        else:  # medium por defecto
            max_items = max(1, int(clip_duration / 14.0))
            min_gap = 3.5

        # Recopilar candidatos de B-roll a partir de la transcripción
        candidates: List[Dict[str, Any]] = []
        categories = self.manifest.get("categories", {})

        for seg in transcript_segments:
            # Segmento dentro del rango del clip
            if seg.end < clip_start or seg.start > clip_end:
                continue

            seg_text = seg.text.strip()
            # 1. Comprobar si hay palabras individuales con timestamps
            words_to_check = seg.words if seg.words else []

            # 2. Análisis global del segmento o por palabras
            if words_to_check:
                for w in words_to_check:
                    if w.end < clip_start or w.start > clip_end:
                        continue
                    w_clean = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", w.word.lower())
                    if len(w_clean) < 3:
                        continue

                    # Comprobar en categorías
                    matched = self._match_categories(w_clean, theme, categories)
                    if matched:
                        cat_id, item_obj, score = matched
                        t_rel_start = max(0.0, w.start - clip_start)
                        t_rel_end = min(clip_duration, t_rel_start + 2.8)
                        candidates.append({
                            "word": w.word,
                            "category": cat_id,
                            "item": item_obj,
                            "start": t_rel_start,
                            "end": t_rel_end,
                            "score": score
                        })
            else:
                # Fallback por texto del segmento
                t_rel_start = max(0.0, seg.start - clip_start)
                t_rel_end = min(clip_duration, t_rel_start + 3.0)
                matched = self._match_categories(seg_text.lower(), theme, categories)
                if matched:
                    cat_id, item_obj, score = matched
                    candidates.append({
                        "word": seg_text[:25],
                        "category": cat_id,
                        "item": item_obj,
                        "start": t_rel_start,
                        "end": t_rel_end,
                        "score": score
                    })

            # 3. Comprobar mención de entidad en la galería (artistas/temas VIP)
            entity = self._find_entity_media(seg_text)
            if entity:
                fpath, mtype, badge, mime, ext = entity
                t_rel_start = max(0.0, seg.start - clip_start)
                t_rel_end = min(clip_duration, t_rel_start + 3.0)
                candidates.append({
                    "word": fpath.stem.replace("_", " "),
                    "category": "artista",
                    "item": {
                        "id": fpath.stem.lower(),
                        "file": str(fpath.resolve()),
                        "type": mtype,
                        "mime": mime,
                        "ext": ext,
                        "badge": badge,
                        "is_absolute": True
                    },
                    "start": t_rel_start,
                    "end": t_rel_end,
                    "score": 1.5  # Alta prioridad para menciones directas
                })

        # Ordenar por relevancia
        candidates.sort(key=lambda c: c["score"], reverse=True)

        # Filtrar no-solapamientos
        scheduled: List[Dict[str, Any]] = []
        for cand in candidates:
            if len(scheduled) >= max_items:
                break
            st, et = cand["start"], cand["end"]
            # Verificar distancia mínima con los ya programados
            collision = any(not (et + min_gap <= s["start"] or st >= s["end"] + min_gap) for s in scheduled)
            if not collision:
                scheduled.append(cand)

        scheduled.sort(key=lambda s: s["start"])

        # Generar BrollItem determinando la posición segura según detección facial
        results: List[BrollItem] = []
        for idx, item in enumerate(scheduled):
            st = round(item["start"], 2)
            et = round(min(clip_duration, st + max(2.2, item["end"] - item["start"])), 2)
            it_data = item["item"]

            if it_data.get("is_absolute"):
                p = Path(it_data["file"])
                media_path = str(p.resolve())
                media_url = f"/gallery_desktop/{p.name}"
                media_type = it_data.get("type", "image")
                badge_text = it_data.get("badge", "🔥 VIP")
                mime_type = it_data.get("mime", "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "video/mp4")
                file_ext = p.suffix.lower()
            else:
                rel = it_data.get("file", "")
                p = BROLL_DIR / rel
                media_path = str(p.resolve()) if p.exists() else str(rel)
                media_url = f"/broll_media/{rel}"
                media_type = it_data.get("type", "video")
                cat_info = categories.get(item["category"], {})
                badge_text = cat_info.get("badge", f"⚡ {item['category'].upper()}")
                mime_type = it_data.get("mime", "video/mp4")
                file_ext = it_data.get("ext", Path(rel).suffix.lower() if rel else ".mp4")

            # Determinar posición para no cubrir el rostro
            pos, layout = self._decide_position(st, et, face_samples, mode)

            results.append(BrollItem(
                id=f"broll_{idx+1}_{item['category']}",
                word=item["word"],
                category=item["category"],
                start=st,
                end=et,
                media_path=media_path,
                media_url=media_url,
                media_type=media_type,
                layout=layout,
                position=pos,
                badge_text=badge_text,
                relevance_score=round(item["score"], 2),
                mime_type=mime_type,
                file_ext=file_ext,
                enabled=True
            ))

        return results

    def _match_categories(
        self, text: str, theme: str, categories: Dict[str, Any]
    ) -> Optional[Tuple[str, Dict[str, Any], float]]:
        """Encuentra la mejor categoría de B-roll según keywords."""
        best_match = None
        best_score = 0.0

        for cat_id, cat_info in categories.items():
            if theme not in ("auto", "none", "", None) and theme != cat_id:
                continue

            score = 0.0
            keywords = cat_info.get("keywords", [])
            for kw in keywords:
                if kw in text:
                    # Coincidencia exacta de palabra o subcadena
                    score += 1.0 if len(kw) > 4 else 0.7
                    if theme == cat_id:
                        score += 1.5

            if score > best_score and cat_info.get("items"):
                best_score = score
                best_match = (cat_id, cat_info["items"][0], score)

        return best_match

    def _decide_position(
        self,
        st: float,
        et: float,
        face_samples: Optional[Sequence[FaceSample]],
        mode: str
    ) -> Tuple[str, str]:
        """
        Decide la posición visual y el layout:
        - Si mode es 'cutaway', usa transición de corte cinematográfico.
        - En tomas con 2 participantes o rostros repartidos a izquierda y derecha,
          conmuta a 'center_cutaway' o 'top_right' para evitar tapar a cualquiera.
        - Si el rostro está en la mitad superior, coloca el B-roll abajo (bottom_right o bottom_left).
        - Si el rostro está abajo, coloca en 'top_right'.
        """
        if mode == "cutaway":
            return "center_cutaway", "cutaway"

        if not face_samples:
            return "bottom_right", "overlay"

        active_faces = [s for s in face_samples if st <= s.t <= et and s.xs]
        if not active_faces:
            return "bottom_right", "overlay"

        # Comprobar si hay dos participantes en escena
        max_faces = max(len(s.xs) for s in active_faces)
        if max_faces >= 2:
            # 2 participantes detectados: verificar posición vertical
            has_ys = any(s.ys for s in active_faces)
            if has_ys:
                all_ys = [y for s in active_faces for y in s.ys]
                avg_y = sum(all_ys) / len(all_ys)
                if avg_y > 0.45:
                    return "top_right", "overlay"
                else:
                    return "center_cutaway", "cutaway"
            return "center_cutaway", "cutaway"

        # 1 participante activo
        avg_x = sum(s.xs[0] for s in active_faces) / len(active_faces)
        avg_y = 0.35
        if any(s.ys for s in active_faces):
            all_ys = [s.ys[0] for s in active_faces if s.ys]
            if all_ys:
                avg_y = sum(all_ys) / len(all_ys)

        if avg_y > 0.55:
            # Rostro en la parte inferior -> colocar arriba a la derecha
            return "top_right", "overlay"
        elif avg_x > 0.55:
            # Rostro a la derecha -> tarjeta a la izquierda
            return "bottom_left", "overlay"
        elif avg_x < 0.45:
            # Rostro a la izquierda -> tarjeta a la derecha
            return "bottom_right", "overlay"
        else:
            return "bottom_right", "overlay"

    def build_broll_filters(
        self,
        broll_items: List[BrollItem],
        base_w: int,
        base_h: int,
        input_label: str
    ) -> Tuple[str, str]:
        """
        Genera la cadena de filtros FFmpeg para aplicar los B-rolls programados
        con transiciones de entrada y salida suaves y soporte robusto para video e imágenes estáticas.
        """
        active_items = [it for it in broll_items if it.enabled and Path(it.media_path).exists()]
        if not active_items:
            return "", input_label

        parts = []
        current_label = input_label

        for idx, item in enumerate(active_items):
            esc_path = str(Path(item.media_path).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            ext = Path(item.media_path).suffix.lower()
            is_image = item.media_type == "image" or ext in (".jpg", ".jpeg", ".png", ".webp")

            node_scaled = f"br_scl_{idx}"
            node_out = f"v_broll_{idx}"

            st = item.start
            et = item.end
            dur = max(0.5, et - st)

            # Para imágenes estáticas, loop=loop=-1:size=1:start=0 alimenta fotogramas continuamente.
            # Para videos MP4, movie alimenta directamente sin loop=0 que congele FFmpeg.
            loop_filter = "loop=loop=-1:size=1:start=0," if is_image else ""

            if item.layout == "cutaway":
                parts.append(
                    f";movie='{esc_path}',{loop_filter}scale={base_w}:{base_h}:force_original_aspect_ratio=increase,"
                    f"crop={base_w}:{base_h},format=yuva420p,"
                    f"fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st={dur-0.25:.2f}:d=0.25:alpha=1[{node_scaled}];"
                    f"{current_label}[{node_scaled}]overlay=x=0:y=0:enable='between(t,{st:.2f},{et:.2f})':eof_action=pass[{node_out}]"
                )
            else:
                card_w = min(360, int(base_w * 0.35))
                card_h = int(card_w * 1.1)

                if item.position == "bottom_left":
                    pos_x = "30"
                    pos_y = f"H-{card_h}-220"
                elif item.position == "top_right":
                    pos_x = f"W-{card_w}-30"
                    pos_y = "120"
                elif item.position == "top_left":
                    pos_x = "30"
                    pos_y = "120"
                else:  # bottom_right por defecto
                    pos_x = f"W-{card_w}-30"
                    pos_y = f"H-{card_h}-220"

                parts.append(
                    f";movie='{esc_path}',{loop_filter}scale={card_w}:{card_h}:force_original_aspect_ratio=increase,"
                    f"crop={card_w}:{card_h},format=yuva420p,"
                    f"fade=t=in:st=0:d=0.20:alpha=1,fade=t=out:st={dur-0.20:.2f}:d=0.20:alpha=1[{node_scaled}];"
                    f"{current_label}[{node_scaled}]overlay=x='{pos_x}':y='{pos_y}':enable='between(t,{st:.2f},{et:.2f})':eof_action=pass[{node_out}]"
                )

            current_label = f"[{node_out}]"

        return "".join(parts), current_label


def save_clip_broll(candidate_id: str, items: List[BrollItem]) -> Path:
    out = CACHE_BROLL_DIR / f"{candidate_id}.json"
    data = [it.to_dict() for it in items]
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_clip_broll(candidate_id: str) -> Optional[List[BrollItem]]:
    path = CACHE_BROLL_DIR / f"{candidate_id}.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [BrollItem.from_dict(d) for d in raw]
        except Exception as e:
            logger.warning(f"Error cargando B-roll de {candidate_id}: {e}")
    return None
