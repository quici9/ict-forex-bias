"""
H1 Feature Logger — ML-ready JSONL storage.

Appends one record per call to h1_feature_log.jsonl.
Dedup: skips if (date + symbol + session) already exists.
score=null when H1Confidence was built with insufficient candles.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from v2.h1_confidence import H1Confidence

MIN_CANDLES = 6   # must match h1_confidence.MIN_CANDLES


# ── Flatten helpers ───────────────────────────────────────────────────────────

def _nearest_fvg_fields(conf: H1Confidence) -> dict:
    """Nearest FVG to current price (direction-agnostic, for ML)."""
    raw = conf.raw
    candidates = [f for f in [raw.nearest_bull_fvg, raw.nearest_bear_fvg] if f is not None]
    if not candidates:
        return {
            "nearest_fvg_dir": None, "nearest_fvg_high": None,
            "nearest_fvg_low": None, "nearest_fvg_size_atr": None,
            "price_in_fvg": False,
        }
    nearest = min(candidates, key=lambda f: abs(f.midpoint - raw.current_price))
    return {
        "nearest_fvg_dir":      nearest.direction,
        "nearest_fvg_high":     nearest.high,
        "nearest_fvg_low":      nearest.low,
        "nearest_fvg_size_atr": nearest.size_atr,
        "price_in_fvg":         nearest.low <= raw.current_price <= nearest.high,
    }


def _ob_fields(conf: H1Confidence) -> dict:
    """Both bull and bear OB fields — full context for ML."""
    raw = conf.raw
    nb  = raw.nearest_bull_ob
    nbr = raw.nearest_bear_ob
    return {
        "bull_ob_present":  nb  is not None,
        "bull_ob_high":     nb.ob_high  if nb  else None,
        "bull_ob_low":      nb.ob_low   if nb  else None,
        "bull_ob_size_atr": nb.size_atr if nb  else None,
        "bear_ob_present":  nbr is not None,
        "bear_ob_high":     nbr.ob_high  if nbr else None,
        "bear_ob_low":      nbr.ob_low   if nbr else None,
        "bear_ob_size_atr": nbr.size_atr if nbr else None,
        "price_near_ob":    raw.price_near_ob,
    }


def build_log_entry(conf: H1Confidence, log_date: str) -> dict:
    """Flatten H1Confidence into a JSONL-ready dict."""
    raw   = conf.raw
    bos   = raw.latest_bos
    choch = raw.latest_choch

    # score is null when insufficient data (empty breakdown = sentinel)
    is_valid  = bool(conf.score_breakdown)
    log_score = conf.score if is_valid else None
    log_grade = conf.grade if is_valid else None
    note      = None if is_valid else "insufficient_data"

    return {
        # Identity
        "ts":      raw.timestamp,
        "symbol":  raw.symbol,
        "session": raw.session,
        "date":    log_date,
        # D1 context (ML labels)
        "d1_bias":      raw.d1_bias,
        "d1_pattern":   raw.d1_pattern,
        "d1_close_pct": raw.d1_close_pct,
        # H1 score
        "h1_score":     log_score,
        "h1_grade":     log_grade,
        "note":         note,
        # Score breakdown (for audit / reconstruction)
        "score_base":   conf.score_breakdown.get("base"),
        "score_bos":    conf.score_breakdown.get("bos"),
        "score_fvg":    conf.score_breakdown.get("fvg"),
        "score_ob":     conf.score_breakdown.get("ob"),
        "score_trend":  conf.score_breakdown.get("trend"),
        # H1 context
        "h1_candles_used": raw.h1_candles_used,
        "current_price":   raw.current_price,
        "atr14":           raw.atr14,
        # Structure
        "trend_direction": raw.trend_direction,
        "hh_count":        raw.hh_count,
        "ll_count":        raw.ll_count,
        # BOS
        "bos_type":     bos.type           if bos   else None,
        "bos_level":    bos.level          if bos   else None,
        "bos_size_atr": bos.swing_size_atr if bos   else None,
        "bos_aligned":  raw.bos_aligned,
        # CHoCH
        "choch_detected": choch is not None,
        "choch_type":     choch.type if choch else None,
        # FVG
        "bull_fvg_count": raw.fvg_count_bull,
        "bear_fvg_count": raw.fvg_count_bear,
        **_nearest_fvg_fields(conf),
        "fvg_aligned":    raw.fvg_aligned,
        # OB
        **_ob_fields(conf),
        "ob_aligned":     raw.ob_aligned,
        # Alignment summary
        "aligned_count": raw.aligned_count,
        "counter_count": raw.counter_count,
        # Actual outcomes (filled by update_actuals.py)
        "actual_session_move":     None,
        "actual_session_pips":     None,
        "d1_actual_bias_next_day": None,
        # Schema
        "schema_v": 1,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def log_h1_features(confidence: H1Confidence, filepath: str) -> None:
    """
    Append one H1Confidence record to the JSONL file at filepath.
    Skips silently if (date + symbol + session) already exists.
    Uses today's date as log_date inferred from confidence.raw.timestamp.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Derive log_date from timestamp (first 10 chars = YYYY-MM-DD)
    log_date = confidence.raw.timestamp[:10]

    # Dedup check
    key = f"{log_date}|{confidence.symbol}|{confidence.session}"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                if f"{e['date']}|{e['symbol']}|{e['session']}" == key:
                    return  # already logged

    entry = build_log_entry(confidence, log_date)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
