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

## 2026-08-20 — Freeze wallet reconciliation boundary

- Use wallet `timestamp` as the balance-ledger order because `transactTime` can precede the exported balance event.
- Treat repeated rows sharing a final `walletBalance` as one continuity batch; compare the sum of completed amounts to the batch balance delta.
- Wallet reconciliation is `READY_WITH_WARNINGS`: 17,474 row-level PASS, 5 real batch anomalies, 3/15 exact snapshot matches, 12 zero snapshots without wallet-history coverage, and terminal XBT/equity agreement.
- Keep wallet-to-execution comparisons aggregate-only; do not fabricate a row-level join from `transactID`, `orderID`, or address fields.
- Proceed to BTC-first behavior episodes and trade cycles while carrying wallet continuity and snapshot coverage flags into derived datasets.

## 2026-08-20 — Enter behavioral episode construction

- Preserve the layered structure: raw derivative fills → execution batches → order episodes → position actions → decision episodes → position cycles.
- XBTUSD is the BTC-first teacher scope; altcoin derivative episodes remain available for generalization diagnostics.
- Execution batches use a documented 300-second same-order gap boundary and never redefine an order episode as a decision.
- Daily XBTUSD no-trade days become explicitly synthetic `HOLD_LONG`, `HOLD_SHORT`, or `NO_TRADE` observations; they are never mixed with raw fills.
- Wallet linkage remains aggregate-only and all six confidence fields are carried into actions, decisions, and cycles.
