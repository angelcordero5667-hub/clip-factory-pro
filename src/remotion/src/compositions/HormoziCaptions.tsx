import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SubtitleSegment, SubtitleWord } from "../types";

interface HormoziCaptionsProps {
  subtitles: SubtitleSegment[];
  clipStartSec: number;
  style?: "hormozi" | "neon" | "minimal" | "karaoke" | "boxed";
  position?: "bottom" | "center" | "top";
  fontSize?: number;
  highlightColor?: string;
}

export const HormoziCaptions: React.FC<HormoziCaptionsProps> = ({
  subtitles,
  clipStartSec,
  style = "hormozi",
  position = "bottom",
  fontSize = 62,
  highlightColor = "#FFE600",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeSec = frame / fps;

  // Encontrar el segmento activo para el tiempo actual
  const activeSegment = subtitles.find((s) => {
    const relStart = s.start - clipStartSec;
    const relEnd = s.end - clipStartSec;
    return currentTimeSec >= relStart && currentTimeSec <= relEnd + 0.15;
  });

  if (!activeSegment) {
    return null;
  }

  const words = activeSegment.words && activeSegment.words.length > 0
    ? activeSegment.words
    : activeSegment.text.split(" ").map((w, i, arr) => {
        const segDur = (activeSegment.end - activeSegment.start);
        const wDur = segDur / Math.max(1, arr.length);
        return {
          word: w,
          start: activeSegment.start + i * wDur,
          end: activeSegment.start + (i + 1) * wDur,
        } as SubtitleWord;
      });

  // Posicionamiento en el lienzo vertical 1080x1920
  let bottomPos = "18%";
  if (position === "center") bottomPos = "48%";
  if (position === "top") bottomPos = "76%";

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: bottomPos,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        flexWrap: "wrap",
        padding: "0 40px",
        zIndex: 50,
        pointerEvents: "none",
        textAlign: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "12px 14px",
          maxWidth: 980,
        }}
      >
        {words.map((w, idx) => {
          const relWordStart = w.start - clipStartSec;
          const relWordEnd = w.end - clipStartSec;
          const isSpoken = currentTimeSec >= relWordStart && currentTimeSec <= relWordEnd + 0.08;
          const isPast = currentTimeSec > relWordEnd + 0.08;

          // Animación de entrada por palabra con spring
          const wordFrameOffset = Math.max(0, Math.round(relWordStart * fps));
          const animSpring = spring({
            frame: frame - wordFrameOffset,
            fps,
            config: { damping: 12, stiffness: 220, mass: 0.5 },
          });

          const scale = isSpoken
            ? interpolate(animSpring, [0, 1], [0.85, 1.15])
            : 1.0;

          // Estilos según el modo
          let textColor = "#FFFFFF";
          let textShadow = "0 4px 14px rgba(0,0,0,0.9), 0 0 2px #000, 0 0 8px #000";
          let bgColor = "transparent";
          let borderRadius = 0;
          let padding = "0 4px";

          if (style === "hormozi") {
            textColor = isSpoken ? highlightColor : "#FFFFFF";
            textShadow = isSpoken
              ? `0 0 16px ${highlightColor}88, 0 4px 12px #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 3px 3px 0 #000`
              : "0 4px 12px #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 3px 3px 0 #000";
          } else if (style === "neon") {
            const neonCol = isSpoken ? "#00F5FF" : "#FFFFFF";
            textColor = neonCol;
            textShadow = isSpoken
              ? "0 0 20px #00F5FF, 0 0 35px #00F5FF, 0 3px 10px #000"
              : "0 0 8px rgba(255,255,255,0.4), 0 3px 8px #000";
          } else if (style === "boxed") {
            textColor = isSpoken ? "#000000" : "#FFFFFF";
            bgColor = isSpoken ? highlightColor : "rgba(0,0,0,0.7)";
            borderRadius = 10;
            padding = "4px 12px";
            textShadow = isSpoken ? "none" : "0 2px 6px #000";
          }

          return (
            <span
              key={`${w.word}-${idx}`}
              style={{
                fontFamily: "'Impact', 'Montserrat', 'Arial Black', sans-serif",
                fontSize: `${fontSize}px`,
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
                color: textColor,
                backgroundColor: bgColor,
                borderRadius: `${borderRadius}px`,
                padding,
                textShadow,
                transform: `scale(${scale})`,
                transition: "color 0.08s ease, transform 0.08s ease",
                display: "inline-block",
                lineHeight: 1.15,
                opacity: isPast ? 0.75 : 1.0,
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </div>
  );
};
