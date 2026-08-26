# Data Lineage

## Frozen teacher data

- Repository: `owenfff/BTC-Trading-Since-2020`
- Source commit recorded in `quant/SOURCE_VERSION.md`: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- Protected inputs: root order, execution, wallet history, position snapshot, wallet/margin snapshots, instrument, wallet-assets, equity curve, and manifest files.
- Protected-input SHA256 verification: PASS in M0-02B-1B-0.1.

## Derived lineage

- Position accounting code/report baseline: report commit `c3414514077ca81e9ddfacfd602704d9698a53dc`.
- Autonomous branch starts from that report commit: `quant/autonomous-behavioral-quant-bot-v1`.
- Raw execution counts: 173434 total, 173226 derivative, 160510 raw Trade, 160302 derivative Trade, 12905 Funding, 19 Settlement, 208 Spot Trade.
- Historical price audit: 5809 EXACT, 1425 RECOVERED, 0 UNRESOLVED among 7234 configured historical Trades.
- Large derived Parquet and event-level audit files are local ignored outputs and are never part of the source lineage commit.

## Accounting foundation artifact

- Code commit: `86be1f430ece5c64237b2dfc133842124119101c`
- Report commit: `f52ea4621b807a00f08dce805d7600a97f74a584`
- Manifest: `quant/reports/accounting_foundation_manifest.json`
- Status: `HIGH_CONFIDENCE_WITH_RESIDUALS` / `READY_WITH_KNOWN_ACCOUNTING_RESIDUALS`

## Wallet reconciliation artifact

- Code commit: `1166e23eff2da21afb5ec3447cccbebf77971295`.
- Report commit: `14335b3aaf312c3e7c42cec7632f7f32f05d0fd5`.
- Report: `quant/reports/wallet_reconciliation.json` and `quant/reports/wallet_reconciliation.md`.
- Coverage: 17,484 wallet rows; 17,482 Completed; currencies BMEX, USDT, XBT; 14,292 balance-continuity batches.
- Results: 17,474 PASS rows, 5 real batch anomalies, 3 exact nonzero snapshot matches, 12 zero snapshots without history, terminal XBT wallet/equity PASS.
- Raw/major values remain currency-separated and are scaled only from `api-v1-wallet-assets.csv`; wallet-to-execution comparisons are aggregate diagnostics only.

## Behavioral dataset artifact

- Code commit: `8866448fc183929078caf418b09de7307c16d02b`.
- Report commit: `a2360d58842028d4dfd33bb3bfd95ec42bfcc4d8`.
- Manifest: `quant/reports/behavior_dataset.json`; profile: `quant/reports/trader_behavior_profile.md`.
- Layer counts: 160,302 derivative fills; 62,388 execution batches; 31,702 order episodes; 32,231 decisions; 1,401 cycles.
- BTC-first counts: 98,874 XBTUSD fills; 20,316 order episodes; 20,845 decisions; 688 cycles; 529 synthetic daily observations.
- `quant/outputs/` contains ignored large outputs. The current runtime wrote schema-equivalent CSV fallbacks because the pinned Parquet engine was unavailable; the report records this without claiming Parquet materialization.
- Confidence schema is present on actions, orders, decisions, and cycles; wallet confidence is aggregate-only and strategy fidelity remains `BEHAVIORAL_APPROXIMATION`.

## Public market-data artifact

- Code commit: `827106a2e5d8c20afe23bb20f52954baccb0f6e5`.
- Report commit: `cb45b621d17cbc33e2d72874a9e69d653a669b2e`.
- Reports: `quant/reports/market_data_audit.md`, `quant/reports/market_data_lineage.json`, and `quant/reports/market_data_gaps.csv`.
- Canonical source policy: BitMEX public no-key `trade/bucketed` for XBTUSD 5m; 1h is derived locally without filling missing 5m bars; funding from `funding`; the current `instrument` snapshot is not used as historical mark/index context.
- Real repository execution bounds used for the request: `2020-05-01T09:03:47.360Z` through `2026-07-18T22:11:15.556Z`; 98,874 XBTUSD Trade rows.
- Current run status: `READY_WITH_WARNINGS`; 653,630 5m bars, 54,470 derived 1h bars, 6,809 funding rows, zero 5m grid gaps, and 653,630 explicit `MARK_INDEX_MISSING` context rows.
- Join policy is `ASOF_PREVIOUS_OR_EQUAL_UTC`; future observations are forbidden. Raw account inputs remained unchanged.
- The official BitMEX S3 public trade archive remains an explicit fallback, but was not blindly downloaded because each daily raw trade object is large and REST succeeded after bounded window retries. The REST cache has per-window SHA256 lineage under ignored `quant/data/market/raw/bitmex_api/`.

