# OKX Public Market History Audit

- status: **READY_WITH_WARNINGS**
- analysis commit: `8023adcd46e4004de56f7d4c8e24e180a1ff89b3`
- source: `https://www.okx.com/api/v5`; credentials: `none`
- requested range: `2020-01-01 00:00:00+00:00` to `2026-08-28 03:44:20.675765+00:00`

## What was imported

The importer uses OKX public history endpoints only. Candle rows are filtered to `confirm=1`; the source opening timestamp is retained and the normalized `timestamp` is the bar close. All context joins are previous-or-equal to that closed bar.

| instrument | candle rows | mark rows | index rows | funding rows | candle audit | causal violations | status |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| BTC-USDT-SWAP | 8999 | 1900 | 10000 | 284 | PASS | 0 | READY_WITH_WARNINGS |

## Coverage interpretation

- OKX historical candles are the primary market series for replay; no BitMEX price is substituted.
- Funding is best-effort and may be limited by OKX public retention. Missing funding remains `None` with a missing mask.
- Mark/index history is attached only when its source timestamp is not later than the closed candle. A missing context value is not replaced with zero.
- Public trade history is not used as a multi-year replacement for the original trader's private BitMEX fills. This output is market context, not teacher labels.

## Lineage and safety

- documentation: [https://app.okx.com/docs-v5/en/](https://app.okx.com/docs-v5/en/)
- protected raw account inputs unchanged: `True`
- changed protected files: `[]`
- raw API page caches and row-level outputs are under ignored `quant/outputs/okx_public_market/`.
- no API key, secret, passphrase, private endpoint, Demo account, or order endpoint is used by this command.

## Next use

Use the generated `features.csv` as a market-context input to the existing historical replay. Keep the BitMEX CSV events as the separate teacher behavior source, and evaluate any model with strict autonomous replay before changing the active Demo model.
