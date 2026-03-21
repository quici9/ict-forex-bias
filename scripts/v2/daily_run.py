"""
ICT Forex Bias System — Daily Runner (Production V3)

Usage:
    python daily_run.py                    # morning run — predict for next trading day
    python daily_run.py --record 2026-03-21  # record actual outcome for that date

Requires:
    TWELVEDATA_API_KEY env var (or .env file in project root)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from v2.pattern_scorer import build_daily_bias, format_telegram_daily, DailyBias
from data.twelvedata_client import fetch_time_series

# ── Constants ─────────────────────────────────────────────────────────────────

SYMBOLS = [
    "AUD/USD", "EUR/USD", "GBP/JPY", "GBP/USD",
    "NZD/USD", "USD/CAD", "USD/CHF", "USD/JPY",
]

LOG_FILE    = PROJECT_ROOT / "data" / "live_performance.jsonl"
STATS_FILE  = PROJECT_ROOT / "data" / "live_stats.json"
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings_v3.yaml"

CONTINUATION_CLOSE_PCT = 0.20  # settings_v3.yaml: continuation_min_close_pct


# ── API key loader ─────────────────────────────────────────────────────────────

def _load_api_key() -> str:
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    if key:
        return key
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TWELVEDATA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return ""


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_last_n_candles(symbol: str, n: int, api_key: str) -> "pd.DataFrame | None":
    """Fetch last N D1 candles for symbol. Returns sorted DataFrame or None."""
    import pandas as pd
    df = fetch_time_series(symbol=symbol, interval="1day", outputsize=n, api_key=api_key)
    if df is None or len(df) < 2:
        return None
    return df.sort_index()


def fetch_d1_rows(symbol: str, api_key: str) -> tuple | None:
    """Return (t2_row, t1_row) for the two most recent completed D1 candles."""
    df = _fetch_last_n_candles(symbol, 5, api_key)
    if df is None:
        print(f"  [WARN] {symbol}: insufficient data")
        return None
    return df.iloc[-2], df.iloc[-1]


def fetch_actual_bias(symbol: str, record_date: str, api_key: str) -> str | None:
    """
    Fetch D1 candles and compute actual_bias for record_date.
    BULLISH  = High(DATE) > High(DATE-1) AND Low(DATE) > Low(DATE-1)
    BEARISH  = High(DATE) < High(DATE-1) AND Low(DATE) < Low(DATE-1)
    NEUTRAL  = everything else
    """
    import pandas as pd
    df = _fetch_last_n_candles(symbol, 10, api_key)
    if df is None or len(df) < 2:
        return None

    # Find the target date row
    target = pd.Timestamp(record_date, tz="UTC")
    if target not in df.index:
        # Try date-only match (ignore time component)
        matches = df.index[df.index.normalize() == target.normalize()]
        if len(matches) == 0:
            return None
        target = matches[-1]

    pos = df.index.get_loc(target)
    if pos == 0:
        return None

    prev_idx = df.index[pos - 1]
    cur  = df.loc[target]
    prev = df.loc[prev_idx]

    if cur["High"] > prev["High"] and cur["Low"] > prev["Low"]:
        return "BULLISH"
    if cur["High"] < prev["High"] and cur["Low"] < prev["Low"]:
        return "BEARISH"
    return "NEUTRAL"


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signals(prediction_date: date, api_key: str) -> list[DailyBias]:
    """Fetch data and return DailyBias for all symbols with debug output."""
    biases: list[DailyBias] = []

    for sym in SYMBOLS:
        rows = fetch_d1_rows(sym, api_key)
        if rows is None:
            continue
        t2_row, t1_row = rows

        t2_range = float(t1_row["High"]) - float(t1_row["Low"])
        if t2_range > 0:
            close_pct = (float(t1_row["Close"]) - float(t2_row["High"])) / t2_range
        else:
            close_pct = 0.0

        bias = build_daily_bias(
            symbol=sym,
            prediction_date=prediction_date,
            t1_high=float(t1_row["High"]),
            t1_low=float(t1_row["Low"]),
            t1_close=float(t1_row["Close"]),
            t2_high=float(t2_row["High"]),
            t2_low=float(t2_row["Low"]),
            continuation_min_close_pct=CONTINUATION_CLOSE_PCT,
        )
        biases.append(bias)

        # Debug per-symbol
        _print_debug(sym, t2_row, t1_row, bias)

    return biases


def _print_debug(
    sym: str,
    t2_row: "pd.Series",
    t1_row: "pd.Series",
    bias: DailyBias,
) -> None:
    t2_range = float(t2_row["High"]) - float(t2_row["Low"])
    if bias.pattern == "CONTINUATION" and t2_range > 0:
        if bias.bias == "BULLISH":
            close_pct = (float(t1_row["Close"]) - float(t2_row["High"])) / t2_range
        else:
            close_pct = (float(t2_row["Low"]) - float(t1_row["Close"])) / t2_range
    else:
        close_pct = 0.0

    tag = f"[{bias.pattern}]" if bias.pattern != "NONE" else "[NONE]"
    conf = " LOW" if bias.confidence == "LOW" else ""
    print(
        f"  {sym:<10} T-2 H={t2_row['High']:.5f} L={t2_row['Low']:.5f} "
        f"| T-1 C={t1_row['Close']:.5f} "
        f"| pct={close_pct:+.1%} "
        f"→ {bias.bias}{conf} {tag}"
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def save_predictions(biases: list[DailyBias], prediction_date: date) -> None:
    """Append predictions (actual=null) to live_performance.jsonl.
    Only saves CONTINUATION signals (non-NEUTRAL).
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    date_str = prediction_date.isoformat()

    # Avoid duplicates: load existing dates × symbols
    existing_keys: set[str] = set()
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                existing_keys.add(f"{e['date']}|{e['symbol']}")

    written = 0
    with open(LOG_FILE, "a") as f:
        for b in biases:
            if b.bias == "NEUTRAL":
                continue
            key = f"{date_str}|{b.symbol}"
            if key in existing_keys:
                continue
            entry = {
                "date":           date_str,
                "symbol":         b.symbol,
                "predicted":      b.bias,
                "pattern":        b.pattern,
                "close_pct":      round(b.close_pct_beyond, 4),
                "confidence":     b.confidence,
                "actual":         None,
                "correct":        None,
                "logged_at":      datetime.now(tz=timezone.utc).isoformat(),
            }
            f.write(json.dumps(entry) + "\n")
            written += 1

    if written:
        print(f"\n  Saved {written} prediction(s) → {LOG_FILE.relative_to(PROJECT_ROOT)}")
    else:
        print(f"\n  No new predictions to save (duplicates skipped or all neutral).")


