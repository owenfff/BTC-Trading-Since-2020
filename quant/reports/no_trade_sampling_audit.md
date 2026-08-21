# NO_TRADE / HOLD Sampling Audit

- total BTC decision rows: `20845`
- synthetic daily rows: `529`
- observed NO_TRADE/HOLD rows: `529`
- synthetic action distribution: `{'HOLD_LONG': 128, 'NO_TRADE': 117, 'HOLD_SHORT': 284}`
- time order: **chronological; no random shuffle**

Synthetic rows come from the frozen behavior dataset and are retained as explicit carry/no-trade observations. They are not silently treated as real fills.
