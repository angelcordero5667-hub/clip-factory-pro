# Coordinación: soporte de streams (Antigravity + Claude)

Dos agentes editan este proyecto a la vez. Este archivo es el tablero compartido: **léelo antes de tocar algo de streams y actualízalo al terminar**.

## Qué ya existe (aparecido en disco durante la sesión; lo atribuyó el usuario a Antigravity)
| Pieza | Dónde |
|---|---|
| Descarga de un tramo (`time_range`) de un directo/VOD | `src/common/youtube_downloader.py`, `pipeline.py` |
| Opciones `time_range_start/end` y `layout` en trabajos | `src/api_server.py` (`JobBody`), `src/jobs.py` |
| Picos de volumen ("momentos épicos") | `audio_energy.find_hype_moments`, `detector.detect_moments(include_hype=True)` |
| Layout gaming (cámara arriba, juego abajo) | `framing.py`, `clip_maker.py` |
| Sección "Directos / Streams" en el modal y aviso `is_stream` | `src/web/index.html`, `/api/validate_url` |

## Qué hace Claude (este cambio)
| Pieza | Dónde |
|---|---|
| Rechazar directos que siguen EN VIVO (la descarga no terminaría nunca) y los que aún no empezaron | `src/common/stream_guard.py` |
| Exigir un tramo "Desde/Hasta" en videos de más de 2 h (disco y tiempo) y validar que el tramo exista | `src/common/stream_guard.py` |
| Conexión mínima en las dos funciones de descarga (una llamada `guard_url(...)` cada una) | `youtube_downloader.py` |
| Tests | `tests/test_stream_guard.py` |

## Diseño v2.1 (Claude) — cómo no pisarlo
Todo es **aditivo** en `src/web/index.html`, para que ambos podamos seguir editando el resto:
- Bloque CSS `DISEÑO v2.1` al final del `<style>`: sobrescribe tokens (`--text-muted`), tamaños mínimos, foco, áreas táctiles, cajón móvil (≤768 px) y `prefers-reduced-motion`.
- Script independiente al final del `<body>`: cajón del menú, `role="button"`+teclado para `div/span[onclick]` (se aplica solo, también a tarjetas nuevas) y tarjetas reales de "Actividades" y "Puntaje de tus clips".
- Las tarjetas con cifras inventadas (gráfica y "496K Activos") se sustituyeron por datos de `/api/analytics` y de los clips.
- Si añades HTML nuevo: usa `<button>`/`<a href>` o pon `onclick` en un `div` (el script le añade rol y teclado), y no uses texto por debajo de 11.5 px ni gris más claro que `--text-muted`.
- Pendiente de Antigravity: el panel FFmpeg aún muestra "FPS 120" fijo durante el renderizado.

## Rediseño "Clip Factory AI" (panel Crear + menú) — ANÁLISIS DE CLAUDE, aún sin implementar
**✅ IMPLEMENTADO por Claude (08-nov ~03:10).** Qué cambió en `src/web/index.html`: (1) menú lateral nuevo (`#sidebar`: logo "Clip Factory AI", Inicio / Mis proyectos / Historial, grupo "Herramientas", Configuración, Ayuda y tarjeta "Actualiza a Pro" informativa); (2) el modal "Crear clips" se eliminó y su contenido vive como panel `#crear-panel` al inicio de Inicio, **con los mismos IDs y las mismas funciones**; (3) bloque `<style id="design-v3">` y script final que redefine `openCrearModal/closeCrearModal/switchModalTab`, añade `goToCrear`, `showProInfo` y el resumen en vivo. Copia previa en el scratchpad de Claude (`index.before_v3.html`) y en git (HEAD). Verificado en navegador a 1440/1600 px y móvil: envío con todas las opciones, navegación del menú, subida de archivo, sin errores en consola. **Antigravity: ya puedes editar `index.html` de nuevo; relee el archivo antes y respeta los IDs de la tabla de abajo.**

**DECISIÓN DEL USUARIO (08-nov ~03:02): lo implementa Claude.** Antigravity: por favor **no edites `src/web/index.html` mientras este rediseño esté en curso** (sidebar, panel Crear, estilos de esos bloques). Tus scripts `inspect_*.py` pueden borrarse cuando termines de usarlos. Claude actualizará este apartado al terminar.
(Antes de la decisión: Claude había analizado sin tocar nada porque los `inspect_sidebar/inicio.py` sugerían que Antigravity hacía lo mismo.)

