# Prospective Decision Audit Journal

- Status: **READY_NO_RUNTIME_RECORDS**
- Journal files: `0`
- Valid decision records: `0`
- Malformed lines: `0`
- Sensitive key paths: `0`

## Purpose

This journal preserves future robot observations before order cancellation or submission. The compact runtime state keeps the latest 5,000 records; this UTC-partitioned JSONL journal is append-only and retained under ignored `quant/outputs/`.

## Files

- No Demo decision records have been captured yet.

## Safety boundary

- Records are allowlisted market context, strategy features, and model output only.
- Sensitive key names, non-JSON values, invalid timestamps, and oversized records are rejected before append.
- This journal is prospective evidence only; it does not recover missing historical pre-action context or prove exact strategy recovery.
- No model promotion, new Demo order, private credential, or mainnet connection is performed by this audit.
