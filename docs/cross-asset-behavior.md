# Cross-Asset Behavioral Reproduction

M13 expands the historical behavior audit from an XBTUSD-first scope to the full 66-symbol decision universe. The result remains `BEHAVIORAL_APPROXIMATION`: it does not claim exact intent recovery, future profitability, or permission to trade.

## Data boundary

- Historical decisions: 32,231 across 66 symbols.
- Market context: public, no-key BitMEX hourly `trade/bucketed` data and public funding data.
- Synthetic market history: forbidden and not used.
- Spot rows remain auditable and are not mixed with derivative position semantics.
- Historical mark/index context remains missing unless present in the verified source; current snapshots are never backfilled.
- Raw account CSV/JSON files remain protected and unchanged.

Coverage is recorded per symbol in `quant/reports/cross_asset_universe.csv` and `quant/outputs/cross_asset_market_coverage.json`. Symbols with insufficient coverage or without a train-only position scale are excluded from unified model fitting, but remain in the behavior inventory.

## Unified model

The exchange-neutral Strategy Core consumes the versioned cross-asset feature contract and emits action, target exposure, confidence, risk tags, and validity. The deterministic NumPy model version is `behavioral-distillation-v2-cross-asset-logistic`.

The model uses chronological TRAIN rows only. Features exclude `label_*`, `observed_*`, future bars, future funding, future account history, and future actions. The tracked leakage audit must remain `PASS` before any paper replay.

## Validation

The tracked reports include global and per-symbol fidelity, three expanding chronological walk-forward windows, fee/slippage/exposure sensitivity, and a local paper replay. Return columns are normalized exposure-return diagnostics, not wallet or account PnL.

Paper replay is local only. Each symbol has an independent paper engine; no exchange SDK, private API, credential, order, or real capital is used.
