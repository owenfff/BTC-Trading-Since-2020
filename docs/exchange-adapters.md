# Exchange adapters

Adapters implement the exchange-neutral ports and normalize instruments, market data, balances, positions, orders, fills, and server time into domain objects.

BitMEX and Bybit include injected-transport mock paths for deterministic tests. Real private endpoints are credential-gated and are not exercised by the repository's offline smoke tests. OKX and Binance remain interface-only until an explicit, separately reviewed adapter implementation is added.

