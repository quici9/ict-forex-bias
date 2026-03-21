"""Configuration loader — reads settings.yaml and exposes a typed AppConfig object."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Typed sub-configs
# ---------------------------------------------------------------------------

@dataclass
class InstrumentConfig:
    symbol: str
    name: str
    smt_partner: str
    enabled: bool = True


@dataclass
class ScoringWeights:
    d1_structure: float = 0.25
    structure_alignment: float = 0.15
    price_zone: float = 0.15
    fvg_h4: float = 0.15
    sweep: float = 0.15
    smt: float = 0.10
    bos_recent: float = 0.05


@dataclass
class ScoringThresholds:
    high_conviction: int = 70
    watchlist: int = 50


@dataclass
class W1Multipliers:
    aligned: float = 1.0
    ranging: float = 0.9
    counter_trend: float = 0.75


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)
    w1_multipliers: W1Multipliers = field(default_factory=W1Multipliers)
    low_vol_threshold: float = 0.30


@dataclass
class FeaturesConfig:
    swing_lookback: int = 5
    fvg_min_displacement: float = 1.5
    fvg_lookback_candles: int = 10
    sweep_lookback_candles: int = 3
    smt_max_candle_diff: int = 5


@dataclass
class DataConfig:
    d1_candles: int = 60
    h4_candles: int = 30
    h1_candles: int = 72
    w1_candles: int = 20
    min_d1_candles: int = 30
    min_h4_candles: int = 20
    min_h1_candles: int = 24
    min_w1_candles: int = 10
    pdh_pdl_atr_threshold: float = 0.5
    stale_data_days: int = 2


@dataclass
class NotificationConfig:
    timezone: str = "Asia/Ho_Chi_Minh"
    min_score_to_show: int = 50
    max_detail_instruments: int = 3


@dataclass
class AppConfig:
    instruments: list[InstrumentConfig] = field(default_factory=list)
    dxy_symbol: str = "DX-Y.NYB"
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    data: DataConfig = field(default_factory=DataConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)

    @property
    def enabled_instruments(self) -> list[InstrumentConfig]:
        return [inst for inst in self.instruments if inst.enabled]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load and validate settings.yaml, return a typed AppConfig."""
    config_path = path or _CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(f"settings.yaml not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return _parse_config(raw)


def _parse_config(raw: dict) -> AppConfig:
    instruments = [
        InstrumentConfig(
            symbol=inst["symbol"],
            name=inst["name"],
            smt_partner=inst["smt_partner"],
            enabled=inst.get("enabled", True),
        )
        for inst in raw.get("instruments", [])
    ]

    dxy_symbol = raw.get("reference", {}).get("dxy", "DX-Y.NYB")

    raw_scoring = raw.get("scoring", {})
    raw_weights = raw_scoring.get("weights", {})
    raw_thresholds = raw_scoring.get("thresholds", {})
    raw_multipliers = raw_scoring.get("w1_multipliers", {})

    scoring = ScoringConfig(
        weights=ScoringWeights(
            d1_structure=raw_weights.get("d1_structure", 0.25),
            structure_alignment=raw_weights.get("structure_alignment", 0.15),
            price_zone=raw_weights.get("price_zone", 0.15),
            fvg_h4=raw_weights.get("fvg_h4", 0.15),
            sweep=raw_weights.get("sweep", 0.15),
            smt=raw_weights.get("smt", 0.10),
            bos_recent=raw_weights.get("bos_recent", 0.05),
        ),
        thresholds=ScoringThresholds(
            high_conviction=raw_thresholds.get("high_conviction", 70),
            watchlist=raw_thresholds.get("watchlist", 50),
        ),
        w1_multipliers=W1Multipliers(
            aligned=raw_multipliers.get("aligned", 1.0),
            ranging=raw_multipliers.get("ranging", 0.9),
            counter_trend=raw_multipliers.get("counter_trend", 0.75),
        ),
        low_vol_threshold=raw_scoring.get("low_vol_threshold", 0.30),
    )

    raw_features = raw.get("features", {})
    features = FeaturesConfig(
        swing_lookback=raw_features.get("swing_lookback", 5),
        fvg_min_displacement=raw_features.get("fvg_min_displacement", 1.5),
        fvg_lookback_candles=raw_features.get("fvg_lookback_candles", 10),
        sweep_lookback_candles=raw_features.get("sweep_lookback_candles", 3),
        smt_max_candle_diff=raw_features.get("smt_max_candle_diff", 5),
    )

    raw_data = raw.get("data", {})
    data = DataConfig(
        d1_candles=raw_data.get("d1_candles", 60),
        h4_candles=raw_data.get("h4_candles", 30),
        h1_candles=raw_data.get("h1_candles", 72),
        w1_candles=raw_data.get("w1_candles", 20),
        min_d1_candles=raw_data.get("min_d1_candles", 30),
        min_h4_candles=raw_data.get("min_h4_candles", 20),
        min_h1_candles=raw_data.get("min_h1_candles", 24),
        min_w1_candles=raw_data.get("min_w1_candles", 10),
        pdh_pdl_atr_threshold=raw_data.get("pdh_pdl_atr_threshold", 0.5),
        stale_data_days=raw_data.get("stale_data_days", 2),
    )

    raw_notif = raw.get("notification", {})
    notification = NotificationConfig(
        timezone=raw_notif.get("timezone", "Asia/Ho_Chi_Minh"),
        min_score_to_show=raw_notif.get("min_score_to_show", 50),
        max_detail_instruments=raw_notif.get("max_detail_instruments", 3),
    )

    return AppConfig(
        instruments=instruments,
        dxy_symbol=dxy_symbol,
        scoring=scoring,
        features=features,
        data=data,
        notification=notification,
    )