## Upcoming lineage

Wallet ledger, public market data, behavioral episodes, features, labels, models, and experiments must each record source URLs/commits, UTC coverage, SHA256, code commit, dependency versions, and report analysis commit.

## M13 cross-asset behavior artifact

- Code commits: `cf220e4` initial cross-asset pipeline; `07f5304e0101852538d52914927f11ef7e8d01ee` bounded public retries, train-only scale eligibility, dynamic walk-forward, and paper replay.
- Universe reports: `quant/reports/cross_asset_universe.csv`, `quant/reports/cross_asset_universe.json`, `quant/reports/cross_asset_universe.md`.
- Dataset reports: `quant/reports/cross_asset_model_dataset_manifest.json` and `quant/reports/cross_asset_leakage_audit.md`.
- Strategy reports: `quant/reports/cross_asset_strategy_fidelity.json`, `quant/reports/cross_asset_per_symbol_metrics.csv`, `quant/reports/cross_asset_walk_forward.csv`, and `quant/reports/cross_asset_sensitivity.csv`.
- Paper report: `quant/reports/cross_asset_paper_replay.json` and `quant/reports/cross_asset_paper_replay.md`.
- Source policy: public no-key BitMEX hourly trade buckets and funding; detailed raw response caches and full cross-asset datasets remain under ignored `quant/outputs/`.
- Coverage result: 66 symbols inventoried; 65 market `PASS`, 1 `INSUFFICIENT`; 10,630 model-eligible rows across 53 symbols after train-only position-scale and derivative filters.
- Analysis commit in the generated model and paper reports: `07f5304e0101852538d52914927f11ef7e8d01ee`.

## Multi-venue non-production runtime artifact

- Code commits: `c58460f` (`Add unified OKX Demo and Binance Testnet runtime`), `d150aab` (`Add OKX and Binance private stream health`), `26bf900` (`Add local DPAPI launchers for OKX and Binance`), `54845f8` (`Show multi-venue runtime telemetry in dashboard`), `0e2d33f` (`Test unified runtime lifecycle and restart safety`), and `370cc7c` (`Make private stream readiness explicit`).
- Report: `quant/reports/multivenue_runtime.md`.
- Added artifacts: hard-pinned OKX Demo and Binance Spot Testnet transports,
  authenticated private WebSocket clients, normalized adapters, explicit
  cross-venue mapping report generation, Spot balance-aware planning, and a
  unified REST-reconciliation/runtime boundary, and local Windows-user DPAPI
  launchers that do not expose credentials to Git or the dashboard. The
  dashboard now aggregates sanitized state for all three non-production
  venues.
- Strategy summary: `quant/reports/strategy_rules.md`; the deterministic
  rules baseline and deployed logistic model are explicitly separated.
- Verification: full suite `311 passed`; new adapter/runtime targeted suite
  `15 passed`; lifecycle/restart suite `3 passed`; no exchange credentials
  used; raw root CSV/JSON inputs unchanged.
- Runtime outputs are ignored under `quant/outputs/`; only code, tests and the
  small report are tracked.

## Leakage-safe feature and label artifact

