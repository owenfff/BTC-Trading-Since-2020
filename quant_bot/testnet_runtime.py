from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_bot.domain.order import Order
from quant_bot.exchanges.bybit import BybitAdapter
from quant_bot.exchanges.http import AdapterError
from quant_bot.execution.target_planner import TargetOrderPlan, plan_target_order
from quant_bot.risk.testnet_gate import check_testnet_order, portfolio_target_scale, risk_envelope_for_symbol
from quant_bot.strategy.deployment import DeploymentBundle, load_deployment_bundle
from quant_bot.strategy.realtime_features import RealtimeFeatureEngine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "quant" / "outputs" / "cross_asset_deployment_model.json"
VENUE_SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {"XBTUSD": ("BTCUSD",)}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")


def _public_account_snapshot(state: dict[str, Any], equity: Decimal) -> dict[str, Any]:
    """Build a dashboard-safe account snapshot without exchange raw payloads."""

    def iso(value: Any) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else str(value) if value is not None else None

    def balance_row(item: Any) -> dict[str, Any]:
        return {
            "currency": str(getattr(item, "currency", "")),
            "total": str(getattr(item, "total", Decimal("0"))),
            "available": str(getattr(item, "available", Decimal("0"))),
        }

    def position_row(item: Any) -> dict[str, Any]:
        return {
            "symbol": str(getattr(item, "symbol", "")),
            "settlement_currency": str(getattr(item, "settlement_currency", "")),
            "quantity": str(getattr(item, "quantity", Decimal("0"))),
            "average_entry_price": str(getattr(item, "average_entry_price", "")) if getattr(item, "average_entry_price", None) is not None else None,
            "realized_pnl": str(getattr(item, "realized_pnl", Decimal("0"))),
        }

    def order_row(item: Any) -> dict[str, Any]:
        return {
            "client_order_id": str(getattr(item, "client_order_id", "")),
            "exchange_order_id": str(getattr(item, "exchange_order_id", "")) if getattr(item, "exchange_order_id", None) else None,
            "symbol": str(getattr(item, "symbol", "")),
            "side": str(getattr(item, "side", "")),
            "status": str(getattr(item, "status", "")),
            "quantity": str(getattr(item, "quantity", Decimal("0"))),
            "price": str(getattr(item, "price", "")) if getattr(item, "price", None) is not None else None,
            "reduce_only": bool(getattr(item, "reduce_only", False)),
            "post_only": bool(getattr(item, "post_only", False)),
            "created_at": iso(getattr(item, "created_at", None)),
        }

    def fill_row(item: Any) -> dict[str, Any]:
        return {
            "event_id": str(getattr(item, "event_id", "")),
            "exchange_fill_id": str(getattr(item, "exchange_fill_id", "")) if getattr(item, "exchange_fill_id", None) else None,
            "client_order_id": str(getattr(item, "client_order_id", "")),
            "symbol": str(getattr(item, "symbol", "")),
            "side": str(getattr(item, "side", "")),
            "quantity": str(getattr(item, "quantity", Decimal("0"))),
            "price": str(getattr(item, "price", Decimal("0"))),
            "fee": str(getattr(item, "fee", Decimal("0"))),
            "fee_currency": str(getattr(item, "fee_currency", "")),
            "timestamp": iso(getattr(item, "timestamp", None)),
        }

    return {
        "equity": str(equity),
        "equity_unit": "USD_EQUIVALENT",
        "reconciliation_ok": bool(state.get("ok")),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "balances": [balance_row(item) for item in state.get("balances", [])],
        "positions": [position_row(item) for item in state.get("positions", [])],
        "open_orders": [order_row(item) for item in state.get("open_orders", [])],
        "recent_fills": [fill_row(item) for item in state.get("recent_fills", [])],
    }


def _instrument_status(instrument: Any) -> str:
    state = instrument.metadata.get("status") if hasattr(instrument, "metadata") else None
    return "ACTIVE" if state in (None, "Trading") else str(state).upper()


def _select_instrument(symbol: str, policy: dict[str, Any], instruments: list[Any]) -> tuple[Any | None, str | None]:
    candidates = [symbol, *VENUE_SYMBOL_ALIASES.get(symbol, ())]
    for candidate in candidates:
        matches = [item for item in instruments if item.canonical_symbol == candidate]
        if str(policy.get("instrument_class", "")).upper() != "SPOT":
            matches = [item for item in matches if item.instrument_type.value != "SPOT"]
        if matches:
            # Derivatives win over Spot for a derivative historical row. A
            # complete, currently trading specification wins over others.
            matches.sort(key=lambda item: (item.terms_complete, _instrument_status(item) == "ACTIVE", item.instrument_type.value != "SPOT"), reverse=True)
            return matches[0], candidate
    return None, None


