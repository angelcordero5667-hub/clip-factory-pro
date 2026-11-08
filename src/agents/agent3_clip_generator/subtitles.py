"""Generador de subtítulos ASS con 4 estilos y tipografía empaquetada en static/fonts.

Estilos
- hormozi: palabra activa resaltada en amarillo y ligeramente más grande (Montserrat ExtraBold).
- limpio:  texto blanco con contorno y sombra suave (Poppins SemiBold).
- karaoke: relleno progresivo de color palabra por palabra con \\kf (Anton).
- minimal: texto pequeño, sin resaltado, para dejar respirar la imagen (Poppins SemiBold).

Reglas comunes: contorno de 4 a 6 px, sombra suave, máximo 2 líneas y 4 palabras por línea,
y posición segura (fuera de la interfaz de TikTok / Reels / Shorts).
"""
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.common.config import settings
from src.common.models import WordTimestamp, TranscriptSegment

logger = logging.getLogger("Agent3_Subtitles")

FONTS_DIR = settings.base_dir / "static" / "fonts"

# Mapeo semántico de palabras clave a emojis (solo se usa si el estilo y la fuente lo permiten)
EMOJI_KEYWORDS: Dict[str, str] = {
    "dinero": "💰", "plata": "💸", "dolar": "💵", "dolares": "💵", "millon": "💎",
    "millones": "💎", "rico": "🤑", "negocio": "💼", "empresa": "🏢", "precio": "🏷️",
    "fuego": "🔥", "brutal": "⚡", "locura": "🤯", "increible": "😱", "shock": "💥",
    "verdad": "💯", "secreto": "🤫", "atencion": "👀", "alerta": "🚨", "cuidado": "⚠️",
    "exito": "🏆", "ganar": "🥇", "crecer": "📈", "futuro": "🚀", "objetivo": "🎯",
    "mente": "🧠", "cerebro": "🧠", "idea": "💡", "aprender": "📚", "pregunta": "❓",
    "tiempo": "⏳", "hora": "⏱️", "rapido": "⚡", "año": "📅",
}
# Cualquier emoji / pictograma (para eliminarlos del texto cuando no se pueden dibujar)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️‍]+")
EMOJI_FONT_GLOB = "NotoEmoji*.ttf"   # fuente MONOCROMA: libass no dibuja emojis a color

# Fuente -> archivo en static/fonts. Si el archivo falta se usa Arial en negrita (sin error).
FONT_FILES = {
    "Montserrat ExtraBold": "Montserrat-ExtraBold.ttf",
    "Anton": "Anton-Regular.ttf",
    "Poppins SemiBold": "Poppins-SemiBold.ttf",
}

# Zona segura 9:16 (1080x1920): la interfaz de TikTok/Reels ocupa ~25 % inferior (descripción,
# botones), ~10 % superior y ~14 % del lado derecho. Los márgenes son simétricos para centrar el texto.
SAFE_V9x16 = {"bottom": 480, "middle": 0, "top": 250}
SAFE_H9x16 = 140


class SubtitleStyle(dict):
    pass


