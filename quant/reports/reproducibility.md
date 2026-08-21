# Reproducibility

- command: `python quant/scripts/run_quant_research.py`
- source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- analysis commit: `b43e428c752383436485813fd5a0c8ae3a02b920`
- branch: `quant/autonomous-behavioral-quant-bot-v1`
- model dataset: `quant/outputs/model_dataset.csv` (ignored local fallback)
- market bars: `quant/outputs/market_bars.csv` (ignored verified public cache output)
- funding/context: `quant/outputs/market_context.csv` (ignored verified public cache output)
- random benchmark seed: `42`; no random split or random model fitting
- model fitting: chronological TRAIN rows only; no test-period statistic fit
- execution: next closed bar's open, configurable bar delay, no same-bar close ideal fill
- external ML dependencies: not used; Logistic Regression and Decision Tree use deterministic NumPy
- research reports: `quant/reports/quant_research_summary.json`, `quant/reports/quant_research_summary.md`, `quant/reports/walk_forward_results.csv`, `quant/reports/robustness_results.csv`
