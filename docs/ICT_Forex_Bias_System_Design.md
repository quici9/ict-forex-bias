# ICT Forex Bias System — System Design

**Version:** 3.0 (Production)
**Last updated:** 2026-03-22
**Status:** DEPLOYED ✅ — First live signal: 2026-03-24

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Non-goals](#2-goals--non-goals)
3. [Architecture Overview](#3-architecture-overview)
4. [Module Breakdown](#4-module-breakdown)
   - 4.1 [Scheduler — GitHub Actions](#41-scheduler--github-actions)
   - 4.2 [Data Pipeline](#42-data-pipeline)
   - 4.3 [Pattern Engine (D1)](#44-pattern-engine-d1)
   - 4.4 [Notification Layer](#45-notification-layer)
   - 4.5 [Persistence Layer](#46-persistence-layer)
5. [Data Model](#5-data-model)
6. [Signal Specification](#6-signal-specification)
7. [Error Handling Strategy](#7-error-handling-strategy)
8. [Repository Structure](#8-repository-structure)
9. [Configuration](#9-configuration)
10. [Infrastructure & Cost](#10-infrastructure--cost)
11. [Roadmap & History](#11-roadmap--history)
12. [Risks & Mitigations](#12-risks--mitigations)

---

## 1. Overview

**ICT Forex Bias System** là một pipeline tự động phân tích thị trường Forex theo phương pháp ICT (Inner Circle Trader), xác định Daily Bias (Bullish / Bearish / Neutral) cho 8 cặp tiền chính, và gửi kết quả qua Telegram.

Hệ thống được vận hành thủ công mỗi sáng. Trader chạy một lệnh duy nhất để nhận bias report và lưu prediction. Cuối ngày chạy thêm một lệnh để ghi actual outcome — giúp theo dõi precision live theo thời gian.

### Điều gì khác so với thiết kế gốc?

Thiết kế ban đầu (v1) sử dụng weighted feature scoring phức tạp (Market Structure + FVG + SMT + Liquidity Sweep). Sau 13 rounds backtesting (2019–2026), phương pháp đó đạt trần **17.8% precision** — không tốt hơn random.

V3 deployed dùng một pattern đơn giản hơn nhiều: **D1 2-candle Continuation**, đạt **64.8% precision** trên test set, 7/7 walk-forward pass.

---

## 2. Goals & Non-goals

### Goals

- Tự động fetch dữ liệu D1 từ TwelveData cho 8 cặp Forex
- Phát hiện D1 Continuation pattern (2-candle)
- Gửi Daily Bias report qua Telegram (optional — disabled bằng config)
- Theo dõi precision live: lưu predictions, record actuals, tính rolling stats
- Chạy được local với một lệnh duy nhất

### Non-goals

- Không tự động vào lệnh hay kết nối broker
- Không phân tích intraday (H4/H1/M15)
- Không cung cấp entry, stop loss, hay target cụ thể
- Không dùng ML/weighted scoring (đã thử, ceiling 17.8%)

---

## 3. Architecture Overview

```
GitHub Actions (cron) — Mon–Fri:

  ┌─ London run 01:45 UTC (08:45 VN) ─────────────────────┐
  │                                                         │
  │  1. Record yesterday's actual:                          │
  │     daily_run.py --record <prev_date>                   │
  │       → Fetch D1(prev_date) + D1(prev_date-1)          │
  │       → Compute actual BULLISH/BEARISH/NEUTRAL          │
  │       → Update live_performance.jsonl                   │
  │       → Recalculate live_stats.json                     │
  │                                                         │
  │  2. Generate today's signals:                           │
  │     daily_run.py                                        │
  │       → Fetch D1 last 5 candles × 8 symbols            │
  │       → classify_d1_pattern() → DailyBias per symbol   │
  │       → format_telegram_daily() → Send Telegram         │
  │       → Save predictions to live_performance.jsonl      │
  │                                                         │
  │  3. git commit + push live_performance.jsonl            │
  │                 live_stats.json                         │
  └─────────────────────────────────────────────────────────┘

  ┌─ NY run 06:45 UTC (13:45 VN) ──────────────────────────┐
  │                                                         │
  │  Generate today's signals (same as London — reminder)   │
  │  git commit + push                                      │
  └─────────────────────────────────────────────────────────┘
```

---

## 4. Module Breakdown

### 4.1 Scheduler — GitHub Actions

**File:** `.github/workflows/run_analysis.yml`

**Lịch chạy:**

| Run | Cron (UTC) | Giờ VN | Tác vụ |
|-----|-----------|--------|-------|
| London | `45 1 * * 1-5` | 08:45 | Record yesterday's actual + generate signals |
| New York | `45 6 * * 1-5` | 13:45 | Generate signals (reminder) |

Chỉ chạy Mon–Fri. Hỗ trợ `workflow_dispatch` để trigger thủ công từ GitHub UI.

**Secrets cần cấu hình trên GitHub (Settings → Secrets → Actions):**

| Secret | Bắt buộc | Mô tả |
|--------|---------|-------|
| `TWELVEDATA_API_KEY` | ✅ | TwelveData API key |
| `TELEGRAM_BOT_TOKEN` | Optional | Chỉ cần nếu `telegram.enabled: true` |
| `TELEGRAM_CHAT_ID` | Optional | Chỉ cần nếu `telegram.enabled: true` |

**Auto-commit:** Sau mỗi run, workflow tự commit `live_performance.jsonl` và `live_stats.json` lên repo. Dùng built-in `GITHUB_TOKEN` — không cần secret riêng.

**Record timing:** D1 Forex candles đóng lúc 22:00 UTC. London run (01:45 UTC ngày hôm sau) an toàn để record actual của ngày hôm trước — candle đã đóng 3.75 giờ trước.

---

### 4.2 Data Pipeline

**File:** `src/data/twelvedata_client.py`

**Mục đích:** Fetch OHLCV từ TwelveData REST API với rate limiting và retry.

**Cấu hình:**
- Free plan: 8 API credits/minute, 800/day
- Token-bucket limiter: giữ dưới 7 req/minute để có margin
- Max 5 retries per request, exponential backoff
- Rate-limit backoff: 65 seconds khi bị throttle

**Hàm chính:**

```python
fetch_time_series(
    symbol: str,          # "EUR/USD"
    interval: str,        # "1day"
    outputsize: int,      # số candles cần
    api_key: str,
) -> pd.DataFrame | None
```

Returns DataFrame với index UTC datetime, columns: Open, High, Low, Close, Volume.

Trả về `None` nếu tất cả retries fail — không raise exception.

**Timeframe dùng:**

| Timeframe | Interval | Outputsize | Mục đích |
|-----------|----------|-----------|---------|
| D1 | `1day` | 5 | Lấy T-2, T-1 để classify pattern |
| D1 | `1day` | 10 | Lấy actual D1 outcome khi record |

---

### 4.4 Pattern Engine (D1)

**File:** `src/v2/pattern_scorer.py`

Đây là core của toàn bộ hệ thống. Chứa tất cả logic: pattern classification, bias building, Telegram formatting.

#### 4.2.1 D1 2-candle Pattern

**Nguyên lý:** Dùng 2 candles D1 đã đóng (T-2 và T-1) để predict chiều của ngày tiếp theo (T).

```
T-2 candle  →  defines the reference range [Low₂, High₂]
T-1 candle  →  test where Close₁ lands relative to T-2 range
T   candle  →  the day we're predicting (not yet formed)
```

**Hàm:** `classify_d1_pattern(t1_high, t1_low, t1_close, t2_high, t2_low, ...)`

Check order (theo priority):

1. **Inside Bar:** `High₁ < High₂ AND Low₁ > Low₂` → `INSIDE_BAR`, NEUTRAL

2. **Reversal** (DISABLED in production):
   - Bullish reversal: `Low₁ < Low₂ − 0.4×Range₂ AND Low₂ < Close₁ < High₂`
   - Bearish reversal: `High₁ > High₂ + 0.4×Range₂ AND Low₂ < Close₁ < High₂`
   - _Tất cả reversal patterns bị downgrade về NEUTRAL (35% precision — sub-random)_

3. **Continuation** ← signal duy nhất được phát:
   - Bullish: `Close₁ > High₂ + 0.20 × Range₂`
   - Bearish: `Close₁ < Low₂ − 0.20 × Range₂`

4. **No Pattern** → NEUTRAL

**Tham số deployed:**

| Parameter | Value | Ghi chú |
|-----------|-------|--------|
| `continuation_min_close_pct` | 0.20 | Close phải vượt 20% ngoài T-2 range |
| `reversal_min_wick_pct` | 0.40 | Inactive (reversal disabled) |
| `reversal_body_ratio` | 0.50 | Inactive |

#### 4.2.2 Build Daily Bias

**Hàm:** `build_daily_bias(symbol, prediction_date, t1_*, t2_*, continuation_min_close_pct)`

1. Gọi `classify_d1_pattern()` để lấy raw pattern
2. Nếu `CONTINUATION` → emit BULLISH/BEARISH
3. Tất cả pattern khác (kể cả REVERSAL) → NEUTRAL
4. Tính `close_pct_beyond`: mức độ close vượt ngoài range, dùng để sort signals
5. Gán confidence tier: `LOW` nếu GBP/JPY (50% precision trong test set)

**Returns:** `DailyBias` dataclass

#### 4.2.3 Confidence Tiers

| Tier | Symbols | Precision (test) | Emoji |
|------|---------|-----------------|-------|
| NORMAL | 7 pairs (tất cả trừ GBP/JPY) | 64.8% avg | 🟢/🔴 |
| LOW | GBP/JPY | 50% | 🟡/🟠 |

#### 4.2.4 Actual Bias Definition

Dùng để record outcome (không phải để predict):

```
BULLISH = High(DATE) > High(DATE-1) AND Low(DATE) > Low(DATE-1)
BEARISH = High(DATE) < High(DATE-1) AND Low(DATE) < Low(DATE-1)
NEUTRAL = everything else (one side higher, one side lower)
```

---

### 4.5 Notification Layer

**File:** `src/v2/pattern_scorer.py` — `format_telegram_daily()`

**Message format:**

```
📅 *Daily Bias — Mon 24 Mar 2026*
──────────────────────────────────
🟢 NZD/USD  BULLISH  `[Continuation]`
   Close +27% beyond High(T-2)
🔴 USD/CAD  BEARISH  `[Continuation]`
   Close −22% beyond Low(T-2)
──────────────────────────────────
🟡 GBP/JPY  BULLISH  `[Continuation]` ⚠️
   ⚠️ GBP/JPY 50% precision (test set)
   Close +31% beyond High(T-2)
──────────────────────────────────
🎯 *Top picks*: NZD/USD, USD/CAD
   Continuation • 64.8% precision
```

**Sort order:**
1. NORMAL confidence signals, sorted by `close_pct_beyond` descending
2. LOW confidence signals (GBP/JPY)
3. NEUTRAL omitted

**Telegram config** (trong `settings_v3.yaml`):

```yaml
telegram:
  enabled: false   # true khi bot đã setup
  bot_token: ""    # hoặc env var TELEGRAM_BOT_TOKEN
  chat_id: ""      # hoặc env var TELEGRAM_CHAT_ID
```

---

### 4.6 Persistence Layer

**Files:**
- `data/live_performance.jsonl` — append-only signal log
- `data/live_stats.json` — rolling stats, recalculated sau mỗi --record

#### Prediction record schema (khi chạy sáng)

```json
{
  "date":       "2026-03-24",
  "symbol":     "EUR/USD",
  "predicted":  "BULLISH",
  "pattern":    "CONTINUATION",
  "close_pct":  0.2341,
  "confidence": "NORMAL",
  "actual":     null,
  "correct":    null,
  "logged_at":  "2026-03-22T22:15:00+00:00"
}
```

#### Actual record schema (sau --record)

```json
{
  "date":       "2026-03-24",
  "symbol":     "EUR/USD",
  "predicted":  "BULLISH",
  "pattern":    "CONTINUATION",
  "close_pct":  0.2341,
  "confidence": "NORMAL",
  "actual":     "BULLISH",
  "correct":    true,
  "logged_at":  "2026-03-22T22:15:00+00:00",
  "updated_at": "2026-03-25T06:00:00+00:00"
}
```

#### live_stats.json schema

```json
{
  "last_updated":          "2026-03-25T06:00:00+00:00",
  "rolling_20d_precision": 0.65,
  "total_signals":         12,
  "total_correct":         8,
  "overall_precision":     0.667,
  "alert":                 false,
  "per_symbol": {
    "EUR/USD": {"precision": 0.70, "total": 5, "correct": 3}
  }
}
```

**Alert:** `rolling_20d_precision < 0.50` khi có đủ 20 records.

---

## 5. Data Model

```python
@dataclass
class DailyBias:
    """Core output of the pattern engine."""
    symbol: str
    date: date
    pattern: str             # CONTINUATION | NONE
    bias: str                # BULLISH | BEARISH | NEUTRAL
    confidence: str          # NORMAL | LOW
    confidence_note: str     # "" hoặc warning text
    t1_high: float
    t1_low: float
    t1_close: float
    t2_high: float
    t2_low: float
    close_pct_beyond: float  # cách bao xa khỏi T-2 range (0.0 nếu NEUTRAL)
    message: str             # human-readable explanation


@dataclass
class SessionSignal:
    """H1 market structure signal — hiện không dùng trong production."""
    symbol: str
    session: str          # London | NY
    d1_bias: str          # BULLISH | BEARISH
    signal: str           # CONFIRM | WARN | FLIP | NO_SIGNAL
    bos: Optional[str]
    choch: Optional[str]
    fvg_levels: list[float]
    message: str
```

---

## 6. Signal Specification

### 6.1 Pattern parameters (deployed V3)

```yaml
d1_pattern:
  continuation_min_close_pct: 0.20   # ACTIVE
  reversal_min_wick_pct: 0.40        # inactive (reversal disabled)
  reversal_body_ratio: 0.50          # inactive
```

### 6.2 Performance (backtest)

| Metric | Value | Period |
|--------|-------|--------|
| Test precision | 64.8% | 2025-07-01 → 2026-03-21 |
| Signal frequency | 2.08/symbol/week | Test period |
| Signal frequency (long-run) | 1.38/symbol/week | 2019–2026 |
| Walk-forward | 7/7 pass | Annual windows 2020–2026 |
| Min WF precision | 57.8% | Worst window |
| Sharpe | 4.94 | Simulated |

### 6.3 Per-symbol precision (test set)

| Symbol | Precision | Tier |
|--------|-----------|------|
| NZD/USD | 72.9% | HIGH |
| USD/CAD | 66.7% | HIGH |
| USD/JPY | 66.3% | HIGH |
| EUR/USD | 66.2% | HIGH |
| AUD/USD | 64.8% | NORMAL |
| USD/CHF | 64.3% | NORMAL |
| GBP/USD | 64.2% | NORMAL |
| GBP/JPY | 50.0% | LOW ⚠️ |

### 6.4 Monitoring thresholds

| Trigger | Action |
|---------|--------|
| `rolling_20d < 50%` for 2+ consecutive weeks | Re-tune |
| Signal freq `< 1.0/wk` for 4+ weeks | Investigate regime shift |
| Live precision `> 60%` for 3 months | Consider reversal re-enablement |

**Do NOT re-tune if:** single bad week, precision 58–64% (normal variance), GBP/JPY underperforms.

---

## 7. Error Handling Strategy

| Category | Handling |
|----------|---------|
| TwelveData fetch failure | Retry 5 lần, skip symbol nếu vẫn fail |
| Insufficient data | Skip symbol, log warning, continue với symbols còn lại |
| Rate limit hit | Wait 65 seconds, auto-retry |
| Telegram send failure | Log error, không block main flow |
| `--record` với date không có data | Log warning per symbol, skip |

**Graceful degradation:** Nếu 3/8 symbols fail → pipeline vẫn chạy và output 5 symbols còn lại.

---

## 8. Repository Structure

```
ict_forex_bias/
│
├── .github/
│   └── workflows/
│       └── run_analysis.yml       # Cron: London 01:45 UTC + NY 06:45 UTC, Mon–Fri
│
├── src/
│   ├── v2/
│   │   └── pattern_scorer.py      # D1 pattern engine, DailyBias, Telegram formatter
│   └── data/
│       └── twelvedata_client.py   # TwelveData API client (rate-limited)
│
├── scripts/
│   └── v2/
│       ├── daily_run.py           # Daily runner: generate signals + record actuals
│       └── monitor.py             # CLI: view rolling stats, per-symbol breakdown
│
├── config/
│   └── settings_v3.yaml           # Production config (pattern params + Telegram)
│
├── data/
│   ├── live_performance.jsonl     # Predictions + actuals log (append-only)
│   ├── live_stats.json            # Rolling precision stats
│   ├── tuning_state_v2.json       # Full deployment + tuning history
│   └── backtest/                  # Historical OHLCV CSVs 2019–2026 (TwelveData)
│       ├── EURUSDX_1d.csv
│       └── ...
│
├── docs/
│   ├── ICT_Forex_Bias_System_Design.md    # Tài liệu này
│   └── ICT_Forex_Bias_System_Action_Plan.md
│
├── tests/
│   └── fixtures/                  # Sample OHLCV data cho unit tests
│
├── .env                           # TWELVEDATA_API_KEY, TELEGRAM_* (gitignored)
├── .env.example
├── requirements.txt
└── README.md
```

---

## 9. Configuration

**File:** `config/settings_v3.yaml` — file config duy nhất cần chỉnh.

```yaml
use_pattern_scorer: true

signal_config:
  mode: "continuation_only"
  reversal_mode: "disabled"
  low_confidence_symbols:
    - "GBP/JPY"

d1_pattern:
  continuation_min_close_pct: 0.2
  reversal_min_wick_pct: 0.4     # inactive
  reversal_body_ratio: 0.5       # inactive

monitoring:
  rolling_window_days: 20
  alert_threshold: 0.50
  review_date: "2026-06-22"

telegram:
  enabled: false
  bot_token: ""    # hoặc env var TELEGRAM_BOT_TOKEN
  chat_id: ""      # hoặc env var TELEGRAM_CHAT_ID
```

**Secrets local** (trong `.env`, không commit):

```
TWELVEDATA_API_KEY=...
TELEGRAM_BOT_TOKEN=...    # optional
TELEGRAM_CHAT_ID=...      # optional
```

**Secrets GitHub Actions** (Settings → Secrets → Actions):

| Secret | Required | Note |
|--------|---------|------|
| `TWELVEDATA_API_KEY` | ✅ | |
| `TELEGRAM_BOT_TOKEN` | Optional | Chỉ cần khi `telegram.enabled: true` |
| `TELEGRAM_CHAT_ID` | Optional | Chỉ cần khi `telegram.enabled: true` |

---

## 10. Infrastructure & Cost

| Service | Usage | Cost |
|---------|-------|------|
| TwelveData (free plan) | ~16 req/day (8 symbols × 2 runs) | $0/month |
| GitHub Actions | ~2 runs/day × 2 min ≈ 120 min/month | $0/month (free: 2,000 min) |
| Telegram Bot API | 2 messages/day | $0/month |

**TwelveData free tier:** 800 credits/day. Mỗi run dùng 8 credits (8 symbols × 1 req). 2 runs/ngày = 16 credits. `--record` thêm 8 credits/ngày nữa = tổng ~24 credits/ngày. Còn dư 776 credits cho manual checks.

**GitHub Actions:** ~120 min/month / 2,000 min free tier = **6%**. $0/month.

---

## 11. Roadmap & History

### Đã hoàn thành

| Phase | Kết quả |
|-------|--------|
| V1: Rule-based weighted scoring | 17.8% ceiling — không vượt random |
| V1.5: Logistic Regression | Cũng ~17.8% — LR không thêm edge |
| V2: D1 2-candle pattern | 57.4% precision (+40pp over V1) |
| V3: Grid search + walk-forward | **64.8%**, 7/7 WF pass, Sharpe 4.94 |
| R10: Data integrity check | Không có bug data — V3 confirmed |
| R11: `close_pct` sweep 0.00–0.35 | Freq gap là structural, không improve được |
| R12: H1 BOS/FVG layer | 49% — không có edge, skip |
| R13: `cp=0.00` walk-forward | 6/7 pass, Win2025=53% < 55% floor, rejected |
| **Deploy V3** | 2026-03-22 ✅ |

### Upcoming

| Date | Milestone |
|------|-----------|
| 2026-06-22 | First quarterly review (rolling_20d precision) |
| 2026-09-22 | Reversal re-evaluation (nếu live precision > 60%) |
| TBD | Re-tune nếu rolling_20d < 50% for 2 consecutive weeks |

---

## 12. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| TwelveData trả về wrong/stale data | Low | High | Check số candles, validate timestamps, so sánh thủ công định kỳ |
| Look-ahead bias khi re-tune | High (nếu không cẩn thận) | High | Walk-forward validation bắt buộc; chỉ dùng test set để confirm |
| Over-tuning sau bad week | Medium | Medium | Monitoring rules rõ ràng: chỉ retune sau `rolling_20d < 50%` for 2+ weeks |
| Regime shift (market changes character) | Medium | Medium | Rolling window 20 days sẽ detect sớm; alert threshold 50% |
| GBP/JPY false signals | High (known) | Low | Marked as LOW confidence tier; trader đã biết |
| Continuation freq giảm (ranging market) | Medium | Low | Bình thường — không có signal = không trade = đúng rồi |
