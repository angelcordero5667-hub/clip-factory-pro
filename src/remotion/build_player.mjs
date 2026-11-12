import esbuild from "esbuild";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function build() {
  const outDir = path.resolve(__dirname, "..", "..", "static", "js");
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  const outFile = path.join(outDir, "remotion-player.js");
  console.log(`Compilando Remotion Player en: ${outFile}...`);

  await esbuild.build({
    entryPoints: [path.join(__dirname, "src", "player", "index.tsx")],
    bundle: true,
    minify: true,
    format: "iife",
    outfile: outFile,
    define: {
      "process.env.NODE_ENV": '"production"',
    },
    loader: {
      ".png": "dataurl",
      ".svg": "text",
    },
  });

  const stat = fs.statSync(outFile);
  console.log(`¡Remotion Player listo! Tamaño: ${(stat.size / 1024).toFixed(1)} KB`);
}

build().catch((err) => {
  console.error("Error compilando Remotion Player:", err);
  process.exit(1);
});
