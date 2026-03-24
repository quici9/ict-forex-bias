"""
Tests for V3 pattern scorer — Continuation-Only mode.

Ground truth (experiment log Round 6):
  BULLISH = High(T) > High(T-1) AND Low(T) > Low(T-1)
  BEARISH = High(T) < High(T-1) AND Low(T) < Low(T-1)
  NEUTRAL = everything else

V3 params:
  continuation_min_close_pct: 0.20
  reversal_mode: disabled
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from v2.pattern_scorer import (
    classify_d1_pattern,
    build_daily_bias,
    format_telegram_daily,
    DailyBias,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

# T-2 reference candle: range = 1.0 (simple numbers for easy math)
T2_HIGH = 1.10
T2_LOW  = 1.09    # range = 0.01
T2_RANGE = T2_HIGH - T2_LOW  # 0.01

# Threshold = 0.20 × 0.01 = 0.002
THRESHOLD = 0.2 * T2_RANGE


# ── classify_d1_pattern ────────────────────────────────────────────────────────

class TestClassifyD1Pattern:

    def test_inside_bar_is_neutral(self):
        pattern, direction = classify_d1_pattern(
            t1_high=T2_HIGH - 0.001,
            t1_low=T2_LOW + 0.001,
            t1_close=1.095,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )
        assert pattern == "INSIDE_BAR"
        assert direction == "NEUTRAL"

    def test_bullish_continuation(self):
        t1_close = T2_HIGH + THRESHOLD + 0.0001  # just above threshold
        pattern, direction = classify_d1_pattern(
            t1_high=t1_close + 0.001,
            t1_low=T2_LOW,
            t1_close=t1_close,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )
        assert pattern == "CONTINUATION"
        assert direction == "BULLISH"

    def test_bearish_continuation(self):
        t1_close = T2_LOW - THRESHOLD - 0.0001  # just below threshold
        pattern, direction = classify_d1_pattern(
            t1_high=T2_HIGH,
            t1_low=t1_close - 0.001,
            t1_close=t1_close,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )
        assert pattern == "CONTINUATION"
        assert direction == "BEARISH"

    def test_close_exactly_at_threshold_is_no_pattern(self):
        t1_close = T2_HIGH + THRESHOLD  # exactly at threshold (not strictly above)
        pattern, direction = classify_d1_pattern(
            t1_high=t1_close + 0.001,
            t1_low=T2_LOW,
            t1_close=t1_close,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )
        assert pattern == "NO_PATTERN"
        assert direction == "NEUTRAL"

    def test_no_pattern_close_inside_range(self):
        # t1 extends range but wick too small for reversal (< 0.4 × range = 0.004)
        # and close stays inside T-2 range so no continuation either
        pattern, direction = classify_d1_pattern(
            t1_high=T2_HIGH + 0.001,  # small extension, wick = 0.001 < threshold
            t1_low=T2_LOW - 0.001,    # small extension, wick = 0.001 < threshold
            t1_close=(T2_HIGH + T2_LOW) / 2,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )
        assert pattern == "NO_PATTERN"
        assert direction == "NEUTRAL"

    def test_zero_range_returns_no_pattern(self):
        pattern, direction = classify_d1_pattern(
            t1_high=1.10, t1_low=1.09, t1_close=1.095,
            t2_high=1.10, t2_low=1.10,  # zero range
        )
        assert pattern == "NO_PATTERN"
        assert direction == "NEUTRAL"

    def test_default_reversal_wick_pct_is_v3_value(self):
        """Default reversal_min_wick_pct must be 0.4 (V3 config, not 0.3)."""
        import inspect
        sig = inspect.signature(classify_d1_pattern)
        default = sig.parameters["reversal_min_wick_pct"].default
        assert default == 0.4, f"Expected 0.4 (V3 config), got {default}"


# ── build_daily_bias ──────────────────────────────────────────────────────────

class TestBuildDailyBias:
    TODAY = date(2026, 3, 24)

    def _bias(self, t1_close, t1_high=None, t1_low=None, symbol="EUR/USD"):
        if t1_high is None:
            t1_high = t1_close + 0.001
        if t1_low is None:
            t1_low = T2_LOW
        return build_daily_bias(
            symbol=symbol,
            prediction_date=self.TODAY,
            t1_high=t1_high,
            t1_low=t1_low,
            t1_close=t1_close,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )

    def test_bullish_continuation_emits_bullish(self):
        t1_close = T2_HIGH + THRESHOLD + 0.0001
        b = self._bias(t1_close)
        assert b.bias == "BULLISH"
        assert b.pattern == "CONTINUATION"
        assert b.confidence == "NORMAL"
        assert b.close_pct_beyond > 0

    def test_bearish_continuation_emits_bearish(self):
        t1_close = T2_LOW - THRESHOLD - 0.0001
        b = self._bias(t1_close, t1_high=T2_HIGH, t1_low=t1_close - 0.001)
        assert b.bias == "BEARISH"
        assert b.pattern == "CONTINUATION"
        assert b.close_pct_beyond > 0

    def test_reversal_signal_disabled_returns_neutral(self):
        # Classic reversal: T-1 sweeps below T-2 low, closes back inside range
        wick_pct = 0.4
        t1_low = T2_LOW - wick_pct * T2_RANGE - 0.0001
        t1_close = (T2_HIGH + T2_LOW) / 2  # closes back inside T-2 range
        b = self._bias(t1_close, t1_high=T2_HIGH - 0.001, t1_low=t1_low)
        assert b.bias == "NEUTRAL", "Reversal must be disabled in V3"
        assert b.pattern == "NONE"

    def test_inside_bar_returns_neutral(self):
        b = build_daily_bias(
            symbol="EUR/USD",
            prediction_date=self.TODAY,
            t1_high=T2_HIGH - 0.001,
            t1_low=T2_LOW + 0.001,
            t1_close=1.095,
            t2_high=T2_HIGH,
            t2_low=T2_LOW,
        )
        assert b.bias == "NEUTRAL"
        assert b.pattern == "NONE"

    def test_gbpjpy_continuation_is_low_confidence(self):
        t1_close = T2_HIGH + THRESHOLD + 0.0001
        b = self._bias(t1_close, symbol="GBP/JPY")
        assert b.bias == "BULLISH"
        assert b.confidence == "LOW"
        assert "GBP/JPY" in b.confidence_note

    def test_non_gbpjpy_is_normal_confidence(self):
        t1_close = T2_HIGH + THRESHOLD + 0.0001
        for sym in ["EUR/USD", "USD/JPY", "NZD/USD", "USD/CAD"]:
            b = self._bias(t1_close, symbol=sym)
            assert b.confidence == "NORMAL", f"{sym} should be NORMAL confidence"

    def test_close_pct_calculation(self):
        t1_close = T2_HIGH + 0.003  # 0.003 above T2_HIGH, range=0.01 → 30%
        b = self._bias(t1_close)
        assert b.bias == "BULLISH"
        assert abs(b.close_pct_beyond - 0.30) < 0.001

    def test_pattern_field_values_are_v3_only(self):
        """V3 DailyBias.pattern must be 'CONTINUATION' or 'NONE' — never 'REVERSAL'."""
        cases = [
            T2_HIGH + THRESHOLD + 0.001,  # continuation
            T2_HIGH - 0.001,              # inside-ish / no pattern
            T2_LOW + 0.001,               # inside-ish
        ]
        for t1_close in cases:
            b = self._bias(t1_close)
            assert b.pattern in ("CONTINUATION", "NONE"), (
                f"V3 pattern must be CONTINUATION or NONE, got {b.pattern!r}"
            )


# ── format_telegram_daily ─────────────────────────────────────────────────────

class TestFormatTelegramDaily:
    TODAY = date(2026, 3, 24)

    def _make_bias(self, symbol, bias, pct=0.25, confidence="NORMAL"):
        return DailyBias(
            symbol=symbol,
            date=self.TODAY,
            pattern="CONTINUATION" if bias != "NEUTRAL" else "NONE",
            bias=bias,
            confidence=confidence,
            confidence_note="GBP/JPY 50% precision (test set)" if confidence == "LOW" else "",
            t1_high=1.10, t1_low=1.09, t1_close=1.102,
            t2_high=1.10, t2_low=1.09,
            close_pct_beyond=pct,
            message="Bullish Continuation — Close +25% beyond High(T-2)",
        )

    def test_empty_list_returns_no_data(self):
        msg = format_telegram_daily([])
        assert "No data" in msg

    def test_all_neutral_returns_no_signals_message(self):
        biases = [self._make_bias("EUR/USD", "NEUTRAL")]
        msg = format_telegram_daily(biases)
        assert "No signals today" in msg

    def test_bullish_signal_present_in_output(self):
        biases = [self._make_bias("EUR/USD", "BULLISH", pct=0.30)]
        msg = format_telegram_daily(biases)
        assert "EUR/USD" in msg
        assert "BULLISH" in msg
        assert "Continuation" in msg

    def test_low_confidence_symbol_has_warning(self):
        biases = [self._make_bias("GBP/JPY", "BULLISH", confidence="LOW")]
        msg = format_telegram_daily(biases)
        assert "⚠️" in msg
        assert "GBP/JPY" in msg

    def test_top_picks_line_present(self):
        biases = [
            self._make_bias("EUR/USD", "BULLISH", pct=0.30),
            self._make_bias("USD/JPY", "BEARISH", pct=0.25),
        ]
        msg = format_telegram_daily(biases)
        assert "Top picks" in msg
        assert "64.8%" in msg

    def test_signals_sorted_by_close_pct_descending(self):
        biases = [
            self._make_bias("EUR/USD", "BULLISH", pct=0.20),
            self._make_bias("NZD/USD", "BULLISH", pct=0.45),
        ]
        msg = format_telegram_daily(biases)
        eur_pos = msg.index("EUR/USD")
        nzd_pos = msg.index("NZD/USD")
        assert nzd_pos < eur_pos, "Higher pct signal (NZD) should appear first"
