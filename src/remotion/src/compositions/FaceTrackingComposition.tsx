import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig, OffthreadVideo } from "remotion";
import { SpeakerTrackPoint } from "../types";

interface FaceTrackingCompositionProps {
  videoSrc: string;
  trimBefore?: number; // frame del video fuente donde empieza el clip
  trackingPoints?: SpeakerTrackPoint[];
  width?: number;
  height?: number;
}

export const FaceTrackingComposition: React.FC<FaceTrackingCompositionProps> = ({
  videoSrc,
  trimBefore = 0,
  trackingPoints = [],
  width = 1080,
  height = 1920,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeSec = frame / fps;

  // Si no hay puntos de tracking, centramos por defecto
  let currentTargetX = 0.5;

  if (trackingPoints.length > 0) {
    // Buscar los dos puntos de tracking más cercanos en el tiempo para interpolar
    const prevPoint = [...trackingPoints]
      .reverse()
      .find((p) => p.timeSec <= currentTimeSec) || trackingPoints[0];
    const nextPoint = trackingPoints.find((p) => p.timeSec > currentTimeSec) || prevPoint;

    if (prevPoint === nextPoint || nextPoint.timeSec === prevPoint.timeSec) {
      currentTargetX = prevPoint.xNormalized;
    } else {
      const p = (currentTimeSec - prevPoint.timeSec) / (nextPoint.timeSec - prevPoint.timeSec);
      currentTargetX = interpolate(p, [0, 1], [prevPoint.xNormalized, nextPoint.xNormalized], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
  }

  // Desplazamiento horizontal de cámara suave
  // Rango: si targetX es 0.2 (hablante a la izquierda), la imagen se mueve a la derecha
  const shiftPercent = (0.5 - currentTargetX) * 80;

  return (
    <div
      style={{
        width,
        height,
        position: "relative",
        overflow: "hidden",
        backgroundColor: "#000000",
      }}
    >
      <OffthreadVideo
        src={videoSrc}
        trimBefore={trimBefore}
        style={{
          width: "auto",
          height: "100%",
          minWidth: "100%",
          objectFit: "cover",
          position: "absolute",
          left: "50%",
          top: "50%",
          transform: `translate(calc(-50% + ${shiftPercent}%), -50%) scale(1.05)`,
          transition: "transform 0.15s ease-out",
        }}
      />
    </div>
  );
};
