# ICT Forex Bias System — Action Plan

**Version:** 1.0  
**Last updated:** 2026-03-21  
**Based on:** System Design v1.0  
**Estimated total duration:** 2–3 weeks (part-time)

---

## Nguyên tắc thực hiện

- **Vertical slices over horizontal layers** — mỗi phase phải tạo ra thứ gì đó chạy được và testable, không build toàn bộ một layer rồi mới sang layer tiếp theo.
- **Config-first** — viết `settings.yaml` và data models trước khi viết bất kỳ logic nào.
- **Test locally trước khi push** — mỗi module phải chạy được bằng `run_local.py` trước khi wire vào GitHub Actions.
- **Không optimize sớm** — ưu tiên correctness trước, performance sau. Pipeline chỉ chạy 2 lần/ngày, 90 giây là đủ.
- **Commit nhỏ, thường xuyên** — mỗi commit là một đơn vị công việc có thể revert độc lập.

---

## Phase 0 — Project Setup

**Mục tiêu:** Repo sạch, môi trường dev sẵn sàng, skeleton structure đúng.  
**Estimated time:** 2–4 giờ  
**Deliverable:** Repo chạy được `python src/main.py` dù chưa có logic gì.

---

### Task 0.1 — Khởi tạo repo

- [ ] Tạo GitHub repo mới (private hoặc public tuỳ preference)
- [ ] Tạo toàn bộ folder structure theo System Design Section 9
- [ ] Tạo `__init__.py` cho tất cả các Python packages
- [ ] Tạo `.gitignore` — bao gồm `.env`, `__pycache__`, `.pytest_cache`, `*.pyc`
- [ ] Tạo `.env.example` với placeholder values

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

---

### Task 0.2 — Python environment

- [ ] Tạo `requirements.txt` với các dependencies cần thiết:
  - `yfinance` — data fetching
  - `pandas` — data manipulation
  - `numpy` — numerical computation
  - `pyyaml` — đọc settings.yaml
  - `python-dotenv` — load .env cho local dev
  - `requests` — Telegram API calls
  - `pytest` — testing
- [ ] Tạo virtual environment local: `python -m venv .venv`
- [ ] Verify install không có conflict: `pip install -r requirements.txt`

---

### Task 0.3 — Config skeleton

- [ ] Tạo `config/settings.yaml` đầy đủ theo System Design Section 10
  - Instruments list với SMT pairs
  - Scoring weights (dùng default values trong design)
  - Thresholds, multipliers
  - Feature parameters (swing_lookback, fvg_lookback, v.v.)
  - Data parameters (số candles mỗi TF)
- [ ] Tạo `src/config.py` — module load và validate settings.yaml, expose typed config object cho toàn bộ codebase dùng chung

---

### Task 0.4 — Data models

- [ ] Tạo `src/models.py` — định nghĩa toàn bộ dataclasses theo System Design Section 5:
  - `InstrumentData`
  - `InstrumentFeatures`
  - `InstrumentScore`
  - `RunResult` (wrapper cho toàn bộ một lần chạy)
- [ ] Đây là bước quan trọng nhất của Phase 0 — models phải đúng trước khi viết bất kỳ logic nào

---

### Task 0.5 — Entry point skeleton

- [ ] Tạo `src/main.py` với orchestration skeleton:
  ```
  load_config()
  fetch_data()       → placeholder, return empty
  calculate_features() → placeholder, return empty
  score()            → placeholder, return empty
  notify()           → placeholder, log to stdout
  persist()          → placeholder
  ```
- [ ] Tạo `scripts/run_local.py` — load `.env` rồi gọi `src/main.py`
- [ ] Verify: `python scripts/run_local.py` chạy không lỗi (dù chưa làm gì)

---

### Phase 0 — Definition of Done

- [ ] `python scripts/run_local.py` chạy thành công end-to-end (dù toàn bộ là stubs)
- [ ] Folder structure đúng với System Design
- [ ] `settings.yaml` đầy đủ tất cả fields
- [ ] Data models đầy đủ tất cả fields

---

## Phase 1 — Data Pipeline

