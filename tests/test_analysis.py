from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent2_viral_detector.analysis import (
    build_windows, compile_keyword_patterns, count_keyword_hits, find_boundaries,
    normalize_text, sliding_windows, snap_to_pauses,
)
from src.agents.agent2_viral_detector.detector import ViralMomentDetector


def seg(i, a, b, text="x"):
    return TranscriptSegment(id=i, start=a, end=b, text=text)


# --- normalización de acentos -------------------------------------------------
def test_normalize_text_quita_acentos_y_mayusculas():
    assert normalize_text("Increíble") == "increible"
    assert normalize_text("AÑO NUEVO ¿Cómo?") == "ano nuevo ¿como?"


def test_keyword_con_y_sin_acento_coinciden():
    pats = compile_keyword_patterns(["increíble", "no puede ser"])
    assert count_keyword_hits(normalize_text("Esto es increible"), pats) == 1
    assert count_keyword_hits(normalize_text("Esto es INCREÍBLE, no puede ser"), pats) == 2
    assert count_keyword_hits(normalize_text("nada relevante"), pats) == 0


def test_keyword_inicio_de_palabra():
    pats = compile_keyword_patterns(["jaja", "ley"])
    assert count_keyword_hits("jajajaja que bueno", pats) == 1   # prefijo OK
    assert count_keyword_hits("los reyes", pats) == 0            # 'ley' no está al inicio de palabra


def test_heuristico_detecta_sin_acentos():
    det = ViralMomentDetector(min_duration=10, max_duration=30)
    t = TranscriptResult(video_path="v", language="es", duration=40, segments=[
        seg(0, 0, 12, "esto es increible"), seg(1, 12, 25, "de verdad increible")])
    cands = det._detect_heuristic(t)
    assert cands and cands[0].category == "reaccion" and cands[0].engine == "heuristic"
    assert cands[0].virality_score > 75


# --- ventanas de transcripción --------------------------------------------------
def test_ventanas_con_solape():
    segs = [seg(i, i * 10.0, i * 10.0 + 10.0) for i in range(120)]  # 20 min
    wins = build_windows(segs, window_sec=360, overlap_sec=30)
    assert len(wins) >= 4
    # la ventana siguiente comienza 330 s después: hay solape de 30 s
    assert wins[0][0].start == 0.0
    assert wins[1][0].start <= 330.0 and wins[1][0].start > 300.0
    last_end = max(s.end for s in wins[0])
    assert last_end - wins[1][0].start >= 30.0
    # todo segmento queda cubierto por al menos una ventana
    covered = {s.id for w in wins for s in w}
    assert covered == {s.id for s in segs}
    # ninguna ventana excede ~6 min + 1 segmento
    assert all(w[-1].end - w[0].start <= 370 for w in wins)


def test_ventana_unica_si_es_corto():
    assert len(build_windows([seg(0, 0, 100)], 360, 30)) == 1
    assert build_windows([], 360, 30) == []


def test_unir_ventanas_deduplica_por_solape(monkeypatch):
    det = ViralMomentDetector(min_duration=10, max_duration=60, max_candidates=10)
    segs = [seg(i, i * 10.0, i * 10.0 + 10.0) for i in range(80)]  # 800 s -> 3 ventanas

    from src.common.models import ViralMomentCandidate

    def fake_query(window, max_clips, id_offset=0):
        # cada ventana devuelve el mismo momento en la zona de solape (330-360)
        return [ViralMomentCandidate(
            id=f"c{id_offset}", start_time=335.0, end_time=358.0, duration=23.0, hook_text="h",
            context_text="c", virality_score=80 + id_offset, category="humor", reasoning="r", engine="llm")]

    monkeypatch.setattr(det, "_query_window", fake_query)
    t = TranscriptResult(video_path="v", language="es", duration=800, segments=segs)
    result = det._detect_with_ollama(t)
    assert len(result) == 1


# --- extracción de JSON del LLM --------------------------------------------------
def test_extrae_clip_unico_suelto_y_no_confunde_hashtags():
    det = ViralMomentDetector()
    single = '{"start_time": 5.2, "end_time": 30.0, "title": "x", "hashtags": ["#a", "#b"]}'
    out = det._extract_json_array(single)
    assert len(out) == 1 and out[0]["start_time"] == 5.2     # antes devolvía la lista de hashtags


def test_extrae_distintas_formas_de_respuesta():
    det = ViralMomentDetector()
    clip = '{"start_time": 1, "end_time": 25}'
    assert len(det._extract_json_array(f'{{"clips": [{clip}, {clip}]}}')) == 2
    assert len(det._extract_json_array(f"[{clip}]")) == 1
    assert len(det._extract_json_array(f'{{"candidates": [{clip}]}}')) == 1
    assert len(det._extract_json_array(f'{{"cualquier": [{clip}]}}')) == 1
    assert len(det._extract_json_array(f"Claro, aquí tienes:\n[{clip}]\nSuerte")) == 1
    assert det._extract_json_array("no es json") == []
    assert det._extract_json_array('{"hashtags": ["#a"]}') == []


def test_descarta_respuestas_copiadas_del_ejemplo(monkeypatch):
    import requests
    det = ViralMomentDetector(min_duration=10, max_duration=60)
    body = ('{"clips": [{"start_time": 0, "end_time": 20, "title": "El Secreto Que Nadie Te Dice 🤫", "hook_text": "x"},'
            '{"start_time": 30, "end_time": 55, "title": "Título real 🔥", "hook_text": "frase real", "virality_score": 90}]}')

    class R:
        def raise_for_status(self): pass
        def json(self): return {"response": body}

    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    out = det._query_window([seg(0, 0, 60, "hola")], max_clips=3)
    assert [c.title for c in out] == ["Título real 🔥"] and out[0].engine == "llm"


