"""Weight tuner — walk-forward grid search to find optimal scoring weights.

CLI usage:
    python backtest/tuner.py --symbol EURUSD=X --train 2020-2022 --val 2023

Walk-forward split (fixed):
    Train: 2020-01-01 → 2022-12-31
    Val:   2023-01-01 → 2023-12-31
    Test:  2024-01-01 → 2024-12-31

Grid: each weight ∈ {0.0, 0.1, 0.2, 0.3}, sum must == 1.0 (± 0.001).
Objective: maximize MCC on validation set.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

# Allow running as `python backtest/tuner.py` from project root
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import AppConfig, load_config, ScoringWeights
from backtest.engine import BacktestEngine, BacktestRow
from backtest.metrics import compute_classification_metrics, ClassificationMetrics

logger = logging.getLogger(__name__)

_WEIGHT_GRID = [0.0, 0.1, 0.2, 0.3]
_WEIGHT_NAMES = ["d1_structure", "d1_h1_alignment", "price_zone", "fvg_h1", "sweep", "smt", "bos_recent"]
_N_WEIGHTS = len(_WEIGHT_NAMES)
_SUM_TARGET = 1.0
_SUM_TOLERANCE = 0.001


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------

def walk_forward_split(
    rows: list[BacktestRow],
    train_start: date = date(2020, 1, 1),
    train_end: date = date(2022, 12, 31),
    val_start: date = date(2023, 1, 1),
    val_end: date = date(2023, 12, 31),
    test_start: date = date(2024, 1, 1),
    test_end: date = date(2024, 12, 31),
) -> tuple[list[BacktestRow], list[BacktestRow], list[BacktestRow]]:
    """Split rows into non-overlapping train / val / test sets by signal_date."""
    train = [r for r in rows if train_start <= r.signal_date <= train_end]
    val   = [r for r in rows if val_start   <= r.signal_date <= val_end]
    test  = [r for r in rows if test_start  <= r.signal_date <= test_end]
    return train, val, test


# ---------------------------------------------------------------------------
# Grid search helpers
# ---------------------------------------------------------------------------

def _enumerate_valid_combos() -> list[tuple[float, ...]]:
    """Return all weight tuples from the grid that sum to 1.0 (± tolerance)."""
    valid: list[tuple[float, ...]] = []
    # Convert to integer units (×10) to avoid float precision issues
    int_grid = [int(round(w * 10)) for w in _WEIGHT_GRID]
    int_target = int(round(_SUM_TARGET * 10))

    for combo in itertools.product(int_grid, repeat=_N_WEIGHTS):
        if sum(combo) == int_target:
            valid.append(tuple(v / 10.0 for v in combo))

    return valid


def _apply_weights(config: AppConfig, weights: tuple[float, ...]) -> AppConfig:
    """Return a config copy with the given weight tuple applied."""
    cfg = copy.deepcopy(config)
    w = cfg.scoring.weights
    for name, value in zip(_WEIGHT_NAMES, weights):
        setattr(w, name, value)
    return cfg


def _rescore_rows(rows: list[BacktestRow], config: AppConfig) -> list[BacktestRow]:
    """Re-run scorer with updated config. Does not touch features or outcomes."""
    from backtest.evaluator import _rescore_rows as _rs
    return _rs(rows, config)


def grid_search_weights(
    train_rows: list[BacktestRow],
    val_rows: list[BacktestRow],
    config: AppConfig,
) -> tuple[ScoringWeights, ClassificationMetrics]:
    """Search all valid weight combos; return best weights + val metrics.

    Selection criterion: maximize MCC on validation set.
    Ties broken by accuracy.
    """
    combos = _enumerate_valid_combos()
    logger.info("Grid search: %d valid weight combinations to evaluate", len(combos))

    best_weights: Optional[tuple[float, ...]] = None
    best_mcc: float = -2.0
    best_metrics: Optional[ClassificationMetrics] = None

    for i, combo in enumerate(combos):
        cfg = _apply_weights(config, combo)
        val_rescored = _rescore_rows(val_rows, cfg)
        metrics = compute_classification_metrics(val_rescored)

        if metrics.mcc > best_mcc or (metrics.mcc == best_mcc and metrics.accuracy > (best_metrics.accuracy if best_metrics else 0.0)):
            best_mcc = metrics.mcc
            best_weights = combo
            best_metrics = metrics

        if (i + 1) % 100 == 0:
            logger.debug("Grid search progress: %d/%d (best MCC so far: %.4f)", i + 1, len(combos), best_mcc)

    if best_weights is None:
        logger.warning("Grid search: no valid combination found, using default weights")
        return config.scoring.weights, compute_classification_metrics(val_rows)

    result_weights = ScoringWeights(**dict(zip(_WEIGHT_NAMES, best_weights)))
    logger.info("Best weights found: %s — Val MCC=%.4f", result_weights, best_mcc)
    return result_weights, best_metrics  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_csv_or_fetch(symbol: str, interval: str, cache_dir: Path) -> Optional[pd.DataFrame]:
    """Load DataFrame from CSV cache if available, else return None."""
    filename = f"{symbol.replace('=', '').replace('-', '_')}_{interval}.csv"
    path = cache_dir / filename
    if path.exists():
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        logger.info("Loaded %s from cache (%d rows)", path.name, len(df))
        return df
    logger.warning("Cache file not found: %s — run scripts/fetch_history.py first", path)
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_year_range(s: str) -> tuple[date, date]:
    """Parse '2020-2022' → (date(2020,1,1), date(2022,12,31))."""
    parts = s.split("-")
    start_year = int(parts[0])
    end_year = int(parts[-1])
    return date(start_year, 1, 1), date(end_year, 12, 31)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Tune scoring weights via walk-forward grid search")
    parser.add_argument("--symbol", required=True, help="e.g. EURUSD=X")
    parser.add_argument("--train", default="2020-2022", help="Train period e.g. 2020-2022")
    parser.add_argument("--val", default="2023", help="Validation period e.g. 2023")
    parser.add_argument("--test", default="2024", help="Test period e.g. 2024")
    parser.add_argument("--data-dir", default="data/backtest", help="Directory with cached CSVs")
    args = parser.parse_args()

    config = load_config()
    cache_dir = Path(args.data_dir)

    symbol = args.symbol
    partner_symbol: Optional[str] = None
    for inst in config.instruments:
        if inst.symbol == symbol:
            partner_symbol = inst.smt_partner
            break

    d1_full = _load_csv_or_fetch(symbol, "1d", cache_dir)
    h1_full = _load_csv_or_fetch(symbol, "1h", cache_dir)
    if d1_full is None or h1_full is None:
        logger.error("Cannot run tuner without cached data. Run scripts/fetch_history.py first.")
        sys.exit(1)

    partner_d1 = _load_csv_or_fetch(partner_symbol, "1d", cache_dir) if partner_symbol else None
    partner_h1 = _load_csv_or_fetch(partner_symbol, "1h", cache_dir) if partner_symbol else None

    train_start, train_end = _parse_year_range(args.train)
    val_start, val_end = _parse_year_range(args.val)
    test_start, test_end = _parse_year_range(args.test)

    overall_start = min(train_start, val_start, test_start)
    overall_end = max(train_end, val_end, test_end)

    logger.info("Running backtest for %s from %s to %s", symbol, overall_start, overall_end)
    engine = BacktestEngine(config)
    all_rows = engine.run(
        symbol=symbol,
        d1_full=d1_full,
        h1_full=h1_full,
        start_date=overall_start,
        end_date=overall_end,
        partner_d1=partner_d1,
        partner_h1=partner_h1,
        partner_symbol=partner_symbol,
    )

    train_rows, val_rows, test_rows = walk_forward_split(
        all_rows,
        train_start=train_start, train_end=train_end,
        val_start=val_start, val_end=val_end,
        test_start=test_start, test_end=test_end,
    )
    logger.info("Split: train=%d, val=%d, test=%d rows", len(train_rows), len(val_rows), len(test_rows))

    # Evaluate baseline on val set
    baseline_metrics = compute_classification_metrics(val_rows)
    logger.info(
        "Baseline (default weights) — Val: acc=%.3f mcc=%.4f",
        baseline_metrics.accuracy, baseline_metrics.mcc,
    )

    # Run grid search on train+val (find best weights, evaluate on val)
    best_weights, val_metrics = grid_search_weights(train_rows, val_rows, config)

    # Apply best weights and evaluate on test set (report only)
    test_config = copy.deepcopy(config)
    for name in _WEIGHT_NAMES:
        setattr(test_config.scoring.weights, name, getattr(best_weights, name))
    test_rescored = _rescore_rows(test_rows, test_config)
    test_metrics = compute_classification_metrics(test_rescored)

    print("\n=== Tuner Results ===")
    print(f"Symbol: {symbol}  |  Train: {args.train}  |  Val: {args.val}  |  Test: {args.test}")
    print(f"\nBest weights:")
    for name in _WEIGHT_NAMES:
        print(f"  {name}: {getattr(best_weights, name):.2f}")
    print(f"\nVal  — accuracy={val_metrics.accuracy:.3f}  mcc={val_metrics.mcc:.4f}")
    print(f"Test — accuracy={test_metrics.accuracy:.3f}  mcc={test_metrics.mcc:.4f}")
    print(f"\nBaseline val — accuracy={baseline_metrics.accuracy:.3f}  mcc={baseline_metrics.mcc:.4f}")
    print("\nAdd to config/settings.yaml under scoring.weights:")
    for name in _WEIGHT_NAMES:
        print(f"  {name}: {getattr(best_weights, name):.2f}")


if __name__ == "__main__":
    main()