def _load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _save_log(entries: list[dict]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def update_actuals(record_date: str, api_key: str) -> None:
    """Fetch D1 actual outcome for record_date and update live_performance.jsonl."""
    entries = _load_log()
    targets = [e for e in entries if e["date"] == record_date and e["actual"] is None]

    if not targets:
        print(f"  No pending predictions found for {record_date}.")
        return

    updated = 0
    for entry in entries:
        if entry["date"] != record_date or entry["actual"] is not None:
            continue

        sym = entry["symbol"]
        actual = fetch_actual_bias(sym, record_date, api_key)
        if actual is None:
            print(f"  [WARN] {sym}: could not fetch actual for {record_date}")
            continue

        entry["actual"] = actual
        entry["correct"] = (entry["predicted"] == actual)
        entry["updated_at"] = datetime.now(tz=timezone.utc).isoformat()

        status = "✅" if entry["correct"] else "❌"
        print(f"  {status} {sym}: predicted={entry['predicted']}  actual={actual}")
        updated += 1

    _save_log(entries)
    print(f"\n  Updated {updated} record(s).")
    _update_stats(entries)


def _update_stats(entries: list[dict]) -> None:
    """Recompute and save live_stats.json from all completed entries."""
    completed = [e for e in entries if e["actual"] is not None]
    if not completed:
        print("  No completed records yet — stats not updated.")
        return

    total   = len(completed)
    correct = sum(1 for e in completed if e["correct"])
    overall = correct / total

    rolling_window = min(20, total)
    recent  = completed[-rolling_window:]
    rolling = sum(1 for e in recent if e["correct"]) / len(recent)

    by_sym: dict = defaultdict(lambda: {"total": 0, "correct": 0})
    for e in completed:
        s = e["symbol"]
        by_sym[s]["total"] += 1
        if e["correct"]:
            by_sym[s]["correct"] += 1

    per_sym = {
        s: {
            "precision": round(v["correct"] / v["total"], 4),
            "total": v["total"],
            "correct": v["correct"],
        }
        for s, v in by_sym.items()
    }

    stats = {
        "last_updated":          datetime.now(tz=timezone.utc).isoformat(),
        "rolling_20d_precision": round(rolling, 4),
        "total_signals":         total,
        "total_correct":         correct,
        "overall_precision":     round(overall, 4),
        "alert":                 rolling < 0.50 and rolling_window >= 20,
        "per_symbol":            per_sym,
    }
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"  Stats updated → {STATS_FILE.relative_to(PROJECT_ROOT)}")


