"""Data models — all dataclasses used across the pipeline.

Defined here first (Task 0.4) so every module imports from one place.
Feature and score fields reflect System Design Section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Data Pipeline layer
# ---------------------------------------------------------------------------

@dataclass
class InstrumentData:
    """Raw OHLCV data for one instrument after fetch + resample."""

    symbol: str
    d1: pd.DataFrame          # 60 candles daily OHLCV
    h4: pd.DataFrame          # 30 candles 4-hour (resampled from H1)
    h1: pd.DataFrame          # 72 candles 1-hour
    w1: pd.DataFrame          # 20 candles weekly (for W1 multiplier only)
    atr14_d1: float           # ATR(14) on D1, used for normalization
    is_valid: bool
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature Engine layer
# ---------------------------------------------------------------------------

@dataclass
class InstrumentFeatures:
    """All ICT-based features for one instrument after Feature Engine."""

    symbol: str

    # --- Market Structure ---
    d1_structure: Optional[float] = None         # [-1, 1] bearish/bullish
    d1_structure_clarity: Optional[float] = None # [0, 1]
    h4_structure: Optional[float] = None         # [-1, 1]
    structure_alignment: Optional[bool] = None   # D1 and H4 same direction
    bos_recent: Optional[bool] = None            # BOS in last N H4 candles
    choch_recent: Optional[bool] = None          # CHoCH in last N H4 candles

    # --- PD Arrays: Premium/Discount ---
    price_zone: Optional[float] = None           # [-1, 1] (1=discount, -1=premium)
    zone_strength: Optional[float] = None        # [0, 1]

    # --- PD Arrays: Fair Value Gap ---
    fvg_exists_h4: Optional[bool] = None
    fvg_direction_h4: Optional[float] = None     # [-1, 1]
    fvg_size_h4: Optional[float] = None          # [0, 1] normalized by ATR
    fvg_exists_h1: Optional[bool] = None
    fvg_direction_h1: Optional[float] = None     # [-1, 1]

    # --- PD Arrays: Previous Day High/Low ---
    near_pdh: Optional[bool] = None
    near_pdl: Optional[bool] = None
    swept_pdh: Optional[bool] = None
    swept_pdl: Optional[bool] = None

    # --- Liquidity ---
    sweep_occurred: Optional[bool] = None
    sweep_direction: Optional[float] = None      # [-1, 1]
    sweep_age: Optional[int] = None              # candles since sweep [0, 10]

    # --- SMT Divergence ---
    smt_signal: Optional[bool] = None
    smt_direction: Optional[float] = None        # [-1, 1]
    smt_timeframe: Optional[str] = None          # "D1" | "H4"

    # --- Meta (for scoring) ---
    w1_direction: Optional[float] = None         # [-1, 1] weekly trend
    atr14_d1: Optional[float] = None


# ---------------------------------------------------------------------------
# Scoring layer
# ---------------------------------------------------------------------------

@dataclass
class InstrumentScore:
    """Scoring result for one instrument."""

    symbol: str
    bias: str                       # BULLISH | BEARISH | WATCHLIST | NEUTRAL | LOW_VOL | ERROR
    score: int                      # [0, 100]
    bullish_score: float            # raw hypothesis score before final_score
    bearish_score: float
    w1_multiplier: float            # 0.75 | 0.9 | 1.0
    is_counter_trend: bool
    is_low_vol: bool
    top_signals: list[str]          # max 4 human-readable signal strings
    features: Optional[InstrumentFeatures] = None


# ---------------------------------------------------------------------------
# Run result (persistence layer)
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Wrapper for a complete pipeline execution — persisted to history.json."""

    run_id: str                     # ISO timestamp of scheduled trigger
    session: str                    # "london" | "new_york"
    timestamp_utc: str              # ISO timestamp when run completed
    instruments: list[InstrumentScore]
    top_pick: Optional[str]         # symbol of highest scoring instrument
    duration_seconds: float
    errors: list[str] = field(default_factory=list)
