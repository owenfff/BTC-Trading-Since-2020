from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from quant_bot.domain.events import DomainEvent, event_id
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar
from quant_bot.domain.risk import RiskConfig, RiskState
from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.config.loader import load_risk_config
from quant_bot.execution.planner import plan_delta
from quant_bot.monitoring.health import evaluate_health
from quant_bot.risk.pre_trade import pre_trade_check
from quant_bot.storage.event_store import InMemoryEventStore
from quant_bot.execution.idempotency import client_order_id
from quant_bot.execution.retry_policy import RetryAction, RetryContext, decide_retry
from quant_bot.execution.state_machine import OrderLifecycle, transition
from quant_bot.execution.order_manager import OrderManager
from quant_bot.execution.reconciliation import reconcile_positions
from quant_bot.execution.fill_tracker import FillTracker
from quant_bot.risk.circuit_breaker import CircuitBreaker
from quant_bot.risk.kill_switch import KillSwitch


def instrument() -> Instrument:
    return Instrument("xbtusd", InstrumentType.INVERSE_PERPETUAL, "XBT", "USD", "XBT", "0.1", "100", "100", "0")


def test_instrument_normalizes_canonical_symbol_price_and_quantity() -> None:
    item = instrument()
    assert item.canonical_symbol == "XBTUSD"
    assert item.normalize_price("100.19") == Decimal("100.1")
    assert item.normalize_quantity("199") == Decimal("100")


def test_market_data_requires_aware_utc_and_decimal_ohlc() -> None:
    bar = MarketBar("XBTUSD", datetime(2020, 1, 1, tzinfo=timezone.utc), "100", "101", "99", "100.5")
    assert bar.timestamp.tzinfo == timezone.utc
    assert bar.close == Decimal("100.5")


def test_event_id_and_store_are_idempotent() -> None:
    identifier = event_id("ORDER", "client-1", {"quantity": "1"})
    event = DomainEvent(identifier, "ORDER", datetime(2020, 1, 1, tzinfo=timezone.utc), "XBTUSD", {})
    store = InMemoryEventStore()
    assert store.append(event) is True
    assert store.append(event) is False
    assert len(store.all()) == 1


def test_planner_returns_delta_order_with_client_id() -> None:
    planned = plan_delta(instrument(), "client-1", Decimal("100"), Decimal("300"), price=Decimal("100.19"))
    assert planned is not None
    assert planned.quantity == Decimal("200")
    assert planned.price == Decimal("100.1")


def test_default_risk_blocks_all_live_activity() -> None:
    config = RiskConfig()
    state = RiskState()
    check = pre_trade_check(config, state, Decimal("0"), Decimal("0"), Decimal("0"))
    assert check.decision.value == "BLOCK"
    assert "LIVE_DISABLED" in check.reasons
    assert evaluate_health(state).status == "BLOCKED"


def test_risk_defaults_are_loaded_from_config() -> None:
    config = load_risk_config("quant_bot/config/safety_defaults.json")
    assert config.live_enabled is False
    assert config.maximum_live_risk == Decimal("0")


def test_timeout_requires_query_before_retry_and_id_is_deterministic() -> None:
    identifier = client_order_id("v1", "2020-01-01T00:00:00Z", "XBTUSD", "BUY", Decimal("100"))
    assert identifier == client_order_id("v1", "2020-01-01T00:00:00Z", "XBTUSD", "BUY", Decimal("100"))
    assert decide_retry(RetryContext(0, request_timed_out=True)) == RetryAction.QUERY_ORDER
    manager = OrderManager()
    order = Order(identifier, "XBTUSD", OrderSide.BUY, OrderType.MARKET, Decimal("100"), datetime(2020, 1, 1, tzinfo=timezone.utc))
    manager.register(order)
    manager.mark_submitted(identifier)
    assert manager.on_timeout(identifier) == RetryAction.QUERY_ORDER


def test_partial_fills_reconcile_and_guards() -> None:
    assert transition(OrderLifecycle.CREATED, OrderLifecycle.SUBMITTED) == OrderLifecycle.SUBMITTED
    assert reconcile_positions({"XBTUSD": Decimal("1")}, {"XBTUSD": Decimal("1")}).ok
    tracker = FillTracker()
    assert tracker.aggregate("missing").filled_quantity == Decimal("0")
    breaker = CircuitBreaker(failure_limit=2)
    breaker.record_failure(); breaker.record_failure()
    assert breaker.open
    switch = KillSwitch()
    try:
        switch.disengage(human_approved=False)
    except PermissionError:
        pass
    else:
        raise AssertionError("kill switch disengaged without approval")
