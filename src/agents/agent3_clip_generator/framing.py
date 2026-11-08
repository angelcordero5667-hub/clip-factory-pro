"""Auto-encuadre: lógica pura (sin OpenCV ni FFmpeg) para decidir y construir el recorte.

Modos de layout
- "blur":  video completo centrado sobre fondo desenfocado (layout original). Se usa si no hay
           rostro de forma fiable.
- "crop":  recorte 9:16 centrado en el hablante con crop dinámico (cámara virtual suave).
- "split": fallback para 2 hablantes: pantalla dividida arriba/abajo (solo 9:16).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

MIN_FACE_RATIO = 0.35        # fracción mínima de muestras con rostro para recortar
SPLIT_MIN_RATIO = 0.35       # fracción de muestras con 2 rostros separados para dividir pantalla
SPLIT_MIN_SEPARATION = 0.25  # separación horizontal mínima (normalizada) entre los 2 rostros


@dataclass
class FaceSample:
    """Rostros detectados en un instante (t en segundos relativos al inicio del clip).
    xs son centros horizontales normalizados (0-1), ordenados de izquierda a derecha."""
    t: float
    xs: List[float] = field(default_factory=list)


@dataclass
class Framing:
    mode: str = "blur"                      # blur | crop | split
    crop_w: int = 0                         # ancho del recorte en px de la fuente
    x_expr: str = ""                        # expresión ffmpeg para x del crop (modo crop)
    split_xs: Tuple[int, int] = (0, 0)      # x (px) del recorte superior e inferior (modo split)
    reason: str = ""


def moving_average(values: Sequence[float], window: int = 5) -> List[float]:
    """Media móvil centrada (ventana impar); los bordes usan la ventana disponible."""
    n = len(values)
    if n == 0 or window <= 1:
        return list(values)
    half = window // 2
    out = []
    for i in range(n):
        chunk = values[max(0, i - half): i + half + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def fill_gaps(values: Sequence[Optional[float]], default: float = 0.5) -> List[float]:
    """Rellena huecos (None) con el valor conocido más cercano; sin datos usa `default`."""
    known = [i for i, v in enumerate(values) if v is not None]
    if not known:
        return [default] * len(values)
    out: List[float] = []
    for i, v in enumerate(values):
        if v is not None:
            out.append(v)
        else:
            nearest = min(known, key=lambda k: abs(k - i))
            out.append(values[nearest])  # type: ignore[arg-type]
    return out


def smooth_track(samples: Sequence[FaceSample], window: int = 5) -> List[Tuple[float, float]]:
    """Convierte muestras en una trayectoria suave [(t, x_normalizada)] del hablante principal.

    Con varios rostros se toma el más cercano al centro previo (continuidad) y, al inicio, el
    más central.
    """
    raw: List[Optional[float]] = []
    prev = 0.5
    for s in samples:
        if s.xs:
            x = min(s.xs, key=lambda v: abs(v - prev))
            raw.append(x)
            prev = x
        else:
            raw.append(None)
    xs = moving_average(fill_gaps(raw), window)
    return [(s.t, x) for s, x in zip(samples, xs)]


def decimate_keyframes(points: Sequence[Tuple[float, float]], tolerance: float) -> List[Tuple[float, float]]:
    """Reduce la trayectoria a keyframes: solo se conserva un punto cuando la interpolación
    lineal entre los guardados se desvía más de `tolerance` (zona muerta: cámara estable)."""
    if len(points) <= 2:
        return list(points)
    kept = [points[0]]
    anchor = 0
    for i in range(2, len(points)):
        t0, x0 = points[anchor]
        t1, x1 = points[i]
        for k in range(anchor + 1, i):
            tk, xk = points[k]
            interp = x0 + (x1 - x0) * ((tk - t0) / (t1 - t0) if t1 != t0 else 0)
            if abs(interp - xk) > tolerance:
                kept.append(points[i - 1])
                anchor = i - 1
                break
    kept.append(points[-1])
    # elimina duplicados de tiempo
    dedup = [kept[0]]
    for p in kept[1:]:
        if p[0] > dedup[-1][0]:
            dedup.append(p)
    return dedup


def build_x_expr(keyframes: Sequence[Tuple[float, float]]) -> str:
    """Expresión de FFmpeg (variable `t`) con interpolación lineal entre keyframes (t, x_px)."""
    if not keyframes:
        return "0"
    if len(keyframes) == 1:
        return f"{keyframes[0][1]:.1f}"
    expr = f"{keyframes[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(keyframes, keyframes[1:]))):
        if t1 == t0:
            continue
        slope = (x1 - x0) / (t1 - t0)
        expr = f"if(lt(t,{t1:.2f}),{x0:.1f}+({slope:.3f})*(t-{t0:.2f}),{expr})"
    # antes del primer keyframe se mantiene su posición
    return f"if(lt(t,{keyframes[0][0]:.2f}),{keyframes[0][1]:.1f},{expr})"


def detect_two_speakers(samples: Sequence[FaceSample]) -> Optional[Tuple[float, float]]:
    """Si en suficientes muestras hay 2 rostros separados, devuelve (x_izq, x_der) medianos."""
    if not samples:
        return None
    pairs = [(s.xs[0], s.xs[-1]) for s in samples if len(s.xs) >= 2 and (s.xs[-1] - s.xs[0]) >= SPLIT_MIN_SEPARATION]
    if len(pairs) / len(samples) < SPLIT_MIN_RATIO:
        return None
    lefts = sorted(p[0] for p in pairs)
    rights = sorted(p[1] for p in pairs)
    return lefts[len(lefts) // 2], rights[len(rights) // 2]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def choose_framing(
    samples: Sequence[FaceSample],
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    allow_split: bool = True,
    layout_mode: Optional[str] = None,
) -> Framing:
    """Decide el layout a partir de las detecciones y las dimensiones fuente/destino."""
    if layout_mode == "blur":
        return Framing(mode="blur", reason="layout desenfoque solicitado")

    if layout_mode == "split" and out_h > out_w and src_w > 0 and src_h > 0:
        half_h = out_h // 2
        crop_w = min(src_w, int(round(src_h * out_w / half_h)) // 2 * 2)
        pair = detect_two_speakers(samples) if samples else None
        if not pair:
            pair = (0.25, 0.75)
        xs = tuple(int(_clamp(p * src_w - crop_w / 2, 0, src_w - crop_w)) for p in pair)
        return Framing(mode="split", crop_w=crop_w, split_xs=xs, reason="layout podcast split: 2 participantes divididos arriba/abajo")

    if layout_mode == "gaming" and out_h > out_w and src_w > 0 and src_h > 0:
        top_h = int(out_h * 0.38) // 2 * 2
        crop_w = min(src_w, int(round(src_h * out_w / top_h)) // 2 * 2)
        cam_x = 0
        if samples:
            with_faces = [s for s in samples if s.xs]
            if with_faces:
                avg_x = sum(s.xs[0] for s in with_faces) / len(with_faces)
                cam_x = int(_clamp(avg_x * src_w - crop_w / 2, 0, src_w - crop_w))
        return Framing(mode="gaming", crop_w=crop_w, split_xs=(cam_x, 0), reason="layout streamer: cámara arriba, juego abajo")

    if src_w <= 0 or src_h <= 0 or not samples:
        return Framing(mode="blur", reason="sin datos de video")

    target_ar = out_w / out_h
    src_ar = src_w / src_h
    if src_ar <= target_ar + 0.05:
        return Framing(mode="blur", reason="la fuente ya es igual o más vertical que el destino")

    with_face = sum(1 for s in samples if s.xs)
    if with_face / len(samples) < MIN_FACE_RATIO:
        return Framing(mode="blur", reason="rostro no detectado de forma fiable")

    # 2 hablantes -> pantalla dividida (solo vertical 9:16)
    if allow_split and out_h > out_w:
        pair = detect_two_speakers(samples)
        if pair:
            half_h = out_h // 2
            crop_w = min(src_w, int(round(src_h * out_w / half_h)) // 2 * 2)
            xs = tuple(int(_clamp(p * src_w - crop_w / 2, 0, src_w - crop_w)) for p in pair)
            return Framing(mode="split", crop_w=crop_w, split_xs=xs, reason="2 hablantes: pantalla dividida")

    crop_w = min(src_w, int(round(src_h * target_ar)) // 2 * 2)
    track = smooth_track(samples)
    px = [(t, _clamp(x * src_w - crop_w / 2, 0, src_w - crop_w)) for t, x in track]
    keyframes = decimate_keyframes(px, tolerance=src_w * 0.02)
    return Framing(mode="crop", crop_w=crop_w, x_expr=build_x_expr(keyframes), reason="recorte centrado en el hablante")