def build_symbol_mapping(bundle: DeploymentBundle, instruments: list[Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for symbol in bundle.symbols:
        policy = dict(bundle.symbol_policy.get(symbol, {}))
        instrument, venue_symbol = _select_instrument(symbol, policy, instruments)
        if not instrument:
            status = "UNAVAILABLE_ON_BYBIT_DEMO"
        elif str(policy.get("instrument_class", "")).upper() == "SPOT" or str(getattr(instrument.instrument_type, "value", instrument.instrument_type)) == "SPOT":
            status = "MONITOR_ONLY_SPOT"
        elif _instrument_status(instrument) != "ACTIVE":
            status = "MONITOR_ONLY_NOT_TRADING"
        elif not instrument.terms_complete:
            status = "BLOCKED_SPEC_UNRESOLVED"
        else:
            status = "ALLOW_DERIVATIVE_TRADING"
        rows.append({"symbol": symbol, "status": status, "bybit_symbol": venue_symbol, "instrument_type": getattr(getattr(instrument, "instrument_type", None), "value", None), "settlement_currency": getattr(instrument, "settlement_currency", None), "contract_multiplier": getattr(instrument, "contract_multiplier", None), "tick_size": getattr(instrument, "tick_size", None), "lot_size": getattr(instrument, "lot_size", None), "mapping_reason": "EXACT_SYMBOL" if venue_symbol == symbol else "EXPLICIT_XBT_TO_BTC_ALIAS" if venue_symbol else None})
    return {"report_version": "BYBIT-DEMO-SYMBOL-MAPPING-1.0", "venue": "bybit-demo", "strategy_fidelity": "BEHAVIORAL_APPROXIMATION", "symbols": rows, "allowed_count": sum(row["status"] == "ALLOW_DERIVATIVE_TRADING" for row in rows), "monitor_only_count": sum(row["status"].startswith("MONITOR_ONLY") for row in rows), "blocked_count": sum(row["status"].startswith("BLOCKED") for row in rows), "unavailable_count": sum(row["status"].startswith("UNAVAILABLE") for row in rows)}


def preflight(*, artifact_path: Path = DEFAULT_ARTIFACT, write_reports: bool = True) -> dict[str, Any]:
    bundle = load_deployment_bundle(artifact_path)
    adapter = BybitAdapter.from_environment()
    instruments = adapter.load_all_instruments()
    mapping = build_symbol_mapping(bundle, instruments)
    if mapping["allowed_count"] <= 0:
        raise AdapterError("bybit-demo", "NO_TRADABLE_SYMBOLS", "no historical derivative symbol currently has a complete Bybit Demo mapping")
    server_time = adapter.get_server_time()
    clock_drift = (datetime.now(timezone.utc) - server_time).total_seconds()
    state = adapter.reconcile_state()
    if not state.get("ok"):
        raise AdapterError(adapter.name, "RECONCILIATION_NOT_OK", "Bybit Demo account state could not be reconciled")
    equity = adapter.fetch_equity()
    if equity <= 0:
        raise AdapterError(adapter.name, "EQUITY_UNRESOLVED", "Bybit Demo equity is zero or unavailable")
    result = {"status": "PASS", "venue": "bybit-demo", "model_version": bundle.model_version, "feature_contract_version": bundle.feature_contract_version, "instrument_count": len(instruments), "mapping": mapping, "equity_available": equity > 0, "clock_drift_seconds": clock_drift, "reconciliation_ok": True, "order_submission_performed": False, "private_websocket": "NOT_STARTED", "local_watchdog": "REQUIRED_FOR_RUN", "credentials": "READ_FROM_LOCAL_ENVIRONMENT_ONLY", "account": _public_account_snapshot(state, equity)}
    if write_reports:
        report_dir = ROOT / "quant" / "reports"
        _write_json(report_dir / "bybit_demo_symbol_mapping.json", mapping)
        (report_dir / "bybit_demo_symbol_mapping.md").write_text("\n".join(["# Bybit Demo Symbol Mapping", "", f"- allowed derivative symbols: `{mapping['allowed_count']}`", f"- monitor-only symbols: `{mapping['monitor_only_count']}`", f"- blocked symbols: `{mapping['blocked_count']}`", f"- unavailable symbols: `{mapping['unavailable_count']}`", "", "Spot and symbols without complete live specifications are never eligible for automatic orders."]) + "\n", encoding="utf-8")
        _write_json(ROOT / "quant" / "outputs" / "bybit_demo_preflight.json", result)
    return result


@dataclass
class TestnetRuntime:
    adapter: BybitAdapter
    bundle: DeploymentBundle
    enable_orders: bool
    confirm_testnet: bool
    created_order_ids: set[str] = field(default_factory=set)
    engines: dict[str, RealtimeFeatureEngine] = field(default_factory=dict)
    instruments: dict[str, Any] = field(default_factory=dict)
    positions: dict[str, Decimal] = field(default_factory=dict)
    active_orders: list[Order] = field(default_factory=list)
    reconciliation_ok: bool = False
    websocket_connected: bool = False
    consecutive_rejects: int = 0
    last_loop_monotonic: float = field(default_factory=time.monotonic)
    stop_event: threading.Event = field(default_factory=threading.Event)
    ws_thread: threading.Thread | None = None
    ws_seen: bool = False
    account_snapshot: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    websocket_error: str | None = None
    last_error: str | None = None
    portfolio_target_scale: Decimal = Decimal("1")
    poll_seconds: int = 60
    _async_stop: Any = field(default=None, init=False, repr=False)
    _async_loop: Any = field(default=None, init=False, repr=False)

    def refresh(self) -> Decimal:
        state = self.adapter.reconcile_state()
        self.reconciliation_ok = bool(state.get("ok"))
        self.positions = {item.symbol: item.quantity for item in state.get("positions", [])}
        self.active_orders = list(state.get("open_orders", []))
        equity = self.adapter.fetch_equity()
        self.account_snapshot = _public_account_snapshot(state, equity)
        self.last_error = None
        return equity

    def on_private_message(self, message: dict[str, Any]) -> None:
        self.websocket_connected = True
        self.ws_seen = True
        if message.get("success") is False or message.get("retCode") not in (None, 0, "0"):
            self.websocket_connected = False

    def on_private_error(self, error: BaseException) -> None:
        self.websocket_connected = False
        self.websocket_error = f"{type(error).__name__}: {str(error)[:160]}"

    def start_private_stream(self) -> None:
        async def runner() -> None:
            stop = asyncio.Event()
            self._async_stop = stop
            self._async_loop = asyncio.get_running_loop()
            try:
                await self.adapter.stream_messages(stop, self.on_private_message, self.on_private_error)
            finally:
                self.websocket_connected = False

        def target() -> None:
            try:
                asyncio.run(runner())
            except Exception as error:  # noqa: BLE001 - keep the main loop alive and record a safe diagnostic
                self.websocket_connected = False
                self.websocket_error = f"{type(error).__name__}: {str(error)[:160]}"

        self.ws_thread = threading.Thread(target=target, name="bybit-demo-private-ws", daemon=True)
        self.ws_thread.start()

    def _watchdog(self) -> None:
        while not self.stop_event.wait(15):
            if self.enable_orders and self.ws_seen and not self.websocket_connected:
                self.cancel_created_orders()
                self.stop_reason = "WEBSOCKET_DISCONNECTED"
                self.stop_event.set()
                break
            if time.monotonic() - self.last_loop_monotonic > max(90, self.poll_seconds * 2 + 30):
                self.cancel_created_orders()
                self.stop_reason = "WATCHDOG_TIMEOUT"
                self.stop_event.set()
                break

    def _plan_symbol(self, symbol: str, equity: Decimal) -> TargetOrderPlan | None:
        instrument = self.instruments[symbol]
        venue_symbol = instrument.canonical_symbol
        bars = self.adapter.fetch_closed_bars(venue_symbol, limit=100)
        if not bars:
            return None
        engine = self.engines.setdefault(symbol, RealtimeFeatureEngine(instrument, feature_symbol=symbol, position_scale=self.bundle.position_scales.get(symbol, 1.0)))
        engine.ingest_closed_bars(bars)
        latest = bars[-1]
        decision_time = datetime.now(timezone.utc)
        current = self.positions.get(venue_symbol, Decimal("0"))
        strategy_input = engine.build_input(decision_time=decision_time, current_qty=current, current_equity=equity)
        signal = self.bundle.model.predict(strategy_input)
        bid, ask = self.adapter.fetch_quote(venue_symbol)
        limit = risk_envelope_for_symbol(self.bundle.risk_envelope, symbol)
        return plan_target_order(instrument, current_contracts=current, target_exposure=Decimal(str(signal.target_exposure)), equity=equity, reference_price=latest.close, bid=bid, ask=ask, decision_time=decision_time, active_orders=self.active_orders, max_target_exposure=limit)

    def process_once(self) -> dict[str, Any]:
        self.last_loop_monotonic = time.monotonic()
        try:
            equity = self.refresh()
        except AdapterError as error:
            self.last_error = f"{error.code}: {error}"
            if self.enable_orders:
                self.cancel_created_orders()
                self.stop_reason = "ACCOUNT_REFRESH_FAILED"
                self.stop_event.set()
            result = {
                "status": "RUNNING_READ_ONLY" if not self.enable_orders else "BLOCKED",
                "equity": self.account_snapshot.get("equity"),
                "plans": 0,
                "submitted": [],
                "blocked": {"account_refresh": [error.code]},
                "websocket_connected": self.websocket_connected,
                "selected_symbols": sorted(self.instruments),
                "order_submission_enabled": self.enable_orders and self.confirm_testnet,
                "created_order_ids": sorted(self.created_order_ids),
                "account": self.account_snapshot,
                "stop_reason": self.stop_reason,
                "websocket_error": self.websocket_error,
                "last_error": self.last_error,
                "portfolio_target_scale": self.portfolio_target_scale,
            }
            _write_json(ROOT / "quant" / "outputs" / "bybit_demo_runtime_state.json", result)
            return result
        total_target = Decimal("0")
        plans: list[TargetOrderPlan] = []
        for symbol, instrument in self.instruments.items():
            if instrument.instrument_type.value == "SPOT" or not instrument.terms_complete:
                continue
            try:
                plan = self._plan_symbol(symbol, equity)
            except (AdapterError, ValueError, KeyError):
                continue
            if plan is None:
                continue
            total_target += abs(plan.target_exposure)
            plans.append(plan)
        total_limit = Decimal(str(self.bundle.risk_envelope.get("historical_simultaneous_total_exposure_cap", "0")))
        self.portfolio_target_scale = portfolio_target_scale(total_target, total_limit)
        if plans and self.portfolio_target_scale < Decimal("1"):
            scaled_plans: list[TargetOrderPlan] = []
            for plan in plans:
                instrument = next((item for item in self.instruments.values() if item.canonical_symbol == plan.symbol), None)
                historical_symbol = next((key for key, item in self.instruments.items() if item.canonical_symbol == plan.symbol), plan.symbol)
                if instrument is None or plan.reference_price is None or plan.bid is None or plan.ask is None:
                    continue
                scaled = plan_target_order(
                    instrument,
                    current_contracts=plan.current_contracts,
                    target_exposure=plan.target_exposure * self.portfolio_target_scale,
                    equity=equity,
                    reference_price=plan.reference_price,
                    bid=plan.bid,
                    ask=plan.ask,
                    decision_time=datetime.now(timezone.utc),
                    active_orders=self.active_orders,
                    max_target_exposure=risk_envelope_for_symbol(self.bundle.risk_envelope, historical_symbol),
                )
                if scaled is not None:
                    scaled_plans.append(scaled)
            plans = scaled_plans
            total_target = sum((abs(plan.target_exposure) for plan in plans), Decimal("0"))
        submitted: list[str] = []
        blocked: dict[str, list[str]] = {}
        order_errors: dict[str, str] = {}
        for plan in plans:
            historical_symbol = next((key for key, item in self.instruments.items() if item.canonical_symbol == plan.symbol), plan.symbol)
            decision = check_testnet_order(enable_orders=self.enable_orders, confirm_testnet=self.confirm_testnet, symbol=historical_symbol, target_exposure=plan.target_exposure, total_target_exposure=total_target, envelope=self.bundle.risk_envelope, reconciliation_ok=self.reconciliation_ok, websocket_connected=self.websocket_connected, market_fresh=True, clock_drift_seconds=Decimal("0"), consecutive_rejects=self.consecutive_rejects)
            if not decision.allowed:
                blocked[plan.symbol] = list(decision.reasons)
                continue
            order = Order(plan.client_order_id, plan.symbol, plan.side, plan.order_type, plan.quantity, datetime.now(timezone.utc), price=plan.price, reduce_only=plan.reduce_only, post_only=plan.post_only)
            try:
                accepted = self.adapter.place_order(order)
            except AdapterError as error:
                self.consecutive_rejects += 1
                order_errors[plan.symbol] = f"{error.code}: {error}"
                self.last_error = order_errors[plan.symbol]
                if self.consecutive_rejects >= 3:
                    self.cancel_created_orders()
                    self.stop_reason = "CONSECUTIVE_ORDER_REJECTS"
                    self.stop_event.set()
                    break
                continue
            self.consecutive_rejects = 0
            self.created_order_ids.add(accepted.client_order_id)
            submitted.append(accepted.client_order_id)
        result = {
            "status": "RUNNING" if self.enable_orders else "RUNNING_READ_ONLY",
            "equity": equity,
            "plans": len(plans),
            "submitted": submitted,
            "blocked": blocked,
            "websocket_connected": self.websocket_connected,
            "selected_symbols": sorted(self.instruments),
            "order_submission_enabled": self.enable_orders and self.confirm_testnet,
            "created_order_ids": sorted(self.created_order_ids),
            "account": self.account_snapshot,
            "stop_reason": self.stop_reason,
            "websocket_error": self.websocket_error,
            "last_error": self.last_error,
            "portfolio_target_scale": self.portfolio_target_scale,
            "order_errors": order_errors,
        }
        _write_json(ROOT / "quant" / "outputs" / "bybit_demo_runtime_state.json", result)
        return result

    def cancel_created_orders(self) -> None:
        for client_id in sorted(self.created_order_ids):
            try:
                self.adapter.cancel_order(client_id)
            except AdapterError:
                pass
        self.created_order_ids.clear()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.cancel_created_orders()
        if self._async_stop is not None and self._async_loop is not None:
            self._async_loop.call_soon_threadsafe(self._async_stop.set)
        if self.ws_thread is not None and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=2)
        self.adapter.disconnect()


def run_foreground(*, artifact_path: Path = DEFAULT_ARTIFACT, enable_orders: bool = False, confirm_testnet: bool = False, symbols: str = "auto", once: bool = False, poll_seconds: int = 60) -> dict[str, Any]:
    bundle = load_deployment_bundle(artifact_path)
    adapter = BybitAdapter.from_environment()
    live_instruments = adapter.load_all_instruments()
    mapping = build_symbol_mapping(bundle, live_instruments)
    allowed = {row["symbol"] for row in mapping["symbols"] if row["status"] == "ALLOW_DERIVATIVE_TRADING"}
    selected = allowed if symbols == "auto" else allowed.intersection({item.strip().upper() for item in symbols.split(",") if item.strip()})
    by_venue_symbol = {item.canonical_symbol: item for item in live_instruments}
    runtime = TestnetRuntime(adapter, bundle, enable_orders, confirm_testnet, instruments={symbol: by_venue_symbol[str(next(row["bybit_symbol"] for row in mapping["symbols"] if row["symbol"] == symbol))] for symbol in selected}, poll_seconds=max(5, poll_seconds))
    # The preflight connector is separate from the runtime connector. Sync the
    # runtime connector's signing clock before the first private request so a
    # local clock offset cannot trigger Bybit error 10002.
    adapter.get_server_time()
    runtime.refresh()
    runtime.start_private_stream()
    watchdog = threading.Thread(target=runtime._watchdog, name="bybit-demo-local-watchdog", daemon=True)
    watchdog.start()
    last: dict[str, Any] = {
        "status": "STARTED",
        "selected_symbols": sorted(selected),
        "mapping": mapping,
        "order_submission_enabled": enable_orders and confirm_testnet,
        "account": runtime.account_snapshot,
        "stop_reason": None,
        "websocket_error": runtime.websocket_error,
        "last_error": runtime.last_error,
        "portfolio_target_scale": runtime.portfolio_target_scale,
    }
    _write_json(ROOT / "quant" / "outputs" / "bybit_demo_runtime_state.json", last)
    try:
        while not runtime.stop_event.is_set():
            last = runtime.process_once()
            if once:
                break
            runtime.stop_event.wait(max(5, poll_seconds))
    except KeyboardInterrupt:
        last = {"status": "STOPPING", **last}
    finally:
        runtime.shutdown()
    if last.get("status") == "RUNNING_READ_ONLY":
        last["status"] = "STOPPED_READ_ONLY"
    elif last.get("status") == "RUNNING":
        last["status"] = "STOPPED"
    last["stop_reason"] = runtime.stop_reason
    last["websocket_error"] = runtime.websocket_error
    last["last_error"] = runtime.last_error
    _write_json(ROOT / "quant" / "outputs" / "bybit_demo_runtime_state.json", last)
    return last


__all__ = ["DEFAULT_ARTIFACT", "TestnetRuntime", "build_symbol_mapping", "preflight", "run_foreground"]