- Code/analysis commit: `83d636a2e5d8c20afe23bb20f52954baccb0f6e5`.
- Manifest: `quant/reports/model_dataset_manifest.json`.
- Reports: `quant/reports/feature_dictionary.md`, `quant/reports/label_dictionary.md`, `quant/reports/leakage_audit.md`, `quant/reports/label_distribution.csv`, `quant/reports/no_trade_sampling_audit.md`, and `quant/reports/dataset_time_split.csv`.
- BTC-first scope: 20,845 XBTUSD decision rows, including 529 explicit synthetic daily HOLD/NO_TRADE observations; 58 feature/label columns in the local CSV fallback.
- Split: chronological 70% TRAIN / 15% VALIDATION / 15% TEST; no random shuffle and no test-period fit statistics.
- Leakage status: `PASS`; future bar, funding, history, label, and invalid-time violation counts are all zero. Labels use the next strictly later decision and skip same-timestamp ties.
- Market warning: all 20,845 rows carry explicit `MARK_INDEX_MISSING` because no historical mark/index series was accepted from the current public instrument snapshot.
- Large dataset path: `quant/outputs/model_dataset.parquet` requested, with ignored `quant/outputs/model_dataset.csv` fallback due unavailable Parquet dependencies. Raw account inputs remained unchanged.

## M5.1 strategy distillation artifact

- Strategy code/analysis commit: `2daab36eb75c6e1cc876b12ff4e369ea57e8ae5`.
- Report commit: `30c0d19f4b283ce9dd5c3de52db0036b4094fb81`.
- Reports: `quant/reports/strategy_fidelity.md`, `quant/reports/strategy_fidelity.json`, `quant/reports/strategy_action_confusion.csv`, `quant/reports/strategy_position_tracking.csv`, and `quant/reports/strategy_regime_fidelity.csv`.
- Models: a TRAIN-only historical frequency baseline and deterministic interpretable rules. Both use only the M4 feature contract; observed target/action and all `label_*` columns are excluded from Strategy Core inputs.
- Strategy output contract includes version, timestamps, target exposure, action, confidence, validity, slippage field, execution preference, and risk tags. The strategy layer has no exchange SDK dependency.
- Fidelity label is fixed as `BEHAVIORAL_APPROXIMATION`; no profitability or exact intent claim is made.
- M5.2 comparison commit: `66c9e34e8189d1fffbd8caf913a876c08df95f31`; report commit: `39077bddcff28cf4d6fa2c2c46b95ee2abe13a84`.
- M5.2 models: deterministic NumPy Logistic Regression and a depth-limited NumPy Decision Tree, each fit only on TRAIN labels. External sklearn/LightGBM/XGBoost packages were not available and were not installed.

## Strategy/backtest parity boundary

- Phase 7 must call the same `quant_bot.strategy` Strategy Core for offline replay and streaming-style signal generation.
- Backtest execution must model historical fees, funding, configurable slippage and signal delay, next-bar execution, target exposure, position limits, partial fills, minimum lot, tick size, and separate settlement currencies without using same-bar close prices as ideal fills.

## M6 walk-forward research artifact

- Code/analysis commit: `b43e428c752383436485813fd5a0c8ae3a02b920`.
- Report commit: `51d21d646c9f65a15f5cc6b34fe6fe63564a7c63`.
- Reports: `quant/reports/quant_research_summary.md`, `quant/reports/quant_research_summary.json`, `quant/reports/walk_forward_results.csv`, `quant/reports/robustness_results.csv`, `quant/reports/failure_analysis.md`, and `quant/reports/reproducibility.md`.
- Parity: 256 fixed-input signals per model across four Strategy Core implementations matched exactly between batch and streaming-style calls.
- Walk-forward: 2020–2022 train / 2023 validation / 2024 test; 2020–2023 train / 2024 validation / 2025 test; 2020–2024 train / 2025 validation / 2026 test.
- Research status: `RESEARCH_ONLY`. No stable out-of-sample profitability claim is made; all controls and unfavorable results are retained.
- Cost boundary: blended historical XBTUSD fee ratio from 98,874 BTC-first action rows; Funding charged only at unique `funding_source_timestamp_utc` events; slippage/tick and normalized exposure assumptions remain explicit.

## Exchange-neutral engineering artifacts

