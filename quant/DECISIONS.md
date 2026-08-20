# Autonomous Decisions

## 2026-08-20 — Freeze accounting boundary

- Treat quantity reconstruction as `EXACT` and use the analytical ledger for behavioral research.
- Keep exchange-reported `realisedPnl`, `execComm`, Funding, wallet history, and position snapshots in a separate reported ledger.
- Keep analytical cost, gross PnL, AEP, cycles, and confidence flags in a separate analytical ledger.
- Classify current-cost fidelity as `HIGH_CONFIDENCE_WITH_RESIDUAL`; do not add more global rounding brute force unless wallet reconciliation supplies direct evidence.
- Classify AEP fidelity as `HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED`.
- Use `PASS` and `WARNING` valuation rows for downstream accounting; only `BLOCKED` rows are excluded.
- The dataset is `TRADE_RECORDS_ONLY`, so strategy fidelity is permanently reported as `BEHAVIORAL_APPROXIMATION`.

## 2026-08-20 — Enter wallet reconciliation

- Phase 1 is frozen in `accounting_foundation_manifest.json` with downstream status `READY_WITH_KNOWN_ACCOUNTING_RESIDUALS`.
- Wallet reconciliation is the next evidence-gathering step; it may improve accounting confidence but must not fabricate one-to-one joins when wallet exports do not carry a unique execution reference.
- Reconciliation will be reported at execution, hour, day, and terminal-snapshot levels according to available evidence.

## 2026-08-20 — Freeze wallet reconciliation boundary

- Use wallet `timestamp` as the balance-ledger order because `transactTime` can precede the exported balance event.
- Treat repeated rows sharing a final `walletBalance` as one continuity batch; compare the sum of completed amounts to the batch balance delta.
- Wallet reconciliation is `READY_WITH_WARNINGS`: 17,474 row-level PASS, 5 real batch anomalies, 3/15 exact snapshot matches, 12 zero snapshots without wallet-history coverage, and terminal XBT/equity agreement.
- Keep wallet-to-execution comparisons aggregate-only; do not fabricate a row-level join from `transactID`, `orderID`, or address fields.
- Proceed to BTC-first behavior episodes and trade cycles while carrying wallet continuity and snapshot coverage flags into derived datasets.

## 2026-08-20 — Enter behavioral episode construction

- Preserve the layered structure: raw derivative fills → execution batches → order episodes → position actions → decision episodes → position cycles.
- XBTUSD is the BTC-first teacher scope; altcoin derivative episodes remain available for generalization diagnostics.
- Execution batches use a documented 300-second same-order gap boundary and never redefine an order episode as a decision.
- Daily XBTUSD no-trade days become explicitly synthetic `HOLD_LONG`, `HOLD_SHORT`, or `NO_TRADE` observations; they are never mixed with raw fills.
- Wallet linkage remains aggregate-only and all six confidence fields are carried into actions, decisions, and cycles.

## 2026-08-20 — Freeze behavioral dataset boundary

- Behavior layers are complete: 160,302 derivative fills, 62,388 execution batches, 31,702 order episodes, 32,231 decisions, and 1,401 position cycles.
- BTC-first teacher scope is XBTUSD: 98,874 fills, 20,316 order episodes, 20,845 decisions, and 688 cycles; 529 daily synthetic HOLD/NO_TRADE observations are explicit negative/carry-forward samples.
- All cycles include `overall_confidence` plus the compatibility `confidence_status`; no future cycle result is included in action or decision rows.
- The underlying accounting engine audit remains `BLOCKED` by unresolved global rounding selection, but downstream event-level eligibility remains `PASS/WARNING` and is reported as `READY_WITH_KNOWN_ACCOUNTING_RESIDUALS`.
- Current runtime could not materialize Parquet because `pyarrow`/`polars` are unavailable and PyPI is unreachable; ignored CSV fallbacks preserve the same schemas and are explicitly recorded in the report.
- Proceed to public BTC market data; no model training starts before leakage-safe market alignment exists.

## 2026-08-20 — Freeze M3 market-source boundary

- Use BitMEX's public no-key `trade/bucketed` as the canonical XBTUSD price source; request 5m first and 15m only as the documented resolution fallback.
- Request funding from public `funding` and mark/index context from public `instrument`; preserve source URL, UTC bounds, download/cache time, and SHA256 in `market_data_lineage.json`.
- Join context using previous-or-equal UTC observations only. Missing bars and missing mark/index/funding values remain explicit; no forward price or future observation is invented.
- The managed desktop runtime blocked both 5m and 15m public requests with WinError 10013. Keep M3 `BLOCKED` at the environment boundary and do not start leakage-safe features until a verified public cache is available.
- Use the official `public.bitmex.com/data/trade/YYYYMMDD.csv.gz` archive as the no-key fallback when REST pagination is unavailable. Aggregate raw trades locally into closed UTC 5m bars, preserve each daily gzip unchanged with SHA-256, reject incomplete date ranges, and never infer mark/index/funding from trade prices.

## 2026-08-20 — Environment HARD_STOP

- BitMEX REST, the official public archive, and GitHub HTTPS all failed with the same managed-runtime socket restriction across repeated attempts.
- A turn-scoped request for public HTTPS permission was not granted. Stop at M3 with all code, tests, reports, and recovery instructions committed locally; do not start M4 features without real market bars.
