from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from quant_bot.domain.balance import Balance
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar, MarketContext, MarketQuote
from quant_bot.domain.order import Order, OrderSide, OrderStatus, OrderType
from quant_bot.domain.position import Position
from quant_bot.exchanges.http import AdapterError
from quant_bot.venue_runtime import VenueRuntime, _position_risk_metrics


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
        # Keep enough history for the feature engine while making the latest
        # closed bar recent enough for the strict runtime freshness gate.
        now = datetime.now(timezone.utc) - timedelta(hours=100)
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

    def fetch_market_context(self, symbol: str, *, bars: list[MarketBar] | None = None) -> MarketContext:
        assert symbol == "BTCUSDT"
        now = datetime.now(timezone.utc)
        latest = (bars or self.bars)[-1]
        return MarketContext(
            symbol,
            MarketQuote(symbol, "99.9", "100.1", now, "fixture-quote"),
            latest.timestamp + timedelta(hours=1),
            None,
            None,
            None,
            None,
            now,
            {"quote": "OK", "closed_bar": "OK", "funding": "MISSING", "mark_price": "MISSING", "index_price": "MISSING"},
        )

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


def test_runtime_rejects_unverified_or_future_market_context(tmp_path: Path) -> None:
    adapter = SimulatedAdapter()
    runtime = _runtime(tmp_path, adapter)
    now = datetime.now(timezone.utc)
    runtime.market_contexts["BTCUSDT"] = MarketContext(
        "BTCUSDT",
        MarketQuote("BTCUSDT", "99.9", "100.1", now, "fixture-quote"),
        now + timedelta(hours=1),
        None,
        None,
        None,
        None,
        now,
        {"quote": "OK", "closed_bar": "UNVERIFIED_ADAPTER_FALLBACK"},
    )
    assert runtime._market_fresh("BTCUSDT") is False

    runtime.market_contexts["BTCUSDT"] = MarketContext(
        "BTCUSDT",
        MarketQuote("BTCUSDT", "99.9", "100.1", now + timedelta(minutes=1), "fixture-quote"),
        now + timedelta(hours=1),
        None,
        None,
        None,
        None,
        now,
        {"quote": "OK", "closed_bar": "OK"},
    )
    assert runtime._market_fresh("BTCUSDT") is False


def test_runtime_persists_pre_action_context_before_order_submission(tmp_path: Path) -> None:
    adapter = SimulatedAdapter()
    runtime = _runtime(tmp_path, adapter)
    runtime.refresh()
    result = runtime.process_once()
    audit = result["behavior_state"]["decision_audit"]
    assert len(audit) == 1
    assert audit[0]["historical_symbol"] == "XBTUSD"
    assert audit[0]["venue_symbol"] == "BTCUSDT"
    assert audit[0]["pre_action"]["quote"]["bid"] == "99.9"
    assert audit[0]["pre_action"]["features"]["feature_latest_bar_time"]
    assert "secret" not in str(audit[0]).lower()
    journal_files = list((tmp_path / "decision_audit").glob("*.jsonl"))
    assert len(journal_files) == 1
    assert "secret" not in journal_files[0].read_text(encoding="utf-8").lower()


def test_runtime_restores_bounded_pre_action_context(tmp_path: Path) -> None:
    adapter = SimulatedAdapter()
    runtime = _runtime(tmp_path, adapter)
    runtime.decision_audit = [{"decision_time": str(index)} for index in range(6000)]
    runtime._result("RUNNING_READ_ONLY", Decimal("1000"), [], {})
    restored = _runtime(tmp_path, adapter)
    assert len(restored.decision_audit) == 5000
    assert restored.decision_audit[0]["decision_time"] == "1000"


def test_runtime_prefers_exchange_reported_position_risk_metrics() -> None:
    position = Position("BTCUSDT", "USDT", "2", "100", notional="250", margin_used="12")
    assert _position_risk_metrics([position]) == (Decimal("250"), Decimal("12"), "EXCHANGE_REPORTED", "EXCHANGE_REPORTED")


def test_runtime_keeps_order_visible_when_cancel_fails(tmp_path: Path) -> None:
    class FailingCancelAdapter(SimulatedAdapter):
        def cancel_order(self, client_order_id: str) -> object:
            raise AdapterError(self.name, "NETWORK", f"cannot cancel {client_order_id}")

    adapter = FailingCancelAdapter()
    runtime = _runtime(tmp_path, adapter)
    order = Order("qbot-stuck", "BTCUSDT", OrderSide.BUY, OrderType.LIMIT, Decimal("1"), datetime.now(timezone.utc), price=Decimal("100"), status=OrderStatus.OPEN)
    runtime.active_orders = [order]
    runtime.created_order_ids.add(order.client_order_id)
    runtime.cancel_created_orders()
    assert runtime.active_orders == [order]
    assert "BOT_ORDER_CANCEL_FAILED" in runtime.risk_state.block_reasons
