from __future__ import annotations

import itertools
import logging

import numpy as np
from scipy.stats import norm

from backend.analyzer import AnalysisResult

logger = logging.getLogger(__name__)

FREQ_W = 0.35
RECENCY_W = 0.25
DUE_W = 0.25
HOT_W = 0.15

SUM_MIN = 160
SUM_MAX = 230
EVEN_MIN = 5
EVEN_MAX = 10
MAX_CONSEC = 5
MAX_DECADE = 7
N_CANDIDATES = 15000
N_BETS = 20
MAX_OVERLAP = 12


def _normalize(d: dict[int, float]) -> dict[int, float]:
    vals = list(d.values())
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return {k: 0.5 for k in d}
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}


def _build_weights(analysis: AnalysisResult) -> np.ndarray:
    freq_norm = _normalize({n: analysis.frequency.get(n, 0) for n in range(1, 26)})
    recency_raw = {n: 1.0 / (analysis.recency.get(n, 1) + 1) for n in range(1, 26)}
    recency_norm = _normalize(recency_raw)
    due_bonus = {n: 0.3 if n in analysis.due_numbers else 0.0 for n in range(1, 26)}
    hot_bonus = {n: 0.2 if n in analysis.hot_numbers else 0.0 for n in range(1, 26)}

    weights = np.array([
        FREQ_W * freq_norm[n] +
        RECENCY_W * recency_norm[n] +
        DUE_W * due_bonus[n] +
        HOT_W * hot_bonus[n]
        for n in range(1, 26)
    ], dtype=float)

    weights = np.clip(weights, 1e-6, None)
    weights /= weights.sum()
    return weights


def _is_valid(combo: list[int], relax: bool = False) -> bool:
    s = sum(combo)
    sum_lo = SUM_MIN - (15 if relax else 0)
    sum_hi = SUM_MAX + (15 if relax else 0)
    if not (sum_lo <= s <= sum_hi):
        return False

    evens = sum(1 for x in combo if x % 2 == 0)
    even_lo = EVEN_MIN - (1 if relax else 0)
    even_hi = EVEN_MAX + (1 if relax else 0)
    if not (even_lo <= evens <= even_hi):
        return False

    decades = [0] * 5
    for x in combo:
        decades[(x - 1) // 5] += 1
    if max(decades) > MAX_DECADE:
        return False

    sorted_c = sorted(combo)
    max_consec = 1
    curr_consec = 1
    for i in range(1, len(sorted_c)):
        if sorted_c[i] == sorted_c[i - 1] + 1:
            curr_consec += 1
            max_consec = max(max_consec, curr_consec)
        else:
            curr_consec = 1
    max_limit = MAX_CONSEC + (1 if relax else 0)
    if max_consec > max_limit:
        return False

    return True


def _sum_score(s: int, mean: float, std: float) -> float:
    if std <= 0:
        return 1.0
    return float(norm.pdf(s, loc=mean, scale=std) / norm.pdf(mean, loc=mean, scale=std))


def _co_occurrence_bonus(combo: list[int], co_matrix: list[list[int]], total: int) -> float:
    if total == 0:
        return 0.0
    bonus = 0.0
    for a, b in itertools.combinations(combo, 2):
        bonus += co_matrix[a - 1][b - 1]
    n_pairs = len(combo) * (len(combo) - 1) / 2
    return bonus / (n_pairs * total) if n_pairs > 0 else 0.0


def _markov_score(combo: list[int], last_draw: list[int], transition: list[list[float]]) -> float:
    if not last_draw or not transition:
        return 0.5
    score = 0.0
    for p in last_draw:
        for c in combo:
            score += transition[p - 1][c - 1]
    return score / (len(last_draw) * len(combo))


def _composite_score(
    combo: list[int],
    weights: np.ndarray,
    analysis: AnalysisResult,
) -> float:
    avg_weight = float(np.mean([weights[n - 1] for n in combo]))
    co_bonus = _co_occurrence_bonus(combo, analysis.co_occurrence, analysis.total_draws)
    s_score = _sum_score(sum(combo), analysis.sum_stats["mean"], analysis.sum_stats["std"])
    m_score = _markov_score(combo, analysis.last_draw, analysis.markov_transition)
    return (avg_weight + co_bonus + s_score + m_score) / 4.0


def _overlap(a: list[int], b: list[int]) -> int:
    return len(set(a) & set(b))


def generate_bets(analysis: AnalysisResult, n_bets: int = N_BETS) -> list[tuple[list[int], float]]:
    if analysis.total_draws < 5:
        logger.warning("Not enough draws for prediction")
        return _fallback_bets(n_bets)

    weights = _build_weights(analysis)
    rng = np.random.default_rng(42)

    candidates: list[tuple[list[int], float]] = []

    for relax in (False, True):
        needed = N_CANDIDATES if not relax else N_CANDIDATES * 2
        for _ in range(needed):
            combo = sorted(rng.choice(25, size=15, replace=False, p=weights).tolist())
            combo = [x + 1 for x in combo]
            if _is_valid(combo, relax=relax):
                score = _composite_score(combo, weights, analysis)
                candidates.append((combo, score))
        if len(candidates) >= 40:
            break

    if not candidates:
        logger.warning("No valid candidates; using fallback")
        return _fallback_bets(n_bets)

    candidates.sort(key=lambda x: x[1], reverse=True)

    # Diversity filter
    selected: list[tuple[list[int], float]] = []
    for combo, score in candidates:
        if all(_overlap(combo, s[0]) <= MAX_OVERLAP for s in selected):
            selected.append((combo, score))
        if len(selected) >= n_bets:
            break

    # Normalize scores to [0, 1]
    if selected:
        raw_scores = [s for _, s in selected]
        s_min, s_max = min(raw_scores), max(raw_scores)
        if s_max > s_min:
            selected = [(c, (s - s_min) / (s_max - s_min)) for c, s in selected]
        else:
            selected = [(c, 0.5) for c, _ in selected]

    return selected


def _fallback_bets(n_bets: int) -> list[tuple[list[int], float]]:
    """Generate simple bets when there's not enough data."""
    rng = np.random.default_rng(0)
    result = []
    for i in range(n_bets):
        combo = sorted(rng.choice(25, size=15, replace=False).tolist())
        combo = [x + 1 for x in combo]
        result.append((combo, 0.5))
    return result