- Phase 8 domain model and paper-safety code: `86634c0...`; Decimal/UTC domain objects, allocator, pre-trade risk, execution planner, event store, health checks, and safety defaults.
- Phase 9 execution and risk controls: `0438315...`; idempotency, retry/query policy, order state machine, fill tracking, reconciliation, clock/stale-data/exchange/drawdown guards, circuit breaker, and kill switch.
- Phase 10 offline runtime: code `0594629...`, reports `dc7b87e...`; shadow and paper smoke paths pass without credentials or network access.
- Phase 11 exchange capability matrix: `61aa22f...`; injected-transport BitMEX/Bybit adapter tests are recorded in code commit `f2c64da...`. Real private endpoints remain credential-gated.
- Phase 12 release safeguards: code commit `9c8cf24...` includes the release audit and the pinned runtime-only dependency split; the fresh clean-room clone passed 273 tests with 2 output-dependent skips, compile validation, controlled research preflight, and the intentional full-research rehydration boundary. Docker Compose parsed successfully; `btc-trading-clean-room:9c8cf24` built and returned `PAPER_SMOKE_PASS` under a read-only filesystem with temporary `/tmp`.

## Unified multi-venue supervisor artifact

- Code commit: `dcfc1033dde8f5361818e4620ec98dee9bba4540`.
- Added `quant_bot/multivenue_runtime.py`, the `run-all` CLI command, and
  `deploy/start-multivenue.ps1` for local OKX Demo plus Binance Spot Testnet
  supervision.
- The supervisor preserves independent venue adapters, mappings, runtime state,
  private-stream health and sanitized BLOCKED results. It does not merge
  historical teacher symbols or account semantics.
- Verification: full `pytest quant/tests -q` returned `314 passed` with zero
  warnings; adapter/runtime targeted tests returned `16 passed`; supervisor
  tests returned `4 passed`; all PowerShell launchers parsed; no credentials
  were used; raw root CSV/JSON inputs were unchanged.
- The code commit and report commits are present on
  `origin/quant/autonomous-behavioral-quant-bot-v1`; remote parity was
  confirmed with `git ls-remote`.

## Binance Futures single-venue artifact

- Code commit: `79af72cf41c16cb32f8c19c1f2b1894e65da6733`.
- Added a native Binance USDⓈ-M Futures Testnet adapter restricted to
  `https://demo-fapi.binance.com` and
  `wss://demo-fstream.binance.com/ws`.
- The adapter maps USDT-margined perpetual instruments, account margin,
  signed positions, open orders, user trades, closed 1h bars, book quotes,
  `GTX` PostOnly orders, `reduceOnly` orders and REST listenKey private WS
  health. Binance Spot remains a separate cash-market approximation.
- Normal operation selects one venue. The existing multi-venue supervisor is
  opt-in and is not used by the default stack.
- Offline verification: full suite `319 passed`; no credentials, private
  endpoint or order was used. Credential-free Futures preflight and run both
  fail closed with `TESTNET_CREDENTIALS_REQUIRED`; root raw CSV/JSON inputs
  remain unchanged.
- Dashboard follow-up code commit: `cdbdc62d2e47003d2455a3e993ccbb099fc52c28`;
  the sanitized read-only status API now includes Futures state as a separate
  venue without exposing credentials or authenticated payloads.
  confirmed with `git ls-remote`.

## One-command local stack artifact

- Code commit: `ad7b8ec4f9ba603a7e08a8b6736244e3f56b1849`.
- Added `deploy/start-quant-stack.ps1` to start the sanitized frontend-only
  dashboard and delegate OKX/Binance supervision to the unified launcher.
- The four PowerShell launchers parsed successfully; dashboard logs are
  ignored under `quant/outputs/`; no credential or raw account payload is
  served by the dashboard process.
- The four PowerShell launchers parsed successfully; dashboard logs are
  ignored under `quant/outputs/`; no credential or raw account payload is
  served by the dashboard process.

## Explicit single-venue selection

- Code commit: `2e0e82b794f4412256b330dc4e4c4a04f4b27f0c`.
- `start-quant-stack.ps1` now defaults to `okx-demo`; Binance is selected with
  `-Venue binance-spot-testnet`, and simultaneous supervision requires the
  explicit `-Venue both` opt-in.
- `start-quant-stack.ps1` now defaults to `okx-demo`; Binance is selected with
  `-Venue binance-spot-testnet`, and simultaneous supervision requires the
  explicit `-Venue both` opt-in.
