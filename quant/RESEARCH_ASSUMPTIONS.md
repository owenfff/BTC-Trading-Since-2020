# Research Assumptions

- The teacher dataset contains trade records, not the original decision logic; all learned behavior is an approximation.
- Root CSV/JSON files are frozen inputs and remain read-only.
- All timestamps are interpreted as UTC.
- Raw wallet and execution amounts are kept in integer units and converted with the frozen wallet-assets scale only when a major-unit view is requested.
- Different settlement currencies are never added without an explicit conversion source.
- Exchange-reported fields are evidence, not automatic analytical state transitions.
- Analytical currentCost/AEP residuals are preserved as confidence flags and are not hidden by tolerance.
- BTC-first modeling uses XBTUSD as the primary teacher market; altcoins remain diagnostic/generalization data.
- Market features must be closed-bar and as-of timestamp aligned; no future extrema or future labels may enter feature rows.
- No live trading or real-account connection is permitted in this program.
