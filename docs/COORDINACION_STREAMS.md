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
- [x] **COMPLETADO POR ANTIGRAVITY (09-nov ~01:45):** Tarea 18: Suite Completa de Efectos Virales y Retención (TikTok / Shorts / Reels):
  1. ⚡ **Barra de Progreso Dinámica:** Línea neón animada en FFmpeg (`drawbox`) de 0% a 100% que avanza con la duración exacta del clip.
  2. 🔍 **Zooms Rítmicos (Punch-In cada 12s):** Reajuste de atención dinámico (1.12x centrado durante 2.2s) para elevar retención visual.
  3. 🎨 **Color Grading Viral:** Presets `pop` (TikTok MrBeast saturado), `cinema` (Teal & Orange), `vignette` (viñeta envolvente suave) y `warm` (cálido podcast).
  4. 📌 **Titular Superior de Gancho (Hook Headline):** Capa ASS en formato cartelera superior (`Alignment=8`) para capturar la mirada en los primeros 6 segundos.
  5. ✨ **Borde Glow Neón en Split:** Línea divisoria luminosa entre hablantes en pantalla dividida 9:16.
  6. 🎮 **Selector de Temas B-Roll:** Soporte para gameplay universal, Minecraft parkour, Subway Surfers, GTA V y ASMR satisfactorio con fallback procedural.
  7. 🎛️ **Controles en UI y Re-render:** Sección dedicada "Efectos Virales y Retención" en panel Crear y en barra lateral del Editor con soporte de re-renderizado en caliente y presets.
  Tests: 228 tests unitarios pasando al 100% y validación Playwright con 0 overflow horizontal en móviles.
