import React from "react";
import { OffthreadVideo, staticFile } from "remotion";

interface SplitScreenCompositionProps {
  videoSrc: string;
  trimBefore?: number; // frame del video fuente donde empieza el clip
  splitRatio?: number; // 0.5 por defecto (50% superior, 50% inferior)
  splitXs?: [number, number]; // Posiciones X relativas de los dos hablantes
  dividerColor?: string;
  width?: number;
  height?: number;
}

export const SplitScreenComposition: React.FC<SplitScreenCompositionProps> = ({
  videoSrc,
  trimBefore = 0,
  splitRatio = 0.5,
  splitXs = [0.25, 0.75],
  dividerColor = "#A855F7",
  width = 1080,
  height = 1920,
}) => {
  const topHeight = Math.round(height * splitRatio);
  const bottomHeight = height - topHeight;

  // Calculamos el desplazamiento horizontal para encuadrar cada persona
  // Si splitXs[0] es 0.25 (persona a la izquierda), centramos en x: 25%
  const topShiftX = -(splitXs[0] * 100 - 50);
  const botShiftX = -(splitXs[1] * 100 - 50);

  return (
    <div
      style={{
        width,
        height,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        position: "relative",
        backgroundColor: "#000000",
      }}
    >
      {/* Panel Superior: Hablante 1 */}
      <div
        style={{
          width: "100%",
          height: topHeight,
          overflow: "hidden",
          position: "relative",
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
            transform: `translate(calc(-50% + ${topShiftX}px), -50%)`,
          }}
        />
      </div>

      {/* Línea divisoria de Neón */}
      <div
        style={{
          width: "100%",
          height: 8,
          backgroundColor: dividerColor,
          boxShadow: `0 0 16px ${dividerColor}, 0 0 30px ${dividerColor}`,
          zIndex: 40,
          position: "relative",
          margin: "-4px 0",
        }}
      >
        <div
          style={{
            width: "100%",
            height: 2,
            backgroundColor: "#FFFFFF",
            opacity: 0.9,
            marginTop: 3,
          }}
        />
      </div>

      {/* Panel Inferior: Hablante 2 */}
      <div
        style={{
          width: "100%",
          height: bottomHeight,
          overflow: "hidden",
          position: "relative",
        }}
      >
        <OffthreadVideo
          src={videoSrc}
          trimBefore={trimBefore}
          muted
          style={{
            width: "auto",
            height: "100%",
            minWidth: "100%",
            objectFit: "cover",
            position: "absolute",
            left: "50%",
            top: "50%",
            transform: `translate(calc(-50% + ${botShiftX}px), -50%)`,
          }}
        />
      </div>
    </div>
  );
};
