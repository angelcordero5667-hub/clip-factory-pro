"""Recorte de silencios largos y muletillas dentro de un clip (funciones puras, sin FFmpeg).

Se calculan los tramos a CONSERVAR en tiempo absoluto del video. Con ellos:
- FFmpeg corta el video/audio (select + setpts) y une lo que queda.
- Los subtítulos se re-sincronizan con `remap_segments` sobre la nueva línea de tiempo.
"""
import re
import unicodedata
from typing import List, Tuple

from src.common.models import TranscriptSegment, WordTimestamp

Range = Tuple[float, float]

# Solo sonidos de duda inequívocos. "este", "o sea", "pues" son palabras reales: no se tocan.
FILLERS = {"eh", "eeh", "ehh", "em", "emm", "mm", "mmm", "hmm", "hm", "uh", "um", "umm"}


def _norm(word: str) -> str:
    s = unicodedata.normalize("NFD", word.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z]", "", s)


def is_filler(word: str) -> bool:
    return _norm(word) in FILLERS


def _snap(t: float, grid: float) -> float:
    return round(round(t / grid) * grid, 3) if grid > 0 else t


def build_keep_ranges(
    words: List[WordTimestamp],
    start: float,
    end: float,
    max_gap: float = 0.7,
    keep_gap: float = 0.25,
    drop_fillers: bool = True,
    grid: float = 0.04,
    min_saved: float = 0.6,
    max_cut_ratio: float = 0.25,
    min_result: float = 10.0,
) -> List[Range]:
    """Tramos [(s, e), ...] a conservar dentro de [start, end]. Lista vacía = no recortar nada.

    - Pausas entre palabras > max_gap se acortan a keep_gap.
    - Las muletillas (eh, mmm...) se eliminan.
    - Se ignora el recorte si ahorra menos de min_saved s, quita más de max_cut_ratio del clip
      o deja menos de min_result s (para no destrozar un clip).
    """
    inside = sorted((w for w in words if w.end > start and w.start < end), key=lambda w: w.start)
    if len(inside) < 2:
        return []

    cuts: List[Range] = []
    for w in inside:
        if drop_fillers and is_filler(w.word):
            cuts.append((max(start, w.start), min(end, w.end)))
    for prev, nxt in zip(inside, inside[1:]):
        gap = nxt.start - prev.end
        if gap > max_gap:
            trim = gap - keep_gap
            cuts.append((prev.end + keep_gap / 2, prev.end + keep_gap / 2 + trim))

    if not cuts:
        return []

    cuts = [(_snap(a, grid), _snap(b, grid)) for a, b in sorted(cuts)]
    merged: List[Range] = []
    for a, b in cuts:
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    saved = sum(b - a for a, b in merged)
    total = end - start
    if saved < min_saved or saved > total * max_cut_ratio or total - saved < min_result:
        return []

    keep: List[Range] = []
    cursor = start
    for a, b in merged:
        if a - cursor > 0.05:
            keep.append((cursor, a))
        cursor = max(cursor, b)
    if end - cursor > 0.05:
        keep.append((cursor, end))
    return keep


def kept_duration(keep: List[Range]) -> float:
    return sum(b - a for a, b in keep)


def remap_time(t: float, keep: List[Range]) -> float:
    """Tiempo absoluto -> tiempo en el clip ya recortado (los tramos quitados se colapsan)."""
    out = 0.0
    for a, b in keep:
        if t <= a:
            return out
        if t < b:
            return out + (t - a)
        out += b - a
    return out


def remap_segments(segments: List[TranscriptSegment], keep: List[Range]) -> List[TranscriptSegment]:
    """Segmentos con las palabras sobre la nueva línea de tiempo (empieza en 0). Quita lo recortado."""
    def in_keep(w: WordTimestamp) -> bool:
        mid = (w.start + w.end) / 2
        return any(a <= mid <= b for a, b in keep)

    out: List[TranscriptSegment] = []
    for seg in segments:
        words = [
            WordTimestamp(word=w.word, start=round(remap_time(w.start, keep), 3),
                          end=round(max(remap_time(w.end, keep), remap_time(w.start, keep) + 0.05), 3),
                          probability=w.probability)
            for w in seg.words if in_keep(w) and not is_filler(w.word)
        ]
        if not words:
            continue
        out.append(TranscriptSegment(
            id=seg.id, start=words[0].start, end=words[-1].end,
            text=" ".join(w.word.strip() for w in words), words=words))
    return out


def select_expr(keep: List[Range], offset: float) -> str:
    """Expresión de FFmpeg para select/aselect con tiempos relativos al inicio del clip."""
    return "+".join(f"between(t,{max(0.0, a - offset):.3f},{max(0.0, b - offset):.3f})" for a, b in keep)
