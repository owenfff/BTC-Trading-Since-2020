from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal
from typing import Any

from quant_bot.domain.risk import RiskConfig


DECIMAL_FIELDS = {
    "maximum_live_risk", "maximum_live_notional", "max_order_notional", "max_symbol_exposure",
    "max_total_exposure", "max_leverage", "max_daily_loss", "max_drawdown",
}


def load_risk_config(path: str | Path) -> RiskConfig:
    values: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    for field in DECIMAL_FIELDS:
        values[field] = Decimal(str(values.get(field, "0")))
    return RiskConfig(**values)
