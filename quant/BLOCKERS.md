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
- Docker Compose configuration and cold-start validation passed. The image uses pinned `quant/runtime-requirements.txt` and returned `PAPER_SMOKE_PASS` under a read-only filesystem with a temporary `/tmp`; no network or exchange call was made.

## M13 cross-asset behavior boundary

- Full behavior inventory: 66 symbols and 32,231 decisions. Public hourly market coverage: 65 `PASS`, 1 `INSUFFICIENT` (`XBTUSD` first-edge coverage).
- Unified model eligibility: 10,630 rows across 53 symbols. Twelve symbols without a chronological TRAIN position scale are excluded rather than scaled from future observations; excluded symbols remain in the inventory and coverage reports.
- Leakage audit: `PASS`; future bar, funding, history, label, and invalid-time checks are all zero.
- Cross-asset fidelity, walk-forward, sensitivity, and paper replay are descriptive `RESEARCH_ONLY` artifacts. They do not establish profitability or exact strategy recovery.
- Public endpoint timeout recovery is bounded and fail-closed. A missing public window produces an explicit coverage failure and never triggers synthetic market data.
- Real private exchange endpoints remain `DEMO_CREDENTIALS_REQUIRED`; no credentials are requested in this phase.

## Multi-venue runtime boundary

- OKX Demo and Binance Spot Testnet preflight still require the user's local
  credentials; no keys were requested or used by autonomous tests.
- Binance USDⓈ-M Futures Testnet is now implemented as a separate single-venue
  path, but its private preflight and order lifecycle remain unverified until
  local credentials are available.
- The unified OKX/Binance runner now has authenticated private WebSocket
  clients, but long-duration reconnect/soak tests and a real Demo/Testnet
  lifecycle remain open.
- Binance Spot is a cash-market behavioral approximation, not a derivative
  position replica; it cannot short and must be explicitly enabled.
- A real account, mainnet endpoint, and live funds remain outside the allowed
  autonomous boundary.

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

## 2026-08-25 — Shanghai node deployment boundary

- The loopback control panel is implemented and tested, but it is intentionally
  not a public credential form. A real Shanghai deployment still requires the
  user to provision Demo/Testnet credentials locally on that server and run
  the first preflight/lifecycle there; credentials must not be sent in chat or
  copied to the US frontend host.
- No real exchange credential, private endpoint, or order lifecycle was used
  during autonomous verification. Until that external local step is complete,
  the bot remains non-production code with a fail-closed credential boundary.

## 2026-08-26 — v3.2 stable-target candidate remains blocked

- The active v3/v3.1 target regression was numerically unstable: near-collinear standardized features yielded very large target coefficients and invalid zero-start extrapolation.
- Candidate `behavioral-distillation-v3.2-stable-target` fixes coefficient stability, but strict autonomous, costed WF1/WF2/WF3 results are still negative (`-0.1778`, `-0.0367`, `-0.0488` normalized return). Profit factor is below `1` in all three windows.
- This is a model-quality blocker, not a credentials or network blocker. The candidate remains non-active and Demo order generation remains unchanged.

## 2026-08-26 — Temporal supervision candidates remain blocked

- The market-clock dataset is causally valid (`264609` rows, `66` groups, `95.12%` explicit `NO_TRADE`, zero future-observation violations), but the unweighted candidate predicts `NO_TRADE` for `100%` of all three strict autonomous test windows.
- The inverse-frequency balanced candidate produces nonzero actions but overtrades: strict costed normalized returns are `-3.233831`, `-0.195200`, and `-0.253852` for WF1/WF2/WF3, and it does not beat the event baseline in every window.
- This is a model calibration and action-frequency blocker, not a credentials or exchange connectivity blocker. Keep the active Demo model unchanged and do not add Demo orders.

## 2026-08-26 — Calibrated action-target candidate remains blocked

- Candidate `behavioral-distillation-v3.4-calibrated-action-target` enforces action-target consistency and avoids the ordinary candidate's hidden repositioning, but costed strict autonomous returns are `+0.018150`, `-0.135907`, and `-0.002102` for WF1/WF2/WF3.
- The candidate therefore fails stable all-window positivity, profit-factor, and event-baseline gates. The remaining blocker is model calibration/generalization, not exchange access or credentials; no Demo model switch or new Demo order is authorized.

## 2026-08-26 — Cost-calibrated threshold candidate remains blocked

- Candidate `behavioral-distillation-v3.5-cost-calibrated-threshold` uses train-only chronological threshold selection (`0.18`, `0.16`, `0.00` for WF1/WF2/WF3) and preserves causal replay.
- Strict autonomous costed returns remain `+0.018150`, `-0.135907`, and `-0.002102`; WF2 and WF3 are negative, and the candidate does not pass all-window positivity, profit-factor, or event-baseline gates.
- This is a model calibration/generalization blocker, not a credential or exchange-access blocker. Do not promote the candidate, switch the active Demo model, or add Demo orders.

## 2026-08-26 — Probability-calibrated cross-venue candidate remains blocked

