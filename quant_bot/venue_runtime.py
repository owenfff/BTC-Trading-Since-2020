from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.order import Order
from quant_bot.exchanges.binance import BinanceSpotAdapter
from quant_bot.exchanges.http import AdapterError
from quant_bot.exchanges.okx import OKXAdapter
from quant_bot.execution.target_planner import TargetOrderPlan, plan_spot_order, plan_target_order
from quant_bot.risk.testnet_gate import check_testnet_order, portfolio_target_scale, risk_envelope_for_symbol
from quant_bot.strategy.deployment import DeploymentBundle, load_deployment_bundle
from quant_bot.strategy.realtime_features import RealtimeFeatureEngine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "quant" / "outputs" / "cross_asset_deployment_model.json"
ALLOWED_MAPPING_STATUSES = {"ALLOW_DERIVATIVE_TRADING", "ALLOW_SPOT_BEHAVIOR_APPROXIMATION"}


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


def _instrument_status(instrument: Instrument) -> str:
    raw = instrument.metadata.get("status", instrument.metadata.get("state", "ACTIVE"))
    normalized = str(raw or "ACTIVE").upper()
    return "ACTIVE" if normalized in {"ACTIVE", "TRADING", "LIVE", "PREOPEN"} else normalized


def _base_from_history(symbol: str) -> str | None:
    value = str(symbol).upper().replace("-", "")
    if value.startswith("XBT"):
        return "BTC"
    for suffix in ("USDT", "USDC", "USD"):
        if value.endswith(suffix) and len(value) > len(suffix):
            base = value[: -len(suffix)]
            # Old quarterly BitMEX contracts must not be silently converted
            # into a current spot or perpetual instrument.
            if re.search(r"[HMUZ]\d{1,2}$", base):
                return None
            return base
    return None


def _candidate_symbols(venue: str, historical_symbol: str, requested_class: str) -> tuple[str, ...]:
    base = _base_from_history(historical_symbol)
    if not base:
        return ()
    if venue == "okx-demo":
        if requested_class == "SPOT":
            return (f"{base}-USDT", f"{base}-USDC")
        return (f"{base}-USDT-SWAP", f"{base}-USDC-SWAP", f"{base}-USD-SWAP")
    if venue == "binance-spot-testnet":
        return (f"{base}USDT", f"{base}USDC", f"{base}USD")
    return ()


def _find_instrument(venue: str, historical_symbol: str, policy: dict[str, Any], instruments: list[Instrument]) -> tuple[Instrument | None, str | None, str | None]:
    requested_class = str(policy.get("instrument_class", "DERIVATIVE")).upper()
    exact = [item for item in instruments if item.canonical_symbol == historical_symbol]
    candidates = exact + [item for item in instruments if item.canonical_symbol in _candidate_symbols(venue, historical_symbol, requested_class)]
    if requested_class != "SPOT":
        derivatives = [item for item in candidates if item.instrument_type != InstrumentType.SPOT]
        if derivatives:
            candidates = derivatives
        elif venue == "binance-spot-testnet":
            # This is an explicit cross-market approximation, never an
            # implicit derivative-to-spot substitution.
            candidates = [item for item in candidates if item.instrument_type == InstrumentType.SPOT]
            requested_class = "SPOT_APPROXIMATION"
    candidates = [item for item in candidates if item.terms_complete and _instrument_status(item) == "ACTIVE"]
    if not candidates:
        return None, None, None
    selected = sorted(candidates, key=lambda item: (item.instrument_type != InstrumentType.SPOT, item.canonical_symbol), reverse=True)[0]
    return selected, selected.canonical_symbol, requested_class