**Mục tiêu:** Fetch và validate OHLCV data cho tất cả instruments, resample H1 → H4.  
**Estimated time:** 1–2 ngày  
**Deliverable:** Có thể in ra DataFrame D1/H4/H1 cho bất kỳ instrument nào.

---

### Task 1.1 — yfinance fetcher

- [ ] Viết `src/data/fetcher.py`:
  - Hàm fetch OHLCV cho một symbol và một interval
  - Retry logic: tối đa 3 lần, exponential backoff (1s, 2s, 4s)
  - Delay 0.5s giữa mỗi request để tránh rate limit
  - Return `None` nếu tất cả retries đều fail (không raise exception)
- [ ] Xử lý đặc thù của yfinance:
  - Column names có thể là MultiIndex khi fetch nhiều symbols — normalize về single-level
  - Timezone handling: convert tất cả timestamps về UTC

---

### Task 1.2 — H4 resampler

- [ ] Viết `src/data/resampler.py`:
  - Nhận H1 DataFrame, trả về H4 DataFrame
  - OHLCV aggregation rules: Open=first, High=max, Low=min, Close=last, Volume=sum
  - Dùng `pandas.resample('4h', offset='0h')` — cần test kỹ offset để candle H4 align đúng với trading sessions
  - Drop candles H4 không đủ 4 candles H1 (incomplete candle ở cuối)

---

### Task 1.3 — ATR calculation

- [ ] Viết utility function `calculate_atr(df, period=14)` trong `src/data/fetcher.py` hoặc tách ra `src/utils.py`:
  - True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
  - ATR = EMA(TR, period)
  - Return float (ATR value của candle cuối cùng)

---

### Task 1.4 — Data validator

- [ ] Viết `src/data/validator.py`:
  - Kiểm tra số candles tối thiểu (D1≥30, H4≥20, H1≥24, W1≥10)
  - Kiểm tra NaN — drop rows, re-check count
  - Kiểm tra stale data — candle cuối cách hiện tại > 2 ngày trading → flag `stale_data`
  - Kiểm tra anomalous candle — body > 5% của close → flag nhưng không skip
  - Return `ValidationResult(is_valid: bool, errors: list[str], warnings: list[str])`

---

### Task 1.5 — Pipeline orchestration

- [ ] Viết `src/data/pipeline.py` — hàm `fetch_all_instruments(config)`:
  - Loop qua tất cả enabled instruments trong config
  - Fetch D1, H1 (cho cả H4 resample), W1
  - Fetch DXY riêng
  - Validate từng instrument
  - Return `dict[symbol, InstrumentData]` — instruments fail validation vẫn được include với `is_valid=False`
- [ ] Wire vào `src/main.py` thay thế placeholder

---

### Task 1.6 — Local testing

- [ ] Chạy `python scripts/run_local.py` và verify:
  - Tất cả 8 instruments được fetch thành công
  - DataFrame D1, H4, H1 có đúng số candles
  - ATR được tính cho tất cả instruments
  - Validation pass cho tất cả
- [ ] Print sample output để confirm data trông hợp lý (không phải NaN, giá Forex range đúng)

---

### Phase 1 — Definition of Done

- [ ] Fetch thành công 8 instruments × 3 timeframes
- [ ] H4 resample hoạt động đúng
- [ ] Validation catch được data lỗi
- [ ] ATR được tính cho tất cả instruments
- [ ] Không có unhandled exceptions khi chạy local

---

## Phase 2 — Feature Engine

**Mục tiêu:** Tính toán đầy đủ tất cả ICT features cho mỗi instrument.  
**Estimated time:** 3–5 ngày (phần phức tạp nhất)  
**Deliverable:** Với mỗi instrument, in ra được một `InstrumentFeatures` object đầy đủ.

> **Quan trọng:** Mỗi sub-module trong Phase 2 nên có unit tests riêng với fixture data trước khi tích hợp. Dùng file CSV sample trong `tests/fixtures/` làm input.

---

### Task 2.1 — Swing point detection (foundation)

