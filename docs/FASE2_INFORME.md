# Clip Factory Pro — Informe de Fase 2 (medir antes de optimizar)

Fecha de las mediciones: 12-nov-2026 (madrugada). Equipo: AMD Ryzen 7 5825U (8 núcleos / 16 hilos, chip de portátil), 23.3 GB RAM, gráficos integrados, Windows 11 IoT Enterprise LTSC *Evaluation* 10.0.26100, Python 3.11.18, FFmpeg 9.0.2.
Regla seguida: **no se instaló nada, no se cambió ningún modelo ni configuración de producción, no se borró nada.** Los scripts de medición viven fuera del repositorio (carpeta temporal de la sesión); aquí solo se guardan los resultados.

> **Advertencia de validez (importante).** Mientras corrían las mediciones, otro agente trabajó en el mismo equipo: instaló Remotion (`src/remotion/node_modules`, 784 MB, entre 02:33 y 02:43), lanzó renders de prueba de Remotion (03:02–03:07) y ejecutó `pytest` (03:20). Eso comparte CPU con mis pruebas. Cada tabla indica qué corrida solapó con esa actividad. **Las cifras son indicativas, no definitivas.**

## 1. Tabla comparativa de modelos de transcripción
Mismo audio de 10 min (min 10:00–20:00 del video CP7w9VZAAGI), mismos parámetros que producción (INT8, 8 hilos, `beam_size=1`, VAD, prompt dominicano, `condition_on_previous_text=False`).

| | small INT8 | large-v3-turbo INT8 |
|---|---|---|
| Carga del modelo (separada) | 2.3 s | 17.4 s |
| Inferencia (10 min de audio) | 137 s | 282 s |
| Factor de tiempo real (RTF) | 0.228 | 0.470 |
| RAM del proceso: tras cargar / pico | 0.33 / 0.96 GB | 0.87 / 1.56 GB |
| CPU del sistema (media / máx.) | 62.5 % / 88.6 % | 59.5 % / 100 % |
| Segmentos / palabras | 182 / 1689 | 242 / 1574 |
| Confianza media por palabra* | 0.779 | 0.882 |
| Palabras con confianza < 0.7* | 29.2 % | 15.4 % |
| Timestamps: palabras de duración ≤ 0 / > 2 s | 31 / 2 | 12 / 4 |
| Solapes o saltos atrás entre palabras | 0 / 0 | 0 / 0 |
| Solape con la actividad del otro agente | final de la corrida (02:33–02:34) | **toda la corrida** (02:34–02:39, `npm install`) |

\* La "confianza" es la autoevaluación del propio modelo; **no es precisión** y no es comparable entre modelos.

**Calidad: no se puede declarar a un modelo más preciso.** No hay transcripción de referencia verificada. El `transcript.srt` que se aportó **ya no existe en disco** (no está en Descargas), así que no se calculó WER contra él, y de todos modos tampoco estaba verificado. Lo único comparable:
- Entre sí, los dos modelos difieren en el **32.8 %** de las palabras (WER cruzado). Eso mide desacuerdo, no quién acierta.
- Observación cualitativa (no es una medición): en varias ventanas de la muestra, turbo devuelve el texto sin puntuación ni mayúsculas, mientras que small sí las pone. Eso afecta la lectura de los subtítulos.
- La muestra para evaluación manual está en `docs/FASE2_muestra_evaluacion_manual.md` (24 ventanas de 15 s con ambos textos y una columna para marcar cuál es correcto). **Hace falta que alguien escuche las ventanas.**

## 2. Modo híbrido: qué hace realmente
Verificado leyendo el código y ejecutándolo:
- `settings.asr.mode = "hybrid"` y `secondary = "qwen3"` **no se leen en ningún sitio** del código.
- El pipeline llama a `transcriber.transcribe()` (y `viral_pack.py` también). **`transcribe_with_review()`, la única ruta que usa el verificador híbrido, no la llama nadie.**
- Aun si se llamara: se construye con `enable_secondary=False`.
- **Qwen3 no se ejecuta.** `torch`, `transformers` y `qwen_asr` no están instalados; `Qwen3ASREngine.transcribe()` devuelve `None` al instante (0.000 s) = fallback correcto y sin error. Y aunque se instalara torch, `transcribe()` solo contiene `return []` (un marcador de posición): **nunca hace inferencia**. La comparación de textos del verificador es un `pass`.
- `Qwen3ForcedAligner.align_words()` devuelve los segmentos tal cual en los dos casos (con o sin torch).
- La verificación en la nube (ElevenLabs) tampoco llama a ningún servicio: solo cuenta segmentos.
- Coste adicional del verificador: **0.04 s** por 10 min de audio. La normalización de jerga dominicana cambió **0 de 242** segmentos en esta muestra.
- Conclusión: el "modo híbrido" activo es, en la práctica, Whisper solo. No aporta ni cuesta nada hoy. No mejora la transcripción porque no hace nada.

