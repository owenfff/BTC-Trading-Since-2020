# M0-02B-0 Historical BitMEX Instrument Specification Coverage

Data source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`; analysis commit: `409911a79b6e31a3721226c73ed737cf35280f48`; branch: `quant/m0-02b0-historical-instrument-specs`.

## Execution summary

- `m0_02b_spec_readiness`: **BLOCKED_BY_MULTIPLIER_VALIDATION**
- Registry: `M0-02B-0/1.0`; total materialized specs: `784` (`11` configured historical + `773` frozen snapshot versions).
- Derivative execution denominator: `173,226`; mapped: `173,226`; coverage: `100.000000`%.
- `MISSING_SPEC`: `0`; `OVERLAPPING_SPECS`: `0`.
- Settlement mapping: `19/19`; settlement currency conflicts: `0`; payout-model conflicts: `0`.
- Multiplier validation: `5809/7234` exact; mismatches: `1425`.
- Spot executions excluded from denominator: `208` Spot Trade rows.

This report only resolves instrument specifications. It does not calculate average cost, realised/unrealised PnL, equity, leverage, margin, candles or trading signals.

## Registry and interval policy

Resolution uses exact symbol matching and the UTC interval `valid_from <= event_time < valid_to_exclusive`. No latest-version fallback is permitted. Snapshot rows retain the requested raw fields, the frozen data commit and a stable complete-row SHA256.

| item | value |
| --- | --- |
| configured historical versions | 11 |
| snapshot versions | 773 |
| spec versions used by derivative executions | 66 |
| interval validation errors | 0 |

## Risk symbols

| symbol | events | matched | specs used | evidence | status |
| --- | --- | --- | --- | --- | --- |
| AAVEUSDT | 567 | 567 | AAVEUSDT-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| ADAUSDT | 155 | 155 | ADAUSDT-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| BNBUSDT | 185 | 185 | BNBUSDT-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| DOGEUSDT | 2068 | 2068 | DOGEUSDT-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| DOTUSDT | 3506 | 3506 | DOTUSDT-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| LINKUSDT | 253 | 253 | LINKUSDT-QUANTO-XBT-2020 | OFFICIAL_EXPLICIT | PASS |
| LUNAUSD | 428 | 428 | LUNAUSD-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| ORDIUSD | 407 | 407 | ORDIUSD-QUANTO-XBT-2023 | OFFICIAL_EXPLICIT | PASS |
| TRXUSDT | 27 | 27 | TRXUSDT-QUANTO-XBT-2021 | OFFICIAL_EXPLICIT | PASS |
| UNIUSDT | 889 | 889 | UNIUSDT-QUANTO-XBT-2021 | OFFICIAL_PARTIAL_EXECUTION_VALIDATED | PASS |
| XLMUSDT | 54 | 54 | XLMUSDT-QUANTO-XBT-2021 | OFFICIAL_PARTIAL_EXECUTION_VALIDATED | PASS |

AAVEUSDT historical rows resolve to `AAVEUSDT-QUANTO-XBT-2021`; the 2024 linear snapshot is outside the historical interval and does not match them.

## Acceptance checks

- XBTUSD mapped specification(s): `['XBTUSD-SNAPSHOT-19d9fb1b3d79']`; payout model(s): `['INVERSE']`; all mapped XBTUSD rows are inverse: **True**.
- AAVEUSDT 2021 mapped specification(s): `['AAVEUSDT-QUANTO-XBT-2021']`; payout model(s): `['QUANTO']`.

## Coverage by symbol

| symbol | derivative events | matched | missing | overlap | compatibility conflicts | first event | last event |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAVEUSDT | 567 | 567 | 0 | 0 | 0 | 2021-07-27T21:27:02.794000Z | 2021-11-02T11:59:59.999000Z |
| ADAM20 | 366 | 366 | 0 | 0 | 0 | 2020-05-02T14:26:45.069000Z | 2020-06-24T06:19:12.538000Z |
| ADAUSD | 575 | 575 | 0 | 0 | 0 | 2021-10-26T05:00:42.074000Z | 2021-11-20T11:47:48.728000Z |
| ADAUSDT | 155 | 155 | 0 | 0 | 0 | 2021-08-09T18:47:45.807000Z | 2021-08-10T16:43:22.467000Z |
| ALTMEXUSD | 70 | 70 | 0 | 0 | 0 | 2021-07-23T04:23:53.756000Z | 2021-07-30T21:00:09.605000Z |
| AXSUSDT | 919 | 919 | 0 | 0 | 0 | 2021-08-11T07:20:56.717000Z | 2021-10-29T16:16:08.976000Z |
| BCHH21 | 101 | 101 | 0 | 0 | 0 | 2021-01-20T00:52:39.433000Z | 2021-02-06T01:40:29.754000Z |
| BCHUSD | 154 | 154 | 0 | 0 | 0 | 2020-09-13T01:17:39.200000Z | 2021-02-02T16:14:13.307000Z |
| BMEXUSD | 143 | 143 | 0 | 0 | 0 | 2022-11-16T01:22:48.452000Z | 2022-11-28T21:05:09.635000Z |
| BNBUSD | 28 | 28 | 0 | 0 | 0 | 2022-01-15T09:17:33.275000Z | 2022-01-15T20:02:51.503000Z |
| BNBUSDT | 185 | 185 | 0 | 0 | 0 | 2021-05-24T05:47:01.011000Z | 2021-10-11T16:36:13.469000Z |
| DOGEUSD | 5924 | 5924 | 0 | 0 | 0 | 2021-10-01T10:11:06.936000Z | 2024-11-04T22:30:18.788000Z |
| DOGEUSDT | 2068 | 2068 | 0 | 0 | 0 | 2021-02-08T04:42:56.268000Z | 2021-09-20T12:37:28.066000Z |
| DOTUSDT | 3506 | 3506 | 0 | 0 | 0 | 2021-03-06T23:27:08.836000Z | 2021-08-17T07:04:54.304000Z |
| DOTUSDTH21 | 49 | 49 | 0 | 0 | 0 | 2021-01-13T22:27:28.708000Z | 2021-03-24T23:41:56.187000Z |
| EOSH21 | 37 | 37 | 0 | 0 | 0 | 2021-01-31T11:31:18.385000Z | 2021-02-07T15:38:05.259000Z |
| EOSUSDTZ20 | 7 | 7 | 0 | 0 | 0 | 2020-10-12T14:58:26.272000Z | 2020-10-14T14:29:40.627000Z |
| ETHH21 | 1138 | 1138 | 0 | 0 | 0 | 2020-12-26T15:54:11.011000Z | 2021-03-26T11:59:59.999000Z |
| ETHH22 | 477 | 477 | 0 | 0 | 0 | 2021-12-31T20:19:58.340000Z | 2022-03-21T20:14:22.063000Z |
| ETHH23 | 391 | 391 | 0 | 0 | 0 | 2023-02-01T14:53:14.510000Z | 2023-03-31T11:59:59.999000Z |
| ETHH24 | 35 | 35 | 0 | 0 | 0 | 2024-01-12T13:59:36.205000Z | 2024-03-29T12:00:00Z |
| ETHM20 | 86 | 86 | 0 | 0 | 0 | 2020-05-29T00:07:56.507000Z | 2020-06-26T07:16:24.011000Z |
| ETHM21 | 178 | 178 | 0 | 0 | 0 | 2021-03-26T23:49:14.441000Z | 2021-06-05T14:15:59.838000Z |
| ETHM22 | 234 | 234 | 0 | 0 | 0 | 2022-03-16T07:47:35.207000Z | 2022-06-24T11:59:59.999000Z |
| ETHM23 | 351 | 351 | 0 | 0 | 0 | 2023-03-23T15:38:09.675000Z | 2023-06-30T11:59:59.999000Z |
| ETHM24 | 282 | 282 | 0 | 0 | 0 | 2024-04-04T20:10:55.922000Z | 2024-06-28T12:00:10.288000Z |
| ETHU20 | 221 | 221 | 0 | 0 | 0 | 2020-07-06T21:23:16.149000Z | 2020-08-20T19:34:39.661000Z |
| ETHU21 | 476 | 476 | 0 | 0 | 0 | 2021-06-24T16:01:32.517000Z | 2021-08-02T15:13:47.175000Z |
| ETHU22 | 47 | 47 | 0 | 0 | 0 | 2022-06-24T19:44:49.420000Z | 2022-09-17T08:34:43.983000Z |
| ETHU23 | 180 | 180 | 0 | 0 | 0 | 2023-08-04T01:20:15.739000Z | 2023-09-29T11:59:59.999000Z |
| ETHU24 | 157 | 157 | 0 | 0 | 0 | 2024-06-20T07:23:01.167000Z | 2024-09-27T12:00:15.299000Z |
| ETHUSD | 19470 | 19470 | 0 | 0 | 0 | 2020-06-01T22:24:28.491000Z | 2024-02-26T19:44:55.050000Z |
| ETHUSDZ20 | 8 | 8 | 0 | 0 | 0 | 2020-10-12T13:39:21.644000Z | 2020-10-12T16:32:24.038000Z |
| ETHZ20 | 1168 | 1168 | 0 | 0 | 0 | 2020-10-28T11:17:12.414000Z | 2020-12-25T11:59:59.999000Z |
| ETHZ21 | 870 | 870 | 0 | 0 | 0 | 2021-10-05T21:55:06.009000Z | 2021-12-31T11:59:59.999000Z |
| ETHZ22 | 182 | 182 | 0 | 0 | 0 | 2022-10-22T22:00:42.461000Z | 2022-12-21T16:19:51.536000Z |
| ETHZ23 | 271 | 271 | 0 | 0 | 0 | 2023-09-29T20:51:15.892000Z | 2023-12-29T12:00:00Z |
| ETHZ24 | 80 | 80 | 0 | 0 | 0 | 2024-10-14T15:26:28.211000Z | 2024-12-27T12:00:10.289000Z |
| LINKUSDT | 253 | 253 | 0 | 0 | 0 | 2021-02-02T07:30:06.999000Z | 2021-09-22T09:14:08.137000Z |
| LINKUSDTZ20 | 16 | 16 | 0 | 0 | 0 | 2020-09-13T00:07:48.984000Z | 2020-09-24T15:38:46.277000Z |
| LTCH21 | 1414 | 1414 | 0 | 0 | 0 | 2020-12-25T18:30:08.190000Z | 2021-03-21T04:28:55.762000Z |
| LTCM20 | 387 | 387 | 0 | 0 | 0 | 2020-05-01T23:45:58.220000Z | 2020-06-08T22:11:45.084000Z |
| LTCM21 | 172 | 172 | 0 | 0 | 0 | 2021-03-29T02:41:02.762000Z | 2021-04-24T05:09:28.694000Z |
| LTCU20 | 316 | 316 | 0 | 0 | 0 | 2020-06-26T12:29:11.610000Z | 2020-09-04T06:45:08.462000Z |
| LTCU21 | 418 | 418 | 0 | 0 | 0 | 2021-08-10T06:48:12.576000Z | 2021-09-24T11:59:59.999000Z |
| LTCUSD | 7473 | 7473 | 0 | 0 | 0 | 2020-08-01T10:10:23.992000Z | 2023-12-06T16:47:47.204000Z |
| LTCZ20 | 816 | 816 | 0 | 0 | 0 | 2020-10-01T14:22:13.848000Z | 2020-12-25T11:59:59.999000Z |
| LTCZ21 | 122 | 122 | 0 | 0 | 0 | 2021-12-06T22:19:25.621000Z | 2021-12-13T19:20:17.272000Z |
| LUNAUSD | 428 | 428 | 0 | 0 | 0 | 2021-10-20T09:55:35.965000Z | 2022-01-22T07:59:21.398000Z |
| ORDIUSD | 407 | 407 | 0 | 0 | 0 | 2023-06-09T01:29:30.612000Z | 2023-10-19T12:00:00Z |
| TRXH21 | 2218 | 2218 | 0 | 0 | 0 | 2020-12-27T16:00:37.274000Z | 2021-03-20T23:20:45.170000Z |
| TRXM20 | 137 | 137 | 0 | 0 | 0 | 2020-05-22T21:43:52.981000Z | 2020-06-14T11:15:54.307000Z |
| TRXM21 | 1468 | 1468 | 0 | 0 | 0 | 2021-03-19T17:56:44.382000Z | 2021-05-20T20:56:46.565000Z |
| TRXU20 | 771 | 771 | 0 | 0 | 0 | 2020-06-30T10:17:05.892000Z | 2020-09-23T18:49:35.589000Z |
| TRXU21 | 1759 | 1759 | 0 | 0 | 0 | 2021-06-29T04:16:50.250000Z | 2021-09-24T11:59:59.999000Z |
| TRXUSDT | 27 | 27 | 0 | 0 | 0 | 2021-10-29T17:27:32.668000Z | 2021-11-02T11:59:59.999000Z |
| TRXZ20 | 498 | 498 | 0 | 0 | 0 | 2020-10-02T04:39:11.650000Z | 2020-12-16T10:03:47.449000Z |
| TRXZ21 | 124 | 124 | 0 | 0 | 0 | 2021-11-15T06:44:35.666000Z | 2021-12-03T20:39:26.899000Z |
| UNIUSDT | 889 | 889 | 0 | 0 | 0 | 2021-04-06T01:12:53.327000Z | 2021-07-13T13:44:24.437000Z |
| XBTM21 | 19 | 19 | 0 | 0 | 0 | 2021-06-05T14:47:48.300000Z | 2021-06-05T14:48:22.779000Z |
| XBTUSD | 104880 | 104880 | 0 | 0 | 0 | 2020-05-01T09:03:47.360000Z | 2026-07-19T12:00:00.330000Z |
| XLMUSDT | 54 | 54 | 0 | 0 | 0 | 2021-04-11T00:32:18.902000Z | 2021-04-11T10:00:31.036000Z |
| XRPUSD | 6128 | 6128 | 0 | 0 | 0 | 2020-07-25T20:39:42.895000Z | 2023-06-15T06:59:21.591000Z |
| XTZUSDTZ20 | 9 | 9 | 0 | 0 | 0 | 2020-10-10T07:58:05.289000Z | 2020-10-13T13:57:53.783000Z |
| YFIUSDTH21 | 359 | 359 | 0 | 0 | 0 | 2020-12-31T07:06:20.957000Z | 2021-03-08T22:24:32.751000Z |
| YFIUSDTZ20 | 508 | 508 | 0 | 0 | 0 | 2020-10-30T20:01:47.433000Z | 2020-12-25T11:59:59.999000Z |

## Evidence confidence

| evidence_confidence | mapped execution rows |
| --- | --- |
| OFFICIAL_EXPLICIT | 172283 |
| OFFICIAL_PARTIAL_EXECUTION_VALIDATED | 943 |

| effective_evidence_confidence | historical spec count |
| --- | --- |
| OFFICIAL_EXPLICIT | 9 |
| OFFICIAL_PARTIAL_EXECUTION_VALIDATED | 2 |

Historical `UNIUSDT` and `XLMUSDT` multiplier values are `OFFICIAL_PARTIAL_EXECUTION_VALIDATED`: the official BitMEX announcement confirms the Quanto/XBT product, while the numeric multiplier is validated against all observed non-zero `execCost` Trade rows. Missing old underlying fields remain explicit nulls rather than guesses.

## Evidence gaps

The following materialized snapshot versions still lack `multiplier_major`. They are currently unused by the frozen execution set, so they do not block this historical replay gate:

| symbol | spec_id | missing fields | used in execution |
| --- | --- | --- | --- |
| AIDOGEUSDT | AIDOGEUSDT-SNAPSHOT-de6f8d25ee15 | multiplier_major | False |
| ETHXBT | ETHXBT-SNAPSHOT-6a225f7c7c04 | multiplier_major | False |
| FCTXBT | FCTXBT-SNAPSHOT-293f713744f2 | multiplier_major | False |
| LSKXBT | LSKXBT-SNAPSHOT-a82491674108 | multiplier_major | False |
| LTCXBT | LTCXBT-SNAPSHOT-4c96ba9905d0 | multiplier_major | False |
| XBTU26-XBTH27 | XBTU26-XBTH27-SNAPSHOT-939454726067 | multiplier_major | False |
| XBTU26-XBTZ26 | XBTU26-XBTZ26-SNAPSHOT-164174a964d7 | multiplier_major | False |
| XBTUSD-XBTH27 | XBTUSD-XBTH27-SNAPSHOT-bd523923e8d7 | multiplier_major | False |
| XBTUSD-XBTU26 | XBTUSD-XBTU26-SNAPSHOT-d35e1f907fb7 | multiplier_major | False |
| XBTUSD-XBTZ26 | XBTUSD-XBTZ26-SNAPSHOT-a89b4fbf6d2f | multiplier_major | False |
| XBTZ26-XBTH27 | XBTZ26-XBTH27-SNAPSHOT-d9e1470d7435 | multiplier_major | False |

## Readiness and blockers

- multiplier validation: DOTUSDT-QUANTO-XBT-2021: 1369 execCost mismatch(es)
- multiplier validation: LINKUSDT-QUANTO-XBT-2020: 56 execCost mismatch(es)

Cost/PnL replay gate: **BLOCKED_BY_MULTIPLIER_VALIDATION**. Core-field blockers are evaluated over specification versions actually used by the frozen derivative execution mapping. Unused current-snapshot rows with unavailable derivations remain listed in `spec_evidence_matrix.csv`; they are not silently filled and do not block this historical dataset gate.

## Raw-data protection

Protected CSV/JSON SHA256 unchanged: **True**; changed files: `none`.

References: [Get Instruments](https://docs.bitmex.com/api-explorer/get-instruments), [contract-size formulas](https://support.bitmex.com/hc/en-gb/articles/16797952159261-How-Do-I-Calculate-Contract-Size-and-Minimum-Trade-Amount-Using-the-instrument-Endpoint). Historical URLs are retained in `spec_evidence_matrix.csv` and the versioned JSON configuration.
