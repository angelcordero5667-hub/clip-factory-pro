"""Análisis de actividad y marcadores de chat en streams (Twitch / YouTube Live).

Mide la velocidad de mensajes por segundo (ráfagas) y la densidad de emotes virales
('LUL', 'KEKW', 'OMG', 'POG', 'CLIP', '????', '🔥') como señal de viralidad en directos.
"""
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

import numpy as np

logger = logging.getLogger("ChatActivity")

HYPE_TOKEN_REGEX = re.compile(
    r"\b(lul|lol|kekw|omg|pog|poggers|clip|clippealo|clip\s*it|jaja|xd|wtfff?|wtf|no\s*way|holy|sheesh|goat|rip|f|khe|watafak)\b|"
    r"[?]{2,}|[!]{2,}|[😂🤣🔥💀😱🤯👏💥]",
    re.IGNORECASE,
)


@dataclass
class ChatMessage:
    t: float        # segundo relativo al inicio del video
    text: str       # contenido textual del mensaje


@dataclass
class ChatActivityProfile:
    hop: float            # resolución temporal en segundos
    norm: np.ndarray      # intensidad normalizada 0..1 por paso
    total_messages: int = 0

    def window_score(self, start: float, end: float) -> float:
        """Devuelve intensidad media 0..1 del tramo [start, end]. 0.5 si no hay datos."""
        if len(self.norm) == 0 or end <= start:
            return 0.5
        i = max(0, int(start / self.hop))
        j = min(len(self.norm), max(i + 1, int(np.ceil(end / self.hop))))
        chunk = self.norm[i:j]
        if len(chunk) == 0:
            return 0.5
        # Combinar promedio y pico percentil 90
        return float(0.6 * chunk.mean() + 0.4 * np.percentile(chunk, 90))


def parse_chat_messages(source: Union[str, Path, List[Any], dict]) -> List[ChatMessage]:
    """Parsea mensajes de chat desde archivo o estructura en memoria.
    
    Soporta:
    - Lista de dicts [{'time': 12.3, 'text': 'OMG'}, ...]
    - Twitch VOD export ('comments': [{'content_offset_seconds': ..., 'message': {'body': ...}}])
    - YouTube live chat JSONL (yt-dlp .live_chat.json)
    """
    raw_list: List[Any] = []
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.exists():
            return []
        try:
            content = p.read_text(encoding="utf-8", errors="ignore").strip()
            if not content:
                return []
            try:
                obj = json.loads(content)
                if isinstance(obj, list):
                    raw_list = obj
                elif isinstance(obj, dict):
                    if "comments" in obj and isinstance(obj["comments"], list):
                        raw_list = obj["comments"]
                    else:
                        raw_list = [obj]
            except json.JSONDecodeError:
                # Archivo JSON Lines (un JSON por línea)
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        try:
                            raw_list.append(json.loads(line))
                        except Exception:
                            continue
        except Exception as e:
            logger.warning(f"Error leyendo archivo de chat {source}: {e}")
            return []
    elif isinstance(source, list):
        raw_list = source
    elif isinstance(source, dict):
        if "comments" in source and isinstance(source["comments"], list):
            raw_list = source["comments"]
        else:
            raw_list = [source]

    messages: List[ChatMessage] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        
        t: Optional[float] = None
        text: str = ""

        # Formato directo {'time'/'t'/'offset', 'text'/'message'/'body'}
        for time_key in ("time", "t", "offset", "time_offset", "content_offset_seconds", "offset_seconds"):
            if time_key in item:
                try:
                    t = float(item[time_key])
                    break
                except (ValueError, TypeError):
                    pass

        # Formato yt-dlp live chat
        if t is None and "replayChatItemAction" in item:
            try:
                actions = item["replayChatItemAction"].get("actions", [])
                for act in actions:
                    render = act.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer", {})
                    if "videoOffsetTimeMsec" in item["replayChatItemAction"]:
                        t = float(item["replayChatItemAction"]["videoOffsetTimeMsec"]) / 1000.0
                    runs = render.get("message", {}).get("runs", [])
                    text = "".join(r.get("text", "") for r in runs)
                    if t is not None and text:
                        break
            except Exception:
                pass

        # Formato Twitch VOD comments
        if text == "":
            msg_obj = item.get("message")
            if isinstance(msg_obj, dict):
                text = str(msg_obj.get("body") or "")
            elif isinstance(msg_obj, str):
                text = msg_obj
            else:
                text = str(item.get("text") or item.get("body") or "")

        if t is not None and t >= 0:
            messages.append(ChatMessage(t=round(t, 2), text=text.strip()))

    messages.sort(key=lambda m: m.t)
    return messages


