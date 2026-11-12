# Fase 10 — HyperFrames: mapa de integración y contrato (borrador para aprobar)

Estado: **solo auditoría y diseño. No se instaló nada ni se modificó código de producción.**
Fecha: 12-nov-2026. Autor del contrato: Claude (backend/arquitectura). Antigravity desarrolla las composiciones **respetando este contrato**.

## 1. Qué es HyperFrames y qué se verificó
- Repositorio oficial: `heygen-com/hyperframes`, paquete npm `hyperframes`, licencia **Apache-2.0** (consultado vía npm, no instalado).
- Requisitos declarados por el paquete: **Node ≥ 22** (este equipo tiene Node 24.21.0 y npm 11.19.0 ✓) y FFmpeg (el del proyecto, 9.0.2 ✓). Renderiza con Chrome sin ventana vía `puppeteer-core` + `@puppeteer/browsers` (descargaría su propio Chromium).
- Dependencias directas: hono, open, acorn, citty, debug, giget, yauzl, ignore, undici 7.25.0, adm-zip, esbuild, fontkit, postcss, css-tree, puppeteer-core, compare-versions, @hono/node-server, @puppeteer/browsers.
- **Ritmo de publicación muy alto**: la última versión (`0.9.39`) se publicó el mismo día de esta consulta; hay más de 400 versiones. Los resúmenes web que encontré se contradicen entre sí (0.4.x, 0.7.x), así que el dato fiable es el del registro npm.
- **Recomendación de versión:** fijar una versión exacta con al menos 2 semanas en el registro (p. ej. `0.8.200`, 25-oct-2026) y confirmarla con las pruebas de la Fase 10-A antes de darla por buena. No usar `latest` ni rangos `^`.

## 2. Conflicto a decidir antes de instalar
El proyecto **ya tiene Remotion** (`src/remotion/`, 784 MB de `node_modules`, `src/common/remotion_engine.py`), creado por otro agente. Sin versionar en git. El brief dice "no instales Remotion ni otros motores de renderizado": hoy habría **dos motores HTML→video** con el mismo propósito. Hay que decidir cuál es el oficial (o si Remotion se retira) para no mantener dos. Además habría hasta tres copias de Chromium: Playwright (`ms-playwright\chromium-1248`), el headless shell de Remotion y el que bajaría HyperFrames.

## 3. Mapa de integración (rutas reales)
| Función | Archivo real | Qué hace hoy | Cambio previsto |
|---|---|---|---|
| Pipeline | `src/agents/agent5_qa_optimizer/pipeline.py` | `run_pipeline`, `rerender_candidate`, pasos `STEPS` | Elegir motor por configuración; fallback |
| Cola y cancelación | `src/jobs.py` (`JobWorker`) | un worker; cancela de forma cooperativa solo entre pasos | Pasar un `cancel_check` al adaptador |
| Render FFmpeg | `src/agents/agent3_clip_generator/clip_maker.py` (`VerticalClipMaker`) | `generate_clip` → `build_filter_complex` + `build_ffmpeg_cmd`; `_run_ffmpeg` usa `subprocess.run` **bloqueante y sin timeout ni cancelación** | Punto de enganche: capa visual HyperFrames antes de la mezcla final; el camino actual no se toca |
| Subtítulos ASS | `src/agents/agent3_clip_generator/subtitles.py` (`SubtitleGenerator`) | estilos Hormozi, etc. | Se mantiene como alternativa y fallback |
| Pack Viral | `src/common/viral_pack.py` (`ViralPackEngine`, `ClipProgressTracker`) | 3 clips en paralelo, estado por clip, `cancel_clip` | Cada clip elige motor; estado propio |
| Endpoints | `src/api_server.py`: `/api/jobs`, `/api/jobs/{id}/cancel`, `/api/clips/{id}/rerender`, `/api/viral_pack/generate`, `/status`, `/cancel/{clip_idx}`, `/api/videos/{id}/zip`, `/api/clips/{id}/download` | — | Parámetros nuevos opcionales (`visual_engine`, `hf_template`, …) |
| Configuración | `src/common/config.py` (`RenderConfig`) | `parallel_clips`, `threads_per_clip`, encoder | Añadir `VisualEngineConfig` con valores por defecto = comportamiento actual |
| Frontend | `src/web/index.html` (vistas Create y Editor) | controles de subtítulos/efectos | Selector de motor y plantilla (**Antigravity**) |
| Zoom | `clip_maker.build_filter_complex` (punch/dynamic zoom en FFmpeg) | zoom ya aplicado a la fuente | **Una sola fuente de verdad**: si el zoom ya está en FFmpeg, HyperFrames no lo repite |

