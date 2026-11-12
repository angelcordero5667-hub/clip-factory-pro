import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface ViralIntroProps {
  headline?: string;
  durationSec?: number;
}

export const ViralIntroComposition: React.FC<ViralIntroProps> = ({
  headline,
  durationSec = 4.0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (!headline || !headline.trim()) {
    return null;
  }

  const durationFrames = Math.round(durationSec * fps);
  if (frame > durationFrames) {
    return null;
  }

  // Animación de entrada y salida
  const enterSpring = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 180 },
  });

  const exitOpacity = interpolate(
    frame,
    [durationFrames - 15, durationFrames],
    [1.0, 0.0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const scale = interpolate(enterSpring, [0, 1], [0.8, 1.0]);
  const translateY = interpolate(enterSpring, [0, 1], [-50, 0]);

  return (
    <div
      style={{
        position: "absolute",
        top: 140,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        zIndex: 60,
        opacity: exitOpacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
        pointerEvents: "none",
        padding: "0 30px",
      }}
    >
      <div
        style={{
          background: "linear-gradient(135deg, rgba(20,20,30,0.92), rgba(30,15,45,0.95))",
          border: "2px solid #FFE600",
          boxShadow: "0 0 24px rgba(255, 230, 0, 0.45), 0 8px 32px rgba(0,0,0,0.8)",
          borderRadius: 24,
          padding: "16px 36px",
          textAlign: "center",
          maxWidth: 920,
        }}
      >
        <span
          style={{
            fontFamily: "'Impact', 'Montserrat', 'Arial Black', sans-serif",
            fontSize: 48,
            fontWeight: 900,
            color: "#FFE600",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            textShadow: "0 3px 10px rgba(0,0,0,0.9)",
            display: "block",
            lineHeight: 1.2,
          }}
        >
          {headline}
        </span>
      </div>
    </div>
  );
};
