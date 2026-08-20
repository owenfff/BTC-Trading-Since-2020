# Public Market Data Audit

- status: **BLOCKED**
- analysis commit: `e83cea15a4a825a9d1269320c51e67febf5ddb19`
- source: `BitMEX` public API; credentials: `none`
- symbol: `XBTUSD`
- requested interval: `5m`; selected interval: `none`
- account execution bounds: `2020-05-01T09:03:47.360000Z` to `2026-07-18T22:11:15.556000Z` (98874 XBTUSD Trade rows)

## Source lineage

The canonical price series is requested from BitMEX `trade/bucketed`, with the official daily `public.bitmex.com` trade archive as a no-key fallback. Funding is requested from `funding`, and mark/index context is requested from `instrument`. Raw responses are kept only under ignored `quant/data/market/raw/` and their SHA-256 is recorded in the JSON report.

| source | status | rows | sha256 |
| --- | --- | ---: | --- |
| trade_bucketed_5m | FAILED | 0 | `` |
| trade_bucketed_15m | FAILED | 0 | `` |
| public_archive_trade | FAILED_INCOMPLETE_RANGE | 0 | `` |
| funding | NOT_ATTEMPTED_NO_BARS | 0 | `` |
| instrument | NOT_ATTEMPTED_NO_BARS | 0 | `` |

## Coverage and gaps

- bar audit: `{"status": "BLOCKED", "row_count": 0, "valid_timestamp_count": 0, "unique_timestamp_count": 0, "duplicate_timestamp_count": 0, "timestamp_parse_failure_count": 0, "out_of_order_transition_count": 0, "first_timestamp_utc": "", "last_timestamp_utc": "", "expected_grid_count": 0, "missing_grid_count": 0, "coverage_ratio": 0.0, "gap_count": 0}`
- gap rows: `1`; details: `market_data_gaps.csv`
- context status counts: `{"COMPLETE": 0, "MARK_INDEX_MISSING": 0, "FUNDING_MISSING": 0, "STALE_CONTEXT": 0}`

No gap is filled with a forward price. The context join is previous-or-equal UTC only; an observation after a bar cannot be used for that bar.

## Environment/blocking boundary

- public source status: `BLOCKED_PUBLIC_DATA_UNAVAILABLE`
- output: `{}`
- A local network denial is an environment blocker, not evidence that BitMEX has no historical data. Rerun this script in a network-enabled environment or place verified responses/archive objects under the ignored market-data paths.
- This package does not use account API keys, private endpoints, live balances, or order placement.

## Next action

If market_data_status is BLOCKED, rerun in a network-enabled environment and freeze the verified public cache before starting leakage-safe features; if READY_WITH_WARNINGS, inspect market_data_gaps.csv and context coverage first.