- [x] **COMPLETADO POR ANTIGRAVITY (09-nov ~00:55):** Tarea 17: Menús Reales, Vistas Dedicadas y Navegación Completa:
  1. 📁 **Vista REAL "Mis Proyectos" (`#view-proyectos`)**: Carga los 27 proyectos desde `/api/videos`, con buscador en tiempo real, selector de orden (recientes/clips/duración), KPIs de proyectos y botones de acción ("Ver Clips", "Descargar ZIP" y "Exportar Guion TXT").
  2. 🕒 **Vista REAL "Historial de Trabajos" (`#view-historial`)**: Lista dinámica de tareas desde `/api/jobs`, tarjeta destacada para el trabajo activo con barra de progreso en vivo, chips de filtro (Todos, En Curso, Listos, Errores/Cancelados) y acciones de cancelación y reintento.
  3. 📊 **Vista REAL "Analytics y Rendimiento" (`#view-analytics`)**: Panel con 4 KPI cards (Videos procesados, Clips listos, Score promedio 94.6, Horas ahorradas), distribución de ganchos virales con barras de colores, resumen de hardware/modelos y ranking de Top 6 Clips más virales con acceso directo al editor.
  4. 👤 **Dropdown Menu REAL en Avatar del Usuario (`#user-dropdown-menu`)**: Al pulsar el avatar se despliega un menú flotante con estado de sesión, accesos directos a todas las vistas, configuración de hardware, atajos de teclado y limpieza de caché.
  5. 🧭 **Pestañas Superiores y Menú Lateral 100% Funcionales**: Se eliminaron los enlaces ficticios ("Audios v" y redirecciones al inicio); ahora cada pestaña (`Crear`, `Proyectos`, `Editor`, `Monitor`, `Historial`, `Analytics`) navega a su vista real correspondiente.
  6. 📱 **Navegación Móvil con Bottom Sheet ("Más")**: El bottom nav incluye botón "Más" que abre un menú deslizante inferior para acceder fluidamente a Historial, Analytics, Ajustes y Ayuda sin sobrecargar la pantalla.
  Verificado: 100% de tests unitarios pasando y suite Playwright visual en `docs/captured_screenshots/menus/`.
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~09:18):** Tarea 16: Optimización y experiencia móvil completa (Mobile Responsiveness & Bottom Navigation):
  1. 📱 Cero desbordamientos horizontales (`scrollWidth == innerWidth`) en todos los tamaños móviles (Android 360px, iPhone SE 375px, iPhone 14 390px, Pixel 7 412px).
  2. 🧭 Barra de navegación inferior móvil tipo app nativa (`.mobile-bottom-nav`) con 4 accesos rápidos ergonómicos: Crear, Editor, Monitor y Ajustes, sincronizados con `switchView`.
  3. 📐 Layout de panel Crear optimizado: inputs adaptables al ancho completo, cards táctiles con área de toque ≥44px, barra de presets con swipe horizontal suave sin scrollbars antiestéticos.
  4. ⏱️ Velocímetros y osciloscopio FFmpeg (`.gauges-row`) escalados limpiamente para encajar en 3 columnas sin desbordar el contenedor.
  5. 🎛️ Modales convertidos a experiencia móvil estilo bottom-sheet táctil (`border-radius: 20px 20px 10px 10px; max-height: 85vh`).
  6. 🖥️ Layout del editor de video en una sola columna con reproductor limitado a `48vh` para edición cómoda con una sola mano.
  Verificado: 223 tests unitarios pasando al 100% y validación Playwright en 4 viewports móviles.
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~09:05):** Tarea 15: Suite de 5 mejoras para el panel de Configuración y Diagnóstico:
  1. ▶️ Arranque interactivo de Ollama (`POST /api/system/start_ollama`) y botón `↻ Actualizar` en vivo en el modal.
  2. 🧠 Selector de proveedor de IA (Ollama Local, Gemini Cloud o Heurístico Puro) persistente en base de datos (`system_kv`).
  3. 📦 Selector de modelos instalados de Ollama (`GET /api/system/ollama_models`) con selección dinámica en la UI.
  4. 💻 Monitor de hardware en vivo en diagnóstico (CPU núcleos/%, RAM usada/total, GPU AMF acelerada).
  5. ⚡ Test de latencia de IA ("Ping IA") (`POST /api/system/test_ai`) con medición en milisegundos y feedback visual.
  Verificado: 223 tests unitarios pasando al 100% y captura de pantalla Playwright en `docs/captured_screenshots/screen_modal_upgraded.png`.
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~08:45):** Tarea 14: Paquete de 7 mejoras de productividad y refinamiento:
  1. 🔍 Búsqueda rápida y ordenación interactiva en la galería de clips (`#clip-search-input`, `#clip-sort-select` por mayor puntaje, más recientes o duración).
  2. 🎨 Selector de paleta de colores de resalte karaoke en subtítulos (`custom_highlight` en API, jobs y pipeline: amarillo, verde lima, cian eléctrico, fucsia TikTok, naranja fuego).
  3. 🎬 Hover preview dinámico (reproducción silenciosa en video HTML5 al pasar el cursor sobre las miniaturas).
  4. 🧹 Monitor de almacenamiento y limpiador de caché temporal (`GET /api/system/storage` y `POST /api/system/cleanup_cache` con botón en ajustes).
  5. 🏷️ Nombres de archivo limpios y descriptivos al descargar clips individuales (`clip_[score]pts_[titulo].mp4`).
  6. 🕒 Historial interactivo de URLs recientes en panel Crear (`#recent-urls-box` con chips clicables y persistencia en `localStorage`).
  7. 📄 Exportación del guion / transcripción completa en formatos TXT y VTT (`/api/videos/{video_id}/transcript/export?format=txt|vtt`).
  Verificado: 222 tests unitarios pasando al 100% y validación Playwright completa en navegador.
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~08:28):** Tarea 13: Prueba de fuego en vivo con video real de YouTube (envío de trabajo real vía /api/jobs con descarga de tramo real, transcripción Whisper small, detector de momentos virales, auto-encuadre vertical 9:16, renderizado con subtítulos estilo Hormozi y descarga verificada del paquete ZIP de 15 MB en 32 segundos).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~08:08):** Tarea 12: Marcadores de chat de Twitch / YouTube Live (analizador de velocidad de chat, picos de mensajes por segundo y emotes de hype 'LUL/OMG/????/KEKW/CLIP' como señal de viralidad en momentos candidatos).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~07:55):** Tarea 11: Modo B-Roll / Video secundario inferior (Estilo TikTok Gameplay: opción de metraje inferior en bucle de data/broll o generador procedural dinámico de retención en FFmpeg bajo el hablante centrado).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~07:45):** Tarea 10: Detección y badges visuales de directos en vivo (/api/validate_url informa is_live e is_upcoming, y la tarjeta de previsualización muestra badge pulsante rojo '🔴 EN VIVO' y aviso amigable).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~07:23):** Tarea 9: Modo Split-Screen / Pantalla dividida Podcast 2 caras (soporte de layout 'split' en panel Crear, api_server, choose_framing y clip_maker con auto-detección de 2 hablantes).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~07:18):** Tarea 8: Filtro y badges por categoría de gancho IA (humor, debate, épico, revelación, consejo) en la biblioteca de clips con filtrado en tiempo real.
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~07:12):** Tarea 7: Generador de Hooks A/B/C interactivo en editor de copys y empaquetado masivo en ZIP con subtítulos .SRT individuales por clip.
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~07:05):** Tarea 6 (EXTRA): Recorte real del clip en el editor (conectar los manejadores `[ ]` de inicio/fin a `PATCH /api/clips/{id}` y botón de aplicar recorte re-renderizando con feedback de duración y validación).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:05):** Tarea 1: Vista previa del enlace + tiempo estimado (miniatura yt-dlp en /api/validate_url, cálculo tiempo estimado con historial real de jobs y video_duration, tarjeta visual con miniatura, canal, duración, sugerencia no bloqueante de Desde/Hasta si > 30 min, protección SSRF y tests unitarios).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:16):** Tarea 2: Selector de idioma y duración del clip (selectores en panel Crear: Auto/ES/EN/PT y Corto 15-30s / Medio 30-60s [default] / Largo 60-90s, JobBody -> jobs.py -> pipeline -> detector con min/max duration, validación contra MIN_CLIP_SEC/MAX_CLIP_SEC y tests unitarios).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:21):** Tarea 3: Aviso al terminar (Notification API del navegador con permiso solo tras clic del usuario, audio armónico sintético vía Web Audio API, progreso dinámico en título de pestaña '(XX%) Clip Factory AI' restaurado al finalizar, interruptor con persistencia en localStorage).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:25):** Tarea 4: Recordar ajustes y presets (persistencia automática en localStorage de todos los ajustes del panel Crear y restauración al abrir, presets integrados Podcast/Gaming/Entrevista y presets personalizados con nombre guardar/aplicar/borrar, sin almacenar URL ni datos sensibles, protegido con try/catch).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~06:30):** Tarea 5: Requisitos en Configuración (endpoint GET /api/health/deps de solo lectura con FFmpeg + versión, encoder h264_amf/libx264, Ollama + modelo, modelo Whisper, modelo YuNet, sin exponer rutas sensibles ni tokens; vista con checks claros ✓/✗ y frases explicativas en modal de configuración; tests unitarios mockeados en test_api_server.py).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~04:30):** Ajuste de posición y tamaño de subtítulos (opciones en panel Crear y en Editor para mover y achicar subtítulos y no tapar rostros; soporte en `subtitles.py`, `clip_maker.py`, `pipeline.py`, `jobs.py`, `api_server.py` y `index.html` con previsualización reactiva en reproductor y tests unitarios).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:42):** Tarea A (Panel FFmpeg con métricas reales del trabajo: paso actual, progreso, tiempo transcurrido, tiempo restante estimado, y '—' cuando no haya trabajo activo; sin FPS inventados ni velocidades fijas).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:45):** Tarea B (Menú lateral: restaurados 'Subtítulos' como atajo al editor/transcripción y 'Plantillas' como atajo a los estilos de subtítulos del panel Crear).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:45):** Tarea C (Limpieza de referencias a #crear-panel en script v3, adaptando goToCrear, openCrearModal y syncPressed al layout SaaS actual).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:48):** Tarea D (Detector de picos de volumen find_hype_moments: activado solo con layout gaming/streamer o include_hype explícito, títulos y copys contextuales basados en transcripción real, duración dinámica y deduplicación con candidatos previos).
- [x] **COMPLETADO POR ANTIGRAVITY (08-nov ~03:52):** Tarea E (Puntajes saturados: implementada normalización por percentiles 66-97 dentro del conjunto de candidatos de cada video, preservando estrictamente el orden relativo y reescalando el desglose breakdown. Con tests unitarios).
- [ ] `/api/validate_url`: mostrar en la interfaz si el enlace es un directo en vivo (Claude puede añadirlo tras avisar).
- [ ] Grabar un directo en vivo durante N minutos (hoy se rechaza con un mensaje claro).
- [ ] Marcadores de tiempo del chat de Twitch como señal de viralidad.
