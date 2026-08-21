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

No current item is a HARD_STOP. A HARD_STOP is reserved for credentials/funds, paid data, destructive raw-data actions, unresolvable Git conflicts, repeated infrastructure failure, unavailable public data, or forced environment interruption.

## Current work package

Phases 1 and 2 are complete. Wallet reconciliation is `READY_WITH_WARNINGS`; the residuals are preserved as flags and do not block BTC-first behavior episode construction.

## Current work package

Phases 1 through 4 are complete. Public market data is `READY_WITH_WARNINGS`; no strategy training or live connectivity is permitted before the M4 leakage audit passes.

## M3 public-market attempt

- `quant/reports/market_data_audit.md` and `quant/reports/market_data_lineage.json` are generated from the real repository execution bounds (`2020-05-01T09:03:47.360Z` through `2026-07-18T22:11:15.556Z` for XBTUSD Trade rows).
- BitMEX public REST `trade/bucketed` returned 653,630 XBTUSD 5m bars from `2020-05-01T09:05:00Z` through `2026-07-18T22:10:00Z`; the UTC grid has zero gaps and zero duplicates.
- Funding returned 6,809 rows. The current `/instrument` endpoint is a current snapshot, not a historical mark/index series; all historical mark/index values remain missing rather than using future data.
- The report is `READY_WITH_WARNINGS`, `raw_account_inputs_unchanged=true`, and large outputs remain ignored local artifacts. M4 may start only with the explicit context warning and leakage audit.
