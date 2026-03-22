"""
H1 Actuals Updater — fills outcome fields in h1_feature_log.jsonl.

Usage:
    python update_actuals.py --date 2026-03-24

For rows matching the date with actual_session_move == null:
  - actual_session_move     : BULLISH | BEARISH | NEUTRAL (session open→close)
  - actual_session_pips     : float (session_close - session_open) / pip_size
  - d1_actual_bias_next_day : BULLISH | BEARISH | NEUTRAL (D1 T+1 vs T)

Data source: data/backtest/ CSV files (no live API needed).
Only updates null fields — never overwrites filled actuals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKTEST_DIR = PROJECT_ROOT / "data" / "backtest"
H1_LOG_FILE  = PROJECT_ROOT / "data" / "h1_feature_log.jsonl"

# ── Symbol → CSV filename mapping ─────────────────────────────────────────────

SYMBOL_TO_FILE = {
    "AUD/USD": "AUDUSDX",
    "EUR/USD": "EURUSDX",
    "GBP/JPY": "GBPJPYX",
    "GBP/USD": "GBPUSDX",
    "NZD/USD": "NZDUSDX",
    "USD/CAD": "USDCADX",
    "USD/CHF": "USDCHFX",
    "USD/JPY": "USDJPYX",
}

JPY_SYMBOLS = {"GBP/JPY", "USD/JPY"}

SESSION_WINDOWS: dict[str, tuple[int, int]] = {
    "London": (7, 12),
    "NY":     (13, 17),
}


# ── CSV loaders ───────────────────────────────────────────────────────────────

def _load_h1(symbol: str) -> Optional[pd.DataFrame]:
    fname = SYMBOL_TO_FILE.get(symbol)
    if fname is None:
        return None
    path = BACKTEST_DIR / f"{fname}_1h.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.sort_index()


def _load_d1(symbol: str) -> Optional[pd.DataFrame]:
    fname = SYMBOL_TO_FILE.get(symbol)
    if fname is None:
        return None
    path = BACKTEST_DIR / f"{fname}_1d.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.sort_index()


# ── Actual computation ────────────────────────────────────────────────────────

def compute_session_move(
    df_h1: pd.DataFrame,
    date_str: str,
    session: str,
    symbol: str,
) -> tuple[Optional[str], Optional[float]]:
    """
    Classify session direction from H1 bars within the session window.
    Returns (move, pips) or (None, None) if data unavailable.
    """
    start_h, end_h = SESSION_WINDOWS.get(session, (7, 12))
    date_ts = pd.Timestamp(date_str, tz="UTC")

    mask = (
        (df_h1.index.normalize() == date_ts.normalize()) &
        (df_h1.index.hour >= start_h) &
        (df_h1.index.hour < end_h)
    )
    bars = df_h1[mask]
    if len(bars) < 1:
        return None, None

    open_price  = float(bars["Open"].iloc[0])
    close_price = float(bars["Close"].iloc[-1])
    pip_size    = 0.01 if symbol in JPY_SYMBOLS else 0.0001
    pips        = round((close_price - open_price) / pip_size, 1)

    if close_price > open_price:
        move = "BULLISH"
    elif close_price < open_price:
        move = "BEARISH"
    else:
        move = "NEUTRAL"

    return move, pips


def compute_d1_actual_next_day(
    df_d1: pd.DataFrame,
    date_str: str,
) -> Optional[str]:
    """
    BULLISH = High(T+1) > High(T) AND Low(T+1) > Low(T)
    BEARISH = High(T+1) < High(T) AND Low(T+1) < Low(T)
    NEUTRAL = everything else
    """
    date_ts = pd.Timestamp(date_str, tz="UTC")
    dates   = df_d1.index.normalize()
    target  = date_ts.normalize()

    matches = df_d1[dates == target]
    if len(matches) == 0:
        return None

    t_idx = df_d1.index.get_loc(matches.index[-1])
    if t_idx >= len(df_d1) - 1:
        return None

    t  = df_d1.iloc[t_idx]
    t1 = df_d1.iloc[t_idx + 1]

    if t1["High"] > t["High"] and t1["Low"] > t["Low"]:
        return "BULLISH"
    if t1["High"] < t["High"] and t1["Low"] < t["Low"]:
        return "BEARISH"
    return "NEUTRAL"


# ── Core update logic ─────────────────────────────────────────────────────────

def update_actuals(target_date: str, log_file: Path = H1_LOG_FILE) -> tuple[int, int]:
    """
    Fill actual fields for rows matching target_date with null actuals.
    Returns (updated, skipped_already_filled).
    """
    if not log_file.exists():
        print(f"  [WARN] Log file not found: {log_file}")
        return 0, 0

    entries = []
    for line in log_file.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))

    targets    = [e for e in entries if e["date"] == target_date]
    to_update  = [e for e in targets if e.get("actual_session_move") is None]
    already_ok = len(targets) - len(to_update)

    if not to_update:
        return 0, already_ok

    # Cache CSV loads per symbol
    h1_cache: dict[str, Optional[pd.DataFrame]] = {}
    d1_cache: dict[str, Optional[pd.DataFrame]] = {}

    updated = 0
    for entry in entries:
        if entry["date"] != target_date or entry.get("actual_session_move") is not None:
            continue

        sym = entry["symbol"]

        if sym not in h1_cache:
            h1_cache[sym] = _load_h1(sym)
        if sym not in d1_cache:
            d1_cache[sym] = _load_d1(sym)

        df_h1 = h1_cache[sym]
        df_d1 = d1_cache[sym]

        move, pips = (None, None)
        if df_h1 is not None:
            move, pips = compute_session_move(df_h1, target_date, entry["session"], sym)

        d1_next = None
        if df_d1 is not None:
            d1_next = compute_d1_actual_next_day(df_d1, target_date)

        if move is None and d1_next is None:
            print(f"  [SKIP] {sym} {entry['session']}: no data for {target_date}")
            continue

        entry["actual_session_move"]     = move
        entry["actual_session_pips"]     = pips
        entry["d1_actual_bias_next_day"] = d1_next
        updated += 1

        arrow = "↑" if move == "BULLISH" else "↓" if move == "BEARISH" else "→"
        print(
            f"  ✅ {sym:<10} [{entry['session']:<6}]  "
            f"move={move} {arrow}  pips={pips:+.1f}  "
            f"d1_next={d1_next}"
        )

    # Rewrite the full file
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return updated, already_ok


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Fill H1 actuals from backtest CSV data")
    p.add_argument("--date", required=True, metavar="YYYY-MM-DD",
                   help="Target date to fill actuals for")
    p.add_argument("--log", default=str(H1_LOG_FILE), metavar="PATH",
                   help="Path to h1_feature_log.jsonl (default: data/h1_feature_log.jsonl)")
    args = p.parse_args()

    print(f"Filling actuals for {args.date} → {args.log}")
    print("-" * 60)
    updated, skipped = update_actuals(args.date, Path(args.log))
    print("-" * 60)
    print(f"Updated: {updated}  |  Already filled (skipped): {skipped}")


if __name__ == "__main__":
    main()
