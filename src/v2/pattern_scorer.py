"""
ICT Forex Bias System — Final Pattern Scorer
Continuation-Only mode with confidence tiers.
Reversal signals DISABLED (35% precision, sub-random).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
import numpy as np


# ── Configuration ─────────────────────────────────────────────────────────────

LOW_CONFIDENCE_SYMBOLS = frozenset(["GBP/JPY"])
LOW_CONFIDENCE_NOTE = "GBP/JPY 50% precision (test set)"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class DailyBias:
    """Final production DailyBias — Continuation-Only mode."""
    symbol: str
    date: date
    pattern: str            # CONTINUATION | NONE
    bias: str               # BULLISH | BEARISH | NEUTRAL
    confidence: str         # NORMAL | LOW
    confidence_note: str    # "" or warning text
    t1_high: float
    t1_low: float
    t1_close: float
    t2_high: float
    t2_low: float
    close_pct_beyond: float  # how far close exceeded T-2 range
    message: str             # human-readable explanation


@dataclass
class SessionSignal:
    symbol: str
    session: str          # London | NY
    d1_bias: str          # BULLISH | BEARISH
    signal: str           # CONFIRM | WARN | FLIP | NO_SIGNAL
    bos: Optional[str]    # BULLISH | BEARISH | None
    choch: Optional[str]  # BULLISH | BEARISH | None
    fvg_levels: list[float] = field(default_factory=list)
    message: str = ""


# ── D1 Pattern Logic ──────────────────────────────────────────────────────────

def classify_d1_pattern(
    t1_high: float,
    t1_low: float,
    t1_close: float,
    t2_high: float,
    t2_low: float,
    reversal_min_wick_pct: float = 0.3,
    continuation_min_close_pct: float = 0.2,
    t1_open: float | None = None,
    reversal_body_ratio: float = 0.0,
) -> tuple[str, str]:
    """
    Classify D1 pattern for prediction day T using T-1 and T-2 candles.
    Returns (pattern_type, direction).
    Check order: InsideBar → Reversal → Continuation → NoPattern.

    reversal_body_ratio: if > 0, reversal only valid when
        body/range of T-1 <= threshold (wick-dominant rejection).
        0.0 = no filter, 0.3 = body must be < 30% of range.
    """
    t2_range = t2_high - t2_low
    if t2_range <= 0:
        return "NO_PATTERN", "NEUTRAL"

    # ① Inside Bar
    if t1_high < t2_high and t1_low > t2_low:
        return "INSIDE_BAR", "NEUTRAL"

    wick_threshold = reversal_min_wick_pct * t2_range

    # ② Reversal with optional body_ratio filter
    is_reversal_bull = t1_low < t2_low - wick_threshold and t2_low < t1_close < t2_high
    is_reversal_bear = t1_high > t2_high + wick_threshold and t2_low < t1_close < t2_high

    if is_reversal_bull or is_reversal_bear:
        # Apply body_ratio filter if enabled
        passes_body_filter = True
        if reversal_body_ratio > 0 and t1_open is not None:
            t1_range = t1_high - t1_low
            if t1_range > 0:
                body = abs(t1_close - t1_open)
                body_ratio = body / t1_range
                passes_body_filter = body_ratio <= reversal_body_ratio

        if passes_body_filter:
            if is_reversal_bull:
                return "REVERSAL", "BULLISH"
            return "REVERSAL", "BEARISH"

    close_threshold = continuation_min_close_pct * t2_range

    # ③ Continuation
    if t1_close > t2_high + close_threshold:
        return "CONTINUATION", "BULLISH"
    if t1_close < t2_low - close_threshold:
        return "CONTINUATION", "BEARISH"

    return "NO_PATTERN", "NEUTRAL"


def build_daily_bias(
    symbol: str,
    prediction_date: date,
    t1_high: float,
    t1_low: float,
    t1_close: float,
    t2_high: float,
    t2_low: float,
    continuation_min_close_pct: float = 0.2,
) -> DailyBias:
    """Build DailyBias in Continuation-Only mode.

    Reversal patterns are classified but then downgraded to NEUTRAL.
    Only CONTINUATION signals are emitted as directional.
    """
    # Classify raw pattern (reversal logic still runs for logging)
    raw_pattern, raw_bias = classify_d1_pattern(
        t1_high, t1_low, t1_close,
        t2_high, t2_low,
        reversal_min_wick_pct=0.4,
        continuation_min_close_pct=continuation_min_close_pct,
    )

    # Continuation-Only: disable reversal signals
    if raw_pattern == "CONTINUATION":
        pattern = "CONTINUATION"
        bias = raw_bias
    else:
        pattern = "NONE"
        bias = "NEUTRAL"

    # Compute close_pct_beyond for continuation strength
    t2_range = t2_high - t2_low
    close_pct = 0.0
    if pattern == "CONTINUATION" and t2_range > 0:
        if bias == "BULLISH":
            close_pct = (t1_close - t2_high) / t2_range
        elif bias == "BEARISH":
            close_pct = (t2_low - t1_close) / t2_range

    # Confidence tier
    confidence = "NORMAL"
    confidence_note = ""
    if symbol in LOW_CONFIDENCE_SYMBOLS and bias != "NEUTRAL":
        confidence = "LOW"
        confidence_note = LOW_CONFIDENCE_NOTE

    message = _build_d1_message(pattern, bias, t1_close, t2_high, t2_low, close_pct)

    return DailyBias(
        symbol=symbol,
        date=prediction_date,
        pattern=pattern,
        bias=bias,
        confidence=confidence,
        confidence_note=confidence_note,
        t1_high=t1_high,
        t1_low=t1_low,
        t1_close=t1_close,
        t2_high=t2_high,
        t2_low=t2_low,
        close_pct_beyond=round(close_pct, 4),
        message=message,
    )


def _build_d1_message(
    pattern: str,
    bias: str,
    t1_close: float,
    t2_high: float,
    t2_low: float,
    close_pct: float,
) -> str:
    """Human-readable explanation of the daily bias."""
    if pattern == "CONTINUATION" and bias == "BULLISH":
        return f"Bullish Continuation — Close +{close_pct:.0%} beyond High(T-2)"
    if pattern == "CONTINUATION" and bias == "BEARISH":
        return f"Bearish Continuation — Close −{close_pct:.0%} below Low(T-2)"
    return "No actionable signal."


def format_telegram_daily(biases: list[DailyBias]) -> str:
    """Format a list of DailyBias into Telegram message.

    Sort order:
      1. HIGH confidence signals (by close_pct_beyond descending)
      2. LOW confidence signals
      3. NEUTRAL signals are omitted
    """
    if not biases:
        return "📅 No data available."

    ref_date = biases[0].date
    weekday = ref_date.strftime("%a")
    date_str = ref_date.strftime("%d %b %Y")

    active = [b for b in biases if b.bias != "NEUTRAL"]

    if not active:
        return (
            f"📅 *Daily Bias — {weekday} {date_str}*\n"
            f"──────────────────────────────────\n"
            f"📊 No signals today — all pairs neutral"
        )

    normal = sorted(
        [b for b in active if b.confidence == "NORMAL"],
        key=lambda b: b.close_pct_beyond,
        reverse=True,
    )
    low = [b for b in active if b.confidence == "LOW"]

    emoji_map = {
        ("BULLISH", "NORMAL"): "🟢",
        ("BEARISH", "NORMAL"): "🔴",
        ("BULLISH", "LOW"): "🟡",
        ("BEARISH", "LOW"): "🟠",
    }

    lines = [
        f"📅 *Daily Bias — {weekday} {date_str}*",
        "──────────────────────────────────",
    ]

    for b in normal:
        emoji = emoji_map.get((b.bias, b.confidence), "⬜")
        pct_str = f"+{b.close_pct_beyond:.0%}" if b.bias == "BULLISH" else f"−{b.close_pct_beyond:.0%}"
        lines.append(f"{emoji} {b.symbol}  {b.bias}  `[Continuation]`")
        lines.append(f"   Close {pct_str} beyond {'High' if b.bias == 'BULLISH' else 'Low'}(T-2)")

    if low:
        lines.append("──────────────────────────────────")
        for b in low:
            emoji = emoji_map.get((b.bias, b.confidence), "⬜")
            pct_str = f"+{b.close_pct_beyond:.0%}" if b.bias == "BULLISH" else f"−{b.close_pct_beyond:.0%}"
            lines.append(f"{emoji} {b.symbol}  {b.bias}  `[Continuation]` ⚠️")
            lines.append(f"   ⚠️ {b.confidence_note}")
            lines.append(f"   Close {pct_str} beyond {'High' if b.bias == 'BULLISH' else 'Low'}(T-2)")

    lines.append("──────────────────────────────────")

    # Top picks: top 3 normal signals
    top = [b.symbol for b in normal[:3]]
    if top:
        lines.append(f"🎯 *Top picks*: {', '.join(top)}")
        lines.append("   Continuation • 64.8% precision")

    return "\n".join(lines)


# ── H1 Market Structure ───────────────────────────────────────────────────────

def _find_swing_points(
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []
    n = len(highs)

    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback: i + lookback + 1]
        if highs[i] == max(window_h):
            swing_highs.append((i, float(highs[i])))

        window_l = lows[i - lookback: i + lookback + 1]
        if lows[i] == min(window_l):
            swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


def _detect_bos_choch(
    closes: np.ndarray,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> tuple[Optional[str], Optional[str]]:
    bos_dir: Optional[str] = None
    choch_dir: Optional[str] = None

    if not swing_highs or not swing_lows:
        return None, None

    last_sh_idx, last_sh_price = swing_highs[-1]
    last_sl_idx, last_sl_price = swing_lows[-1]
    n = len(closes)

    for i in range(last_sh_idx + 1, n):
        if closes[i] > last_sh_price:
            bos_dir = "BULLISH"
            break

    for i in range(last_sl_idx + 1, n):
        if closes[i] < last_sl_price:
            bos_dir = "BEARISH"
            break

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        _, sh1 = swing_highs[-2]
        sh2_idx, sh2 = swing_highs[-1]
        _, sl1 = swing_lows[-2]
        sl2_idx, sl2 = swing_lows[-1]

        if sh2 > sh1 and sl2 > sl1:  # uptrend — watch for bearish CHoCH
            for i in range(max(sh2_idx, sl2_idx) + 1, n):
                if closes[i] < sl1:
                    choch_dir = "BEARISH"
                    break
        elif sh2 < sh1 and sl2 < sl1:  # downtrend — watch for bullish CHoCH
            for i in range(max(sh2_idx, sl2_idx) + 1, n):
                if closes[i] > sh1:
                    choch_dir = "BULLISH"
                    break

    return bos_dir, choch_dir


def _detect_fvg(
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int,
) -> tuple[list[float], list[float]]:
    n = len(highs)
    start = max(0, n - lookback - 2)
    bull_levels: list[float] = []
    bear_levels: list[float] = []

    for i in range(start, n - 2):
        a_high, a_low = highs[i], lows[i]
        c_high, c_low = highs[i + 2], lows[i + 2]

        if c_low > a_high:
            filled = any(lows[j] <= a_high for j in range(i + 2, n))
            if not filled:
                bull_levels.append(float((a_high + c_low) / 2))

        if c_high < a_low:
            filled = any(highs[j] >= a_low for j in range(i + 2, n))
            if not filled:
                bear_levels.append(float((a_low + c_high) / 2))

    return bull_levels, bear_levels


def compute_session_signal(
    df_h1_context: pd.DataFrame,
    d1_bias: str,
    swing_lookback: int = 2,
    fvg_lookback: int = 8,
) -> SessionSignal:
    """
    Compute H1 session signal from context candles.
    df_h1_context: H1 candles before the session (look-ahead free).
    Returns a SessionSignal (caller fills symbol/session fields).
    """
    _empty = SessionSignal(
        symbol="", session="", d1_bias=d1_bias,
        signal="NO_SIGNAL", bos=None, choch=None,
    )

    if len(df_h1_context) < swing_lookback * 2 + 1:
        return _empty

    highs = df_h1_context["High"].values
    lows = df_h1_context["Low"].values
    closes = df_h1_context["Close"].values

    swing_highs, swing_lows = _find_swing_points(highs, lows, lookback=swing_lookback)

    if not swing_highs or not swing_lows:
        return _empty

    bos_dir, choch_dir = _detect_bos_choch(closes, swing_highs, swing_lows)
    bull_fvgs, bear_fvgs = _detect_fvg(highs, lows, lookback=fvg_lookback)

    last_close = float(closes[-1])
    fvg_aligned = False
    fvg_levels: list[float] = []

    if d1_bias == "BULLISH" and bull_fvgs:
        fvg_aligned = any(abs(last_close - lvl) / last_close < 0.002 for lvl in bull_fvgs)
        fvg_levels = bull_fvgs
    elif d1_bias == "BEARISH" and bear_fvgs:
        fvg_aligned = any(abs(last_close - lvl) / last_close < 0.002 for lvl in bear_fvgs)
        fvg_levels = bear_fvgs

    if d1_bias == "BULLISH":
        if choch_dir == "BEARISH":
            signal = "FLIP"
        elif bos_dir == "BULLISH" or choch_dir == "BULLISH" or fvg_aligned:
            signal = "CONFIRM"
        elif bos_dir == "BEARISH":
            signal = "WARN"
        else:
            signal = "NO_SIGNAL"
    elif d1_bias == "BEARISH":
        if choch_dir == "BULLISH":
            signal = "FLIP"
        elif bos_dir == "BEARISH" or choch_dir == "BEARISH" or fvg_aligned:
            signal = "CONFIRM"
        elif bos_dir == "BULLISH":
            signal = "WARN"
        else:
            signal = "NO_SIGNAL"
    else:
        signal = "NO_SIGNAL"

    return SessionSignal(
        symbol="", session="",
        d1_bias=d1_bias,
        signal=signal,
        bos=bos_dir,
        choch=choch_dir,
        fvg_levels=fvg_levels,
    )


# ── Telegram Formatter ────────────────────────────────────────────────────────

_BIAS_EMOJI = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⬜"}
_SIGNAL_EMOJI = {"CONFIRM": "✅", "WARN": "⚠️", "FLIP": "🔄", "NO_SIGNAL": "➖"}
_PATTERN_LABEL = {
    "REVERSAL": "Reversal",
    "CONTINUATION": "Continuation",
    "INSIDE_BAR": "Inside Bar",
    "NO_PATTERN": "No Pattern",
}


def format_daily_bias_message(
    biases: list[DailyBias],
    report_date: date,
) -> str:
    """Format the daily D1 bias report for Telegram."""
    day_str = report_date.strftime("%a %d %b %Y")
    lines = [
        f"📅 *Daily Bias — {day_str}*",
        "──────────────────────────────────",
    ]

    directional = [b for b in biases if b.bias != "NEUTRAL"]
    neutral = [b for b in biases if b.bias == "NEUTRAL"]

    for b in sorted(directional, key=lambda x: x.symbol):
        emoji = _BIAS_EMOJI[b.bias]
        pat = _PATTERN_LABEL[b.pattern]
        lines.append(f"{emoji} {b.symbol:<10} {b.bias:<8} `[{pat}]`")
        lines.append(f"   {b.message}")

    for b in sorted(neutral, key=lambda x: x.symbol):
        emoji = _BIAS_EMOJI[b.bias]
        pat = _PATTERN_LABEL[b.pattern]
        lines.append(f"{emoji} {b.symbol:<10} {b.bias:<8} `[{pat}]`")

    # Top pick: prefer REVERSAL > CONTINUATION, then directional only
    reversals = [b for b in directional if b.pattern == "REVERSAL"]
    top_pick = reversals[0] if reversals else (directional[0] if directional else None)

    lines.append("──────────────────────────────────")
    if top_pick:
        pat = _PATTERN_LABEL[top_pick.pattern]
        lines.append(
            f"🎯 *Top pick:* {top_pick.symbol} — {pat} pattern, "
            f"{top_pick.bias.lower()} bias"
        )
    else:
        lines.append("🎯 *Top pick:* No directional signals today")

    return "\n".join(lines)


def format_session_message(
    signals: list[SessionSignal],
    session: str,
    utc_time: str,
) -> str:
    """Format the pre-session H1 confirmation message for Telegram."""
    lines = [
        f"🕐 *Pre-{session} — {utc_time} UTC*",
        "──────────────────────────────────",
    ]

    for sig in sorted(signals, key=lambda x: x.symbol):
        emoji = _SIGNAL_EMOJI.get(sig.signal, "➖")
        fvg_str = ""
        if sig.fvg_levels:
            lvl = sig.fvg_levels[0]
            fvg_str = f" + FVG @ {lvl:.5f}"

        lines.append(
            f"{emoji} {sig.symbol:<10} {sig.signal} {sig.d1_bias}{fvg_str}"
        )
        if sig.message:
            lines.append(f"   {sig.message}")

    lines.append("──────────────────────────────────")
    return "\n".join(lines)
