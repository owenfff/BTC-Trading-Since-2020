# Hyperliquid Order Intent Audit

> `PARTIAL_PRE_ACTION_CONTEXT`: the snapshot exposes submitted order terms before fills, but not a complete trigger context.

## Result

- Order records: `2649`; unique order IDs: `1343`.
- Filled-status order IDs: `203`; matching fill order IDs: `203`; creation before/at first fill: `203`.
- All order records are `Limit` / `Gtc` in this snapshot.
- Available intent fields include side, limit price, size, GTC, reduce-only/trigger flags and order timestamp.

## What this adds

It supports a stronger description of Hyperliquid execution style: submitted limit-order terms and their later open/canceled/filled lifecycle can be analyzed before looking at the fill result.

## What it does not add

It does not provide the historical quote/order-book state, the trader's private trigger, subjective conviction, or a complete all-time order archive. The official historical-orders endpoint is a recent-window source, so this snapshot cannot be treated as complete history.

## Boundary

No credentials, private endpoint, mainnet connection or order was used. Raw source files remain unchanged; the active Demo model remains unchanged and promotion is not allowed.