STYLES: Dict[str, Dict] = {
    "hormozi": dict(font="Montserrat ExtraBold", size=72, outline=6, shadow=3, bold=0, uppercase=True,
                    mode="highlight", primary="&H00FFFFFF", highlight="&H0000F0FF", allow_emoji=True),
    "hormozi_classic": dict(font="Montserrat ExtraBold", size=74, outline=6, shadow=3, bold=0, uppercase=True,
                            mode="plain", primary="&H0000F0FF", highlight="&H0000F0FF", allow_emoji=True),
    "hormozi_neon": dict(font="Montserrat ExtraBold", size=72, outline=6, shadow=4, bold=0, uppercase=True,
                         mode="highlight", primary="&H00FFFFFF", highlight="&H0000F0FF", allow_emoji=True),
    "beast": dict(font="Anton", size=78, outline=6, shadow=4, bold=0, uppercase=True,
                  mode="highlight", primary="&H00FFFFFF", highlight="&H003AF2B6", allow_emoji=True),
    "limpio": dict(font="Poppins SemiBold", size=64, outline=5, shadow=4, bold=0, uppercase=False,
                   mode="plain", primary="&H00FFFFFF", highlight="&H00FFFFFF", allow_emoji=False),
    "minimal": dict(font="Poppins SemiBold", size=52, outline=4, shadow=2, bold=0, uppercase=False,
                    mode="plain", primary="&H00FFFFFF", highlight="&H00FFFFFF", allow_emoji=False),
    "karaoke": dict(font="Anton", size=82, outline=6, shadow=3, bold=0, uppercase=True,
                    mode="karaoke", primary="&H0000F0FF", highlight="&H0000F0FF", allow_emoji=True),
    "gaming": dict(font="Anton", size=80, outline=6, shadow=4, bold=0, uppercase=True,
                   mode="karaoke", primary="&H00EED322", highlight="&H00EED322", allow_emoji=True),
    "podcast": dict(font="Poppins SemiBold", size=62, outline=5, shadow=3, bold=0, uppercase=False,
                    mode="highlight", primary="&H00FFFFFF", highlight="&H00F755A8", allow_emoji=False),
    "bounce": dict(font="Anton", size=80, outline=6, shadow=4, bold=0, uppercase=True,
                   mode="bounce", primary="&H00FFFFFF", highlight="&H003AF2B6", allow_emoji=True),
    "glow": dict(font="Montserrat ExtraBold", size=72, outline=6, shadow=5, bold=0, uppercase=True,
                 mode="highlight", primary="&H00FFFFFF", highlight="&H00F755A8", allow_emoji=True),
}
# Nombres alternativos -> estilos actuales
STYLE_ALIASES = {
    "mrbeast": "hormozi",
    "cyber": "karaoke",
    "clean": "limpio",
    "classic": "hormozi_classic",
    "neon": "hormozi_neon",
    "minimal_white": "minimal",
    "pop": "bounce",
    "bouncing": "bounce",
}
# Compatibilidad con código que lea SubtitleGenerator.ASS_STYLES
ASS_STYLES = STYLES

MAX_LINES = 2
MAX_WORDS_PER_LINE = 4
TARGET_BLOCK_WORDS = 7       # 4 + 3 palabras en 2 líneas
PAUSE_BREAK = 0.6            # una pausa mayor corta el bloque


def emoji_font_available() -> bool:
    return any(FONTS_DIR.glob(EMOJI_FONT_GLOB))


def resolve_font(name: str) -> Tuple[str, int]:
    """Devuelve (nombre_de_fuente, bold_flag). Si falta el archivo: Arial negrita."""
    filename = FONT_FILES.get(name)
    if filename and (FONTS_DIR / filename).exists():
        return name, 0
    if filename:
        logger.debug(f"Fuente {filename} no encontrada en {FONTS_DIR}; se usa Arial.")
    return "Arial", -1


def group_words(
    words: List[WordTimestamp],
    target: int = TARGET_BLOCK_WORDS,
    pause_break: float = PAUSE_BREAK,
) -> List[List[WordTimestamp]]:
    """Agrupa palabras en bloques de hasta `target` palabras (<= 2 líneas de <= 4).

    Corta antes si hay fin de oración o una pausa larga; nunca supera MAX_LINES*MAX_WORDS_PER_LINE.
    """
    limit = min(target, MAX_LINES * MAX_WORDS_PER_LINE)
    blocks: List[List[WordTimestamp]] = []
    cur: List[WordTimestamp] = []
    for w in words:
        if cur and (w.start - cur[-1].end) >= pause_break:
            blocks.append(cur)
            cur = []
        cur.append(w)
        ends_sentence = w.word.rstrip().endswith((".", "?", "!", "…")) and len(cur) >= 3
        if len(cur) >= limit or ends_sentence:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def split_lines(n_words: int) -> List[int]:
    """Reparte n palabras en 1 o 2 líneas equilibradas (máx. 4 por línea)."""
    if n_words <= MAX_WORDS_PER_LINE:
        return [n_words]
    first = (n_words + 1) // 2
    return [first, n_words - first]


# Ancho medio de un carácter en MAYÚSCULAS como fracción del tamaño de fuente (aproximado)
CHAR_WIDTH = {"Montserrat ExtraBold": 0.72, "Anton": 0.48, "Poppins SemiBold": 0.64, "Arial": 0.68}


def fit_font_size(lines_text: List[str], font: str, size: int, available_px: int) -> int:
    """Reduce el tamaño de fuente (hasta 60 %) si la línea más larga no cabe en el ancho seguro."""
    longest = max((len(t) for t in lines_text), default=0)
    if longest == 0:
        return size
    needed = longest * size * CHAR_WIDTH.get(font, 0.66)
    if needed <= available_px:
        return size
    return max(int(size * 0.6), int(size * available_px / needed))


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


