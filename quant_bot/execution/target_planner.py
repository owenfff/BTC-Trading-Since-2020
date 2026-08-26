from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Iterable

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.order import OrderSide, OrderType


@dataclass(frozen=True)
class TargetOrderPlan:
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal
    reduce_only: bool
    post_only: bool
    target_exposure: Decimal
    target_contracts: Decimal
    current_contracts: Decimal
    reason: str
    reference_price: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    strategy_action: str = ""
    strategy_confidence: Decimal | None = None
    strategy_signal_timestamp: str = ""
    strategy_risk_tags: tuple[str, ...] = ()
    strategy_basis: tuple[str, ...] = ()
    strategy_source_symbols: tuple[str, ...] = ()
    strategy_source_signals: tuple[dict[str, Any], ...] = ()


def _signed_target_contracts(instrument: Instrument, target_exposure: Decimal, equity: Decimal, reference_price: Decimal) -> Decimal:
    if equity <= 0 or reference_price <= 0:
        raise ValueError("equity and reference price must be positive")
    target_notional = equity * target_exposure
    multiplier = instrument.contract_multiplier
    if instrument.instrument_type == InstrumentType.INVERSE_PERPETUAL:
        return target_notional / multiplier
    return target_notional / (reference_price * multiplier)


def _client_id(symbol: str, target: Decimal, current: Decimal, decision_time: datetime) -> str:
    stamp = decision_time.astimezone(timezone.utc).isoformat(timespec="seconds")
    digest = hashlib.sha256(f"{symbol}|{target}|{current}|{stamp}".encode()).hexdigest()[:20]
    return f"qbot-{digest}"


def plan_target_order(
    instrument: Instrument,
    *,
    current_contracts: Decimal,
    target_exposure: Decimal,
    equity: Decimal,
    reference_price: Decimal,
    bid: Decimal,
    ask: Decimal,
    decision_time: datetime,
    active_orders: Iterable[Any] = (),
    max_target_exposure: Decimal | None = None,
) -> TargetOrderPlan | None:
    if instrument.instrument_type == InstrumentType.SPOT:
        return None
    if not instrument.terms_complete:
        return None
    if max_target_exposure is not None:
        limit = abs(max_target_exposure)
        if limit <= 0:
            return None
        target_exposure = max(-limit, min(limit, target_exposure))
    if any(str(getattr(item, "symbol", "")).upper() == instrument.canonical_symbol for item in active_orders):
        return None
    target_contracts = _signed_target_contracts(instrument, target_exposure, equity, reference_price)
    delta = target_contracts - current_contracts
    quantity = instrument.normalize_quantity(delta)
    if quantity <= 0:
        return None
    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    reducing = current_contracts != 0 and ((current_contracts > 0 and side == OrderSide.SELL) or (current_contracts < 0 and side == OrderSide.BUY))
    # A flip is split into a ReduceOnly close/reduce first. The opening leg is
    # only created after the next remote reconciliation confirms the old side.
    if current_contracts != 0 and target_contracts != 0 and current_contracts * target_contracts < 0:
        quantity = instrument.normalize_quantity(current_contracts)
        reducing = True
        reason = "FLIP_REDUCE_FIRST"
    else:
        reason = "TARGET_DELTA"
    if quantity <= 0:
        return None
    quote = bid if side == OrderSide.BUY else ask
    if quote <= 0:
        return None
    price = instrument.normalize_price(quote)
    if price <= 0:
        return None
    return TargetOrderPlan(
        _client_id(instrument.canonical_symbol, target_contracts, current_contracts, decision_time), instrument.canonical_symbol,
        side, OrderType.LIMIT, quantity, price, reducing, not reducing, target_exposure, target_contracts, current_contracts, reason,
        reference_price, bid, ask,
    )


def plan_spot_order(
    instrument: Instrument,
    *,
    current_base_quantity: Decimal,
    target_exposure: Decimal,
    equity: Decimal,
    reference_price: Decimal,
    bid: Decimal,
    ask: Decimal,
    decision_time: datetime,
    active_orders: Iterable[Any] = (),
    max_target_exposure: Decimal | None = None,
) -> TargetOrderPlan | None:
    """Plan a cash-market order from the reconciled base-asset balance.

    Spot has no short position and no ``reduceOnly`` flag.  A negative
    behavioral target is therefore flattened to zero exposure rather than
    turned into an invalid short order.
    """

    if instrument.instrument_type != InstrumentType.SPOT or not instrument.terms_complete:
        return None
    if equity <= 0 or reference_price <= 0:
        return None
    if max_target_exposure is not None:
        limit = abs(max_target_exposure)
        if limit <= 0:
            return None
        target_exposure = max(Decimal("0"), min(limit, target_exposure))
    else:
        target_exposure = max(Decimal("0"), target_exposure)
    if any(str(getattr(item, "symbol", "")).upper() == instrument.canonical_symbol for item in active_orders):
        return None

    target_quantity = instrument.normalize_quantity((equity * target_exposure) / reference_price)
    current_quantity = max(Decimal("0"), current_base_quantity)
    delta = target_quantity - current_quantity
    quantity = instrument.normalize_quantity(delta)
    if quantity <= 0:
        return None
    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    quote = bid if side == OrderSide.BUY else ask
    price = instrument.normalize_price(quote)
    if price <= 0 or (instrument.minimum_notional > 0 and price * quantity < instrument.minimum_notional):
        return None
    return TargetOrderPlan(
        _client_id(instrument.canonical_symbol, target_quantity, current_quantity, decision_time),
        instrument.canonical_symbol,
        side,
        OrderType.LIMIT,
        quantity,
        price,
        False,
        True,
        target_exposure,
        target_quantity,
        current_quantity,
        "SPOT_TARGET_DELTA",
        reference_price,
        bid,
        ask,
    )


__all__ = ["TargetOrderPlan", "plan_spot_order", "plan_target_order"]
