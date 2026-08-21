# Strategy Fidelity

- strategy fidelity: **BEHAVIORAL_APPROXIMATION**
- source dataset rows: `20845`
- analysis commit: `66c9e34e8189d1fffbd8caf913a876c08df95f31`
- M5.1/M5.2 scope: behavior frequency baseline, deterministic interpretable rules, NumPy Logistic Regression, and a small NumPy Decision Tree.
- Every fitted model uses TRAIN labels only; the rule strategy uses no labels and no exchange SDK.
- Historical mark/index context is missing by source limitation and remains an explicit risk tag.

## Metrics

| model | split | action accuracy | macro F1 | weighted F1 | direction accuracy | target MAE | target correlation | add recall | reduce recall | flip recall | confidence gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| frequency_baseline | TRAIN | 0.523336 | 0.156089 | 0.484450 | 0.896032 | 0.073739 | 0.715041 | 0.816585 | 0.334231 | 0.000000 | 0.000000 |
| frequency_baseline | VALIDATION | 0.441318 | 0.130739 | 0.395334 | 0.848737 | 0.050873 | 0.757110 | 0.808953 | 0.271216 | 0.000000 | 0.071838 |
| frequency_baseline | TEST | 0.526552 | 0.153391 | 0.496763 | 0.977287 | 0.063681 | 0.770534 | 0.733574 | 0.439157 | 0.000000 | 0.036028 |
| distilled_rules | TRAIN | 0.266466 | 0.131943 | 0.317425 | 0.719005 | 0.059457 | 0.873354 | 0.199469 | 0.380183 | 0.000000 | 0.437428 |
| distilled_rules | VALIDATION | 0.245923 | 0.124088 | 0.299303 | 0.638951 | 0.048037 | 0.717950 | 0.255990 | 0.266842 | 0.000000 | 0.578372 |
| distilled_rules | TEST | 0.297185 | 0.135505 | 0.320688 | 0.949776 | 0.060486 | 0.778763 | 0.262816 | 0.358939 | 0.000000 | 0.345377 |
| logistic_numpy | TRAIN | 0.713865 | 0.226068 | 0.684330 | 0.913920 | 0.011163 | 0.991539 | 0.864366 | 0.697361 | 0.000000 | 0.101752 |
| logistic_numpy | VALIDATION | 0.643748 | 0.212284 | 0.599766 | 0.881036 | 0.007032 | 0.986886 | 0.854351 | 0.682415 | 0.000000 | 0.128724 |
| logistic_numpy | TEST | 0.578375 | 0.185222 | 0.539132 | 0.978247 | 0.010021 | 0.988746 | 0.435379 | 0.839565 | 0.000000 | 0.112401 |
| decision_tree_numpy | TRAIN | 0.734494 | 0.233733 | 0.704677 | 0.934686 | 0.066677 | 0.761426 | 0.864619 | 0.725004 | 0.000000 | 0.000000 |
| decision_tree_numpy | VALIDATION | 0.673489 | 0.219668 | 0.627623 | 0.907579 | 0.049363 | 0.747358 | 0.867591 | 0.683290 | 0.000000 | 0.060103 |
| decision_tree_numpy | TEST | 0.641395 | 0.197856 | 0.613716 | 0.980166 | 0.068095 | 0.740529 | 0.745848 | 0.664854 | 0.000000 | 0.171429 |

## Timing definitions

Open and close timing error are conservative miss-latency proxies: when the next labeled action belongs to the relevant family but the strategy emits another family, the full time to that next action is charged; a correct family prediction receives zero error. They are not a claim that the strategy knows a future timestamp.

## Boundary

This artifact is a behavioral approximation from trade records. It does not establish profitability, exact intent recovery, or live-trading readiness. Optional boosted-tree comparison, walk-forward backtesting, funding/slippage/latency simulation, and exchange adapters remain later stages.
