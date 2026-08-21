# Strategy Fidelity

- strategy fidelity: **BEHAVIORAL_APPROXIMATION**
- source dataset rows: `20845`
- analysis commit: `2daab36eb75c6e1cc876b12ff4e369ea57e8ae5e`
- M5.1 scope: behavior frequency baseline plus deterministic interpretable rules.
- The frequency baseline fits labels from TRAIN only. The rule strategy uses no labels and no exchange SDK.
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

## Timing definitions

Open and close timing error are conservative miss-latency proxies: when the next labeled action belongs to the relevant family but the strategy emits another family, the full time to that next action is charged; a correct family prediction receives zero error. They are not a claim that the strategy knows a future timestamp.

## Boundary

This artifact is a behavioral approximation from trade records. It does not establish profitability, exact intent recovery, or live-trading readiness. Logistic Regression, Decision Tree, walk-forward backtesting, funding/slippage/latency simulation, and exchange adapters remain later stages.