- Credential-free individual runs returned venue-specific structured BLOCKED
  results with zero submissions; adapter/runtime tests returned `16 passed`.

## 2026-08-25 — Loopback control artifact

- Code commit `75e0bf8` adds `frontend/server.py` loopback-only start/stop
  controls and the local Windows/Linux launchers.
- The control API accepts only venue, mode, and explicit Testnet confirmation;
  it rejects credential-shaped fields and exposes only sanitized process state.
- The panel can run on a Shanghai trading node through an SSH tunnel. It does
  not change the exchange-neutral model, raw-input lineage, or single-venue
  default, and it does not claim a completed external order lifecycle.

## M15 Hyperliquid public replay and cross-venue indicator artifact

- Implementation/report commit: `54ead1ab466acca9d2e4388e954bf4c0cf8ed2ed`.

- Website: `https://paul.catseye.today/`; public source repository:
  `pystashell/track_paul_btc_hyperliquid_trade`.
- Pinned source revision: `ace13c7a675a20d4932b430508a750d7ad7867e9`;
  target wallet: `0xdae4df7207feb3b350e4284c8efe5f7dac37f637`.
- Source manifest checks: 7/7 files PASS. Candle archive: 7,894 1h bars,
  SHA256 `4cc68091ad1f8c687db7c7a59290073dfe43928566a280dd9813659765f52a3d`.
  Normalized snapshot: 321 Hyperliquid BTC-perpetual fill rows, 320 eligible
  rows at the frozen cutoff, 2,084 funding records.
- Combined datasets: 32,552 rows and 31,631 eligible rows in both v2/v3
  contracts; source counts are 32,231 BitMEX and 321 Hyperliquid rows.
- Reports: `quant/reports/hyperliquid_public_source_audit.md`,
  `quant/reports/cross_venue_indicator_autonomous_audit.md`,
  `quant/reports/cross_venue_indicator_by_window.csv`,
  `quant/reports/cross_venue_indicator_by_symbol.csv`, and
  `quant/reports/cross_venue_indicator_cost_sensitivity.csv`.
- Replay artifact: ignored
  `quant/outputs/replay_dashboard_hyperliquid_btc.json`; it contains public
  1h bars, fill-derived order lifecycle points, observed closed PnL and causal
  indicator snapshots for the local panel.
- Strict autonomous result: WF1/WF2/WF3 data is available and leakage/hash
  gates pass, but the candidate remains `DEMO_CONTINUE_LIVE_BLOCKED` because
  costed autonomous performance fails the positive/profit-factor/hold-control
  promotion gates. No model switch, private API call, or order was performed.

## M15.1 v3.2 stable-target candidate

- Code commit: `14f11b14e77190457f2af5ccb96806d15037fce1`.
- Candidate model: `behavioral-distillation-v3.2-stable-target`; feature contract: `m13-v3.1-operational-parity`; artifact: `quant/outputs/cross_asset_deployment_model_v32.json`.
- Target regression uses opt-in ridge `λ=1.0`; legacy models retain `λ=0` when loaded from existing artifacts. Candidate model SHA256: `7d8a12e97cb90f1e71f3d94087cfc5069c0a4c90a3fa928fcf989c62e06f8d07`.
- Validation report: `quant/reports/cross_asset_v32_stable_target_audit.md` and `.json`. Candidate coefficients are bounded (`max abs ≈ 0.2754`) and artifact loading passes, but strict autonomous costed returns remain negative in all three windows; candidate was not promoted.
- No raw account CSV/JSON was changed. No private API, credential, mainnet endpoint, or order was used.

## M15.3 temporal market-clock supervision

