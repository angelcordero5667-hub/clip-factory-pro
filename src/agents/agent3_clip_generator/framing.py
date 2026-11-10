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
SPLIT_MIN_SEPARATION = 0.18  # separación horizontal mínima normalizada (calibrada a 0.18 para podcasts cercanos)


@dataclass
class FaceSample:
    """Rostros detectados en un instante (t en segundos relativos al inicio del clip).
    xs son centros horizontales normalizados (0-1), ordenados de izquierda a derecha."""
    t: float
    xs: List[float] = field(default_factory=list)
    ys: List[float] = field(default_factory=list)
    ws: List[float] = field(default_factory=list)
    hs: List[float] = field(default_factory=list)


@dataclass
class Framing:
    mode: str = "blur"                      # blur | crop | split | gaming | broll
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


def smooth_track_ema(
    samples: Sequence[FaceSample],
    alpha: float = 0.22,
    deadband: float = 0.035,
    window: int = 3,
    switch_threshold: float = 0.22,
    switch_sustain_sec: float = 2.5
) -> List[Tuple[float, float]]:
    """
    Seguimiento cinematográfico estilo Klap:
    - Deadband: ignora micro-oscilaciones de cabeza menores a 3.5% para máxima estabilidad de trípode virtual.
    - EMA: suavizado exponencial para transiciones sedosas cuando el sujeto se desplaza lateralmente.
    - Cortes directos (hard-cuts): si se confirma un cambio sostenido de interlocutor (> 2.5s),
      la cámara salta instantáneamente al nuevo hablante en lugar de un paneo lento artificial.
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
    filled = fill_gaps(raw)
    n = len(filled)
    if n == 0:
        return [(s.t, 0.5) for s in samples]

    dt = (samples[-1].t - samples[0].t) / max(1, n - 1) if n > 1 else 0.5
    lookahead_steps = max(2, int(switch_sustain_sec / max(0.01, dt)))

    out_xs = []
    cut_indices = set()
    curr = filled[0]
    for i in range(n):
        target = filled[i]
        diff = abs(target - curr)

        # Detección de cambio sostenido de interlocutor
        is_sustained_switch = False
        if diff >= switch_threshold and i + lookahead_steps <= n:
            future_window = filled[i:i + lookahead_steps]
            if all(abs(f - target) <= switch_threshold * 0.70 for f in future_window):
                is_sustained_switch = True

        if is_sustained_switch:
            # Corte directo cinematográfico: salto inmediato de cámara
            curr = target
            cut_indices.add(i)
        elif diff > deadband:
            curr = curr + alpha * (target - curr)

        out_xs.append(curr)

    if cut_indices:
        smoothed = []
        seg_start = 0
        sorted_cuts = sorted(cut_indices) + [n]
        for cut_idx in sorted_cuts:
            if cut_idx > seg_start:
                sub_chunk = out_xs[seg_start:cut_idx]
                smoothed.extend(moving_average(sub_chunk, window=window))
            seg_start = cut_idx
    else:
        smoothed = moving_average(out_xs, window=window)
    return [(s.t, x) for s, x in zip(samples, smoothed)]



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


def detect_two_speakers(
    samples: Sequence[FaceSample],
    min_separation: float = SPLIT_MIN_SEPARATION
) -> Optional[Tuple[float, float]]:
    """Si en suficientes muestras hay 2 rostros separados, devuelve (x_izq, x_der) medianos."""
    if not samples:
        return None
    pairs = [(s.xs[0], s.xs[-1]) for s in samples if len(s.xs) >= 2 and (s.xs[-1] - s.xs[0]) >= min_separation]
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

    if layout_mode in ("split", "dual_speaker", "split_screen") and out_h > out_w and src_w > 0 and src_h > 0:
        half_h = out_h // 2
        raw_crop_w = int(round(src_h * out_w / half_h)) // 2 * 2
        crop_w = max(2, min(src_w, raw_crop_w))
        pair = detect_two_speakers(samples) if samples else None
        if not pair:
            pair = (0.25, 0.75)
        max_offset = max(0, src_w - crop_w)
        xs = tuple(int(_clamp(p * src_w - crop_w / 2, 0, max_offset)) for p in pair)
        return Framing(mode="split", crop_w=crop_w, split_xs=xs, reason="layout podcast dual speaker: 2 participantes divididos arriba/abajo")

    if layout_mode == "podcast" and out_h > out_w and src_w > 0 and src_h > 0:
        pair = detect_two_speakers(samples) if samples else None
        if pair:
            half_h = out_h // 2
            raw_crop_w = int(round(src_h * out_w / half_h)) // 2 * 2
            crop_w = max(2, min(src_w, raw_crop_w))
            max_offset = max(0, src_w - crop_w)
            xs = tuple(int(_clamp(p * src_w - crop_w / 2, 0, max_offset)) for p in pair)
            return Framing(mode="split", crop_w=crop_w, split_xs=xs, reason="layout podcast inteligente: 2 participantes detectados")
        # Si no hay 2 hablantes, continúa hacia active_speaker crop
        layout_mode = "active_speaker"

    if layout_mode in ("active_speaker", "dynamic_crop") and src_w > 0 and src_h > 0:
        target_ar = out_w / out_h
        raw_crop_w = int(round(src_h * target_ar)) // 2 * 2
        crop_w = max(2, min(src_w, raw_crop_w))
        max_offset = max(0, src_w - crop_w)
        track = smooth_track_ema(samples) if samples else [(0.0, 0.5)]
        px = [(t, _clamp(x * src_w - crop_w / 2, 0, max_offset)) for t, x in track]
        keyframes = decimate_keyframes(px, tolerance=src_w * 0.02)
        return Framing(mode="crop", crop_w=crop_w, x_expr=build_x_expr(keyframes), reason=f"seguimiento facial {layout_mode} (Klap EMA)")

    if layout_mode == "gaming" and out_h > out_w and src_w > 0 and src_h > 0:
        top_h = int(out_h * 0.38) // 2 * 2
        raw_crop_w = int(round(src_h * out_w / top_h)) // 2 * 2
        crop_w = max(2, min(src_w, raw_crop_w))
        max_offset = max(0, src_w - crop_w)
        cam_x = 0
        if samples:
            with_faces = [s for s in samples if s.xs]
            if with_faces:
                avg_x = sum(s.xs[0] for s in with_faces) / len(with_faces)
                cam_x = int(_clamp(avg_x * src_w - crop_w / 2, 0, max_offset))
        return Framing(mode="gaming", crop_w=crop_w, split_xs=(cam_x, 0), reason="layout streamer: cámara arriba, juego abajo")

    if layout_mode == "broll" and out_h > out_w and src_w > 0 and src_h > 0:
        top_h = int(out_h * 0.50) // 2 * 2
        raw_crop_w = int(round(src_h * out_w / top_h)) // 2 * 2
        crop_w = max(2, min(src_w, raw_crop_w))
        max_offset = max(0, src_w - crop_w)
        cam_x = int((src_w - crop_w) / 2)
        if samples:
            with_faces = [s for s in samples if s.xs]
            if with_faces:
                avg_x = sum(s.xs[0] for s in with_faces) / len(with_faces)
                cam_x = int(_clamp(avg_x * src_w - crop_w / 2, 0, max_offset))
        return Framing(mode="broll", crop_w=crop_w, split_xs=(cam_x, 0), reason="layout b-roll gameplay: hablante arriba, metraje de retención abajo")

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
            raw_crop_w = int(round(src_h * out_w / half_h)) // 2 * 2
            crop_w = max(2, min(src_w, raw_crop_w))
            max_offset = max(0, src_w - crop_w)
            xs = tuple(int(_clamp(p * src_w - crop_w / 2, 0, max_offset)) for p in pair)
            return Framing(mode="split", crop_w=crop_w, split_xs=xs, reason="2 hablantes: pantalla dividida")

    raw_crop_w = int(round(src_h * target_ar)) // 2 * 2
    crop_w = max(2, min(src_w, raw_crop_w))
    max_offset = max(0, src_w - crop_w)
    # Cámara cinematográfica inteligente: suavizado exponencial EMA con deadband
    track = smooth_track_ema(samples, alpha=0.18, deadband=0.035, window=3)
    px = [(t, _clamp(x * src_w - crop_w / 2, 0, max_offset)) for t, x in track]
    keyframes = decimate_keyframes(px, tolerance=src_w * 0.02)
    return Framing(mode="crop", crop_w=crop_w, x_expr=build_x_expr(keyframes), reason="recorte centrado en el hablante (cámara cinematográfica suave)")
