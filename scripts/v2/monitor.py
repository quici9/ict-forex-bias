"""
Live performance monitor for ICT Forex Bias System.

Usage:
    # Record prediction result:
    python monitor.py record --date 2026-03-24 --symbol EUR/USD --predicted BULLISH --actual BULLISH

    # Show rolling stats:
    python monitor.py stats

    # Show per-symbol breakdown:
    python monitor.py stats --per-symbol
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_FILE = PROJECT_ROOT / "data" / "live_performance.jsonl"
STATS_FILE = PROJECT_ROOT / "data" / "live_stats.json"

ROLLING_WINDOW = 20
ALERT_THRESHOLD = 0.50


def record_prediction(
    prediction_date: str,
    symbol: str,
    pattern: str,
    predicted: str,
    actual: str,
    close_pct: float = 0.0,
) -> None:
    """Append a prediction result to the JSONL log."""
    correct = predicted == actual

    entry = {
        "date": prediction_date,
        "symbol": symbol,
        "pattern": pattern,
        "predicted": predicted,
        "t1_close_pct": close_pct,
        "actual": actual,
        "correct": correct,
        "logged_at": datetime.now(tz=__import__('datetime').timezone.utc).isoformat(),
    }

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    status = "✅" if correct else "❌"
    print(f"{status} Recorded: {symbol} {prediction_date} predicted={predicted} actual={actual}")


def load_log() -> list[dict]:
    """Load all entries from the JSONL log."""
    if not LOG_FILE.exists():
        return []

    entries = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def compute_stats(per_symbol: bool = False) -> None:
    """Compute and display rolling stats."""
    entries = load_log()

    if not entries:
        print("📊 No data yet. Use 'monitor.py record' to add predictions.")
        return

    total = len(entries)
    correct = sum(1 for e in entries if e["correct"])
    overall_precision = correct / total if total > 0 else 0.0

    # Rolling window
    recent = entries[-ROLLING_WINDOW:] if len(entries) >= ROLLING_WINDOW else entries
    recent_total = len(recent)
    recent_correct = sum(1 for e in recent if e["correct"])
    rolling_precision = recent_correct / recent_total if recent_total > 0 else 0.0

    alert = rolling_precision < ALERT_THRESHOLD and recent_total >= ROLLING_WINDOW

    print("=" * 50)
    print("📊 ICT Forex Bias — Live Performance")
    print("=" * 50)
    print(f"  Total signals:      {total}")
    print(f"  Total correct:      {correct}")
    print(f"  Overall precision:  {overall_precision:.1%}")
    print(f"  Rolling {ROLLING_WINDOW}d prec:  {rolling_precision:.1%}")
    print(f"  Last entry:         {entries[-1]['date']}")

    if alert:
        print()
        print(f"  🚨 ALERT: Rolling precision {rolling_precision:.1%} < {ALERT_THRESHOLD:.0%}")
        print("  → Consider pausing signals and investigating.")

    # Per-symbol breakdown
    if per_symbol:
        print()
        print("Per-Symbol Breakdown:")
        print("-" * 40)

        by_symbol: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
        for e in entries:
            sym = e["symbol"]
            by_symbol[sym]["total"] += 1
            if e["correct"]:
                by_symbol[sym]["correct"] += 1

        for sym in sorted(by_symbol.keys()):
            s = by_symbol[sym]
            prec = s["correct"] / s["total"] if s["total"] > 0 else 0.0
            print(f"  {sym:10s}  {prec:5.1%}  ({s['correct']}/{s['total']})")

    # Save stats file
    stats = {
        "last_updated": datetime.now(tz=__import__('datetime').timezone.utc).isoformat(),
        "rolling_20d_precision": round(rolling_precision, 4),
        "total_signals": total,
        "total_correct": correct,
        "overall_precision": round(overall_precision, 4),
        "alert": alert,
        "per_symbol": {},
    }

    by_symbol_all: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for e in entries:
        sym = e["symbol"]
        by_symbol_all[sym]["total"] += 1
        if e["correct"]:
            by_symbol_all[sym]["correct"] += 1

    for sym, s in by_symbol_all.items():
        prec = s["correct"] / s["total"] if s["total"] > 0 else 0.0
        stats["per_symbol"][sym] = {
            "precision": round(prec, 4),
            "total": s["total"],
            "correct": s["correct"],
        }

    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

    print()
    print(f"Stats saved to {STATS_FILE.relative_to(PROJECT_ROOT)}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="ICT Forex Bias Live Monitor")
    subparsers = parser.add_subparsers(dest="command")

    # Record subcommand
    rec = subparsers.add_parser("record", help="Record a prediction result")
    rec.add_argument("--date", required=True, help="Prediction date (YYYY-MM-DD)")
    rec.add_argument("--symbol", required=True, help="Symbol (e.g. EUR/USD)")
    rec.add_argument("--predicted", required=True, choices=["BULLISH", "BEARISH"])
    rec.add_argument("--actual", required=True, choices=["BULLISH", "BEARISH", "NEUTRAL"])
    rec.add_argument("--pattern", default="CONTINUATION")
    rec.add_argument("--close-pct", type=float, default=0.0)

    # Stats subcommand
    st = subparsers.add_parser("stats", help="Show rolling stats")
    st.add_argument("--per-symbol", action="store_true", help="Show per-symbol breakdown")

    args = parser.parse_args()

    if args.command == "record":
        record_prediction(
            prediction_date=args.date,
            symbol=args.symbol,
            pattern=args.pattern,
            predicted=args.predicted,
            actual=args.actual,
            close_pct=args.close_pct,
        )
    elif args.command == "stats":
        compute_stats(per_symbol=args.per_symbol)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