def build_chat_profile(
    messages: Sequence[ChatMessage],
    duration: Optional[float] = None,
    hop: float = 2.0,
    window_sec: float = 15.0,
) -> Optional[ChatActivityProfile]:
    """Construye un perfil temporal de actividad y hype en el chat (0..1).
    
    Combina:
    1. Ráfaga de mensajes (volumen por segundo en ventana deslizante).
    2. Proporción de mensajes que contienen emotes o palabras de reacción viral (LUL, OMG, POG, ????).
    """
    if not messages:
        return None

    max_t = max(m.t for m in messages)
    total_dur = max(duration or 0.0, max_t + hop)
    if total_dur < window_sec:
        return None

    n_steps = int(np.ceil(total_dur / hop))
    if n_steps < 3:
        return None

    times = [m.t for m in messages]
    is_hype = [bool(HYPE_TOKEN_REGEX.search(m.text)) for m in messages]

    half_win = window_sec / 2.0
    scores = np.zeros(n_steps, dtype=np.float32)

    # Cálculo por paso temporal
    idx_start = 0
    idx_end = 0
    n_msg = len(messages)

    for step in range(n_steps):
        t_center = step * hop
        t_lo = max(0.0, t_center - half_win)
        t_hi = t_center + half_win

        while idx_start < n_msg and times[idx_start] < t_lo:
            idx_start += 1
        while idx_end < n_msg and times[idx_end] <= t_hi:
            idx_end += 1

        window_count = idx_end - idx_start
        if window_count > 0:
            hype_count = sum(is_hype[idx_start:idx_end])
            velocity = window_count / window_sec
            hype_ratio = hype_count / window_count
            # Puntuación combinada: volumen + multiplicador por emotes virales
            scores[step] = velocity * (1.0 + 1.5 * hype_ratio)
        else:
            scores[step] = 0.0

    lo, hi = np.percentile(scores, 15), np.percentile(scores, 95)
    if hi - lo < 1e-4:
        norm = np.full(n_steps, 0.5, dtype=np.float32)
    else:
        norm = np.clip((scores - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)

    return ChatActivityProfile(hop=hop, norm=norm, total_messages=len(messages))


def find_chat_hype_peaks(
    profile: ChatActivityProfile,
    min_duration: float = 20.0,
    max_duration: float = 60.0,
    top_n: int = 5,
    min_separation: float = 30.0,
) -> List[Tuple[float, float, float]]:
    """Detecta los momentos donde el chat explotó en mensajes y risas/emoción.
    
    Devuelve lista de (start_time, end_time, intensity_score_0_to_1) ordenada cronológicamente.
    """
    if not profile or len(profile.norm) == 0:
        return []
    total_seconds = len(profile.norm) * profile.hop
    if total_seconds < min_duration:
        return []

    win_steps = max(1, int(min_duration / profile.hop))
    scores: List[Tuple[float, float]] = []
    for i in range(len(profile.norm) - win_steps):
        s = float(profile.norm[i : i + win_steps].mean())
        scores.append((i * profile.hop, s))

    scores.sort(key=lambda x: x[1], reverse=True)
    peaks: List[Tuple[float, float, float]] = []

    for t_start, s in scores:
        if any(abs(t_start - p_start) < min_separation for p_start, _, _ in peaks):
            continue
        dur = min_duration
        step_dur = 5.0
        while dur + step_dur <= max_duration:
            next_steps = int((dur + step_dur) / profile.hop)
            idx_start = int(t_start / profile.hop)
            if idx_start + next_steps > len(profile.norm):
                break
            expanded_score = float(profile.norm[idx_start : idx_start + next_steps].mean())
            if expanded_score >= s * 0.75:
                dur += step_dur
            else:
                break
        t_end = min(total_seconds, t_start + dur)
        peaks.append((round(t_start, 2), round(t_end, 2), round(s, 3)))
        if len(peaks) >= top_n:
            break

    peaks.sort(key=lambda x: x[0])
    return peaks


def chat_bonus(score01: float, max_points: float = 8.0) -> float:
    """Calcula bono de puntaje de viralidad según la actividad del chat (-max a +max)."""
    return round((max(0.0, min(1.0, score01)) - 0.5) * 2.0 * max_points, 1)