- [ ] Viết `detect_swings(df, lookback=5)` trong `src/features/market_structure.py`:
  - Trả về list các `SwingPoint(index, price, type)` trong đó type là `HIGH` hoặc `LOW`
  - Điều kiện swing high: `df['high'][i]` là max trong window `[i-lookback, i+lookback]`
  - Điều kiện swing low: tương tự với `df['low'][i]`
  - **Lưu ý:** Không dùng candle cuối cùng làm swing point (look-ahead bias) — chỉ xét đến `len(df) - lookback - 1`
- [ ] Unit test: verify swing points được detect đúng trên sample data

---

### Task 2.2 — Market Structure

- [ ] Viết `src/features/market_structure.py`:
  - `detect_structure(swings)` → xác định HH/HL (Bullish), LH/LL (Bearish), hoặc Mixed (Ranging)
  - `calculate_d1_structure(d1_df, config)` → trả về `(direction: float, clarity: float)`
  - `calculate_h4_structure(h4_df, config)` → tương tự
  - `check_structure_alignment(d1_structure, h4_structure)` → Bool
  - `detect_bos(swings, df)` → Bool — BOS trong N candles gần nhất
  - `detect_choch(swings, df)` → Bool — CHoCH trong N candles gần nhất
- [ ] Unit tests với các scenario:
  - Clear uptrend (3 HH + 3 HL)
  - Clear downtrend (3 LH + 3 LL)
  - Ranging market (alternating)
  - BOS xảy ra ở candle cuối

---

### Task 2.3 — Premium & Discount Zone

- [ ] Viết sub-module trong `src/features/pd_arrays.py`:
  - `find_dealing_range(swings, direction)` → `(swing_high_price, swing_low_price)`
  - `calculate_price_zone(current_price, dealing_range)` → float [-1, 1]
    - 1.0 = deep discount (gần swing low)
    - -1.0 = deep premium (gần swing high)
    - 0.0 = at equilibrium (50%)
  - `calculate_zone_strength(current_price, dealing_range)` → float [0, 1]
- [ ] Unit tests: verify zone calculation với known prices và ranges

---

### Task 2.4 — Fair Value Gap (FVG)

- [ ] Viết sub-module trong `src/features/pd_arrays.py`:
  - `detect_fvgs(df, atr14, config)` → list các `FVG(top, bottom, direction, candle_index, is_filled)`
  - Logic 3-candle pattern như đã mô tả trong System Design
  - Displacement check: body của candle giữa ≥ `fvg_min_displacement × atr14`
  - `is_fvg_filled(fvg, df)` → Bool — kiểm tra giá đã chạm vào midpoint của gap chưa
  - `get_active_fvgs(df, atr14, config)` → chỉ trả về FVGs chưa fill, trong N candles gần nhất
  - Trả về features: `fvg_exists`, `fvg_direction`, `fvg_size_normalized`
- [ ] Unit tests:
  - 3-candle pattern tạo bullish FVG
  - 3-candle pattern tạo bearish FVG
  - FVG bị fill không được return
  - Displacement nhỏ hơn threshold không được count

---

### Task 2.5 — PDH/PDL

- [ ] Viết sub-module trong `src/features/pd_arrays.py`:
  - `get_pdh_pdl(d1_df)` → `(pdh: float, pdl: float)` — high và low của D1 candle trước
  - `check_near_level(current_price, level, atr14, threshold_multiplier)` → Bool
  - `check_swept_level(d1_df, level)` → Bool — wick vượt qua nhưng close không vượt

---

### Task 2.6 — Liquidity Sweep

- [ ] Viết `src/features/liquidity.py`:
  - Reuse `detect_swings()` từ Task 2.1 để identify swing points quan trọng
  - `detect_sweep(df, swings, config)` → `SweepResult(occurred: bool, direction: float, age: int)`
  - Điều kiện sweep (dùng default conservative approach — candle close vượt rồi reverse):
    - Candle `i` close vượt qua swing point
    - Candle `i+1` engulf ngược chiều (close về phía bên kia)
    - Hoặc: wick vượt swing point, body nằm bên trong — đây sẽ là configurable setting sau
  - `age` = số candles từ sweep đến candle hiện tại
- [ ] Unit tests:
  - Sweep xảy ra và được detect
  - Near-miss (wick chạm gần nhưng không sweep) không được count
  - Sweep cũ hơn lookback không được count

---

