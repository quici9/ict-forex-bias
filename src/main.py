"""Entry point — orchestrates the full ICT Forex Bias pipeline.

Phase 0: skeleton with placeholder functions.
Subsequent phases will replace placeholders with real implementations.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from src.config import AppConfig, load_config
from src.models import InstrumentData, InstrumentFeatures, InstrumentScore, RunResult

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Pipeline steps (stubs — replaced phase by phase)
# ---------------------------------------------------------------------------

def fetch_data(config: AppConfig) -> dict[str, InstrumentData]:
    """Phase 1: Fetch OHLCV from yfinance for all enabled instruments."""
    logger.info("[STUB] fetch_data — returning empty dict")
    return {}


def calculate_features(
    instruments: dict[str, InstrumentData],
    config: AppConfig,
) -> dict[str, InstrumentFeatures]:
    """Phase 2: Compute ICT features for each instrument."""
    logger.info("[STUB] calculate_features — returning empty dict")
    return {}


def score(
    features: dict[str, InstrumentFeatures],
    config: AppConfig,
) -> list[InstrumentScore]:
    """Phase 3: Score each instrument and assign bias label."""
    logger.info("[STUB] score — returning empty list")
    return []


def notify(scores: list[InstrumentScore], session: str, config: AppConfig) -> None:
    """Phase 4: Format and send Telegram message."""
    logger.info("[STUB] notify — session=%s, instruments=%d", session, len(scores))
    logger.info("[STUB] Would send Telegram message here")


def persist(run_result: RunResult, config: AppConfig) -> None:
    """Phase 5: Append run result to data/history.json."""
    logger.info("[STUB] persist — run_id=%s, session=%s", run_result.run_id, run_result.session)


# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------

def detect_session() -> str:
    """Detect Kill Zone session from current UTC hour."""
    utc_hour = datetime.now(timezone.utc).hour
    if 1 <= utc_hour < 4:
        return "london"
    if 6 <= utc_hour < 9:
        return "new_york"
    # Fallback for manual / off-schedule runs
    return "manual"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(config: Optional[AppConfig] = None) -> RunResult:
    """Execute the full pipeline end-to-end."""
    start_time = time.time()
    errors: list[str] = []
    run_id = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session = detect_session()

    logger.info("=" * 60)
    logger.info("ICT Forex Bias — starting run [%s] session=%s", run_id, session)
    logger.info("=" * 60)

    if config is None:
        config = load_config()

    logger.info(
        "Config loaded — %d instruments enabled",
        len(config.enabled_instruments),
    )

    # Step 1 — Data
    instruments = fetch_data(config)

    # Step 2 — Features
    features = calculate_features(instruments, config)

    # Step 3 — Scoring
    scores = score(features, config)

    # Step 4 — Notify
    notify(scores, session, config)

    # Step 5 — Persist
    top_pick = scores[0].symbol if scores else None
    duration = round(time.time() - start_time, 2)
    timestamp_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    run_result = RunResult(
        run_id=run_id,
        session=session,
        timestamp_utc=timestamp_utc,
        instruments=scores,
        top_pick=top_pick,
        duration_seconds=duration,
        errors=errors,
    )

    persist(run_result, config)

    logger.info(
        "Run complete — duration=%.2fs, instruments=%d, errors=%d",
        duration,
        len(scores),
        len(errors),
    )

    return run_result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_pipeline()
