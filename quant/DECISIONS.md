# Autonomous Decisions

## 2026-08-20 — Freeze accounting boundary

- Treat quantity reconstruction as `EXACT` and use the analytical ledger for behavioral research.
- Keep exchange-reported `realisedPnl`, `execComm`, Funding, wallet history, and position snapshots in a separate reported ledger.
- Keep analytical cost, gross PnL, AEP, cycles, and confidence flags in a separate analytical ledger.
- Classify current-cost fidelity as `HIGH_CONFIDENCE_WITH_RESIDUAL`; do not add more global rounding brute force unless wallet reconciliation supplies direct evidence.
- Classify AEP fidelity as `HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED`.
- Use `PASS` and `WARNING` valuation rows for downstream accounting; only `BLOCKED` rows are excluded.
- The dataset is `TRADE_RECORDS_ONLY`, so strategy fidelity is permanently reported as `BEHAVIORAL_APPROXIMATION`.

## 2026-08-20 — Freeze M5.1 strategy-core boundary

- Use one exchange-neutral Strategy Core contract for research callers. The strategy layer must not import exchange SDKs or submit orders.
- The first fidelity comparison is intentionally limited to a TRAIN-only historical frequency baseline and deterministic rules. No opaque ML model, hyperparameter search, profitability claim, or live connection is introduced in M5.1.
- The Strategy Core receives only M4 features and prior account state; observed target/action and all `label_*` columns are forbidden inputs.
- Preserve the required fidelity measures, including action macro/weighted F1, target exposure MAE/correlation, open/close miss-latency proxies, add/reduce/flip recall, cycle direction match, regime fidelity, and confidence calibration.
- M5.2 may add Logistic Regression and Decision Tree comparisons only if dependencies are available and the same leakage-safe input and signal contracts remain in force.

## 2026-08-20 — Complete M5 strategy comparison boundary

- M5 completed four descriptive models: TRAIN-only frequency baseline, deterministic rules, deterministic NumPy Logistic Regression, and a depth-limited NumPy Decision Tree.
- The exact Strategy Core signal contract is shared across these models; no strategy code imports exchange SDKs.
- External sklearn, LightGBM, and XGBoost were unavailable in the runtime and were not installed. This is an environment warning, not a reason to change the raw-data or no-live-trading boundary.
- Proceed to Phase 7 only through a single Strategy Core parity harness and a chronological backtest that models fees, funding, slippage, delay, next-bar execution, limits, lots, ticks, and settlement currencies.

## 2026-08-21 — Complete M6 research boundary

- Use `RESEARCH_ONLY` for the current research result. It is a valid reproducibility outcome, not an engineering blocker and not a profitability claim.
- Funding from the as-of context table must be charged only at unique `funding_source_timestamp_utc` event times; repeated as-of rows are not separate payments.
- Use the same Strategy Core for batch and streaming-style signal generation. The parity sample passed for all four models.
- Keep Buy & Hold, simple moving-average trend, volatility-filtered trend, distilled rules, imitation baseline, same-turnover random, and teacher trajectory in the comparison set. Teacher trajectory remains descriptive only.
- The normalized exposure-return proxy is not the BitMEX wallet/account ledger. Phase 8 must not convert it into live capital claims or order instructions.

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

## 2026-08-20 — Complete M3 public market data

- Public BitMEX REST access succeeded after the environment resumed. The downloader uses 7-day UTC windows, retries truncated responses, and recursively splits unstable windows; each complete response is cached with SHA256 under ignored paths.
- The frozen XBTUSD range contains 653,630 valid 5m bars with zero duplicates, zero timestamp parse failures, zero out-of-order transitions, and zero grid gaps. A local 1h series contains 54,470 derived bars and records one incomplete edge bucket without filling it.
- Funding coverage contains 6,809 rows. The current public `/instrument` endpoint is not accepted as historical mark/index data; all 653,630 context rows remain `MARK_INDEX_MISSING` rather than using a future snapshot.
- M3 is `READY_WITH_WARNINGS`. Begin M4 leakage-safe features and labels only with previous-or-equal UTC joins, no future observations, and an explicit mark/index missingness feature/flag.

## 2026-08-20 — Complete M4 leakage-safe features and labels