- Candidate `behavioral-distillation-v3.6-probability-calibrated` passes causal checks, calibration-holdout improvement, coefficient bounds, and `368` tests, but strict autonomous replay makes zero adjustments in WF1/WF2/WF3 and has zero net return.
- Hyperliquid coverage is not globally validated: its `5796` rows start at `2025-11-15`, while the global walk-forward normalizer has no pre-2025 training scale for `HYPERLIQUID:BTC-PERP`; therefore all `4686` raw WF3 rows are excluded from model-eligible testing. The `1160`-row native holdout is explicitly diagnostic-only.
- This is a data-coverage and model-generalization blocker. Do not promote v3.6, switch the active Demo model, or add Demo orders.

## 2026-08-26 — Two-stage action/target candidate remains blocked

- Candidate `behavioral-distillation-v3.7-two-stage-action-target` improves model decomposition but does not pass strict autonomous costed replay: WF1/WF2/WF3 net returns are `0.000000`, `-0.048936`, and `0.000000`, with WF2 PF `0.933678`.
- WF1 and WF3 predicted no-trade rates are `100%`; the candidate still cannot produce a stable autonomous action policy across time. Hyperliquid remains excluded from the global test because its model-eligible global test coverage is zero.
- This is a model-quality, label-timing, and cross-venue-coverage blocker. Do not promote v3.7, switch the active Demo model, or add Demo orders.

## 2026-08-26 — Corrected labels do not clear promotion blocker

- Event action/target consistency and temporal causal ordering now pass after repairing isolated order-episode targets and same-timestamp Hyperliquid next-label handling; the temporal audit has warnings only (`373` same-time ties and `70` net-zero hourly labels hiding offsetting source actions).
- The v3.7 strict autonomous re-audit remains blocked: WF1/WF3 make no adjustments, while WF2 remains negative after costs (`-0.048939`, PF `0.933658`).
- Keep the active Demo model unchanged; do not switch the Demo deployment or add new Demo orders.
- Remaining research options are a short action-sequence/memory protocol or verified pre-2025 Hyperliquid behavior/scale coverage. Hourly offsetting actions should become an explicit sequence target if they are needed for fidelity, rather than being silently relabeled.

## 2026-08-26 — State-robust candidates remain blocked

- The v3.8 state-augmentation candidate reduces zero-start state mismatch but overtrades and remains negative in WF1/WF2 after costs (`-3.514461`, `-0.103915`). It is not a deployable policy.
- The v3.9 autonomous-threshold correction prevents teacher-state threshold selection from masking all autonomous actions, but results remain unstable (`-0.262682`, `+0.001748`, `+0.253175` across WF1/WF2/WF3); WF1 PF is below one and Hyperliquid has zero global model-eligible test rows.
- The strategy profile is descriptive only. It confirms a sparse, stateful adjustment process, but it cannot identify a unique original strategy from trade records alone. Keep the current Demo model unchanged and do not add Demo orders.

## 2026-08-26 — Sequence-memory candidate remains blocked

- The v4.0 candidate adds causal last-three-action memory and uses autonomous executed history at replay time, but strict costed returns are `0.000000`, `-0.000028`, and `+0.004218` for WF1/WF2/WF3; WF1 makes no adjustments and the global Hyperliquid coverage gate still fails.
- This is a model-identifiability/generalization blocker, not a missing indicator or exchange-connection problem. Keep the active Demo model unchanged; do not promote v4.0 or add Demo orders.

## 2026-08-26 — Venue-native diagnostics do not clear blocker

- The independent BitMEX holdout is negative after costs (`-0.004768`, PF `0.971626`) and predicts actions on `57.43%` of rows, which is materially overactive for this replay.
- The independent Hyperliquid holdout produces no autonomous adjustments (`0.00%` action rate) and has only `1160` test rows, with incomplete funding context. It is not evidence of a deployable policy.
- The remaining blocker is executable-policy calibration and cross-venue generalization, not a missing indicator or exchange-connection problem. Keep the active Demo model unchanged; do not promote v4.1 or add Demo orders.

## 2026-08-26 — Shared intent/native layer collapses to no-trade

- Candidate v4.2 passes the causal audit and uses a final untouched chronological test slice, but both venue results predict `100% NO_TRADE`; no autonomous adjustments are executed.
- Native exposure calibration is non-informative on the calibration slice (`slope=0.0` for both BitMEX and Hyperliquid), so it cannot rescue the shared model's action-timing failure.
- This is a sparse-label/model-identifiability and autonomous state-generalization blocker. Do not promote v4.2, switch the active Demo model, or add Demo orders.

## 2026-08-26 — Venue-neutral timing head fails to capture action timing

- v4.3 is causally clean but predicts only `2` actions on the BitMEX untouched holdout and `0` on Hyperliquid; timing F1 is `0.000000` on both.
- BitMEX costed net return is `-0.004365` with PF `0.964532`; Hyperliquid has no executed adjustment. The all-NO_TRADE baseline is not treated as learned behavior.
- Autonomous action timing and sparse-label identifiability remain unresolved. Do not promote v4.3, switch the active Demo model, or add Demo orders.
