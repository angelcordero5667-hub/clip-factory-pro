# Benchmarks

Máquina: AMD Ryzen 7 5825U (8 núcleos / 16 hilos), 24 GB RAM, Windows 11. Entrada: `data/inputs/ejemplo_podcast.mp4` (25 s, 0.5 MB).

- **Pipeline completo** (`python benchmark_runner.py`): transcripción + detección + render.
  Con este video el VAD descarta todo el audio → 0 candidatos → no hay render. La base (24.85 s)
  incluía una llamada a Ollama sobre una transcripción vacía; ahora una transcripción vacía no
  consulta al LLM. **Esa diferencia no es una mejora real de rendimiento**, solo evita trabajo inútil.
- **Render** (`python benchmark_render.py`): 2 clips sintéticos de 20 s con subtítulos, 9:16. Es la
  métrica útil para las optimizaciones de FFmpeg.
- **Corrida real** (`run_pipeline.py --fast --language es`): extracto de 150 s de un podcast
  (video 1280x720 con voz), 3 clips de 64 s, 41 s y 28 s. No existe base comparable (el código
  anterior no se midió con este archivo).

| Etapa | Pipeline completo (s) | Render 2 clips (s) | Notas |
|-------|----------------------:|-------------------:|-------|
| Base (antes de cambios) | 24.85 | 36.28 | libx264 fast crf22, boxblur a 1080x1920, detección de escenas por clip |
| Etapa 0 (higiene y bugs) | 24.85 | 36.28 | Sin cambios de rendimiento (no se re-midió) |
| Etapa 1 (libx264 veryfast crf24, blur a 270x480, 2 clips en paralelo, 1 detección de escenas) | - | 10.05 | `CLIP_HW_ENCODER=0` |
| Etapa 1 (con h264_amf, por defecto) | - | 6.35 | AMF validado: h264 1080x1920; fallback automático a libx264 |
| Etapa 2 (ventanas LLM, heurístico lineal, pausas) | - | - | No afecta al render; solo detección |
| Etapa 3 (auto-encuadre) | - | 5.88 | Sin modelo YuNet el encuadre cae a blur (mismo costo); con rostros añade ~1 s de muestreo por clip |
| Etapa 4 (dashboard único, cola en SQLite) | - | 5.88 | Render sin cambios; miniatura JPG por clip añade ~0.1 s |
| Etapa 5 (subtítulos, 4 estilos) | 1.98 | 6.11 | Fuentes con `fontsdir`; coste de subtítulos similar |
| Etapa 6 (rediseño dashboard v2.0, responsive, kit) | 1.98 | 6.11 | Interfaz frontend vanilla, sin overhead en servidor; tests 100% verdes |
| Etapa 7 (YuNet real + loudnorm EBU R128) | 1.98 | 7.09 | YuNet ONNX real validado en podcast 60s (14.17s inferencia, 4.2 FPS, modo `crop`). Normalización de audio loudnorm -14 LUFS |

Corrida real final (extracto de 150 s, `--fast`, AMF, sin YuNet): **67.9 s en total**
(≈25 s transcripción con Whisper `base` INT8, ≈43 s render de 3 clips incluida la detección de escenas).

Reproducir:

```powershell
$env:PYTHONPATH="."
.venv\python.exe benchmark_runner.py
.venv\python.exe benchmark_render.py
$env:CLIP_HW_ENCODER="0"; .venv\python.exe benchmark_render.py   # solo libx264
```

Corrida real con LLM (Ollama llama3.2:3b, mismo extracto, 1 ventana): **109.5 s** (≈57 s de análisis LLM, 3 clips `llm`). El modelo de 3B ignora la duración pedida, por lo que sus clips se amplían al mínimo antes de renderizar.