- Code commit: `9240672` (`Add market-clock temporal replay candidate`).
- Input dataset: `quant/outputs/cross_venue_model_dataset_v3.csv`, SHA256 `e131e08e45883664242f9443b2d4847341792a5df020aa31cb65eea05ade02e9`.
- Market context: `quant/outputs/cross_asset_market_context.csv`, SHA256 `976cb1bb83d72012f3753585bbc3f969587ced3127d5430f02d6ff7c27ddb807`.
- Derived ignored output: `quant/outputs/cross_venue_temporal_dataset_v3.csv`; manifest: `quant/reports/cross_venue_temporal_dataset_v3_manifest.json`. It contains `264609` deterministic hourly rows across `66` venue/instrument groups, `264288` eligible rows, and `95.12%` explicit `NO_TRADE` labels.
- Causal temporal audit: `quant/reports/cross_venue_temporal_autonomous_audit.md` and `.json`; ordinary temporal candidate is blocked because strict autonomous costed net returns are negative and it predicts no trade in all windows.
- Balanced candidate audit: `quant/reports/cross_venue_temporal_balanced_autonomous_audit.md` and `.json`; it is blocked because it overtrades, remains negative after costs, and fails the event-baseline comparison gate.
- Batch indicator equivalence: `1440` sampled reference fields compared with zero mismatches; full suite `365 passed`.
- No raw account CSV/JSON was modified. No private API, credential, mainnet endpoint, or order was used. The active Demo model remains unchanged.

## M15.4 calibrated action-target candidate

- Code commit: `5968c343cb9c7a32fff4174d9e7c1a21903b7437`.
- Candidate version: `behavioral-distillation-v3.4-calibrated-action-target`; it uses `sqrt_balanced` class weighting and enforces that `NO_TRADE`/`HOLD_*` target exposure equals the current simulated exposure.
- Report: `quant/reports/cross_venue_temporal_calibrated_autonomous_audit.md` and `.json`. Causal checks remain zero; strict costed returns are `+0.018150`, `-0.135907`, and `-0.002102` across WF1/WF2/WF3, so the candidate is not promoted.
- Full suite after the change: `366 passed`. No raw CSV/JSON, credential, private endpoint, mainnet endpoint, or order was used. Active Demo model remains unchanged.

## M15.5 cost-calibrated threshold candidate

- Code commit: `6c0e0396c65db0e662fe5f3bae65180c3b2475f1`.
- Candidate version: `behavioral-distillation-v3.5-cost-calibrated-threshold`; the action-target consistency invariant remains enabled.
- Report: `quant/reports/cross_venue_temporal_threshold_calibrated_autonomous_audit.md` and `.json`.
- Thresholds were selected from train-only chronological tails: `WF1=0.18`, `WF2=0.16`, `WF3=0.00`. Strict autonomous costed returns were `+0.018150`, `-0.135907`, and `-0.002102`; the candidate remains blocked.
- Causal checks pass and all `366` tests pass. No raw CSV/JSON was modified; no credential, private endpoint, mainnet endpoint, or order was used. Active Demo model remains unchanged.

## M15.6 probability-calibrated cross-venue stability candidate

- Code commit: `7773c76` (`Add probability calibration and venue stability audit`).
- Candidate version: `behavioral-distillation-v3.6-probability-calibrated`; model calibration uses a bounded temperature-plus-class-bias layer fitted only on a chronological training holdout and supports artifact round-trip serialization.
- Report: `quant/reports/cross_venue_probability_calibrated_stability_audit.md` and `.json`; per-symbol detail: `quant/reports/cross_venue_probability_calibrated_by_symbol.csv`.
- Global report: `264288` rows, causal checks pass, calibration NLL does not worsen, and the full suite passes with `368` tests. The candidate makes zero strict autonomous adjustments in WF1/WF2/WF3 and is not promoted.
- Venue coverage: BitMEX has model-eligible global test rows; Hyperliquid has `5796` rows from `2025-11-15` to `2026-07-15` but `0` model-eligible global test rows due to missing pre-2025 training position scale. Its `1160`-row within-venue holdout is diagnostic-only (`net ≈ 0.002951`, `PF ≈ 1.011`) and not a cross-venue promotion result.
- No raw CSV/JSON was modified; no credential, private endpoint, mainnet endpoint, or order was used. Active Demo model remains unchanged.

## M15.7 two-stage action-timing and target-size candidate