### Task 2.7 — SMT Divergence

- [ ] Viết `src/features/smt.py`:
  - `calculate_smt(instrument_df, partner_df, config)` → `SMTResult(signal: bool, direction: float, timeframe: str)`
  - So sánh swing lows (cho bullish SMT) hoặc swing highs (cho bearish SMT)
  - Hai swings phải trong window `smt_max_candle_diff` của nhau
  - Handle trường hợp partner data không available → return `SMTResult(signal=False, ...)`
  - **Lưu ý về DXY:** USDCAD dùng DXY làm partner, nhưng DXY là dollar index (không phải Forex pair) — cần invert direction khi so sánh
- [ ] Unit tests:
  - Bullish SMT: pair A lower low, pair B không lower low
  - Bearish SMT: pair A higher high, pair B không higher high
  - Không có SMT khi cả hai đồng thuận

---

### Task 2.8 — W1 Direction (cho multiplier)

- [ ] Viết `calculate_w1_direction(w1_df, config)` trong `src/features/market_structure.py`:
  - Reuse `detect_swings()` và `detect_structure()` trên W1 data
  - Return float [-1, 1] — chỉ dùng magnitude và sign, không return clarity score
  - Ranging threshold: nếu structure clarity < 0.4 → return 0.0 (neutral/ranging)

---

### Task 2.9 — Feature aggregator

- [ ] Viết `src/features/aggregator.py`:
  - Hàm `calculate_all_features(instrument_data, partner_data, dxy_data, config)` → `InstrumentFeatures`
  - Gọi tất cả sub-modules từ Tasks 2.2–2.8
  - Handle `None` return từ bất kỳ sub-module nào — log warning, tiếp tục với None value
  - Wire vào `src/main.py`
- [ ] Integration test: chạy aggregator trên real fetched data, verify không có unhandled exceptions

---

### Phase 2 — Definition of Done

- [ ] Tất cả features được tính cho 8 instruments
- [ ] Không có look-ahead bias (verify bằng code review — không dùng `df.iloc[-1]` cho signal generation)
- [ ] Unit tests pass cho tất cả sub-modules
- [ ] `InstrumentFeatures` object được populated đầy đủ (không có unexpected None values)
- [ ] Kết quả trên D1 data nhìn hợp lý khi compare thủ công với chart

---

## Phase 3 — Scoring Layer

**Mục tiêu:** Tính điểm và xác định bias label cho mỗi instrument.  
**Estimated time:** 1 ngày  
**Deliverable:** Có thể print ra ranked list với scores.

---

### Task 3.1 — Core scorer

- [ ] Viết `src/scoring/scorer.py`:
  - `score_instrument(features, config)` → `InstrumentScore`
  - Tính `bullish_score` và `bearish_score` riêng biệt:
    - Với mỗi feature: nếu feature đồng chiều với hypothesis → contribute positive; ngược chiều → contribute negative (hoặc zero, tuỳ thiết kế)
    - Nhân với weight từ config
  - `final_score = max(bullish_score, bearish_score) × 100`
  - Áp dụng W1 multiplier
  - Assign bias label theo thresholds trong config

---

### Task 3.2 — Low-volatility filter

- [ ] Thêm vào scorer:
  - Tính rolling average ATR(14) của 20 ngày (`atr_avg_20d`)
  - Nếu `atr14_current < low_vol_threshold × atr_avg_20d` → overwrite bias label thành `LOW_VOL`
  - Lưu ý: cần pass thêm D1 historical data vào scorer để tính `atr_avg_20d`

---

### Task 3.3 — Top signals extractor

- [ ] Thêm vào scorer:
  - `extract_top_signals(features, bias_direction)` → `list[str]` tối đa 4 strings
  - Chọn các features có contribution cao nhất và active
  - Format thành human-readable strings cho Telegram message
  - Ví dụ: `"D1 downtrend rõ (3 LH+LL)"`, `"FVG H4 chưa fill @ 1.2680"`, `"Sell-side swept 2H ago"`

---

### Task 3.4 — Batch scorer

- [ ] Viết `score_all(features_dict, config)` → `list[InstrumentScore]` sorted by score descending:
  - Filter out NEUTRAL và LOW_VOL (hoặc để ở cuối, tùy preference)
  - Wire vào `src/main.py`

