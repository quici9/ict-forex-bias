"""
ICT Forex Bias System — Daily Runner (Production V3)

Usage:
    python daily_run.py                      # morning run — predict for next trading day
    python daily_run.py --pre-london         # pre-London H1 confidence report
    python daily_run.py --pre-ny             # pre-NY H1 confidence report
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
from v2.h1_confidence import compute_h1_confidence, format_h1_telegram, H1Confidence
from data.twelvedata_client import fetch_time_series

# ── Constants ─────────────────────────────────────────────────────────────────

SYMBOLS = [
    "AUD/USD", "EUR/USD", "GBP/JPY", "GBP/USD",
    "NZD/USD", "USD/CAD", "USD/CHF", "USD/JPY",
]

LOG_FILE      = PROJECT_ROOT / "data" / "live_performance.jsonl"
STATS_FILE    = PROJECT_ROOT / "data" / "live_stats.json"
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings_v3.yaml"

CONTINUATION_CLOSE_PCT = 0.20  # settings_v3.yaml: continuation_min_close_pct

# H1 context: session candles + prior context bars
H1_OUTPUTSIZE = 24
H1_LOG_PATH   = str(PROJECT_ROOT / "data" / "h1_feature_log.jsonl")


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

# Raw candle snapshot for one symbol — kept alongside DailyBias for ML logging.
RawCandles = dict


def _build_candle_snapshot(t2_row: "pd.Series", t1_row: "pd.Series") -> RawCandles:
    """Capture T-2 and T-1 OHLC values as a flat dict for ML feature storage."""
    t2_range = float(t2_row["High"]) - float(t2_row["Low"])
    t1_range = float(t1_row["High"]) - float(t1_row["Low"])
    t1_body  = abs(float(t1_row["Close"]) - float(t1_row.get("Open", float(t1_row["Close"]))))
    return {
        # T-2 candle (reference candle)
        "t2_high":        round(float(t2_row["High"]),  5),
        "t2_low":         round(float(t2_row["Low"]),   5),
        "t2_close":       round(float(t2_row["Close"]), 5),
        "t2_open":        round(float(t2_row.get("Open", t2_row["Close"])), 5),
        "t2_range":       round(t2_range, 5),
        # T-1 candle (signal candle)
        "t1_high":        round(float(t1_row["High"]),  5),
        "t1_low":         round(float(t1_row["Low"]),   5),
        "t1_close":       round(float(t1_row["Close"]), 5),
        "t1_open":        round(float(t1_row.get("Open", t1_row["Close"])), 5),
        "t1_range":       round(t1_range, 5),
        "t1_body":        round(t1_body, 5),
        "t1_body_ratio":  round(t1_body / t1_range, 4) if t1_range > 0 else 0.0,
        # Derived features useful for ML
        "t1_close_pct_of_t2_range": round(
            (float(t1_row["Close"]) - float(t2_row["Low"])) / t2_range, 4
        ) if t2_range > 0 else 0.0,
    }


def generate_signals(
    prediction_date: date, api_key: str,
) -> list[tuple[DailyBias, RawCandles]]:
    """Fetch data and return (DailyBias, raw_candles) pairs for all symbols."""
    results: list[tuple[DailyBias, RawCandles]] = []

    for sym in SYMBOLS:
        rows = fetch_d1_rows(sym, api_key)
        if rows is None:
            continue
        t2_row, t1_row = rows

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
        candles = _build_candle_snapshot(t2_row, t1_row)
        results.append((bias, candles))

        # Debug per-symbol
        _print_debug(sym, t2_row, t1_row, bias)

    return results


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

def save_predictions(
    results: list[tuple[DailyBias, RawCandles]],
    prediction_date: date,
) -> None:
    """Append all predictions to live_performance.jsonl with full candle snapshot.

    Records ALL symbols (including NEUTRAL) so ML datasets have negative examples.
    The 'predicted' field reflects the rule-based signal; 'actual' is filled later.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    date_str = prediction_date.isoformat()
    dow = prediction_date.strftime("%A")  # e.g. "Monday"

    # Avoid duplicates: load existing date × symbol keys
    existing_keys: set[str] = set()
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                existing_keys.add(f"{e['date']}|{e['symbol']}")

    written = 0
    with open(LOG_FILE, "a") as f:
        for b, candles in results:
            key = f"{date_str}|{b.symbol}"
            if key in existing_keys:
                continue
            entry = {
                # ── Identity ──────────────────────────────────────────────────
                "date":           date_str,
                "day_of_week":    dow,
                "symbol":         b.symbol,
                # ── Rule-based output (labels for supervised ML) ───────────────
                "predicted":      b.bias,        # BULLISH | BEARISH | NEUTRAL
                "pattern":        b.pattern,     # CONTINUATION | NONE
                "close_pct":      round(b.close_pct_beyond, 4),
                "confidence":     b.confidence,  # NORMAL | LOW
                # ── Raw candle features (inputs for ML models) ─────────────────
                "features":       candles,
                # ── Outcome fields (filled by --record run) ────────────────────
                "actual":         None,
                "correct":        None,
                # ── Metadata ───────────────────────────────────────────────────
                "schema_v":       2,
                "logged_at":      datetime.now(tz=timezone.utc).isoformat(),
            }
            f.write(json.dumps(entry) + "\n")
            written += 1

    directional = sum(1 for b, _ in results if b.bias != "NEUTRAL")
    neutral     = sum(1 for b, _ in results if b.bias == "NEUTRAL")
    if written:
        print(
            f"\n  Saved {written} record(s) → {LOG_FILE.relative_to(PROJECT_ROOT)}"
            f"  ({directional} signal, {neutral} neutral)"
        )
    else:
        print(f"\n  No new predictions to save (duplicates skipped).")


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

