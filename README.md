# ICT Forex Bias System

> **Rule-based Daily Bias predictor for 8 Forex pairs, powered by ICT's D1 2-candle Continuation pattern.**
>
> 📊 **64.8% precision** on test set (2025-H2 → 2026-Q1) · 7/7 walk-forward pass · Sharpe 4.94 · $0/month infrastructure

---

## Table of Contents

1. [Overview](#overview)
2. [Performance](#performance)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [Quick Start](#quick-start)
6. [Daily Workflow](#daily-workflow)
7. [Pre-Session H1 Reports](#pre-session-h1-reports)
8. [Configuration](#configuration)
9. [GitHub Actions Automation](#github-actions-automation)
10. [Dashboard (GitHub Pages)](#dashboard-github-pages)
11. [Data Files](#data-files)
12. [Monitoring & Alerts](#monitoring--alerts)
13. [Infrastructure & Cost](#infrastructure--cost)
14. [Roadmap](#roadmap)
15. [Troubleshooting](#troubleshooting)

---

## Overview

**ICT Forex Bias System** is an automated pipeline that analyses Forex markets using the ICT (Inner Circle Trader) methodology. Every trading day it:

1. Fetches D1 candle data for **8 major Forex pairs** via TwelveData API
2. Applies a **D1 2-candle Continuation pattern** to classify each pair as `BULLISH`, `BEARISH`, or `NEUTRAL`
3. Sends a **Daily Bias report** via Telegram before London and New York sessions
4. Tracks **live precision** by recording actual outcomes and computing rolling stats

### What makes this different

The system went through 13+ rounds of backtesting (2019–2026). An earlier weighted feature scoring approach (Market Structure + FVG + SMT + Liquidity Sweep) hit a ceiling of **17.8% precision** — worse than random. The final V3 uses a single, simple pattern that achieves **64.8%** on a held-out test set.

### Supported pairs

`AUD/USD` · `EUR/USD` · `GBP/JPY` · `GBP/USD` · `NZD/USD` · `USD/CAD` · `USD/CHF` · `USD/JPY`

---

## Performance

### Backtest results (V3 deployed config)

| Metric | Value | Period |
|--------|-------|--------|
| Test precision | **64.8%** | 2025-07-01 → 2026-03-21 |
| Signal frequency | 2.08 signals/symbol/week | Test period |
| Signal frequency (long-run) | 1.38 signals/symbol/week | 2019–2026 |
| Walk-forward | **7/7 pass** | Annual windows 2020–2026 |
| Worst WF window | 57.8% | — |
| Simulated Sharpe | 4.94 | — |

### Per-symbol precision (test set)

| Symbol | Precision | Tier |
|--------|-----------|------|
| NZD/USD | **72.9%** | HIGH |
| USD/CAD | **66.7%** | HIGH |
| USD/JPY | **66.3%** | HIGH |
| EUR/USD | **66.2%** | HIGH |
| AUD/USD | 64.8% | NORMAL |
| USD/CHF | 64.3% | NORMAL |
| GBP/USD | 64.2% | NORMAL |
| GBP/JPY | 50.0% | LOW ⚠️ |

> GBP/JPY is marked as `LOW` confidence in all reports and sorted to the bottom of signals.

---

## Architecture

```
Daily flow (Mon – Fri):

  ┌─ Morning run (22:00 UTC prev day / 08:45 VN) ──────────────┐
  │  1. Record yesterday's actual outcome:                      │
  │     python daily_run.py --record <prev_date>               │
  │       → Fetch D1 for prev_date, compute BULLISH/BEARISH    │
  │       → Update live_performance.jsonl                       │
  │       → Update live_stats.json (rolling precision)         │
  │       → Backfill H1 actuals → h1_feature_log.jsonl        │
  │                                                             │
  │  2. Generate today's signals:                               │
  │     python daily_run.py                                     │
  │       → Fetch D1 last 5 candles × 8 symbols               │
  │       → classify_d1_pattern() → DailyBias per symbol       │
  │       → format_telegram_daily() → send Telegram            │
  │       → Append predictions to live_performance.jsonl       │
  └─────────────────────────────────────────────────────────────┘

  ┌─ Pre-London (06:30 UTC / 13:30 VN) ────────────────────────┐
  │  python daily_run.py --pre-london                          │
  │    → Fetch H1 data × 8 symbols                             │
  │    → Detect BOS, CHoCH, FVG, OB structures                 │
  │    → Score H1 alignment vs D1 bias (0–100, grade A–D)      │
  │    → Send H1 confidence report via Telegram                │
  │    → Log features to h1_feature_log.jsonl                  │
  └─────────────────────────────────────────────────────────────┘

  ┌─ Pre-NY (12:30 UTC / 19:30 VN) ────────────────────────────┐
  │  python daily_run.py --pre-ny                              │
  │    → Same as Pre-London, for New York session              │
  └─────────────────────────────────────────────────────────────┘
```

### D1 Pattern Logic

Two closed D1 candles are used to predict the direction of the next trading day:

```
T-2 candle  →  defines the reference range [Low₂, High₂]
T-1 candle  →  where Close₁ lands relative to T-2 range
T   candle  →  the day being predicted (not yet formed)
```

**Continuation signal** (only active pattern):
- 🟢 **BULLISH**: `Close₁ > High₂ + 0.20 × Range₂`
- 🔴 **BEARISH**: `Close₁ < Low₂ − 0.20 × Range₂`
- ⬜ **NEUTRAL**: everything else (Inside Bar, Reversal disabled, No Pattern)

> Reversal patterns were evaluated and achieved only 35% precision — disabled in production.

### H1 Confidence Scoring (Phase D)

Before each session, the system analyses H1 market structure to grade how well intraday conditions align with the D1 bias. This does **not** affect D1 predictions or precision tracking — it is context enrichment for discretionary entry decisions.

**Structures detected:**
- **BOS** (Break of Structure) — bullish or bearish
- **CHoCH** (Change of Character) — potential reversal signal
- **FVG** (Fair Value Gap) — unfilled imbalance zones
- **OB** (Order Block) — institutional supply/demand zones
- **Trend** — HH+HL (up), LH+LL (down), or ranging

**Scoring formula** (base 50 + component deltas, clamped 0–100):

| Component | Aligned | Counter |
|-----------|---------|---------|
| BOS/CHoCH | +35 | −15 to −20 |
| FVG | +8 to +25 | −10 |
| OB | +12 to +25 | −10 |
| Trend | +15 | −8 |

**Grades:** A ≥ 80 ✅ · B 65–79 · C 50–64 ⚠️ · D < 50 ❌

---

## Project Structure

```
ict_forex_bias/
│
├── .github/
│   └── workflows/
│       └── run_analysis.yml        # Cron automation: London 01:45 UTC + NY 06:45 UTC
│
├── src/
│   ├── v2/
│   │   ├── pattern_scorer.py       # D1 pattern engine, DailyBias, Telegram formatter
│   │   ├── h1_detector.py          # H1 structure detection: BOS, CHoCH, FVG, OB
│   │   └── h1_confidence.py        # H1 confidence scorer and Telegram formatter
│   └── data/
│       └── twelvedata_client.py    # TwelveData API client (rate-limited, retry)
│
├── scripts/
│   └── v2/
│       ├── daily_run.py            # Main CLI runner (signals, record, pre-session)
│       ├── h1_logger.py            # Log H1 features to JSONL
│       ├── update_actuals.py       # Backfill H1 actuals from backtest CSV
│       └── monitor.py              # View rolling stats and per-symbol breakdown
│
├── backtest/
│   ├── engine.py                   # Backtest engine
│   ├── evaluator.py                # Precision / frequency metrics
│   ├── metrics.py                  # Walk-forward, Sharpe, per-symbol stats
│   ├── reporter.py                 # Console/CSV report generator
│   └── tuner.py                    # Grid search parameter tuner
│
├── config/
│   └── settings_v3.yaml            # Production config (pattern params + Telegram)
│
├── data/
│   ├── live_performance.jsonl      # Append-only predictions + actuals log
│   ├── live_stats.json             # Rolling precision stats (auto-updated)
│   ├── tuning_state_v2.json        # Full tuning history (13+ rounds)
│   └── backtest/                   # Historical OHLCV CSVs 2019–2026
│       ├── EURUSDX_1d.csv
│       └── ...
│
├── docs/
│   ├── index.html                  # GitHub Pages dashboard
│   ├── app.js                      # Dashboard data rendering
│   ├── style.css                   # Dashboard styles
│   ├── ICT_Forex_Bias_System_Design.md
│   ├── ICT_Forex_Bias_System_Action_Plan.md
│   └── ICT_Forex_Bias_Experiment_Log-2.md
│
├── tests/
│   └── fixtures/                   # Sample OHLCV data for unit tests
│
├── .env                            # Local secrets (gitignored)
├── .env.example                    # Secret template
├── requirements.txt
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- [TwelveData API key](https://twelvedata.com/) (free tier is sufficient)
- Telegram Bot (optional) — create via [@BotFather](https://t.me/BotFather)

### 1. Clone and install

```bash
git clone https://github.com/quici9/ict-forex-bias.git
cd ict-forex-bias

python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows

pip install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env`:

```env
TWELVEDATA_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_token_here   # optional
TELEGRAM_CHAT_ID=your_chat_id_here   # optional
```

### 3. Run your first signal

```bash
python scripts/v2/daily_run.py --dry-run
```

`--dry-run` prints signals and H1 output without saving to disk or sending Telegram.

---

## Daily Workflow

### Generate D1 bias signals (every morning)

```bash
python scripts/v2/daily_run.py
```

Output example:
```
============================================================
ICT Forex Bias — run date: Sat 22 Mar 2026
Predicting for:            Mon 24 Mar 2026
============================================================

[DEBUG] Per-symbol pattern detection:
------------------------------------------------------------
  AUD/USD    T-2 H=0.63412 L=0.62855 | T-1 C=0.63501 | pct=+1.6% → NEUTRAL [NONE]
  EUR/USD    T-2 H=1.08524 L=1.07801 | T-1 C=1.09021 | pct=+6.9% → BULLISH [CONTINUATION]
  ...

📅 *Daily Bias — Mon 24 Mar 2026*
──────────────────────────────────
🟢 EUR/USD  BULLISH  [Continuation]
   Close +6.9% beyond High(T-2)
```

### Record actual outcome (next morning)

```bash
python scripts/v2/daily_run.py --record 2026-03-24
```

This fetches the D1 candle for `2026-03-24`, computes `BULLISH/BEARISH/NEUTRAL`, compares against prediction, updates `live_performance.jsonl` and `live_stats.json`.

### View live performance

```bash
python scripts/v2/monitor.py
```

---

## Pre-Session H1 Reports

Run before each trading session to get an H1 confluence grade for every pair.

### Pre-London (run at 06:30 UTC / 13:30 VN)

```bash
python scripts/v2/daily_run.py --pre-london
```

### Pre-New York (run at 12:30 UTC / 19:30 VN)

```bash
python scripts/v2/daily_run.py --pre-ny
```

**Telegram output example:**
```
🕐 *Pre-London — Sat 22 Mar 2026 06:30 UTC*
────────────────────────────────────
🟢 EUR/USD  BULLISH  [Continuation]
   H1: 78/100 (B) Good confluence
   • BOS ↑ broke 1.08950  [aligned]
   • Bull FVG 1.08820–1.08890 ← price inside  [aligned]
   • Bull OB 1.08700–1.08780  [aligned]
   • Trend: HH+HL structure  [aligned]
────────────────────────────────────
Grade: A≥80✅ B65-79 C50-64⚠️ D<50❌
```

H1 features are logged to `data/h1_feature_log.jsonl` for future ML training.

---

## Configuration

All parameters are in `config/settings_v3.yaml`. No source code changes needed.

```yaml
# config/settings_v3.yaml

use_pattern_scorer: true

signal_config:
  mode: "continuation_only"
  reversal_mode: "disabled"          # 35% precision — disabled
  low_confidence_symbols:
    - "GBP/JPY"
  low_confidence_threshold: 0.55

d1_pattern:
  continuation_min_close_pct: 0.20  # ACTIVE — Close must clear 20% beyond T-2 range
  reversal_min_wick_pct: 0.40       # inactive
  reversal_body_ratio: 0.50         # inactive

h1_confirmation:
  swing_lookback: 2
  fvg_lookback_candles: 8
  h1_context_candles_before: 18

live:
  daily_report_utc: "22:00"
  pre_london_utc: "06:30"
  pre_ny_utc: "12:30"

monitoring:
  rolling_window_days: 20
  alert_threshold: 0.50
  review_date: "2026-06-22"
  re_tune_trigger: "precision_20d < 0.50 for 2 consecutive weeks"

telegram:
  enabled: true                      # set to false to disable Telegram
  bot_token: ""                      # or env var TELEGRAM_BOT_TOKEN
  chat_id: ""                        # or env var TELEGRAM_CHAT_ID
```

---

## GitHub Actions Automation

### Schedule

| Workflow run | Cron (UTC) | Time (VN) | Action |
|---|---|---|---|
| London | `45 1 * * 1-5` | 08:45 | Record yesterday's actual + generate signals |
| New York | `45 6 * * 1-5` | 13:45 | Generate signals (reminder) |

### Setup

1. Push the repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add these secrets:

| Secret | Required | Description |
|--------|---------|-------------|
| `TWELVEDATA_API_KEY` | ✅ | Your TwelveData API key |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat/channel ID |

4. Manual trigger: **Actions → ICT Forex Bias → Run workflow**

After each run, the workflow auto-commits `live_performance.jsonl` and `live_stats.json` using the built-in `GITHUB_TOKEN` — no extra secrets needed.

### TwelveData API usage

| Operation | API credits/day |
|-----------|-----------------|
| Morning signals (8 symbols × 1 req) | 8 credits |
| Record actual (8 symbols × 1 req) | 8 credits |
| Pre-London + Pre-NY H1 (8 × 2 sessions) | 16 credits |
| **Total** | **~32 credits** |

Free tier: 800 credits/day → **4% utilisation**.

---

## Dashboard (GitHub Pages)

A live monitoring dashboard is available at:

**`https://quici9.github.io/ict-forex-bias/`**

Built with vanilla HTML/CSS/JS and served from `docs/`. Reads `live_performance.jsonl` and `live_stats.json` directly — no backend required.

**Features:**
- Rolling 20-day precision gauge
- Per-symbol precision breakdown
- Signal history table with correct/incorrect indicators
- Auto-alert banner when `rolling_20d < 50%`

---

## Data Files

### `data/live_performance.jsonl`

Append-only JSONL log. One record per symbol per day.

```jsonc
// Prediction record (written at signal time)
{
  "date":        "2026-03-24",
  "day_of_week": "Monday",
  "symbol":      "EUR/USD",
  "predicted":   "BULLISH",
  "pattern":     "CONTINUATION",
  "close_pct":   0.2341,
  "confidence":  "NORMAL",
  "features": {
    "t2_high": 1.08524, "t2_low": 1.07801, "t2_close": 1.08012,
    "t1_high": 1.09340, "t1_low": 1.08600, "t1_close": 1.09021,
    "t1_body_ratio": 0.72, "t1_close_pct_of_t2_range": 1.69
  },
  "actual":      null,
  "correct":     null,
  "schema_v":    2,
  "logged_at":   "2026-03-22T22:15:00+00:00"
}

// After --record run (actual filled in)
{
  ...,
  "actual":     "BULLISH",
  "correct":    true,
  "updated_at": "2026-03-25T06:00:00+00:00"
}
```

### `data/live_stats.json`

Recomputed after every `--record` run.

```jsonc
{
  "last_updated":          "2026-03-25T06:00:00+00:00",
  "rolling_20d_precision": 0.65,
  "total_signals":         12,
  "total_correct":         8,
  "overall_precision":     0.667,
  "alert":                 false,
  "per_symbol": {
    "EUR/USD": { "precision": 0.70, "total": 5, "correct": 3 }
  }
}
```

### `data/h1_feature_log.jsonl`

H1 raw features logged per symbol per session (for future ML training). Written by `--pre-london` and `--pre-ny` runs.

---

## Monitoring & Alerts

### Live precision check

```bash
python scripts/v2/monitor.py
```

### Alert threshold

| Condition | Action |
|-----------|--------|
| `rolling_20d < 50%` for **2+ consecutive weeks** | Mandatory re-tune |
| Signal frequency `< 1.0/week` for **4+ weeks** | Investigate regime shift |
| Live precision `> 60%` for **3 months** | Consider reversal re-enablement |

**Do NOT re-tune if:**
- Single bad week (normal variance)
- Precision in 58–64% range (within expected bounds)
- GBP/JPY underperforms alone (known LOW confidence pair)

### Review schedule

| Date | Milestone |
|------|-----------|
| 2026-06-22 | First quarterly review |
| 2026-09-22 | Reversal re-evaluation (if live precision > 60%) |

---

## Infrastructure & Cost

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| TwelveData (free) | ~32 req/day | **$0** |
| GitHub Actions | ~4 runs/day × 2 min ≈ 240 min/month | **$0** (free: 2,000 min) |
| GitHub Pages | Static dashboard | **$0** |
| Telegram Bot API | ~4 messages/day | **$0** |
| **Total** | | **$0/month** |

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| V1: Rule-based weighted scoring | ❌ Retired | 17.8% precision ceiling |
| V1.5: Logistic Regression | ❌ Retired | ~17.8% — no additional edge |
| V2: D1 2-candle pattern | ✅ Complete | 57.4% precision |
| V3: Grid search + walk-forward | ✅ **Deployed** | 64.8%, 7/7 WF pass |
| Phase D: H1 confluence layer | ✅ Complete | Pre-session scoring, H1 feature logging |
| GitHub Pages dashboard | ✅ Complete | Live monitoring UI |
| Quarterly review | 🗓 2026-06-22 | Live precision review |
| Reversal re-evaluation | 🗓 2026-09-22 | Only if live precision > 60% |
| ML enhancement | 🗓 TBD | After sufficient labeled data |

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError` | venv not activated | `source .venv/bin/activate` |
| `[ERROR] TWELVEDATA_API_KEY not set` | Missing `.env` | Copy `.env.example` → `.env`, add key |
| `FileNotFoundError: settings_v3.yaml` | Wrong working directory | Run from project root |
| `H1 fetch failed — skipping` | TwelveData rate limit | Wait 60s and retry, or use `--dry-run` |
| Telegram not received | Token/Chat ID wrong | `curl https://api.telegram.org/bot{TOKEN}/getMe` |
| Empty data on weekend | Market closed | Normal — Forex closes Friday 22:00 UTC |
| `No pending predictions found` | Already recorded or no signal saved | Run morning signal generation first |

---

## Author

Built by **Neun Liam** · Deployed 2026-03-22 · [github.com/quici9/ict-forex-bias](https://github.com/quici9/ict-forex-bias)
