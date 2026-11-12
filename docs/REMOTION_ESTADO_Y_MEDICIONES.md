# Remotion en Clip Factory Pro — estado, correcciones y mediciones (Claude, 12-nov-2026)

Reparto vigente: **Claude = Remotion** (`src/remotion/`, `src/common/remotion_engine.py`, sus tests). Antigravity = HyperFrames. Remotion **no está activado por defecto** en el pipeline: el motor FFmpeg+ASS sigue siendo el de producción.

## Defectos encontrados al renderizar un clip real (47 s del video completo de 22 min)
| # | Defecto | Cómo se detectó | Estado |
|---|---|---|---|
| 1 | **Cualquier clip de más de 30 s fallaba**: la composición tenía duración fija de 900 frames y el motor pedía `0-1409`. | Render real: `frame range 0-1409 is not inbetween 0-899` | **Corregido** (`calculateMetadata` en `Root.tsx`) y verificado con render real |
| 2 | **El video empezaba en 0:00 del original, no en el inicio del clip** (faltaba `trimBefore`). La prueba anterior usaba un clip que empezaba en 0 s y lo ocultaba. | Lectura del código; confirmado comparando fotogramas del render con el original en los mismos instantes | **Corregido** en las 3 composiciones con video |
| 3 | Dos capas de video con audio (fondo difuminado + video nítido) podían duplicar el sonido. | Lectura del código | Capa de fondo en `muted`. El render real conserva el volumen del original (media −17.6 dB y pico −0.8 dB, idénticos a la fuente) |
| 4 | **Cancelar dejaba procesos**: `proc.terminate()` en Windows solo mata `npx.cmd`, no node/Chromium/FFmpeg. | Lectura del código | **Corregido**: `kill_process_tree` (psutil) |
| 5 | `stderr` sin vaciar durante el render (riesgo de bloqueo) y cancelación solo al llegar una línea de salida. | Lectura del código | **Corregido**: stderr unido a stdout, lector en hilo, cancelación cada 0.5 s |
| 6 | Sin tiempo máximo. | Lectura del código | **Corregido**: `timeout_s` (1800 s por defecto) |
| 7 | Archivo de props con nombre por milisegundo (posible choque entre renders simultáneos). | Lectura del código | **Corregido**: UUID |

## Pruebas
- `tests/test_remotion_engine_process.py` (nuevo, 5 pruebas, **sin Node ni Chromium**): mata árbol padre+hijo, cancelación, tiempo máximo, props únicos, error real. Junto a `test_remotion_engine.py`: **9 pasan**.
- **Cancelación real** con Remotion y Chromium a los 45 s: terminó en 45.5 s, sin MP4 a medias, sin procesos node/Chromium/FFmpeg vivos después.

## Medición real (Ryzen 7 5825U, 1 render, concurrency 2, clip de 47 s)
| | Remotion | FFmpeg + ASS (producción, mediciones de la Fase 2) |
|---|---|---|
| Tiempo | **310.8 s** (6.6× el tiempo del clip) | 140–165 s por clip de 42–61 s (1 clip a la vez, 8 hilos) |
| RAM pico (todos los procesos del render) | **5.64 GB** (media 3.5) | ≈ 1.0 GB |
| CPU media / máx. | 43.8 % / 69.6 % | 33.6 % media (render + escaneo, otra prueba) |
| Procesos Chromium a la vez | hasta 6 | 0 |
| Tamaño | 74.3 MB (13.3 Mbps), H.264 + AAC 48 kHz estéreo | ≈ 71 MB de media por clip |

Cautelas: son dos pruebas distintas (otro clip, otro momento); el equipo se comparte con otro agente; una sola corrida por configuración. **Indicativo, no concluyente.** Lo que sí es claro: Remotion cuesta alrededor del doble de tiempo y 5 veces más RAM por clip.

## Lo que Remotion NO hace hoy (diferencias con el pipeline de producción)
- Encuadre: solo "blur" (video apaisado centrado sobre fondo difuminado). No usa el seguimiento facial ni el recorte inteligente 9:16 de FFmpeg (el motor no le pasa `faceTrackingPoints`).
- Audio: copia el audio del original; **no aplica** la masterización (loudness, limitador), la mezcla de SFX ni el recorte de silencios del pipeline.
- No hay B-roll, ni titular dinámico, ni miniaturas, ni integración con la cola de trabajos ni con la cancelación de `jobs.py`.
- Cada video nuevo se **copia entero** a `src/remotion/public/` (229 MB el de 22 min).

