import pytest
from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.common.models import ViralMomentCandidate, ViralityBreakdown


def _make_candidate(cand_id: str, score: float, hook: float = 90.0, flow: float = 90.0, trend: float = 90.0):
    return ViralMomentCandidate(
        id=cand_id,
        start_time=0.0,
        end_time=20.0,
        duration=20.0,
        title=f"Clip {cand_id}",
        hook_text="Gancho",
        context_text="Contexto",
        virality_score=score,
        breakdown=ViralityBreakdown(
            hook_score=hook,
            flow_score=flow,
            trend_score=trend,
        ),
        category="humor",
        reasoning="Test",
    )


def test_saturated_scores_are_spread():
    # 5 clips apiñados entre 98.5 y 100
    raw_scores = [100.0, 99.8, 99.4, 99.0, 98.5]
    cands = [_make_candidate(f"c_{i}", s) for i, s in enumerate(raw_scores)]

    norm_cands = ViralMomentDetector.normalize_virality_scores(cands, target_min=66.0, target_max=97.0)
    norm_scores = [c.virality_score for c in norm_cands]

    # El mejor clip debe estar en 97.0
    assert norm_scores[0] == 97.0
    # El peor debe estar en 66.0
    assert norm_scores[-1] == 66.0
    # La diferencia entre el primero y el último debe ser amplia (>= 30 puntos)
    assert (norm_scores[0] - norm_scores[-1]) >= 30.0
    # Los valores intermedios deben tener separación visible
    for i in range(len(norm_scores) - 1):
        assert norm_scores[i] > norm_scores[i + 1]


def test_strict_order_preservation():
    # Clips con variaciones aleatorias ordenadas
    raw_scores = [98.2, 95.0, 91.4, 88.0, 82.5, 75.0]
    cands = [_make_candidate(f"c_{i}", s) for i, s in enumerate(raw_scores)]

    norm_cands = ViralMomentDetector.normalize_virality_scores(cands)
    norm_scores = [c.virality_score for c in norm_cands]

    # Orden descendente estricto
    for i in range(len(norm_scores) - 1):
        assert norm_scores[i] >= norm_scores[i + 1]
    # Rango en [0, 100]
    for s in norm_scores:
        assert 0.0 <= s <= 100.0


def test_equal_scores_graceful_tiering():
    # Todos con 99.0 exacto
    cands = [_make_candidate(f"c_{i}", 99.0) for i in range(4)]
    norm_cands = ViralMomentDetector.normalize_virality_scores(cands, target_min=70.0, target_max=95.0)
    norm_scores = [c.virality_score for c in norm_cands]

    assert len(norm_scores) == 4
    # No hay NaN ni división por cero
    assert all(isinstance(s, float) and not (s != s) for s in norm_scores)
    # Se escalonan suavemente
    assert norm_scores[0] >= norm_scores[-1]
    assert 70.0 <= norm_scores[-1] <= norm_scores[0] <= 95.0


def test_single_candidate_normalization():
    cand = _make_candidate("c_single", 99.5)
    norm = ViralMomentDetector.normalize_virality_scores([cand])
    assert len(norm) == 1
    assert 75.0 <= norm[0].virality_score <= 97.0


def test_breakdown_scores_rescaled_proportionally():
    cand = _make_candidate("c_0", 100.0, hook=90.0, flow=80.0, trend=70.0)
    cands = [cand, _make_candidate("c_1", 80.0, hook=70.0, flow=60.0, trend=50.0)]

    norm = ViralMomentDetector.normalize_virality_scores(cands)
    c0 = norm[0]
    # Si virality_score bajó de 100 a 97, los subpuntajes deben haber bajado con el mismo ratio
    assert c0.breakdown.hook_score == round(90.0 * (97.0 / 100.0), 1)
    assert c0.breakdown.flow_score == round(80.0 * (97.0 / 100.0), 1)
    assert c0.breakdown.trend_score == round(70.0 * (97.0 / 100.0), 1)
