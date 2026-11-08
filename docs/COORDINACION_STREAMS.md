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

## Zonas reservadas (no editar sin avisar aquí)
- **Antigravity:** `framing.py`, layout gaming, sección de streams del HTML, `find_hype_moments`.
- **Claude:** `stream_guard.py`, `tests/test_stream_guard.py`, `tests/test_security.py`, `trimming.py`, `audio_energy.compute_energy_profile`.
- **Compartidos (editar con cuidado y releer antes):** `pipeline.py`, `api_server.py`, `jobs.py`, `youtube_downloader.py`, `index.html`.

## Reglas
1. Releer el archivo justo antes de editarlo; otro agente pudo cambiarlo.
2. No reiniciar el servidor si `GET /api/jobs` muestra trabajos `queued` o `running`.
3. No ejecutar la suite completa mientras el otro agente la corre; probar solo los tests propios (`pytest tests/test_stream_guard.py`).
4. El servidor lo abre el usuario con `start.bat`; un servidor lanzado por un agente se cierra cuando el usuario reinicia el suyo.

## ✅ Resuelto: túnel público con contraseña
Había un túnel `*.trycloudflare.com` abierto con `"auth": false`. Ahora el servidor exige token en `/api` y `/clips_media`
(salvo `/api/health`), tanto en local como por el túnel (verificado: 401 sin token, 200 con token).
- El token vive en `data/api_token.txt` (carpeta `data/`, fuera de git). El servidor lo lee en cada petición, así que
  **protege aunque lo arranque cualquiera** (start.bat, Antigravity, Claude). Cambiar el archivo rota el token sin reiniciar.
- `CLIP_API_TOKEN` (variable de entorno) tiene prioridad sobre el archivo.
- Primer acceso: abrir `https://<tunel>/?token=<token>` una vez; queda una cookie de 30 días (HttpOnly, SameSite=Strict, Secure por HTTPS).
- **Regla:** nadie borra, imprime ni pega `data/api_token.txt` en chats, logs o documentos.
- Nota: `request_guard` acepta cualquier `*.trycloudflare.com` como Host (cambio de Antigravity). Es aceptable ahora que hay token.

## Pendiente / ideas (reclamar aquí antes de empezar)
- [ ] `/api/validate_url`: mostrar en la interfaz si el enlace es un directo en vivo (Claude puede añadirlo tras avisar).
- [ ] `include_hype=True` añade "momentos épicos" de 20 s con título genérico también en podcasts; valorar activarlo solo con el layout gaming/streamer (decisión de Antigravity).
- [ ] Grabar un directo en vivo durante N minutos (hoy se rechaza con un mensaje claro).
- [ ] Marcadores de tiempo del chat de Twitch como señal de viralidad.