## Veredicto honesto
IMPLEMENTADO y PROBADO: el render de un clip real funciona de principio a fin tras las correcciones (con video correcto, subtítulos sincronizados, audio sin cambios de nivel, cancelación limpia).
NO APROBADO como motor de producción: más lento y pesado, sin paridad de funciones, no conectado a la cola.

## Pendiente (en orden propuesto)
1. Paridad de audio: renderizar la parte visual sin audio y dejar que FFmpeg mezcle el audio masterizado.
2. Enganche a `jobs.py` con cancelación y estado de progreso, detrás de una opción `visual_engine`, desactivado por defecto.
3. Evitar la copia del video completo a `public/` (servir solo el tramo del clip).
4. Comparar con HyperFrames cuando Antigravity tenga su primera plantilla (misma prueba, mismo clip).

---
## Actualización — audio masterizado y enganche opcional (12-nov, tarde)

### Qué se implementó
- **Audio masterizado**: Remotion renderiza **solo la imagen** (`--muted`) y FFmpeg une el audio del original pasado por la **misma cadena** que el motor FFmpeg (`build_audio_filter_chain`: loudnorm −14 LUFS + limitador + micro-fundido). La imagen se copia con `-c:v copy` (una sola codificación de video). Se valida con ffprobe (video y audio presentes, duraciones coherentes).
- **Enganche opcional** `visual_engine`: `"ffmpeg"` (por defecto) o `"remotion"`, en `rerender_candidate` (`pipeline.py`), en la rama de re-render de `jobs.py` y en `POST /api/clips/{id}/rerender?visual_engine=remotion`. Si Remotion no está o falla, se registra el motivo y se usa FFmpeg sin duplicar el clip.
- **Cancelación de un render en marcha**: `POST /api/jobs/{id}/cancel?force=true` mata el árbol de procesos de Remotion. (Con FFmpeg no se puede interrumpir.)
- Conversión del color de resaltado ASS (`&H0000FFFF`) a CSS (`#FFFF00`).
- **No** se tocó `index.html`: la interfaz para elegir motor queda para Antigravity.

### Verificación real (clip de 47 s del video de 22 min, Ryzen 7 5825U)
| Comprobación | Resultado |
|---|---|
| Render completo de principio a fin | **257.6 s**, 1080×1920, H.264 + AAC, 73.6 MB, duración 47.0 s |
| Audio | original −14.7 LUFS / pico −0.8 dBFS → final **−14.1 LUFS / pico −1.8 dBFS** (masterizado) |
| Momento del video y subtítulos | fotogramas a los 12 s y 30 s coinciden con el original; subtítulos en el color pedido; barra de progreso visible |
| Pruebas automáticas | 7 nuevas (`test_remotion_integration.py`) + 5 de procesos; suite: **302 pasan, 4 fallan** (los mismos 4 de antes) |

### Estado por funcionalidad
| Funcionalidad | IMPLEMENTADO | PROBADO | APROBADO | PENDIENTE |
|---|---|---|---|---|
| Render de clip real con Remotion | sí | sí (2 renders reales) | no | — |
| Audio masterizado (loudnorm + limitador) | sí | sí (−14.1 LUFS) | no | comparar oído contra el motor FFmpeg |
| Cancelación (árbol de procesos) | sí | sí (real y en pruebas) | no | cancelar vía API real con el servidor |
| Fallback a FFmpeg | sí | sí (prueba unitaria) | no | probar con Chromium roto real |
| Enganche en `jobs`/API | sí | parcial (pruebas unitarias; no se ejecutó un job real) | no | job real de punta a punta |
| SFX, B-roll, recorte de silencios, encuadre inteligente | **no** | — | — | paridad con el motor FFmpeg |
| Interfaz | no | — | — | Antigravity |
| Tiempo/RAM | — | 258–311 s y ≈ 5.6 GB por clip de 47 s | **no aprobado** (≈ 2× más lento y 5× más RAM que FFmpeg) | optimizar o aceptar |