---

### Task 3.5 — Scoring unit tests

- [ ] Test các scenario:
  - All features aligned bullish → score cao, label BULLISH
  - Mixed signals → score thấp, label NEUTRAL hoặc WATCHLIST
  - Counter-trend (D1 bull nhưng W1 bear) → multiplier 0.75 applied
  - Low volatility → overwrite thành LOW_VOL

---

### Phase 3 — Definition of Done

- [ ] Scores được tính đúng theo formula
- [ ] W1 multiplier applied đúng
- [ ] Low-vol filter hoạt động
- [ ] `[CTrend]` flag được set đúng
- [ ] Output list sorted by score descending
- [ ] Unit tests pass

---

## Phase 4 — Notification Layer

**Mục tiêu:** Format và gửi Telegram message.  
**Estimated time:** 4–6 giờ  
**Deliverable:** Nhận được Telegram message đúng format khi chạy local.

---

### Task 4.1 — Telegram Bot setup

- [ ] Tạo bot mới qua `@BotFather` trên Telegram
- [ ] Lưu `BOT_TOKEN` vào `.env`
- [ ] Gửi một tin nhắn cho bot, gọi `https://api.telegram.org/bot{TOKEN}/getUpdates` để lấy `CHAT_ID`
- [ ] Lưu `CHAT_ID` vào `.env`
- [ ] Verify bằng cách gọi API trực tiếp từ terminal: gửi "Hello" và xác nhận nhận được

---

### Task 4.2 — Message formatter

- [ ] Viết `src/notify/formatter.py`:
  - `format_report(scores, session, timestamp, config)` → `str`
  - Session header với tên Kill Zone và giờ VN
  - Group scores thành 3 sections: high conviction (≥70), watchlist (50–69), skipped (<50)
  - Emoji prefix: 🟢/🔴 cho high conviction, ⚪ cho watchlist, ⏭️ cho skipped
  - Top pick section: expand chi tiết cho instrument có score cao nhất
  - Counter-trend badge `[CTrend]`
  - Escape các ký tự đặc biệt nếu dùng MarkdownV2 (`.`, `-`, `(`, `)`, v.v.)

---

### Task 4.3 — Telegram sender

- [ ] Viết `src/notify/telegram.py`:
  - `send_message(text, bot_token, chat_id)` → Bool
  - Dùng `requests.post` đến `https://api.telegram.org/bot{TOKEN}/sendMessage`
  - Parse mode: plain text (tránh escape issues) — có thể upgrade lên MarkdownV2 sau
  - Retry logic: 3 lần, exponential backoff
  - Return `True` nếu thành công, `False` nếu fail sau tất cả retries (không raise)

---

### Task 4.4 — Error notification

- [ ] Thêm hàm `send_error_report(errors, bot_token, chat_id)`:
  - Gửi message ngắn khi pipeline gặp lỗi nghiêm trọng
  - Format: `⚠️ Bias bot error — London KZ\n{error_summary}`
  - Đảm bảo hàm này được gọi ngay cả khi main pipeline crash

---

### Task 4.5 — End-to-end local test

- [ ] Chạy full pipeline local: `python scripts/run_local.py`
- [ ] Verify nhận được Telegram message đúng format
- [ ] Check tất cả sections hiển thị đúng
- [ ] Check timestamp đúng timezone VN

---

### Phase 4 — Definition of Done

- [ ] Telegram message nhận được khi chạy local
- [ ] Format đúng với System Design Section 4.5
- [ ] Error notification hoạt động khi có exception
- [ ] Không có unhandled exceptions trong notification layer

---

## Phase 5 — Persistence Layer

**Mục tiêu:** Lưu kết quả mỗi run vào `history.json`.  
**Estimated time:** 2–3 giờ  
**Deliverable:** `history.json` được update sau mỗi lần chạy.

---

### Task 5.1 — JSON writer

