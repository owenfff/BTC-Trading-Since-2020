# Quant Research Summary

- research status: **RESEARCH_ONLY**
- strategy fidelity: **BEHAVIORAL_APPROXIMATION**
- analysis commit: `659e32c5e536b5ae75eeffd17990c63336b8afb4`
- market bars: `653630` verified 5m XBTUSD rows
- decision rows: `20845`
- historical blended fee rate: `0.00051430` from `98874` XBTUSD action rows
- return unit: normalized exposure-return proxy; not wallet or strategy PnL
- execution: next-bar open, configurable delay, fees, funding, slippage, limit, lot-step, and tick-step parameters
- no exchange API, key, account, live order, or capital was used

## Walk-forward windows

The three windows are chronological: 2020–2022 train / 2023 validation / 2024 test; 2020–2023 train / 2024 validation / 2025 test; 2020–2024 train / 2025 validation / 2026 test. The final 2026 window ends at the frozen market-data boundary.

## Test highlights

| window | strategy | total return | Sharpe | max drawdown | turnover | fees | funding | slippage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| WF1_2020_2022_train_2023_val_2024_test | distilled_rules | 0.024641 | 0.298923 | -0.094497 | 82.147090 | 0.042248 | 0.004701 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | frequency_baseline | 0.000006 | 0.005706 | -0.001560 | 1.153190 | 0.000593 | 0.000178 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | logistic_numpy | 0.212677 | 1.480138 | -0.094614 | 0.250000 | 0.000129 | 0.031432 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | decision_tree_numpy | -0.052002 | -0.839332 | -0.076865 | 18.819320 | 0.009679 | -0.010938 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | btc_buy_hold | 0.218585 | 1.515268 | -0.094614 | 0.250000 | 0.000129 | 0.031699 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | sma_trend | -1.722871 | -0.912929 | -1.706686 | 3384.250000 | 1.740505 | 0.000789 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | volatility_filtered_trend | -1.606434 | -0.448899 | -1.600416 | 3088.250000 | 1.588273 | 0.000211 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | teacher_historical_trajectory | 0.002019 | 0.063456 | -0.055319 | 14.760230 | 0.007591 | -0.010942 | 0.000000 |
| WF1_2020_2022_train_2023_val_2024_test | same_turnover_random | -0.080643 | -0.690908 | -0.100234 | 357.750000 | 0.183989 | 0.000936 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | distilled_rules | 0.057921 | 0.722566 | -0.051612 | 66.190370 | 0.034041 | 0.002333 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | frequency_baseline | -0.001025 | -1.106715 | -0.001334 | 0.912710 | 0.000469 | 0.000090 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | logistic_numpy | -0.362721 | -3.847557 | -0.388422 | 639.250000 | 0.328763 | -0.000603 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | decision_tree_numpy | 0.001950 | 0.062899 | -0.064717 | 31.627100 | 0.016266 | -0.005905 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | btc_buy_hold | -0.012110 | -0.048792 | -0.103962 | 0.250000 | 0.000129 | 0.015953 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | sma_trend | -1.719513 | 0.467525 | -1.719413 | 3417.250000 | 1.757476 | 0.000340 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | volatility_filtered_trend | -1.504905 | -0.748267 | -1.505150 | 2934.000000 | 1.508943 | 0.000188 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | teacher_historical_trajectory | 0.037170 | 0.499536 | -0.089270 | 7.997500 | 0.004113 | -0.010698 | 0.000000 |
| WF2_2020_2023_train_2024_val_2025_test | same_turnover_random | -0.100756 | -1.094462 | -0.135670 | 305.500000 | 0.157117 | -0.000931 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | distilled_rules | -0.019330 | -0.451181 | -0.097153 | 12.249980 | 0.006300 | 0.000736 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | frequency_baseline | -0.000556 | -1.011827 | -0.001064 | 0.243660 | 0.000125 | -0.000014 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | logistic_numpy | -0.063414 | -0.940196 | -0.113861 | 0.250000 | 0.000129 | -0.001622 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | decision_tree_numpy | 0.035160 | 1.477627 | -0.021883 | 1.870370 | 0.000962 | 0.000556 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | btc_buy_hold | -0.060135 | -0.886550 | -0.113861 | 0.250000 | 0.000129 | -0.001553 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | sma_trend | -0.910897 | -32.171160 | -0.911131 | 1781.750000 | 0.916346 | -0.000479 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | volatility_filtered_trend | -0.840769 | -29.696157 | -0.841076 | 1579.750000 | 0.812458 | -0.000335 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | teacher_historical_trajectory | 0.037086 | 1.456688 | -0.032772 | 0.977800 | 0.000503 | 0.000888 | 0.000000 |
| WF3_2020_2024_train_2025_val_2026_test | same_turnover_random | -0.007304 | -0.079203 | -0.101335 | 61.250000 | 0.031501 | 0.000108 | 0.000000 |

## Interpretation

`RESEARCH_ONLY` is intentional. This run establishes a reproducible, leakage-safe backtest foundation and records both favorable and unfavorable outcomes; it does not claim stable out-of-sample profitability. Historical mark/index data is missing, normalized exposure is unitless, and the teacher trajectory is descriptive rather than a tradable benchmark.

See `walk_forward_results.csv`, `robustness_results.csv`, `failure_analysis.md`, and `reproducibility.md` for complete rows and boundaries.
