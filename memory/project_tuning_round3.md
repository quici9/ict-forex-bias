---
name: project_tuning_round3
description: Tuning findings Rounds 1-6: session vol filter experiment, rule-based ceiling ~17-18%, Round 6 ICT pattern rebuild achieving 57.4% precision
type: project
---

## Rounds 1–5 Summary
- Rounds 1-5 used weighted scoring (7 ICT features) + session vol filter
- Best precision ceiling: ~17.8% after 32+ iterations
- Root cause: D1 feature alignment rate ~41% (coin flip); 77% sessions NEUTRAL actual
- LR model (Round 5): JPY=22.3%, non-JPY=5.1% — worse than rule-based
- Recommendation after Round 5: full rebuild

## Round 6 — ICT Pattern Rebuild (COMPLETED 2026-03-22)

**Logic (Tầng 1 — D1):** 4-state mutually exclusive check order:
1. INSIDE_BAR → NEUTRAL
2. REVERSAL (wick_pct filter) → BULLISH/BEARISH
3. CONTINUATION (close_pct filter) → BULLISH/BEARISH
4. NO_PATTERN → NEUTRAL

**Logic (Tầng 2 — H1):** BOS → CHoCH → FVG → CONFIRM/WARN/FLIP/NO_SIGNAL

**Phase A Results (9,431 rows, 2022-2026):**
- CONTINUATION: 44.2%, REVERSAL: 37.8%, INSIDE_BAR: 17.0%, NO_PATTERN: 1.1%
- Actual bias base rate: BULLISH 35.5%, NEUTRAL 32.4%, BEARISH 32.1%
- Naive accuracy: Continuation 56.3%, Reversal 36.8%

**Phase B Results (test set 2025-07-01 → 2026-03-21):**
- D1 overall precision: 0.482 (vs old 0.178 ceiling)
- CONTINUATION precision: 0.577, REVERSAL precision: 0.335
- H1 confirmation value: +0pp (does NOT improve precision)
- Signal frequency: 4.87/symbol/week (target 2-5 ✓)

**Phase C Best Params:**
- reversal_min_wick_pct: 0.3 (wick must exceed 30% of T-2 range)
- continuation_min_close_pct: 0.2 (close must be >20% of T-2 range outside)
- swing_lookback: 2 (H1 doesn't matter for precision)
- fvg_lookback_candles: 8 (H1 doesn't matter for precision)

**Phase C Results:**
- Train precision: 51.7%, Test precision: 57.4%, Gap: -5.8pp (no overfit)
- Frequency: 2.85 signals/symbol/week ✓
- vs old ceiling: +39.6pp absolute improvement

**Phase D:** Scorer rebuilt in `src/v2/pattern_scorer.py`

**Key Insight:** Simple ICT pattern logic (no scoring weights) dramatically outperforms old weighted approach. H1 confirmation layer adds negligible value. Next step: wire into main pipeline.

**Why:**
Round 6 was motivated by 32+ iterations failing to exceed 17.8% precision with complex weighted scoring. Pure ICT pattern logic (InsideBar/Reversal/Continuation) encodes the actual market structure rules rather than proxy features.

**How to apply:**
Use `src/v2/pattern_scorer.py` for all future bias calculations. Config in `config/settings_v2.yaml`. Do NOT revert to old scorer.py weighted approach.
