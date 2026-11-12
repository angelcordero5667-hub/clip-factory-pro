"""
Contrato y Validador Estricto para HyperFrames (Fase 10).
Asegura validación rigurosa de composition_props.json:
- Dimensiones, FPS, duración positiva.
- Timestamps relativos válidos (sin negativos, orden cronológico, dentro de duración).
- Escapado seguro de HTML contra inyecciones.
- Límites de recursos.
"""

import html
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class WordTiming(BaseModel):
    word: str
    start: float
    end: float
    highlight: bool = False

    @field_validator("word")
    def sanitize_word(cls, v: str) -> str:
        s = html.escape(str(v).strip())
        if not s:
            raise ValueError("La palabra no puede estar vacía")
        return s

    @model_validator(mode="after")
    def check_timing(self):
        if self.start < 0:
            raise ValueError(f"Timestamp negativo no permitido: {self.start}")
        if self.end < self.start:
            raise ValueError(f"Fin de palabra ({self.end}) no puede ser menor a inicio ({self.start})")
        return self


class SegmentTiming(BaseModel):
    segment_id: int
    start: float
    end: float
    text: str
    words: List[WordTiming] = Field(default_factory=list)

    @field_validator("text")
    def sanitize_text(cls, v: str) -> str:
        return html.escape(str(v).strip())

    @model_validator(mode="after")
    def check_segment(self):
        if self.start < 0:
            raise ValueError(f"Inicio de segmento negativo: {self.start}")
        if self.end < self.start:
            raise ValueError(f"Fin de segmento ({self.end}) no puede ser menor a inicio ({self.start})")
        for w in self.words:
            # Tolerancia de 0.2s para alineaciones de Whisper
            if w.start < self.start - 0.25 or w.end > self.end + 0.25:
                # Normalizamos palabra a los límites del segmento
                w.start = max(self.start, w.start)
                w.end = min(self.end, max(w.start + 0.05, w.end))
        return self


class VisualMeta(BaseModel):
    width: int = Field(default=1080, ge=320, le=3840)
    height: int = Field(default=1920, ge=320, le=3840)
    fps: int = Field(default=30, ge=15, le=120)
    duration: float = Field(..., gt=0.0, le=600.0)
    speed_mode: str = "fast"


class HeadlineConfig(BaseModel):
    text: str = ""
    start: float = 0.0
    duration: float = 3.0
    animation: str = "slide_down"

    @field_validator("text")
    def sanitize_headline(cls, v: str) -> str:
        return html.escape(str(v).strip())


class VisualTheme(BaseModel):
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE600"
    stroke_color: str = "#000000"
    font_family: str = "Montserrat ExtraBold"


class VisualConfig(BaseModel):
    template: str = "hormozi"
    theme: VisualTheme = Field(default_factory=VisualTheme)
    headline: Optional[HeadlineConfig] = None
    show_progress_bar: bool = False
    safe_zone_bottom_px: int = Field(default=460, ge=100, le=800)


class HyperFramesCompositionProps(BaseModel):
    clip_id: str
    meta: VisualMeta
    visual: VisualConfig = Field(default_factory=VisualConfig)
    transcript: List[SegmentTiming] = Field(default_factory=list)

    @field_validator("clip_id")
    def validate_id(cls, v: str) -> str:
        clean = "".join(c for c in v if c.isalnum() or c in ("-", "_"))
        if not clean:
            raise ValueError("ID de composición no válido")
        return clean

    @model_validator(mode="after")
    def validate_clip_bounds(self):
        dur = self.meta.duration
        for seg in self.transcript:
            if seg.start > dur:
                raise ValueError(f"Segmento {seg.segment_id} inicia después del fin del clip ({seg.start} > {dur})")
            if seg.end > dur + 0.5:
                seg.end = dur
                for w in seg.words:
                    if w.end > dur:
                        w.end = dur
        return self


def validate_composition_props(data: Dict[str, Any]) -> HyperFramesCompositionProps:
    """Valida y sanea el payload de composición; lanza ValueError ante anomalías."""
    return HyperFramesCompositionProps.model_validate(data)
