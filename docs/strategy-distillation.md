# Strategy distillation

The Strategy Core is exchange-neutral. It consumes the leakage-safe feature contract and prior state, then emits a versioned signal contract with target exposure, action, confidence, validity, slippage, execution preference, and risk tags.

The current models are behavioral approximations evaluated on chronological splits. They are not claims of exact trader intent and they do not submit orders or import exchange SDKs.

