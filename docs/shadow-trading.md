# Shadow trading

Shadow mode runs the Strategy Core and risk gates without placing or simulating exchange orders. It is suitable for checking signal cadence, data freshness, deduplication, reconnect behavior, and observability.

The offline smoke path must remain credential-free and must keep live trading disabled.

