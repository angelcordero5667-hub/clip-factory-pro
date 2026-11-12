export interface SubtitleWord {
  word: string;
  start: number; // segundos
  end: number;   // segundos
  highlight?: boolean;
  color?: string;
}

export interface SubtitleSegment {
  id: number | string;
  start: number;
  end: number;
  text: string;
  words?: SubtitleWord[];
}

export interface SoundEffectItem {
  type: "whoosh" | "pop" | "impact" | "bass_drop";
  timeSec: number;
  volume?: number;
}

export interface SpeakerTrackPoint {
  timeSec: number;
  xNormalized: number; // 0.0 a 1.0 (centro del rostro en X)
  yNormalized: number; // 0.0 a 1.0 (centro del rostro en Y)
}

export interface ViralShortProps {
  // Fuentes de medios
  videoSrc: string; // URL o ruta relativa/absoluta
  audioSrc?: string;
  title?: string;

  // Parámetros de tiempo y corte
  clipStartSec: number;
  clipEndSec: number;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;

  // Subtítulos
  subtitles: SubtitleSegment[];
  subtitleStyle?: "hormozi" | "neon" | "minimal" | "karaoke" | "boxed";
  subtitlePosition?: "bottom" | "center" | "top";
  subtitleFontSize?: number;
  customHighlightColor?: string;

  // Encuadre y Tracking
  framingMode?: "blur" | "crop" | "split" | "gaming";
  splitRatio?: number; // 0.5 por defecto
  splitXs?: [number, number]; // coordenadas x de los dos hablantes
  faceTrackingPoints?: SpeakerTrackPoint[];

  // Efectos Anti-Swipe y Retención
  punchZoom?: boolean;
  punchZoomStartSec?: number;
  punchZoomDurationSec?: number;
  punchZoomScale?: number; // 1.12 a 1.25

  dynamicZoom?: boolean;
  hookHeadline?: string;
  colorFilter?: "none" | "pop" | "cinema" | "warm" | "vignette";
  progressBar?: boolean;
  progressBarColor?: string;

  // Audio & SFX
  soundEffects?: SoundEffectItem[];
  enableSfx?: boolean;
}
