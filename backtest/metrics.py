"""Backtest metrics — accuracy, precision, recall, MCC, IC, na_rate, win-rate buckets."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import math

import numpy as np
import pandas as pd

from backtest.engine import BacktestRow


def _normal_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (no scipy needed)."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _rank(arr: np.ndarray) -> np.ndarray:
    """Return average ranks for arr (handles ties via average method)."""
    order = arr.argsort()
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(arr) + 1)
    # Handle ties: find groups of equal values and assign average rank
    i = 0
    sorted_arr = arr[order]
    while i < len(sorted_arr):
        j = i + 1
        while j < len(sorted_arr) and sorted_arr[j] == sorted_arr[i]:
            j += 1
        if j > i + 1:
            avg = ranks[order[i:j]].mean()
            ranks[order[i:j]] = avg
        i = j
    return ranks
from src.models import InstrumentFeatures


# ---------------------------------------------------------------------------
# Dataclasses for metric results
# ---------------------------------------------------------------------------

@dataclass
class ClassificationMetrics:
    accuracy: float = 0.0
    precision_bullish: float = 0.0
    precision_bearish: float = 0.0
    recall_bullish: float = 0.0
    recall_bearish: float = 0.0
    mcc: float = 0.0
    n_total: int = 0
    n_bullish_signals: int = 0
    n_bearish_signals: int = 0
    n_neutral_signals: int = 0


@dataclass
class FeatureIC:
    feature_name: str
    ic: float = 0.0          # Spearman correlation with outcome_1d
    na_rate: float = 0.0     # fraction of rows where feature is None/NaN
    p_value: float = 1.0


@dataclass
class WinRateBucket:
    label: str           # e.g. "[50-60)"
    score_min: int
    score_max: int
    n_signals: int = 0
    win_rate: float = 0.0


@dataclass
class BacktestMetrics:
    classification: ClassificationMetrics = field(default_factory=ClassificationMetrics)
    feature_ics: list[FeatureIC] = field(default_factory=list)
    win_rate_buckets: list[WinRateBucket] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature names that can be evaluated for IC
# ---------------------------------------------------------------------------

NUMERIC_FEATURES: list[str] = [
    "d1_structure",
    "d1_structure_clarity",
    "h1_structure",
    "price_zone",
    "zone_strength",
    "fvg_direction_h1",
    "fvg_size_h1",
    "sweep_direction",
    "smt_direction",
]

BOOL_FEATURES: list[str] = [
    "d1_h1_alignment",
    "bos_recent",
    "choch_recent",
    "fvg_exists_h1",
    "near_pdh",
    "near_pdl",
    "swept_pdh",
    "swept_pdl",
    "sweep_occurred",
    "smt_signal",
]


# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------

def _is_correct(row: BacktestRow) -> Optional[bool]:
    """Return True/False/None (non-directional signal → None)."""
    if row.bias_predicted not in ("BULLISH", "BEARISH"):
        return None
    if np.isnan(row.outcome_1d):
        return None
    if row.bias_predicted == "BULLISH":
        return row.outcome_1d > 0
    return row.outcome_1d < 0


def compute_classification_metrics(rows: list[BacktestRow]) -> ClassificationMetrics:
    """Compute accuracy, precision, recall, MCC from a list of BacktestRows."""
    directional = [r for r in rows if r.bias_predicted in ("BULLISH", "BEARISH")
                   and not np.isnan(r.outcome_1d)]

    if not directional:
        return ClassificationMetrics(n_total=len(rows))

    # TP/FP/FN/TN for binary BULLISH (positive) vs BEARISH (negative)
    tp = sum(1 for r in directional if r.bias_predicted == "BULLISH" and r.outcome_1d > 0)
    fp = sum(1 for r in directional if r.bias_predicted == "BULLISH" and r.outcome_1d <= 0)
    fn = sum(1 for r in directional if r.bias_predicted == "BEARISH" and r.outcome_1d > 0)
    tn = sum(1 for r in directional if r.bias_predicted == "BEARISH" and r.outcome_1d <= 0)

    n = len(directional)
    accuracy = (tp + tn) / n if n > 0 else 0.0
    precision_bull = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    precision_bear = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    recall_bull = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    recall_bear = tn / (tn + fp) if (tn + fp) > 0 else 0.0

    mcc_denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / mcc_denom if mcc_denom > 0 else 0.0

    return ClassificationMetrics(
        accuracy=accuracy,
        precision_bullish=precision_bull,
        precision_bearish=precision_bear,
        recall_bullish=recall_bull,
        recall_bearish=recall_bear,
        mcc=mcc,
        n_total=len(rows),
        n_bullish_signals=sum(1 for r in rows if r.bias_predicted == "BULLISH"),
        n_bearish_signals=sum(1 for r in rows if r.bias_predicted == "BEARISH"),
        n_neutral_signals=sum(1 for r in rows if r.bias_predicted in ("NEUTRAL", "WATCHLIST")),
    )


# ---------------------------------------------------------------------------
# Feature IC (Information Coefficient)
# ---------------------------------------------------------------------------

def _extract_feature_value(row: BacktestRow, feature_name: str) -> Optional[float]:
    """Extract a scalar feature value from a BacktestRow, converting bools to float."""
    f: InstrumentFeatures = row.features
    val = getattr(f, feature_name, None)
    if val is None:
        return None
    if isinstance(val, bool):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def compute_feature_ic(rows: list[BacktestRow], feature_name: str) -> FeatureIC:
    """Compute Spearman IC between feature_name values and outcome_1d."""
    values: list[float] = []
    outcomes: list[float] = []

    for row in rows:
        if np.isnan(row.outcome_1d):
            continue
        val = _extract_feature_value(row, feature_name)
        if val is not None:
            values.append(val)
            outcomes.append(row.outcome_1d)

    na_rate = 1.0 - len(values) / len(rows) if rows else 1.0

    if len(values) < 10:
        return FeatureIC(feature_name=feature_name, ic=0.0, na_rate=na_rate, p_value=1.0)

    # Spearman = Pearson on ranks (no scipy needed)
    r_vals = _rank(np.array(values, dtype=float))
    r_outcomes = _rank(np.array(outcomes, dtype=float))
    corr = float(np.corrcoef(r_vals, r_outcomes)[0, 1])
    ic = corr if not math.isnan(corr) else 0.0

    # Two-sided p-value approximation: t = r * sqrt((n-2)/(1-r^2))
    n = len(values)
    if abs(ic) >= 1.0 or n <= 2:
        p_value = 0.0 if abs(ic) >= 1.0 else 1.0
    else:
        t_stat = ic * math.sqrt((n - 2) / (1 - ic ** 2))
        # Approximate p-value using normal distribution (valid for large n)
        p_value = float(2 * (1 - _normal_cdf(abs(t_stat))))

    return FeatureIC(feature_name=feature_name, ic=ic, na_rate=na_rate, p_value=p_value)


def compute_all_feature_ics(rows: list[BacktestRow]) -> list[FeatureIC]:
    """Compute IC for all known numeric and boolean features."""
    all_features = NUMERIC_FEATURES + BOOL_FEATURES
    return [compute_feature_ic(rows, fn) for fn in all_features]


# ---------------------------------------------------------------------------
# Win rate by score bucket
# ---------------------------------------------------------------------------

_BUCKETS = [
    ("[50-60)", 50, 60),
    ("[60-70)", 60, 70),
    ("[70-80)", 70, 80),
    ("[80+]",   80, 101),
]


def compute_winrate_by_bucket(rows: list[BacktestRow]) -> list[WinRateBucket]:
    """Group directional signals by score bucket and compute win rate per bucket."""
    result: list[WinRateBucket] = []
    directional = [r for r in rows if r.bias_predicted in ("BULLISH", "BEARISH")
                   and not np.isnan(r.outcome_1d)]

    for label, lo, hi in _BUCKETS:
        bucket_rows = [r for r in directional if lo <= r.score.score < hi]
        if not bucket_rows:
            result.append(WinRateBucket(label=label, score_min=lo, score_max=hi))
            continue

        wins = sum(1 for r in bucket_rows
                   if (r.bias_predicted == "BULLISH" and r.outcome_1d > 0)
                   or (r.bias_predicted == "BEARISH" and r.outcome_1d < 0))
        result.append(WinRateBucket(
            label=label,
            score_min=lo,
            score_max=hi,
            n_signals=len(bucket_rows),
            win_rate=wins / len(bucket_rows),
        ))

    return result


# ---------------------------------------------------------------------------
# Aggregate all metrics
# ---------------------------------------------------------------------------

def compute_all_metrics(rows: list[BacktestRow]) -> BacktestMetrics:
    return BacktestMetrics(
        classification=compute_classification_metrics(rows),
        feature_ics=compute_all_feature_ics(rows),
        win_rate_buckets=compute_winrate_by_bucket(rows),
    )
