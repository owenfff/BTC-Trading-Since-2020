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
from quant_bot.risk.testnet_gate import check_testnet_order, risk_envelope_for_symbol
from quant_bot.strategy.deployment import DeploymentBundle, load_deployment_bundle
from quant_bot.strategy.realtime_features import RealtimeFeatureEngine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "quant" / "outputs" / "cross_asset_deployment_model.json"


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


def _instrument_status(instrument: Any) -> str:
    state = instrument.metadata.get("status") if hasattr(instrument, "metadata") else None
    return "ACTIVE" if state in (None, "Trading") else str(state).upper()


def build_symbol_mapping(bundle: DeploymentBundle, instruments: list[Any]) -> dict[str, Any]:
    by_symbol = {str(item.canonical_symbol): item for item in instruments}
    rows: list[dict[str, Any]] = []
    for symbol in bundle.symbols:
        policy = dict(bundle.symbol_policy.get(symbol, {}))
        instrument = by_symbol.get(symbol)
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
        rows.append({"symbol": symbol, "status": status, "bybit_symbol": symbol if instrument else None, "instrument_type": getattr(getattr(instrument, "instrument_type", None), "value", None), "settlement_currency": getattr(instrument, "settlement_currency", None), "contract_multiplier": getattr(instrument, "contract_multiplier", None), "tick_size": getattr(instrument, "tick_size", None), "lot_size": getattr(instrument, "lot_size", None)})
    return {"report_version": "BYBIT-DEMO-SYMBOL-MAPPING-1.0", "venue": "bybit-demo", "strategy_fidelity": "BEHAVIORAL_APPROXIMATION", "symbols": rows, "allowed_count": sum(row["status"] == "ALLOW_DERIVATIVE_TRADING" for row in rows), "monitor_only_count": sum(row["status"].startswith("MONITOR_ONLY") for row in rows), "blocked_count": sum(row["status"].startswith("BLOCKED") for row in rows), "unavailable_count": sum(row["status"].startswith("UNAVAILABLE") for row in rows)}


