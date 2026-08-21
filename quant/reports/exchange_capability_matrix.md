# Exchange Capability Matrix

Checked against official documentation on 2026-08-21. This is a documentation and interface milestone only; no adapter was connected and no credentials were requested.

| exchange | public REST | private REST | public WS | private WS | Demo/Testnet evidence | current implementation |
| --- | --- | --- | --- | --- | --- | --- |
| BitMEX | documented | documented | documented | documented | Testnet REST `https://testnet.bitmex.com/api/v1`, WS `wss://ws.testnet.bitmex.com/realtime` | mock adapter + public normalization; real credentials required |
| Bybit | documented | documented | documented in API family | documented in API family | Official API intro documents testnet endpoint `https://api-testnet.bybit.com` | mock adapter + public normalization; real credentials required |
| OKX | documented | documented | documented | documented | Official V5 docs document Demo Trading and `x-simulated-trading: 1` | interface only |
| Binance | documented | documented | product-specific | product-specific | Official developer docs state testnet/demo support varies by product | interface only |

## Official sources

- [BitMEX API overview](https://www.bitmex.com/app/apiOverview) and [BitMEX API/testnet support](https://support.bitmex.com/hc/en-gb/articles/6205448296605-Does-BitMEX-Have-An-API)
- [Bybit API introduction](https://bybit-exchange.github.io/docs/v3/intro)
- [OKX API guide and Demo Trading services](https://app.okx.com/docs-v5/en/)
- [Binance Developer Documentation — environments](https://developers.binance.com/en/docs/introduction)

## Boundary

The repository now exposes `ExchangeAdapter`, `ExchangeRegistry`, capability metadata, two injected-transport BitMEX/Bybit adapters, and a dependency-neutral CCXT normalization placeholder. Public normalization and private mock paths are tested; no real `connect`, authentication, market streaming, order submission, or account access was executed. Any future Demo/Testnet private integration requires credentials and separate human approval; the current status is `DEMO_CREDENTIALS_REQUIRED`.
