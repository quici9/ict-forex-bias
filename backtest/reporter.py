"""Reporter — generates eval_report_YYYYMMDD.md in results/ directory."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from backtest.engine import BacktestRow
from backtest.evaluator import FeatureEvalResult
from backtest.metrics import BacktestMetrics, ClassificationMetrics

logger = logging.getLogger(__name__)

_RESULTS_DIR = Path(__file__).parent.parent / "results"


def generate_report(
    symbol: str,
    train_metrics: ClassificationMetrics,
    val_metrics: ClassificationMetrics,
    test_metrics: ClassificationMetrics,
    all_metrics: BacktestMetrics,
    feature_evals: list[FeatureEvalResult],
    best_weights: dict[str, float],
    tuned_val_metrics: Optional[ClassificationMetrics] = None,
    lookahead_violations: int = 0,
    n_train: int = 0,
    n_val: int = 0,
    n_test: int = 0,
) -> Path:
    """Write results/eval_report_YYYYMMDD.md and return the file path."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y%m%d")
    report_path = _RESULTS_DIR / f"eval_report_{today}.md"

    lines: list[str] = []

    # -----------------------------------------------------------------------
    # 1. Executive Summary
    # -----------------------------------------------------------------------
    lines += [
        f"# Backtest Evaluation Report — {symbol}",
        f"_Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
        "| Period | Rows | Accuracy | Precision Bull | Precision Bear | MCC |",
        "|--------|------|----------|----------------|----------------|-----|",
        _metrics_row("Train (default weights)", n_train, train_metrics),
        _metrics_row("Val (default weights)",   n_val,   val_metrics),
        _metrics_row("Test (default weights)",  n_test,  test_metrics),
    ]

    if tuned_val_metrics is not None:
        lines.append(_metrics_row("Val (tuned weights)", n_val, tuned_val_metrics))

    lines += [
        "",
        f"**Accuracy improvement (default → tuned on Val):** "
        f"{(tuned_val_metrics.accuracy - val_metrics.accuracy) * 100:+.1f}%"
        if tuned_val_metrics else "_Tuned metrics not available._",
        "",
    ]

    # -----------------------------------------------------------------------
    # 2. Feature Ranking Table
    # -----------------------------------------------------------------------
    lines += [
        "---",
        "",
        "## 2. Feature Ranking (sorted by IC descending)",
        "",
        "| Feature | IC | IC p-value | NA Rate | Solo Accuracy | Marginal ΔAcc | Recommendation |",
        "|---------|-----|------------|---------|---------------|---------------|----------------|",
    ]
    for ev in feature_evals:
        lines.append(
            f"| {ev.feature_name} "
            f"| {ev.ic:+.3f} "
            f"| {ev.p_value:.3f} "
            f"| {ev.na_rate * 100:.0f}% "
            f"| {ev.solo_accuracy:.3f} "
            f"| {ev.marginal_delta_acc:+.3f} "
            f"| {ev.recommendation} |"
        )

    lines += [""]

    # -----------------------------------------------------------------------
    # 3. Recommended Weight Set
    # -----------------------------------------------------------------------
    lines += [
        "---",
        "",
        "## 3. Recommended Weight Set",
        "",
        "Copy-paste into `config/settings.yaml` under `scoring.weights:`:",
        "",
        "```yaml",
        "scoring:",
        "  weights:",
    ]
    for name, value in best_weights.items():
        lines.append(f"    {name}: {value:.2f}")
    lines += ["```", ""]

    # -----------------------------------------------------------------------
    # 4. Features to Remove
    # -----------------------------------------------------------------------
    to_remove = [ev for ev in feature_evals if ev.recommendation.startswith("remove")]
    to_investigate = [ev for ev in feature_evals if ev.recommendation.startswith("investigate")]

    lines += [
        "---",
        "",
        "## 4. Features to Remove",
        "",
    ]
    if to_remove:
        for ev in to_remove:
            lines.append(f"- **{ev.feature_name}**: IC={ev.ic:+.3f}, NA={ev.na_rate*100:.0f}%, ΔAcc={ev.marginal_delta_acc:+.3f}")
    else:
        lines.append("_No features recommended for removal._")

    lines += [
        "",
        "### Under Investigation",
        "",
    ]
    if to_investigate:
        for ev in to_investigate:
            lines.append(f"- **{ev.feature_name}**: {ev.recommendation} — IC={ev.ic:+.3f}, solo_acc={ev.solo_accuracy:.3f}")
    else:
        lines.append("_No features under investigation._")
    lines += [""]

    # -----------------------------------------------------------------------
    # 5. Thresholds to Change (FeaturesConfig notes)
    # -----------------------------------------------------------------------
    lines += [
        "---",
        "",
        "## 5. Feature Thresholds Notes",
        "",
        "_Threshold tuning was not run in this report. To tune FeaturesConfig parameters,_",
        "_add `--tune-features` flag to the tuner CLI (future work)._",
        "",
        "| Parameter | Current Value | Tuning Range | Step |",
        "|-----------|---------------|--------------|------|",
        "| swing_lookback | — | 3–10 | 1 |",
        "| fvg_min_displacement | — | 1.0–3.0 | 0.25 |",
        "| fvg_lookback_candles | — | 5–20 | 5 |",
        "| sweep_lookback_candles | — | 2–6 | 1 |",
        "| smt_max_candle_diff | — | 2–8 | 1 |",
        "",
    ]

    # -----------------------------------------------------------------------
    # 6. Look-ahead Audit Log
    # -----------------------------------------------------------------------
    lines += [
        "---",
        "",
        "## 6. Look-ahead Audit Log",
        "",
        f"**Total violations detected:** {lookahead_violations}",
        "",
    ]
    if lookahead_violations == 0:
        lines.append("✓ No look-ahead bias violations found. All features used only data strictly before signal_date T.")
    else:
        lines.append(f"⚠️ {lookahead_violations} look-ahead violation(s) were detected and skipped during backtest.")
    lines += ["", "---", "", "_End of report._", ""]

    # -----------------------------------------------------------------------
    # Write to file
    # -----------------------------------------------------------------------
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report written to %s", report_path)
    return report_path


def _metrics_row(label: str, n: int, m: ClassificationMetrics) -> str:
    return (
        f"| {label} | {n} "
        f"| {m.accuracy:.3f} "
        f"| {m.precision_bullish:.3f} "
        f"| {m.precision_bearish:.3f} "
        f"| {m.mcc:.4f} |"
    )
