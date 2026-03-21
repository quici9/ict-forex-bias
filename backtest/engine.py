"""Backtest engine — replay historical data day-by-day, compute features and scores.

HARD CONSTRAINT: Features at signal_date T use ONLY data with index < T (strict less-than).
No exceptions. verify_no_lookahead() is called before every feature calculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.config import AppConfig
from src.data.fetcher import calculate_atr
from src.features.aggregator import calculate_all_features
from src.models import InstrumentData, InstrumentFeatures, InstrumentScore
from src.scoring.scorer import score_instrument

logger = logging.getLogger(__name__)

# Minimum D1 and H1 candles required before a backtest row is generated.
_MIN_D1 = 30
_MIN_H1 = 24


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class BacktestRow:
    """One row of backtest output — signal + outcome for signal_date T."""
    signal_date: date
    symbol: str
    features: InstrumentFeatures
    score: InstrumentScore
    bias_predicted: str          # BULLISH | BEARISH | NEUTRAL | WATCHLIST | LOW_VOL
    outcome_1d: float            # Close[T+1] - Open[T]; NaN if unavailable
    outcome_3d: float            # Close[T+3] - Open[T]; NaN if unavailable
    label_1d: int                # +1 | -1 | 0 based on outcome_1d vs ATR threshold
    open_T: float = 0.0
    atr14_at_T: float = 0.0


# ---------------------------------------------------------------------------
# Look-ahead guard
# ---------------------------------------------------------------------------

def verify_no_lookahead(df: pd.DataFrame, signal_date: pd.Timestamp) -> None:
    """Raise ValueError if any row in df has index >= signal_date.

    Args:
        df:           The sliced DataFrame to verify.
        signal_date:  The current signal timestamp (T 00:00 UTC).
    """
    violations = df[df.index >= signal_date]
    if not violations.empty:
        raise ValueError(
            f"Look-ahead bias detected: {len(violations)} row(s) at or after "
            f"{signal_date}. First violation: {violations.index[0]}"
        )


# ---------------------------------------------------------------------------
# Helper: build InstrumentData from pre-sliced DataFrames
# ---------------------------------------------------------------------------

def _make_instrument_data(
    symbol: str,
    d1_slice: pd.DataFrame,
    h1_slice: pd.DataFrame,
    config: AppConfig,
) -> InstrumentData:
    """Wrap sliced DataFrames into InstrumentData, computing ATR from the slice."""
    atr14 = calculate_atr(d1_slice)
    is_valid = len(d1_slice) >= config.data.min_d1_candles and len(h1_slice) >= config.data.min_h1_candles
    return InstrumentData(
        symbol=symbol,
        d1=d1_slice,
        h1=h1_slice,
        atr14_d1=atr14,
        is_valid=is_valid,
    )


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------

def _compute_outcomes(
    d1_full: pd.DataFrame,
    signal_ts: pd.Timestamp,
    atr14: float,
) -> tuple[float, float, float, int]:
    """Return (open_T, outcome_1d, outcome_3d, label_1d).

    Outcomes are computed from d1_full rows at or after signal_date,
    so they are NOT used for feature computation — only for evaluation.
    """
    future = d1_full[d1_full.index >= signal_ts]
    if future.empty:
        return 0.0, float("nan"), float("nan"), 0

    open_T = float(future.iloc[0]["Open"])
    outcome_1d = float(future.iloc[1]["Close"]) - open_T if len(future) > 1 else float("nan")
    outcome_3d = float(future.iloc[3]["Close"]) - open_T if len(future) > 3 else float("nan")

    threshold = atr14 * 0.3
    if np.isnan(outcome_1d) or threshold == 0.0:
        label_1d = 0
    elif outcome_1d > threshold:
        label_1d = 1
    elif outcome_1d < -threshold:
        label_1d = -1
    else:
        label_1d = 0

    return open_T, outcome_1d, outcome_3d, label_1d


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Replays historical data for one symbol and computes per-day features/scores.

    Usage:
        engine = BacktestEngine(config)
        rows = engine.run("EURUSD=X", d1_full, h1_full, start, end)
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def run(
        self,
        symbol: str,
        d1_full: pd.DataFrame,
        h1_full: pd.DataFrame,
        start_date: date,
        end_date: date,
        partner_d1: Optional[pd.DataFrame] = None,
        partner_h1: Optional[pd.DataFrame] = None,
        partner_symbol: Optional[str] = None,
    ) -> list[BacktestRow]:
        """Replay from start_date to end_date, yielding one BacktestRow per trading day.

        Args:
            symbol:         Instrument ticker (e.g. "EURUSD=X").
            d1_full:        Full D1 DataFrame covering start_date - N_lookback to end_date + 5.
            h1_full:        Full H1 DataFrame, same coverage.
            start_date:     First signal date (inclusive).
            end_date:       Last signal date (inclusive).
            partner_d1:     Optional D1 data for SMT partner instrument.
            partner_h1:     Optional H1 data for SMT partner instrument.
            partner_symbol: Ticker of the SMT partner.
        """
        rows: list[BacktestRow] = []
        cfg = self.config

        # Build the list of trading days within [start_date, end_date]
        trading_days = self._get_trading_days(d1_full, start_date, end_date)
        logger.info(
            "BacktestEngine.run: %s — %d trading days from %s to %s",
            symbol, len(trading_days), start_date, end_date,
        )

        for T in trading_days:
            signal_ts = pd.Timestamp(T, tz="UTC")

            # Slice strictly before T — the ONLY valid data for feature computation
            d1_slice = d1_full[d1_full.index < signal_ts].tail(cfg.data.d1_candles)
            h1_slice = h1_full[h1_full.index < signal_ts].tail(cfg.data.h1_candles)

            if len(d1_slice) < _MIN_D1:
                logger.debug("Skipping %s on %s: insufficient D1 (%d)", symbol, T, len(d1_slice))
                continue

            # Enforce look-ahead guard (raises on violation)
            try:
                verify_no_lookahead(d1_slice, signal_ts)
                verify_no_lookahead(h1_slice, signal_ts)
            except ValueError as exc:
                logger.error("Look-ahead violation for %s on %s: %s", symbol, T, exc)
                continue

            logger.debug(
                "%s @ %s: D1=%d candles, H1=%d candles",
                symbol, T, len(d1_slice), len(h1_slice),
            )

            # Build InstrumentData objects from slices
            inst_data = _make_instrument_data(symbol, d1_slice, h1_slice, cfg)

            partner_data: Optional[InstrumentData] = None
            if partner_d1 is not None and partner_h1 is not None and partner_symbol:
                p_d1_slice = partner_d1[partner_d1.index < signal_ts].tail(cfg.data.d1_candles)
                p_h1_slice = partner_h1[partner_h1.index < signal_ts].tail(cfg.data.h1_candles)
                partner_data = _make_instrument_data(partner_symbol, p_d1_slice, p_h1_slice, cfg)

            # Compute features
            features = calculate_all_features(inst_data, partner_data, cfg)

            # Score
            score = score_instrument(features, cfg, inst_data)

            # Compute outcomes (from future data — only used for evaluation, not features)
            atr14 = inst_data.atr14_d1
            open_T, outcome_1d, outcome_3d, label_1d = _compute_outcomes(
                d1_full, signal_ts, atr14
            )

            rows.append(BacktestRow(
                signal_date=T,
                symbol=symbol,
                features=features,
                score=score,
                bias_predicted=score.bias,
                outcome_1d=outcome_1d,
                outcome_3d=outcome_3d,
                label_1d=label_1d,
                open_T=open_T,
                atr14_at_T=atr14,
            ))

        logger.info(
            "BacktestEngine.run complete: %s — %d rows generated",
            symbol, len(rows),
        )
        return rows

    @staticmethod
    def _get_trading_days(
        d1_full: pd.DataFrame,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """Return trading days in [start_date, end_date] that exist in d1_full."""
        start_ts = pd.Timestamp(start_date, tz="UTC")
        end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
        mask = (d1_full.index >= start_ts) & (d1_full.index < end_ts)
        days_in_range = d1_full.index[mask]
        return [ts.date() for ts in days_in_range]