def build_venue_symbol_mapping(bundle: DeploymentBundle, venue: str, instruments: list[Instrument]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for historical_symbol in bundle.symbols:
        policy = dict(bundle.symbol_policy.get(historical_symbol, {}))
        instrument, venue_symbol, mapped_class = _find_instrument(venue, historical_symbol, policy, instruments)
        if instrument is None:
            status = "UNAVAILABLE_ON_VENUE"
        elif instrument.instrument_type == InstrumentType.SPOT and mapped_class != "SPOT_APPROXIMATION":
            status = "MONITOR_ONLY_SPOT"
        elif instrument.instrument_type == InstrumentType.SPOT:
            status = "ALLOW_SPOT_BEHAVIOR_APPROXIMATION"
        else:
            status = "ALLOW_DERIVATIVE_TRADING"
        rows.append({
            "historical_symbol": historical_symbol,
            "venue_symbol": venue_symbol,
            "status": status,
            "instrument_type": instrument.instrument_type.value if instrument else None,
            "base_currency": instrument.base_currency if instrument else None,
            "quote_currency": instrument.quote_currency if instrument else None,
            "settlement_currency": instrument.settlement_currency if instrument else None,
            "contract_multiplier": instrument.contract_multiplier if instrument else None,
            "tick_size": instrument.tick_size if instrument else None,
            "lot_size": instrument.lot_size if instrument else None,
            "mapping_reason": "EXACT_SYMBOL" if venue_symbol == historical_symbol else "BASE_QUOTE_BEHAVIORAL_CROSSWALK" if venue_symbol else None,
        })
    return {
        "report_version": "MULTIVENUE-SYMBOL-MAPPING-1.0",
        "venue": venue,
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "symbols": rows,
        "allowed_count": sum(row["status"] in ALLOWED_MAPPING_STATUSES for row in rows),
        "derivative_allowed_count": sum(row["status"] == "ALLOW_DERIVATIVE_TRADING" for row in rows),
        "spot_approximation_count": sum(row["status"] == "ALLOW_SPOT_BEHAVIOR_APPROXIMATION" for row in rows),
        "unavailable_count": sum(row["status"] == "UNAVAILABLE_ON_VENUE" for row in rows),
    }


def _snapshot(state: dict[str, Any], equity: Decimal, *, equity_unit: str) -> dict[str, Any]:
    def as_text(item: Any, name: str, default: Any = None) -> Any:
        value = getattr(item, name, default)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    return {
        "equity": str(equity),
        "equity_unit": equity_unit,
        "reconciliation_ok": bool(state.get("ok")),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "balances": [{"currency": as_text(item, "currency", ""), "total": as_text(item, "total", "0"), "available": as_text(item, "available", "0")} for item in state.get("balances", [])],
        "positions": [{"symbol": as_text(item, "symbol", ""), "settlement_currency": as_text(item, "settlement_currency", ""), "quantity": as_text(item, "quantity", "0"), "average_entry_price": as_text(item, "average_entry_price"), "realized_pnl": as_text(item, "realized_pnl", "0")} for item in state.get("positions", [])],
        "open_orders": [{"client_order_id": as_text(item, "client_order_id", ""), "exchange_order_id": as_text(item, "exchange_order_id"), "symbol": as_text(item, "symbol", ""), "side": as_text(item, "side", ""), "status": as_text(item, "status", ""), "quantity": as_text(item, "quantity", "0"), "price": as_text(item, "price"), "reduce_only": bool(getattr(item, "reduce_only", False)), "post_only": bool(getattr(item, "post_only", False))} for item in state.get("open_orders", [])],
        "recent_fills": [{"event_id": as_text(item, "event_id", ""), "exchange_fill_id": as_text(item, "exchange_fill_id"), "client_order_id": as_text(item, "client_order_id", ""), "symbol": as_text(item, "symbol", ""), "side": as_text(item, "side", ""), "quantity": as_text(item, "quantity", "0"), "price": as_text(item, "price", "0"), "fee": as_text(item, "fee", "0"), "fee_currency": as_text(item, "fee_currency", ""), "timestamp": as_text(item, "timestamp")} for item in state.get("recent_fills", [])],
    }


@dataclass
class VenueRuntime:
    adapter: Any
    venue: str
    bundle: DeploymentBundle
    enable_orders: bool
    confirm_testnet: bool
    allow_spot_approximation: bool
    instruments: dict[str, Instrument]
    output_path: Path
    poll_seconds: int = 60
    created_order_ids: set[str] = field(default_factory=set)
    engines: dict[str, RealtimeFeatureEngine] = field(default_factory=dict)
    positions: dict[str, Decimal] = field(default_factory=dict)
    balances: dict[str, Decimal] = field(default_factory=dict)
    active_orders: list[Order] = field(default_factory=list)
    account_snapshot: dict[str, Any] = field(default_factory=dict)
    reconciliation_ok: bool = False
    market_connected: bool = True
    private_stream_available: bool = False
    private_stream_seen: bool = False
    private_stream_error: str | None = None
    ws_thread: threading.Thread | None = None
    _async_stop: asyncio.Event | None = field(default=None, init=False, repr=False)
    _async_loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    consecutive_rejects: int = 0
    last_error: str | None = None
    stop_reason: str | None = None
    portfolio_target_scale: Decimal = Decimal("1")
    stop_event: threading.Event = field(default_factory=threading.Event)
    last_loop_monotonic: float = field(default_factory=time.monotonic)

    @property
    def equity_unit(self) -> str:
        return "USDT_EQUIVALENT" if self.venue == "binance-spot-testnet" else "USD_EQUIVALENT"

    def refresh(self) -> Decimal:
        state = self.adapter.reconcile_state()
        self.reconciliation_ok = bool(state.get("ok"))
        self.positions = {str(item.symbol): Decimal(str(item.quantity)) for item in state.get("positions", [])}
        self.active_orders = list(state.get("open_orders", []))
        self.balances = {str(item.currency).upper(): Decimal(str(item.available)) for item in state.get("balances", [])}
        equity = self.adapter.fetch_equity()
        self.account_snapshot = _snapshot(state, equity, equity_unit=self.equity_unit)
        self.last_error = None
        return equity

    def _spot_quantity(self, instrument: Instrument) -> Decimal:
        return self.balances.get(instrument.base_currency.upper(), Decimal("0"))

    def on_private_message(self, message: dict[str, Any]) -> None:
        self.private_stream_seen = True
        self.market_connected = not (message.get("success") is False or str(message.get("code", "0")) not in {"0", ""})

    def on_private_error(self, error: BaseException) -> None:
        self.market_connected = False
        self.private_stream_error = f"{type(error).__name__}: {str(error)[:160]}"

    def start_private_stream(self) -> None:
        if not hasattr(self.adapter, "stream_messages"):
            self.private_stream_available = False
            return
        self.private_stream_available = True
        if self.enable_orders:
            self.market_connected = False

        async def runner() -> None:
            stop = asyncio.Event()
            self._async_stop = stop
            self._async_loop = asyncio.get_running_loop()
            try:
                await self.adapter.stream_messages(stop, self.on_private_message, self.on_private_error)
            finally:
                self.market_connected = False if self.enable_orders else self.market_connected

        def target() -> None:
            try:
                asyncio.run(runner())
            except Exception as error:  # noqa: BLE001 - preserve a safe runtime diagnostic
                self.on_private_error(error)

        self.ws_thread = threading.Thread(target=target, name=f"{self.venue}-private-ws", daemon=True)
        self.ws_thread.start()

    def _watchdog(self) -> None:
        while not self.stop_event.wait(15):
            if self.enable_orders and self.private_stream_available and self.private_stream_seen and not self.market_connected:
                self.cancel_created_orders()
                self.stop_reason = "PRIVATE_WEBSOCKET_DISCONNECTED"
                self.stop_event.set()
                break
            if time.monotonic() - self.last_loop_monotonic > max(90, self.poll_seconds * 2 + 30):
                self.cancel_created_orders()
                self.stop_reason = "WATCHDOG_TIMEOUT"
                self.stop_event.set()
                break

    def _plan_symbol(self, historical_symbol: str, instrument: Instrument, equity: Decimal) -> TargetOrderPlan | None:
        venue_symbol = instrument.canonical_symbol
        bars = self.adapter.fetch_closed_bars(venue_symbol, limit=100)
        if not bars:
            return None
        engine = self.engines.setdefault(historical_symbol, RealtimeFeatureEngine(instrument, feature_symbol=historical_symbol, position_scale=self.bundle.position_scales.get(historical_symbol, 1.0)))
        engine.ingest_closed_bars(bars)
        latest = bars[-1]
        decision_time = datetime.now(timezone.utc)
        current = self._spot_quantity(instrument) if instrument.instrument_type == InstrumentType.SPOT else self.positions.get(venue_symbol, Decimal("0"))
        strategy_input = engine.build_input(decision_time=decision_time, current_qty=current, current_equity=equity)
        signal = self.bundle.model.predict(strategy_input)
        bid, ask = self.adapter.fetch_quote(venue_symbol)
        limit = risk_envelope_for_symbol(self.bundle.risk_envelope, historical_symbol)
        if instrument.instrument_type == InstrumentType.SPOT:
            if not self.allow_spot_approximation:
                return None
            return plan_spot_order(instrument, current_base_quantity=current, target_exposure=Decimal(str(signal.target_exposure)), equity=equity, reference_price=latest.close, bid=bid, ask=ask, decision_time=decision_time, active_orders=self.active_orders, max_target_exposure=limit)
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
            return self._result("BLOCKED" if self.enable_orders else "RUNNING_READ_ONLY", Decimal("0"), [], {"account_refresh": [error.code]})

        plans: list[TargetOrderPlan] = []
        blocked: dict[str, list[str]] = {}
        for historical_symbol, instrument in self.instruments.items():
            if instrument.instrument_type == InstrumentType.SPOT and not self.allow_spot_approximation:
                blocked[historical_symbol] = ["SPOT_APPROXIMATION_DISABLED"]
                continue
            try:
                plan = self._plan_symbol(historical_symbol, instrument, equity)
            except (AdapterError, KeyError, ValueError) as error:
                blocked[historical_symbol] = [getattr(error, "code", type(error).__name__)]
                continue
            if plan is not None:
                plans.append(plan)

        total_target = sum((abs(item.target_exposure) for item in plans), Decimal("0"))
        total_limit = Decimal(str(self.bundle.risk_envelope.get("historical_simultaneous_total_exposure_cap", "0")))
        self.portfolio_target_scale = portfolio_target_scale(total_target, total_limit)
        if plans and self.portfolio_target_scale < Decimal("1"):
            # Recompute each delta with the same cap applied to the behavioral
            # target.  This keeps the cap enforceable after aggregation.
            scaled: list[TargetOrderPlan] = []
            for plan in plans:
                historical_symbol = next((key for key, item in self.instruments.items() if item.canonical_symbol == plan.symbol), plan.symbol)
                instrument = self.instruments[historical_symbol]
                target = plan.target_exposure * self.portfolio_target_scale
                if instrument.instrument_type == InstrumentType.SPOT:
                    rebuilt = plan_spot_order(instrument, current_base_quantity=plan.current_contracts, target_exposure=target, equity=equity, reference_price=plan.reference_price or Decimal("0"), bid=plan.bid or Decimal("0"), ask=plan.ask or Decimal("0"), decision_time=datetime.now(timezone.utc), active_orders=self.active_orders, max_target_exposure=risk_envelope_for_symbol(self.bundle.risk_envelope, historical_symbol))
                else:
                    rebuilt = plan_target_order(instrument, current_contracts=plan.current_contracts, target_exposure=target, equity=equity, reference_price=plan.reference_price or Decimal("0"), bid=plan.bid or Decimal("0"), ask=plan.ask or Decimal("0"), decision_time=datetime.now(timezone.utc), active_orders=self.active_orders, max_target_exposure=risk_envelope_for_symbol(self.bundle.risk_envelope, historical_symbol))
                if rebuilt is not None:
                    scaled.append(rebuilt)
            plans = scaled
            total_target = sum((abs(item.target_exposure) for item in plans), Decimal("0"))

        submitted: list[str] = []
        order_errors: dict[str, str] = {}
        for plan in plans:
            historical_symbol = next((key for key, item in self.instruments.items() if item.canonical_symbol == plan.symbol), plan.symbol)
            decision = check_testnet_order(enable_orders=self.enable_orders, confirm_testnet=self.confirm_testnet, symbol=historical_symbol, target_exposure=plan.target_exposure, total_target_exposure=total_target, envelope=self.bundle.risk_envelope, reconciliation_ok=self.reconciliation_ok, websocket_connected=self.market_connected, market_fresh=True, clock_drift_seconds=Decimal("0"), consecutive_rejects=self.consecutive_rejects)
            if not decision.allowed:
                blocked[historical_symbol] = list(decision.reasons)
                continue
            order = Order(plan.client_order_id, plan.symbol, plan.side, plan.order_type, plan.quantity, datetime.now(timezone.utc), price=plan.price, reduce_only=plan.reduce_only, post_only=plan.post_only)
            try:
                accepted = self.adapter.place_order(order)
            except AdapterError as error:
                self.consecutive_rejects += 1
                order_errors[historical_symbol] = f"{error.code}: {error}"
                if self.consecutive_rejects >= 3:
                    self.cancel_created_orders()
                    self.stop_reason = "CONSECUTIVE_ORDER_REJECTS"
                    self.stop_event.set()
                continue
            self.consecutive_rejects = 0
            self.created_order_ids.add(accepted.client_order_id)
            submitted.append(accepted.client_order_id)
        return self._result("RUNNING" if self.enable_orders else "RUNNING_READ_ONLY", equity, plans, blocked, submitted, order_errors)

    def _result(self, status: str, equity: Decimal, plans: list[TargetOrderPlan], blocked: dict[str, list[str]], submitted: list[str] | None = None, order_errors: dict[str, str] | None = None) -> dict[str, Any]:
        result = {"status": status, "venue": self.venue, "equity": equity, "plans": len(plans), "submitted": submitted or [], "blocked": blocked, "market_connection": "PRIVATE_WEBSOCKET" if self.private_stream_available else "REST_POLLING", "market_connected": self.market_connected, "private_stream_seen": self.private_stream_seen, "private_stream_error": self.private_stream_error, "order_submission_enabled": self.enable_orders and self.confirm_testnet, "created_order_ids": sorted(self.created_order_ids), "account": self.account_snapshot, "stop_reason": self.stop_reason, "last_error": self.last_error, "portfolio_target_scale": self.portfolio_target_scale, "order_errors": order_errors or {}, "strategy_fidelity": "BEHAVIORAL_APPROXIMATION"}
        _write_json(self.output_path, result)
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
        if self._async_stop is not None and self._async_loop is not None:
            self._async_loop.call_soon_threadsafe(self._async_stop.set)
        if self.ws_thread is not None and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=2)
        self.cancel_created_orders()
        if hasattr(self.adapter, "disconnect"):
            self.adapter.disconnect()


