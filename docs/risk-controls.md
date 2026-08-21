# Risk controls

Risk checks are fail-closed. They cover stale data, clock skew, exchange identity, portfolio limits, drawdown, circuit breaker state, kill switch state, duplicate order intent, and reconciliation.

The checked-in default configuration keeps live mode disabled and live risk/notional limits at zero. A human must explicitly review any future non-zero configuration.