- [ ] Viết `src/persist.py`:
  - `load_history(path)` → parse `history.json`, return list of runs (empty list nếu file không tồn tại)
  - `append_run(history, run_result)` → thêm run mới vào đầu list
  - `trim_history(history, max_runs=90)` → giữ tối đa 90 runs gần nhất
  - `save_history(history, path)` → write ra file với `indent=2`
  - `build_run_result(scores, session, start_time, end_time, errors)` → `RunResult` object serializable thành JSON

---

### Task 5.2 — Serialization

- [ ] Đảm bảo tất cả dataclasses có thể serialize sang JSON:
  - Viết `to_dict()` method hoặc dùng `dataclasses.asdict()`
  - Handle `numpy` types (np.float64, np.bool_) — yfinance trả về numpy types, JSON serializer không hiểu → cần convert về Python native types
  - Handle `pandas.Timestamp` → convert về ISO string

---

### Task 5.3 — Wire vào main pipeline

- [ ] Update `src/main.py`: gọi persist sau notification
- [ ] Verify `history.json` được tạo và updated sau mỗi lần chạy local
- [ ] Verify structure của JSON đúng với schema trong System Design Section 4.6

---

### Phase 5 — Definition of Done

- [ ] `history.json` được tạo khi chưa tồn tại
- [ ] Mỗi run append một entry mới
- [ ] Trim hoạt động đúng (không vượt quá 90 runs)
- [ ] JSON valid và đúng schema
- [ ] Numpy/Pandas types được serialized đúng

---

## Phase 6 — GitHub Actions

**Mục tiêu:** Tự động hoá pipeline chạy theo lịch trên GitHub Actions.  
**Estimated time:** 2–4 giờ  
**Deliverable:** Pipeline chạy tự động 2 lần/ngày, gửi Telegram, commit history.json.

---

### Task 6.1 — Workflow file

- [ ] Tạo `.github/workflows/run_analysis.yml`:
  - Triggers: `schedule` (cron) + `workflow_dispatch` (manual)
  - Hai cron jobs:
    - London: `45 1 * * 1-5`
    - New York: `45 6 * * 1-5`
  - Steps:
    1. `actions/checkout@v4` với `token: ${{ secrets.GITHUB_TOKEN }}`
    2. `actions/setup-python@v5` với Python 3.11
    3. `pip install -r requirements.txt`
    4. `python src/main.py` với env vars từ secrets
    5. Git commit và push `data/history.json`

---

### Task 6.2 — Session detection

- [ ] Update `src/main.py` để tự detect session từ UTC time:
  - Nếu giờ UTC ≈ 01:45 → session = `"london"`
  - Nếu giờ UTC ≈ 06:45 → session = `"new_york"`
  - Fallback khi chạy manual (`workflow_dispatch`): detect từ current UTC time
  - Pass session string vào formatter để hiển thị đúng tên Kill Zone

---

### Task 6.3 — GitHub Secrets

- [ ] Add vào GitHub repo Settings → Secrets and variables → Actions:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
- [ ] Verify secrets accessible trong workflow bằng cách reference `${{ secrets.TELEGRAM_BOT_TOKEN }}`

---

### Task 6.4 — Git auto-commit config

- [ ] Trong workflow, sau khi pipeline chạy xong:
  ```yaml
  - name: Commit history
    run: |
      git config user.name "ict-bias-bot"
      git config user.email "bot@users.noreply.github.com"
      git add data/history.json
      git diff --staged --quiet || git commit -m "bot: bias report $(date -u +%Y-%m-%d) $SESSION"
      git push
  ```
  - `git diff --staged --quiet ||` — chỉ commit nếu có thay đổi thực sự

---

### Task 6.5 — Manual trigger test

- [ ] Push workflow lên GitHub
- [ ] Trigger thủ công từ Actions tab → Run workflow
- [ ] Verify: pipeline chạy thành công, Telegram message nhận được, `history.json` được commit
- [ ] Kiểm tra Actions log để confirm không có errors

---

### Task 6.6 — Scheduled run verification

- [ ] Chờ đến giờ cron tiếp theo (có thể dùng London run 08:45 VN ngày giao dịch tiếp theo)
- [ ] Verify tự động trigger thành công
- [ ] Confirm Telegram message nhận được đúng giờ

---

### Phase 6 — Definition of Done

