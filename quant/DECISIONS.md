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

## 2026-08-24 — Keep venue selection single by default and add futures semantics

- Supporting multiple exchanges does not mean running them simultaneously.
  Every normal launch selects exactly one venue; the existing supervisor is an
  explicit opt-in diagnostic path and is not the default.
- Binance Spot remains available only as an explicitly acknowledged cash-market
  behavioral approximation. Historical derivative behavior is mapped natively
  to a separate Binance USDⓈ-M Futures Testnet adapter when that venue is
  selected.
- The Binance Futures adapter is restricted to the official demo-fapi and
  demo-fstream hosts, USDT-margined perpetuals, `positionSide=BOTH`, Decimal
  quantity/price normalization, `GTX` post-only and `reduceOnly` risk-reduction
  orders.
- No credential, private endpoint, or order lifecycle was used in autonomous
  tests; real Demo/Testnet preflight remains an external local step.

## 2026-08-21 — Freeze clean-room release evidence

- Lock the release dependencies to the versions installed in the fresh Python 3.11.9 environment: NumPy 2.3.5, Polars 1.43.2, PyArrow 24.0.0, and Pytest 8.4.2.
- The full research command fails closed with structured `BLOCKED_INPUTS_MISSING` when ignored market/behavior outputs are absent. It must never substitute synthetic market history for a release smoke test.
- Repeated fixture shadow and paper runs are reproducible. This proves framework smoke behavior only; it does not prove long-running stability or profitability.
- Keep full research/test dependencies in `quant/requirements.txt` and use the smaller pinned `quant/runtime-requirements.txt` for the paper/shadow Docker image. The image was built and run successfully as `btc-trading-clean-room:9c8cf24` with read-only storage and temporary `/tmp`; this validates packaging and fixture smoke only, not exchange connectivity or profitability.

## 2026-08-24 — Add one-command multi-venue supervision

- Keep the Strategy Core exchange-neutral and supervise OKX Demo and Binance
  Spot Testnet as separate venue workers; never merge their balances,
  positions, contract units or Spot/derivative semantics.
- Treat a missing credential, region restriction, mapping failure or private
  stream failure as a venue-scoped `BLOCKED` result. It must not be converted
  into a successful overall run or an order submission.
- Preserve explicit testnet confirmation and the Binance Spot behavioral
  approximation flag. No mainnet endpoint, live credential or real capital is
  enabled by the unified launcher.
- Record code commit `dcfc1033dde8f5361818e4620ec98dee9bba4540`; full local
  verification is `314 passed` with no credentials. Remote push remains an
  external retry after the first GitHub HTTPS attempt failed.

## 2026-08-25 — Add loopback local control, keep public dashboard read-only

- The operator dashboard may start exactly one selectable OKX Demo, Binance
  Spot Testnet, or Binance USDⓈ-M Futures Testnet node only when the server is
  bound to loopback. A public or US-hosted dashboard cannot start a trading
  process.
- The browser sends no API key, secret, passphrase, password, or credential
  field. Windows launchers keep the existing local DPAPI credential flow;
  Linux nodes use credentials already provisioned in the local service
  environment.
- A Shanghai node is an acceptable trading/panel host if it can reach the
  selected official Demo/Testnet endpoints. The US host may remain a sanitized
  frontend-only observability surface.
- Normal operation still selects one venue. OKX/Binance support means
  selectable adapters, not a requirement to run them simultaneously.

## 2026-08-26 — Add Hyperliquid public replay and cross-venue indicator audit

- Treat the published Hyperliquid replay site as a pinned public snapshot
  source, not as a DOM or private-account integration. The current manifest
  revision is `ace13c7a675a20d4932b430508a750d7ad7867e9`; raw files remain
  under ignored external storage and retain their own SHA256 values.
- Keep BitMEX and Hyperliquid venue, symbol, contract and settlement fields
  separate. Only normalized rows that pass source verification, causal
  features and strict autonomous replay may enter the combined research
  dataset; raw files are never merged.
- Evaluate both `CONDITIONAL_BEHAVIOR` and `STRICT_AUTONOMOUS_REPLAY`. The
  strict track starts from zero simulated state, uses prior closed bars and
  next-bar execution, and never consumes teacher position/action/account
  fields. Same-time aliases are confidence-weighted into one net event.