**Transcripción selectiva (evaluación, sin implementar).** Estimación con los datos medidos: transcribir con small (137 s) y volver a pasar turbo solo por los segmentos de baja confianza (prob. media < 0.7 = 20 % de la voz, 103 s) costaría ≈ 186 s frente a 282 s de turbo completo (≈ 34 % menos). **Riesgo:** small se equivoca con confianza alta (difiere 32.8 % de turbo), así que filtrar solo por probabilidad dejaría errores sin revisar. Es una estimación, no una medición, y su calidad no está validada.

## 3. Render: 1, 2 y 3 clips simultáneos
Pack de 3 clips (148 s de contenido) del video completo de 22 min, con las opciones del pack real (Hormozi, barra de progreso, color cinema, zoom dinámico y punch, B-roll, SFX, encuadre inteligente). Se escribió en carpeta temporal.

| Configuración (workers × hilos por clip) | Tiempo total medido | Tiempo por clip | RAM pico (python + FFmpeg) | CPU sistema (media) | Frec. media / temp. media y máx. | Solape con otro agente |
|---|---|---|---|---|---|---|
| 1 × 8 | **1155.7 s** | 140 / 165 / 149 s | 1.02 GB | 48 % | 3065 MHz / 73 °C / 88.9 °C | último minuto |
| 2 × 6 | **889.0 s** | 203 / 242 / 153 s | 1.44 GB | 52 % | 2669 MHz / 71 °C / 73.9 °C | Remotion y esbuild durante la corrida |
| 3 × 4 (actual) | **no válido** | 253 / 225 s (el tercero marcó 28 562 s) | 2.4 GB | — | — | `pytest` al inicio; **el equipo se suspendió** durante la prueba |

- En la corrida 3 × 4 el equipo entró en suspensión (el reloj saltó ~8 h), por eso el total (29 061 s) es un artefacto. Solo son fiables los tiempos de los dos clips que terminaron: 225–253 s cada uno en paralelo.
- Frecuencia sostenida: base 2.0 GHz; en carga el chip subió a 2.7–3.9 GHz y a 73–89 °C. Con tres renders en paralelo cada clip tardó ≈ 70 % más que solo, lo que sugiere límite térmico/energético y no falta de hilos. (No tengo una medición limpia que lo confirme.)
- **CORRECCIÓN (13-nov): este "hallazgo" era un artefacto de mi prueba, no un problema de producción.** En 1 × 8 el render fue 454 s y el total 1155 s; los ≈ 700 s sobrantes son `detect_scene_cuts` recorriendo el video completo (**629 s medidos**, un hilo, 337 cortes). Pero ese escaneo solo ocurre si se llama a `generate_clips_parallel` **sin** `scene_cuts`, que es lo que hizo mi script. El pipeline real (`pipeline.py`, líneas 263-292) **ya calcula los cortes solo alrededor de cada clip** con `detect_scene_cuts_near` y los pasa ya hechos; hay tests (`test_scene_cuts_near.py`, `test_pipeline.py`) y un comentario en el código que lo documenta. Por tanto **los totales de 1155 s y 889 s de esta tabla están inflados ≈ 500-700 s y no representan el pack de producción**. Solo valen los tiempos por clip y la comparación entre configuraciones. Ningún llamador de `src/` usa hoy ese camino lento.
- Estimación (no medida) de la fase de render pura, que es lo que cuesta el pack en producción: 1 × 8 ≈ 454 s, 2 × 6 ≈ 395 s, 3 × 4 ≈ 250 s.

## 4. Configuración de concurrencia
Con lo medido **no hay base para cambiar `parallel_clips=3 / threads_per_clip=4`**: 3 en paralelo dio el mejor tiempo de render estimado, con solo 2.4 GB de RAM. Falta una corrida limpia (sin otro agente y sin suspensión) para confirmarlo. No conviene subir los hilos por proceso: con 3 clips ya se usa el equivalente a 12 hilos y la temperatura llegó a 89 °C con 8 hilos en un solo clip.

## 5. Consumo de memoria
Pico del proceso: 1.0–2.4 GB en render, 1.0–1.6 GB en transcripción. El sistema marcó 13–16 GB usados, pero incluye otros programas. El límite `max_ram_usage_gb=18` está muy por encima de lo que usa el pipeline; solo registra un aviso, no pausa nada.

