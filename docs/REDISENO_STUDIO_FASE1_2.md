# Clip Factory Pro — Rediseño "AI Creative Studio" · Fases 1 y 2

Estado: **solo documentación. Ningún código de la interfaz se ha cambiado para esta fase.**
Fuente de verdad: el código actual (`src/web/index.html` ≈ 525 KB / 11 425 líneas, `src/api_server.py`), consultado el 10-nov.

## FASE 1 — Descubrimiento

### 1.1 Estructura actual
- Frontend: **un solo archivo** `src/web/index.html` (CSS + HTML + 4 bloques `<script>`, JS vanilla, sin framework ni build). Lo sirve `GET /`.
- Navegación por `switchView(id)` sobre 8 secciones `view-*`: `inicio`, `editor`, `miniaturas`, `copys`, `ffmpeg`, `proyectos`, `historial`, `analytics`.
- Auth: `request_guard` (Host/Origin), `token_guard` + cookie `HttpOnly clip_token` emitida por `/api/auth/login`. Token hoy **desactivado por decisión del usuario**. El frontend ya no guarda el token.
- Backend (FastAPI): ~50 endpoints. Pipeline real: faster-whisper → detector (Ollama/heurístico/energía de audio) → clip_maker (FFmpeg, YuNet, subtítulos ASS) → SQLite. Cola de un solo worker (`src/jobs.py`).
- Tests: 34 archivos `tests/test_*.py`. Hay 61 de seguridad+API verificados en esta sesión; **la suite completa no se ha corrido en esta fase**.
- Hay otro agente (Antigravity) editando el mismo repo → ver reglas en `docs/COORDINACION_STREAMS.md`.

### 1.2 Mapa módulo nuevo → funcionalidad existente

| Módulo nuevo | Vista actual | Endpoints reales | Estado |
|---|---|---|---|
| Home | `view-inicio` (parte) | `/api/videos`, `/api/clips`, `/api/jobs` | Existe, hay que recomponer |
| Create | `view-inicio` (panel Crear) | `/api/upload`, `/api/validate_url`, `POST /api/jobs`, `/api/process` | Existe (archivo + URL + rango de tiempo + opciones) |
| Editor | `view-editor` | `/api/clips/{id}`, `PATCH`, `/rerender`, `/transcript` (GET/PUT), `/export_srt`, `/broll`, `/sfx`, `/dominicanize` | Existe edición de subtítulos/estilos y re-render. **No hay timeline multipista real** (ver 1.3) |
| Clips | `view-inicio` galería + `view-historial` | `/api/clips`, `/clips/{id}/download`, `/status`, `DELETE /api/clips?confirm=yes`, `/qr`, `/download_info` | Existe |
| AI Tools | `view-copys`, `view-miniaturas` + panel del editor | `/generate_hooks`, `/generate_thumbnail`, `/suggest_artists`, `/gallery`, `/broll/catalog`, `/sfx/catalog`, `/dominicanize`, `/system/test_ai` | Existe, hoy disperso en 3 sitios |
| Projects | `view-proyectos` | `/api/videos`, `/api/videos/{id}/zip`, `/transcript/export` | Existe |
| Processing | `view-historial` + `view-ffmpeg` + banner global | `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/cancel`, `/api/system/metrics` | Existe (progreso real, `idle_seconds`, cancelación cooperativa) |
| Analytics | `view-analytics` | `/api/analytics` (`total_videos, total_clips, approved_clips, avg_score, time_saved_hours`), `/api/health/deps` | Existe, **solo 5 métricas reales** |
| Settings | modal/paneles dispersos | `/api/config`, `/api/system/ai_config` (GET/POST), `/system/ollama_models`, `/system/start_ollama`, `/system/storage`, `/system/cleanup_cache`, `/health/deps` | Existe, sin pantalla propia |

