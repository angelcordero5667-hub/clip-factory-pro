# Clip Factory Pro

Convierte videos largos (YouTube o archivo local) en clips verticales listos para TikTok, Shorts y Reels.
Corre 100 % en local, optimizado para CPU (Ryzen 7 5825U, 24 GB RAM) con aceleración AMD opcional (h264_amf).

## Cómo correr

Requisitos: Windows 11, el entorno `.venv` del proyecto, FFmpeg en `tools/ffmpeg/bin` y (opcional) Ollama con `llama3.2:3b`.

```powershell
# Dashboard web (abre http://127.0.0.1:8501)
start.bat

# Línea de comandos
$env:PYTHONPATH="."
.venv\python.exe run_pipeline.py "data\inputs\mi_video.mp4" --max-clips 5
.venv\python.exe run_pipeline.py "data\inputs\mi_video.mp4" --fast --language es   # sin LLM, solo heurístico
```

- El servidor escucha **solo en 127.0.0.1**. El token de acceso está en `data/api_token.txt` (o en la variable `CLIP_API_TOKEN`, que tiene prioridad). Se exige también por el túnel público. Abre una vez `http://127.0.0.1:8501/?token=<contenido de data/api_token.txt>` y el navegador lo recuerda 30 días. Para cambiarlo, edita el archivo (sin reiniciar). Nunca lo compartas ni lo subas a git.
- Variables útiles: `CLIP_HW_ENCODER=0` (forzar libx264), `CLIP_SMART_FRAMING=0` (sin auto-encuadre), `CLIP_TRIM_SILENCES=0` (no recortar pausas ni muletillas), `CLIP_DB_PATH` (otra base de datos).
- Seguridad: el servidor rechaza cabeceras `Host` desconocidas y peticiones que modifican datos desde otro origen. Si lo abres por un túnel o dominio propio, agrégalo con `set CLIP_ALLOWED_HOSTS=mi-tunel.trycloudflare.com` (y usa siempre `CLIP_API_TOKEN`). Las subidas tienen tope de `CLIP_MAX_UPLOAD_MB` (4096 por defecto). Los enlaces que apuntan a direcciones locales o privadas se rechazan. `DELETE /api/clips` exige `?confirm=yes`.
- Cancelar: un trabajo en cola se cancela al instante; uno en curso se detiene al terminar su paso actual (`POST /api/jobs/{id}/cancel?force=true`). `GET /api/jobs` incluye `idle_seconds` para ver cuánto lleva sin novedades.
- Tests: `.venv\python.exe -m pytest -q` (usan una base de datos temporal; no tocan `data/`).

### Dashboard Web v2.0

El dashboard se renovó por completo en `src/web/index.html` (vanilla HTML/CSS/JS, sin dependencias CDN pesadas) con un sistema de diseño oscuro estilo neón:
- **Layout y navegación:** Sidebar fija con menú a Inicio, Mis Proyectos, Historial, Plantillas, Analytics y Configuración.
- **Hero & Entrada:** Pestañas para enlaces de YouTube con validación en vivo y zona drag & drop de videos MP4 locales.
- **Opciones de generación:** Formatos (9:16, 1:1, 16:9), estilos de subtítulos (Hormozi, MrBeast, Limpio, Minimal), selector de cantidad de clips y opciones para modo ultra-rápido o marca de agua para plan gratis.
- **Visualizador de clips:** Tarjetas verticales 9:16 con miniaturas reales, badges de virality score circular dinámico, vista previa de video al pasar el cursor y reproductor a pantalla completa.
- **Social Media Kit (Drawer):** Generador y editor de copys virales para TikTok, Instagram Reels y YouTube Shorts, hashtags con resplandor neón, mockup interactivo de smartphone y botón para copiar con un solo clic o descargar el paquete completo `.zip`.
- **Atajos de teclado:** `A` para aprobar clip, `D` para descartar, `←` / `→` para navegar entre clips, `Esc` para cerrar modales y drawer.

### Fuentes tipográficas

La interfaz usa Sora, Inter y JetBrains Mono; los subtítulos usan Montserrat ExtraBold, Anton y Poppins SemiBold,
todas en `static/fonts` (licencia SIL OFL). Si faltan, la interfaz usa fuentes del sistema y los subtítulos usan Arial.
Para descargar las de subtítulos que falten: `powershell -ExecutionPolicy Bypass -File scripts\fetch_fonts.ps1`.

### Auto-encuadre al hablante

Necesita el modelo de rostros YuNet en `data/models/` (OpenCV 5 ya no trae Haar). Ver [docs/AUTOENCUADRE.md](docs/AUTOENCUADRE.md).

## Arquitectura