- [ ] Workflow file valid YAML, không có syntax errors
- [ ] Manual trigger chạy thành công
- [ ] Scheduled trigger chạy đúng giờ
- [ ] Secrets được inject đúng
- [ ] `history.json` được auto-committed sau mỗi run
- [ ] Pipeline chạy xong trong < 3 phút

---

## Phase 7 — Testing & Hardening

**Mục tiêu:** Đảm bảo hệ thống robust trước khi rely vào cho trading thực.  
**Estimated time:** 1–2 ngày  
**Deliverable:** Test suite pass, edge cases được handle.

---

### Task 7.1 — Unit test completion

- [ ] Verify coverage cho tất cả các feature modules:
  - `test_market_structure.py` — swing detection, BOS, CHoCH
  - `test_pd_arrays.py` — FVG detection, premium/discount, PDH/PDL
  - `test_liquidity.py` — sweep detection
  - `test_smt.py` — divergence detection
  - `test_scorer.py` — scoring formula, multipliers, label assignment
- [ ] Tạo fixtures `tests/fixtures/` với sample OHLCV CSVs cho từng scenario
- [ ] Không cần 100% coverage — ưu tiên test các edge cases và boundary conditions

---

### Task 7.2 — Edge case testing

- [ ] Test khi yfinance trả về empty DataFrame
- [ ] Test khi một instrument bị skip nhưng pipeline vẫn chạy
- [ ] Test khi Telegram API timeout
- [ ] Test khi `history.json` bị corrupt (invalid JSON)
- [ ] Test khi market đang closed (weekend) — data fetch trả về gì

---

### Task 7.3 — Sanity check với real charts

- [ ] Chạy pipeline và so sánh output với TradingView thủ công cho 2–3 instruments
- [ ] Check các điểm:
  - Bias label có đúng không (nhìn chart tự chấm)
  - FVG được detect có tồn tại trên chart không
  - Liquidity sweep được detect có khớp với wick trên chart không
- [ ] Nếu có sai lệch lớn → debug feature module tương ứng

---

### Task 7.4 — README

- [ ] Viết `README.md` với:
  - Mô tả ngắn về hệ thống
  - Setup instructions: clone, install dependencies, create `.env`, chạy local
  - GitHub Actions setup: cách add secrets
  - Config guide: giải thích các params trong `settings.yaml`
  - Troubleshooting: các lỗi phổ biến và cách fix

---

### Phase 7 — Definition of Done

- [ ] `pytest` chạy thành công, không có failures
- [ ] Edge cases được handle gracefully (không crash)
- [ ] Sanity check với real charts pass ở mức chấp nhận được
- [ ] README đủ để người khác (hoặc bạn sau 6 tháng) setup lại từ đầu

---

## Summary

| Phase | Nội dung | Estimated Time | Deliverable |
|-------|---------|----------------|-------------|
| 0 | Project setup | 2–4 giờ | Repo skeleton, config, models |
| 1 | Data pipeline | 1–2 ngày | Fetch + validate OHLCV |
| 2 | Feature engine | 3–5 ngày | Tất cả ICT features |
| 3 | Scoring layer | 1 ngày | Bias labels + scores |
| 4 | Notification | 4–6 giờ | Telegram message |
| 5 | Persistence | 2–3 giờ | history.json |
| 6 | GitHub Actions | 2–4 giờ | Full automation |
| 7 | Testing & hardening | 1–2 ngày | Robust, tested system |
| **Total** | | **~2–3 tuần (part-time)** | **Production-ready v1** |

---

## Thứ tự ưu tiên nếu bị giới hạn thời gian

Nếu cần có kết quả sớm, có thể build theo vertical slice sau:

**Minimum viable path (1 tuần):**
```
Phase 0 → Phase 1 → Task 2.1 + 2.2 (Market Structure only) → Phase 3 (simplified) → Phase 4 → Phase 6
```

Hệ thống này chỉ dùng Market Structure để score nhưng vẫn chạy được tự động và gửi Telegram. Sau đó bổ sung Feature Engine dần (FVG → Liquidity → SMT) mà không cần thay đổi gì ở Scoring và Notification.

---

*Action Plan này là living document — cập nhật checkbox và notes khi thực hiện từng task.*
