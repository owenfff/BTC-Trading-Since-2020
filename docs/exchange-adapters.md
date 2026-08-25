# Exchange adapters

Adapters implement the exchange-neutral ports and normalize instruments, market data, balances, positions, orders, fills, and server time into domain objects.

BitMEX, Bybit, OKX and Binance use injected-transport mock paths for deterministic tests. Real private endpoints are credential-gated and are not exercised by the repository's offline smoke tests.

Current non-production connector status:

- `bybit-demo`: native REST/private WebSocket runtime is enabled for Demo Trading.
- `okx-demo`: native Demo REST signing, instrument discovery, account/position/order/fill mapping, order lifecycle and the unified REST-polling runtime are enabled.
- `binance-spot-testnet`: native Spot Testnet HMAC REST signing, instrument discovery, account/balance/order/fill mapping, order lifecycle and the unified REST-polling runtime are enabled behind an explicit Spot behavioral-approximation flag. Spot has no `reduceOnly` capability; sells are balance-driven and negative derivative targets are flattened rather than shorted.

All non-production endpoints are hard-pinned. A production URL or an untrusted endpoint is rejected before any request is made. Credentials are read locally only and are never placed in reports or source control.

The unified OKX/Binance runner uses REST polling for account reconciliation and closed-bar decisions. It does not claim private WebSocket parity with the existing Bybit Demo runner; the runtime state records `market_connection=REST_POLLING` so this operational boundary remains visible.
