# Clean-room release test

## Result

**PASS_WITH_RESEARCH_INPUT_REHYDRATION_REQUIRED**

The remote branch was cloned into a fresh temporary directory at commit `9c8cf2413dd8e93239941dbe42e012155f0a6524` with no local ignored outputs or caches copied into it.

| Check | Result |
| --- | --- |
| Python runtime | PASS; fresh Python 3.11.9 |
| Declared dependency install | PASS; NumPy 2.3.5, Polars 1.43.2, PyArrow 24.0.0, Pytest 8.4.2 |
| Full pytest suite | PASS; 273 passed, 2 skipped |
| Shadow mode, one fixture row, repeated twice | `SHADOW_SMOKE_PASS`; deterministic |
| Paper mode, one fixture row, repeated twice | `PAPER_SMOKE_PASS`; deterministic |
| Docker Compose configuration | PASS |
| Docker image build/run | PASS; `btc-trading-clean-room:9c8cf24` built and returned `PAPER_SMOKE_PASS` under read-only filesystem and temporary `/tmp` |
| Release secret scan | PASS; 0 findings |
| Personal-data scan | PASS; 0 findings |
| Dependency audit | PASS; all declared requirements pinned |
| License audit | WARNING; tracked historical teacher/source exports require redistribution review |
| Large-file scan | WARNING; 2 tracked historical/source files require review |
| Research command | `BLOCKED_INPUTS_MISSING`, exit 2, controlled preflight |
| Live default | Disabled |
| Demo/private exchange access | `DEMO_CREDENTIALS_REQUIRED`; no credentials requested |

## Research input boundary

`quant/scripts/run_quant_research.py` returned a structured `BLOCKED_INPUTS_MISSING` result in the clean clone because the verified market and behavior outputs under `quant/outputs/` are intentionally ignored and are not redistributed by this release. The release therefore records `quant_research_runnable=false`; it does not claim that a clean clone contains the private/local research dataset.

To rerun full research, rehydrate the exact verified outputs described by the manifests, then run the research command from the repository root. Do not regenerate or modify the protected root account exports.

## Safety boundary

The clean-room smoke path uses only the checked-in fixture. No API key, private account, exchange connection, order submission, or live capital was used. The checked-in defaults keep live mode disabled and both live risk and notional limits at zero.

The Docker image uses the smaller, pinned runtime dependency file `quant/runtime-requirements.txt`; full research and test dependencies remain in `quant/requirements.txt`. The image was built from the current branch after the base image was made available locally, then run with `--read-only --tmpfs /tmp`. It returned one deterministic fixture paper signal with `PAPER_SMOKE_PASS`; no network, credentials, exchange connection, or live capital was used.
