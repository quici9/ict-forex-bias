# ICT Forex Bias System — Production Status & Operations

**Version:** 3.0
**Last updated:** 2026-03-22
**Status:** DEPLOYED ✅
**First live signal:** 2026-03-24
**Next review:** 2026-06-22

---

## Lịch sử phát triển

| Phase | Nội dung | Kết quả |
|-------|---------|--------|
| V1: Rule-based weighted scoring | Market Structure + FVG + SMT + Liquidity Sweep | 17.8% — dưới random |
| V1.5: Logistic Regression | Train trên feature vector từ V1 | 17.8% — LR không thêm edge |
| V2: D1 2-candle pattern | Phát hiện continuation từ 2 nến D1 | 57.4% (+40pp) |
| R7–9: Grid search + walk-forward | Sweep `close_pct`, validate 7 WF windows | **64.8%, 7/7 pass** |
| R10: Data integrity check | Kiểm tra bug, xác nhận V3 | No bug — V3 confirmed |
| R11: `close_pct` sweep 0.00–0.35 | Tìm cải thiện freq | Freq gap structural, rejected |
| R12: H1 BOS/FVG layer | Add intraday confirmation | 49% — no edge |
| R13: `cp=0.00` walk-forward | Test ngưỡng thấp hơn | 6/7 pass, Win2025=53% < 55% floor, rejected |
| **Deploy V3** | `continuation_min_close_pct: 0.20` | **2026-03-22** ✅ |

---

## Cấu hình deployed (V3)

| Tham số | Giá trị |
|---------|--------|
| Mode | Continuation-Only (Reversal DISABLED) |
| `continuation_min_close_pct` | **0.20** |
| Config file | `config/settings_v3.yaml` |
| Data source | TwelveData (D1 interval) |
| Test precision | **64.8%** |
| Signal frequency | **2.08/symbol/week** (test) · 1.38 (long-run) |
| Walk-forward | **7/7 pass** · Min 57.8% · Sharpe 4.94 |

### Symbol tiers

| Tier | Symbols | Test precision |
|------|---------|---------------|
| HIGH | NZD/USD, USD/CAD, EUR/USD, USD/JPY | 66–73% |
| NORMAL | AUD/USD, USD/CHF, GBP/USD | 64–65% |
| LOW ⚠️ | GBP/JPY | 50% |

---

## Vận hành hàng ngày

### Tự động (GitHub Actions)

Workflow chạy 2 lần/ngày, Mon–Fri:

| Run | Cron UTC | Giờ VN | Tác vụ |
|-----|---------|--------|-------|
| London | `45 1 * * 1-5` | 08:45 | Record yesterday's actual → Generate signals |
| New York | `45 6 * * 1-5` | 13:45 | Generate signals (reminder) |

Sau mỗi run: tự commit `live_performance.jsonl` + `live_stats.json`.

### Thủ công (khi cần)

```bash
# Generate signals (predict next trading day)
python scripts/v2/daily_run.py

# Record actual outcome cho một ngày cụ thể
python scripts/v2/daily_run.py --record 2026-03-24

# Xem rolling stats
python scripts/v2/monitor.py stats
python scripts/v2/monitor.py stats --per-symbol
```

---

## Monitoring

### Alert triggers

| Trigger | Action |
|---------|--------|
| `rolling_20d < 50%` for **2 consecutive weeks** | Re-tune |
| Signal freq `< 1.0/wk` for **4+ weeks** | Investigate regime shift |
| Live precision `> 60%` for **3 months** | Evaluate reversal re-enablement |

### Không re-tune nếu

- Single bad week (normal variance)
- Precision 58–64% (trong expected backtest range)
- GBP/JPY underperforms (known LOW tier)
- No-signal days (bình thường — avg 1.38 signals/sym/wk long-run)

### Review schedule

| Date | Milestone |
|------|-----------|
| 2026-06-22 | Quarterly review — đánh giá rolling precision 3 tháng đầu |
| 2026-09-22 | Reversal re-evaluation (nếu live precision > 60%) |

---

## Quy trình re-tune (nếu cần)

Chỉ thực hiện khi alert trigger được kích hoạt.

1. **Xác nhận regime shift** — so sánh signal freq và precision với backtest period
2. **Walk-forward sweep** — test các giá trị `close_pct` mới trên train data (2019–2024)
3. **Validation rule:**
   - 7/7 WF windows pass, min precision ≥ 55% mỗi window
   - Frequency ≥ 1.5/sym/wk trên train set
4. **Deploy** — update `config/settings_v3.yaml`, ghi lại vào `data/tuning_state_v2.json`

Dữ liệu lịch sử để backtest: `data/backtest/*.csv` (2019–2026).

---

## Secrets cần cấu hình

### GitHub Actions (Settings → Secrets → Actions)

| Secret | Required | Mô tả |
|--------|---------|-------|
| `TWELVEDATA_API_KEY` | ✅ | TwelveData API key |
| `TELEGRAM_BOT_TOKEN` | Optional | Chỉ cần khi `telegram.enabled: true` |
| `TELEGRAM_CHAT_ID` | Optional | Chỉ cần khi `telegram.enabled: true` |

### Local (`.env`)

```
TWELVEDATA_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## Files quan trọng

| File | Mục đích |
|------|---------|
| `config/settings_v3.yaml` | Production config — chỉnh ở đây |
| `src/v2/pattern_scorer.py` | D1 pattern engine |
| `src/data/twelvedata_client.py` | TwelveData API client |
| `scripts/v2/daily_run.py` | Daily runner |
| `scripts/v2/monitor.py` | Live stats CLI |
| `data/live_performance.jsonl` | Signal log (predictions + actuals) |
| `data/live_stats.json` | Rolling precision stats |
| `data/tuning_state_v2.json` | Full deployment + tuning state |
| `data/backtest/` | Historical OHLCV CSVs (2019–2026) |
| `.github/workflows/run_analysis.yml` | GitHub Actions cron |