### 1.3 Capacidades que NO existen (se marcan como "propuestas", no se simulan)
1. **Timeline multipista editable** (mover/recortar clips en pistas de vídeo y audio): no hay endpoint que acepte una edición de pistas. El backend solo hace *re-render* con opciones (estilo, posición, B-roll, SFX, zoom, etc.) y recorte por rango al descargar.
2. **Biblioteca de audio del proyecto** y de "recursos": solo hay catálogos fijos de B-roll y SFX.
3. **Métricas de rendimiento social** (vistas, retención, ingresos): inexistentes. No se mostrarán.
4. **Proyectos con nombre/estado propios**: hoy "proyecto" = vídeo fuente (`vid_*`). No hay entidad Proyecto ni fecha de modificación. Propuesta, no implementado.
5. **Logs de proceso** por job: no hay endpoint de logs; solo `message`, `progress`, `error`.
6. **Importar por URL**: soportado vía yt-dlp (con límites de directos); se mantiene.

> Consecuencia para el Editor: lo que se puede construir **de verdad** es un espacio de trabajo profesional (biblioteca + previsualización grande + inspector contextual + línea de tiempo de **un clip**: playhead, palabras de subtítulo, marcas de B-roll/SFX que ya existen en datos). La edición libre multipista queda como *propuesta*, con los controles deshabilitados y rotulados.

### 1.4 Riesgos de la migración
- Un único archivo de 11 k líneas con ~195 manejadores `onclick` en línea y estado global: reescribirlo de golpe rompe flujos.
- Antigravity también edita `index.html` → conflictos si no hay reclamo de zonas.
- Cada "pantalla nueva" debe conservar los IDs que usa el JS actual hasta migrarlo.

## FASE 2 — Especificación de diseño

### 2.1 Tokens (los del brief, sin cambios)
```
--bg:#090B10  --s1:#11151E  --s2:#191F2B  --s3:#202838  --line:#293242
--tx:#F4F5F7  --tx2:#929BAA  --tx3:#657084
--violet:#A78BFA  --teal:#38D6C8  --action:#E6FF70
--ok:#4ADE80  --warn:#FBBF24  --err:#F87171
```
- Espaciado: 4 · 8 · 12 · 16 · 24 · 32 · 48. Radios: 6 (controles) · 10 (paneles) · 14 (vídeo/modal).
- Tipografía: Inter (UI) + JetBrains Mono (tiempos, métricas). Escala: 11/12/13/15/18/24. Títulos de página 18–24 px, no más.
- Acento de acción **lima** solo para la acción primaria de cada pantalla; violeta para selección/foco; teal para estado "en proceso".
- Foco visible 2 px violeta; `prefers-reduced-motion` respetado; transiciones 120–200 ms.

### 2.2 Estructura de aplicación (shell)
```
┌ rail 64px ┬──────────── barra de contexto (proyecto · estado de cola · buscar) ────────────┐
│ Home      │                                                                                │
│ Create    │                       área de trabajo (flexible)                               │
│ Editor    │                                                                                │
│ Clips     │                                                                                │
│ AI Tools  │                                                                                │
│ Projects  │                                                                                │
│ Processing│                                                                                │
│ Analytics │                                                                                │
│ Settings  └────────────────────────────────────────────────────────────────────────────────┘
```
- Rail compacto (iconos) que se expande a 220 px con etiquetas; el indicador de proceso vive en la barra de contexto y enlaza a Processing.
- Móvil: barra inferior con 5 destinos (Home, Create, Clips, Processing, Más). El Editor en móvil es **vista dedicada** (preview arriba, inspector en hoja inferior, sin timeline multipista).

