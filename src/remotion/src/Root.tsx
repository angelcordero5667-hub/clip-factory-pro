import React from "react";
import { Composition } from "remotion";
import { ViralShortComposition } from "./compositions/ViralShortComposition";
import { HormoziCaptions } from "./compositions/HormoziCaptions";
import { PunchZoom } from "./compositions/PunchZoom";
import { SplitScreenComposition } from "./compositions/SplitScreenComposition";
import { FaceTrackingComposition } from "./compositions/FaceTrackingComposition";
import { ViralIntroComposition } from "./compositions/ViralIntroComposition";
import { SoundEffectsComposition } from "./compositions/SoundEffectsComposition";
import { DynamicTransitions } from "./compositions/DynamicTransitions";
import { ViralShortProps } from "./types";

export const RemotionRoot: React.FC = () => {
  const defaultProps: ViralShortProps = {
    videoSrc: "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    clipStartSec: 0,
    clipEndSec: 30,
    durationInFrames: 900,
    fps: 30,
    width: 1080,
    height: 1920,
    subtitles: [
      {
        id: 1,
        start: 0.5,
        end: 2.8,
        text: "ESTE ES EL SECRETO MILLONARIO",
        words: [
          { word: "ESTE", start: 0.5, end: 0.9 },
          { word: "ES", start: 0.9, end: 1.2 },
          { word: "EL", start: 1.2, end: 1.5 },
          { word: "SECRETO", start: 1.5, end: 2.1, highlight: true },
          { word: "MILLONARIO", start: 2.1, end: 2.8, highlight: true },
        ],
      },
    ],
    subtitleStyle: "hormozi",
    subtitlePosition: "bottom",
    subtitleFontSize: 62,
    customHighlightColor: "#FFE600",
    framingMode: "blur",
    punchZoom: true,
    hookHeadline: "🔥 ¿SABÍAS ESTO? 👀",
    colorFilter: "pop",
    progressBar: true,
  };

  return (
    <>
      <Composition
        id="ViralShortComposition"
        component={ViralShortComposition}
        durationInFrames={900}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultProps}
        // La duración, fps y tamaño salen de las props de cada clip. Sin esto, cualquier clip de más
        // de 30 s fallaba ("frame range 0-1409 is not inbetween 0-899").
        calculateMetadata={(({ props }: { props: ViralShortProps }) => ({
          durationInFrames: Math.max(1, Math.round(props.durationInFrames ?? 900)),
          fps: props.fps ?? 30,
          width: props.width ?? 1080,
          height: props.height ?? 1920,
        })) as any}
      />
      <Composition
        id="HormoziCaptions"
        component={HormoziCaptions as any}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          subtitles: defaultProps.subtitles,
          clipStartSec: 0,
        }}
      />
      <Composition
        id="SplitScreenComposition"
        component={SplitScreenComposition as any}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          videoSrc: defaultProps.videoSrc,
          splitRatio: 0.5,
        }}
      />
      <Composition
        id="FaceTrackingComposition"
        component={FaceTrackingComposition as any}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          videoSrc: defaultProps.videoSrc,
          trackingPoints: [],
        }}
      />
      <Composition
        id="ViralIntroComposition"
        component={ViralIntroComposition as any}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          headline: "🔴 EXCLUSIVA | VIRAL SHORTS",
        }}
      />
      <Composition
        id="SoundEffectsComposition"
        component={SoundEffectsComposition as any}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          soundEffects: [{ type: "whoosh", timeSec: 0.2 }],
          clipStartSec: 0,
        }}
      />
      <Composition
        id="DynamicTransitions"
        component={DynamicTransitions as any}
        durationInFrames={60}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          transitionFrames: [15],
        }}
      />
    </>
  );
};
