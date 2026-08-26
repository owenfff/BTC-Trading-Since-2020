# Venue-Native Behavior Audit

> Diagnostic only. Each venue is split chronologically and calibrated independently. No result authorizes a Demo model switch or order.

| venue | train rows | test rows | autonomous net return | profit factor | autonomous action rate |
|---|---:|---:|---:|---:|---:|
| `BITMEX` | 206793 | 42624 | -0.004768 | 0.971626 | 57.43% |
| `HYPERLIQUID` | 4636 | 1160 | 0.000000 | — | 0.00% |

## Interpretation

A positive native holdout is not evidence of cross-venue generalization; a negative one does not prove the trader changed strategy. Contract scale, funding, liquidity and market coverage are venue-specific. The shared model remains blocked until global causal and costed gates pass.

## Boundary

No credentials, private endpoint, mainnet connection, or order was used. Raw CSV/JSON files remain read-only.
