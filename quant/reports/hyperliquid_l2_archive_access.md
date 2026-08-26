# Hyperliquid Historical L2 Archive Access Audit

> Status: **`REQUESTER_OR_OBJECT_ACCESS_BLOCKED`**. This was a no-download access probe, not a data import.

## Probe

- Method: HTTP `HEAD` only.
- Requester-pays header: not sent.
- Market-file body downloaded: no.
- Representative object keys checked:
  - `market_data/20251115/17/l2Book/BTC.lz4`
  - `market_data/20251115/18/l2Book/BTC.lz4`
  - `market_data/20260101/00/l2Book/BTC.lz4`
  - `market_data/20260718/20/l2Book/BTC.lz4`

## Result

| HTTP status | count |
|---:|---:|
| `403` | 4 |

A `403` is ambiguous between requester-pays/object authorization and an unavailable key. It is not evidence that historical L2 is absent, but the data cannot be used until access, cost, and coverage are independently verified.

## Boundary

No credentials, requester-pays header, private endpoint, mainnet connection, order, or market-file download was used. The active Demo model remains unchanged and promotion is not allowed.
