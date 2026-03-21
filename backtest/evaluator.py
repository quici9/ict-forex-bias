"""Per-feature evaluator — measures each feature's individual and marginal contribution."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass

from src.config import AppConfig, ScoringWeights
from backtest.engine import BacktestRow
from backtest.metrics import (
    ClassificationMetrics,
    compute_classification_metrics,
    compute_feature_ic,
    FeatureIC,
)
from src.scoring.scorer import score_instrument

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FeatureEvalResult:
    feature_name: str
    ic: float = 0.0
    na_rate: float = 0.0
    p_value: float = 1.0
    solo_accuracy: float = 0.0   # accuracy when only this feature has weight=1.0
    marginal_delta_acc: float = 0.0  # Acc(all) - Acc(all except this feature)
    recommendation: str = "keep"  # "keep" | "investigate" | "remove"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCOREABLE_FEATURES = [
    "d1_structure",
    "d1_h1_alignment",
    "price_zone",
    "fvg_h1",
    "sweep",
    "smt",
    "bos_recent",
]

# Mapping from scoring weight name → InstrumentFeatures field that carries the signal
_WEIGHT_TO_SIGNAL_FIELD: dict[str, str] = {
    "d1_structure":    "d1_structure",
    "d1_h1_alignment": "d1_h1_alignment",
    "price_zone":      "price_zone",
    "fvg_h1":          "fvg_direction_h1",
    "sweep":           "sweep_direction",
    "smt":             "smt_direction",
    "bos_recent":      "bos_recent",
}


def _rescore_rows(rows: list[BacktestRow], config: AppConfig) -> list[BacktestRow]:
    """Re-run scorer on all rows using the current config weights, return new rows."""
    rescored: list[BacktestRow] = []
    for row in rows:
        new_score = score_instrument(row.features, config)
        new_row = copy.copy(row)
        new_row.score = new_score
        new_row.bias_predicted = new_score.bias
        rescored.append(new_row)
    return rescored


def _config_with_only(base_config: AppConfig, feature_name: str) -> AppConfig:
    """Return a config where only feature_name has weight=1.0, all others=0.0."""
    cfg = copy.deepcopy(base_config)
    w = cfg.scoring.weights
    for fn in _SCOREABLE_FEATURES:
        setattr(w, fn, 1.0 if fn == feature_name else 0.0)
    return cfg


def _config_without(base_config: AppConfig, feature_name: str) -> AppConfig:
    """Return a config where feature_name has weight=0.0, others keep original values (renormalized)."""
    cfg = copy.deepcopy(base_config)
    w = cfg.scoring.weights
    original_weight = getattr(w, feature_name, 0.0)
    setattr(w, feature_name, 0.0)

    # Renormalize remaining weights so they still sum to ~1.0
    remaining_total = sum(
        getattr(w, fn) for fn in _SCOREABLE_FEATURES if fn != feature_name
    )
    if remaining_total > 0 and original_weight > 0:
        scale = 1.0 / remaining_total
        for fn in _SCOREABLE_FEATURES:
            if fn != feature_name:
                setattr(w, fn, getattr(w, fn) * scale)
    return cfg


# ---------------------------------------------------------------------------
# Main evaluation functions
# ---------------------------------------------------------------------------

def evaluate_single_feature(
    rows: list[BacktestRow],
    feature_name: str,
    baseline_accuracy: float,
    config: AppConfig,
) -> FeatureEvalResult:
    """Evaluate one scoring feature in isolation and vs the full model."""
    ic_result: FeatureIC = compute_feature_ic(rows, _WEIGHT_TO_SIGNAL_FIELD.get(feature_name, feature_name))

    # Solo accuracy: only this feature has weight, others = 0
    solo_config = _config_with_only(config, feature_name)
    solo_rows = _rescore_rows(rows, solo_config)
    solo_metrics: ClassificationMetrics = compute_classification_metrics(solo_rows)

    # Marginal: accuracy without this feature (others renormalized)
    ablated_config = _config_without(config, feature_name)
    ablated_rows = _rescore_rows(rows, ablated_config)
    ablated_metrics: ClassificationMetrics = compute_classification_metrics(ablated_rows)
    marginal_delta = baseline_accuracy - ablated_metrics.accuracy

    # Recommendation logic
    recommendation = _recommend(ic_result.ic, ic_result.na_rate, marginal_delta, solo_metrics.accuracy)

    return FeatureEvalResult(
        feature_name=feature_name,
        ic=ic_result.ic,
        na_rate=ic_result.na_rate,
        p_value=ic_result.p_value,
        solo_accuracy=solo_metrics.accuracy,
        marginal_delta_acc=marginal_delta,
        recommendation=recommendation,
    )


def _recommend(ic: float, na_rate: float, marginal_delta: float, solo_acc: float) -> str:
    if marginal_delta < -0.02:
        return "remove"  # removing this feature improves accuracy by > 2%
    if ic < 0.0:
        return "investigate (negative IC)"
    if ic < 0.02 and na_rate > 0.50:
        return "remove"
    if solo_acc < 0.52:
        return "investigate (low solo accuracy)"
    return "keep"


def evaluate_all_features(
    rows: list[BacktestRow],
    config: AppConfig,
) -> list[FeatureEvalResult]:
    """Evaluate every scoring feature; returns list sorted by IC descending."""
    baseline_metrics = compute_classification_metrics(rows)
    baseline_accuracy = baseline_metrics.accuracy

    logger.info(
        "Evaluating %d features. Baseline accuracy: %.3f (n=%d)",
        len(_SCOREABLE_FEATURES), baseline_accuracy, baseline_metrics.n_total,
    )

    results: list[FeatureEvalResult] = []
    for feature_name in _SCOREABLE_FEATURES:
        result = evaluate_single_feature(rows, feature_name, baseline_accuracy, config)
        logger.info(
            "  %s: IC=%.3f na=%.0f%% solo_acc=%.3f ΔAcc=%.3f → %s",
            feature_name, result.ic, result.na_rate * 100,
            result.solo_accuracy, result.marginal_delta_acc, result.recommendation,
        )
        results.append(result)

    results.sort(key=lambda r: r.ic, reverse=True)
    return results
