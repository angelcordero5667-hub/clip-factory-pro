/**
 * Script de Renderizado Headless con @remotion/renderer para Clip Factory Pro.
 * Invocado por Python con props en JSON y reporte de progreso en tiempo real.
 */

import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const args = process.argv.slice(2);
  const getArg = (flag) => {
    const idx = args.indexOf(flag);
    return idx !== -1 && idx + 1 < args.length ? args[idx + 1] : null;
  };

  const propsPath = getArg("--props");
  const outputPath = getArg("--output");
  const compositionId = getArg("--composition") || "ViralShortComposition";
  const concurrency = parseInt(getArg("--concurrency") || "2", 10);
  const customFps = getArg("--fps") ? parseInt(getArg("--fps"), 10) : null;

  if (!propsPath || !outputPath) {
    console.error(JSON.stringify({ type: "error", error: "Faltan argumentos requeridos: --props y --output" }));
    process.exit(1);
  }

  // Leer y parsear props JSON
  let inputProps = {};
  try {
    const raw = fs.readFileSync(propsPath, "utf-8");
    inputProps = JSON.parse(raw);
  } catch (err) {
    console.error(JSON.stringify({ type: "error", error: `Error leyendo props: ${err.message}` }));
    process.exit(1);
  }

  const entryPoint = path.join(__dirname, "src", "index.ts");
  console.log(JSON.stringify({ type: "status", stage: "bundling", message: "Empaquetando bundle Remotion..." }));

  let bundleLocation;
  try {
    bundleLocation = await bundle({
      entryPoint,
      webpackOverride: (config) => config,
    });
  } catch (err) {
    console.error(JSON.stringify({ type: "error", error: `Error en bundle: ${err.message}` }));
    process.exit(1);
  }

  console.log(JSON.stringify({ type: "status", stage: "selecting_composition", message: "Seleccionando composición..." }));

  let composition;
  try {
    composition = await selectComposition({
      serveUrl: bundleLocation,
      id: compositionId,
      inputProps,
    });
  } catch (err) {
    console.error(JSON.stringify({ type: "error", error: `Error seleccionando composición: ${err.message}` }));
    process.exit(1);
  }

  // Ajustar duración y fps si se especifican en inputProps
  if (inputProps.durationInFrames) {
    composition.durationInFrames = inputProps.durationInFrames;
  }
  if (customFps) {
    composition.fps = customFps;
  }

  console.log(JSON.stringify({
    type: "status",
    stage: "rendering",
    totalFrames: composition.durationInFrames,
    fps: composition.fps,
    width: composition.width,
    height: composition.height
  }));

  // Asegurar directorio de salida
  const outDir = path.dirname(outputPath);
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  // Renderizar a MP4
  try {
    await renderMedia({
      composition,
      serveUrl: bundleLocation,
      codec: "h264",
      outputLocation: outputPath,
      inputProps,
      concurrency,
      imageFormat: "jpeg",
      jpegQuality: 90,
      audioCodec: "aac",
      audioBitrate: "192k",
      onProgress: ({ renderedFrames, encodedFrames }) => {
        const percent = Math.min(1.0, renderedFrames / composition.durationInFrames);
        console.log(JSON.stringify({
          type: "progress",
          percent: Number(percent.toFixed(3)),
          renderedFrames,
          encodedFrames,
          totalFrames: composition.durationInFrames
        }));
      },
    });

    console.log(JSON.stringify({
      type: "done",
      outputPath,
      success: true,
      message: "Renderizado Remotion completado con éxito."
    }));
  } catch (err) {
    console.error(JSON.stringify({ type: "error", error: `Error en renderMedia: ${err.message}` }));
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(JSON.stringify({ type: "error", error: err.message }));
  process.exit(1);
});
