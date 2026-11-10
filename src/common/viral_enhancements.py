"""
Módulo de Mejoras Virales Estilo Clipper Profesional (2025-2026):
1. Detecta stickers/B-roll contextual según el tema (dinero, alerta, fuego, artistas).
2. Provee rutas de micro-SFX (whoosh, impact, ding) generados localmente.
3. Configura filtros de audio para bucle infinito (Seamless Loop) y normalización.
"""

import re
from pathlib import Path
from typing import Optional, List, Dict, Any

SFX_DIR = Path("data/assets/sfx")
GALLERY_DIR = Path("data/gallery")
DESKTOP_GALLERY_DIR = Path(r"C:\Users\Angel\Desktop\Galeria_Artistas")


def detect_contextual_sticker(text: str) -> Optional[Path]:
    """
    Detecta si en el fragmento se habla de un tema viral de alto impacto
    o de un artista y devuelve la ruta de la imagen para superponerla como B-Roll.
    """
    if not text:
        return None
    t = text.lower()
    
    # 1. Dinero y pérdidas millonarias
    if any(k in t for k in ["dinero", "millon", "cuarto", "cualto", "pesetas", "dolar", "dólar", "billon"]):
        p = GALLERY_DIR / "dinero_millones.jpg"
        if p.exists():
            return p
            
    # 2. Confesiones censuradas o polémicas
    if any(k in t for k in ["alerta", "censura", "peligro", "secreto", "grave", "muerte", "cárcel", "preso"]):
        p = GALLERY_DIR / "alerta_censurado.jpg"
        if p.exists():
            return p
            
    # 3. Exclusivas y bombas de bochinche
    if any(k in t for k in ["fuego", "bomba", "exclusiva", "bochinche", "caliente", "chisme"]):
        p = GALLERY_DIR / "fuego_bochinche.jpg"
        if p.exists():
            return p
            
    # 4. Artista específico si se menciona
    if "yailin" in t:
        p = GALLERY_DIR / "yailin_la_mas_viral.jpg"
        if p.exists():
            return p
    if "rochy" in t:
        p = GALLERY_DIR / "rochy_rd.jpg"
        if p.exists():
            return p
    if "anuel" in t:
        p = GALLERY_DIR / "anuel_aa.jpg"
        if p.exists():
            return p
    if "alofoke" in t or "santiago" in t:
        p = GALLERY_DIR / "alofoke.jpg"
        if p.exists():
            return p
            
    return None


def get_sfx_path(name: str) -> Optional[Path]:
    """Devuelve la ruta a un micro-SFX (whoosh, impact, ding)."""
    p = SFX_DIR / f"{name}.wav"
    return p if p.exists() else None


def build_audio_filter_chain(
    duration: float,
    normalize_audio: bool = True,
    seamless_loop: bool = False,
    cut_expr: Optional[str] = None,
    audio_profile: str = "social",
    target_lufs: float = -14.0,
    target_lra: float = 11.0,
    target_tp: float = -1.5,
    master_limiter: bool = True,
    true_peak_limit: float = 0.79,
) -> List[str]:
    """
    Construye la cadena de filtros de audio profesional para Clip Factory Pro:
    1. aselect para corte de pausas/silencios (si cut_expr está activo).
    2. Normalización de loudness configurable según perfil:
       - 'social': loudnorm broadcast para redes sociales (I=-14 LUFS, LRA=11, TP=-1.5 dBTP).
       - 'original': sin loudnorm (preserva la dinámica pura y volumen original).
       - 'custom': loudnorm con parámetros a medida (target_lufs, target_lra, target_tp).
    3. Audio Master Limiter transparente (True Peak target <= -1.0 dBTP):
       - alimiter de lookahead para evitar clipping digital y 'peak regrowth' por codec AAC.
       - attack=5ms, release=50ms, asc=0, level=disabled, limit=0.87 (-1.21 dBFS).
    4. Seamless Loop (micro fadeout de 0.12s) para bucle perfecto en TikTok/Reels.
    """
    af = []
    if cut_expr:
        af.append(f"aselect='{cut_expr}',asetpts=N/SR/TB")

    # 1. Normalización de loudness configurable
    effective_profile = audio_profile.lower() if normalize_audio else "original"

    if effective_profile == "social":
        af.append(f"loudnorm=I={target_lufs:.1f}:LRA={target_lra:.1f}:TP={target_tp:.1f}")
    elif effective_profile == "custom":
        af.append(f"loudnorm=I={target_lufs:.1f}:LRA={target_lra:.1f}:TP={target_tp:.1f}")
    elif effective_profile == "original":
        pass  # Preserva dinámica original sin loudnorm
    else:
        af.append(f"loudnorm=I={target_lufs:.1f}:LRA={target_lra:.1f}:TP={target_tp:.1f}")

    # 2. Audio Master Limiter transparente (evita clipping digital e inter-sample en AAC)
    if master_limiter:
        af.append("highpass=f=25")
        af.append(
            f"alimiter=level_in=1:level_out=1:limit={true_peak_limit:.4f}:attack=0.5:release=50:asc=0:level=disabled"
        )

    # 3. Seamless Loop
    if seamless_loop and duration > 1.0:
        st = max(0.0, duration - 0.12)
        af.append(f"afade=t=out:st={st:.3f}:d=0.12")

    return af
