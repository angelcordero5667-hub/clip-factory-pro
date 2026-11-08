import re

import pytest

from src.common.models import TranscriptSegment, WordTimestamp
from src.agents.agent3_clip_generator import subtitles as sub
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker
from src.agents.agent3_clip_generator.subtitles import (
    MAX_WORDS_PER_LINE, SubtitleGenerator, fit_font_size, group_words, split_lines,
)

TEXT = "Nadie te cuenta el secreto del dinero increíble que cambia tu vida hoy mismo".split()


def segs(words=TEXT, step=0.3):
    ws = [WordTimestamp(word=w, start=1.0 + i * step, end=1.0 + i * step + step - 0.02) for i, w in enumerate(words)]
    return [TranscriptSegment(id=0, start=1.0, end=ws[-1].end, text=" ".join(words), words=ws)]


def dialogues(path):
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:") and "\\an9" not in l]


def visible_text(line):
    text = line.split(",,", 1)[1] if ",,0,0,0,," not in line else line.split(",,0,0,0,,", 1)[1]
    return re.sub(r"\{[^}]*\}", "", text)


@pytest.mark.parametrize("style", ["hormozi", "limpio", "karaoke", "minimal"])
def test_cuatro_estilos_generan_ass_valido(tmp_path, style):
    out = SubtitleGenerator().generate_ass(1.0, 6.0, segs(), tmp_path / f"{style}.ass", style_preset=style)
    content = out.read_text(encoding="utf-8")
    assert "[Script Info]" in content and "[Events]" in content and dialogues(out)


@pytest.mark.parametrize("style", ["hormozi", "limpio", "karaoke", "minimal"])
def test_maximo_2_lineas_y_4_palabras_por_linea(tmp_path, style):
    out = SubtitleGenerator().generate_ass(1.0, 6.0, segs(), tmp_path / "s.ass", style_preset=style)
    for line in dialogues(out):
        lines = visible_text(line).split("\\N")
        assert 1 <= len(lines) <= 2
        assert all(1 <= len(l.split()) <= MAX_WORDS_PER_LINE for l in lines), lines


def test_contorno_entre_4_y_6_px(tmp_path):
    for name, cfg in sub.STYLES.items():
        assert 4 <= cfg["outline"] <= 6, name
        assert cfg["shadow"] > 0, name


def test_hormozi_resalta_palabra_activa_en_amarillo(tmp_path):
    out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(), tmp_path / "h.ass", style_preset="hormozi")
    first = dialogues(out)[0]
    assert "&H0000F0FF" in first and first.count("\\fscx112") == 1   # una sola palabra resaltada
    assert "NADIE" in visible_text(first)


def test_karaoke_usa_relleno_progresivo(tmp_path):
    out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(), tmp_path / "k.ass", style_preset="karaoke")
    assert "\\kf" in dialogues(out)[0]


def test_limpio_y_minimal_no_resaltan(tmp_path):
    for style in ("limpio", "minimal"):
        out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(), tmp_path / f"{style}.ass", style_preset=style)
        assert "\\kf" not in out.read_text(encoding="utf-8") and "\\fscx112" not in out.read_text(encoding="utf-8")


def test_minimal_conserva_minusculas_y_hormozi_mayusculas(tmp_path):
    g = SubtitleGenerator()
    low = visible_text(dialogues(g.generate_ass(1.0, 4.0, segs(), tmp_path / "m.ass", style_preset="minimal"))[0])
    up = visible_text(dialogues(g.generate_ass(1.0, 4.0, segs(), tmp_path / "h.ass", style_preset="hormozi"))[0])
    assert "nadie" in low.lower() and low != low.upper()
    assert up == up.upper()


def test_posicion_segura_vertical(tmp_path):
    out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(), tmp_path / "p.ass", style_preset="hormozi", aspect_ratio="9:16")
    style = [l for l in out.read_text(encoding="utf-8").splitlines() if l.startswith("Style:")][0].split(",")
    margin_v = int(style[-2])
    assert margin_v >= 0.22 * 1920            # fuera del ~25 % inferior de la interfaz de TikTok/Reels
    assert "PlayResY: 1920" in out.read_text(encoding="utf-8")


def test_playres_sigue_el_formato(tmp_path):
    for ar, (w, h) in {"1:1": (1080, 1080), "16:9": (1920, 1080)}.items():
        out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(), tmp_path / f"{w}.ass", aspect_ratio=ar)
        txt = out.read_text(encoding="utf-8")
        assert f"PlayResX: {w}" in txt and f"PlayResY: {h}" in txt


def test_agrupacion_corta_en_pausas_y_limita_tamano():
    ws = [WordTimestamp(word=f"p{i}", start=i * 0.3, end=i * 0.3 + 0.25) for i in range(9)]
    ws += [WordTimestamp(word="tras", start=10.0, end=10.3), WordTimestamp(word="pausa", start=10.4, end=10.7)]
    blocks = group_words(ws)
    assert all(len(b) <= 2 * MAX_WORDS_PER_LINE for b in blocks)
    assert [w.word for w in blocks[-1]] == ["tras", "pausa"]       # la pausa de 9 s abre bloque nuevo


