"""TwelveData REST API client for OHLCV time series.

Supports daily (1day) and hourly (1h) intervals.

Rate limits (free plan):
  - 8 API credits/minute
  - 800 API credits/day
  Each /time_series call = 1 credit.

This client implements a token-bucket rate limiter that stays under 8 req/min
by waiting automatically before each request when the bucket is exhausted.

Symbols use TwelveData native format: "EUR/USD", "GBP/USD", "DX", etc.

Reference: https://twelvedata.com/docs#time-series
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap: inject local twelvedata install if package not in active env
# ---------------------------------------------------------------------------
_FALLBACK_PKG_PATH = "/tmp/td_pkgs_py314"
try:
    import requests  # noqa: F401
except ImportError:
    if Path(_FALLBACK_PKG_PATH).exists():
        sys.path.insert(0, _FALLBACK_PKG_PATH)

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com/time_series"
_MAX_RETRIES = 5
_RATE_LIMIT_BACKOFF = 65  # seconds to wait when rate-limited (one full minute + buffer)

# Max outputsize per request for TwelveData free plan
_MAX_OUTPUTSIZE = 5000

# ---------------------------------------------------------------------------
# Token-bucket rate limiter: max 8 requests per 60 seconds
# ---------------------------------------------------------------------------
_RATE_LIMIT_PER_MINUTE = 7  # use 7 (not 8) to have 1 request safety margin
_RATE_WINDOW_SECONDS = 62   # slightly over 60s window for safety
_request_timestamps: deque[float] = deque()


def _wait_for_rate_limit() -> None:
    """Block until we are under the rate limit, then record this request."""
    now = time.monotonic()
    # Remove timestamps older than our window
    while _request_timestamps and (now - _request_timestamps[0]) > _RATE_WINDOW_SECONDS:
        _request_timestamps.popleft()

    if len(_request_timestamps) >= _RATE_LIMIT_PER_MINUTE:
        # How long until the oldest request expires from the window?
        oldest = _request_timestamps[0]
        wait = _RATE_WINDOW_SECONDS - (now - oldest) + 0.5
        if wait > 0:
            logger.info(
                "Rate limit: %d/%d requests in last %ds — waiting %.1fs ...",
                len(_request_timestamps), _RATE_LIMIT_PER_MINUTE, _RATE_WINDOW_SECONDS, wait,
            )
            time.sleep(wait)

    _request_timestamps.append(time.monotonic())


# Internal interval alias map: short form → TwelveData API interval string
_INTERVAL_MAP: dict[str, str] = {
    "1d": "1day",
    "1h": "1h",
    "1wk": "1week",
}


def to_twelvedata_interval(interval: str) -> str:
    """Convert short interval alias to TwelveData API interval string.

    Examples: "1d" → "1day", "1wk" → "1week". Pass-through if already native.
    """
    return _INTERVAL_MAP.get(interval, interval)


def fetch_time_series(
    symbol: str,
    interval: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    outputsize: int = _MAX_OUTPUTSIZE,
    api_key: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV time series from TwelveData (rate-limited, with retry).

    Args:
        symbol:      TwelveData symbol (e.g. "EUR/USD").
        interval:    TwelveData interval (e.g. "1day", "1h").
        start_date:  ISO date "YYYY-MM-DD". Optional.
        end_date:    ISO date "YYYY-MM-DD". Optional.
        outputsize:  Number of data points to return (max 5000 per request).
        api_key:     TwelveData API key. Falls back to TWELVEDATA_API_KEY env var.

    Returns:
        DataFrame with columns [Open, High, Low, Close, Volume] indexed by UTC
        datetime (timezone-aware). Returns None if all retries fail.
    """
    key = api_key or os.environ.get("TWELVEDATA_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "TWELVEDATA_API_KEY is not set. "
            "Add it to .env or pass api_key= explicitly."
        )

    params: dict = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "format": "JSON",
        "apikey": key,
    }
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    for attempt in range(_MAX_RETRIES):
        # Check rate limit before every request
        _wait_for_rate_limit()

        try:
            resp = requests.get(_BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "error":
                msg = data.get("message", "")
                # Detect per-minute rate limit and wait a full minute
                if "run out of API credits" in msg or "rate limit" in msg.lower():
                    logger.warning(
                        "Per-minute rate limit hit for %s/%s — waiting %ds (attempt %d/%d)",
                        symbol, interval, _RATE_LIMIT_BACKOFF, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(_RATE_LIMIT_BACKOFF)
                    continue
                logger.warning(
                    "TwelveData API error for %s/%s: %s (attempt %d/%d)",
                    symbol, interval, msg, attempt + 1, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(5)
                continue

            values = data.get("values", [])
            if not values:
                logger.warning(
                    "Empty values for %s/%s (attempt %d/%d)",
                    symbol, interval, attempt + 1, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(5)
                continue

            df = _parse_response(values)
            logger.debug(
                "TwelveData: %s/%s → %d candles", symbol, interval, len(df)
            )
            return df

        except requests.RequestException as exc:
            logger.warning(
                "HTTP error for %s/%s (attempt %d/%d): %s",
                symbol, interval, attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(10)

        except Exception as exc:
            logger.warning(
                "Unexpected error for %s/%s (attempt %d/%d): %s",
                symbol, interval, attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(5)

    logger.error("TwelveData: all retries failed for %s/%s", symbol, interval)
    return None


def _parse_response(values: list[dict]) -> pd.DataFrame:
    """Parse TwelveData values list into a UTC-indexed OHLCV DataFrame.

    TwelveData returns newest-first; we reverse to chronological order.
    """
    records = []
    for row in reversed(values):
        records.append({
            "datetime": row["datetime"],
            "Open": float(row["open"]),
            "High": float(row["high"]),
            "Low": float(row["low"]),
            "Close": float(row["close"]),
            "Volume": float(row.get("volume", 0) or 0),
        })

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df


def fetch_ohlcv_paginated(
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    api_key: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Fetch a long date range by paginating through 5000-row chunks.

    Each page uses 1 API credit. The built-in rate limiter automatically
    pauses when approaching the 8 requests/minute limit.

    Args:
        symbol:     TwelveData symbol (e.g. "EUR/USD").
        interval:   TwelveData interval (e.g. "1day", "1h").
        start_date: ISO date "YYYY-MM-DD".
        end_date:   ISO date "YYYY-MM-DD".
        api_key:    TwelveData API key.

    Returns:
        Concatenated, deduplicated DataFrame sorted ascending by datetime.
    """
    chunks: list[pd.DataFrame] = []
    current_end = end_date
    start_ts = pd.Timestamp(start_date, tz="UTC")

    max_pages = 50  # safety limit — 50 pages × 5000 bars = 250k bars max
    page = 0

    while page < max_pages:
        chunk = fetch_time_series(
            symbol=symbol,
            interval=interval,
            start_date=start_date,
            end_date=current_end,
            outputsize=_MAX_OUTPUTSIZE,
            api_key=api_key,
        )
        if chunk is None or chunk.empty:
            break

        chunks.append(chunk)
        oldest = chunk.index[0]

        # If we've reached or passed the start_date, we're done
        if oldest <= start_ts:
            break

        # Move end_date back to one day before the oldest row we got
        next_end = (oldest - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if next_end == current_end:
            break  # no progress — safety stop
        current_end = next_end
        page += 1

        logger.info(
            "Paginating %s/%s: page %d oldest=%s, continuing from %s",
            symbol, interval, page, oldest.date(), current_end,
        )

    if not chunks:
        return None

    combined = pd.concat(chunks)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    combined = combined[combined.index >= start_ts]
    return combined
