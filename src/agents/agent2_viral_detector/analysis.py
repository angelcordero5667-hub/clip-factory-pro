"""Funciones puras de análisis de transcripción (fáciles de probar sin Ollama ni FFmpeg)."""
import bisect
import re
import unicodedata
from typing import List, Optional, Tuple

from src.common.models import TranscriptSegment, WordTimestamp

SENTENCE_END = (".", "?", "!", "…", "¿", "¡")


def normalize_text(text: str) -> str:
    """Minúsculas y sin acentos/diacríticos: 'Increíble' -> 'increible', 'Año' -> 'ano'."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def compile_keyword_patterns(keywords: List[str]) -> List[re.Pattern]:
    """Patrones con inicio de palabra (así 'jaja' también encuentra 'jajaja' pero 'ley' no encuentra 'reyes')."""
    return [re.compile(r"\b" + re.escape(normalize_text(k))) for k in keywords]


def count_keyword_hits(normalized_text: str, patterns: List[re.Pattern]) -> int:
    return sum(1 for p in patterns if p.search(normalized_text))


# ----------------------------------------------------------------------
# Ventanas de transcripción para el LLM
# ----------------------------------------------------------------------
def build_windows(
    segments: List[TranscriptSegment],
    window_sec: float = 360.0,
    overlap_sec: float = 30.0,
) -> List[List[TranscriptSegment]]:
    """Divide los segmentos en ventanas de ~window_sec (5-8 min) con solape de overlap_sec.

    Cada ventana contiene los segmentos que intersectan [t0, t0 + window_sec]. La siguiente
    ventana empieza en t0 + window_sec - overlap_sec. Sin segmentos -> lista vacía.
    """
    if not segments:
        return []
    window_sec = max(60.0, window_sec)
    overlap_sec = min(max(0.0, overlap_sec), window_sec / 2)
    total_end = max(s.end for s in segments)
    step = window_sec - overlap_sec

    windows: List[List[TranscriptSegment]] = []
    t0 = min(s.start for s in segments)
    while True:
        t1 = t0 + window_sec
        chunk = [s for s in segments if s.end > t0 and s.start < t1]
        if chunk and (not windows or chunk[-1].id != windows[-1][-1].id):
            windows.append(chunk)
        if t1 >= total_end:
            break
        t0 += step
    return windows


# ----------------------------------------------------------------------
# Ventana deslizante de paso fijo (heurístico)
# ----------------------------------------------------------------------
def sliding_windows(
    segments: List[TranscriptSegment],
    min_duration: float,
    max_duration: float,
    step_sec: float = 10.0,
    lengths: Optional[List[float]] = None,
) -> List[Tuple[int, int]]:
    """Genera ventanas (i, j) de índices de segmentos [i, j] con inicio cada `step_sec`.

    Para cada inicio fijo se prueban varias duraciones objetivo; el fin es el último
    segmento que termina dentro de start + L. Complejidad O((T/paso) · |L| · log n).
    """
    if not segments:
        return []
    lengths = lengths or sorted({min_duration, (min_duration + max_duration) / 2, max_duration})
    starts = [s.start for s in segments]
    ends = [s.end for s in segments]
    t = starts[0]
    t_last = ends[-1]
    seen = set()
    out: List[Tuple[int, int]] = []
    while t + min_duration <= t_last + 1e-6:
        i = bisect.bisect_left(starts, t - 1e-6)
        if i < len(segments):
            for L in lengths:
                # último segmento cuyo fin <= inicio_real + L
                j = bisect.bisect_right(ends, starts[i] + L + 1e-6) - 1
                if j >= i and ends[j] - starts[i] >= min_duration - 1e-6 and (i, j) not in seen:
                    seen.add((i, j))
                    out.append((i, j))
        t += step_sec
    return out


# ----------------------------------------------------------------------
# Ajuste de inicio/fin a pausas
# ----------------------------------------------------------------------
def flatten_words(segments: List[TranscriptSegment]) -> List[WordTimestamp]:
    words: List[WordTimestamp] = []
    for seg in segments:
        words.extend(seg.words)
    return sorted(words, key=lambda w: w.start)


def find_boundaries(words: List[WordTimestamp], min_gap: float = 0.3) -> Tuple[List[float], List[float]]:
    """Devuelve (inicios_validos, finales_validos) a partir de pausas y puntuación.

    Un inicio válido es el comienzo de una palabra precedida por una pausa >= min_gap o por
    fin de oración. Un final válido es el fin de una palabra seguida de pausa o que cierra oración.
    """
    starts: List[float] = []
    ends: List[float] = []
    if not words:
        return starts, ends
    starts.append(words[0].start)
    for prev, nxt in zip(words, words[1:]):
        gap = nxt.start - prev.end
        closes_sentence = prev.word.rstrip().endswith(SENTENCE_END)
        if gap >= min_gap or closes_sentence:
            ends.append(prev.end)
            starts.append(nxt.start)
    ends.append(words[-1].end)
    return starts, ends


def _nearest(value: float, options: List[float], tolerance: float) -> Optional[float]:
    best = None
    best_d = tolerance + 1e-9
    for o in options:
        d = abs(o - value)
        if d <= best_d:
            best, best_d = o, d
    return best


def snap_to_pauses(
    start: float,
    end: float,
    words: List[WordTimestamp],
    tolerance: float = 3.0,
    min_gap: float = 0.3,
    min_duration: float = 0.0,
    max_duration: float = 1e9,
    pad_start: float = 0.10,
    pad_end: float = 0.20,
) -> Tuple[float, float, bool]:
    """Mueve el inicio y el fin a la pausa/fin de oración más cercana (±tolerance s).

    Devuelve (inicio, fin, ajustado). Sin palabras con timestamps no cambia nada.
    Respeta los límites de duración; si el ajuste los violara, conserva el original.
    """
    if not words:
        return start, end, False
    starts, ends = find_boundaries(words, min_gap=min_gap)
    new_start = _nearest(start, starts, tolerance)
    new_end = _nearest(end, ends, tolerance)
    adjusted = new_start is not None or new_end is not None
    s = max(0.0, (new_start if new_start is not None else start) - (pad_start if new_start is not None else 0.0))
    e = (new_end if new_end is not None else end) + (pad_end if new_end is not None else 0.0)
    if e - s < min_duration or e - s > max_duration or e <= s:
        return start, end, False
    return round(s, 2), round(e, 2), adjusted
