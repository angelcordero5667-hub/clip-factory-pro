import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  staticFile,
} from "remotion";
import { ViralShortProps } from "../types";
import { HormoziCaptions } from "./HormoziCaptions";
import { PunchZoom } from "./PunchZoom";
import { SplitScreenComposition } from "./SplitScreenComposition";
import { FaceTrackingComposition } from "./FaceTrackingComposition";
import { ViralIntroComposition } from "./ViralIntroComposition";
import { SoundEffectsComposition } from "./SoundEffectsComposition";
import { DynamicTransitions } from "./DynamicTransitions";

export const resolveMediaSource = (src: string): string => {
  if (!src) return "";
  if (
    src.startsWith("http://") ||
    src.startsWith("https://") ||
    src.startsWith("data:") ||
    src.startsWith("blob:") ||
    src.startsWith("file://")
  ) {
    return src;
  }
  try {
    return staticFile(src);
  } catch {
    return src;
  }
};

export const ViralShortComposition: React.FC<ViralShortProps> = ({
  videoSrc,
  clipStartSec = 0,
  clipEndSec = 30,
  subtitles = [],
  subtitleStyle = "hormozi",
  subtitlePosition = "bottom",
  subtitleFontSize = 62,
  customHighlightColor = "#FFE600",
  framingMode = "blur",
  splitRatio = 0.5,
  splitXs = [0.25, 0.75],
  faceTrackingPoints = [],
  punchZoom = true,
  punchZoomStartSec = 0,
  punchZoomDurationSec = 2.5,
  punchZoomScale = 1.15,
  dynamicZoom = false,
  hookHeadline,
  colorFilter = "pop",
  progressBar = true,
  progressBarColor = "#A855F7",
  soundEffects = [],
  enableSfx = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const resolvedSrc = resolveMediaSource(videoSrc);
  // El video fuente es el original completo: hay que empezar en el inicio del clip, no en 0:00.
  const trimFrames = Math.max(0, Math.round(clipStartSec * fps));

  // Filtros de color CSS
  let filterCss = "none";
  if (colorFilter === "pop") {
    filterCss = "contrast(1.12) saturate(1.25) brightness(1.02)";
  } else if (colorFilter === "cinema") {
    filterCss = "contrast(1.18) saturate(0.92) sepia(0.08)";
  } else if (colorFilter === "warm") {
    filterCss = "sepia(0.18) saturate(1.15) brightness(1.03)";
  }

  // Render del fondo según el modo de encuadre
  const renderVideoLayer = () => {
    if (framingMode === "split") {
      return (
        <SplitScreenComposition
          videoSrc={resolvedSrc}
          trimBefore={trimFrames}
          splitRatio={splitRatio}
          splitXs={splitXs}
          width={width}
          height={height}
        />
      );
    }

    if (framingMode === "crop" && faceTrackingPoints.length > 0) {
      return (
        <FaceTrackingComposition
          videoSrc={resolvedSrc}
          trimBefore={trimFrames}
          trackingPoints={faceTrackingPoints}
          width={width}
          height={height}
        />
      );
    }

    // Modo Blur (Fondo desenfocado + Video original centrado 9:16)
    return (
      <AbsoluteFill style={{ backgroundColor: "#000000" }}>
        {/* Fondo desenfocado 270x480 reescalado a pantalla completa */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            overflow: "hidden",
            filter: "blur(40px) brightness(0.42)",
            transform: "scale(1.15)",
          }}
        >
          <OffthreadVideo
            src={resolvedSrc}
            trimBefore={trimFrames}
            muted
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
        </div>

        {/* Video nítido centrado manteniendo relación de aspecto */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 10,
          }}
        >
          <OffthreadVideo
            src={resolvedSrc}
            trimBefore={trimFrames}
            style={{
              maxWidth: "100%",
              maxHeight: "100%",
              objectFit: "contain",
              filter: filterCss,
              borderRadius: 16,
              boxShadow: "0 10px 40px rgba(0,0,0,0.85)",
            }}
          />
        </div>
      </AbsoluteFill>
    );
  };

  // Barra de progreso inferior
  const progressPercent = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#000000",
        width,
        height,
        overflow: "hidden",
      }}
    >
      {/* Capa de video con PunchZoom */}
      <PunchZoom
        enabled={punchZoom}
        startSec={punchZoomStartSec}
        durationSec={punchZoomDurationSec}
        maxScale={punchZoomScale}
        dynamicPulses={dynamicZoom}
      >
        {renderVideoLayer()}
      </PunchZoom>

      {/* Viñeta opcional */}
      {colorFilter === "vignette" && (
        <AbsoluteFill
          style={{
            background: "radial-gradient(circle, transparent 55%, rgba(0,0,0,0.85) 100%)",
            pointerEvents: "none",
            zIndex: 30,
          }}
        />
      )}

      {/* Gancho de inicio (Headline) */}
      <ViralIntroComposition headline={hookHeadline} durationSec={3.5} />

      {/* Subtítulos Hormozi sincronizados por palabra */}
      <HormoziCaptions
        subtitles={subtitles}
        clipStartSec={clipStartSec}
        style={subtitleStyle}
        position={subtitlePosition}
        fontSize={subtitleFontSize}
        highlightColor={customHighlightColor}
      />

      {/* Transiciones dinámicas */}
      <DynamicTransitions transitionFrames={[0, 90, 180]} type="flash" />

      {/* Efectos de sonido */}
      {enableSfx && (
        <SoundEffectsComposition
          soundEffects={soundEffects}
          clipStartSec={clipStartSec}
        />
      )}

      {/* Barra de progreso inferior */}
      {progressBar && (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 10,
            backgroundColor: "rgba(255,255,255,0.22)",
            zIndex: 90,
          }}
        >
          <div
            style={{
              height: "100%",
              width: `${progressPercent}%`,
              backgroundColor: progressBarColor,
              boxShadow: `0 0 12px ${progressBarColor}`,
            }}
          />
        </div>
      )}
    </AbsoluteFill>
  );
};