# ── H1 pre-session runner ─────────────────────────────────────────────────────

def _load_latest_biases(api_key: str) -> dict[str, DailyBias]:
    """Load today's D1 biases from live_performance.jsonl, or compute fresh."""
    today = date.today().isoformat()
    biases: dict[str, DailyBias] = {}

    if LOG_FILE.exists():
        for line in LOG_FILE.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                if e["date"] == today and e["symbol"] in SYMBOLS:
                    # Reconstruct minimal DailyBias from log for display purposes
                    from v2.pattern_scorer import DailyBias as DB
                    import datetime as _dt
                    biases[e["symbol"]] = DB(
                        symbol=e["symbol"],
                        date=_dt.date.fromisoformat(e["date"]),
                        pattern=e["pattern"],
                        bias=e["predicted"],
                        confidence=e["confidence"],
                        confidence_note="",
                        t1_high=e["features"].get("t1_high", 0),
                        t1_low=e["features"].get("t1_low", 0),
                        t1_close=e["features"].get("t1_close", 0),
                        t2_high=e["features"].get("t2_high", 0),
                        t2_low=e["features"].get("t2_low", 0),
                        close_pct_beyond=e.get("close_pct", 0),
                        message="",
                    )

    # Fall back: compute live for any missing symbols
    missing = [s for s in SYMBOLS if s not in biases]
    if missing:
        pred_date = next_trading_day(date.today())
        for sym in missing:
            rows = fetch_d1_rows(sym, api_key)
            if rows is None:
                continue
            t2, t1 = rows
            biases[sym] = build_daily_bias(
                symbol=sym,
                prediction_date=pred_date,
                t1_high=float(t1["High"]),
                t1_low=float(t1["Low"]),
                t1_close=float(t1["Close"]),
                t2_high=float(t2["High"]),
                t2_low=float(t2["Low"]),
                continuation_min_close_pct=CONTINUATION_CLOSE_PCT,
            )
    return biases


def _fetch_h1(symbol: str, api_key: str) -> "pd.DataFrame | None":
    """Fetch last H1_OUTPUTSIZE H1 candles, sorted ascending."""
    import pandas as pd
    df = fetch_time_series(
        symbol=symbol, interval="1h", outputsize=H1_OUTPUTSIZE, api_key=api_key,
    )
    if df is None or len(df) < 6:
        return None
    return df.sort_index()


def _load_h1_logger():
    """Lazy-load h1_logger module."""
    import importlib.util as _ilu
    path = PROJECT_ROOT / "scripts" / "v2" / "h1_logger.py"
    spec = _ilu.spec_from_file_location("h1_logger", path)
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_pre_session(session: str, api_key: str, dry_run: bool) -> None:
    """Fetch H1 data, compute confidence scores, log features, print/send report."""
    from datetime import datetime as _dt, timezone as _tz

    utc_now  = _dt.now(tz=_tz.utc)
    utc_time = utc_now.strftime("%a %d %b %Y %H:%M UTC")
    log_date = date.today().isoformat()

    print("=" * 60)
    print(f"ICT Forex Bias — Pre-{session} H1 Confidence")
    print(f"UTC time: {utc_now.strftime('%H:%M %Z')} | Date: {log_date}")
    print("=" * 60)

    print("\n[1/3] Loading D1 biases...")
    d1_biases = _load_latest_biases(api_key)

    print("\n[2/3] Fetching H1 data & computing confidence scores:")
    print("-" * 60)
    confidences: list[H1Confidence] = []

    h1_logger = _load_h1_logger()

    for sym in SYMBOLS:
        d1    = d1_biases.get(sym)
        df_h1 = _fetch_h1(sym, api_key)

        if df_h1 is None:
            print(f"  {sym:<10} [WARN] H1 fetch failed — skipping")
            continue

        conf = compute_h1_confidence(
            df_h1=df_h1,
            symbol=sym,
            session=session,
            d1_bias=d1.bias if d1 else "NEUTRAL",
            d1_pattern=d1.pattern if d1 else "NONE",
            d1_close_pct=d1.close_pct_beyond if d1 else 0.0,
        )
        confidences.append(conf)
        _print_h1_debug_verbose(conf)

        if not dry_run:
            h1_logger.log_h1_features(conf, H1_LOG_PATH)

    print()
    print("=" * 60)
    tg_msg = format_h1_telegram(confidences, session, utc_time, d1_biases)
    print(tg_msg)
    print("=" * 60)

    if not dry_run:
        print(f"\n  H1 features logged → {H1_LOG_PATH}")
        sent = send_telegram(tg_msg)
        if sent:
            print("  📤 Telegram message sent.")
        else:
            print("  📋 Telegram disabled.")


