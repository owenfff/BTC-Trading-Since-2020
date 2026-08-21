# Clean-room release test

## Result

**PASS_WITH_RESEARCH_INPUT_REHYDRATION_REQUIRED**

The remote branch was cloned into a fresh temporary directory at commit `d2bd86bef426bc2288249328ad5afa821293c92a` with no local ignored outputs or caches copied into it.

| Check | Result |
| --- | --- |
| `quant_bot` compilation | PASS |
| Shadow mode, one fixture row | `SHADOW_SMOKE_PASS` |
| Paper mode, one fixture row | `PAPER_SMOKE_PASS` |
| Phase 10 smoke harness | PASS |
| Release secret scan | PASS; 0 findings |
| Research command | BLOCKED_INPUTS_MISSING |
| Live default | Disabled |
| Demo/private exchange access | `DEMO_CREDENTIALS_REQUIRED` |

## Research input boundary

`quant/scripts/run_quant_research.py` correctly stopped in the clean clone because the verified market and behavior outputs under `quant/outputs/` are intentionally ignored and are not redistributed by this release. The release therefore records `quant_research_runnable=false`; it does not claim that a clean clone contains the private/local research dataset.

To rerun full research, rehydrate the exact verified outputs described by the manifests, then run the research command from the repository root. Do not regenerate or modify the protected root account exports.

## Safety boundary

The clean-room smoke path uses only the checked-in fixture. No API key, private account, exchange connection, order submission, or live capital was used. The checked-in defaults keep live mode disabled and both live risk and notional limits at zero.

