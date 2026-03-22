"""
H1 Market Structure Detector.
BOS, CHoCH, FVG zones, Order Blocks — all distances ATR14-normalized
for cross-symbol comparability (JPY pairs vs non-JPY).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class FVGZone:
    direction:  str    # "BULLISH" | "BEARISH"
    high:       float  # top of gap
    low:        float  # bottom of gap
    midpoint:   float  # (high + low) / 2
    candle_idx: int    # middle candle of the 3-candle pattern
    filled:     bool   # True if price has traded through
    size_atr:   float  # gap size / ATR14


@dataclass
class OrderBlock:
    direction:   str    # "BULLISH" | "BEARISH"
    ob_high:     float
    ob_low:      float
    ob_midpoint: float
    bos_level:   float  # swing price that created this OB
    candle_idx:  int
    tested:      bool   # True if price has retested the OB
    size_atr:    float


@dataclass
class StructurePoint:
    type:           str    # "BOS_BULL"|"BOS_BEAR"|"CHOCH_BULL"|"CHOCH_BEAR"
    level:          float  # swing price that was broken
    candle_idx:     int    # candle where break was confirmed
    swing_size_atr: float  # swing range / ATR14


# ── ATR14 ─────────────────────────────────────────────────────────────────────

def compute_atr14(df: pd.DataFrame) -> float:
    """ATR14 using True Range over the last 14 periods."""
    tail = df.tail(15)
    if len(tail) < 2:
        return float((df["High"] - df["Low"]).mean()) or 0.0001
    h, l, c = tail["High"].values, tail["Low"].values, tail["Close"].values
    tr = [
        max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        for i in range(1, len(h))
    ]
    return float(np.mean(tr[-14:])) or 0.0001


# ── Swing Points ──────────────────────────────────────────────────────────────

def find_swing_points(
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int = 2,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing highs and lows as (index, price) pairs."""
    n, sh, sl = len(highs), [], []
    for i in range(lookback, n - lookback):
        if highs[i] == max(highs[i - lookback: i + lookback + 1]):
            sh.append((i, float(highs[i])))
        if lows[i] == min(lows[i - lookback: i + lookback + 1]):
            sl.append((i, float(lows[i])))
    return sh, sl


# ── BOS ───────────────────────────────────────────────────────────────────────

def find_latest_bos(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    atr14: float,
) -> Optional[StructurePoint]:
    """Most recently confirmed BOS (bull or bear), or None."""
    n = len(closes)
    events: list[StructurePoint] = []

    for sh_idx, sh_price in swing_highs:
        for k in range(sh_idx + 1, n):
            if closes[k] > sh_price:
                sz = (sh_price - lows[sh_idx]) / atr14
                events.append(StructurePoint("BOS_BULL", sh_price, k, round(sz, 3)))
                break

    for sl_idx, sl_price in swing_lows:
        for k in range(sl_idx + 1, n):
            if closes[k] < sl_price:
                sz = (highs[sl_idx] - sl_price) / atr14
                events.append(StructurePoint("BOS_BEAR", sl_price, k, round(sz, 3)))
                break

    return max(events, key=lambda x: x.candle_idx) if events else None


# ── CHoCH ─────────────────────────────────────────────────────────────────────

