"""
H1 Confidence Scorer — context enrichment layer.
H1 score does NOT affect DailyBias, precision tracking, or evaluate_v2.py.
Raw features are stored in full for future ML training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import pandas as pd

from v2.h1_detector import (
    FVGZone, OrderBlock, StructurePoint,
    compute_atr14, find_swing_points,
    find_latest_bos, find_latest_choch,
    detect_trend, detect_fvg_zones, detect_order_blocks,
)

if TYPE_CHECKING:
    from v2.pattern_scorer import DailyBias

MIN_CANDLES = 6


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class H1RawFeatures:
    """Complete raw features — stored for future ML training. Never filtered."""
    symbol:          str
    session:         str       # "London" | "NY"
    timestamp:       str       # ISO UTC
    d1_bias:         str       # BULLISH | BEARISH | NEUTRAL
    d1_pattern:      str       # CONTINUATION | NONE
    d1_close_pct:    float

    h1_candles_used: int
    current_price:   float
    atr14:           float

    latest_bos:      Optional[StructurePoint]
    latest_choch:    Optional[StructurePoint]
    trend_direction: str       # "UP" | "DOWN" | "RANGING"
    hh_count:        int
    ll_count:        int

    nearest_bull_fvg: Optional[FVGZone]
    nearest_bear_fvg: Optional[FVGZone]
    price_in_fvg:     bool
    fvg_count_bull:   int
    fvg_count_bear:   int

    nearest_bull_ob:  Optional[OrderBlock]
    nearest_bear_ob:  Optional[OrderBlock]
    price_near_ob:    bool     # aligned OB midpoint within 1×ATR14

    bos_aligned:      Optional[bool]
    fvg_aligned:      Optional[bool]
    ob_aligned:       Optional[bool]
    aligned_count:    int      # 0–3
    counter_count:    int      # 0–3


@dataclass
class H1Confidence:
    """Scored output for display and logging."""
    symbol:          str
    session:         str
    d1_bias:         str
    score:           int         # 0–100
    grade:           str         # A / B / C / D / N/A
    raw:             H1RawFeatures
    display_lines:   list[str] = field(default_factory=list)
    score_breakdown: dict     = field(default_factory=dict)
    # base + bos + fvg + ob + trend + raw_total keys


# ── Internal helpers ──────────────────────────────────────────────────────────

def _nearest_fvg(zones: list[FVGZone], price: float) -> Optional[FVGZone]:
    return min(zones, key=lambda f: abs(f.midpoint - price)) if zones else None


def _nearest_ob(obs: list[OrderBlock], price: float) -> Optional[OrderBlock]:
    return min(obs, key=lambda o: abs(o.ob_midpoint - price)) if obs else None


def _is_aligned(item_dir: Optional[str], d1_bias: str) -> Optional[bool]:
    if item_dir is None or d1_bias == "NEUTRAL":
        return None
    return item_dir == d1_bias


# ── Feature collection helpers ────────────────────────────────────────────────

def _collect_structure(
    df: pd.DataFrame, atr14: float,
) -> tuple:
    """Returns (sh, sl, bos, choch, trend, hh, ll)."""
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    sh, sl = find_swing_points(h, l, lookback=2)
    bos   = find_latest_bos(h, l, c, sh, sl, atr14)
    choch = find_latest_choch(c, sh, sl, atr14)
    trend, hh, ll = detect_trend(sh, sl)
    return sh, sl, bos, choch, trend, hh, ll


def _collect_fvg(
    df: pd.DataFrame, price: float, atr14: float,
) -> tuple[Optional[FVGZone], Optional[FVGZone], bool, int, int]:
    """Returns (nearest_bull_fvg, nearest_bear_fvg, price_in_fvg, count_bull, count_bear)."""
    bulls, bears = detect_fvg_zones(df, atr14)
    uf_bulls = [f for f in bulls if not f.filled]
    uf_bears = [f for f in bears if not f.filled]
    nb    = _nearest_fvg(uf_bulls, price)
    nbear = _nearest_fvg(uf_bears, price)
    in_fvg = (
        (nb    is not None and nb.low    <= price <= nb.high) or
        (nbear is not None and nbear.low <= price <= nbear.high)
    )
    return nb, nbear, in_fvg, len(uf_bulls), len(uf_bears)


def _collect_ob(
    df: pd.DataFrame, atr14: float,
    sh: list, sl: list, price: float,
) -> tuple[Optional[OrderBlock], Optional[OrderBlock]]:
    """Returns (nearest_bull_ob, nearest_bear_ob)."""
    bull_obs, bear_obs = detect_order_blocks(df, atr14, sh, sl)
    return _nearest_ob(bull_obs, price), _nearest_ob(bear_obs, price)


def _compute_alignment(
    d1_bias: str,
    bos: Optional[StructurePoint],
    nb_fvg: Optional[FVGZone],
    nbear_fvg: Optional[FVGZone],
    nb_ob: Optional[OrderBlock],
    nbear_ob: Optional[OrderBlock],
    price: float,
    atr14: float,
) -> tuple[Optional[bool], Optional[bool], Optional[bool], int, int, bool]:
    """Returns (bos_al, fvg_al, ob_al, aligned_count, counter_count, price_near_ob)."""
    bos_dir = ("BULLISH" if bos and "BULL" in bos.type else
               "BEARISH" if bos else None)
    bos_al = _is_aligned(bos_dir, d1_bias)

    if d1_bias == "BULLISH":
        fvg_al = (True if nb_fvg else False if nbear_fvg else None)
        ob_al  = (True if nb_ob  else False if nbear_ob  else None)
        aligned_ob = nb_ob
    elif d1_bias == "BEARISH":
        fvg_al = (True if nbear_fvg else False if nb_fvg else None)
        ob_al  = (True if nbear_ob  else False if nb_ob  else None)
        aligned_ob = nbear_ob
    else:
        return None, None, None, 0, 0, False

    near_ob = (
        aligned_ob is not None and
        abs(price - aligned_ob.ob_midpoint) / atr14 <= 1.0
    )
    al_cnt = sum(1 for x in [bos_al, fvg_al, ob_al] if x is True)
    ct_cnt = sum(1 for x in [bos_al, fvg_al, ob_al] if x is False)
    return bos_al, fvg_al, ob_al, al_cnt, ct_cnt, near_ob


# ── Build raw features ────────────────────────────────────────────────────────

def _build_raw_features(
    df: pd.DataFrame,
    symbol: str,
    session: str,
    d1_bias: str,
    d1_pattern: str,
    d1_close_pct: float,
    timestamp: str,
) -> H1RawFeatures:
    atr14 = compute_atr14(df)
    price = float(df["Close"].values[-1])
    sh, sl, bos, choch, trend, hh, ll = _collect_structure(df, atr14)
    nb_fvg, nbear_fvg, in_fvg, cnt_bull, cnt_bear = _collect_fvg(df, price, atr14)
    nb_ob, nbear_ob = _collect_ob(df, atr14, sh, sl, price)
    bos_al, fvg_al, ob_al, al_cnt, ct_cnt, near_ob = _compute_alignment(
        d1_bias, bos, nb_fvg, nbear_fvg, nb_ob, nbear_ob, price, atr14,
    )
    return H1RawFeatures(
        symbol=symbol, session=session, timestamp=timestamp,
        d1_bias=d1_bias, d1_pattern=d1_pattern, d1_close_pct=d1_close_pct,
        h1_candles_used=len(df), current_price=round(price, 5), atr14=round(atr14, 5),
        latest_bos=bos, latest_choch=choch, trend_direction=trend, hh_count=hh, ll_count=ll,
        nearest_bull_fvg=nb_fvg, nearest_bear_fvg=nbear_fvg, price_in_fvg=in_fvg,
        fvg_count_bull=cnt_bull, fvg_count_bear=cnt_bear,
        nearest_bull_ob=nb_ob, nearest_bear_ob=nbear_ob, price_near_ob=near_ob,
        bos_aligned=bos_al, fvg_aligned=fvg_al, ob_aligned=ob_al,
        aligned_count=al_cnt, counter_count=ct_cnt,
    )


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_bos_choch(raw: H1RawFeatures) -> int:
    """BOS/CHoCH component, weight 35."""
    if raw.d1_bias == "NEUTRAL":
        return 0
    choch = raw.latest_choch
    if choch is not None:
        choch_dir = "BULLISH" if "BULL" in choch.type else "BEARISH"
        if choch_dir != raw.d1_bias:
            return -20
    if raw.latest_bos is None:
        return 0
    bos_dir = "BULLISH" if "BULL" in raw.latest_bos.type else "BEARISH"
    return 35 if bos_dir == raw.d1_bias else -15


def _score_fvg(raw: H1RawFeatures) -> int:
    """FVG component, weight 25. Uses aligned-direction FVG only."""
    if raw.d1_bias == "NEUTRAL":
        return 0
    aligned = raw.nearest_bull_fvg if raw.d1_bias == "BULLISH" else raw.nearest_bear_fvg
    counter = raw.nearest_bear_fvg if raw.d1_bias == "BULLISH" else raw.nearest_bull_fvg
    if aligned is not None and not aligned.filled:
        if aligned.low <= raw.current_price <= aligned.high:
            return 25
        dist_atr = abs(raw.current_price - aligned.midpoint) / raw.atr14 if raw.atr14 > 0 else 99
        return 15 if dist_atr <= 0.5 else 8
    if counter is not None and not counter.filled:
        return -10
    return 0


def _score_ob(raw: H1RawFeatures) -> int:
    """OB component, weight 25."""
    if raw.d1_bias == "NEUTRAL":
        return 0
    aligned = raw.nearest_bull_ob if raw.d1_bias == "BULLISH" else raw.nearest_bear_ob
    counter = raw.nearest_bear_ob if raw.d1_bias == "BULLISH" else raw.nearest_bull_ob
    if aligned is not None:
        return 25 if raw.price_near_ob else 12
    if counter is not None:
        return -10
    return 0


def _score_trend(raw: H1RawFeatures) -> int:
    """Trend structure component, weight 15."""
    if raw.d1_bias == "NEUTRAL" or raw.trend_direction == "RANGING":
        return 0
    aligned = (raw.trend_direction == "UP") == (raw.d1_bias == "BULLISH")
    return 15 if aligned else -8


def _compute_score(raw: H1RawFeatures) -> tuple[int, str, dict]:
    if raw.d1_bias == "NEUTRAL":
        return 50, "N/A", {}
    bos_pts   = _score_bos_choch(raw)
    fvg_pts   = _score_fvg(raw)
    ob_pts    = _score_ob(raw)
    trend_pts = _score_trend(raw)
    raw_total = 50 + bos_pts + fvg_pts + ob_pts + trend_pts
    score = max(0, min(100, raw_total))
    breakdown = {
        "base": 50, "bos": bos_pts, "fvg": fvg_pts,
        "ob": ob_pts, "trend": trend_pts, "raw_total": raw_total,
    }
    if score >= 80:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 50:
        grade = "C"
    else:
        grade = "D"
    return score, grade, breakdown


# ── Telegram formatting ───────────────────────────────────────────────────────

_GRADE_LABELS = {
    "A": "Strong confluence ✅",
    "B": "Good confluence",
    "C": "Partial/neutral ⚠️",
    "D": "Counter-signal ❌",
}

_BIAS_EMOJI = {
    ("BULLISH", "NORMAL"): "🟢",
    ("BEARISH", "NORMAL"): "🔴",
    ("BULLISH", "LOW"):    "🟡",
    ("BEARISH", "LOW"):    "🟠",
    ("NEUTRAL", "NORMAL"): "⬜",
    ("NEUTRAL", "LOW"):    "⬜",
}


def _format_bos_line(raw: H1RawFeatures) -> str:
    if raw.latest_bos is None:
        return "   • No BOS detected"
    tag   = "[aligned]" if raw.bos_aligned else "[counter ⚠️]"
    arrow = "↑" if "BULL" in raw.latest_bos.type else "↓"
    kind  = "BOS" if "BOS" in raw.latest_bos.type else "CHoCH"
    return f"   • {kind} {arrow} broke {raw.latest_bos.level:.5g}  {tag}"


def _format_fvg_line(raw: H1RawFeatures) -> str:
    fvg = raw.nearest_bull_fvg if raw.d1_bias == "BULLISH" else raw.nearest_bear_fvg
    if fvg is None or fvg.filled:
        return "   • No FVG nearby"
    tag    = "[aligned]" if raw.fvg_aligned else "[counter ⚠️]"
    inside = " ← price inside" if fvg.low <= raw.current_price <= fvg.high else ""
    label  = "Bull" if fvg.direction == "BULLISH" else "Bear"
    return f"   • {label} FVG {fvg.low:.5g}–{fvg.high:.5g}{inside}  {tag}"


def _format_ob_line(raw: H1RawFeatures) -> str:
    ob = raw.nearest_bull_ob if raw.d1_bias == "BULLISH" else raw.nearest_bear_ob
    if ob is None:
        return "   • No OB detected"
    tag   = "[aligned]" if raw.ob_aligned else "[counter ⚠️]"
    label = "Bull" if ob.direction == "BULLISH" else "Bear"
    return f"   • {label} OB {ob.ob_low:.5g}–{ob.ob_high:.5g}  {tag}"


def _format_trend_line(raw: H1RawFeatures) -> str:
    if raw.trend_direction == "UP":
        txt = "HH+HL structure"
        tag = "[aligned]" if raw.d1_bias == "BULLISH" else "[counter ⚠️]"
    elif raw.trend_direction == "DOWN":
        txt = "LH+LL structure"
        tag = "[aligned]" if raw.d1_bias == "BEARISH" else "[counter ⚠️]"
    else:
        return "   • Trend: ranging"
    return f"   • Trend: {txt}  {tag}"


def _build_display_lines(raw: H1RawFeatures, score: int, grade: str) -> list[str]:
    if raw.d1_bias == "NEUTRAL":
        return ["   H1: N/A — No D1 bias to align"]
    label = _GRADE_LABELS.get(grade, "")
    return [
        f"   H1: {score}/100 ({grade}) {label}",
        _format_bos_line(raw),
        _format_fvg_line(raw),
        _format_ob_line(raw),
        _format_trend_line(raw),
    ]


def format_h1_telegram(
    confidences: list[H1Confidence],
    session: str,
    utc_time: str,
    d1_biases: dict[str, "DailyBias"],
) -> str:
    """Format pre-session H1 confidence report for Telegram."""
    lines = [
        f"🕐 *Pre-{session} — {utc_time}*",
        "────────────────────────────────────",
    ]
    for conf in confidences:
        d1 = d1_biases.get(conf.symbol)
        tier      = d1.confidence if d1 else "NORMAL"
        emoji     = _BIAS_EMOJI.get((conf.d1_bias, tier), "⬜")
        pat_label = (d1.pattern.replace("_", " ").title() if d1 and d1.pattern != "NONE"
                     else "No Pattern")
        warn = " ⚠️" if tier == "LOW" else ""
        lines.append(f"{emoji} {conf.symbol}  {conf.d1_bias}  `[{pat_label}]`{warn}")
        lines.extend(conf.display_lines)
        lines.append("────────────────────────────────────")
    lines.append("Grade: A≥80✅ B65-79 C50-64⚠️ D<50❌")
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_h1_confidence(
    df_h1: pd.DataFrame,
    symbol: str,
    session: str,
    d1_bias: str,
    d1_pattern: str,
    d1_close_pct: float,
    timestamp: Optional[str] = None,
) -> H1Confidence:
    """
    Compute H1 confidence score for one symbol.
    df_h1 must be sorted ascending with at least MIN_CANDLES rows.
    Does NOT modify DailyBias or affect precision tracking.
    """
    ts = timestamp or datetime.now(tz=timezone.utc).isoformat()

    if len(df_h1) < MIN_CANDLES:
        raw = H1RawFeatures(
            symbol=symbol, session=session, timestamp=ts,
            d1_bias=d1_bias, d1_pattern=d1_pattern, d1_close_pct=d1_close_pct,
            h1_candles_used=len(df_h1), current_price=0.0, atr14=0.0,
            latest_bos=None, latest_choch=None, trend_direction="RANGING",
            hh_count=0, ll_count=0,
            nearest_bull_fvg=None, nearest_bear_fvg=None, price_in_fvg=False,
            fvg_count_bull=0, fvg_count_bear=0,
            nearest_bull_ob=None, nearest_bear_ob=None, price_near_ob=False,
            bos_aligned=None, fvg_aligned=None, ob_aligned=None,
            aligned_count=0, counter_count=0,
        )
        return H1Confidence(
            symbol=symbol, session=session, d1_bias=d1_bias,
            score=50, grade="C", raw=raw,
            display_lines=["   H1: Insufficient data"],
            score_breakdown={},   # empty signals insufficient data to logger
        )

    raw   = _build_raw_features(df_h1, symbol, session, d1_bias, d1_pattern, d1_close_pct, ts)
    score, grade, breakdown = _compute_score(raw)
    display = _build_display_lines(raw, score, grade)
    return H1Confidence(
        symbol=symbol, session=session, d1_bias=d1_bias,
        score=score, grade=grade, raw=raw,
        display_lines=display, score_breakdown=breakdown,
    )
