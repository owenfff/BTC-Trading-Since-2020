# Autonomous Decisions

## 2026-08-20 — Freeze accounting boundary

- Treat quantity reconstruction as `EXACT` and use the analytical ledger for behavioral research.
- Keep exchange-reported `realisedPnl`, `execComm`, Funding, wallet history, and position snapshots in a separate reported ledger.
- Keep analytical cost, gross PnL, AEP, cycles, and confidence flags in a separate analytical ledger.
- Classify current-cost fidelity as `HIGH_CONFIDENCE_WITH_RESIDUAL`; do not add more global rounding brute force unless wallet reconciliation supplies direct evidence.
- Classify AEP fidelity as `HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED`.
- Use `PASS` and `WARNING` valuation rows for downstream accounting; only `BLOCKED` rows are excluded.
- The dataset is `TRADE_RECORDS_ONLY`, so strategy fidelity is permanently reported as `BEHAVIORAL_APPROXIMATION`.

## 2026-08-20 — Enter wallet reconciliation

- Phase 1 is frozen in `accounting_foundation_manifest.json` with downstream status `READY_WITH_KNOWN_ACCOUNTING_RESIDUALS`.
- Wallet reconciliation is the next evidence-gathering step; it may improve accounting confidence but must not fabricate one-to-one joins when wallet exports do not carry a unique execution reference.
- Reconciliation will be reported at execution, hour, day, and terminal-snapshot levels according to available evidence.
