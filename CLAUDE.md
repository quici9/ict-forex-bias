# ICT Forex Bias System - Claude Guide

This file provides context and strict guidelines for Claude when working on the **ICT Forex Bias System** repository.

## 🎯 Project Overview
- **Purpose:** An automated pipeline that analyzes the Forex market using ICT (Inner Circle Trader) concepts, determines Daily Bias (Bullish / Bearish / Neutral), and ranks pairs based on signal convergence.
- **Key Constraints:** 
  - Fast execution (under 90 seconds). 
  - Fully automated via GitHub Actions (runs twice a day before London and NY Kill Zones).
  - No automated trading/entry execution. No ML/AI models for scoring in v1.

## 🏗 Architecture & Core Principles
- **Vertical Slices:** Prioritize building end-to-end working features over completing horizontal layers.
- **Config & Model First:** Always define data models (`src/models.py`) and configurations (`config/settings.yaml`) before writing any business logic.
- **Testability:** Every module must be testable locally using `scripts/run_local.py` before wiring into GitHub Actions.
- **Separation of Concerns:**
  - `src/data/`: Handles fetching, validation, and resampling. Knows only about DataFrames and OHLCV.
  - `src/features/`: Calculates ICT features from DataFrames. Knows only about math and feature vectors. Ignorant of scoring logic.
  - `src/scoring/`: Computes aggregated scores and assigns bias labels based on feature vectors. Ignorant of Telegram or external notifications.
  - `src/notify/`: Formats results and communicates with Telegram Bot API.

## 💻 Tech Stack
- **Language:** Python 3.11+
- **Data & Computation:** `pandas`, `numpy`
- **Data Source:** `TwelveData` (REST API, requires `TWELVEDATA_API_KEY` env var)
- **Testing:** `pytest`

## 📋 Development Rules
- **TypeScript/Python Equivalence Rules:** Keep code DRY and SOLID. Prioritize readability over cleverness.
- **Naming Conventions:** 
  - Functions, Variables, Methods: `snake_case` (e.g., `get_active_fvgs`, `atr14_d1`)
  - Classes, Dataclasses: `PascalCase` (e.g., `InstrumentData`, `SwingPoint`)
  - Constants: `SCREAMING_SNAKE_CASE`
- **Typing:** Always use Python type hints (`list[str]`, `dict`, `pd.DataFrame`).
- **Data Models:** Leverage `@dataclass` extensively for internal data structures (defined in `src/models.py`).
- **Code Size:** 
  - Keep functions under **40 lines**. Each function should do one thing perfectly.
  - Keep files under **300 lines**. Split if it gets too long.
- **Comments & Documentation:** All code comments MUST be written in English. Do not write dead/commented-out code.
- **Error Handling:** 
  - **Graceful degradation is mandatory**. If one instrument fails data fetching or validation, skip it and continue the pipeline for the rest. Do not let one failure crash the whole run.
  - Handle exceptions where external interactions occur (TwelveData API calls, Telegram API calls).

## 🧪 Testing Guidelines
- **Framework:** Use `pytest` for all unit and integration tests.
- **Fixtures:** Rely on static, sample OHLCV data stored as CSVs in `tests/fixtures/` for deterministic testing of feature logic.
- **Mocking:** Mock external dependencies (`requests.post` for TwelveData and Telegram) to keep unit tests fast and independent.
- **Focus:** Test behavior and edge cases (e.g., missing data, anomalous candles, look-ahead bias prevention). Let `pytest` guide development.

## 🚀 Execution Commands
- **Local testing:** `python scripts/run_local.py`
- **Run Unit Tests:** `pytest tests/`

## 📌 Alignment with Action Plan & System Design
Always refer to `docs/ICT_Forex_Bias_System_Design.md` as the ultimate source of truth for calculations, thresholds, and business rules. Use `docs/ICT_Forex_Bias_System_Action_Plan.md` to track current progress and determine the next logical implementation step.
