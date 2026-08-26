# Prospective Decision Context Audit

> Status: **`READY_FOR_PROSPECTIVE_CAPTURE`**. This records future runtime observations; it is not historical strategy recovery.

## Purpose

The runtime now stores a bounded snapshot immediately after it builds the strategy input and obtains the model output, but before it cancels/replaces orders or submits a new order. This preserves the context that the robot itself actually saw at decision time.

## Captured context

- venue and historical symbol mapping;
- bid/ask, quote timestamp, closed-bar timestamp and source;
- funding rate, mark/index values, source timestamps and coverage status;
- allowlisted strategy features only;
- model action, target exposure, confidence, validity and risk tags;
- reconciled pre-action quantity and equity.

Snapshots are persisted under the ignored runtime state `behavior_state.decision_audit`, capped at 5,000 rows with oldest-first eviction. No credentials or raw adapter payloads are copied.

## Boundary

This makes future Demo behavior auditable and replayable. It does not add labels to historical data, recover the original trader's missing private trigger, promote a model, or authorize orders. The current model remains `BEHAVIORAL_APPROXIMATION`; Demo state is unchanged.

## Verification

- Targeted runtime tests: `5 passed`.
- Full suite: `411 passed`.
- Raw CSV/JSON inputs unchanged; no credentials, private endpoints, mainnet connection or new Demo order used.
