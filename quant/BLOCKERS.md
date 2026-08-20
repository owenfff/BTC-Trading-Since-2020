# Autonomous Blockers and Boundaries

## Known non-blocking research limitations

| Area | Status | Evidence | Downstream treatment |
| --- | --- | --- | --- |
| Quantity replay | EXACT | 173226 derivative executions; terminal XBTUSD quantity -998000 | Allowed as behavioral teacher state |
| Current cost engine | HIGH_CONFIDENCE_WITH_RESIDUAL | Closest candidate is about 2 raw units from snapshot | Analytical cost retained; exchange value retained separately |
| AEP engine | HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED | Displayed difference 0.2974 | Never used as an exact teacher label |
| Execution order | PARTIAL_WITH_CONFIDENCE_FLAGS | 11689 unique chains, 780 ambiguous, 371 cross-order ties | Carry ordering confidence into behavior dataset |
| Reported PnL | READY_WITH_WARNINGS | 8788 exact, 6951 mismatch among 15739 eligible | Keep reported and analytical PnL separate |
| Market context | BLOCKED_ENVIRONMENT | M3 downloader/audit plus official daily public-trade archive fallback are implemented; BitMEX public 5m, 15m, and archive requests failed with managed-runtime WinError 10013; no bars were fabricated | Rerun in a network-enabled environment, verify cache/archive lineage, gaps, and context coverage, then allow leakage-safe modeling |
| Wallet reconciliation | READY_WITH_WARNINGS | 17474 row PASS, 5 real continuity anomalies, 3/15 exact snapshots, 12 zero snapshots without history, terminal equity PASS | Carry flags; do not fabricate joins |
| Behavior dataset | READY_WITH_WARNINGS | 160302 fills → 62388 batches → 31702 orders → 32231 decisions → 1401 cycles; XBTUSD 688 cycles | Allowed for market-context alignment; preserve confidence fields |
| Parquet runtime | ENVIRONMENT_WARNING | pyarrow/polars unavailable and PyPI blocked; explicit ignored CSV fallback generated | Restore pinned dependency before consuming Parquet-only tools |
| GitHub remote | ENVIRONMENT_BLOCKED | `git push` failed to connect to `github.com:443`; local branch remains committed and clean | Retry the authorized current-branch push when HTTPS access returns; no PR was created |

No current item is a HARD_STOP. A HARD_STOP is reserved for credentials/funds, paid data, destructive raw-data actions, unresolvable Git conflicts, repeated infrastructure failure, unavailable public data, or forced environment interruption.

## Current work package

Phases 1 and 2 are complete. Wallet reconciliation is `READY_WITH_WARNINGS`; the residuals are preserved as flags and do not block BTC-first behavior episode construction.

## Current work package

Phases 1 through 3 are complete. Public market data is `BLOCKED_ENVIRONMENT`; no strategy training or live connectivity is permitted before market lineage and leakage audits pass.

## M3 public-market attempt

- `quant/reports/market_data_audit.md` and `quant/reports/market_data_lineage.json` are generated from the real repository execution bounds (`2020-05-01T09:03:47.360Z` through `2026-07-18T22:11:15.556Z` for XBTUSD Trade rows).
- BitMEX `trade/bucketed` was attempted at 5m and the documented 15m fallback. Both public requests failed at the local socket boundary with `WinError 10013`; this is not evidence that the public source lacks history.
- The official `public.bitmex.com` daily trade archive fallback was attempted for the first three UTC partitions and stopped with the same repeated infrastructure error; the full 2,270-day range was not falsely marked complete.
- The report is `BLOCKED`, `raw_account_inputs_unchanged=true`, and no market output is treated as valid. No feature or label work may start until a verified public cache is available.