- Code commit: `852175f` (`Add two-stage action timing model`).
- Candidate version: `behavioral-distillation-v3.7-two-stage-action-target`; timing and action/target heads use deterministic NumPy models under the shared Strategy Core contract.
- Report: `quant/reports/cross_venue_two_stage_autonomous_audit.md` and `.json`; per-symbol detail: `quant/reports/cross_venue_two_stage_by_symbol.csv`.
- The timing head is trained on idle and non-idle rows; the action head is trained only on non-idle rows. Train-only timing thresholds are `WF1=0.57`, `WF2=0.19`, `WF3=0.26`.
- Strict autonomous costed returns are `0.000000`, `-0.048936`, and `0.000000` for WF1/WF2/WF3; the candidate is blocked. Full suite after the change: `369 passed`.
- Global model-eligible test coverage remains BitMEX-only (`HYPERLIQUID=0` in WF1/WF2/WF3). No raw CSV/JSON was modified; no credential, private endpoint, mainnet endpoint, or order was used. Active Demo model remains unchanged.

## M15.8 label/timing audit and repair

- Code paths: `quant/src/behavior/decision_episodes.py` now uses isolated order-episode position targets; `quant/src/cross_asset/hyperliquid.py` skips same-timestamp fills when selecting the next label; `quant/scripts/build_behavior_dataset.py` refreshes the CSV mirror after successful Parquet output; `quant/scripts/audit_cross_venue_temporal_labels.py` audits event and temporal labels.
- Audit outputs: `quant/reports/cross_venue_temporal_label_audit.md`, `.json`, and `cross_venue_temporal_label_audit_by_symbol.csv`.
- Final audit: `PASS_WITH_WARNINGS`; `32552` event rows across `66` state keys; `264609` temporal rows with `264288` eligible rows; zero hard failures; `373` same-timestamp event ties and `70` same-hour net-zero labels retained as explicit warnings.
- Rebuilt source-derived inputs: behavior dataset counts remain `173434` raw executions, `160302` derivative fills, `62388` execution batches, `31702` order episodes, `32231` decision episodes, and `1401` trade cycles. The cross-venue temporal dataset remains `264609` rows.
- The repaired inputs were re-audited by `cross_venue_two_stage_autonomous_audit.py`; v3.7 remains `DEMO_CONTINUE_LIVE_BLOCKED` and the active Demo model is unchanged. Raw account CSV/JSON hashes remain unchanged; generated large outputs remain ignored and were rebuilt locally; no credentials or private endpoints were used.

## M15.9 state-robust threshold audit and behavior profile

- Code commit: `8a8b521` (`Add state-robust audit and strategy behavior profile`).
- Independent candidates: `behavioral-distillation-v3.8-state-robust-action-target` and `behavioral-distillation-v3.9-state-robust-autonomous-threshold`; both use deterministic NumPy models, train-only chronological fitting, zero-start autonomous replay, and no active Demo artifact replacement.
- Reports: `quant/reports/cross_venue_state_robust_autonomous_audit.*`, `cross_venue_state_robust_by_symbol.csv`, `cross_venue_state_robust_autonomous_threshold_audit.*`, and `cross_venue_state_robust_autonomous_threshold_by_symbol.csv`.
- v3.8 strict costed returns: `-3.514461`, `-0.103915`, `+0.229969` for WF1/WF2/WF3. v3.9 strict costed returns: `-0.262682`, `+0.001748`, `+0.253175`; both candidates remain blocked by stability and/or cross-venue gates.
- Behavior profile outputs: `strategy_behavior_profile_v4.md`, `.json`, and `strategy_behavior_profile_v4_by_symbol.csv`; input `quant/outputs/cross_venue_temporal_dataset_v3.csv`, `264609` rows, `264288` eligible. It is post-hoc descriptive and not a model artifact.
- Full suite after this package: `378 passed`. Raw account CSV/JSON remained unchanged; ignored derived outputs were read/rebuilt locally; no credentials, private endpoints, mainnet connection, or order was used.

## M15.10 causal action-sequence memory

