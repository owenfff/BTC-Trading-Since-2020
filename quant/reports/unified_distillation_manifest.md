# Unified Distillation v4.6 Manifest

- status: **CANDIDATE_PENDING_STRICT_AUTONOMOUS_AUDIT**
- model: `behavioral-distillation-v4.6-unified-distillation`
- feature contract: `m16-unified-cross-venue-distillation`
- raw rows: `32552`; fit rows: `31279`; ambiguous rows retained/excluded: `0`
- sources: `{'BITMEX': 32231, 'HYPERLIQUID': 321}`
- symbols: `67`
- dataset SHA256: `3db0b050ec3f4c5602cf3c682e1a5bd8a2c8bbff0a21c5f304e0bebfafbafc69`
- model SHA256: `695648b77b77e249afc3c6981dcea5ccf58c74a2861eb98db29eb13d8c9bb508`
- code commit: `9935af4ef37f1f9acb42beaef5f784ad74c1d449`
- frozen cutoff: `2026-07-18T21:17:31.514000Z`
- selected train-only threshold: `0.9`
- source venue is a balancing/reporting key, not a learned model feature
- Spot remains monitor-only
- current v3 Demo model was not changed

This artifact is a candidate only. Strict autonomous replay must pass before any Demo model switch.
