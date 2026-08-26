# Public-Record Identifiability Ceiling Audit

> The conditional benchmark is an oracle-timing diagnostic, not a deployable strategy. It is compared with v4.3 strict autonomous timing on a separate final chronological slice.

| venue | train event rows | untouched event rows | conditional action F1 | autonomous timing F1 | gap |
|---|---:|---:|---:|---:|---:|
| `BITMEX` | 8006 | 2923 | 0.382047 | 0.000000 | 0.382047 |
| `HYPERLIQUID` | 117 | 25 | 0.585714 | 0.000000 | 0.585714 |

## Interpretation

A large conditional/autonomous gap means the public record contains information about the type or size of an action once an event is known, but does not identify when the action should be initiated. This is a direct limitation on autonomous imitation, not evidence that the original trader used a particular indicator.

## Boundary

No credentials, private endpoint, mainnet connection, or order was used. Historical state is explicitly allowed only in this conditional diagnostic; it is forbidden in the strict autonomous path. The active Demo model remains unchanged.
