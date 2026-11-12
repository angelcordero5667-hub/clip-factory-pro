import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface DynamicTransitionsProps {
  transitionFrames?: number[];
  type?: "flash" | "whip" | "zoom_bump";
}

export const DynamicTransitions: React.FC<DynamicTransitionsProps> = ({
  transitionFrames = [],
  type = "flash",
}) => {
  const frame = useCurrentFrame();

  // Buscar si estamos dentro de alguna ventana de transición (duración 6 frames ~ 0.2s)
  const activeCut = transitionFrames.find((f) => Math.abs(frame - f) <= 4);

  if (activeCut === undefined) {
    return null;
  }

  const dist = Math.abs(frame - activeCut);
  const intensity = interpolate(dist, [0, 4], [1.0, 0.0], {
    extrapolateRight: "clamp",
  });

  if (type === "flash") {
    return (
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "#FFFFFF",
          opacity: intensity * 0.75,
          pointerEvents: "none",
          zIndex: 80,
        }}
      />
    );
  }

  if (type === "whip") {
    const shiftX = (frame - activeCut) * 40;
    return (
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "linear-gradient(90deg, rgba(0,0,0,0.8), rgba(255,255,255,0.4), rgba(0,0,0,0.8))",
          transform: `translateX(${shiftX}px)`,
          opacity: intensity * 0.8,
          pointerEvents: "none",
          zIndex: 80,
        }}
      />
    );
  }

  return null;
};
