import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface PunchZoomProps {
  children: React.ReactNode;
  enabled?: boolean;
  startSec?: number;
  durationSec?: number;
  maxScale?: number;
  dynamicPulses?: boolean;
}

export const PunchZoom: React.FC<PunchZoomProps> = ({
  children,
  enabled = true,
  startSec = 0,
  durationSec = 2.5,
  maxScale = 1.15,
  dynamicPulses = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (!enabled) {
    return <>{children}</>;
  }

  const startFrame = Math.round(startSec * fps);
  const durationFrames = Math.round(durationSec * fps);
  const endFrame = startFrame + durationFrames;

  let currentScale = 1.0;

  if (frame >= startFrame && frame <= endFrame) {
    // Zoom inicial con retorno progresivo
    const progress = (frame - startFrame) / durationFrames;
    if (progress < 0.25) {
      // Entrada rápida de zoom
      currentScale = interpolate(progress, [0, 0.25], [1.0, maxScale], {
        extrapolateRight: "clamp",
      });
    } else {
      // Retorno suave a 1.0x
      currentScale = interpolate(progress, [0.25, 1.0], [maxScale, 1.0], {
        extrapolateRight: "clamp",
      });
    }
  } else if (dynamicPulses) {
    // Pulsos periódicos cada 8 segundos para mantener la retención
    const cycleFrames = fps * 8;
    const pulseFrame = frame % cycleFrames;
    if (pulseFrame < fps * 1.5) {
      const p = pulseFrame / (fps * 1.5);
      currentScale = interpolate(p, [0, 0.3, 1], [1.0, 1.08, 1.0], {
        extrapolateRight: "clamp",
      });
    }
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        transform: `scale(${currentScale})`,
        transformOrigin: "center center",
        transition: "transform 0.05s ease-out",
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
};