- Code commit: `8699326` (`Add causal action sequence memory features`).
- Feature contract additions: `feature_action_lag_1/2/3`; `build_cross_venue_temporal_dataset.py` derives them from prior source events only, and `research/autonomous_replay.py` replaces them with the autonomous state's last three executed actions.
- Candidate: `behavioral-distillation-v4.0-sequence-memory`; report: `quant/reports/cross_venue_sequence_memory_autonomous_audit.md` and `.json`; per-symbol detail: `cross_venue_sequence_memory_by_symbol.csv`.
- Strict autonomous costed returns: `0.000000`, `-0.000028`, `+0.004218` for WF1/WF2/WF3; candidate remains `DEMO_CONTINUE_LIVE_BLOCKED` and active Demo is unchanged.
- The temporal dataset remains `264609` rows / `264288` eligible after rebuild; temporal label audit remains `PASS_WITH_WARNINGS` with no hard failures. Full suite: `380 passed`. Raw account CSV/JSON was not modified; no credentials, private endpoints, mainnet connection, or order was used.

## M15.11 venue-native behavior diagnostics

- Code: `quant/scripts/audit_venue_native_behavior.py`; tests: `quant/tests/test_venue_native_behavior.py`.
- Candidate: `behavioral-distillation-v4.1-venue-native-calibration`. Reports: `quant/reports/venue_native_behavior_audit.md`, `.json`, and `venue_native_behavior_by_symbol.csv`.
- Source: `quant/outputs/cross_venue_temporal_dataset_v3.csv`, `264609` rows / `264288` model-eligible rows. Each venue was split chronologically with an 80/20 train/holdout boundary and train-only normalization/calibration.
- BitMEX: `206793` train / `42624` holdout; strict autonomous net return `-0.004768`, PF `0.971626`, action rate `57.43%`.
- Hyperliquid: `4636` train / `1160` holdout; strict autonomous net return `0.000000`, no effective adjustments, action rate `0.00%`.
- Status: diagnostic evidence only; no model promotion, Demo change, order, credential, private endpoint, or mainnet connection. Raw account CSV/JSON remained unchanged.

## M15.12 shared intent / venue-native execution layer

- Code commit: `e57b643` (`Add shared intent native layer audit`); tests: `quant/tests/test_shared_intent_native_layer.py`.
- Candidate: `behavioral-distillation-v4.2-shared-intent-native-layer`. Reports: `quant/reports/shared_intent_native_layer_audit.md`, `.json`, and `shared_intent_native_layer_by_symbol.csv`.
- Source: `quant/outputs/cross_venue_temporal_dataset_v3.csv`, `264288` model-eligible rows. Per venue: chronological `60%` train / `20%` calibration / `20%` untouched test; shared fit rows `158572`.
- Causal audit: `PASS` with zero future-bar, future-funding, non-strict-clock, and non-future-label violations.
- BitMEX: `41996` untouched test rows, predicted action rate `0.00%`, layered net return `0.000000`, action Macro-F1 `0.192789`, target MAE `0.112609`.
- Hyperliquid: `1160` untouched test rows, predicted action rate `0.00%`, layered net return `0.000000`, action Macro-F1 `0.329702`, target MAE `0.502278`.
- Native exposure slope was `0.0` for both venues. Status is diagnostic-only; active Demo remains unchanged, raw CSV/JSON remained unchanged, and no credential/private endpoint/order was used.

## M15.13 shared intent timing head

- Code commits: `c7c284a` (timing audit) and `c2d7eef` (timing tests). Full suite after this package: `389 passed`.
- Candidate: `behavioral-distillation-v4.3-shared-intent-timing`. Reports: `quant/reports/shared_intent_timing_audit.md`, `.json`, and `shared_intent_timing_by_symbol.csv`.
- Source: `quant/outputs/cross_venue_temporal_dataset_v3.csv`; per venue the model used chronological `60%` training, `20%` calibration, and a final untouched `20%` test. Shared training rows: `158572`; global probability calibration rows: `45873`.
- Causal audit: `PASS` with zero invalid decision times, future bars, future funding, non-strict clock ordering, and non-future labels.
- BitMEX: test `41996` rows, threshold `0.05`, `2` predicted actions, timing F1 `0.000000`, net return `-0.004365`, PF `0.964532`.
- Hyperliquid: test `1160` rows, threshold `0.15`, `0` predicted actions, timing F1 `0.000000`, net return `0.000000`.
- Status: diagnostic-only; active Demo remains unchanged, raw CSV/JSON remained unchanged, and no credential, private endpoint, mainnet connection, or order was used.
