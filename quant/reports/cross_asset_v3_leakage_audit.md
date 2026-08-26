# Cross-Asset Leakage Audit

- status: **PASS**
- rows: `32231`
- model-eligible rows: `10630`

| check | violations |
| --- | ---: |
| future_bar_observation_count | 0 |
| future_funding_observation_count | 0 |
| future_history_observation_count | 0 |
| non_future_label_violation_count | 0 |
| invalid_decision_time_count | 0 |

All market observations are strictly earlier than the decision. Labels use the next strictly later decision within the same symbol. Symbol coverage failures remain explicit and are excluded from model fitting.
