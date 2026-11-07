from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    probability: float = 1.0

class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: List[WordTimestamp] = Field(default_factory=list)

class TranscriptResult(BaseModel):
    video_path: str
    language: str
    duration: float
    segments: List[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""

class ViralityBreakdown(BaseModel):
    hook_score: float = Field(default=85.0, ge=0.0, le=100.0)
    flow_score: float = Field(default=85.0, ge=0.0, le=100.0)
    trend_score: float = Field(default=80.0, ge=0.0, le=100.0)

class ViralMomentCandidate(BaseModel):
    id: str
    start_time: float
    end_time: float
    duration: float
    title: str = ""                       # Título viral generado estilo OpusClip
    hook_text: str                        # Primeros 3 segundos
    context_text: str                     # Contexto completo
    virality_score: float = Field(ge=0.0, le=100.0)  # Puntuación estilo OpusClip (0-100)
    breakdown: ViralityBreakdown = Field(default_factory=ViralityBreakdown)
    category: str                         # humor, discusion, reaccion, sorpresa, ensenanza
    reasoning: str                        # Explicación de por qué es viral
    social_description: str = ""          # Copy listo para TikTok/Reels/Shorts
    hashtags: List[str] = Field(default_factory=list)
    status: str = "pending"               # pending, approved, rejected
    clip_path: Optional[str] = None
    engine: str = "heuristic"             # llm | heuristic: motor que produjo el candidato
    pause_aligned: bool = False           # inicio/fin ajustados a pausas del habla


def parse_time_str(val: Optional[object]) -> Optional[float]:
    """Convierte '01:25:30', '90:00', '45', 120 en segundos flotantes."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    s = str(val).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return max(0.0, float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
        elif len(parts) == 2:
            return max(0.0, float(parts[0]) * 60 + float(parts[1]))
        elif len(parts) == 1:
            return max(0.0, float(parts[0]))
    except ValueError:
        return None
    return None
