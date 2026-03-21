"""Smoke tests for Phase 0 — verifies config loading and data models are correct."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.config import load_config, AppConfig
from src.models import InstrumentData, InstrumentFeatures, InstrumentScore, RunResult


CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

EXPECTED_SYMBOLS = {
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X",
    "AUDUSD=X", "NZDUSD=X", "USDCAD=X", "GBPJPY=X",
}


class TestConfigLoading:
    def test_config_loads_without_error(self):
        config = load_config(CONFIG_PATH)
        assert isinstance(config, AppConfig)

    def test_all_instruments_present(self):
        config = load_config(CONFIG_PATH)
        symbols = {inst.symbol for inst in config.instruments}
        assert symbols == EXPECTED_SYMBOLS

    def test_all_instruments_enabled_by_default(self):
        config = load_config(CONFIG_PATH)
        for inst in config.instruments:
            assert inst.enabled is True

    def test_smt_partners_are_valid_symbols(self):
        config = load_config(CONFIG_PATH)
        valid_symbols = EXPECTED_SYMBOLS | {"DX-Y.NYB"}
        for inst in config.instruments:
            assert inst.smt_partner in valid_symbols, (
                f"{inst.symbol} has invalid SMT partner: {inst.smt_partner}"
            )

    def test_scoring_weights_sum_to_one(self):
        config = load_config(CONFIG_PATH)
        w = config.scoring.weights
        total = (
            w.d1_structure
            + w.structure_alignment
            + w.price_zone
            + w.fvg_h4
            + w.sweep
            + w.smt
            + w.bos_recent
        )
        assert abs(total - 1.0) < 1e-6, f"Weights sum to {total}, expected 1.0"

    def test_high_conviction_threshold_above_watchlist(self):
        config = load_config(CONFIG_PATH)
        assert config.scoring.thresholds.high_conviction > config.scoring.thresholds.watchlist

    def test_w1_multipliers_ordered(self):
        config = load_config(CONFIG_PATH)
        m = config.scoring.w1_multipliers
        assert m.counter_trend < m.ranging <= m.aligned

    def test_dxy_reference_symbol(self):
        config = load_config(CONFIG_PATH)
        assert config.dxy_symbol == "DX-Y.NYB"


class TestDataModels:
    def test_instrument_features_all_fields_optional(self):
        """InstrumentFeatures must allow partial population (fields filled phase by phase)."""
        features = InstrumentFeatures(symbol="EURUSD=X")
        # All optional fields should be None by default
        assert features.d1_structure is None
        assert features.fvg_exists_h4 is None
        assert features.smt_signal is None

    def test_instrument_score_instantiates(self):
        score = InstrumentScore(
            symbol="EURUSD=X",
            bias="NEUTRAL",
            score=0,
            bullish_score=0.0,
            bearish_score=0.0,
            w1_multiplier=1.0,
            is_counter_trend=False,
            is_low_vol=False,
            top_signals=[],
        )
        assert score.symbol == "EURUSD=X"

    def test_run_result_instantiates(self):
        result = RunResult(
            run_id="2026-03-21T01:45:00+00:00",
            session="london",
            timestamp_utc="2026-03-21T01:47:00+00:00",
            instruments=[],
            top_pick=None,
            duration_seconds=3.14,
        )
        assert result.session == "london"
        assert result.errors == []


class TestMainOrchestrator:
    def test_pipeline_runs_without_exception(self):
        """Full skeleton pipeline must complete without raising any exception."""
        from src.main import run_pipeline
        result = run_pipeline()
        assert isinstance(result, RunResult)

    def test_session_detection_returns_string(self):
        from src.main import detect_session
        session = detect_session()
        assert isinstance(session, str)
        assert session in {"london", "new_york", "manual"}