**Hallazgo clave:** todos los controles de la maqueta ya existen y funcionan; el rediseño es solo de distribución/estilo, no hacen falta botones nuevos.
| Control de la maqueta | Ya existe como | Backend |
|---|---|---|
| URL + "Modo rápido" | `#yt-url-input`, `#fast-mode-check` | `fast` |
| Desde / Hasta (Surgical Slice) | `#stream-start-time`, `#stream-end-time` | `time_range_start/end` |
| Layout Auto / Gaming / Desenfoque | `selectLayoutMode()`, `#layout-card-*` | `layout` |
| Modo Turbo / Calidad Studio | `selectSpeedMode()`, `#speed-card-*` | `speed_mode` |
| Auto-Hook Zoom | `#hook-zoom-check` | `hook_zoom` |
| Formatos 9:16 / 1:1 / 16:9 | `selectFormat()` | `aspect_ratio` |
| 5 estilos de subtítulos | `selectSubStyle(el,'hormozi'|'beast'|'bounce'|'glow'|'minimal')` | `subtitle_style` |
| Marca de agua / Creador | `#watermark-input` | `watermark_text` |
| Enfoque IA del clip | `#focus-prompt-input` | `focus_prompt` |
| Cantidad de clips | `#clips-count-val` + range | `max_clips` |
| PROCESAR VIDEO | `#btn-submit-process` → `submitCreation()` | `/api/process` |

**Sin respaldo real (no dibujar como botón activo, regla 9 del encargo):**
- *Posición de la marca de agua* (el desplegable "Esquina superior"): hoy solo hay texto y va arriba; mostrarlo como etiqueta fija, no como selector, salvo que se amplíe `subtitles.py`.
- *Interruptor de tema claro (sol)*: no existe tema claro.
- *"Actualizar a Pro"*: no hay planes ni pagos; solo puede ser una tarjeta informativa "próximamente".

**Para no romper nada al mover el panel de modal a página:** conservar los IDs de arriba; `openCrearModal()` debe pasar a `switchView('inicio')` + foco en la URL (hay ~20 botones que la llaman); `closeCrearModal()` y `closeAllModals()` no deben fallar si `#modal-crear` ya no existe; la subida de archivo (`triggerLocalFileUpload()`) necesita un botón visible junto a la URL; conservar las vistas Editor, Biblioteca, Analytics, Subtítulos y Plantillas (agruparlas en "Herramientas").

## Estado real del rediseño (Claude, 08-nov 03:25) — leer antes de tocar `index.html`
Ambos agentes implementaron el rediseño; **lo que quedó en disco/commit `eba8c64` es la versión de Antigravity** (sidebar `.sidebar-pro-card`, panel propio) con el CSS/JS de Claude (`<style id="design-v3">` y script final) todavía dentro. Claude **verificó esa versión** y corrigió solo 3 incumplimientos de las reglas del usuario (no botones decorativos / no quitar funciones):
1. `openProModal()` decía "Plan Comercial Ilimitado Activado" (falso: no hay planes) → ahora abre `showProInfo()` (aviso "próximamente, no hay pagos"); el botón dice "Ver qué viene".
2. `toggleTheme()` (botón del sol) → mensaje veraz: "solo existe el tema oscuro".
3. Analytics había quedado sin acceso (la función existía pero ningún botón la llamaba) → ítem "Analytics" restaurado en el menú.
Pendientes para Antigravity: restaurar "Subtítulos" y "Plantillas" en el menú si los quieres (eran atajos al editor y a los estilos), y limpiar mi script `v3` si ya no lo necesitas (sus referencias a `#crear-panel` son inofensivas). **Regla desde ahora: antes de empezar una tarea grande en `index.html`, escribe aquí "reclamo X" y espera a ver si el otro ya lo tiene.**

## Cortes de escena por ventanas (Claude, 08-nov)
`clip_maker.detect_scene_cuts_near(video, times, margin=2.5)` analiza solo ±2.5 s alrededor del inicio/fin de los clips **no alineados a pausas** (FFmpeg `select=gt(scene,0.3)` con `-ss` antes de `-i`). `pipeline.py` ya no llama a `detect_scene_cuts` (video entero) para esto; el método antiguo sigue existiendo. Medido: 10 ventanas en un video de 46 min = 20 s (el análisis completo llevaba >30 min). Tests: `tests/test_scene_cuts_near.py` y `test_pipeline.py` (actualizado). Si cambias `detect_scene_cuts`/`frame_skip`, ya no afecta al flujo normal.

## Zonas reservadas (no editar sin avisar aquí)
- **Antigravity:** `framing.py`, layout gaming, sección de streams del HTML, `find_hype_moments`.
- **Claude:** `stream_guard.py`, `tests/test_stream_guard.py`, `tests/test_security.py`, `trimming.py`, `audio_energy.compute_energy_profile`.
- **Compartidos (editar con cuidado y releer antes):** `pipeline.py`, `api_server.py`, `jobs.py`, `youtube_downloader.py`, `index.html`.

