# External Hyperliquid Public Source Audit

- Status: **PASS**
- Website snapshot synced at: `2026-08-26T02:36:52.694Z`
- Source repository: `pystashell/track_paul_btc_hyperliquid_trade`
- Source revision: `ace13c7a675a20d4932b430508a750d7ad7867e9`
- Target wallet: `0xdae4df7207feb3b350e4284c8efe5f7dac37f637`
- Model inclusion: **normalized-only after cross-venue audit** (raw source remains separate)

## Coverage

- Historical order events / unique order IDs: 2649 / 1343
- Fills: 341
- Funding records / total USDC: 2794 / -1797.581080
- Aligned state checkpoints: {'frontendOpenOrders': 35, 'clearinghouseState': 35, 'spotClearinghouseState': 35}
- Latest public open orders: 14

## Replayed behavior

- Fill window: `1763228044580` → `1787159312600` (Unix ms)
- Terminal position: `1.33557 BTC`
- Maximum absolute position: `2.07997 BTC`
- Action counts: `{'OPEN_LONG': 1, 'ADD_LONG': 137, 'REDUCE_LONG': 160, 'FLIP_SHORT': 5, 'REDUCE_SHORT': 19, 'FLIP_LONG': 5, 'ADD_SHORT': 14}`

## Independent behavior profile

The following metrics are derived from the public order and fill events. They are descriptive observations, not recovered private rules and not training labels.

- Orders ever observed with a filled event: `203` / `1343` (`0.15115413`)
- Orders ever observed with a canceled event: `1126` / `1343` (`0.83842144`)
- Order shape: all Limit=`True`, all GTC=`True`, reduce-only events=`0`
- Order lifetime median / P90 / max: `34217187` / `731958204` / `4507194070` ms
- Fill crossed fraction: `0.16129032` (55 / 341)
- Gross fill size / notional: `17.46305 BTC` / `1349380.273090 USDC`
- Reported fees / fee rate on gross notional: `268.845116 USDC` / `1.99235991 bps`
- Fill latency median / P90 / max: `50008004` / `642635108` / `2474916638` ms
- Position episodes: `11` total, `10` closed, `1` open at end
- Episode sides: `6` long / `5` short
- Episode duration median / max: `903551733` / `8243746527` ms
- Fills per episode median: `12`

## Latest state

- Perpetual account value: `65257.650336 USDC`
- Total perpetual notional: `105248.25828 USDC`
- Signed notional / account value: `1.612811030401730583081347920`
- BTC position: `1.33557`; entry: `64249.1`; unrealised: `19439.049134`

## Why this source matters

The site demonstrates a reproducible public-account pipeline: pin the source revision and file hashes, preserve raw events, keep daily state checkpoints, collapse orders by lifecycle, replay fills into position, normalize funding aggregation, and only then derive leverage/PnL timelines.

This report is a source-quality audit. It does not claim that the Hyperliquid trader and the BitMEX teacher used the same strategy; normalized behavior rows are eligible for the separate cross-venue experiment only after its own leakage, cost and strict-autonomous gates.

## Version boundary

The website's published snapshot is treated as its own data version. A separate checkout of the same-named GitHub revision may contain different data-file bytes; if a comparison is supplied, those differences are retained here rather than silently merged.


## Limitations

- This is a separate Hyperliquid trader reference, not the BitMEX teacher account.
- It is not mixed into the current behavioral-distillation model.
- Website portfolio values are derived from snapshots, fills, funding and public candles; they are not imported as labels.
- Public data availability and the source-manifest revision must be rechecked before any future refresh.
