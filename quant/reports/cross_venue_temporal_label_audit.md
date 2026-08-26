# Cross-Venue Temporal Label Audit

- status: **PASS_WITH_WARNINGS**
- event rows: `32552` across `66` state keys
- temporal rows: `264609`; eligible: `264288`
- strategy fidelity: `BEHAVIORAL_APPROXIMATION`

## Checks

| check | count | classification |
| --- | ---: | --- |
| `net_zero_label_hides_source_action` | 70 | WARNING |
| `same_timestamp_event_ties` | 373 | WARNING |

## Interpretation

- event action/target consistency: **PASS**
- temporal action/target consistency: **PASS**
- same-hour net-zero: Some hourly labels can hide offsetting source actions; this is retained as a warning, not silently relabeled.
- execution semantics: A decision at t uses state strictly before t and labels the net target before the next hourly decision; autonomous replay executes at the next bar open.

Detailed per-venue/per-instrument counts are in `cross_venue_temporal_label_audit_by_symbol.csv`.