Hallazgo que condiciona el diseño: `_run_ffmpeg` no tiene cancelación ni timeout. Por eso un re-render en marcha no se puede cancelar desde la API (me pasó con el trabajo #51). El adaptador de HyperFrames debe nacer con `Popen`, timeout y terminación del árbol de procesos, y de paso sirve de modelo para arreglar FFmpeg.

## 4. Decisión técnica: cómo se combina con el video
Se evaluarán dos alternativas (la decisión final depende de pruebas, no de preferencia):
- **A. Composición completa en HyperFrames** (video + texto en el navegador): más simple, pero re-codifica el video una vez más y el navegador decodifica el video fuente (CPU alta en un Ryzen 5825U).
- **B. Capa visual transparente superpuesta con FFmpeg**: HyperFrames renderiza solo subtítulos/gráficos con canal alfa (WebM VP9 con alfa, o secuencia PNG) y FFmpeg la superpone sobre el video ya encuadrado, junto con el audio masterizado. Evita doble codificación del video y deja el audio intacto.
- Preferida en el papel: **B**. **No verificado**: que HyperFrames exporte alfa fiable, bordes sin halo, sincronía y coste de CPU. Si el alfa falla, se usa A con el audio original reemplazado después por FFmpeg.
- El audio **nunca** pasa por HyperFrames: se renderiza video sin audio y FFmpeg mezcla el audio masterizado existente. Se valida con `ffprobe` (códec, canales, sample rate, duración ±1 frame).

## 5. Contrato de integración (v0.1)
Un solo JSON de entrada por clip, que Python genera y las composiciones leen. **Todos los tiempos son segundos relativos al inicio del clip final** (ya recortado por pausas), redondeados a ms; el render usa 30 fps y ajusta los tiempos al frame más cercano (determinista).

```json
{
  "schema_version": "0.1",
  "clip": {"id": "vid_xxx_clip_h_171", "duration": 42.0, "width": 1080, "height": 1920, "fps": 30, "language": "es"},
  "style": {"template": "hormozi|kinetic|minimal|bold_viral", "intensity": "low|medium|high", "accent_color": "#FFFF00",
            "uppercase": true, "safe_zone": {"top": 0.12, "bottom": 0.22, "left": 0.06, "right": 0.06}},
  "words": [{"text": "carril", "start": 3.12, "end": 3.51, "confidence": 0.93, "emphasis": false}],
  "segments": [{"id": 4, "start": 3.0, "end": 6.2, "text": "…"}],
  "punch_zooms": [{"start": 5.0, "end": 5.6, "scale": 1.12, "applied_in": "ffmpeg"}],
  "headline": {"text": null, "start": 0.0, "end": 2.5},
  "overlays": [{"kind": "speaker_label|lower_third|context_label|number_counter|callout", "text": "…", "start": 1.0, "end": 4.0, "source": "pipeline"}],
  "render": {"mode": "overlay_alpha|full", "quality": "draft|standard|high", "timeout_s": 600}
}
```
Reglas:
- **Ningún texto, nombre o cifra va escrito en las plantillas**: todo viene de este JSON. No se inventan identidades; los overlays de hablante solo se rellenan si el pipeline aporta el dato (`source: "pipeline"`).
- Los zooms con `applied_in: "ffmpeg"` **no** se vuelven a aplicar en la composición.
- Las palabras mantienen la ortografía y expresiones dominicanas tal como las entrega Python.
- Las plantillas deben ser deterministas: sin `Math.random`, sin fechas, sin red.

**Salida del adaptador** (`HyperFramesRenderer.render(...)` → resultado):
`{"status": "done|error|cancelled", "visual_path": "...(webm|mp4|png_seq)", "has_alpha": true, "duration": 42.0, "frames": 1260, "render_seconds": 0, "error": {"code": "...", "message": "..."} | null}`

**Estados y progreso** (por clip, independientes): `queued → preparing → rendering(0..1) → assembling → done`, más `error` y `cancelled`. Códigos de error: `NOT_INSTALLED`, `NODE_MISSING`, `CHROMIUM_MISSING`, `TIMEOUT`, `RENDER_FAILED`, `INVALID_COMPOSITION`, `CANCELLED`. Si hay error, el pipeline registra el motivo y **cae al motor FFmpeg+ASS** sin duplicar el clip.

## 6. Reparto de trabajo
- **Claude:** esquema del contrato, `HyperFramesRenderer` (Python), configuración con HyperFrames **desactivado por defecto**, enganche en pipeline/Pack Viral, cancelación y limpieza de procesos, ensamblado FFmpeg, pruebas A, D, F, G.
- **Antigravity:** carpeta `visual_engine/` (composiciones HTML/CSS/JS, componentes, animaciones, estilos A–D), controles del frontend y vista previa, pruebas B y C visuales.
- Ninguno edita `pipeline.py`, `clip_maker.py`, `viral_pack.py`, `api_server.py`, `config.py` ni `index.html` sin reclamarlo antes en `docs/COORDINACION_STREAMS.md`.

## 7. Plan por etapas (cada una con evidencia)
1. **10-A Compatibilidad:** instalar en `visual_engine/` aislado con versión y lockfile fijos; `hyperframes` CLI; una composición mínima → MP4; comprobar alfa. *(necesita aprobación: descarga de paquetes y de Chromium)*
2. **10-B Adaptador y config:** `HyperFramesRenderer`, cancelación con `Popen`, timeouts, limpieza; pruebas sin Chromium con un proceso simulado.
3. **10-C Plantillas** (Antigravity) contra el contrato; comparación con ASS en jerga dominicana.
4. **10-D Integración** en pipeline y Pack Viral con fallback; UI.
5. **10-E Medición** en el Ryzen 7 5825U (1 y 2 renders; luego 3 solo si es estable) y regresión completa.
Criterio de salida: nada se marca como APROBADO hasta tener comparación real contra el motor actual.

## 8. Decisiones que necesito de ti
1. ¿Qué hacemos con Remotion (conservar como segundo motor, retirar o dejar congelado)?
2. ¿Autorizas instalar `hyperframes` (versión fija, p. ej. 0.8.200) en `visual_engine/` y descargar su Chromium (~150–200 MB estimado, no medido)?
3. ¿Antigravity retoma la carpeta `visual_engine/` y la interfaz bajo este contrato?

## 9. ADDENDUM TÉCNICO DEL USUARIO (12-nov) — requisitos para el dueño de HyperFrames (Antigravity)
Verificación en el registro npm hecha por Claude (solo lectura, nada instalado):
- `npm view hyperframes version` → **0.9.39** (existe y es la última hoy).
- `hyperframes@0.9.39` integridad: `sha512-8dFgMtpwdauh1+oa2ImYjdBT11kcxVgtFeGLY3+Vk4DGNzkzPSaD6Z+Zwyyheh4T+jXUvv/T9N2MgBNMyJpWjA==`
- `hyperframes@0.9.37` existe; integridad: `sha512-PR5oJq1wY/0om/ciEZuZ0efSflWxl2ne4LalMSdbBS/DtQXyMTz5ZMlEmeivvhjVi+dhqAaQr+1ISKIi6bcm2g==`
- Dependencias de la última versión: ver sección 1 de este documento (Node ≥ 22). Si se instala una versión distinta de la fijada, documentar y justificar el cambio.

Requisitos del addendum (resumen; el texto íntegro lo aportó el usuario):
1. Transparencia: WebM VP9 con alfa; validar con ffprobe, fotogramas RGBA, fondo de contraste y composición real sobre el video; alternativas ProRes 4444 o secuencia PNG RGBA. **Un overlay con fondo negro no vale.**
2. Ensamblado FFmpeg con índices de entrada correctos; conservar el audio masterizado; `-c copy` solo si el audio ya es el final; verificar duración, timestamps, FPS y sincronía.
3. **Validación estricta de `composition_props.json`**: id, dimensiones, FPS, duración, plantilla, colores, timestamps, segmentos, palabras, animaciones, límites de recursos; rechazar tiempos negativos, segmentos fuera de duración y propiedades no permitidas; escapar textos y no ejecutar contenido no confiable.
4. Timeline determinista: GSAP pausada con ID correcto y duración finita; sin `Date.now()`, sin `Math.random()` sin semilla, sin red, sin animaciones infinitas; `hyperframes lint`, `check` y snapshots antes de renderizar.
5. Sincronía: tiempos relativos al clip, al FPS real de exportación; validar primer, intermedio y último fotograma.
6. Rendimiento por etapas (Chromium, composición, captura, codificación del overlay, ensamblado, total) con RAM y CPU; **no tres Chromium a la vez** hasta demostrar estabilidad.
7. Primero solo la plantilla **Hormozi** de principio a fin; HyperFrames desactivado por defecto; no tocar ASS, el renderizador anterior ni el Pack Viral hasta validar el adaptador individual.
8. Aprobado solo con un video final real, transparente en la etapa intermedia, compuesto, sincronizado y reproducible, con evidencia reproducible.

Nota de reparto: por decisión posterior del usuario, **Antigravity implementa HyperFrames**; Claude trabaja con Remotion. Claude puede escribir el validador del contrato (`composition_props`) y la mezcla FFmpeg si Antigravity lo pide, sin editar archivos compartidos sin reclamarlos.