def _print_h1_debug_verbose(conf: H1Confidence) -> None:
    """Detailed per-symbol debug output for Phase D verification."""
    raw = conf.raw
    sep = "─" * 45

    print(f"\n  Symbol: {conf.symbol}")
    print(f"  H1 candles loaded: {raw.h1_candles_used}")
    print(f"  ATR14: {raw.atr14:.5f}  |  Current price: {raw.current_price:.5f}")

    # BOS
    if raw.latest_bos:
        tag = "aligned" if raw.bos_aligned else "counter"
        print(f"  BOS:   {raw.latest_bos.type} @ {raw.latest_bos.level:.5g}  [{tag}]")
    else:
        print("  BOS:   none detected")

    # CHoCH
    if raw.latest_choch:
        print(f"  CHoCH: {raw.latest_choch.type} @ {raw.latest_choch.level:.5g}")

    # FVG
    nb = raw.nearest_bull_fvg
    nbr = raw.nearest_bear_fvg
    print(f"  FVG:   bull={raw.fvg_count_bull} unfilled  bear={raw.fvg_count_bear} unfilled")
    if nb:
        print(f"         nearest bull: {nb.low:.5g}–{nb.high:.5g}  "
              f"size={nb.size_atr:.2f}×ATR  in_fvg={raw.price_in_fvg}")
    if nbr:
        print(f"         nearest bear: {nbr.low:.5g}–{nbr.high:.5g}  size={nbr.size_atr:.2f}×ATR")

    # OB
    nb_ob  = raw.nearest_bull_ob
    nbr_ob = raw.nearest_bear_ob
    ob_any = nb_ob or nbr_ob
    if ob_any:
        print(f"  OB:    present  nearby={raw.price_near_ob}")
    else:
        print("  OB:    none detected")

    # Score breakdown
    bd = conf.score_breakdown
    if bd:
        raw_t = bd.get("raw_total", conf.score)
        clamped = f" → clamped to {conf.score}" if raw_t != conf.score else ""
        print(
            f"  Score: 50"
            f" + BOS({bd.get('bos',0):+d})"
            f" + FVG({bd.get('fvg',0):+d})"
            f" + OB({bd.get('ob',0):+d})"
            f" + Trend({bd.get('trend',0):+d})"
            f" = {raw_t}{clamped}"
            f" → Grade {conf.grade}"
        )
    else:
        print(f"  Score: insufficient data")
    print(f"  {sep}")


def next_trading_day(from_date: date) -> date:
    """Return next Mon if from_date is Sat/Sun, else next calendar day."""
    candidate = from_date + timedelta(days=1)
    # Skip Saturday (5) and Sunday (6)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


# ── H1 actuals update ────────────────────────────────────────────────────────

def _update_h1_actuals_for_date(record_date: str, _api_key: str) -> None:
    """Call update_actuals.update_actuals() for the given date (uses backtest CSV)."""
    import importlib.util as _ilu
    path = PROJECT_ROOT / "scripts" / "v2" / "update_actuals.py"
    spec = _ilu.spec_from_file_location("update_actuals", path)
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    updated, skipped = mod.update_actuals(record_date)
    print(f"  H1 actuals: {updated} updated, {skipped} already filled → data/h1_feature_log.jsonl")


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ICT Forex Bias — Daily Runner V3")
    p.add_argument(
        "--record", metavar="DATE",
        help="Record actual D1 outcome for DATE (YYYY-MM-DD)",
    )
    p.add_argument(
        "--pre-london", action="store_true",
        help="Run pre-London H1 confidence report (07:00 UTC)",
    )
    p.add_argument(
        "--pre-ny", action="store_true",
        help="Run pre-NY H1 confidence report (12:30 UTC)",
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

    # ── Mode: pre-session H1 report ───────────────────────────────
    if args.pre_london:
        run_pre_session("London", api_key, args.dry_run)
        return

    if args.pre_ny:
        run_pre_session("NY", api_key, args.dry_run)
        return

    # ── Mode: record actual ────────────────────────────────────────
    if args.record:
        print("=" * 60)
        print(f"Recording actual outcomes for {args.record}")
        print("=" * 60)
        update_actuals(args.record, api_key)
        _update_h1_actuals_for_date(args.record, api_key)
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
    results = generate_signals(prediction_date, api_key)

    if not results:
        print("[ERROR] No signals generated — check API connectivity.")
        sys.exit(1)

    # Format and print Telegram output (directional signals only)
    biases = [b for b, _ in results]
    print()
    print("=" * 60)
    tg_msg = format_telegram_daily(biases)
    print(tg_msg)
    print("=" * 60)

    if not args.dry_run:
        save_predictions(results, prediction_date)

        sent = send_telegram(tg_msg)
        if sent:
            print("  📤 Telegram message sent.")
        else:
            print("  📋 Telegram disabled (enabled: false in settings_v3.yaml).")


if __name__ == "__main__":
    main()