class SubtitleGenerator:
    ASS_STYLES = STYLES

    # ----------------------------------------------------------------- utilidades
    def resolve_style(self, name: str) -> Tuple[str, Dict]:
        name = STYLE_ALIASES.get(name, name)
        if name not in STYLES:
            name = "hormozi"
        return name, STYLES[name]

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0.0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs >= 100:
            cs = 99
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _enrich_with_emoji(self, word: str) -> str:
        clean = re.sub(r"[^\w]", "", word.lower())
        for key, emoji in EMOJI_KEYWORDS.items():
            if key in clean:
                return f"{word} {emoji}"
        return word

    @staticmethod
    def play_res(aspect_ratio: str = "9:16") -> Tuple[int, int]:
        return {"1:1": (1080, 1080), "16:9": (1920, 1080)}.get(aspect_ratio, (1080, 1920))

    def _margins(self, position: str, res: Tuple[int, int]) -> Tuple[int, int, int]:
        """(alineación, marginV, marginLR) en la zona segura según el formato."""
        w, h = res
        pos = (position or "bottom").lower()
        align = {"top": 8, "middle": 5}.get(pos, 2)
        if h > w:   # vertical 9:16
            return align, SAFE_V9x16.get(pos, SAFE_V9x16["bottom"]), SAFE_H9x16
        if w > h:   # horizontal 16:9: la interfaz es menor; margen inferior moderado
            return align, {"bottom": 110, "middle": 0, "top": 90}.get(pos, 110), 220
        return align, {"bottom": 150, "middle": 0, "top": 110}.get(pos, 150), 110   # cuadrado

    def _get_header(self, style_name: str, position: str, res: Tuple[int, int],
                    custom_fontsize: Optional[int] = None, custom_highlight: Optional[str] = None) -> str:
        _, s = self.resolve_style(style_name)
        font, bold = resolve_font(s["font"])
        size = custom_fontsize or s["size"]
        if s["mode"] == "karaoke":
            # \kf rellena de SecondaryColour (aún no cantado) a PrimaryColour (ya cantado)
            primary, secondary = (custom_highlight or s["highlight"]), "&H00FFFFFF"
        else:
            primary = secondary = s["primary"]
        align, margin_v, margin_lr = self._margins(position, res)
        w, h = res
        return f"""[Script Info]
Title: Clip Factory Subtitles
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{primary},{secondary},&H00000000,&H96000000,{bold},0,0,0,100,100,0,0,1,{s['outline']},{s['shadow']},{align},{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # ----------------------------------------------------------------- palabras del clip
    @staticmethod
    def _clip_words(segments: List[TranscriptSegment], clip_start: float, clip_end: float) -> List[WordTimestamp]:
        words: List[WordTimestamp] = []
        for seg in segments:
            if seg.end < clip_start or seg.start > clip_end:
                continue
            if seg.words:
                words.extend(w for w in seg.words if w.end >= clip_start and w.start <= clip_end)
            else:
                # Sin timestamps por palabra: reparte el segmento de forma uniforme
                tokens = seg.text.split()
                if not tokens:
                    continue
                step = (seg.end - seg.start) / len(tokens)
                for i, tok in enumerate(tokens):
                    ws, we = seg.start + i * step, seg.start + (i + 1) * step
                    if we >= clip_start and ws <= clip_end:
                        words.append(WordTimestamp(word=tok, start=ws, end=we))
        words.sort(key=lambda w: w.start)
        return words

    # ----------------------------------------------------------------- generación
    def generate_ass(
        self,
        clip_start: float,
        clip_end: float,
        segments: List[TranscriptSegment],
        output_path: Path,
        style_preset: str = "hormozi",
        include_emojis: bool = True,
        position: str = "bottom",
        custom_fontsize: Optional[int] = None,
        custom_highlight: Optional[str] = None,
        uppercase: Optional[bool] = None,
        add_watermark: bool = False,
        watermark_text: Optional[str] = None,
        aspect_ratio: str = "9:16",
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        style_name, s = self.resolve_style(style_preset)
        res = self.play_res(aspect_ratio)
        upper = s["uppercase"] if uppercase is None else uppercase
        hl = custom_highlight or s["highlight"]
        # Emojis: solo si el estilo lo permite Y hay una fuente que libass pueda dibujar. Si no, se omiten.
        use_emoji = bool(include_emojis and s["allow_emoji"] and emoji_font_available())
        total = max(0.0, clip_end - clip_start)
        font_name, _ = resolve_font(s["font"])
        base_size = custom_fontsize or s["size"]
        _, _, margin_lr = self._margins(position, res)

        events: List[str] = []
        if add_watermark or watermark_text:
            wm = _ass_escape((watermark_text or "Clip Factory").strip())
            events.append(
                f"Dialogue: 1,0:00:00.00,{self._format_time(total)},Default,,0,0,0,,"
                f"{{\\an9\\pos({res[0] - 60},70)\\fs30\\c&H00FFFFFF&\\3c&H80000000&\\bord3}}{wm}")

        def render_word(w: WordTimestamp) -> str:
            text = _ass_escape(w.word.strip())
            if not use_emoji:
                text = _EMOJI_RE.sub("", text).strip()
            if upper:
                text = text.upper()
            if use_emoji:
                text = self._enrich_with_emoji(text)
            return text

        words = [w for w in self._clip_words(segments, clip_start, clip_end) if render_word(w)]
        for block in group_words(words):
            lines = split_lines(len(block))
            # índice de palabra en el bloque -> ¿salto de línea antes de ella?
            breaks = {lines[0]} if len(lines) == 2 else set()
            b_start = max(0.0, block[0].start - clip_start)
            b_end = min(total, block[-1].end - clip_start)
            if b_end <= b_start:
                continue

            # Si la línea más larga no cabe en el ancho seguro, se reduce la fuente solo en este bloque
            rendered = [render_word(w) for w in block]
            cut = [0] + sorted(breaks) + [len(block)]
            line_texts = [" ".join(rendered[cut[k]:cut[k + 1]]) for k in range(len(cut) - 1)]
            fs = fit_font_size(line_texts, font_name, base_size, res[0] - 2 * margin_lr)
            fs_tag = f"{{\\fs{fs}}}" if fs < base_size else ""

            if s["mode"] == "plain":
                text = "".join(("\\N" if i in breaks else (" " if i else "")) + render_word(w) for i, w in enumerate(block))
                events.append(f"Dialogue: 0,{self._format_time(b_start)},{self._format_time(b_end)},Default,,0,0,0,,{fs_tag}{text}")

            elif s["mode"] == "karaoke":
                parts = []
                for i, w in enumerate(block):
                    nxt = block[i + 1].start if i + 1 < len(block) else w.end
                    cs = max(1, int(round((max(nxt, w.end) - w.start) * 100)))
                    sep = "\\N" if i in breaks else (" " if i else "")
                    parts.append(f"{sep}{{\\kf{cs}}}{render_word(w)}")
                events.append(f"Dialogue: 0,{self._format_time(b_start)},{self._format_time(b_end)},Default,,0,0,0,,{fs_tag}{''.join(parts)}")

            elif s["mode"] == "bounce":
                for a, active in enumerate(block):
                    w_start = max(0.0, active.start - clip_start)
                    w_end = min(total, (block[a + 1].start if a + 1 < len(block) else active.end) - clip_start)
                    if w_end <= w_start:
                        continue
                    parts = []
                    for i, w in enumerate(block):
                        sep = "\\N" if i in breaks else (" " if i else "")
                        if i == a:
                            parts.append(f"{sep}{{\\c{hl}\\t(0,70,\\fscx125\\fscy125)\\t(70,140,\\fscx112\\fscy112)}}{render_word(w)}{{\\c{s['primary']}\\fscx100\\fscy100}}")
                        else:
                            parts.append(f"{sep}{render_word(w)}")
                    events.append(f"Dialogue: 0,{self._format_time(w_start)},{self._format_time(w_end)},Default,,0,0,0,,{fs_tag}{''.join(parts)}")

            else:  # highlight (hormozi): un evento por palabra activa con todo el bloque visible
                for a, active in enumerate(block):
                    w_start = max(0.0, active.start - clip_start)
                    w_end = min(total, (block[a + 1].start if a + 1 < len(block) else active.end) - clip_start)
                    if w_end <= w_start:
                        continue
                    parts = []
                    for i, w in enumerate(block):
                        sep = "\\N" if i in breaks else (" " if i else "")
                        if i == a:
                            parts.append(f"{sep}{{\\c{hl}\\fscx112\\fscy112}}{render_word(w)}{{\\c{s['primary']}\\fscx100\\fscy100}}")
                        else:
                            parts.append(f"{sep}{render_word(w)}")
                    events.append(f"Dialogue: 0,{self._format_time(w_start)},{self._format_time(w_end)},Default,,0,0,0,,{fs_tag}{''.join(parts)}")

        ass = self._get_header(style_name, position, res, custom_fontsize, custom_highlight) + "\n".join(events) + "\n"
        output_path.write_text(ass, encoding="utf-8")
        return output_path
