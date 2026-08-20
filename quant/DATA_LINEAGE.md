# Data Lineage

## Frozen teacher data

- Repository: `owenfff/BTC-Trading-Since-2020`
- Source commit recorded in `quant/SOURCE_VERSION.md`: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- Protected inputs: root order, execution, wallet history, position snapshot, wallet/margin snapshots, instrument, wallet-assets, equity curve, and manifest files.
- Protected-input SHA256 verification: PASS in M0-02B-1B-0.1.

## Derived lineage

- Position accounting code/report baseline: report commit `c3414514077ca81e9ddfacfd602704d9698a53dc`.
- Autonomous branch starts from that report commit: `quant/autonomous-behavioral-quant-bot-v1`.
- Raw execution counts: 173434 total, 173226 derivative, 160510 raw Trade, 160302 derivative Trade, 12905 Funding, 19 Settlement, 208 Spot Trade.
- Historical price audit: 5809 EXACT, 1425 RECOVERED, 0 UNRESOLVED among 7234 configured historical Trades.
- Large derived Parquet and event-level audit files are local ignored outputs and are never part of the source lineage commit.

## Accounting foundation artifact

- Code commit: `86be1f430ece5c64237b2dfc133842124119101c`
- Report commit: `f52ea4621b807a00f08dce805d7600a97f74a584`
- Manifest: `quant/reports/accounting_foundation_manifest.json`
- Status: `HIGH_CONFIDENCE_WITH_RESIDUALS` / `READY_WITH_KNOWN_ACCOUNTING_RESIDUALS`

## Upcoming lineage

Wallet ledger, public market data, behavioral episodes, features, labels, models, and experiments must each record source URLs/commits, UTC coverage, SHA256, code commit, dependency versions, and report analysis commit.