def find_latest_choch(
    closes: np.ndarray,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    atr14: float,
) -> Optional[StructurePoint]:
    """CHoCH against the established trend, or None."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None
    n = len(closes)
    _, sh1      = swing_highs[-2]
    sh2_idx, sh2 = swing_highs[-1]
    _, sl1      = swing_lows[-2]
    sl2_idx, sl2 = swing_lows[-1]
    start = max(sh2_idx, sl2_idx) + 1

    if sh2 > sh1 and sl2 > sl1:          # uptrend → watch for bearish CHoCH
        for k in range(start, n):
            if closes[k] < sl1:
                return StructurePoint("CHOCH_BEAR", sl1, k, round((sh2 - sl1) / atr14, 3))

    elif sh2 < sh1 and sl2 < sl1:        # downtrend → watch for bullish CHoCH
        for k in range(start, n):
            if closes[k] > sh1:
                return StructurePoint("CHOCH_BULL", sh1, k, round((sh1 - sl2) / atr14, 3))

    return None


# ── Trend Direction ───────────────────────────────────────────────────────────

def detect_trend(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> tuple[str, int, int]:
    """(trend_direction, hh_count, ll_count). UP / DOWN / RANGING."""
    sh_p = [p for _, p in swing_highs]
    sl_p = [p for _, p in swing_lows]
    hh = sum(1 for i in range(1, len(sh_p)) if sh_p[i] > sh_p[i - 1])
    lh = (len(sh_p) - 1) - hh
    hl = sum(1 for i in range(1, len(sl_p)) if sl_p[i] > sl_p[i - 1])
    ll = (len(sl_p) - 1) - hl
    if hh >= 2 and hl >= 2:
        return "UP", hh, ll
    if lh >= 2 and ll >= 2:
        return "DOWN", hh, ll
    return "RANGING", hh, ll


# ── FVG Zones ─────────────────────────────────────────────────────────────────

def detect_fvg_zones(
    df: pd.DataFrame,
    atr14: float,
) -> tuple[list[FVGZone], list[FVGZone]]:
    """All 3-candle FVG zones (including filled). Returns (bull_fvgs, bear_fvgs)."""
    h, l = df["High"].values, df["Low"].values
    n = len(h)
    bulls: list[FVGZone] = []
    bears: list[FVGZone] = []

    for i in range(n - 2):
        ah, al = h[i], l[i]
        ch, cl = h[i + 2], l[i + 2]

        if cl > ah:   # bull FVG: gap between candle A high and candle C low
            filled = any(l[j] <= ah for j in range(i + 2, n))
            sz = (cl - ah) / atr14
            bulls.append(FVGZone(
                "BULLISH", round(float(cl), 5), round(float(ah), 5),
                round(float((ah + cl) / 2), 5), i + 1, filled, round(sz, 3),
            ))

        if ch < al:   # bear FVG: gap between candle A low and candle C high
            filled = any(h[j] >= al for j in range(i + 2, n))
            sz = (al - ch) / atr14
            bears.append(FVGZone(
                "BEARISH", round(float(al), 5), round(float(ch), 5),
                round(float((al + ch) / 2), 5), i + 1, filled, round(sz, 3),
            ))

    return bulls, bears


# ── Order Blocks ──────────────────────────────────────────────────────────────

def detect_order_blocks(
    df: pd.DataFrame,
    atr14: float,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> tuple[list[OrderBlock], list[OrderBlock]]:
    """OBs formed at confirmed BOS swings. Returns (bull_obs, bear_obs)."""
    opens  = df["Open"].values if "Open" in df.columns else df["Close"].values
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    n = len(c)
    bulls: list[OrderBlock] = []
    bears: list[OrderBlock] = []

    for sh_idx, sh_price in swing_highs:
        if not any(c[k] > sh_price for k in range(sh_idx + 1, n)):
            continue
        for j in range(sh_idx, -1, -1):
            if c[j] < opens[j]:   # last bearish candle before swing → bull OB
                sz = (h[j] - l[j]) / atr14
                tested = any(l[k] <= h[j] and h[k] >= l[j] for k in range(j + 1, n))
                bulls.append(OrderBlock(
                    "BULLISH", round(float(h[j]), 5), round(float(l[j]), 5),
                    round(float((h[j] + l[j]) / 2), 5),
                    round(float(sh_price), 5), j, tested, round(sz, 3),
                ))
                break

    for sl_idx, sl_price in swing_lows:
        if not any(c[k] < sl_price for k in range(sl_idx + 1, n)):
            continue
        for j in range(sl_idx, -1, -1):
            if c[j] > opens[j]:   # last bullish candle before swing → bear OB
                sz = (h[j] - l[j]) / atr14
                tested = any(l[k] <= h[j] and h[k] >= l[j] for k in range(j + 1, n))
                bears.append(OrderBlock(
                    "BEARISH", round(float(h[j]), 5), round(float(l[j]), 5),
                    round(float((h[j] + l[j]) / 2), 5),
                    round(float(sl_price), 5), j, tested, round(sz, 3),
                ))
                break

    return bulls, bears
