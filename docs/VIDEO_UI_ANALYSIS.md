# ANÁLISIS DE INGENIERÍA INVERSA DE INTERFAZ (VIDEO DE REFERENCIA)

**Documento:** `docs/VIDEO_UI_ANALYSIS.md`  
**Referencia de Origen:** `media_1793989502529_308e336a.mp4` (10.02 s, 1280x720, 24 FPS, 240 frames).  
**Equipo:** Principal UI/UX Designer, Senior Frontend Architect, Motion Designer & QA Engineer.

---

## 1. INVENTARIO DE PANTALLAS Y VISTAS IDENTIFICADAS

A partir del muestreo cronológico del video se han detectado 4 vistas principales y 2 estados modales/superpuestos:

| Escena / Tiempo | Vista Identificada | Tipo | Descripción Visual Principal |
| :--- | :--- | :--- | :--- |
| **00:00 - 00:02** (Frames 01-04) | **Dashboard Principal ("Audiovisual" / "Inicio")** | Pantalla Completa | Tablero analítico con métricas de actividad (gráfico de líneas neón), tendencias (gráfico de barras), creación rápida con 3 tarjetas de colores, lista de proyectos recientes (carrusel de videos), acciones rápidas y generador de títulos/copys. |
| **00:02 - 00:04** (Frames 05-07) | **Modal "Crear clips" (Importación y Configuración)** | Modal Centrado / Overlay | Modal flotante con pestañas *Crear de clips* y *Render de clips*, campo de URL de YouTube con validación en verde, selector de relación de aspecto (9:16, 1:1, 16:9 con borde naranja en hover) y tarjetas de estilos de subtítulos (*Hormozi Neón*, *MrBeast Lime*, *Minimal*). |
| **00:04 - 00:06** (Frames 08-13) | **Editor de Video y Recorte Temporal ("Editor de video")** | Pantalla Completa | Interfaz de estudio con reproductor vertical 9:16 (previsualización con subtítulo *Hormozi Neón*), controles de velocidad (1x, 1.5x, 2x activo en naranja), botón de captura de fotogramas, slider de cantidad de clips, panel superior de rango y timeline multipista (Video, Rango con manejadores amarillos `[  ]`, Subtítulos, Audio) con cabezal de aguja roja. |
| **00:06 - 00:09** (Frames 14-17) | **Monitor de Rendimiento ("Motor FFmpeg")** | Pantalla Completa Dividida | Visualización técnica con 3 velocímetros circulares (CPU 45% en gradiente rosa, GPU 82% en cyan con osciloscopio de frecuencia en vivo, RAM 12.4 GB / 32 GB en coral), filmstrip de video en decodificación con telemetría en verde (`FPS: 120`, `Progreso: 88%`, `Tiempo restante: 00:12`, `Velocidad: 4.2x`), botón interactivo neón `Exportar Proyecto` y columna derecha con galería vertical 3x3 de clips generados. |
| **00:09 - 00:10** (Frames 18-20) | **Finalización de Generación ("Generación completada")** | Estado de Éxito / Feedback | Tarjeta central con insignia circular animada en verde neón con checkmark `✔ Generación completado`, toast flotante superior `✔ Generación completada con éxito (10/10 Clips)` y galería de clips lista para previsualizar y exportar. |

---

## 2. COMPONENTES IDENTIFICADOS Y ESTRUCTURA ATÓMICA

### 2.1. Marco de Ventana y Navegación Global
1. **Controles de Ventana macOS:** 3 círculos en la esquina superior izquierda (Rojo `#EF4444`, Amarillo `#F59E0B`, Verde `#10B981`) de 12 px de diámetro con separación de 8 px.
2. **Sidebar Lateral Izquierda:**
   - **Logotipo:** Icono de doble "C" neón gradiente fucsia-cyan con texto `Clip Factory` y badge `Pro v2.0` en violeta claro.
   - **Elementos de Navegación Vertical:**
     - `Inicio` (Ítem activo con pastilla translúcida violeta `#201736` y texto blanco brillante).
     - `Crear clips` (Icono video play).
     - `Mis proyectos` (Icono carpeta).
     - `Historial` (Icono reloj circular).
     - `Biblioteca` (Icono galería con play).
     - `Editor de video` (Icono tijeras de edición).
     - `Subtítulos` (Icono texto CC).
     - `Plantillas` (Icono cuadrícula 2x2).
     - `Analytics` (Icono gráfico de barras).
     - `Configuración` (Ubicado en el pie de la barra lateral con icono de engranaje).
3. **Barra Superior (Header):**
   - **Pestañas Superiores:** `Inicio` (con subrayado luminoso fucsia), `Proyectos`, `Audios v`.
   - **Buscador Rápido:** Input compacto con icono de lupa `Buscar`.
   - **Notificaciones y Perfil:** Campana con badge rojo de alertas pendientes (`1`), icono de ayuda `(?)` y avatar circular con foto de perfil.
   - **Botones de Acción Global:**
     - Botón contorneado `Compartir` con icono de play/share.
     - Botón principal de pastilla `Avanzado` con gradiente fucsia-magenta (`linear-gradient(135deg, #EC4899, #8B5CF6)`) e icono de descarga.

