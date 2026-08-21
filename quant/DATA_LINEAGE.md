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
