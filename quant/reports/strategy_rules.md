# Behavioral strategy rules and deployment boundary

## Conclusion first

The repository has learned a reproducible trading-behavior approximation. It
has not recovered the original trader's private decision rules and it does not
provide a profitability guarantee.

The live Demo/Testnet runner loads the frozen
`behavioral-distillation-v2-cross-asset-deploy` artifact. The small rules below
are the auditable baseline used for comparison; they are not silently mixed
into the deployed NumPy cross-asset model.

## Evidence boundary

- 173,434 historical execution rows were preserved.
- 160,302 derivative trade fills were used in the behavior layers.
- 32,231 decision episodes cover 66 historical symbols.
- Spot records remain separate from leveraged derivative position semantics.
- Inputs are `TRADE_RECORDS_ONLY`; observed future actions and `label_*` fields
  are not runtime features.
- Runtime features use only closed 1-hour bars and account state available at
  the decision timestamp.

## Auditable deterministic baseline

The `behavioral-distillation-v1-rules` baseline follows this decision tree:

1. If the required return/slope features or the market regime are unavailable,
   preserve the current normalized exposure and emit `HOLD_*` or `NO_TRADE`.
2. Mark an environment as bullish when the 24-bar trend slope and 24-bar
   return are positive, or the regime is an uptrend. Mark it bearish using the
   symmetric negative condition.
3. When flat, open long in a bullish environment or short in a bearish one.
   Initial exposure is scaled by the absolute 24-bar return and capped at
   `0.25` normalized exposure.
4. When long, close a small long at or below `0.05` exposure if bearish; reduce
   a larger long by half. In a bullish environment, add up to `0.25` exposure
   while below `0.20`; otherwise hold.
5. When short, apply the symmetric close/reduce/add/hold logic.
6. High realized volatility adds a risk tag and reduces confidence. Missing
   mark/index context, low accounting confidence, and insufficient history are
   explicit risk tags rather than hidden imputations.

## Deployed cross-asset model

The deployed model is deterministic NumPy multiclass logistic imitation plus a
linear target-exposure regression. It uses the frozen feature encoder and
outputs the shared Signal Contract: action, target exposure, confidence,
valid-until, execution preference, and risk tags.

M13 time-out-of-sample diagnostics for the cross-asset logistic model were:

| Metric | Result |
|---|---:|
| action accuracy | 0.6492 |
| action macro-F1 | 0.1759 |
| target exposure MAE | 0.0633 |
| target exposure correlation | 0.8835 |
| add recall | 0.8824 |
| reduce recall | 0.6547 |
| flip recall | 0.0000 |
| cycle direction match | 0.9448 |

The low macro-F1 and zero flip recall are material limitations. The bot must
therefore be described as a behavioral approximation, not a precise replica.

## Execution translation

- A target exposure is converted to a venue-specific contract quantity using
  the current equity, price, tick, lot, and contract multiplier.
- Only the difference between current remote position and target position is
  submitted.
- A reversal is split into a reduce-only close first; the opening leg waits for
  a later reconciliation.
- Passive limit/PostOnly orders are preferred; risk-reduction orders are not
  marked PostOnly.
- Historical P99 per-symbol and simultaneous portfolio exposure caps remain
  active.
- OKX SWAP uses derivative position semantics.
- Binance Spot uses available base-asset balances, cannot short, and requires
  an explicit Spot behavioral-approximation flag. Negative targets flatten the
  balance instead of creating a short.

## What the model does not know

The source records do not prove private news inputs, discretionary intent,
unobserved cancellations, hidden risk limits, or the original trader's exact
entry/exit rationale. Current-cost and AEP residuals, ambiguous execution
ordering, missing historical mark/index context, and insufficient per-symbol
market coverage remain visible in the research reports.

## Operational status

The code can run in OKX Demo and Binance Spot Testnet modes after local
credential-gated preflight. No mainnet URL, live credential, or real order is
enabled by this report. Actual Testnet order lifecycle and long-duration
reconnect tests must be verified on the user's local Demo/Testnet account
before any claim beyond non-production readiness.
