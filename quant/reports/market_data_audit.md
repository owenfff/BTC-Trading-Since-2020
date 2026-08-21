# Public Market Data Audit

- status: **READY_WITH_WARNINGS**
- analysis commit: `827106a2e5d8c20afe23bb20f52954baccb0f6e5`
- source: `BitMEX` public API; credentials: `none`
- symbol: `XBTUSD`
- requested interval: `5m`; selected interval: `5m`
- account execution bounds: `2020-05-01T09:03:47.360000Z` to `2026-07-18T22:11:15.556000Z` (98874 XBTUSD Trade rows)

## Source lineage

The canonical price series is requested from BitMEX `trade/bucketed`, with the official public S3 trade archive as an explicit fallback. Funding is requested from `funding`; the current `/instrument` endpoint is not treated as a historical mark/index series. Raw responses are kept only under ignored `quant/data/market/raw/` and their SHA-256 is recorded in the JSON report.

| source | status | rows | sha256 |
| --- | --- | ---: | --- |
| trade_bucketed_5m | PASS | 653630 | `48b5e518ec8f1d96e635b7f88e0dbc75201ce93001faedd6cbc5741131027a71` |
| public_archive_trade | AVAILABLE_EXPLICIT_FALLBACK_NOT_AUTO_SELECTED | 0 | `` |
| funding | PASS | 6809 | `b997b99c628d518191a3ea8f2d485604a567cf30f4d81a110384a1b7a197e83b` |
| instrument | UNAVAILABLE_HISTORICAL_SNAPSHOT_SERIES | 0 | `` |

## Coverage and gaps

- bar audit: `{"status": "PASS", "row_count": 653630, "valid_timestamp_count": 653630, "unique_timestamp_count": 653630, "duplicate_timestamp_count": 0, "timestamp_parse_failure_count": 0, "out_of_order_transition_count": 0, "first_timestamp_utc": "2020-05-01T09:05:00.000Z", "last_timestamp_utc": "2026-07-18T22:10:00.000Z", "expected_grid_count": 653630, "missing_grid_count": 0, "coverage_ratio": 1.0, "gap_count": 0}`
- derived 1h bar audit: `{"source_row_count": 653630, "normalized_row_count": 54470, "target_interval": "1h", "expected_child_count": 12, "incomplete_target_bar_count": 1, "note": "Derived by UTC bucket aggregation; no missing 5m child bar is filled.", "grid_audit": {"status": "PASS", "row_count": 54470, "valid_timestamp_count": 54470, "unique_timestamp_count": 54470, "duplicate_timestamp_count": 0, "timestamp_parse_failure_count": 0, "out_of_order_transition_count": 0, "first_timestamp_utc": "2020-05-01T10:00:00.000Z", "last_timestamp_utc": "2026-07-18T23:00:00.000Z", "expected_grid_count": 54470, "missing_grid_count": 0, "coverage_ratio": 1.0, "gap_count": 0}}`
- gap rows: `0`; details: `market_data_gaps.csv`
- context status counts: `{"COMPLETE": 0, "MARK_INDEX_MISSING": 653630, "FUNDING_MISSING": 0, "STALE_CONTEXT": 0}`

No gap is filled with a forward price. The context join is previous-or-equal UTC only; an observation after a bar cannot be used for that bar.

## Environment/blocking boundary

- public source status: `PASS`
- output: `{"market_bars": {"format": "csv_fallback_no_parquet_engine", "path": "quant\\outputs\\market_bars.csv", "requested_path": "quant\\outputs\\market_bars.parquet", "row_count": 653630}, "market_context": {"format": "csv_fallback_no_parquet_engine", "path": "quant\\outputs\\market_context.csv", "requested_path": "quant\\outputs\\market_context.parquet", "row_count": 653630}, "market_bars_1h": {"format": "csv_fallback_no_parquet_engine", "path": "quant\\outputs\\market_bars_1h.csv", "requested_path": "quant\\outputs\\market_bars_1h.parquet", "row_count": 54470}}`
- A future local network denial is an environment blocker, not evidence that BitMEX has no historical data. Rerun this script in a network-enabled environment or use the verified cached responses under the ignored market-data paths.
- This package does not use account API keys, private endpoints, live balances, or order placement.

## Next action

Market data is READY_WITH_WARNINGS: inspect the explicit mark/index warning and 1h child coverage, then begin leakage-safe M4 features and labels. Do not use current instrument snapshots for historical bars.