def _adapter_for(venue: str) -> tuple[Any, Path]:
    if venue == "okx-demo":
        return OKXAdapter.from_environment(), ROOT / "quant" / "outputs" / "okx_demo_runtime_state.json"
    if venue == "binance-spot-testnet":
        return BinanceSpotAdapter.from_environment(), ROOT / "quant" / "outputs" / "binance_spot_testnet_runtime_state.json"
    raise AdapterError(venue, "UNSUPPORTED_VENUE", f"unsupported unified runtime venue: {venue}")


def run_foreground_venue(*, venue: str, artifact_path: Path = DEFAULT_ARTIFACT, enable_orders: bool = False, confirm_testnet: bool = False, symbols: str = "auto", once: bool = False, poll_seconds: int = 60, allow_spot_approximation: bool = False) -> dict[str, Any]:
    bundle = load_deployment_bundle(artifact_path)
    adapter, output_path = _adapter_for(venue)
    live_instruments = adapter.load_all_instruments()
    mapping = build_venue_symbol_mapping(bundle, venue, live_instruments)
    _write_json(ROOT / "quant" / "reports" / f"{venue.replace('-', '_')}_symbol_mapping.json", mapping)
    if mapping["allowed_count"] <= 0:
        raise AdapterError(venue, "NO_TRADABLE_SYMBOLS", "no historical symbol currently has a complete venue mapping")
    allowed_rows = [row for row in mapping["symbols"] if row["status"] in ALLOWED_MAPPING_STATUSES]
    if symbols != "auto":
        requested = {item.strip().upper() for item in symbols.split(",") if item.strip()}
        allowed_rows = [row for row in allowed_rows if row["historical_symbol"] in requested]
    if not allow_spot_approximation:
        allowed_rows = [row for row in allowed_rows if row["status"] != "ALLOW_SPOT_BEHAVIOR_APPROXIMATION"]
    by_venue_symbol = {item.canonical_symbol: item for item in live_instruments}
    selected = {row["historical_symbol"]: by_venue_symbol[row["venue_symbol"]] for row in allowed_rows if row["venue_symbol"] in by_venue_symbol}
    if not selected:
        raise AdapterError(venue, "NO_SELECTED_SYMBOLS", "no selected symbols remain after the Spot/derivative safety boundary")
    if hasattr(adapter, "set_tracked_symbols"):
        adapter.set_tracked_symbols(tuple(item.canonical_symbol for item in selected.values()))
    adapter.get_server_time()
    runtime = VenueRuntime(adapter, venue, bundle, enable_orders, confirm_testnet, allow_spot_approximation, selected, output_path, max(5, poll_seconds))
    runtime.start_private_stream()
    watchdog = threading.Thread(target=runtime._watchdog, name=f"{venue}-watchdog", daemon=True)
    watchdog.start()
    equity = runtime.refresh()
    last = runtime._result("STARTED", equity, [], {}, [])
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
    _write_json(output_path, last)
    return last


__all__ = ["ALLOWED_MAPPING_STATUSES", "DEFAULT_ARTIFACT", "VenueRuntime", "build_venue_symbol_mapping", "run_foreground_venue"]
