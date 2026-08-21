# Autonomous Blockers and Boundaries

## Known non-blocking research limitations

| Area | Status | Evidence | Downstream treatment |
| --- | --- | --- | --- |
| Quantity replay | EXACT | 173226 derivative executions; terminal XBTUSD quantity -998000 | Allowed as behavioral teacher state |
| Current cost engine | HIGH_CONFIDENCE_WITH_RESIDUAL | Closest candidate is about 2 raw units from snapshot | Analytical cost retained; exchange value retained separately |
| AEP engine | HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED | Displayed difference 0.2974 | Never used as an exact teacher label |
| Execution order | PARTIAL_WITH_CONFIDENCE_FLAGS | 11689 unique chains, 780 ambiguous, 371 cross-order ties | Carry ordering confidence into behavior dataset |
| Reported PnL | READY_WITH_WARNINGS | 8788 exact, 6951 mismatch among 15739 eligible | Keep reported and analytical PnL separate |
| Market context | READY_WITH_WARNINGS | 653,630 verified 5m bars and 54,470 derived 1h bars; zero 5m grid gaps; 6,809 funding rows; historical mark/index series unavailable from the current public instrument snapshot endpoint | Allow M4 only with explicit `MARK_INDEX_MISSING` flags and previous-or-equal UTC joins |
| Wallet reconciliation | READY_WITH_WARNINGS | 17474 row PASS, 5 real continuity anomalies, 3/15 exact snapshots, 12 zero snapshots without history, terminal equity PASS | Carry flags; do not fabricate joins |
| Behavior dataset | READY_WITH_WARNINGS | 160302 fills → 62388 batches → 31702 orders → 32231 decisions → 1401 cycles; XBTUSD 688 cycles | Allowed for market-context alignment; preserve confidence fields |
| Parquet runtime | ENVIRONMENT_WARNING | pyarrow/polars unavailable and PyPI blocked; explicit ignored CSV fallback generated | Restore pinned dependency before consuming Parquet-only tools |
| GitHub remote | READY | Autonomous branch pushed successfully; no PR was created | Continue pushing only the autonomous branch; never push `main` |
| Public HTTPS permission | CLEARED_FOR_M3 | Public BitMEX and GitHub HTTPS access succeeded in the resumed runtime | Keep no-key/public-only boundary |
| Leakage-safe features and labels | PASS_WITH_WARNINGS | 20,845 chronological BTC decision rows; all five future-information checks are zero; historical mark/index remains explicitly missing | Eligible for interpretable M5 distillation; no model training or live connectivity |
| Strategy distillation M5 | COMPLETE_WITH_WARNINGS | Frequency baseline, deterministic rules, NumPy Logistic Regression, and NumPy Decision Tree evaluated on TRAIN/VALIDATION/TEST; fidelity remains `BEHAVIORAL_APPROXIMATION` | Phase 7 may use the same Strategy Core; optional boosted-tree comparison is deferred because the runtime lacks pinned LightGBM/XGBoost |
| Phase 7 research | RESEARCH_ONLY | Three chronological walk-forward windows, 54 result rows, 22 robustness rows, parity PASS; no stable profitability claim | Proceed to Phase 8 while preserving unitless-return and historical mark/index warnings |

No current item is a HARD_STOP. A HARD_STOP is reserved for credentials/funds, paid data, destructive raw-data actions, unresolvable Git conflicts, repeated infrastructure failure, unavailable public data, or forced environment interruption.

## Phase 8–12 delivery boundary

- Domain model and fail-closed risk controls are complete; live mode remains disabled.
- Offline shadow and paper smoke tests pass using a checked-in one-row fixture. No exchange network call or order submission was made.
- BitMEX and Bybit adapters are mock-tested through injected transports. Real private endpoints are `DEMO_CREDENTIALS_REQUIRED`; credentials must not be requested automatically.
- Clean-room release status is `PASS_WITH_RESEARCH_INPUT_REHYDRATION_REQUIRED`. A fresh clone can compile and run the fixture smoke paths, while the full research command correctly stops until verified ignored market/behavior outputs are rehydrated.
- Release audit found no credential-like secrets. Tracked historical teacher/source exports remain subject to redistribution and licensing review.
- A fresh Python 3.11.9 environment installed all declared pinned dependencies; the clean-room suite passed 273 tests and skipped 2 tests that require intentionally ignored derived outputs.
- Docker Compose configuration passed. Docker image build could not reach Docker Hub's public `python:3.11-slim` registry, so Docker cold start remains unverified as an environment warning.

## Current work package

Phases 1 and 2 are complete. Wallet reconciliation is `READY_WITH_WARNINGS`; the residuals are preserved as flags and do not block BTC-first behavior episode construction.

## Current work package

Phases 1 through 4 are complete. Public market data is `READY_WITH_WARNINGS`; no strategy training or live connectivity is permitted before the M4 leakage audit passes.

## M3 public-market attempt

- `quant/reports/market_data_audit.md` and `quant/reports/market_data_lineage.json` are generated from the real repository execution bounds (`2020-05-01T09:03:47.360Z` through `2026-07-18T22:11:15.556Z` for XBTUSD Trade rows).
- BitMEX public REST `trade/bucketed` returned 653,630 XBTUSD 5m bars from `2020-05-01T09:05:00Z` through `2026-07-18T22:10:00Z`; the UTC grid has zero gaps and zero duplicates.
- Funding returned 6,809 rows. The current `/instrument` endpoint is a current snapshot, not a historical mark/index series; all historical mark/index values remain missing rather than using future data.
- The report is `READY_WITH_WARNINGS`, `raw_account_inputs_unchanged=true`, and large outputs remain ignored local artifacts. M4 may start only with the explicit context warning and leakage audit.

## M4 leakage-safe feature and label audit

- `quant/reports/model_dataset_manifest.json` records 20,845 XBTUSD decision rows, 529 synthetic daily HOLD/NO_TRADE rows, and a chronological 70/15/15 split.
- `quant/reports/leakage_audit.md` is `PASS`: future bars, future funding, future history, non-future labels, and invalid decision times all have zero violations.
- The large dataset is a local ignored CSV fallback because the runtime lacks a Parquet engine; no raw account input changed.
- Historical mark/index context remains `MARK_INDEX_MISSING` for all 20,845 rows and is represented explicitly, never backfilled from a current snapshot.

## M5 strategy fidelity boundary

- `quant/reports/strategy_fidelity.json` evaluates a TRAIN-only frequency baseline and a deterministic rule strategy across chronological TRAIN, VALIDATION, and TEST splits.
- Action confusion, position tracking, and regime fidelity are retained in separate small CSV reports.
- The results are descriptive behavioral fidelity only. They do not establish profitability, exact intent recovery, or permission to trade.
- Logistic and tree implementations use deterministic NumPy because sklearn, LightGBM, and XGBoost are unavailable in this runtime; no unpinned dependency was installed.

## M6 research boundary

- `quant/reports/quant_research_summary.json` is `RESEARCH_ONLY`, not an engineering block. It records 54 chronological validation/test rows and 22 robustness rows.
- All required families are present: fees +50% and ×2, 1/2/5 tick slippage, one-bar delay, ±10%/±20% exposure perturbations, top-cycle removal, bull/bear/sideways subsets, long-only, short-only, and multiple exposure limits.
- Results are a normalized exposure-return proxy, not BitMEX wallet/account PnL. Buy & Hold, teacher trajectory, and random controls are retained for context; teacher trajectory is descriptive only.
