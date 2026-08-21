# Leakage Audit

- status: **PASS**
- analysis commit: `83d636abf994b1a57ed751c9b6f1051a00a13204`
- rows audited: `20845`

## Checks

| check | violations |
| --- | ---: |
| future_bar_observation_count | 0 |
| future_funding_observation_count | 0 |
| future_history_observation_count | 0 |
| non_future_label_violation_count | 0 |
| invalid_decision_time_count | 0 |

Feature rule: `bar_end_time < decision_time`; funding source timestamps must be `<= decision_time`; history timestamps must be strictly earlier. Labels use the next strictly later decision and skip same-timestamp ties.

No future high/low, future cycle PnL, future action, or test-period normalization statistic is used as a feature. Historical mark/index context is missing by source limitation and is represented by an explicit missingness flag.

- dataset split: `Chronological 70% TRAIN / 15% VALIDATION / 15% TEST by decision_time; no random shuffle; no fit statistics`
- raw account inputs unchanged: `True`
