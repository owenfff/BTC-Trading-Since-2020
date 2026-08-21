# Reproducibility

- command: `python quant/scripts/run_quant_research.py`
- source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- analysis commit: `659e32c5e536b5ae75eeffd17990c63336b8afb4`
- branch: `quant/autonomous-behavioral-quant-bot-v1`
- model dataset: `quant/outputs/model_dataset.csv` (ignored local fallback)
- market bars: `quant/outputs/market_bars.csv` (ignored verified public cache output)
- funding/context: `quant/outputs/market_context.csv` (ignored verified public cache output)
- random benchmark seed: `42`; no random split or random model fitting
- model fitting: chronological TRAIN rows only; no test-period statistic fit
- execution: next closed bar's open, configurable bar delay, no same-bar close ideal fill
- external ML dependencies: not used; Logistic Regression and Decision Tree use deterministic NumPy
- research reports: `quant/reports/quant_research_summary.json`, `quant/reports/quant_research_summary.md`, `quant/reports/walk_forward_results.csv`, `quant/reports/robustness_results.csv`

## Clean-room verification

- clean-room commit: `9c8cf2413dd8e93239941dbe42e012155f0a6524`
- release-audit commit: `9c8cf2413dd8e93239941dbe42e012155f0a6524`
- fresh runtime: Python 3.11.9
- pinned dependencies: NumPy 2.3.5; Polars 1.43.2; PyArrow 24.0.0; Pytest 8.4.2
- clean-room tests: 273 passed, 2 skipped because two checks require intentionally ignored derived outputs
- shadow and paper fixture smoke: each repeated twice with identical one-row output
- full research without rehydration: controlled `BLOCKED_INPUTS_MISSING`, exit code 2
- Docker Compose config: PASS; Docker image build/run: PASS with `btc-trading-clean-room:9c8cf24` and `PAPER_SMOKE_PASS` under read-only filesystem
- secret scan: PASS; personal-data scan: PASS; dependency pin audit: PASS; license audit: warning for tracked teacher/source redistribution review
- `quant_research_runnable`: `false`; `paper_code_ready`: `true`
- Docker uses the pinned runtime-only dependency set in `quant/runtime-requirements.txt`; full research/test dependencies remain in `quant/requirements.txt`.
