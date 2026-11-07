"""Energía del audio por tiempo: ayuda a puntuar momentos con risas, énfasis o discusión animada.

El perfil se normaliza contra el propio video (percentiles 10 y 95), así un podcast tranquilo y
un video ruidoso se comparan igual de bien. Todo es puro NumPy + un FFmpeg que ya existe.
"""
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("AudioEnergy")

SAMPLE_RATE = 16000


@dataclass
class EnergyProfile:
    hop: float            # segundos por valor
    norm: np.ndarray      # 0..1 por tramo, ya normalizado contra el video

    def window_score(self, start: float, end: float) -> float:
        """0..1: mezcla del nivel medio y de los picos (p90) del tramo [start, end]. 0.5 si no hay datos."""
        if len(self.norm) == 0 or end <= start:
            return 0.5
        i = max(0, int(start / self.hop))
        j = min(len(self.norm), max(i + 1, int(np.ceil(end / self.hop))))
        chunk = self.norm[i:j]
        if len(chunk) == 0:
            return 0.5
        return float(0.6 * chunk.mean() + 0.4 * np.percentile(chunk, 90))


def build_profile(samples: np.ndarray, hop: float = 0.5, sample_rate: int = SAMPLE_RATE) -> Optional[EnergyProfile]:
    """Perfil de energía a partir de muestras PCM int16 mono. None si hay muy poco audio."""
    frame = int(hop * sample_rate)
    n = len(samples) // frame
    if n < 4:
        return None
    x = samples[: n * frame].astype(np.float32).reshape(n, frame) / 32768.0
    rms = np.sqrt((x ** 2).mean(axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-9)
    lo, hi = np.percentile(db, 10), np.percentile(db, 95)
    if hi - lo < 1.0:  # audio plano (silencio o volumen constante): no aporta señal
        return EnergyProfile(hop=hop, norm=np.full(n, 0.5, dtype=np.float32))
    return EnergyProfile(hop=hop, norm=np.clip((db - lo) / (hi - lo), 0.0, 1.0).astype(np.float32))


def compute_energy_profile(media_path: str, ffmpeg_exe: str, hop: float = 0.5,
                           timeout: int = 600) -> Optional[EnergyProfile]:
    """Decodifica el audio con FFmpeg (mono, 16 kHz) y devuelve su perfil. None si algo falla."""
    if not media_path or not Path(media_path).is_file():
        return None
    try:
        proc = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-i", str(media_path),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        if proc.returncode != 0 or not proc.stdout:
            return None
        return build_profile(np.frombuffer(proc.stdout, dtype=np.int16), hop=hop)
    except Exception as e:
        logger.warning(f"No se pudo medir la energía del audio: {e}")
        return None


def energy_bonus(score01: float, max_points: float = 8.0) -> float:
    """Puntos a sumar/restar al puntaje de viralidad: de -max_points (apagado) a +max_points (muy animado)."""
    return round((max(0.0, min(1.0, score01)) - 0.5) * 2.0 * max_points, 1)


def find_hype_moments(
    profile: EnergyProfile,
    min_duration: float = 20.0,
    max_duration: float = 60.0,
    top_n: int = 5,
    min_separation: float = 30.0,
) -> list[tuple[float, float, float]]:
    """Encuentra los momentos de mayor volumen/energía (risas, gritos, emoción) en directos/streams.

    Devuelve lista de (start_time, end_time, energy_score_0_to_1) ordenada cronológicamente.
    """
    if not profile or len(profile.norm) == 0:
        return []
    total_seconds = len(profile.norm) * profile.hop
    if total_seconds < min_duration:
        return []

    win_steps = max(1, int(min_duration / profile.hop))
    scores: list[tuple[float, float]] = []
    for i in range(len(profile.norm) - win_steps):
        s = float(profile.norm[i : i + win_steps].mean())
        scores.append((i * profile.hop, s))

    scores.sort(key=lambda x: x[1], reverse=True)
    peaks: list[tuple[float, float, float]] = []

    for t_start, s in scores:
        if any(abs(t_start - p_start) < min_separation for p_start, _, _ in peaks):
            continue
        t_end = min(total_seconds, t_start + min_duration)
        peaks.append((round(t_start, 2), round(t_end, 2), round(s, 3)))
        if len(peaks) >= top_n:
            break

    peaks.sort(key=lambda x: x[0])
    return peaks
