# Label Dictionary

Labels are future outcomes and are kept separate from feature construction.

| label | definition |
| --- | --- |
| `label_next_target_exposure` | Next strictly later decision's target contract position divided by 10,000,000 |
| `label_next_action` | Next strictly later decision action, including `NO_TRADE` and `HOLD_*` |
| `label_next_position_delta_bucket` | Next position delta: `ZERO`, `SMALL` (<=1% scale), `MEDIUM` (<=10%), or `LARGE` |
| `label_time_to_next_action_seconds` | Seconds until the next strictly later decision |
| `label_status` | `AVAILABLE`, `NO_LATER_DECISION`, or `SAME_TIMESTAMP_TIE_ONLY` |

Rows with no later strictly timed decision retain null labels; same-timestamp order ties are not treated as future labels.