- Add RSI14, MACD 12/26/9, Bollinger 20/2, volume percentile 72 and existing
  causal features as model inputs. These are model-input explanations only;
  they are not claims about the original trader's private indicators.
- The current strict autonomous candidate fails the promotion gates because
  costed results are not positive and do not beat the equal-weight hold
  control in all windows. Keep the current Demo model; do not auto-switch and
  do not add Demo orders. The public API refresh is credential-free and remains
  fail-closed when the local network cannot complete TLS.

## 2026-08-26 — Stabilize target-exposure regression; keep candidate blocked

- The existing NumPy target regression used an unregularized pseudoinverse. Near-collinear contract/indicator features produced coefficients up to approximately `1e11` and caused zero-start autonomous predictions to saturate at `-1/+1`.
- Add an opt-in ridge penalty (`target_l2`) while preserving `target_l2=0` for legacy artifact compatibility. Build the independent candidate `behavioral-distillation-v3.2-stable-target` with `λ=1.0` and record its artifact/model hash.
- The candidate artifact loads successfully and reduces strict-autonomous target MAE to approximately `0.19–0.20`, but costed WF1/WF2/WF3 net returns remain negative and the promotion gates fail. Keep the active Demo model unchanged; no new Demo orders are authorized.
- The next model-research task is bar-clock/temporal supervision and explicit no-trade frequency alignment. This is required before claiming the model has learned a deployable signal policy.

## 2026-08-26 — Add market-clock temporal supervision; keep candidates blocked

- Event-driven rows were expanded into a deterministic one-row-per-available-closed-1h-bar dataset across 66 venue/instrument behavior groups. The dataset contains `264609` rows, `264288` indicator-eligible rows, and an explicit `NO_TRADE` rate of `95.12%`.
- The batch indicator implementation was checked against the reference causal implementation for `1440` sampled fields with zero mismatches. The full temporal dataset audit has zero future-bar, future-funding, non-strict clock-order, and non-future-label violations.
- The ordinary temporal candidate avoids the event-frequency mismatch but collapses to `NO_TRADE=100%` in all strict autonomous windows. The explicit inverse-frequency balanced candidate avoids that collapse but overtrades and remains negative after fees/slippage; neither candidate is promoted.
- Keep the existing Demo model unchanged. These reports demonstrate why event similarity, indicator presence, or better relative performance is insufficient without calibrated action frequency and positive costed autonomous validation.

## 2026-08-26 — Enforce action-target consistency; keep calibrated candidate blocked

- Add an opt-in calibrated temporal candidate `behavioral-distillation-v3.4-calibrated-action-target` using square-root inverse-frequency weighting and an explicit invariant: `NO_TRADE`/`HOLD_*` cannot produce a different target exposure from the current simulated position.
- The candidate reduces unnecessary repositioning and is positive in WF1, but remains negative in WF2 and WF3 after costed autonomous replay; it fails the all-window positive/profit-factor/event-baseline gates.
- Keep the active Demo model unchanged. A model that is numerically stable or better than a weak event baseline is not sufficient for deployment without stable out-of-time autonomous behavior.

## 2026-08-26 — Train-only cost-calibrated threshold remains blocked

- Candidate `behavioral-distillation-v3.5-cost-calibrated-threshold` selects confidence thresholds only from the chronological tail of each training window (`WF1=0.18`, `WF2=0.16`, `WF3=0.00`); the test windows remain untouched during selection.
- Strict autonomous, costed normalized returns are `+0.018150`, `-0.135907`, and `-0.002102` for WF1/WF2/WF3. The candidate fails stable all-window positivity, profit-factor, and event-baseline gates.
- Keep the active Demo model unchanged. Threshold calibration is research evidence, not proof that the robot has learned the original trader's strategy or a deployable profitable signal.

## 2026-08-26 — Probability-calibrated stability candidate remains blocked

