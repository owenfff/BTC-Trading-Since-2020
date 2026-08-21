# Execution and Reconciliation

- clientOrderId generation: deterministic UUID5-derived ID
- timeout policy: query order state before any retry
- duplicate fill events: ignored by event ID
- partial fills: aggregated by clientOrderId
- local restart state: JSON state store smoke-tested
- live exchange reconciliation: interface only; no adapter or network call is enabled

Result: **CODE_READY_OFFLINE_ONLY**