def _llm_cand(cid, start, end, score=80):
    from src.common.models import ViralMomentCandidate
    return ViralMomentCandidate(id=cid, start_time=start, end_time=end, duration=end - start, hook_text="h",
                                context_text="c", virality_score=score, category="humor", reasoning="r", engine="llm")


def test_clips_cortos_del_llm_se_amplian_al_minimo():
    det = ViralMomentDetector(min_duration=20, max_duration=60)
    t = TranscriptResult(video_path="v", language="es", duration=300, segments=[seg(0, 0, 300)])
    out = det._validate_and_adjust_boundaries([_llm_cand("a", 70.5, 71.3), _llm_cand("b", 295.0, 298.0),
                                               _llm_cand("c", 10, 200)], t)
    by = {c.id: c for c in out}
    assert by["a"].duration == 25.0 and by["a"].start_time == 70.5      # ampliado hacia delante
    assert by["b"].end_time == 300.0 and by["b"].duration >= 20          # al final del video: retrocede el inicio
    assert by["c"].duration == 60.0                                       # demasiado largo: se recorta


def test_si_el_llm_no_da_nada_valido_se_usa_el_heuristico(monkeypatch):
    det = ViralMomentDetector(min_duration=20, max_duration=60)
    t = TranscriptResult(video_path="v", language="es", duration=100, segments=[
        seg(0, 0, 30, "esto es increible"), seg(1, 30, 60, "no puede ser")])
    monkeypatch.setattr(det, "_detect_with_ollama", lambda tr: [_llm_cand("x", 500, 501)])  # fuera del video
    out = det.detect_moments(t)
    assert out and all(c.engine == "heuristic" for c in out)


# --- ventana deslizante ---------------------------------------------------------
def test_ventana_deslizante_paso_fijo_es_lineal():
    segs = [seg(i, i * 5.0, i * 5.0 + 5.0) for i in range(2000)]  # ~2.7 h
    spans = sliding_windows(segs, 20, 60, step_sec=10)
    # ~1000 inicios x <=3 duraciones: pocas ventanas, no O(n^2)
    assert 0 < len(spans) <= 3 * 1000 + 3
    for i, j in spans:
        d = segs[j].end - segs[i].start
        assert 20 <= d <= 60


# --- pausas ---------------------------------------------------------------------
def words(spec):
    return [WordTimestamp(word=w, start=a, end=b) for w, a, b in spec]


def test_find_boundaries_por_pausa_y_puntuacion():
    ws = words([("hola", 0.0, 0.4), ("mundo.", 0.5, 1.0), ("otra", 1.1, 1.5), ("frase", 2.2, 2.6)])
    starts, ends = find_boundaries(ws, min_gap=0.3)
    assert 1.1 in starts          # tras fin de oración
    assert 2.2 in starts          # tras pausa de 0.7 s
    assert 1.0 in ends and 1.5 in ends


def test_snap_a_pausa_mas_cercana():
    ws = words([("uno", 10.0, 10.5), ("dos.", 10.6, 11.0), ("tres", 11.8, 12.2), ("cuatro", 12.3, 12.9),
                ("cinco.", 13.0, 13.5), ("seis", 14.3, 14.8)])
    # inicio 11.5 (mitad del hueco) -> arranca en "tres" (11.8); fin 13.2 (dentro de 'cinco') -> 13.5
    s, e, changed = snap_to_pauses(11.5, 13.2, ws, tolerance=1.0, pad_start=0.0, pad_end=0.0)
    assert changed and s == 11.8 and e == 13.5


def test_snap_no_cambia_sin_palabras_o_fuera_de_tolerancia():
    assert snap_to_pauses(5.0, 30.0, []) == (5.0, 30.0, False)
    ws = words([("a", 0.0, 0.2), ("b", 50.0, 50.2)])
    s, e, changed = snap_to_pauses(20.0, 30.0, ws, tolerance=1.0)
    assert (s, e, changed) == (20.0, 30.0, False)


def test_snap_respeta_duracion_maxima():
    ws = words([("a", 0.0, 0.2), ("b.", 0.3, 0.5), ("c", 1.5, 1.8), ("d.", 1.9, 40.0)])
    s, e, changed = snap_to_pauses(1.4, 38.0, ws, tolerance=3.0, max_duration=30.0)
    assert (s, e, changed) == (1.4, 38.0, False)


def test_detector_alinea_candidatos_a_pausas():
    det = ViralMomentDetector(min_duration=5, max_duration=30)
    ws = words([("hola", 0.0, 0.4), ("amigos.", 0.5, 1.2), ("hoy", 2.0, 2.3), ("vamos", 2.4, 2.8),
                ("a", 2.9, 3.0), ("ver.", 3.1, 8.0), ("listo", 9.0, 9.5)])
    t = TranscriptResult(video_path="v", language="es", duration=10.0, segments=[
        TranscriptSegment(id=0, start=0, end=10, text="hola amigos hoy vamos a ver listo", words=ws)])
    from src.common.models import ViralMomentCandidate
    c = ViralMomentCandidate(id="x", start_time=1.6, end_time=7.9, duration=6.3, hook_text="h",
                             context_text="c", virality_score=90, category="humor", reasoning="r")
    out = det._align_to_pauses([c], t)[0]
    assert out.pause_aligned and out.start_time == 1.9 and out.end_time == 8.2