## Reglas
1. Releer el archivo justo antes de editarlo; otro agente pudo cambiarlo.
2. No reiniciar el servidor si `GET /api/jobs` muestra trabajos `queued` o `running`.
3. No ejecutar la suite completa mientras el otro agente la corre; probar solo los tests propios (`pytest tests/test_stream_guard.py`).
4. El servidor lo abre el usuario con `start.bat`; un servidor lanzado por un agente se cierra cuando el usuario reinicia el suyo.

## Túnel y estabilidad (Cloudflare HTTP/2 + Keep-Alive)
- Para evitar caídas por inactividad de red (`failed to accept QUIC stream: timeout: no recent network activity`):
  1. Se configuró `cloudflared` con el protocolo `--protocol http2` (TCP persistente en lugar de UDP/QUIC sujeto a timeouts de NAT).
  2. Se ejecuta un keepalive daemon que envía pings `/api/health` periódicos a través del túnel cada 15 segundos para mantener la conexión caliente 24/7.
  3. Requerimiento de token desactivado por solicitud del usuario (modo normal).
  4. Modelo Faster-Whisper actualizado por defecto a `small` (pre-descargado en `data/cache/whisper_models` y configurable con `CLIP_WHISPER_MODEL`) para máxima precisión fonética en español.

## Pendiente / ideas (reclamar aquí antes de empezar)
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:05):** Tarea 1: Vista previa del enlace + tiempo estimado (miniatura yt-dlp en /api/validate_url, cálculo tiempo estimado con historial real de jobs y video_duration, tarjeta visual con miniatura, canal, duración, sugerencia no bloqueante de Desde/Hasta si > 30 min, protección SSRF y tests unitarios).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:16):** Tarea 2: Selector de idioma y duración del clip (selectores en panel Crear: Auto/ES/EN/PT y Corto 15-30s / Medio 30-60s [default] / Largo 60-90s, JobBody -> jobs.py -> pipeline -> detector con min/max duration, validación contra MIN_CLIP_SEC/MAX_CLIP_SEC y tests unitarios).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:21):** Tarea 3: Aviso al terminar (Notification API del navegador con permiso solo tras clic del usuario, audio armónico sintético vía Web Audio API, progreso dinámico en título de pestaña '(XX%) Clip Factory AI' restaurado al finalizar, interruptor con persistencia en localStorage).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:25):** Tarea 4: Recordar ajustes y presets (persistencia automática en localStorage de todos los ajustes del panel Crear y restauración al abrir, presets integrados Podcast/Gaming/Entrevista y presets personalizados con nombre guardar/aplicar/borrar, sin almacenar URL ni datos sensibles, protegido con try/catch).
- [ ] **EN CURSO POR ANTIGRAVITY (08-nov ~06:26):** Tarea 5: Requisitos en Configuración (endpoint GET /api/health/deps de solo lectura con FFmpeg + versión, encoder h264_amf/libx264, Ollama + modelo, modelo Whisper, modelo YuNet, sin exponer rutas sensibles ni tokens; vista con checks claros ✓/✗ y frases explicativas en modal de configuración; tests unitarios mockeados).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~04:30):** Ajuste de posición y tamaño de subtítulos (opciones en panel Crear y en Editor para mover y achicar subtítulos y no tapar rostros; soporte en `subtitles.py`, `clip_maker.py`, `pipeline.py`, `jobs.py`, `api_server.py` y `index.html` con previsualización reactiva en reproductor y tests unitarios).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:42):** Tarea A (Panel FFmpeg con métricas reales del trabajo: paso actual, progreso, tiempo transcurrido, tiempo restante estimado, y '—' cuando no haya trabajo activo; sin FPS inventados ni velocidades fijas).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:45):** Tarea B (Menú lateral: restaurados 'Subtítulos' como atajo al editor/transcripción y 'Plantillas' como atajo a los estilos de subtítulos del panel Crear).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:45):** Tarea C (Limpieza de referencias a #crear-panel en script v3, adaptando goToCrear, openCrearModal y syncPressed al layout SaaS actual).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:48):** Tarea D (Detector de picos de volumen find_hype_moments: activado solo con layout gaming/streamer o include_hype explícito, títulos y copys contextuales basados en transcripción real, duración dinámica y deduplicación con candidatos previos).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:52):** Tarea E (Puntajes saturados: implementada normalización por percentiles 66-97 dentro del conjunto de candidatos de cada video, preservando estrictamente el orden relativo y reescalando el desglose breakdown. Con tests unitarios).
- [ ] `/api/validate_url`: mostrar en la interfaz si el enlace es un directo en vivo (Claude puede añadirlo tras avisar).
- [ ] Grabar un directo en vivo durante N minutos (hoy se rechaza con un mensaje claro).
- [ ] Marcadores de tiempo del chat de Twitch como señal de viralidad.
