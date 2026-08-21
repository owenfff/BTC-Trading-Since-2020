# Threat Model

Primary threats are credential leakage, duplicate orders after timeout, stale market data, clock drift, private/public stream disagreement, reconciliation failure, excessive exposure, and accidental live enablement.

Mitigations include ignored secrets, deterministic clientOrderId, query-before-retry, stale/clock/exchange guards, circuit breaker, global kill switch, zero live defaults, Decimal normalization, and explicit reconciliation state. The current adapters use injected fake transports in tests only.
