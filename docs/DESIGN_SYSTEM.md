# SISTEMA DE DISEÑO — CLIP FACTORY PRO (VIDEO SPEC)

**Documento:** `docs/DESIGN_SYSTEM.md`  
**Referencia:** Fotogramas de `media_1793989502529_308e336a.mp4`  

---

## 1. DESIGN TOKENS Y PALETA DE COLORES

```css
:root {
  /* Lienzo y Superficies */
  --bg-app: #080a11;
  --bg-sidebar: #0c0e17;
  --bg-surface: #121624;
  --bg-surface-elevated: #181d2f;
  --bg-surface-hover: #1f253c;
  --bg-overlay: rgba(8, 10, 17, 0.75);

  /* Bordes y Líneas */
  --border-subtle: rgba(255, 255, 255, 0.07);
  --border-focus: rgba(168, 85, 247, 0.5);
  --border-active: #a855f7;

  /* Acentos Neón Primarios y Secundarios */
  --neon-purple: #a855f7;
  --neon-pink: #ec4899;
  --neon-cyan: #22d3ee;
  --neon-lime: #10b981;
  --neon-lime-light: #b6f23a;
  --neon-orange: #f97316;
  --neon-amber: #f59e0b;
  --neon-red: #ef4444;

  /* Gradientes */
  --grad-logo: linear-gradient(135deg, #ec4899, #a855f7 50%, #22d3ee);
  --grad-cta: linear-gradient(135deg, #ec4899, #8b5cf6);
  --grad-btn-generate: linear-gradient(135deg, #ec4899, #a855f7, #3b82f6);
  --grad-accent-purple: linear-gradient(135deg, rgba(168, 85, 247, 0.2), rgba(168, 85, 247, 0.05));
  --grad-accent-cyan: linear-gradient(135deg, rgba(34, 211, 238, 0.2), rgba(34, 211, 238, 0.05));
  --grad-active-pill: linear-gradient(90deg, #2b1f4c, #1a162b);

  /* Texto */
  --text-primary: #ffffff;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --text-dim: #475569;

  /* Tipografías */
  --font-heading: 'Sora', 'Space Grotesk', -apple-system, sans-serif;
  --font-body: 'Inter', -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Radios de Borde */
  --radius-xs: 4px;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-pill: 9999px;

  /* Sombras y Resplandores Neón */
  --glow-purple: 0 0 25px rgba(168, 85, 247, 0.4);
  --glow-pink: 0 0 25px rgba(236, 72, 153, 0.4);
  --glow-cyan: 0 0 25px rgba(34, 211, 238, 0.4);
  --glow-green: 0 0 20px rgba(16, 185, 129, 0.4);
  --glow-orange: 0 0 20px rgba(249, 115, 22, 0.4);
  --shadow-card: 0 10px 30px -5px rgba(0, 0, 0, 0.5);
}
```

---

## 2. ESPECIFICACIÓN DE COMPONENTES SEGÚN EL VIDEO

### 2.1. Ventana y Barra Lateral (Sidebar)
- **Ancho:** 220 px fijo.
- **Top:** 3 botones macOS window dots (Rojo `#EF4444`, Amarillo `#F59E0B`, Verde `#10B981`) de 11 px con separación de 7 px.
- **Logo:** Icono de doble "C" de 28x28 px con gradiente `#EC4899` a `#22D3EE` + texto `Clip Factory` (15 px, font-weight 700) + insignia `Pro v2.0` (10 px, color `#A855F7`).
- **Navegación:**
  - `Inicio` (activo por defecto con fondo `#231c38` y borde sutil violeta).
  - `Crear clips`
  - `Mis proyectos`
  - `Historial`
  - `Biblioteca`
  - `Editor de video`
  - `Subtítulos`
  - `Plantillas`
  - `Analytics`
  - `Configuración` (al pie con `margin-top: auto`).

### 2.2. Cabecera (Header)
- **Altura:** 56 px.
- **Pestañas:** `Inicio` (con indicador inferior magenta neón), `Proyectos`, `Audios v`.
- **Buscador:** Input con icono `Buscar`.
- **Iconos:** Campana con punto rojo `1`, Ayuda `?`, Avatar con foto.
- **Botones de Acción:**
  - `Compartir` (botón contorneado).
  - `Avanzado` (botón de pastilla con gradiente `#EC4899` a `#8B5CF6`).

### 2.3. Vistas y Modales
1. **Vista Inicio / Audiovisual:**
   - Título `Audiovisual` + barra de filtros y acciones.
   - Gráfico de actividad (líneas violeta y cyan con puntos).
   - Gráfico de tendencias (barras verticales cyan).
   - Tarjetas de creación (Mosaicos Violeta, Cyan, Naranja).
   - Proyectos recientes (carrusel de 4 clips).
   - Quick Actions (3 tarjetas de colores).
   - Títulos y copys (tabla con botones `Verificar`).
   - Miniaturas destacadas (2 videos con play).
   - Widget de chat flotante en esquina inferior derecha.

2. **Modal "Crear clips":**
   - Backdrop blur.
   - Pestañas `Crear de clips` | `Render de clips`.
   - Input con validación en vivo `✔ URL Validada`.
   - Selector de aspecto `9:16`, `1:1`, `16:9` (hover naranja neón).
   - Tarjetas de subtítulos: `Hormozi Neón`, `MrBeast Lime`, `Minimal`.

3. **Vista "Editor de video":**
   - Reproductor 9:16 con subtítulo `Hormozi Neón con watch?`.
   - Velocidades `1x`, `1.5x`, `2x` (2x en naranja).
   - Botón `Captura de fotogramas` (dispara toast `✔ Fotograma guardado`).
   - Slider de cantidad de clips (5 a 100).
   - Botón principal `✨ Generar clips con IA`.
   - Timeline con 4 pistas (Video, Rango `[   ]`, Subtítulos, Audio) y cabezal rojo.

4. **Vista Procesamiento & Telemetría ("Motor FFmpeg"):**
   - 3 velocímetros circulares (CPU 45%, GPU 82% con osciloscopio, RAM 12.4 GB / 32 GB).
   - Filmstrip con fotogramas en proceso, `FPS: 120`, `Progreso: 88%`, `Tiempo restante: 00:12`, `Velocidad: 4.2x`.
   - Botón neón `Exportar Proyecto`.
   - Columna derecha con `100% Completado`, filtros con LED verdes y galería 3x3 de clips generados.
   - Insignia de éxito animada `✔ Generación completado`.