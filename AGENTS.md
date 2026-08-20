# Autonomous Quant Program Rules

This repository is an offline research and simulation project. Preserve the raw CSV/JSON files at the repository root byte-for-byte.

## Non-negotiable boundaries

- Never request, store, or use real API keys, secrets, private keys, or real funds.
- Never connect to a real trading account or place live orders.
- Never modify, overwrite, reformat, move, or recommit raw root CSV/JSON files.
- Do not push `main`, create pull requests, merge pull requests, squash, rebase, or rewrite existing analysis history.
- Keep large Parquet, raw market files, and event-level CSV/JSON under `quant/outputs/` or a local cache and ignored by Git.
- Use UTC, `Decimal` for monetary values, explicit currency/scale, and deterministic time-series ordering.
- Never use future information, random time-series shuffles, per-row favorable overrides, or arbitrary tolerances to hide reconciliation differences.

## Research contract

The teacher data is `TRADE_RECORDS_ONLY`; the strongest honest strategy claim is `BEHAVIORAL_APPROXIMATION`. Exchange-reported accounting and analytical accounting must remain separate. Current-cost/AEP residuals are recorded as fidelity limitations and do not globally block behavioral research.

Every complete work package must update the autonomous state files, run the real command and tests, inspect the diff, use a code commit followed by a report commit, push the autonomous branch, and leave `git status` clean with an explicit `next_action`.

Before resuming, read `quant/AUTONOMOUS_PROGRAM.md`, `quant/AUTONOMOUS_STATE.json`, `quant/DECISIONS.md`, `quant/BLOCKERS.md`, and `quant/DATA_LINEAGE.md`. Continue from `next_action`; do not restart completed work.
