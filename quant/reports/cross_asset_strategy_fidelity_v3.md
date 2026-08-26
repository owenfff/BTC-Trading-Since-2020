# Cross-Asset Strategy Fidelity_v3

- strategy fidelity: **BEHAVIORAL_APPROXIMATION**
- eligible rows: `10630`
- eligible symbols: `53`
- analysis commit: `e90499470c82f25804687c829ca6c5ddb0f79d84`
- models: frequency baseline, deterministic rules, and unified NumPy cross-asset logistic model
- all fits use chronological TRAIN rows only
- no exchange SDK, private API, credential, or live capital was used

## Interpretation

This is a behavioral approximation. Per-symbol metrics, walk-forward rows, and sensitivity rows are descriptive validation artifacts. The return columns are normalized exposure-return proxies and are not wallet, account, or strategy PnL claims.
