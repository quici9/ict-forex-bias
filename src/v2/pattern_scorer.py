"""
ICT Forex Bias System — Final Pattern Scorer
Continuation-Only mode with confidence tiers.
Reversal signals DISABLED (35% precision, sub-random).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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


# ── D1 Pattern Logic ──────────────────────────────────────────────────────────

def classify_d1_pattern(
    t1_high: float,
    t1_low: float,
    t1_close: float,
    t2_high: float,
    t2_low: float,
    reversal_min_wick_pct: float = 0.4,
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