- Candidate `behavioral-distillation-v3.6-probability-calibrated` uses a nested chronological split: 60% fit, 20% probability calibration, 20% threshold selection, then an untouched walk-forward test. The calibrator only changed parameters when training-holdout NLL decreased.
- Causal checks pass and the full suite passes (`368` tests), but the candidate produced zero strict autonomous adjustments and zero net return in WF1/WF2/WF3. It is not a learned deployable policy.
- The global cross-venue coverage gate fails: Hyperliquid contributes `5796` rows from `2025-11-15` onward, but `0` model-eligible rows enter the global test windows because no earlier training position scale exists. A `1160`-row Hyperliquid native holdout is recorded as diagnostic-only.
- Keep the active Demo model unchanged and do not interpret the small positive native Hyperliquid diagnostic as proof of cross-venue generalization.

## 2026-08-26 — Two-stage action-timing candidate remains blocked

- Candidate `behavioral-distillation-v3.7-two-stage-action-target` separates the timing decision (`ACTION` versus idle) from action type and target exposure. The timing head is trained on every causal hourly row; the action head is trained only on non-idle rows.
- Train-only threshold selection yields predicted action rates near the observed training-tail rates, but strict autonomous test results are `0.000000`, `-0.048936`, and `0.000000` for WF1/WF2/WF3; WF2 profit factor is `0.933678`.
- Keep the active Demo model unchanged. The two-stage structure improves diagnosis of timing versus sizing, but does not establish that the original trader's strategy has been learned or that a deployable signal exists.

## 2026-08-26 — Repair event-target label contamination and re-audit timing

- Decision targets now prefer the isolated order-episode position (`local_position_after`) produced by `build_order_episodes`; the global position fallback remains only for legacy callers. This prevents interleaved orders from contaminating an order's action/target label.
- Successful PyArrow dataset writes now also refresh the CSV mirror used by downstream scripts, preventing stale derived inputs after a Parquet build.
- Hyperliquid next-event labels now skip same-timestamp fills and use the next strictly later event, while preserving same-time ties for explicit audit reporting.
- The temporal label audit is `PASS_WITH_WARNINGS`: `32552` event rows, `264609` temporal rows, `264288` eligible rows, zero hard failures, `373` same-timestamp event ties, and `70` same-hour net-zero labels that can hide offsetting source actions.
- The repaired data was re-run through v3.7 strict autonomous replay. The promotion result is unchanged: WF1/WF3 make zero adjustments, WF2 net return is approximately `-0.048939` with PF approximately `0.933658`; the active Demo model remains unchanged.
- These repairs establish causal/action-target consistency, not exact strategy recovery, full learning, or a profitability claim.

## 2026-08-26 — State-robust and autonomous-threshold candidates remain research-only

- Candidate `behavioral-distillation-v3.8-state-robust-action-target` added deterministic zero-start and half-teacher-state variants for non-idle training actions only. It reduced the teacher/autonomous state-distribution mismatch in training, but strict costed returns were `-3.514461`, `-0.103915`, and `+0.229969` in WF1/WF2/WF3; it is not promoted.
- Candidate `behavioral-distillation-v3.9-state-robust-autonomous-threshold` selected thresholds using autonomous zero-start state probabilities from a train-only chronological segment. Strict costed returns were `-0.262682`, `+0.001748`, and `+0.253175`, with WF1 PF `0.954884`; cross-venue coverage and all-window stability gates still fail. The active Demo model remains unchanged.
- The descriptive strategy profile reports `264288` eligible hourly rows, `95.13%` explicit `NO_TRADE`, `4.87%` non-idle actions, mean observed cycle duration about `49.9` hours, and mean same-instrument action interval about `20.2` hours. Current exposure is a stronger observed action conditioning variable than any single indicator; this is association, not proof of a private rule.
- The honest status remains `BEHAVIORAL_APPROXIMATION`: the data has been distilled into auditable candidates and behavior facts, but the robot has not fully learned the trader's strategy and no profitability or production claim is authorized.

## 2026-08-26 — Add causal action-sequence memory; keep candidate blocked

