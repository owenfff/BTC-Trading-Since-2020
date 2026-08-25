from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from quant_bot.domain.balance import Balance
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar
from quant_bot.domain.order import Order, OrderSide, OrderStatus, OrderType
from quant_bot.domain.position import Position
from quant_bot.venue_runtime import VenueRuntime


class SimulatedSignalModel:
    def __init__(self, target: str = "0.25") -> None:
        self.target = Decimal(target)

    def predict(self, _strategy_input: object) -> SimpleNamespace:
        return SimpleNamespace(target_exposure=self.target)


class SimulatedBundle:
    model = SimulatedSignalModel()
    position_scales = {"XBTUSD": 1.0}
    risk_envelope = {
        "per_symbol_target_exposure": {"XBTUSD": {"p99_abs_target_exposure": "0.5"}},
        "historical_simultaneous_total_exposure_cap": "1.0",
    }


class SimulatedAdapter:
    name = "okx-demo"

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        now = datetime.now(timezone.utc) - timedelta(hours=110)
        self.bars = [MarketBar("BTCUSDT", now + timedelta(hours=index), "100", "101", "99", "100", "10", source="fixture") for index in range(100)]
        self.place_calls = 0

    def reconcile_state(self) -> dict[str, object]:
        return {
            "ok": True,
            "balances": [Balance("USDT", "1000", "1000")],
            "positions": [],
            "open_orders": list(self.orders.values()),
            "recent_fills": [],
        }

    def fetch_equity(self) -> Decimal:
        return Decimal("1000")

    def fetch_closed_bars(self, symbol: str, *, limit: int = 100) -> list[MarketBar]:
        assert symbol == "BTCUSDT"
        return self.bars[-limit:]

    def fetch_quote(self, symbol: str) -> tuple[Decimal, Decimal]:
        assert symbol == "BTCUSDT"
        return Decimal("99.9"), Decimal("100.1")

    def place_order(self, order: Order) -> Order:
        self.place_calls += 1
        accepted = Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, f"exchange-{self.place_calls}")
        self.orders[accepted.client_order_id] = accepted
        return accepted

    def cancel_order(self, client_order_id: str) -> object:
        self.orders.pop(client_order_id, None)
        return {"ok": True}


def _runtime(tmp_path: Path, adapter: SimulatedAdapter) -> VenueRuntime:
    instrument = Instrument("BTCUSDT", InstrumentType.LINEAR_PERPETUAL, "BTC", "USDT", "USDT", "0.1", "1", "1", "0", contract_multiplier="1")
    return VenueRuntime(adapter, "okx-demo", SimulatedBundle(), True, True, False, {"XBTUSD": instrument}, tmp_path / "runtime.json")


def test_runtime_submits_once_and_restart_reconciles_existing_order(tmp_path: Path) -> None:
    adapter = SimulatedAdapter()
    first = _runtime(tmp_path, adapter)
    first.refresh()
    result = first.process_once()
    assert result["status"] == "RUNNING"
    assert len(result["submitted"]) == 1
    assert adapter.place_calls == 1

    # A second loop and a fresh runtime both see the remote active order and
    # must not submit a duplicate client order.
    assert first.process_once()["submitted"] == []
    restarted = _runtime(tmp_path, adapter)
    restarted.refresh()
    assert restarted.process_once()["submitted"] == []
    assert adapter.place_calls == 1


def test_runtime_cancels_created_order_on_shutdown(tmp_path: Path) -> None:
    adapter = SimulatedAdapter()
    runtime = _runtime(tmp_path, adapter)
    runtime.refresh()
    result = runtime.process_once()
    assert result["submitted"]
    runtime.shutdown()
    assert adapter.orders == {}


def test_runtime_blocks_order_when_private_stream_is_unhealthy(tmp_path: Path) -> None:
    adapter = SimulatedAdapter()
    runtime = _runtime(tmp_path, adapter)
    runtime.private_stream_available = True
    runtime.private_stream_seen = True
    runtime.market_connected = False
    runtime.refresh()
    result = runtime.process_once()
    assert result["submitted"] == []
    assert result["blocked"]["XBTUSD"] == ["WEBSOCKET_NOT_CONNECTED"]