```
 URL de YouTube / archivo ──► Descarga (yt-dlp: audio para transcribir; video 720p una sola vez)
                                  │
                                  ▼
          Agente 1  Transcripción  faster-whisper INT8, beam 1, VAD, timestamps por palabra
                                  │   (caché por archivo en data/cache/transcripts)
                                  ▼
          Agente 2  Detección      LLM (Ollama) por ventanas de 6 min con solape de 30 s
                                  │   + heurístico (ventana deslizante, texto sin acentos)
                                  │   → puntaje 0-100, ajuste de inicio/fin a pausas del habla
                                  ▼
          Agente 3  Clips          cortes de escena (1 vez por video) → auto-encuadre (crop/split/blur)
                                  │   → subtítulos ASS (4 estilos) → FFmpeg, 2 clips en paralelo
                                  │   → mp4 + miniatura jpg por clip
                                  ▼
          SQLite    videos · candidates · jobs   ──►  FastAPI + src/web/index.html (dashboard)
          Agente 5  Orquestador (pipeline.py) y control de memoria del proceso (optimizer.py)
```

### Detalles que importan

- **Puntaje**: 0-100 (verde ≥ 85, ámbar ≥ 70). Cada clip registra su motor (`llm` o `heuristic`), visible en el dashboard.
- **Cola de trabajos**: tabla `jobs` en SQLite; un worker procesa un video a la vez. Los trabajos interrumpidos por un reinicio quedan como error.
- **Encoder**: `h264_amf` si FFmpeg lo expone (`ffmpeg -encoders`); si falla, reintenta solo con `libx264` (`-preset veryfast -crf 24`).
- **Fondo desenfocado**: se desenfoca a 270x480 y se reescala (mucho más barato que desenfocar 1080x1920).
- **Formatos**: 9:16, 1:1 y 16:9. **Exportación**: ZIP por video (mp4 + jpg + `copys.txt`), de aprobados o de todos.
- **Subtítulos**: `hormozi`, `limpio`, `karaoke`, `minimal`; máx. 2 líneas de 4 palabras, contorno 4-6 px, fuera de la zona de interfaz de TikTok/Reels. Los emojis solo se dibujan si el estilo lo permite y existe una fuente monocroma (`NotoEmoji*.ttf` en `static/fonts`); si no, se omiten sin error.

## Atajos del dashboard

`←` `→` `↑` `↓` navegar · `A` aprobar · `D` descartar · `E` editar · `Enter` vista previa · `?` ayuda.

## API (resumen)

| Método y ruta | Uso |
|---|---|
| `GET /api/clips?video_id=` | Clips del video (el más reciente por defecto); lista vacía si no hay datos |
| `POST /api/clips/{id}/status` | `approved`, `rejected`, `pending` |
| `PATCH /api/clips/{id}` | Editar título y tiempos (queda marcado para re-renderizar) |
| `POST /api/clips/{id}/rerender` | Encola un nuevo render |
| `GET /api/clips/{id}/download` | Descarga del mp4 |
| `GET /api/videos/{id}/zip?only=approved` | ZIP del video |
| `GET /api/system/metrics` | Métricas de CPU, RAM, GPU/encoder y cola en tiempo real |
| `POST /api/jobs` · `GET /api/jobs` · `POST /api/jobs/{id}/cancel` | Cola de trabajos |
| `POST /api/upload` | Subir un archivo a `data/inputs` (nunca sobrescribe) |

## Estructura de carpetas

```
clip-factory-pro/
├─ src/
│  ├─ api_server.py             # FastAPI: dashboard + API
│  ├─ jobs.py                   # worker de la cola de trabajos
│  ├─ web/index.html            # único dashboard
│  ├─ common/                   # config, base de datos, modelos, descargas de YouTube
│  └─ agents/
│     ├─ agent1_transcription/  # faster-whisper
│     ├─ agent2_viral_detector/ # detector.py + analysis.py (ventanas, acentos, pausas)
│     ├─ agent3_clip_generator/ # clip_maker, framing, face_tracker, subtitles
│     └─ agent5_qa_optimizer/   # pipeline y optimizer
├─ static/fonts/                # única carpeta de assets (tipografías)
├─ scripts/fetch_fonts.ps1
├─ docs/                        # BENCHMARK.md, AUTOENCUADRE.md, IMPLEMENTATION_REPORT.md
├─ tests/
├─ data/                        # inputs, outputs, cache, clip_factory.db (no se versiona)
├─ tools/                       # ffmpeg, cloudflared (no se versiona)
├─ run_pipeline.py · benchmark_runner.py · benchmark_render.py · start.bat
└─ requirements.txt · requirements.lock.txt
```

## Benchmarks

Detalle y cómo reproducirlos en [docs/BENCHMARK.md](docs/BENCHMARK.md). Render de 2 clips de 20 s (9:16 con subtítulos):

| | Segundos |
|---|---:|
| Antes (libx264 fast, blur a 1080x1920, secuencial) | 36.3 |
| libx264 veryfast + blur a 1/4 + 2 en paralelo | 10.1 |
| h264_amf (por defecto) | 6.1 |
