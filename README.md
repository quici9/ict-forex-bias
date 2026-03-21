# ICT Forex Bias System

Pipeline tự động phân tích thị trường Forex theo phương pháp ICT, gửi Daily Bias report qua Telegram trước mỗi **London Kill Zone** (08:45 VN) và **New York Kill Zone** (13:45 VN).

---

## Quick Start (Local)

### 1. Prerequisites

```bash
python --version   # Python 3.11+
```

### 2. Clone và cài đặt

```bash
git clone https://github.com/quici9/ict-forex-bias.git
cd ict-forex-bias
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

### 3. Cấu hình secrets

```bash
cp .env.example .env
# Mở .env và điền TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
```

### 4. Chạy local

```bash
python scripts/run_local.py
```

---

## GitHub Actions Setup

1. Push repo lên GitHub
2. Vào **Settings → Secrets and variables → Actions**
3. Thêm hai secrets:
   - `TELEGRAM_BOT_TOKEN` — lấy từ `@BotFather`
   - `TELEGRAM_CHAT_ID` — lấy qua `getUpdates` API
4. Trigger thủ công: **Actions → ICT Forex Bias → Run workflow**

Cron tự động chạy mỗi ngày giao dịch lúc **08:45** và **13:45** giờ VN.

---

## Configuration

Chỉnh `config/settings.yaml` để:

- Bật/tắt instrument (field `enabled`)
- Điều chỉnh feature weights (field `scoring.weights`)
- Thay đổi thresholds (field `scoring.thresholds`)

Không cần thay source code — pipeline đọc config khi chạy.

---

## Cấu trúc dự án

```
src/
├── main.py              # Entry point, pipeline orchestrator
├── config.py            # Typed config loader
├── models.py            # All dataclasses
├── data/                # Fetch, validate, resample
├── features/            # ICT feature modules
├── scoring/             # Weighted scoring
└── notify/              # Telegram formatter + sender
config/settings.yaml     # Instrument list + all params
data/history.json        # Auto-committed run history
scripts/run_local.py     # Local dev runner
tests/                   # Unit tests
```

---

## Roadmap

- **v1** (current) — Rule-based scoring, Telegram notification, GitHub Actions
- **v1.5** — Accuracy tracking, weight tuning
- **v2** — GitHub Pages dashboard
- **v3** — ML enhancement (after sufficient labeled data)

---

## Troubleshooting

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `ModuleNotFoundError` | venv chưa activate | `source .venv/bin/activate` |
| `FileNotFoundError: settings.yaml` | Chạy từ thư mục sai | Chạy từ project root |
| Telegram không nhận được | Token/Chat ID sai | Verify bằng curl: `curl https://api.telegram.org/bot{TOKEN}/getMe` |
| yfinance trả về empty | Weekend hoặc holiday | Bình thường — thị trường đóng cửa |