def test_split_lines():
    assert split_lines(3) == [3] and split_lines(4) == [4]
    assert split_lines(5) == [3, 2] and split_lines(7) == [4, 3] and split_lines(8) == [4, 4]


def test_fuente_se_reduce_si_no_cabe():
    assert fit_font_size(["HOLA"], "Anton", 72, 800) == 72
    reduced = fit_font_size(["PALABRASMUYLARGAS" * 3], "Montserrat ExtraBold", 72, 800)
    assert 43 <= reduced < 72


def test_emojis_omitidos_sin_error_si_no_hay_fuente(tmp_path, monkeypatch):
    monkeypatch.setattr(sub, "emoji_font_available", lambda: False)
    out = SubtitleGenerator().generate_ass(1.0, 6.0, segs(["el", "dinero", "es", "increible"]), tmp_path / "e.ass",
                                           style_preset="hormozi", include_emojis=True)
    assert not re.search("[\U0001F300-\U0001FAFF]", out.read_text(encoding="utf-8"))


def test_emojis_incluidos_solo_si_estilo_y_fuente_lo_permiten(tmp_path, monkeypatch):
    monkeypatch.setattr(sub, "emoji_font_available", lambda: True)
    g = SubtitleGenerator()
    words = ["el", "dinero", "es", "increible"]
    con = g.generate_ass(1.0, 6.0, segs(words), tmp_path / "a.ass", style_preset="hormozi", include_emojis=True)
    assert re.search("[\U0001F300-\U0001FAFF]", con.read_text(encoding="utf-8"))
    # "limpio" no permite emojis aunque haya fuente
    sin = g.generate_ass(1.0, 6.0, segs(words), tmp_path / "b.ass", style_preset="limpio", include_emojis=True)
    assert not re.search("[\U0001F300-\U0001FAFF]", sin.read_text(encoding="utf-8"))


def test_emojis_del_texto_se_eliminan_si_no_se_pueden_dibujar(tmp_path, monkeypatch):
    monkeypatch.setattr(sub, "emoji_font_available", lambda: False)
    out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(["hola", "🔥", "mundo"]), tmp_path / "x.ass")
    assert "🔥" not in out.read_text(encoding="utf-8")


def test_fuente_ausente_cae_a_arial(tmp_path, monkeypatch):
    monkeypatch.setattr(sub, "FONTS_DIR", tmp_path / "vacia")
    assert sub.resolve_font("Montserrat ExtraBold") == ("Arial", -1)
    out = SubtitleGenerator().generate_ass(1.0, 4.0, segs(), tmp_path / "f.ass")
    assert "Style: Default,Arial," in out.read_text(encoding="utf-8")


def test_fuente_presente_se_usa(tmp_path, monkeypatch):
    (tmp_path / "Anton-Regular.ttf").write_bytes(b"x")
    monkeypatch.setattr(sub, "FONTS_DIR", tmp_path)
    assert sub.resolve_font("Anton") == ("Anton", 0)


def test_estilo_desconocido_y_alias(tmp_path):
    g = SubtitleGenerator()
    assert g.resolve_style("mrbeast")[0] == "hormozi" and g.resolve_style("cyber")[0] == "karaoke"
    assert g.resolve_style("inventado")[0] == "hormozi"


def test_filtro_incluye_fontsdir(tmp_path):
    ass = tmp_path / "a.ass"
    ass.write_text("x", encoding="utf-8")
    f, _ = VerticalClipMaker().build_filter_complex(1080, 1920, ass)
    assert "subtitles='" in f and ":fontsdir='" in f and "static/fonts" in f
    assert "C\\:/" in f     # los dos puntos de la unidad de Windows van escapados


def test_segmentos_sin_palabras_se_reparten(tmp_path):
    seg = [TranscriptSegment(id=0, start=0.0, end=4.0, text="una frase sin timestamps por palabra")]
    out = SubtitleGenerator().generate_ass(0.0, 4.0, seg, tmp_path / "n.ass", style_preset="limpio")
    assert dialogues(out)


def test_subtitle_position_bottom_low_and_numeric():
    g = SubtitleGenerator()
    align_low, margin_v_low, _ = g._margins("bottom_low", (1080, 1920))
    assert align_low == 2
    assert margin_v_low == 280

    align_num, margin_v_num, _ = g._margins("320", (1080, 1920))
    assert align_num == 2
    assert margin_v_num == 320


def test_subtitle_size_presets_in_generate_ass(tmp_path):
    g = SubtitleGenerator()
    seg = [TranscriptSegment(id=0, start=0.0, end=4.0, text="probando tamano pequeno")]
    out_small = g.generate_ass(0.0, 4.0, seg, tmp_path / "small.ass", style_preset="hormozi", subtitle_size="small")
    content_small = out_small.read_text(encoding="utf-8")
    assert "Style: Default" in content_small
    assert ",51," in content_small

    out_large = g.generate_ass(0.0, 4.0, seg, tmp_path / "large.ass", style_preset="hormozi", subtitle_size="large")
    content_large = out_large.read_text(encoding="utf-8")
    assert ",90," in content_large

