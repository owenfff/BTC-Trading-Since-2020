# Historical Behavior Replay Dashboard

## Purpose

The dashboard now includes a three-layer historical replay inspired by the
reference panel at `paul.catseye.today`:

1. market context with 1-hour XBTUSD closes and historical order-episode lines;
2. position posture reconstructed from the order/accounting replay;
3. cumulative analytical realised result by closed trade cycle.

The time scrubber and play control move all three layers together and update a
time-point inspector. This is an observability and research surface; it is not
a claim of exact strategy recovery, live equity, or future profitability.

## Data boundary

- Market source: local `quant/outputs/market_bars_1h.csv`.
- Order source: local `quant/outputs/order_episodes.csv`.
- Position source: the `position_before` / `position_after` fields in the
  audited order episodes.
- Result source: local `quant/outputs/trade_cycles.csv` using
  `gross_pnl_analytical` at cycle close time.
- PnL scale: read from `quant/reports/currency_scale_coverage.csv`; XBT is
  displayed with scale 8 rather than as raw minimum units.
- No exchange credentials, private API, live orders, or synthetic market bars
  are used by this replay endpoint.

The lower chart is deliberately labelled **analytical realised PnL**. It is not
the same thing as a historical wallet equity curve, and it does not include a
live mark-to-market valuation.

## Runtime surface

The frontend exposes a compact endpoint:

```text
GET /api/replay?symbol=XBTUSD&limit=1000
```

The endpoint caches the local derived files in process memory and uniformly
downsamples the response while retaining the first and last points. Current
local data coverage is:

- 54,470 hourly bars;
- 20,316 order episodes;
- 687 trade-cycle result points.

## Verification

- `quant/tests/test_frontend_control.py`: 7 passed, including replay endpoint
  endpoint downsampling and missing-data behavior.
- `node --check frontend/app.js`: passed.
- Browser smoke: three canvases rendered, replay status `LOCAL REPLAY READY`,
  XBT scale label visible, and the existing read-only status/control surface
  remained available.

## Next extension

The current replay is intentionally XBTUSD-first. The next safe extension is
to expose additional symbols only after each symbol has a verified market
coverage state and currency-scale mapping; Spot records must remain separate
from leveraged derivative position semantics.
