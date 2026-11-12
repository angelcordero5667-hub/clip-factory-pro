import React from "react";
import { Audio, Sequence, useVideoConfig } from "remotion";
import { SoundEffectItem } from "../types";

interface SoundEffectsProps {
  soundEffects?: SoundEffectItem[];
  clipStartSec: number;
}

export const SoundEffectsComposition: React.FC<SoundEffectsProps> = ({
  soundEffects = [],
  clipStartSec,
}) => {
  const { fps } = useVideoConfig();

  // Solo renderizar efectos que tengan una fuente de audio explícita (URL o data URI)
  const validEffects = (soundEffects || []).filter(
    (sfx) => sfx && (sfx as any).src && (
      (sfx as any).src.startsWith("http://") ||
      (sfx as any).src.startsWith("https://") ||
      (sfx as any).src.startsWith("data:")
    )
  );

  if (validEffects.length === 0) {
    return null;
  }

  return (
    <>
      {validEffects.map((sfx, idx) => {
        const relTimeSec = Math.max(0, sfx.timeSec - clipStartSec);
        const fromFrame = Math.round(relTimeSec * fps);
        const durFrames = Math.round(fps * 1.5); // 1.5s por efecto

        return (
          <Sequence
            key={`sfx-${idx}-${sfx.type}`}
            from={fromFrame}
            durationInFrames={durFrames}
          >
            <Audio
              src={(sfx as any).src}
              volume={sfx.volume !== undefined ? sfx.volume : 0.5}
            />
          </Sequence>
        );
      })}
    </>
  );
};