def preflight(*, artifact_path: Path = DEFAULT_ARTIFACT, write_reports: bool = True) -> dict[str, Any]:
    bundle = load_deployment_bundle(artifact_path)
    adapter = BybitAdapter.from_environment()
    instruments = adapter.load_all_instruments()
    mapping = build_symbol_mapping(bundle, instruments)
    server_time = adapter.get_server_time()
    clock_drift = (datetime.now(timezone.utc) - server_time).total_seconds()
    state = adapter.reconcile_state()
    if not state.get("ok"):
        raise AdapterError(adapter.name, "RECONCILIATION_NOT_OK", "Bybit Demo account state could not be reconciled")
    equity = adapter.fetch_equity()
    if equity <= 0:
        raise AdapterError(adapter.name, "EQUITY_UNRESOLVED", "Bybit Demo equity is zero or unavailable")
    result = {"status": "PASS", "venue": "bybit-demo", "model_version": bundle.model_version, "feature_contract_version": bundle.feature_contract_version, "instrument_count": len(instruments), "mapping": mapping, "equity_available": equity > 0, "clock_drift_seconds": clock_drift, "reconciliation_ok": True, "order_submission_performed": False, "private_websocket": "NOT_STARTED", "local_watchdog": "REQUIRED_FOR_RUN", "credentials": "READ_FROM_LOCAL_ENVIRONMENT_ONLY"}
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
    _async_stop: Any = field(default=None, init=False, repr=False)
    _async_loop: Any = field(default=None, init=False, repr=False)

    def refresh(self) -> Decimal:
        state = self.adapter.reconcile_state()
        self.reconciliation_ok = bool(state.get("ok"))
        self.positions = {item.symbol: item.quantity for item in state.get("positions", [])}
        self.active_orders = list(state.get("open_orders", []))
        return self.adapter.fetch_equity()

    def on_private_message(self, message: dict[str, Any]) -> None:
        self.websocket_connected = True
        self.ws_seen = True
        if message.get("success") is False or message.get("retCode") not in (None, 0, "0"):
            self.websocket_connected = False

    def start_private_stream(self) -> None:
        async def runner() -> None:
            stop = asyncio.Event()
            self._async_stop = stop
            self._async_loop = asyncio.get_running_loop()
            try:
                await self.adapter.stream_messages(stop, self.on_private_message)
            finally:
                self.websocket_connected = False

        def target() -> None:
            try:
                asyncio.run(runner())
            except (AdapterError, OSError):
                self.websocket_connected = False

        self.ws_thread = threading.Thread(target=target, name="bybit-demo-private-ws", daemon=True)
        self.ws_thread.start()

    def _watchdog(self) -> None:
        while not self.stop_event.wait(15):
            if self.ws_seen and not self.websocket_connected:
                self.cancel_created_orders()
                self.stop_event.set()
                break
            if time.monotonic() - self.last_loop_monotonic > 60:
                self.cancel_created_orders()
                self.stop_event.set()
                break

    def _plan_symbol(self, symbol: str, equity: Decimal) -> TargetOrderPlan | None:
        instrument = self.instruments[symbol]
        bars = self.adapter.fetch_closed_bars(symbol, limit=100)
        if not bars:
            return None
        engine = self.engines.setdefault(symbol, RealtimeFeatureEngine(instrument, position_scale=self.bundle.position_scales.get(symbol, 1.0)))
        engine.ingest_closed_bars(bars)
        latest = bars[-1]
        bid, ask = self.adapter.fetch_quote(symbol)
        decision_time = datetime.now(timezone.utc)
        strategy_input = engine.build_input(decision_time=decision_time, current_qty=self.positions.get(symbol, Decimal("0")), current_equity=equity)
        signal = self.bundle.model.predict(strategy_input)
        current = self.positions.get(symbol, Decimal("0"))
        limit = risk_envelope_for_symbol(self.bundle.risk_envelope, symbol)
        return plan_target_order(instrument, current_contracts=current, target_exposure=Decimal(str(signal.target_exposure)), equity=equity, reference_price=latest.close, bid=bid, ask=ask, decision_time=decision_time, active_orders=self.active_orders, max_target_exposure=limit)

    def process_once(self) -> dict[str, Any]:
        self.last_loop_monotonic = time.monotonic()
        equity = self.refresh()
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
        submitted: list[str] = []
        blocked: dict[str, list[str]] = {}
        for plan in plans:
            decision = check_testnet_order(enable_orders=self.enable_orders, confirm_testnet=self.confirm_testnet, symbol=plan.symbol, target_exposure=plan.target_exposure, total_target_exposure=total_target, envelope=self.bundle.risk_envelope, reconciliation_ok=self.reconciliation_ok, websocket_connected=self.websocket_connected, market_fresh=True, clock_drift_seconds=Decimal("0"))
            if not decision.allowed:
                blocked[plan.symbol] = list(decision.reasons)
                continue
            order = Order(plan.client_order_id, plan.symbol, plan.side, plan.order_type, plan.quantity, datetime.now(timezone.utc), price=plan.price, reduce_only=plan.reduce_only, post_only=plan.post_only)
            try:
                accepted = self.adapter.place_order(order)
            except AdapterError:
                self.consecutive_rejects += 1
                continue
            self.consecutive_rejects = 0
            self.created_order_ids.add(accepted.client_order_id)
            submitted.append(accepted.client_order_id)
        return {"status": "RUNNING", "equity": equity, "plans": len(plans), "submitted": submitted, "blocked": blocked, "websocket_connected": self.websocket_connected}

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
    instruments = {item.canonical_symbol: item for item in adapter.load_all_instruments()}
    mapping = build_symbol_mapping(bundle, list(instruments.values()))
    allowed = {row["symbol"] for row in mapping["symbols"] if row["status"] == "ALLOW_DERIVATIVE_TRADING"}
    selected = allowed if symbols == "auto" else allowed.intersection({item.strip().upper() for item in symbols.split(",") if item.strip()})
    runtime = TestnetRuntime(adapter, bundle, enable_orders, confirm_testnet, instruments={symbol: instruments[symbol] for symbol in selected})
    runtime.refresh()
    runtime.start_private_stream()
    watchdog = threading.Thread(target=runtime._watchdog, name="bybit-demo-local-watchdog", daemon=True)
    watchdog.start()
    last: dict[str, Any] = {"status": "STARTED", "selected_symbols": sorted(selected), "mapping": mapping}
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
    _write_json(ROOT / "quant" / "outputs" / "bybit_demo_runtime_state.json", last)
    return last


__all__ = ["DEFAULT_ARTIFACT", "TestnetRuntime", "build_symbol_mapping", "preflight", "run_foreground"]