## 6. Auditoría de caché (solo lectura)
Existen **dos** cachés de transcripción, ninguna incluye el modelo ni una versión:
- `data/cache/transcripts/<nombre_archivo>.json` (pipeline): la clave es **solo el nombre del archivo**. Dos videos distintos con el mismo nombre compartirían transcripción, y al cambiar de modelo se seguiría sirviendo la anterior.
- `data/cache/tx_<nombre>_<tamaño>_<mtime>_<idioma>_<dominicano>.json` (Transcriber): incluye tamaño y fecha, pero tampoco el modelo.
- Otras cachés: subtítulos ASS por clip (57 archivos), `broll/` y `sfx/` (bibliotecas), `whisper_models/` (1.5 GB turbo + small + base + tiny).
- **No encontré** caché de audio extraído (el pipeline descarga el audio aparte para enlaces, pero para archivos locales transcribe el video directo), de detecciones faciales, de cortes de escena, ni de miniaturas. Los cortes de escena (solo alrededor de cada clip, segundos) se recalculan en cada pack; no se cachean.

## 7. Dependencias
- `opencv-python` y `opencv-python-headless` (ambos 5.0.0.93) escriben en **la misma carpeta `cv2/`**. Solo `face_tracker.py` importa cv2 y usa funciones sin ventana (`VideoCapture`, `FaceDetectorYN`): bastaría la versión headless. `opencv-python` está instalado porque `scenedetect` (usado en `clip_maker.detect_scene_cuts`) lo declara como requisito. No se desinstaló nada. Desinstalar uno puede borrar archivos que usa el otro; hay que reinstalar y correr pruebas.
- `ffmpeg-python` y `httpx2` figuran en `requirements.txt` pero no los importa `src/`, `tests/` ni `scripts/` (no revisé `tools/`).
- **`tools/`: 159 archivos** (no se tocó ninguno): 45 de inspección/diagnóstico de solo lectura, 33 parches de una sola vez que reescriben archivos del proyecto, 30 de QA/pruebas/auditorías, 16 generadores de assets y capturas, 14 generadores de la interfaz, 10 plantillas HTML, 11 otros, más `cloudflared.exe` (53 MB) y `ffmpeg/`.

## 8. Hallazgo fuera del alcance: Remotion ya está en el proyecto
En la Fase 1 dije que no había Remotion. **Era falso en el momento de esta fase:** existe `src/remotion/` (package.json de 02:33, `node_modules` 784 MB, `render.mjs`) y `src/common/remotion_engine.py`, creados por otro agente mientras yo medía. Yo no lo instalé y no lo toqué. Está sin versionar (`??` en git). No lo mido: la instrucción era no instalarlo y mantenerlo como prototipo posterior. Conviene decidir quién lo mantiene y no mezclarlo con estas pruebas.

## 9. Mejoras posibles sin dependencias nuevas (pendientes de aprobación)
1. ~~Cortes de escena~~ **Retirada:** el pipeline ya usa `detect_scene_cuts_near` (ver corrección en la sección 3). Solo quedaría, como red de seguridad opcional, hacer que el camino de respaldo de `generate_clips_parallel` también use detección local; no mejora nada hoy porque nadie lo usa.
2. **Claves de caché** de transcripción: incluir modelo, idioma, modo dominicano y versión, y unificar las dos cachés.
3. **Quitar el modo híbrido muerto** o conectarlo de verdad (hoy no hace nada); si se quiere re-pasar solo los segmentos dudosos, hacerlo con el mismo faster-whisper (turbo sobre los segmentos de baja confianza).
4. **Resource Manager mínimo** con `psutil`: pausar o bajar a 1 render cuando la RAM disponible caiga y cuando la temperatura pase de un umbral (la lectura existe en `ThermalZoneInformation`, aunque no es una API estable).
5. (Menor) Cachear los cortes de escena locales por video; hoy cuestan segundos.

## 10. Dependencias que justificarían instalación (aún no se justifican)
Ninguna por ahora. WhisperX y pyannote exigirían torch (varios GB) y, para pyannote, una cuenta de Hugging Face; no hay evidencia medida de que hagan falta mientras no exista una referencia verificada que muestre el problema. MediaPipe no se justifica mientras YuNet funcione. Remotion ya está instalado por otro agente; su coste real debe medirse contra el render FFmpeg+ASS en una fase aparte.

## 11. Qué falta
- Escuchar la muestra manual y decidir small vs turbo (hoy no hay evidencia de calidad).
- Repetir la corrida de render 3 × 4 en un equipo en reposo (sin otro agente ni suspensión) y las pruebas de 10, 30 y 120 min (solo existe material de 22 min).
- Aprobación para aplicar las mejoras de la sección 9.