### 2.3 Wireframes (resumen por pantalla)
- **Home:** héroe con una sola acción "Crear proyecto" + zona de soltar vídeo; debajo, rejilla grande de proyectos recientes (miniaturas 16:9), tira de clips recientes (9:16) y panel "En proceso" con jobs reales. Sin tarjetas KPI.
- **Create:** columna izquierda = origen (archivo/URL + validación + datos del archivo); derecha = formato de salida y preferencias; "Opciones avanzadas" plegado. Datos solo reales (`/api/validate_url`, tamaño/tipo del archivo local).
- **Editor:** biblioteca (izq.) · preview 9:16 grande con tiempo en mono (centro) · inspector contextual (der.) · línea de tiempo de un clip (abajo). El inspector cambia según el objeto seleccionado (clip / subtítulo / B-roll / SFX / audio).
- **Clips:** cuadrícula/lista, orden, filtro, búsqueda, estados vacío/carga/error; puntuación solo si el backend la da (`virality_score` existe).
- **AI Tools:** un panel por herramienta (Subtítulos, Ganchos, Copys, Miniaturas, B-roll, SFX, Dominicanizar) con contexto → configuración → generar → resultado. Sin duplicados.
- **Projects:** biblioteca por vídeo fuente; sin fecha de modificación hasta que exista en backend.
- **Processing:** lista de jobs con estados reales (en cola/ejecutando/completado/fallido/cancelado), progreso real, tiempos y cancelar. Sin logs hasta que exista endpoint.
- **Analytics:** 5 métricas reales con su explicación + estado de dependencias reales.
- **Settings:** General · Exportación · Modelos de IA · Procesamiento · Hardware, sobre `/api/config`, `/api/system/*`.

### 2.4 Contratos de componentes (JS vanilla, un solo patrón)
Cada componente = función `Name(props) → HTMLElement` creada con `createElement` (sin `innerHTML` con datos) y un archivo CSS con prefijo `cf-`.

| Componente | Props | Origen de datos |
|---|---|---|
| `ApplicationShell` | `route`, `project`, `queue` | estado global |
| `Navigation` | `items`, `active`, `collapsed` | estático |
| `WorkspaceHeader` | `title`, `actions` | — |
| `ProjectCard` | `video` | `/api/videos` |
| `VideoThumbnail` | `src`, `duration`, `ratio`, `badge` | clip/video |
| `VideoPreview` | `clip`, `timecode`, `safeZones` | `/clips/{id}/download` |
| `Timeline` | `clip`, `words`, `broll`, `sfx`, `playhead` | `/transcript`, `/broll`, `/sfx` |
| `MediaLibrary` | `videos`, `clips` | `/api/videos`, `/api/clips` |
| `ContextInspector` | `selection` | estado del editor |
| `ToolPanel` | `tool`, `ctx` | endpoint de cada herramienta |
| `ProcessingJob` | `job` | `/api/jobs` |
| `StatusIndicator` | `state` | job |
| `Modal`, `Dropdown`, `Tooltip`, `Toast`, `EmptyState`, `LoadingSkeleton`, `ErrorState`, `ConfirmationDialog` | genéricas | — |

### 2.5 Estrategia técnica propuesta (Fase 3)
1. Nuevos archivos bajo `src/web/studio/` (`tokens.css`, `shell.css`, `components.js`, `api.js`, `store.js`, `pages/*.js`), servidos como estáticos; **sin dependencias nuevas, sin build**.
2. `index.html` carga la nueva UI detrás de `?ui=studio` (y luego por defecto); la UI actual queda intacta como respaldo mientras se migra pantalla por pantalla.
3. El shell nuevo monta primero las vistas actuales dentro de su marco y se reemplazan una a una, conservando los IDs que usa el JS vigente hasta migrarlo.
4. Rollback = quitar el parámetro/`git revert` del commit; la UI anterior no se borra hasta aprobación expresa.

### 2.6 Puertas de calidad y QA (se aplican en Fase 8)
Para cada recorrido de usuario del brief se registrará PASS / FAIL / BLOCKED / NOT IMPLEMENTED con evidencia. A fecha de esta fase: **0 recorridos ejecutados** sobre el diseño nuevo.

## Decisiones que necesitan aprobación del usuario
1. Alcance: el brief equivale a rehacer una aplicación entera (varias sesiones). Propongo ir por fases con entrega verificable en cada una.
2. El **Editor multipista** no es posible sin backend nuevo; propongo la versión de "un clip" descrita arriba y dejar la edición libre como propuesta.
3. Ya existe una capa visual "Aurora" (CSS) en `index.html`; la nueva UI **no** la usará como base.
