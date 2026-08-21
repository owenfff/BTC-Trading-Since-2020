# Cross-Asset Behavior Universe

- symbols: `66`
- decision rows: `32231`
- analysis commit: `07f5304e0101852538d52914927f11ef7e8d01ee`
- strategy fidelity: **BEHAVIORAL_APPROXIMATION**
- raw account inputs unchanged: `True`

The inventory includes every symbol present in the behavior decision export. Position scales are fitted from chronological TRAIN rows only. Spot and derivative semantics remain explicitly separated.

Market coverage is sourced from public, no-key BitMEX market endpoints at hourly resolution. No synthetic bars are generated; symbols with insufficient or failed coverage remain outside model eligibility and are listed in the JSON/CSV reports.
