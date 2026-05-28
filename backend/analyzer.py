from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class AnalysisResult:
    frequency: dict[int, int] = field(default_factory=dict)
    frequency_pct: dict[int, float] = field(default_factory=dict)
    recency: dict[int, int] = field(default_factory=dict)
    hot_numbers: list[int] = field(default_factory=list)
    cold_numbers: list[int] = field(default_factory=list)
    due_numbers: list[int] = field(default_factory=list)
    even_odd_avg: dict[str, float] = field(default_factory=dict)
    sum_stats: dict = field(default_factory=dict)
    decade_dist: dict[str, float] = field(default_factory=dict)
    co_occurrence: list[list[int]] = field(default_factory=list)
    top_pairs: list[dict] = field(default_factory=list)
    top_trios: list[dict] = field(default_factory=list)
    markov_transition: list[list[float]] = field(default_factory=list)
    last_draw: list[int] = field(default_factory=list)
    last_concurso: int = 0
    last_data: str = ""
    total_draws: int = 0
    sum_distribution: list[int] = field(default_factory=list)
    sum_buckets: list[str] = field(default_factory=list)
    frequency_recent: dict[int, int] = field(default_factory=dict)


def compute_analysis(df: pd.DataFrame) -> AnalysisResult:
    if df.empty or len(df) < 5:
        return AnalysisResult()

    df = df.sort_values("concurso").reset_index(drop=True)
    total = len(df)
    all_dezenas = df["dezenas"].tolist()

    # --- Frequency ---
    freq: dict[int, int] = {n: 0 for n in range(1, 26)}
    for dez in all_dezenas:
        for n in dez:
            freq[n] = freq.get(n, 0) + 1

    freq_pct = {n: round(freq[n] / total * 100, 2) for n in range(1, 26)}

    # --- Frequency recent (last 20 draws) ---
    recent_n = min(20, total)
    freq_recent: dict[int, int] = {n: 0 for n in range(1, 26)}
    for dez in all_dezenas[-recent_n:]:
        for n in dez:
            freq_recent[n] = freq_recent.get(n, 0) + 1

    # --- Recency (draws since last appearance) ---
    recency: dict[int, int] = {}
    for n in range(1, 26):
        for i in range(len(all_dezenas) - 1, -1, -1):
            if n in all_dezenas[i]:
                recency[n] = (len(all_dezenas) - 1) - i
                break
        else:
            recency[n] = total

    # --- Hot / Cold ---
    sorted_by_recent = sorted(range(1, 26), key=lambda n: freq_recent[n], reverse=True)
    hot_numbers = sorted_by_recent[:10]
    cold_numbers = sorted_by_recent[-10:]

    # --- Due numbers ---
    due_numbers = []
    for n in range(1, 26):
        avg_gap = total / max(freq[n], 1)
        if recency[n] > avg_gap:
            due_numbers.append(n)

    # --- Even/Odd ---
    even_counts = [sum(1 for x in dez if x % 2 == 0) for dez in all_dezenas]
    avg_even = float(np.mean(even_counts))
    even_odd_avg = {"even": round(avg_even, 2), "odd": round(15 - avg_even, 2)}

    # --- Sum stats ---
    sums = [sum(dez) for dez in all_dezenas]
    sum_stats = {
        "mean": round(float(np.mean(sums)), 2),
        "std": round(float(np.std(sums)), 2),
        "min": int(min(sums)),
        "max": int(max(sums)),
        "median": round(float(np.median(sums)), 2),
    }

    # Sum distribution histogram (buckets of 10)
    bucket_min, bucket_max = 140, 260
    buckets = list(range(bucket_min, bucket_max + 1, 10))
    hist, _ = np.histogram(sums, bins=buckets)
    sum_distribution = hist.tolist()
    sum_buckets = [f"{buckets[i]}-{buckets[i+1]-1}" for i in range(len(buckets) - 1)]

    # --- Decade distribution ---
    decade_labels = ["1-5", "6-10", "11-15", "16-20", "21-25"]
    decade_ranges = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25)]
    decade_sums = [0] * 5
    for dez in all_dezenas:
        for i, (lo, hi) in enumerate(decade_ranges):
            decade_sums[i] += sum(1 for x in dez if lo <= x <= hi)
    decade_dist = {decade_labels[i]: round(decade_sums[i] / total, 2) for i in range(5)}

    # --- Co-occurrence matrix (25x25) ---
    co_matrix = np.zeros((25, 25), dtype=int)
    for dez in all_dezenas:
        for a, b in itertools.combinations(dez, 2):
            co_matrix[a - 1][b - 1] += 1
            co_matrix[b - 1][a - 1] += 1

    # --- Top pairs ---
    pair_scores = []
    for i in range(25):
        for j in range(i + 1, 25):
            pair_scores.append({"pair": [i + 1, j + 1], "count": int(co_matrix[i][j])})
    top_pairs = sorted(pair_scores, key=lambda x: x["count"], reverse=True)[:20]

    # --- Top trios ---
    trio_scores = {}
    for dez in all_dezenas:
        for combo in itertools.combinations(sorted(dez), 3):
            trio_scores[combo] = trio_scores.get(combo, 0) + 1
    top_trios_raw = sorted(trio_scores.items(), key=lambda x: x[1], reverse=True)[:15]
    top_trios = [{"trio": list(k), "count": v} for k, v in top_trios_raw]

    # --- Markov transition matrix ---
    transition = np.zeros((25, 25), dtype=float)
    for i in range(1, total):
        prev = all_dezenas[i - 1]
        curr = all_dezenas[i]
        for p in prev:
            for c in curr:
                transition[p - 1][c - 1] += 1
    row_sums = transition.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    transition = transition / row_sums

    last_draw = sorted(all_dezenas[-1]) if all_dezenas else []
    last_row = df.iloc[-1]

    return AnalysisResult(
        frequency=freq,
        frequency_pct=freq_pct,
        recency=recency,
        hot_numbers=hot_numbers,
        cold_numbers=cold_numbers,
        due_numbers=due_numbers,
        even_odd_avg=even_odd_avg,
        sum_stats=sum_stats,
        decade_dist=decade_dist,
        co_occurrence=co_matrix.tolist(),
        top_pairs=top_pairs,
        top_trios=top_trios,
        markov_transition=transition.tolist(),
        last_draw=last_draw,
        last_concurso=int(last_row["concurso"]),
        last_data=str(last_row.get("data", "")),
        total_draws=total,
        sum_distribution=sum_distribution,
        sum_buckets=sum_buckets,
        frequency_recent=freq_recent,
    )