### 2.2. Componentes del Dashboard Principal ("Audiovisual")
1. **Fila 1 — Gráficos y Creación:**
   - **Tarjeta de Actividades:** Gráfico suave de doble línea en neón (violeta `#A855F7` y cyan `#22D3EE`) con cuadrícula de fondo oscura y menú de 3 puntos.
   - **Tarjeta de Tendencias:** Gráfico de barras neón cyan con selector desplegable de periodo y métricas de impacto (`Activos 496K`, `Éxito`, `2.6S`).
   - **Tarjeta "Crear Proyectos":** 3 botones de mosaico cuadrado con esquinas redondeadas:
     - Mosaico Violeta: `Crear proyecto` (icono destello).
     - Mosaico Cyan: `Archivos` (icono carpeta).
     - Mosaico Naranja: `Proyectar fuentes` (icono imagen).
     - Botón inferior ancho `Preparar clip contenido`.
2. **Fila 2 — Proyectos Recientes y Quick Actions:**
   - **Carrusel de Proyectos Recientes:** Tarjetas de video horizontales con miniatura, badge de duración (`0:28`, `0:58`, etc.), título `Clip de Prueba #01` y fecha.
   - **Quick Actions:** Mosaico de 3 bloques interactivos:
     - Rojo `#EF4444`: `Recorte perfecto`.
     - Azul `#3B82F6`: `Descargar / Importar`.
     - Fucsia `#EC4899`: `Filtro viral`.
3. **Fila 3 — Generación de Copys y Miniaturas:**
   - Tabla estilizada `Crear Títulos` con iconos musicales, etiquetas de red (`Diseño`, `Reels`), contador de visualizaciones y botones `Verificar`.
   - Bloque `Color Actions` con miniaturas reproducibles.
4. **Widget Flotante:** Botón circular violeta en la esquina inferior derecha con icono de chat/soporte.

### 2.3. Modal "Crear clips"
- Fondo oscuro con efecto `backdrop-filter: blur(12px)`.
- Contenedor rectangular con esquinas redondeadas (20 px) y borde sutil `rgba(255, 255, 255, 0.08)`.
- Pestañas superiores con indicador activo en rosa neón.
- Campo de entrada con foco en resplandor violeta y mensaje de validación verde `✔ URL Validada`.
- Botones de Formato (`9:16`, `1:1`, `16:9`) con realce naranja en hover/focus.
- Tarjetas de Subtítulos con demostración visual:
  - *Hormozi Neón:* Caja activa con resplandor fucsia.
  - *MrBeast Lime:* Texto verde lima neón.
  - *Minimal:* Blanco con contraste limpio.

### 2.4. Editor de Video Multipista
1. **Panel Izquierdo:**
   - Previsualizador de video en proporción 9:16.
   - Subtítulos dinámicos renderizados en tiempo real sobre el video (`Hormozi Neón con watch?`).
   - Barra de control de velocidad: pastillas `1x`, `1.5x`, `2x` (2x destacado en naranja brillante).
   - Botón `Captura de fotogramas` con icono de cámara.
   - Controles de configuración y slider de cantidad de clips (5 a 100).
   - Botón principal de acción: `✨ Generar clips con IA` con gradiente neón vibrante.
2. **Panel Central de Edición:**
   - Tarjeta superior con slider de recorte macro (`6:16` a `40:00`) y botón rosa `Obtener clip`.
   - Contador de código de tiempo en tipografía monoespaciada `00:00:10 / 00:00:00`.
   - **Timeline Multipista:**
     - **Pista 1 (Video):** Miniaturas de fotogramas continuos + forma de onda de video.
     - **Pista 2 (Clip Selector):** Rango de selección con manejadores amarillos `[   ]` desplazables y arrastrables.
     - **Pista 3 (Subtítulos):** Bloques de colores para cada segmento de subtítulo (*Hormozi Neón*, *MrBeast Lime*, *Minimal*).
     - **Pista 4 (Audio):** Forma de onda de audio en verde lima `#10B981`.
     - **Cabezal de Aguja:** Línea vertical roja `#EF4444` con marcador superior en pastilla roja.
3. **Toast de Notificación:** Pastilla verde oscura en esquina superior derecha con icono de check y texto `✔ Fotograma guardado`.

### 2.5. Monitor de Hardware y Motor FFmpeg
1. **Tríada de Velocímetros (Gauges):**
   - **CPU:** Anillo circular con gradiente rosa/fucsia y valor `45%`.
   - **GPU:** Anillo circular cyan con osciloscopio dinámico de ondas verdes y valor `82%`.
   - **RAM:** Anillo circular rojo coral con valor `12.4 GB / 32 GB` y desglose de uso.
