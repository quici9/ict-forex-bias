# ICT Forex Bias System — System Design

**Version:** 1.0  
**Last updated:** 2026-03-21  
**Author:** TBD  
**Status:** Draft — pending implementation

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Non-goals](#2-goals--non-goals)
3. [Architecture Overview](#3-architecture-overview)
4. [Module Breakdown](#4-module-breakdown)
   - 4.1 [Scheduler](#41-scheduler--github-actions)
   - 4.2 [Data Pipeline](#42-data-pipeline)
   - 4.3 [Feature Engine](#43-feature-engine)
   - 4.4 [Scoring Layer](#44-scoring-layer)
   - 4.5 [Notification Layer](#45-notification-layer)
   - 4.6 [Persistence Layer](#46-persistence-layer)
5. [Data Model](#5-data-model)
6. [Instrument Configuration](#6-instrument-configuration)
7. [Scoring Specification](#7-scoring-specification)
8. [Error Handling Strategy](#8-error-handling-strategy)
9. [Repository Structure](#9-repository-structure)
10. [Configuration Management](#10-configuration-management)
11. [Infrastructure & Cost](#11-infrastructure--cost)
12. [Roadmap](#12-roadmap)
13. [Risks & Mitigations](#13-risks--mitigations)

---

## 1. Overview

**ICT Forex Bias System** là một pipeline tự động phân tích thị trường Forex theo phương pháp ICT (Inner Circle Trader), xác định Daily Bias (Bullish / Bearish / Neutral) cho từng cặp tiền, và xếp hạng các cặp theo mức độ hội tụ tín hiệu.

Hệ thống chạy tự động 2 lần mỗi ngày — trước London Kill Zone và trước New York Kill Zone — gửi kết quả phân tích qua Telegram, giúp trader rút ngắn thời gian phân tích buổi sáng từ 60–90 phút xuống còn ~10 phút.

### Vấn đề cần giải quyết

Trader theo phương pháp ICT cần thực hiện phân tích top-down (D1 → H4 → H1) trên nhiều cặp tiền trước mỗi Kill Zone. Quá trình này lặp đi lặp lại, tốn thời gian, và dễ bị bỏ sót khi thực hiện thủ công. Hệ thống này tự động hoá phần "scan và lọc", để trader chỉ cần tập trung vào những cặp có tín hiệu hội tụ cao nhất.

---

## 2. Goals & Non-goals

### Goals

- Tự động fetch dữ liệu OHLCV từ yfinance cho 8 cặp Forex chính
- Encode các rule ICT (Market Structure, FVG, Liquidity, Premium/Discount) thành các feature có thể tính toán
- Tính điểm (0–100) cho từng cặp theo weighted rule-based scoring
- Gửi Telegram report trước mỗi Kill Zone (London & New York)
- Chạy hoàn toàn tự động trên GitHub Actions, không cần can thiệp thủ công
- Hỗ trợ chạy local dễ dàng cho mục đích test và development
- Lưu log kết quả dưới dạng JSON để phục vụ dashboard sau này

### Non-goals (v1)

- **Không** tự động vào lệnh hay kết nối với broker
- **Không** thực hiện backtesting hay tính toán win rate
- **Không** cung cấp điểm vào lệnh (entry), stop loss, hay target cụ thể
- **Không** phân tích timeframe dưới H1 (M15, M5, M1)
- **Không** xây dựng GitHub Pages dashboard (để dành v2)
- **Không** dùng ML/AI model trong scoring (để dành v2 sau khi có đủ labeled data)

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   GitHub Actions (Cron)                  │
│         01:45 UTC (London) · 06:45 UTC (New York)        │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    Data Pipeline                         │
│   yfinance → fetch OHLCV → validate → normalize          │
│   Timeframes: D1, H4, H1  |  8 pairs + DXY              │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    Feature Engine                        │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │   Market     │  │  PD Arrays   │  │   Liquidity   │  │
│  │  Structure   │  │  FVG · OB    │  │  Sweep · SMT  │  │
│  │ BOS · CHoCH  │  │  Prem/Disc   │  │               │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    Scoring Layer                         │
│   Weighted sum (0–100) · W1 multiplier · Bias label      │
│   Filter: score ≥ 50   |   Sort by score desc            │
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────┐    ┌─────────────────────────────┐
│   Telegram Notifier  │    │     Persistence (JSON log)  │
│   Formatted report   │    │   history.json → git commit │
│   per Kill Zone      │    │   (foundation for v2 dash)  │
└──────────────────────┘    └─────────────────────────────┘
```

### Luồng thực thi tổng thể

```
Cron trigger
  → Fetch OHLCV (D1, H4, H1) cho 8 pairs + DXY
  → Validate & clean data
  → Calculate features per instrument per timeframe
  → Score từng pair (0–100) với W1 multiplier
  → Filter score ≥ 50, sort descending
  → Format Telegram message
  → Send Telegram notification
  → Append result to history.json
  → Git commit history.json (auto, trong Actions)
  → Exit
```

Tổng thời gian chạy ước tính: **dưới 90 giây**.

---

## 4. Module Breakdown

### 4.1 Scheduler — GitHub Actions

**Mục đích:** Trigger pipeline tự động theo lịch, quản lý secrets, và cung cấp môi trường chạy miễn phí.

**Lịch chạy:**

| Run | Cron (UTC) | Giờ VN (UTC+7) | Mục đích |
|-----|-----------|----------------|----------|
| London pre-KZ | `45 1 * * 1-5` | 08:45 | Trước London Kill Zone (09:00 VN) |
| NY pre-KZ | `45 6 * * 1-5` | 13:45 | Trước New York Kill Zone (14:00 VN) |

Chỉ chạy Monday–Friday (`1-5`), bỏ qua cuối tuần khi Forex đóng cửa.

**Trigger thủ công:** Hỗ trợ `workflow_dispatch` để chạy bất kỳ lúc nào từ GitHub UI — tiện cho việc test.

**Secrets cần cấu hình trên GitHub:**
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Không cần API key cho yfinance vì thư viện này gọi Yahoo Finance trực tiếp.

**Python version:** 3.11 (stable, tương thích tốt với tất cả dependencies).

---

### 4.2 Data Pipeline

**Mục đích:** Fetch, validate, và chuẩn hoá dữ liệu OHLCV từ yfinance.

#### 4.2.1 Instrument list

| yfinance Symbol | Cặp | Vai trò | SMT pair |
|----------------|-----|---------|----------|
| `EURUSD=X` | EUR/USD | Primary | GBPUSD |
| `GBPUSD=X` | GBP/USD | Primary | EURUSD |
| `USDJPY=X` | USD/JPY | Primary | USDCHF |
| `USDCHF=X` | USD/CHF | Primary | USDJPY |
| `AUDUSD=X` | AUD/USD | Primary | NZDUSD |
| `NZDUSD=X` | NZD/USD | Primary | AUDUSD |
| `USDCAD=X` | USD/CAD | Primary | DXY |
| `GBPJPY=X` | GBP/JPY | Primary | USDJPY |
| `DX-Y.NYB` | DXY Index | Reference only | — |

DXY được fetch nhưng **không được score** — chỉ dùng như reference cho SMT divergence của USDCAD.

#### 4.2.2 Timeframes cần fetch

| Timeframe | yfinance interval | Số candles cần | Mục đích |
|-----------|------------------|----------------|----------|
| Daily (D1) | `1d` | 60 candles | Market structure, Daily bias, PDH/PDL |
| 4-Hour (H4) | `1h` (aggregate) | 120 candles H1 → 30 H4 | FVG detection, intraday structure |
| 1-Hour (H1) | `1h` | 72 candles | Liquidity sweep, entry zone context |

> **Lưu ý kỹ thuật:** yfinance không có interval `4h`. Cần fetch `1h` rồi resample thành H4 bằng pandas `resample('4h')`. Đây là bước xử lý bắt buộc trong data pipeline.

#### 4.2.3 Data validation

Sau mỗi lần fetch, pipeline phải kiểm tra:

1. **Số lượng candle tối thiểu:** D1 ≥ 30, H4 ≥ 20, H1 ≥ 24. Nếu thiếu → bỏ qua instrument đó, log warning.
2. **NaN values:** Drop rows có NaN trong OHLCV. Nếu sau khi drop còn đủ candle → tiếp tục. Nếu không → skip instrument.
3. **Weekend gaps:** Candle cuối cùng phải là ngày giao dịch gần nhất. Nếu timestamp của candle cuối cách hơn 2 ngày so với thời điểm chạy → flag `stale_data`.
4. **Anomalous candles:** Nếu `|close - open| / close > 0.05` (biến động > 5% trong một candle D1) → flag để review, vẫn tiếp tục xử lý.

#### 4.2.4 ATR Normalization

Mỗi instrument cần tính **ATR(14) trên D1** và lưu lại. ATR được dùng để normalize các threshold trong Feature Engine — tránh hard-code pip values vì mỗi cặp có volatility khác nhau.

```
atr_normalized_threshold = raw_threshold_in_price / atr14_daily
```

---

### 4.3 Feature Engine

**Mục đích:** Tính toán các ICT-based features cho từng instrument, đầu ra là một vector số cho Scoring Layer.

Mỗi feature trả về một trong ba dạng:
- **Boolean** (True/False): Điều kiện có thoả mãn hay không
- **Float [-1, 1]**: Direction (1 = bullish, -1 = bearish, 0 = neutral)
- **Float [0, 1]**: Strength/confidence score

#### 4.3.1 Market Structure (module: `market_structure.py`)

**Input:** D1 OHLCV, H4 OHLCV  
**Logic:**

Phát hiện swing highs và swing lows bằng lookback window cố định (mặc định: 5 candles mỗi bên — configurable). Một điểm là swing high nếu nó là high nhất trong `[i-n, i+n]`.

Từ chuỗi swing points, xác định:

| Feature | Định nghĩa | Output |
|---------|-----------|--------|
| `d1_structure` | Xu hướng D1: HH+HL = Bullish, LH+LL = Bearish, mixed = Ranging | Float [-1, 1] |
| `d1_structure_clarity` | Số lượng swing points rõ ràng (nhiều hơn = rõ ràng hơn) | Float [0, 1] |
| `h4_structure` | Tương tự nhưng trên H4 | Float [-1, 1] |
| `structure_alignment` | D1 và H4 đồng chiều | Bool |
| `bos_recent` | Break of Structure xảy ra trong 3 candles H4 gần nhất | Bool |
| `choch_recent` | Change of Character xảy ra trong 3 candles H4 gần nhất (tín hiệu reversal) | Bool |

**BOS definition:** Candle đóng cửa vượt qua swing high (bullish BOS) hoặc swing low (bearish BOS) gần nhất đã được xác nhận.

**CHoCH definition:** Giá phá vỡ swing point ngược chiều trend hiện tại sau khi đã sweep liquidity.

#### 4.3.2 PD Arrays (module: `pd_arrays.py`)

**Sub-module 1: Premium & Discount Zone**

**Input:** D1 OHLCV  
**Logic:**

1. Xác định dealing range: từ swing low gần nhất đến swing high gần nhất trên D1 (hoặc ngược lại tuỳ chiều trend).
2. Tính Fibonacci 50% của dealing range.
3. So sánh vị trí close của candle D1 hiện tại.

| Feature | Định nghĩa | Output |
|---------|-----------|--------|
| `price_zone` | Vị trí giá: > 50% = Premium, < 50% = Discount, ≈ 50% = EQ | Float [-1, 1] (1=discount, -1=premium) |
| `zone_strength` | Khoảng cách từ giá đến 50% level, normalized theo dealing range | Float [0, 1] |

**Sub-module 2: Fair Value Gap (FVG)**

**Input:** H4 OHLCV, H1 OHLCV  
**Logic:**

FVG được xác định bằng 3-candle pattern:
- **Bullish FVG:** `candle[i-1].high < candle[i+1].low` — gap giữa high của candle trước và low của candle sau cú displacement bullish.
- **Bearish FVG:** `candle[i-1].low > candle[i+1].high` — gap giữa low của candle trước và high của candle sau cú displacement bearish.

Điều kiện thêm:
- Candle giữa (displacement candle) phải có body ≥ 1.5× ATR(14) để xác nhận đây là displacement thật sự, không phải nhiễu.
- FVG "chưa fill" nếu giá chưa quay lại vùng gap đó.
- Chỉ xét FVG trong 10 candles H4 gần nhất (không nhìn quá xa vào quá khứ).

| Feature | Định nghĩa | Output |
|---------|-----------|--------|
| `fvg_exists_h4` | Có FVG chưa fill trên H4 | Bool |
| `fvg_direction_h4` | Chiều của FVG gần nhất | Float [-1, 1] |
| `fvg_size_h4` | Kích thước FVG normalized theo ATR | Float [0, 1] |
| `fvg_exists_h1` | Có FVG chưa fill trên H1 | Bool |
| `fvg_direction_h1` | Chiều của FVG gần nhất trên H1 | Float [-1, 1] |

**Sub-module 3: Previous Day High/Low (PDH/PDL)**

**Input:** D1 OHLCV  

| Feature | Định nghĩa | Output |
|---------|-----------|--------|
| `near_pdh` | Giá đang trong 0.5× ATR so với PDH | Bool |
| `near_pdl` | Giá đang trong 0.5× ATR so với PDL | Bool |
| `swept_pdh` | Giá đã sweep PDH trong D1 hiện tại (wick vượt qua nhưng không close trên) | Bool |
| `swept_pdl` | Giá đã sweep PDL trong D1 hiện tại | Bool |

#### 4.3.3 Liquidity Module (module: `liquidity.py`)

**Input:** H4 OHLCV, H1 OHLCV  

**Liquidity Sweep Detection:**

Sweep được xác nhận khi:
1. Giá tạo wick vượt qua một swing high/low quan trọng (xác định bằng lookback 10 candles H4)
2. Candle đóng cửa bên trong swing point đó (không close vượt qua)
3. Hoặc: giá close vượt qua nhưng trong candle tiếp theo ngay lập tức đảo chiều với engulfing body

| Feature | Định nghĩa | Output |
|---------|-----------|--------|
| `sweep_occurred` | Có liquidity sweep trong 3 candles H4 gần nhất | Bool |
| `sweep_direction` | Chiều sweep: swept buyside (-1, bearish signal) hoặc sellside (1, bullish signal) | Float [-1, 1] |
| `sweep_age` | Sweep xảy ra cách bao nhiêu candles H4 (càng gần càng tốt) | Int [0, 10] |

#### 4.3.4 SMT Divergence (module: `smt.py`)

**Input:** D1 và H4 OHLCV của hai correlated instruments

**Logic:**

Với mỗi pair và SMT partner của nó, so sánh swing lows (cho bullish signal) hoặc swing highs (cho bearish signal) trên cùng timeframe:

- **Bullish SMT:** Pair A tạo lower low, nhưng pair B (correlated) không tạo lower low — tín hiệu sell-side liquidity sweep không được confirm → bullish bias.
- **Bearish SMT:** Pair A tạo higher high, nhưng pair B không tạo higher high → bearish bias.

Điều kiện: Hai swing points phải cách nhau tối đa 5 candles để được coi là "cùng thời điểm".

| Feature | Định nghĩa | Output |
|---------|-----------|--------|
| `smt_signal` | Có SMT divergence không | Bool |
| `smt_direction` | Chiều tín hiệu SMT | Float [-1, 1] |
| `smt_timeframe` | Divergence xảy ra trên D1 hay H4 | String |

**SMT pairs:**

| Instrument | SMT Partner | Logic |
|-----------|------------|-------|
| EURUSD | GBPUSD | Cùng nhóm USD weakness/strength |
| GBPUSD | EURUSD | Cùng nhóm |
| USDJPY | USDCHF | Cùng nhóm safe haven |
| USDCHF | USDJPY | Cùng nhóm |
| AUDUSD | NZDUSD | Cùng nhóm commodity currency |
| NZDUSD | AUDUSD | Cùng nhóm |
| USDCAD | DXY | DXY là reference dollar strength |
| GBPJPY | USDJPY | JPY component |

---

### 4.4 Scoring Layer

**Mục đích:** Tổng hợp tất cả features thành một điểm số duy nhất (0–100) và xác định bias label.

#### 4.4.1 Weighted scoring formula

```
raw_score = Σ (feature_score_i × weight_i × direction_alignment_i)
```

Trong đó:
- `feature_score_i` ∈ [0, 1]: Độ mạnh của tín hiệu
- `weight_i`: Trọng số cấu hình trong `settings.yaml`
- `direction_alignment_i` ∈ {+1, -1}: +1 nếu feature đồng chiều với direction đang xét, -1 nếu ngược chiều

`raw_score` được tính riêng cho cả Bullish hypothesis và Bearish hypothesis. Cặp nào có raw_score cao hơn → đó là bias label.

`final_score = max(bullish_score, bearish_score) × 100`

#### 4.4.2 Feature weights (default)

| Feature | Weight | Rationale |
|---------|--------|-----------|
| `d1_structure` | 0.25 | Nền tảng của bias — quan trọng nhất |
| `structure_alignment` (D1+H4) | 0.15 | Đồng thuận đa TF tăng confidence |
| `price_zone` | 0.15 | ICT principle: mua ở discount, bán ở premium |
| `fvg_h4` | 0.15 | PD Array có giá trị cao nhất trong ngày |
| `sweep_occurred` | 0.15 | Liquidity sweep là trigger của move thật |
| `smt_signal` | 0.10 | Tín hiệu xác nhận từ correlated pair |
| `bos_recent` | 0.05 | Xác nhận structure shift gần đây |

**Tổng weights = 1.0**

#### 4.4.3 W1 Multiplier

Weekly trend được tính riêng (fetch W1 data) và áp dụng như một multiplier lên final_score:

| Điều kiện | Multiplier | Ghi chú |
|-----------|-----------|--------|
| D1 bias đồng chiều W1 | × 1.0 | Fully aligned — không thay đổi |
| W1 ranging / không rõ | × 0.9 | Giảm nhẹ confidence |
| D1 bias ngược chiều W1 | × 0.75 | Counter-trend — rủi ro cao hơn |

#### 4.4.4 Bias label assignment

| Điều kiện | Label |
|-----------|-------|
| final_score ≥ 70 | `BULLISH` hoặc `BEARISH` (tùy direction thắng) |
| 50 ≤ final_score < 70 | `WATCHLIST` — có tín hiệu nhưng chưa đủ conviction |
| final_score < 50 | `NEUTRAL` — không đủ hội tụ, bỏ qua |

#### 4.4.5 Low-volatility filter

Nếu ATR(14) của instrument < 30% so với average ATR(14) của 20 ngày trước → overwrite bias label thành `LOW_VOL` bất kể score. Thị trường đang nằm im không phù hợp để trade Kill Zone.

#### 4.4.6 Counter-trend flag

Nếu W1 multiplier = 0.75 → thêm tag `[CTrend]` vào output. Đây là tín hiệu cho trader biết setup này đi ngược xu hướng lớn, cần thận trọng hơn.

---

### 4.5 Notification Layer

**Mục đích:** Format và gửi kết quả qua Telegram Bot API.

#### 4.5.1 Telegram Bot setup

- Tạo bot qua `@BotFather`, lấy `BOT_TOKEN`
- Lấy `CHAT_ID` bằng cách gửi message cho bot rồi call `getUpdates`
- Hỗ trợ cả cá nhân (personal chat) và group

#### 4.5.2 Message format

```
📊 ICT Bias Report — London Kill Zone
🕑 08:45 VN · Mon 21 Mar 2026
─────────────────────────────
🔴 GBPUSD  BEARISH   82/100
🔴 EURUSD  BEARISH   74/100
🟢 USDJPY  BULLISH   71/100  [CTrend]
─────────────────────────────
⚪ AUDUSD  WATCHLIST 58/100
⚪ USDCAD  WATCHLIST 53/100
─────────────────────────────
⏭️ NZDUSD  NEUTRAL  — skipped
⏭️ USDCHF  NEUTRAL  — skipped
⏭️ GBPJPY  LOW_VOL  — skipped
─────────────────────────────
🔍 Top pick: GBPUSD
   • D1 downtrend rõ (3 LH+LL liên tiếp)
   • FVG H4 chưa fill tại 1.2680–1.2695
   • Sell-side swept 2 candles trước
   • SMT confirm: EURUSD không tạo HH
   • W1 aligned ✓
```

#### 4.5.3 Message design decisions

- **Emoji thay màu sắc:** Telegram plain text không hỗ trợ màu, dùng emoji để scan nhanh
- **Top pick:** Chỉ expand detail cho instrument có score cao nhất — giữ message ngắn
- **Skipped instruments:** Vẫn liệt kê để trader biết đã được scan, không phải bị bỏ sót
- **Timestamp theo giờ VN:** Dễ đọc hơn UTC cho người dùng ở Việt Nam
- **Parse mode:** `MarkdownV2` hoặc plain text — tránh HTML mode để ít lỗi escape hơn

#### 4.5.4 Retry logic

Nếu Telegram API call thất bại → retry tối đa 3 lần với exponential backoff (1s, 2s, 4s). Nếu vẫn thất bại → log error, pipeline vẫn tiếp tục (không block bước persist).

---

### 4.6 Persistence Layer

**Mục đích:** Lưu kết quả mỗi lần chạy vào file JSON, commit lên repo. Đây là foundation cho dashboard v2.

#### 4.6.1 File location

`data/history.json` — file duy nhất, append-only structure.

#### 4.6.2 JSON schema

```json
{
  "runs": [
    {
      "run_id": "2026-03-21T01:45:00Z",
      "session": "london",
      "timestamp_utc": "2026-03-21T01:47:23Z",
      "instruments": [
        {
          "symbol": "GBPUSD",
          "bias": "BEARISH",
          "score": 82,
          "is_counter_trend": false,
          "is_low_vol": false,
          "features": {
            "d1_structure": -0.85,
            "d1_structure_clarity": 0.90,
            "h4_structure": -0.70,
            "structure_alignment": true,
            "price_zone": -0.60,
            "fvg_exists_h4": true,
            "fvg_direction_h4": -1.0,
            "fvg_size_h4": 0.45,
            "sweep_occurred": true,
            "sweep_direction": -1.0,
            "sweep_age": 2,
            "smt_signal": true,
            "smt_direction": -1.0
          },
          "w1_multiplier": 1.0,
          "atr14_d1": 0.00812
        }
      ],
      "top_pick": "GBPUSD",
      "duration_seconds": 47,
      "errors": []
    }
  ]
}
```

#### 4.6.3 Git auto-commit

Sau mỗi lần chạy thành công, GitHub Actions tự commit `data/history.json`:

```
git config user.name "ict-bias-bot"
git config user.email "bot@noreply"
git add data/history.json
git commit -m "bot: bias report 2026-03-21 london"
git push
```

Dùng `GITHUB_TOKEN` built-in của Actions — không cần secret riêng.

#### 4.6.4 File size management

Giữ tối đa 90 runs gần nhất trong file (≈ 45 ngày giao dịch × 2 sessions). Các run cũ hơn tự động trim trước khi write. Ước tính kích thước file: ~200KB — hoàn toàn phù hợp cho git tracking.

---

## 5. Data Model

### 5.1 Internal data structures

```python
# Sau bước fetch và validate
@dataclass
class InstrumentData:
    symbol: str
    d1: pd.DataFrame      # OHLCV, 60 candles
    h4: pd.DataFrame      # OHLCV resampled, 30 candles
    h1: pd.DataFrame      # OHLCV, 72 candles
    w1: pd.DataFrame      # OHLCV, 20 candles (chỉ dùng cho multiplier)
    atr14_d1: float
    is_valid: bool
    validation_errors: list[str]

# Sau Feature Engine
@dataclass
class InstrumentFeatures:
    symbol: str
    # Market Structure
    d1_structure: float         # [-1, 1]
    d1_structure_clarity: float # [0, 1]
    h4_structure: float         # [-1, 1]
    structure_alignment: bool
    bos_recent: bool
    choch_recent: bool
    # PD Arrays
    price_zone: float           # [-1, 1] (1=discount, -1=premium)
    zone_strength: float        # [0, 1]
    fvg_exists_h4: bool
    fvg_direction_h4: float     # [-1, 1]
    fvg_size_h4: float          # [0, 1]
    fvg_exists_h1: bool
    fvg_direction_h1: float
    near_pdh: bool
    near_pdl: bool
    swept_pdh: bool
    swept_pdl: bool
    # Liquidity
    sweep_occurred: bool
    sweep_direction: float      # [-1, 1]
    sweep_age: int              # candles since sweep
    # SMT
    smt_signal: bool
    smt_direction: float        # [-1, 1]
    # Meta
    w1_direction: float         # [-1, 1] dùng để tính multiplier
    atr14_d1: float

# Sau Scoring Layer
@dataclass
class InstrumentScore:
    symbol: str
    bias: str                   # BULLISH | BEARISH | WATCHLIST | NEUTRAL | LOW_VOL
    score: int                  # [0, 100]
    bullish_score: float        # raw score cho bullish hypothesis
    bearish_score: float        # raw score cho bearish hypothesis
    w1_multiplier: float        # 0.75 | 0.9 | 1.0
    is_counter_trend: bool
    is_low_vol: bool
    top_signals: list[str]      # Tối đa 4 signal strings cho Telegram message
    features: InstrumentFeatures
```

---

## 6. Instrument Configuration

Toàn bộ instrument list được cấu hình trong `config/settings.yaml`, không hard-code trong source:

```yaml
instruments:
  - symbol: "EURUSD=X"
    name: "EUR/USD"
    smt_partner: "GBPUSD=X"
    enabled: true

  - symbol: "GBPUSD=X"
    name: "GBP/USD"
    smt_partner: "EURUSD=X"
    enabled: true

  - symbol: "USDJPY=X"
    name: "USD/JPY"
    smt_partner: "USDCHF=X"
    enabled: true

  - symbol: "USDCHF=X"
    name: "USD/CHF"
    smt_partner: "USDJPY=X"
    enabled: true

  - symbol: "AUDUSD=X"
    name: "AUD/USD"
    smt_partner: "NZDUSD=X"
    enabled: true

  - symbol: "NZDUSD=X"
    name: "NZD/USD"
    smt_partner: "AUDUSD=X"
    enabled: true

  - symbol: "USDCAD=X"
    name: "USD/CAD"
    smt_partner: "DX-Y.NYB"
    enabled: true

  - symbol: "GBPJPY=X"
    name: "GBP/JPY"
    smt_partner: "USDJPY=X"
    enabled: true

reference:
  dxy: "DX-Y.NYB"
```

---

## 7. Scoring Specification

### 7.1 Full settings.yaml

```yaml
scoring:
  weights:
    d1_structure: 0.25
    structure_alignment: 0.15
    price_zone: 0.15
    fvg_h4: 0.15
    sweep: 0.15
    smt: 0.10
    bos_recent: 0.05

  thresholds:
    high_conviction: 70    # BULLISH/BEARISH
    watchlist: 50          # WATCHLIST
    # Below watchlist → NEUTRAL

  w1_multipliers:
    aligned: 1.0
    ranging: 0.9
    counter_trend: 0.75

  low_vol_threshold: 0.30  # ATR < 30% của 20-day avg → LOW_VOL

features:
  swing_lookback: 5          # candles mỗi bên để xác định swing point
  fvg_min_displacement: 1.5  # minimum body size tính bằng ATR multiplier
  fvg_lookback_candles: 10   # số candles H4 nhìn lại để tìm FVG
  sweep_lookback_candles: 3  # số candles H4 gần nhất để check sweep
  smt_max_candle_diff: 5     # max khoảng cách giữa 2 swing để so sánh SMT

data:
  d1_candles: 60
  h4_candles: 30
  h1_candles: 72
  w1_candles: 20
  pdh_pdl_atr_threshold: 0.5  # near PDH/PDL nếu trong 0.5 × ATR

notification:
  timezone: "Asia/Ho_Chi_Minh"
  min_score_to_show: 50        # Không hiển thị instruments dưới mức này trong detail
  max_detail_instruments: 3    # Số instruments được expand detail
```

### 7.2 Ví dụ tính điểm

**Scenario: GBPUSD Bearish**

| Feature | Value | Contribution (bearish) |
|---------|-------|----------------------|
| d1_structure = -0.85 (bearish) | aligned | 0.85 × 0.25 = 0.213 |
| structure_alignment = True | aligned | 1.0 × 0.15 = 0.150 |
| price_zone = -0.60 (premium) | aligned | 0.60 × 0.15 = 0.090 |
| fvg_h4 = True, direction = -1 | aligned | 1.0 × 0.15 = 0.150 |
| sweep = True, direction = -1 | aligned | 1.0 × 0.15 = 0.150 |
| smt = True, direction = -1 | aligned | 1.0 × 0.10 = 0.100 |
| bos_recent = True (bearish) | aligned | 1.0 × 0.05 = 0.050 |
| **Raw bearish score** | | **0.903** |
| × W1 multiplier (1.0) | | **0.903** |
| **Final score** | | **90/100 → BEARISH** |

---

## 8. Error Handling Strategy

### 8.1 Error categories

| Category | Ví dụ | Hành động |
|----------|-------|-----------|
| **Data fetch failure** | yfinance timeout, rate limit | Retry 3 lần, skip instrument nếu vẫn fail |
| **Insufficient data** | Thiếu candles sau validate | Skip instrument, log warning |
| **Feature calculation error** | Division by zero trong normalization | Return `None` cho feature đó, score với weights còn lại |
| **Scoring error** | Tất cả features đều None | Skip instrument, mark as `ERROR` |
| **Telegram send failure** | Network error, bot blocked | Retry 3 lần exponential backoff, log nếu vẫn fail |
| **Git commit failure** | Conflict, permission | Log error, không retry — next run sẽ overwrite |

### 8.2 Degraded operation

Pipeline được thiết kế để **không bao giờ crash hoàn toàn**. Nếu 3/8 instruments bị skip vì data lỗi → pipeline vẫn tiếp tục với 5 instruments còn lại và gửi kết quả (kèm warning trong message).

Nếu **tất cả** instruments fail → gửi message lỗi ngắn qua Telegram thay vì không gửi gì.

### 8.3 Logging

Mỗi run tạo một log entry có:
- Timestamp bắt đầu và kết thúc
- Số instruments thành công / thất bại
- Danh sách errors với traceback
- Duration

Log được in ra stdout (GitHub Actions tự capture vào run logs).

---

## 9. Repository Structure

```
forex-bias-bot/
│
├── .github/
│   └── workflows/
│       └── run_analysis.yml        # Cron + manual dispatch workflow
│
├── src/
│   ├── __init__.py
│   ├── main.py                     # Entry point — orchestrates toàn bộ pipeline
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py              # yfinance wrapper, retry logic
│   │   ├── validator.py            # Data quality checks
│   │   └── resampler.py            # H1 → H4 resample logic
│   │
│   ├── features/
│   │   ├── __init__.py
│   │   ├── market_structure.py     # BOS, CHoCH, swing detection
│   │   ├── pd_arrays.py            # FVG, Premium/Discount, PDH/PDL
│   │   ├── liquidity.py            # Sweep detection
│   │   └── smt.py                  # SMT divergence
│   │
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── scorer.py               # Weighted aggregation, bias label, W1 multiplier
│   │
│   └── notify/
│       ├── __init__.py
│       ├── formatter.py            # Build message string
│       └── telegram.py             # Telegram Bot API client
│
├── config/
│   └── settings.yaml               # Instruments, weights, thresholds — editable
│
├── data/
│   └── history.json                # Auto-committed bởi GitHub Actions
│
├── docs/                           # Placeholder cho GitHub Pages (v2)
│   └── .gitkeep
│
├── tests/
│   ├── test_market_structure.py
│   ├── test_pd_arrays.py
│   ├── test_liquidity.py
│   ├── test_scorer.py
│   └── fixtures/                   # Sample OHLCV data cho unit tests
│       └── sample_eurusd_d1.csv
│
├── scripts/
│   └── run_local.py                # Helper script để chạy local với env vars
│
├── requirements.txt
├── .env.example                    # Template cho local development
├── .gitignore                      # Bao gồm .env
└── README.md
```

### Separation of concerns

- `src/data/` — chỉ biết về OHLCV DataFrames, không biết về ICT concepts
- `src/features/` — chỉ nhận DataFrame, trả về số — không biết về scoring
- `src/scoring/` — chỉ nhận features, trả về score — không biết về Telegram
- `src/notify/` — chỉ nhận InstrumentScore list, format và send

Mỗi layer có thể được test và thay thế độc lập.

---

## 10. Configuration Management

### 10.1 Secrets (không bao giờ commit lên git)

| Secret | Môi trường | Nguồn |
|--------|-----------|-------|
| `TELEGRAM_BOT_TOKEN` | GitHub Actions Secrets | BotFather |
| `TELEGRAM_CHAT_ID` | GitHub Actions Secrets | getUpdates API |

### 10.2 Local development

File `.env` (gitignored):
```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

`scripts/run_local.py` load `.env` tự động trước khi chạy pipeline.

### 10.3 Tuning workflow

`config/settings.yaml` là file duy nhất trader cần chỉnh. Workflow điển hình:

1. Quan sát kết quả 1–2 tuần
2. Nhận thấy feature X hay bị miss → tăng weight của X trong `settings.yaml`
3. Commit, push — GitHub Actions sẽ dùng config mới ngay lần chạy tiếp theo
4. Không cần thay đổi source code

---

## 11. Infrastructure & Cost

### 11.1 GitHub Actions usage

| Metric | Calculation | Value |
|--------|------------|-------|
| Runs per day | 2 sessions × 5 days/week | 10/week |
| Duration per run | Fetch + compute + notify | ~90 seconds |
| Monthly minutes | 10 runs/week × 4.3 weeks × 1.5 min | ~65 minutes |
| Free tier limit | GitHub Free | 2,000 min/month |
| **Usage** | | **~3.2% của free tier** |

**Chi phí: $0/tháng.**

### 11.2 yfinance

Miễn phí, không cần tài khoản, không có SLA. Rate limit không chính thức — với 9 instruments × 4 timeframes = 36 requests, thêm delay nhỏ 0.5s giữa requests để tránh bị block.

### 11.3 Telegram Bot API

Miễn phí không giới hạn. Rate limit: 30 messages/second — pipeline chỉ gửi 1 message mỗi lần chạy, không vấn đề gì.

---

## 12. Roadmap

### v1 — MVP (target: 2–3 tuần)

- [ ] Data pipeline với yfinance + validation
- [ ] Feature engine: Market Structure, FVG, Liquidity, SMT
- [ ] Weighted scoring + W1 multiplier
- [ ] Telegram notification
- [ ] GitHub Actions automation
- [ ] history.json persistence
- [ ] Unit tests cho core features
- [ ] README với setup instructions

### v1.5 — Tuning (song song với trading, 1–3 tháng)

- [ ] Điều chỉnh weights dựa trên kết quả thực tế
- [ ] Thêm daily note vào history.json: trader manually note setup có profitable không
- [ ] Simple accuracy tracking: % lần bias đúng chiều per instrument
- [ ] Có thể thêm XAUUSD nếu cần (cần ATR-normalized threshold riêng)

### v2 — Dashboard (sau 3–6 tháng)

- [ ] GitHub Pages dashboard với HTML/JS
- [ ] Visualize history: accuracy per pair, per session, trend over time
- [ ] Heatmap: ngày nào / session nào hệ thống đáng tin cậy nhất

### v3 — ML Enhancement (optional, sau khi có đủ labeled data)

- [ ] Label history data với trade outcome
- [ ] Train XGBoost classifier trên features hiện có
- [ ] A/B test: rule-based vs ML scoring
- [ ] Chỉ deploy ML nếu prove out-of-sample outperformance

---

## 13. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| yfinance data quality thấp | Medium | Medium | Validation layer bắt buộc; log anomalies; so sánh thủ công định kỳ |
| yfinance API thay đổi / bị block | Low | High | Abstract trong `fetcher.py` để dễ swap sang OANDA nếu cần |
| Look-ahead bias khi backtest sau này | High (nếu không cẩn thận) | High | Chỉ dùng `iloc[:-1]` khi tính features — không bao giờ dùng candle hiện tại để confirm signal của chính nó |
| Over-optimization (curve fitting weights) | Medium | Medium | Chỉ tune weights sau khi có ≥ 30 observations; không tune từng trade |
| GitHub Actions cron delay | Low | Low | Actions cron có thể delay vài phút — vẫn đủ thời gian trước KZ |
| Ranging market → nhiều NEUTRAL | Medium | Low | Bình thường — ít setup = không trade = tốt hơn là force setup |
| W1 data có gaps (yfinance) | Low | Low | Chỉ dùng W1 cho multiplier, không dùng cho primary scoring |
