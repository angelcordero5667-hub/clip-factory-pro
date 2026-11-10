"""
Motor de Efectos de Sonido Inteligente (Smart SFX Engine) - Inspirado en Submagic.
Detecta momentos clave (ganchos, pausas dramáticas, picos de energía, remates y números),
inserta SFX sincronizados organizados en 7 categorías y mezcla con ducking inteligente
para no interferir con la voz original.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.agents.agent2_viral_detector.audio_energy import EnergyProfile
from src.common.config import settings
from src.common.models import TranscriptSegment

logger = logging.getLogger("Agent3_SmartSFX")

SFX_DIR = Path("data/assets/sfx")
SFX_MANIFEST = SFX_DIR / "sfx_manifest.json"
CACHE_SFX_DIR = Path("data/cache/sfx")
CACHE_SFX_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "impact",
    "whoosh",
    "pop",
    "cinematic",
    "comedy",
    "notification",
    "transition"
]


@dataclass
class SFXItem:
    id: str
    name: str
    category: str         # impact | whoosh | pop | cinematic | comedy | notification | transition
    time: float           # timestamp relativo al inicio del clip (segundos)
    sfx_file: str         # ej. "impact/bass_drop.wav"
    sfx_path: str         # ruta absoluta al archivo WAV
    sfx_url: str          # URL para el frontend ej. "/sfx_media/impact/bass_drop.wav"
    volume: float         # 0.05 a 0.70
    reason: str           # ej. "Gancho inicial", "Mención de dinero", "Remate cómico", "Pico de energía"
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SFXItem":
        return cls(**data)


class SmartSFXEngine:
    def __init__(self):
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Dict[str, List[Dict[str, Any]]]:
        if SFX_MANIFEST.exists():
            try:
                return json.loads(SFX_MANIFEST.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Error cargando sfx_manifest.json: {e}")
        return {}

    def get_catalog(self) -> Dict[str, Any]:
        """Devuelve todos los efectos de sonido agrupados por sus 7 categorías con URLs de audio."""
        result = {}
        for cat in CATEGORIES:
            items = []
            entries = self.manifest.get(cat, [])
            for entry in entries:
                rel = entry.get("file", "")
                p = SFX_DIR / rel
                items.append({
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "desc": entry.get("desc"),
                    "category": cat,
                    "rel_file": rel,
                    "url": f"/sfx_media/{rel}",
                    "exists": p.exists()
                })
            result[cat] = {
                "category": cat,
                "items": items
            }
        return result

    def get_default_sound(self, category: str) -> Optional[Tuple[str, str, Path]]:
        """Devuelve (nombre, rel_file, abs_path) del sonido predeterminado de una categoría."""
        entries = self.manifest.get(category, [])
        if entries:
            e = entries[0]
            rel = e.get("file", "")
            p = SFX_DIR / rel
            return e.get("name", category.capitalize()), rel, p.resolve()
        # Fallback genérico
        fallback = SFX_DIR / f"{category}.wav"
        if fallback.exists():
            return category.capitalize(), f"{category}.wav", fallback.resolve()
        return None

    def analyze_and_schedule(
        self,
        transcript_segments: List[TranscriptSegment],
        clip_start: float,
        clip_end: float,
        energy_profile: Optional[EnergyProfile] = None,
        hook_text: str = "",
        virality_score: float = 85.0,
        intensity: str = "normal",   # "soft" | "normal" | "aggressive" | "off"
        active_categories: Optional[Sequence[str]] = None,
        has_dynamic_zoom: bool = False,
    ) -> List[SFXItem]:
        """
        Detecta los momentos donde los efectos enriquecen la narrativa:
        - Inicio (gancho inmediato): impact / whoosh
        - Picos de emoción / risas: bass_drop / dramatic_hit
        - Preguntas o remates cómicos: record_scratch / rimshot
        - Mención de cifras / dinero: cash_register / ding
        - Zooms dinámicos de cámara: whoosh
        """
        if intensity == "off" or clip_end <= clip_start:
            return []

        clip_duration = clip_end - clip_start
        allowed_cats = set(active_categories) if active_categories else set(CATEGORIES)

        # Configuración según intensidad
        if intensity == "soft":
            base_vol = 0.18
            max_sfx = max(2, int(clip_duration / 12.0))
            min_gap = 4.0
        elif intensity == "aggressive":
            base_vol = 0.42
            max_sfx = max(4, int(clip_duration / 3.5))
            min_gap = 1.8
        else:  # normal por defecto
            base_vol = 0.28
            max_sfx = max(3, int(clip_duration / 5.5))
            min_gap = 2.4

        scheduled: List[SFXItem] = []
        occupied_times: List[float] = []

        def can_place(t: float) -> bool:
            for prev in occupied_times:
                effective_gap = min(min_gap, 0.65) if prev <= 0.4 else min_gap
                if abs(t - prev) < effective_gap:
                    return False
            return True

        # 1. Pre-análisis: Comprobar si hay una palabra clave de alto impacto inmediata en los primeros 0.4 segundos
        early_keyword_sfx: Optional[SFXItem] = None
        for seg in transcript_segments:
            if seg.end < clip_start or seg.start > clip_end:
                continue
            t_seg_rel = max(0.0, seg.start - clip_start)
            if t_seg_rel <= 0.4:
                seg_lower = seg.text.lower()
                # Prioridad 1: Dinero / Éxito
                if "notification" in allowed_cats and any(k in seg_lower for k in ["dinero", "millon", "millones", "cuarto", "cualto", "dolar", "dólar", "gané", "ganamos", "rico"]):
                    entries = self.manifest.get("notification", [])
                    chosen = next((e for e in entries if "cash" in e["id"]), entries[0] if entries else None)
                    if chosen:
                        p = (SFX_DIR / chosen["file"]).resolve()
                        t_cue = round(max(0.2, t_seg_rel + 0.25), 2)
                        early_keyword_sfx = SFXItem(
                            id="sfx_intro_cash_priority",
                            name=chosen["name"],
                            category="notification",
                            time=t_cue,
                            sfx_file=chosen["file"],
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{chosen['file']}",
                            volume=round(base_vol * 1.15, 2),
                            reason="Gancho prioritario: Mención de dinero inicial",
                            enabled=True
                        )
                        break
                # Prioridad 2: Comedia
                elif "comedy" in allowed_cats and any(k in seg_lower for k in ["jajaja", "risa", "mentira", "loco", "mentiroso", "diantre", "chercha", "broma", "burla"]):
                    entries = self.manifest.get("comedy", [])
                    chosen = next((e for e in entries if "rimshot" in e["id"]), entries[0] if entries else None)
                    if chosen:
                        p = (SFX_DIR / chosen["file"]).resolve()
                        t_cue = round(max(0.2, t_seg_rel + 0.25), 2)
                        early_keyword_sfx = SFXItem(
                            id="sfx_intro_comedy_priority",
                            name=chosen["name"],
                            category="comedy",
                            time=t_cue,
                            sfx_file=chosen["file"],
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{chosen['file']}",
                            volume=round(base_vol * 1.15, 2),
                            reason="Gancho prioritario: Remate cómico inicial",
                            enabled=True
                        )
                        break
                # Prioridad 3: Peligro o Secreto
                elif "cinematic" in allowed_cats and any(k in seg_lower for k in ["secreto", "peligro", "alerta", "grave", "muerte", "cárcel", "problema", "conspiración"]):
                    entries = self.manifest.get("cinematic", [])
                    chosen = entries[0] if entries else None
                    if chosen:
                        p = (SFX_DIR / chosen["file"]).resolve()
                        t_cue = round(max(0.2, t_seg_rel + 0.25), 2)
                        early_keyword_sfx = SFXItem(
                            id="sfx_intro_cinema_priority",
                            name=chosen["name"],
                            category="cinematic",
                            time=t_cue,
                            sfx_file=chosen["file"],
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{chosen['file']}",
                            volume=round(base_vol * 1.15, 2),
                            reason="Gancho prioritario: Tensión inicial",
                            enabled=True
                        )
                        break

        # Si hubo palabra clave en los primeros 0.4s, toma la prioridad absoluta del gancho
        if early_keyword_sfx:
            scheduled.append(early_keyword_sfx)
            occupied_times.append(early_keyword_sfx.time)
        elif "whoosh" in allowed_cats or "impact" in allowed_cats:
            # Gancho inicial genérico (Punch de entrada al segundo 0.3s)
            intro_cat = "whoosh" if virality_score < 80 else "impact"
            snd = self.get_default_sound(intro_cat)
            if snd:
                name, rel, abs_path = snd
                t_intro = 0.3
                scheduled.append(SFXItem(
                    id=f"sfx_intro_{intro_cat}",
                    name=name,
                    category=intro_cat,
                    time=t_intro,
                    sfx_file=rel,
                    sfx_path=str(abs_path),
                    sfx_url=f"/sfx_media/{rel}",
                    volume=min(0.50, round(base_vol * 1.15, 2)),
                    reason="Gancho inicial de atención",
                    enabled=True
                ))
                occupied_times.append(t_intro)

        # 2. Análisis por palabras y frases en la transcripción
        for seg in transcript_segments:
            if seg.end < clip_start or seg.start > clip_end:
                continue

            words = seg.words if seg.words else []
            t_seg_rel = max(0.0, seg.start - clip_start)

            # Buscar palabras de dinero o éxito -> notification (caja registradora o ding)
            seg_lower = seg.text.lower()
            if any(k in seg_lower for k in ["dinero", "millon", "cuarto", "cualto", "dolar", "dólar", "gané", "ganamos", "rico"]):
                if "notification" in allowed_cats and can_place(t_seg_rel + 0.4):
                    entries = self.manifest.get("notification", [])
                    chosen = next((e for e in entries if "cash" in e["id"]), entries[0] if entries else None)
                    if chosen:
                        rel = chosen["file"]
                        p = (SFX_DIR / rel).resolve()
                        t_cue = round(t_seg_rel + 0.4, 2)
                        scheduled.append(SFXItem(
                            id=f"sfx_{len(scheduled)+1}_cash",
                            name=chosen["name"],
                            category="notification",
                            time=t_cue,
                            sfx_file=rel,
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{rel}",
                            volume=round(base_vol * 1.1, 2),
                            reason="Mención de dinero y millones",
                            enabled=True
                        ))
                        occupied_times.append(t_cue)

            # Remates, risas o chistes -> comedy (rimshot o record scratch)
            if any(k in seg_lower for k in ["jajaja", "risa", "mentira", "loco", "mentiroso", "diantre", "chercha", "broma", "burla"]):
                if "comedy" in allowed_cats and can_place(t_seg_rel + 0.6):
                    entries = self.manifest.get("comedy", [])
                    chosen = next((e for e in entries if "rimshot" in e["id"]), entries[0] if entries else None)
                    if chosen:
                        rel = chosen["file"]
                        p = (SFX_DIR / rel).resolve()
                        t_cue = round(t_seg_rel + 0.6, 2)
                        scheduled.append(SFXItem(
                            id=f"sfx_{len(scheduled)+1}_comedy",
                            name=chosen["name"],
                            category="comedy",
                            time=t_cue,
                            sfx_file=rel,
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{rel}",
                            volume=round(base_vol * 1.0, 2),
                            reason="Momento cómico o punchline",
                            enabled=True
                        ))
                        occupied_times.append(t_cue)

            # Confidencial, peligro o secreto -> cinematic (tension riser o dramatic hit)
            if any(k in seg_lower for k in ["secreto", "peligro", "alerta", "grave", "muerte", "cárcel", "problema", "conspiración"]):
                if "cinematic" in allowed_cats and can_place(t_seg_rel + 0.5):
                    entries = self.manifest.get("cinematic", [])
                    chosen = entries[0] if entries else None
                    if chosen:
                        rel = chosen["file"]
                        p = (SFX_DIR / rel).resolve()
                        t_cue = round(t_seg_rel + 0.5, 2)
                        scheduled.append(SFXItem(
                            id=f"sfx_{len(scheduled)+1}_cinema",
                            name=chosen["name"],
                            category="cinematic",
                            time=t_cue,
                            sfx_file=rel,
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{rel}",
                            volume=round(base_vol * 1.05, 2),
                            reason="Momento dramático o revelación",
                            enabled=True
                        ))
                        occupied_times.append(t_cue)

        # 3. Picos de energía de audio (AudioEnergyProfile) -> bass_drop o impact
        if energy_profile and len(energy_profile.norm) > 0 and "impact" in allowed_cats:
            hop = energy_profile.hop
            start_idx = int(clip_start / hop)
            end_idx = min(len(energy_profile.norm), int(clip_end / hop))
            if end_idx > start_idx:
                chunk = energy_profile.norm[start_idx:end_idx]
                p85 = float(chunk.mean() + 1.2 * chunk.std()) if len(chunk) > 3 else 0.8
                for idx_step, val in enumerate(chunk):
                    if val > p85:
                        t_peak = round(idx_step * hop, 2)
                        if 1.0 <= t_peak <= clip_duration - 1.5 and can_place(t_peak):
                            entries = self.manifest.get("impact", [])
                            chosen = next((e for e in entries if "bass_drop" in e["id"]), entries[0] if entries else None)
                            if chosen:
                                rel = chosen["file"]
                                p = (SFX_DIR / rel).resolve()
                                scheduled.append(SFXItem(
                                    id=f"sfx_{len(scheduled)+1}_peak",
                                    name=chosen["name"],
                                    category="impact",
                                    time=t_peak,
                                    sfx_file=rel,
                                    sfx_path=str(p),
                                    sfx_url=f"/sfx_media/{rel}",
                                    volume=round(base_vol * 1.15, 2),
                                    reason="Pico de energía acústica / emoción",
                                    enabled=True
                                ))
                                occupied_times.append(t_peak)
                                break  # Máx un impacto por subida acústica

        # 4. Sincronización con Zoom Dinámico (Whoosh cada ciclo de mod(t, 12) = 0)
        if has_dynamic_zoom and "whoosh" in allowed_cats:
            t_zoom = 12.0
            while t_zoom < clip_duration - 2.0:
                if can_place(t_zoom):
                    entries = self.manifest.get("whoosh", [])
                    chosen = next((e for e in entries if "fast_swoosh" in e["id"]), entries[0] if entries else None)
                    if chosen:
                        rel = chosen["file"]
                        p = (SFX_DIR / rel).resolve()
                        scheduled.append(SFXItem(
                            id=f"sfx_{len(scheduled)+1}_zoom",
                            name=chosen["name"],
                            category="whoosh",
                            time=round(t_zoom, 2),
                            sfx_file=rel,
                            sfx_path=str(p),
                            sfx_url=f"/sfx_media/{rel}",
                            volume=round(base_vol * 0.9, 2),
                            reason="Transición de zoom dinámico",
                            enabled=True
                        ))
                        occupied_times.append(t_zoom)
                t_zoom += 12.0

        # Limitar al máximo según intensidad y ordenar cronológicamente
        scheduled.sort(key=lambda x: x.time)
        return scheduled[:max_sfx]

    def build_audio_mix_args(
        self,
        sfx_items: List[SFXItem],
        base_audio_label: str = "0:a"
    ) -> Tuple[List[str], str, str]:
        """
        Construye los argumentos de FFmpeg para mezclar la voz principal con los efectos SFX:
        Devuelve (lista_de_entradas_i, cadena_de_filtros_af, etiqueta_de_salida).
        Si no hay SFX activos, devuelve ([], "", base_audio_label).
        """
        active = [it for it in sfx_items if it.enabled and Path(it.sfx_path).exists()]
        if not active:
            return [], "", base_audio_label

        input_args: List[str] = []
        filter_parts: List[str] = []
        mix_inputs = [f"[{base_audio_label}]"]

        for idx, item in enumerate(active):
            input_args.extend(["-i", str(Path(item.sfx_path).resolve())])
            # El índice de entrada en FFmpeg depende de cuántos inputs previos hay.
            # Se formulará dinámicamente o se pasará como cadena de delay.
            ms = max(0, int(item.time * 1000.0))
            vol = max(0.05, min(0.9, item.volume))
            sfx_in_idx = idx + 1  # 0 es el video original
            node_label = f"sfx_{idx}"
            filter_parts.append(
                f"[{sfx_in_idx}:a]adelay={ms}|{ms},volume={vol:.2f}[{node_label}]"
            )
            mix_inputs.append(f"[{node_label}]")

        total_inputs = len(mix_inputs)
        # Pesos explícitos para amix:
        # Entrada 1 (voz original) = peso 1.0; Entradas SFX = pesos calibrados (0.25-0.55)
        # Esto previene que amix divida la voz entre N y garantiza claridad vocal absoluta
        weights = ["1.0"] + [f"{min(0.60, max(0.20, it.volume)):.2f}" for it in active]
        weights_str = " ".join(weights)
        mix_expr = "".join(mix_inputs) + f"amix=inputs={total_inputs}:duration=first:dropout_transition=2:weights='{weights_str}'[a_sfx_mix]"
        filter_parts.append(mix_expr)

        return input_args, ";".join(filter_parts), "[a_sfx_mix]"


def save_clip_sfx(candidate_id: str, items: List[SFXItem]) -> Path:
    out = CACHE_SFX_DIR / f"{candidate_id}.json"
    data = [it.to_dict() for it in items]
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_clip_sfx(candidate_id: str) -> Optional[List[SFXItem]]:
    path = CACHE_SFX_DIR / f"{candidate_id}.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [SFXItem.from_dict(d) for d in raw]
        except Exception as e:
            logger.warning(f"Error cargando SFX de {candidate_id}: {e}")
    return None