# ── Telegram ──────────────────────────────────────────────────────────────────

def _load_telegram_config() -> dict:
    try:
        import yaml  # type: ignore
        with open(SETTINGS_FILE) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("telegram", {})
    except Exception:
        return {}


def send_telegram(message: str) -> bool:
    cfg = _load_telegram_config()
    if not cfg.get("enabled", False):
        return False

    token   = cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [WARN] Telegram enabled but bot_token/chat_id not configured.")
        return False

    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  [ERROR] Telegram send failed: {e}")
        return False


# ── Next trading day logic ─────────────────────────────────────────────────────

def next_trading_day(from_date: date) -> date:
    """Return next Mon if from_date is Sat/Sun, else next calendar day."""
    candidate = from_date + timedelta(days=1)
    # Skip Saturday (5) and Sunday (6)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ICT Forex Bias — Daily Runner V3")
    p.add_argument(
        "--record", metavar="DATE",
        help="Record actual D1 outcome for DATE (YYYY-MM-DD)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print signals but don't save or send Telegram",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    api_key = _load_api_key()
    if not api_key:
        print("[ERROR] TWELVEDATA_API_KEY not set. Add to .env or export env var.")
        sys.exit(1)

    # ── Mode: record actual ────────────────────────────────────────
    if args.record:
        print("=" * 60)
        print(f"Recording actual outcomes for {args.record}")
        print("=" * 60)
        update_actuals(args.record, api_key)
        return

    # ── Mode: generate signals ─────────────────────────────────────
    today = date.today()
    prediction_date = next_trading_day(today)

    print("=" * 60)
    print(f"ICT Forex Bias — run date: {today.strftime('%a %d %b %Y')}")
    print(f"Predicting for:            {prediction_date.strftime('%a %d %b %Y')}")
    print("=" * 60)

    print("\n[DEBUG] Per-symbol pattern detection:")
    print("-" * 60)
    biases = generate_signals(prediction_date, api_key)

    if not biases:
        print("[ERROR] No signals generated — check API connectivity.")
        sys.exit(1)

    # Format and print Telegram output
    print()
    print("=" * 60)
    tg_msg = format_telegram_daily(biases)
    print(tg_msg)
    print("=" * 60)

    if not args.dry_run:
        save_predictions(biases, prediction_date)

        sent = send_telegram(tg_msg)
        if sent:
            print("  📤 Telegram message sent.")
        else:
            print("  📋 Telegram disabled (enabled: false in settings_v3.yaml).")


if __name__ == "__main__":
    main()