2. **Caja Técnica "Motor FFmpeg":**
   - Filmstrip animado con fotogramas secuenciales.
   - Mensaje de estado `Procesando Video...`.
   - Cuadrícula de telemetría:
     - `FPS: 120` (en verde neón `#22C55E`).
     - `Progreso: 88%`.
     - `Tiempo restante: 00:12`.
     - `Velocidad: 4.2x`.
   - Botón inferior con contorno neón animado `Exportar Proyecto`.
3. **Galería Derecha de Clips Generados:**
   - Barra superior `100% Completado` con barra de progreso verde y selector de orden con puntos LED verdes.
   - Buscador `Filtrar` con interruptor toggle.
   - Cuadrícula de clips verticales 9:16 con badges de duración, títulos, reproductor emergente y métricas virales.

---

## 3. SISTEMA DE DISEÑO VISUAL BASADO EN LA REFERENCIA

### 3.1. Paleta de Colores Extraída
- **Lienzo / Background:** `#07080E` (Negro azulado profundo con viñeteado).
- **Superficies / Cards:** `#111420` (Gris azulado oscuro con opacidad y tinte violeta).
- **Superficies Elevadas / Hover:** `#181C2D` (Tono elevado para modales y tarjetas activas).
- **Bordes:** `rgba(255, 255, 255, 0.08)` y `rgba(168, 85, 247, 0.3)` para estados activos.
- **Acentos Neón:**
  - *Neón Fucsia / Violeta:* `#A855F7` y `#EC4899` (primario para llamadas a la acción, títulos y logos).
  - *Neón Cyan:* `#22D3EE` (secundario para gráficos, GPU y estados de conexión).
  - *Neón Verde Lima:* `#10B981` y `#B6F23A` (éxito, validación de URL, FPS y subtítulo MrBeast).
  - *Naranja Neón / Coral:* `#F97316` y `#F59E0B` (velocidad 2x, manejadores de corte `[  ]`, advertencias).
  - *Rojo Playhead:* `#EF4444` (aguja de reproducción del timeline).
- **Tipografía:**
  - *Primario (Títulos y Botones):* `#FFFFFF` (Blanco puro, sans-serif moderna `Space Grotesk` / `Sora`).
  - *Secundario (Etiquetas y Rutas):* `#94A3B8` (Gris claro neutro `Inter`).
  - *Métricas / Timecode:* `#E2E8F0` (`JetBrains Mono`).

### 3.2. Espaciados, Radios y Sombras
- **Radios de Borde (Border Radius):**
  - Botones y pastillas: `9999px` (estilo pill completo).
  - Tarjetas y paneles: `16px` a `20px`.
  - Mosaicos y sub-tarjetas: `12px`.
  - Manejadores del timeline: `6px`.
- **Sombras y Resplandores (Box Shadows):**
  - Resplandor Fucsia: `0 0 25px rgba(236, 72, 153, 0.45)`.
  - Resplandor Cyan: `0 0 25px rgba(34, 211, 238, 0.45)`.
  - Resplandor Verde: `0 0 20px rgba(16, 185, 129, 0.45)`.
  - Elevación de tarjeta: `0 10px 30px rgba(0, 0, 0, 0.5)`.

---

## 4. ANÁLISIS DE INTERACTIVIDAD Y TRANSICIONES

1. **Navegación de Vistas:**
   - La barra lateral conmuta fluidamente entre las vistas: `Inicio` (Dashboard Analítico), `Crear clips` (Modal/Formulario), `Editor de video` (Estudio Multipista) y `Monitor FFmpeg` (Telemetría de Hardware y Galería).
2. **Validación Reactiva de Enlaces:**
   - Al escribir una URL válida en el modal de creación, aparece de inmediato el badge verde `✔ URL Validada`.
3. **Timeline Scrubbing & Trimming:**
   - Los manejadores amarillos `[   ]` de la pista 2 se arrastran suavemente a 60 FPS actualizando la duración seleccionada.
   - El cabezal rojo se puede mover con click y arrastre sincronizando el fotograma del reproductor de video.
4. **Telemetría Dinámica en Tiempo Real:**
   - Los velocímetros de CPU, GPU (con osciloscopio senoidal/aleatorio reactivo) y RAM leen los datos reales del endpoint `/api/system/metrics` y actualizan sus arcos SVG con transiciones fluidas.
5. **Captura de Fotogramas (Snapshot):**
   - El botón de cámara captura el canvas actual del video y dispara el toast superior `✔ Fotograma guardado` mientras descarga el JPG localmente.
6. **Exportación de Proyecto:**
   - El botón `Exportar Proyecto` con borde gradiente animado descarga el paquete completo ZIP desde `/api/download_zip` o abre las opciones de exportación.

---

## 5. CONCLUSIÓN DEL ANÁLISIS

La interfaz mostrada en el video combina la estética de un estudio audiovisual profesional (*DaVinci Resolve / Premiere Pro*) con la usabilidad moderna de un SaaS de IA (*OpusClip / CapCut*). Toda esta arquitectura visual será replicada con máxima precisión en `src/web/index.html` asegurando que la funcionalidad real de backend, el procesamiento FFmpeg, el modelo YuNet y la suite de pruebas permanezcan 100% operativos.