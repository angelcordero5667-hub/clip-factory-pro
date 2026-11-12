import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { Player, PlayerRef } from "@remotion/player";
import { ViralShortComposition } from "../compositions/ViralShortComposition";
import { ViralShortProps } from "../types";

export interface PlayerController {
  updateProps: (partial: Partial<ViralShortProps>) => void;
  play: () => void;
  pause: () => void;
  seekTo: (frame: number) => void;
  getCurrentFrame: () => number | undefined;
}

const RemotionPlayerApp: React.FC<{
  initialProps: ViralShortProps;
  onReady?: (controller: PlayerController) => void;
}> = ({ initialProps, onReady }) => {
  const [props, setProps] = useState<ViralShortProps>(initialProps);
  const playerRef = useRef<PlayerRef>(null);

  useEffect(() => {
    const controller: PlayerController = {
      updateProps: (partial: Partial<ViralShortProps>) => {
        setProps((prev) => ({ ...prev, ...partial }));
      },
      play: () => playerRef.current?.play(),
      pause: () => playerRef.current?.pause(),
      seekTo: (f: number) => playerRef.current?.seekTo(f),
      getCurrentFrame: () => playerRef.current?.getCurrentFrame(),
    };
    if (onReady) {
      onReady(controller);
    }
    (window as any).__remotionController = controller;
  }, [onReady]);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        backgroundColor: "transparent",
      }}
    >
      <Player
        ref={playerRef}
        component={ViralShortComposition}
        inputProps={props}
        durationInFrames={props.durationInFrames || 300}
        fps={props.fps || 30}
        compositionWidth={props.width || 1080}
        compositionHeight={props.height || 1920}
        style={{
          width: "100%",
          maxHeight: "100%",
          aspectRatio: "9/16",
          borderRadius: "16px",
          overflow: "hidden",
          boxShadow: "0 12px 48px rgba(0,0,0,0.85)",
          border: "1px solid rgba(255,255,255,0.12)",
        }}
        controls
        loop
        autoPlay
      />
    </div>
  );
};

// Exponer API global para integración con el frontend existente (vanilla JS)
(window as any).RemotionPlayerStudio = {
  activeController: null as PlayerController | null,
  mount: (container: HTMLElement | string, initialProps: ViralShortProps) => {
    const el = typeof container === "string" ? document.getElementById(container) : container;
    if (!el) {
      console.error("[RemotionPlayerStudio] Contenedor no encontrado:", container);
      return null;
    }
    const root = createRoot(el);
    root.render(
      <RemotionPlayerApp
        initialProps={initialProps}
        onReady={(c) => {
          (window as any).RemotionPlayerStudio.activeController = c;
        }}
      />
    );
    return {
      updateProps: (p: Partial<ViralShortProps>) => {
        (window as any).RemotionPlayerStudio.activeController?.updateProps(p);
      },
      play: () => (window as any).RemotionPlayerStudio.activeController?.play(),
      pause: () => (window as any).RemotionPlayerStudio.activeController?.pause(),
      seekTo: (f: number) => (window as any).RemotionPlayerStudio.activeController?.seekTo(f),
    };
  },
  updateProps: (p: Partial<ViralShortProps>) => {
    (window as any).RemotionPlayerStudio.activeController?.updateProps(p);
  },
};