- Build one chronological row per XBTUSD decision, including the 529 explicit synthetic daily HOLD/NO_TRADE observations; do not restrict the dataset to trade timestamps.
- Market features use only closed bars with `bar_end_time < decision_time`; funding is as-of with source time `<= decision_time`; account history is strictly earlier than the decision.
- Labels use the next strictly later decision, skip same-timestamp ties, and remain separate from features. No future cycle profit/high/low or test-period normalization statistic is used.
- The 20,845-row dataset has a chronological 70/15/15 split and a `PASS` leakage audit with zero violations in all five checks.
- Historical mark/index context remains explicitly missing. The dataset is eligible for interpretable strategy distillation, but model training, API credentials, live trading, and PR creation remain out of scope.

## 2026-08-21 — Freeze offline runtime boundary

- Shadow and paper modes are allowed only as offline, credential-free smoke paths until a separate human review authorizes any exchange connectivity.
- Clean-room releases include a small checked-in fixture. Large verified market and behavior outputs remain ignored and require explicit rehydration; a fresh clone must not silently fabricate them.
- `quant_research_runnable=false` is an intentional release-manifest value when those ignored inputs are absent. The research command must fail closed with an input error rather than substitute synthetic market history.

## 2026-08-21 — Freeze adapter credential boundary

- Mock transports may test normalization, idempotency, and adapter error handling without network access.
- Real private exchange calls remain `DEMO_CREDENTIALS_REQUIRED`; no API key or private account is requested in autonomous mode.
- Default live risk and notional limits remain zero, and `live_enabled` remains false.

## 2026-08-21 — Freeze cross-asset behavioral boundary

- Use all 66 historical symbols for the behavior inventory, but keep Spot and derivative semantics separate.
- Use only public no-key BitMEX hourly trade buckets and funding; no synthetic market history and no current-snapshot backfill for historical mark/index values.
- Fit position scales from chronological TRAIN rows only. Symbols without a TRAIN scale are excluded from the unified model instead of using future information.
- Keep the Strategy Core exchange-neutral and label the model `BEHAVIORAL_APPROXIMATION`; it outputs action, target exposure, confidence, risk tags, and validity but never submits orders.
- Require zero leakage violations, per-symbol traceability, three time-out windows, sensitivity diagnostics, and repeatable local paper replay before considering the phase complete.
- No API key, private endpoint, demo account, testnet account, or real capital is needed for this phase.

## 2026-08-24 — Add multi-venue non-production runtime boundary

- Keep historical strategy learning exchange-neutral; venue symbol mapping is
  a runtime eligibility/crosswalk layer only and never rewrites teacher data or
  model features.
- Add native, hard-pinned OKX Demo and Binance Spot Testnet REST adapters with
  local-only credential gates and deterministic injected-transport tests.
- Use the existing Bybit private-WebSocket runner unchanged. The first shared
  OKX/Binance runner uses REST polling, records that fact in runtime state, and
  remains non-production only.
- Treat Binance Spot as wallet-balance semantics. It cannot short or use
  `reduceOnly`; derivative-trained targets require an explicit behavioral
  approximation flag and negative targets flatten rather than short.
- Do not call this phase complete for production readiness until the new
  private streams survive long-run soak tests and a human-approved
  non-production order lifecycle has been verified.

## 2026-08-21 — Freeze clean-room release evidence

- Lock the release dependencies to the versions installed in the fresh Python 3.11.9 environment: NumPy 2.3.5, Polars 1.43.2, PyArrow 24.0.0, and Pytest 8.4.2.
- The full research command fails closed with structured `BLOCKED_INPUTS_MISSING` when ignored market/behavior outputs are absent. It must never substitute synthetic market history for a release smoke test.
- Repeated fixture shadow and paper runs are reproducible. This proves framework smoke behavior only; it does not prove long-running stability or profitability.
- Keep full research/test dependencies in `quant/requirements.txt` and use the smaller pinned `quant/runtime-requirements.txt` for the paper/shadow Docker image. The image was built and run successfully as `btc-trading-clean-room:9c8cf24` with read-only storage and temporary `/tmp`; this validates packaging and fixture smoke only, not exchange connectivity or profitability.