- Add `feature_action_lag_1`, `feature_action_lag_2`, and `feature_action_lag_3` to the shared feature contract. Temporal rows derive them only from events strictly before the decision timestamp; autonomous replay supplies the robot's own last three executed actions.
- Candidate `behavioral-distillation-v4.0-sequence-memory` was evaluated with the existing state-robust training protocol and untouched chronological test windows. Strict costed returns were `0.000000`, `-0.000028`, and `+0.004218` in WF1/WF2/WF3; it remains blocked.
- Sequence memory improves the causal representation and prevents the model from reading teacher action history during autonomous replay, but it does not establish stable strategy recovery. The active Demo model remains unchanged.
- Full test suite after the change: `380 passed`. No claim of exact learning or future profitability is permitted.

## 2026-08-26 — Venue-native calibration confirms platform divergence

- Candidate `behavioral-distillation-v4.1-venue-native-calibration` split BitMEX and Hyperliquid independently in chronological 80/20 windows and fitted each venue with train-only normalization and calibration.
- BitMEX used `206793` train rows and `42624` holdout rows. Strict autonomous net return was `-0.004768`, profit factor `0.971626`, and predicted action rate `57.43%`, indicating overtrading after costs.
- Hyperliquid used `4636` train rows and `1160` holdout rows. Strict autonomous replay made no effective adjustment, with `0.000000` net return and a `0.00%` action rate; its coverage is materially smaller and funding context is mostly missing.
- The same trader across venues does not imply one identical executable policy: contract scale, funding, liquidity, symbol coverage, and execution rules are venue-specific. Preserve a shared behavior layer plus venue-native scale/execution/calibration rather than silently treating platforms as interchangeable.
- Both results are `DIAGNOSTIC_ONLY`; the active Demo model remains unchanged. No exact-strategy, full-learning, or profitability claim is authorized.

## 2026-08-26 — Shared intent plus native layer remains blocked

- Candidate `behavioral-distillation-v4.2-shared-intent-native-layer` collapses direction-specific labels into venue-neutral `OPEN`, `ADD`, `REDUCE`, `FLIP`, and `NO_TRADE` intent families. Contract/unit categories, funding, and mark/index basis are excluded from the shared input; normalized state and common market features remain.
- The split is per venue and chronological: `60%` fit, `20%` calibration, and a final untouched `20%` test. Causal checks pass with zero violations. Native exposure calibration is fitted only on the middle slice and is bounded to prevent direction reversal or unbounded resizing.
- On the untouched test, BitMEX and Hyperliquid both predicted `100% NO_TRADE`; the native exposure slopes collapsed to `0.0`. The candidate therefore does not capture an executable shared intent and is not promoted.
- The result narrows the diagnosis: the remaining issue is autonomous action timing/state generalization and sparse-label identifiability, not simply venue contract-unit scaling. Active Demo remains unchanged.

## 2026-08-26 — Venue-neutral timing head remains blocked

- Candidate `behavioral-distillation-v4.3-shared-intent-timing` separates the binary action-timing head from action family and target size. It uses venue-neutral features, a causal zero-start state path, a 60% fit / 20% calibration / 20% untouched test split, and train-only probability calibration.
- On the untouched BitMEX holdout, selected threshold `0.05` produced only `2` predicted actions, timing F1 `0.000000`, and costed net return `-0.004365` (PF `0.964532`). On Hyperliquid, threshold `0.15` produced `0` actions and timing F1 `0.000000`.
- The separated timing head therefore does not recover executable action timing. Keep the active Demo model unchanged; no candidate promotion or new Demo orders are authorized.

## 2026-08-26 — Public-record identifiability ceiling is measurable

- Candidate `behavioral-distillation-v4.4-identifiability-ceiling` trains only on non-idle event rows and evaluates only on non-idle events in the final chronological slice. It intentionally gives the benchmark an oracle event trigger and historical dynamic state, so it is a conditional upper-bound diagnostic rather than a deployable policy.
- Conditional action-type Macro-F1 is `0.382047` on BitMEX and `0.585714` on Hyperliquid, with target exposure MAE `0.055041` and `0.047233` respectively. The corresponding strict autonomous timing F1 is `0.000000` on both venues.
- The large gap shows that the public record contains some information about how an observed action was sized/classified, but does not identify when the action should begin. This is a data/identifiability limit, not evidence that another indicator will recover the private trigger.
- Keep the active Demo model unchanged. No exact-strategy or full-learning claim is authorized.
