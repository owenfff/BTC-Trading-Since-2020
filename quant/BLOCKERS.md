# Autonomous Blockers and Boundaries

## Known non-blocking research limitations

| Area | Status | Evidence | Downstream treatment |
| --- | --- | --- | --- |
| Quantity replay | EXACT | 173226 derivative executions; terminal XBTUSD quantity -998000 | Allowed as behavioral teacher state |
| Current cost engine | HIGH_CONFIDENCE_WITH_RESIDUAL | Closest candidate is about 2 raw units from snapshot | Analytical cost retained; exchange value retained separately |
| AEP engine | HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED | Displayed difference 0.2974 | Never used as an exact teacher label |
| Execution order | PARTIAL_WITH_CONFIDENCE_FLAGS | 11689 unique chains, 780 ambiguous, 371 cross-order ties | Carry ordering confidence into behavior dataset |
| Reported PnL | READY_WITH_WARNINGS | 8788 exact, 6951 mismatch among 15739 eligible | Keep reported and analytical PnL separate |
| Market context | NOT_STARTED | No public market dataset built yet | Required before leakage-safe modeling |
| Wallet reconciliation | READY_WITH_WARNINGS | 17474 row PASS, 5 real continuity anomalies, 3/15 exact snapshots, 12 zero snapshots without history, terminal equity PASS | Carry flags; do not fabricate joins |
| Behavior dataset | READY_WITH_WARNINGS | 160302 fills → 62388 batches → 31702 orders → 32231 decisions → 1401 cycles; XBTUSD 688 cycles | Allowed for market-context alignment; preserve confidence fields |
| Parquet runtime | ENVIRONMENT_WARNING | pyarrow/polars unavailable and PyPI blocked; explicit ignored CSV fallback generated | Restore pinned dependency before consuming Parquet-only tools |

No current item is a HARD_STOP. A HARD_STOP is reserved for credentials/funds, paid data, destructive raw-data actions, unresolvable Git conflicts, repeated infrastructure failure, unavailable public data, or forced environment interruption.

## Current work package

Phases 1 and 2 are complete. Wallet reconciliation is `READY_WITH_WARNINGS`; the residuals are preserved as flags and do not block BTC-first behavior episode construction.

## Current work package

Phases 1 through 3 are complete. Public market data is `IN_PROGRESS`; no strategy training or live connectivity is permitted before market lineage and leakage audits pass.
