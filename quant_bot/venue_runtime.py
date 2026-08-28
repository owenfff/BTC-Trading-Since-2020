from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketContext, MarketQuote
from quant_bot.domain.order import Order
from quant_bot.decision_audit_journal import DecisionAuditJournal, DecisionAuditJournalError
from quant_bot.exchanges.binance import BinanceSpotAdapter
from quant_bot.exchanges.binance_futures import BinanceFuturesAdapter
from quant_bot.exchanges.http import AdapterError
from quant_bot.exchanges.okx import OKXAdapter
from quant_bot.execution.aggregation import merge_duplicate_target_plans
from quant_bot.execution.target_planner import TargetOrderPlan, plan_spot_order, plan_target_order
from quant_bot.risk.testnet_gate import check_testnet_order, portfolio_target_scale, risk_envelope_for_symbol
from quant_bot.risk.runtime_risk import RuntimeRiskState
from quant_bot.strategy.deployment import DeploymentBundle, load_deployment_bundle
from quant_bot.strategy.explanations import strategy_basis_from_features, strategy_reason_zh
from quant_bot.strategy.feature_contract import LEGACY_FEATURE_CONTRACT_VERSION
from quant_bot.strategy.realtime_features import RealtimeFeatureEngine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v3.json"
KILL_SWITCH_PATH = ROOT / "quant" / "outputs" / "okx_demo_kill_switch.json"
ALLOWED_MAPPING_STATUSES = {"ALLOW_DERIVATIVE_TRADING", "ALLOW_SPOT_BEHAVIOR_APPROXIMATION"}
MAX_ACTIVE_ORDER_AGE_SECONDS = 15 * 60
MAX_LEVERAGE = Decimal("2")
REQUIRED_MARGIN_MODE = "isolated"
MAX_DECISION_AUDIT_ROWS = 5000


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


def _audit_value(value: Any) -> Any:
    """Convert a prospective decision value to a credential-free JSON scalar."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _audit_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_audit_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _audit_value(value.item())
        except Exception:  # noqa: BLE001 - diagnostics must never stop the loop
            pass
    return str(value)


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
    if venue == "binance-futures-testnet":
        return (f"{base}USDT",)
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


def _snapshot(state: dict[str, Any], equity: Decimal, *, equity_unit: str, order_context: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    context_by_order = order_context or {}

    def as_text(item: Any, name: str, default: Any = None) -> Any:
        value = getattr(item, name, default)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def strategy_fields(item: Any) -> dict[str, Any]:
        client_id = as_text(item, "client_order_id", "")
        metadata = getattr(item, "metadata", {}) or {}
        context = context_by_order.get(str(client_id), {}) or metadata.get("strategy_context", {}) or {}
        return {
            "strategy_action": context.get("strategy_action"),
            "strategy_reason": context.get("strategy_reason"),
            "strategy_confidence": context.get("strategy_confidence"),
            "strategy_target_exposure": context.get("strategy_target_exposure"),
            "strategy_current_contracts": context.get("strategy_current_contracts"),
            "strategy_target_contracts": context.get("strategy_target_contracts"),
            "strategy_signal_timestamp": context.get("strategy_signal_timestamp"),
            "strategy_risk_tags": context.get("strategy_risk_tags", []),
            "strategy_basis": context.get("strategy_basis", []),
            "strategy_reason_zh": context.get("strategy_reason_zh", ""),
            "strategy_source_symbols": context.get("strategy_source_symbols", []),
            "strategy_source_signals": context.get("strategy_source_signals", []),
        }

    return {
        "equity": str(equity),
        "equity_unit": equity_unit,
        "reconciliation_ok": bool(state.get("ok")),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "balances": [{"currency": as_text(item, "currency", ""), "total": as_text(item, "total", "0"), "available": as_text(item, "available", "0")} for item in state.get("balances", [])],
        "positions": [{"symbol": as_text(item, "symbol", ""), "settlement_currency": as_text(item, "settlement_currency", ""), "quantity": as_text(item, "quantity", "0"), "average_entry_price": as_text(item, "average_entry_price"), "mark_price": as_text(item, "mark_price"), "realized_pnl": as_text(item, "realized_pnl", "0"), "unrealized_pnl": as_text(item, "unrealized_pnl"), "leverage": as_text(item, "leverage"), "margin_mode": as_text(item, "margin_mode"), "notional": as_text(item, "notional"), "margin_used": as_text(item, "margin_used")} for item in state.get("positions", [])],
        "open_orders": [{"client_order_id": as_text(item, "client_order_id", ""), "exchange_order_id": as_text(item, "exchange_order_id"), "symbol": as_text(item, "symbol", ""), "side": as_text(item, "side", ""), "status": as_text(item, "status", ""), "quantity": as_text(item, "quantity", "0"), "price": as_text(item, "price"), "reduce_only": bool(getattr(item, "reduce_only", False)), "post_only": bool(getattr(item, "post_only", False)), **strategy_fields(item)} for item in state.get("open_orders", [])],
        "recent_fills": [{"event_id": as_text(item, "event_id", ""), "exchange_fill_id": as_text(item, "exchange_fill_id"), "client_order_id": as_text(item, "client_order_id", ""), "symbol": as_text(item, "symbol", ""), "side": as_text(item, "side", ""), "quantity": as_text(item, "quantity", "0"), "price": as_text(item, "price", "0"), "fee": as_text(item, "fee", "0"), "fee_currency": as_text(item, "fee_currency", ""), "timestamp": as_text(item, "timestamp"), **strategy_fields(item)} for item in state.get("recent_fills", [])],
    }


def _position_risk_metrics(positions: list[Any]) -> tuple[Decimal, Decimal, str, str]:
    """Prefer exchange-reported notional/margin and label fallbacks explicitly."""

    total_notional = Decimal("0")
    margin_used = Decimal("0")
    notional_sources: set[str] = set()
    margin_sources: set[str] = set()
    for item in positions:
        reported_notional = getattr(item, "notional", None)
        if reported_notional is not None and Decimal(str(reported_notional)) > 0:
            total_notional += abs(Decimal(str(reported_notional)))
            notional_sources.add("EXCHANGE_REPORTED")
        else:
            quantity = abs(Decimal(str(getattr(item, "quantity", "0"))))
            entry = abs(Decimal(str(getattr(item, "average_entry_price", "0") or "0")))
            total_notional += quantity * entry
            notional_sources.add("FALLBACK_QTY_X_ENTRY")
        reported_margin = getattr(item, "margin_used", None)
        if reported_margin is not None:
            margin_used += abs(Decimal(str(reported_margin)))
            margin_sources.add("EXCHANGE_REPORTED")
        else:
            margin_sources.add("UNAVAILABLE")
    return (
        total_notional,
        margin_used,
        "+".join(sorted(notional_sources)) if notional_sources else "NO_OPEN_POSITIONS",
        "+".join(sorted(margin_sources)) if margin_sources else "NO_OPEN_POSITIONS",
    )


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
    order_context: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    seen_fill_ids: set[str] = field(default_factory=set)
    behavior_state_bootstrapped: bool = False
    persisted_engine_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    realized_pnl_by_symbol: dict[str, Decimal] = field(default_factory=dict)
    market_contexts: dict[str, MarketContext] = field(default_factory=dict)
    risk_state: RuntimeRiskState = field(default_factory=RuntimeRiskState)
    clock_drift_seconds: Decimal = Decimal("0")
    latest_feedback_at: str | None = None
    orphans_checked: bool = False
    decision_audit: list[dict[str, Any]] = field(default_factory=list)
    latest_signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    risk_metrics: dict[str, str] = field(default_factory=dict)
    decision_journal: DecisionAuditJournal = field(init=False, repr=False)
    _result_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _last_result: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.decision_journal = DecisionAuditJournal(self.output_path.parent / "decision_audit")
        self._restore_runtime_state()
        if KILL_SWITCH_PATH.exists():
            self.risk_state.engage_kill_switch()

    def _restore_runtime_state(self) -> None:
        if not self.output_path.exists():
            return
        try:
            payload = json.loads(self.output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        behavior = payload.get("behavior_state", {}) if isinstance(payload, dict) else {}
        self.seen_fill_ids = {str(item) for item in behavior.get("seen_fill_ids", []) if str(item)}
        self.persisted_engine_state = {str(key): dict(value) for key, value in dict(behavior.get("engine_state", {})).items() if isinstance(value, dict)}
        try:
            self.realized_pnl_by_symbol = {str(key): Decimal(str(value)) for key, value in dict(behavior.get("realized_pnl_by_symbol", {})).items()}
        except (InvalidOperation, TypeError, ValueError):
            self.realized_pnl_by_symbol = {}
        self.order_context.update({str(key): dict(value) for key, value in dict(behavior.get("order_context", {})).items() if isinstance(value, dict)})
        self.behavior_state_bootstrapped = bool(behavior.get("bootstrapped", False))
        self.decision_audit = [dict(item) for item in behavior.get("decision_audit", []) if isinstance(item, dict)][-MAX_DECISION_AUDIT_ROWS:]
        self.risk_state.restore(payload.get("risk"))

    def _engine_for(self, historical_symbol: str) -> RealtimeFeatureEngine:
        instrument = self.instruments[historical_symbol]
        engine = self.engines.get(historical_symbol)
        if engine is None:
            engine = RealtimeFeatureEngine(instrument, feature_symbol=historical_symbol, position_scale=self.bundle.position_scales.get(historical_symbol, 1.0), feature_contract_version=getattr(self.bundle, "feature_contract_version", LEGACY_FEATURE_CONTRACT_VERSION))
            if historical_symbol in self.persisted_engine_state:
                engine.restore(self.persisted_engine_state[historical_symbol])
            self.engines[historical_symbol] = engine
        return engine

    def _historical_sources_for_venue(self, venue_symbol: str) -> list[str]:
        return [symbol for symbol, instrument in self.instruments.items() if instrument.canonical_symbol == venue_symbol]

    @staticmethod
    def _fill_action(previous: Decimal, signed_quantity: Decimal, current: Decimal) -> str:
        direction = "LONG" if (signed_quantity > 0 or current > 0) else "SHORT"
        if previous == 0:
            return f"OPEN_{direction}"
        if current == 0:
            return "CLOSE"
        if (previous > 0 > current) or (previous < 0 < current):
            return f"FLIP_{direction}"
        if (previous > 0 and signed_quantity > 0) or (previous < 0 and signed_quantity < 0):
            return f"ADD_{direction}"
        return f"REDUCE_{'LONG' if previous > 0 else 'SHORT'}"

    def _record_fills(self, fills: list[Any], previous_positions: dict[str, Decimal], new_positions: dict[str, Decimal], previous_realized: dict[str, Decimal], new_realized: dict[str, Decimal]) -> None:
        unseen_by_symbol: dict[str, int] = {}
        for fill in fills:
            event_id = str(getattr(fill, "event_id", "") or getattr(fill, "exchange_fill_id", ""))
            if event_id and event_id not in self.seen_fill_ids:
                symbol = str(getattr(fill, "symbol", ""))
                unseen_by_symbol[symbol] = unseen_by_symbol.get(symbol, 0) + 1
        # Reconstruct the position cursor in fill order.  The exchange
        # snapshot contains only the final quantity for this refresh; using
        # that final value for every fill mislabels a multi-fill transition
        # (for example OPEN + ADD) and poisons the next decision features.
        position_cursor = {str(symbol): Decimal(str(quantity)) for symbol, quantity in previous_positions.items()}
        for fill in sorted(fills, key=lambda item: getattr(item, "timestamp", datetime.min.replace(tzinfo=timezone.utc))):
            event_id = str(getattr(fill, "event_id", "") or getattr(fill, "exchange_fill_id", ""))
            if not event_id or event_id in self.seen_fill_ids:
                continue
            symbol = str(getattr(fill, "symbol", ""))
            signed = Decimal(str(getattr(fill, "quantity", "0")))
            if str(getattr(getattr(fill, "side", None), "value", getattr(fill, "side", ""))).upper() == "SELL":
                signed = -abs(signed)
            else:
                signed = abs(signed)
            previous = position_cursor.get(symbol, previous_positions.get(symbol, Decimal("0")))
            current = previous + signed
            position_cursor[symbol] = current
            action = self._fill_action(previous, signed, current)
            sources = list((self.order_context.get(str(getattr(fill, "client_order_id", "")), {}) or {}).get("strategy_source_symbols", []))
            if not sources:
                sources = self._historical_sources_for_venue(symbol)
            if not sources:
                self.seen_fill_ids.add(event_id)
                continue
            confidence = "HIGH" if len(sources) == 1 and str(getattr(fill, "client_order_id", "")) in self.order_context else "LOW_CONFIDENCE"
            realized_delta = new_realized.get(symbol, Decimal("0")) - previous_realized.get(symbol, Decimal("0"))
            if unseen_by_symbol.get(symbol, 0) > 1:
                realized_delta /= Decimal(str(unseen_by_symbol[symbol]))
            fee = Decimal(str(getattr(fill, "fee", "0")))
            for source in sources:
                engine = self._engine_for(source)
                share = Decimal("1") / Decimal(str(len(sources)))
                engine.record_action(
                    action,
                    realised_outcome=float(realized_delta * share),
                    fee=float(fee * share),
                    timestamp=getattr(fill, "timestamp", None),
                    current_position=current,
                )
                if confidence != "HIGH":
                    engine.latest_market_context_status = {**engine.latest_market_context_status, "behavior_source": "LOW_CONFIDENCE"}
            timestamp = getattr(fill, "timestamp", None)
            self.latest_feedback_at = timestamp.isoformat() if isinstance(timestamp, datetime) else datetime.now(timezone.utc).isoformat()
            self.seen_fill_ids.add(event_id)
        if len(self.seen_fill_ids) > 2000:
            self.seen_fill_ids = set(sorted(self.seen_fill_ids)[-2000:])
        self.behavior_state_bootstrapped = True

    @property
    def equity_unit(self) -> str:
        return "USDT_EQUIVALENT" if self.venue in {"binance-spot-testnet", "binance-futures-testnet"} else "USD_EQUIVALENT"

    def refresh(self) -> Decimal:
        state = self.adapter.reconcile_state()
        self.reconciliation_ok = bool(state.get("ok"))
        previous_positions = dict(self.positions)
        previous_realized = dict(self.realized_pnl_by_symbol)
        next_positions = {str(item.symbol): Decimal(str(item.quantity)) for item in state.get("positions", [])}
        next_realized: dict[str, Decimal] = {}
        for item in state.get("positions", []):
            next_realized[str(item.symbol)] = Decimal(str(getattr(item, "realized_pnl", "0")))
        self._record_fills(list(state.get("recent_fills", [])), previous_positions, next_positions, previous_realized, next_realized)
        self.realized_pnl_by_symbol = next_realized
        self.positions = next_positions
        self.active_orders = list(state.get("open_orders", []))
        self.balances = {str(item.currency).upper(): Decimal(str(item.available)) for item in state.get("balances", [])}
        equity = self.adapter.fetch_equity()
        position_rows = list(state.get("positions", []))
        total_notional, margin_used, notional_source, margin_source = _position_risk_metrics(position_rows)
        self.risk_metrics = {"notional_source": notional_source, "margin_source": margin_source}
        self.risk_state.update(equity, total_notional=total_notional, margin_used=margin_used)
        if self.risk_state.block_reasons and self.enable_orders:
            self._engage_safety(self.risk_state.block_reasons[0])
        self._discover_and_cancel_orphans()
        self.account_snapshot = _snapshot(state, equity, equity_unit=self.equity_unit, order_context=self.order_context)
        self.last_error = None
        return equity

    def _is_bot_order(self, order: Order) -> bool:
        client_id = str(getattr(order, "client_order_id", ""))
        return client_id.lower().startswith(("qbot", "qbotv31"))

    def _discover_and_cancel_orphans(self) -> None:
        owned = [order for order in self.active_orders if self._is_bot_order(order)]
        self.created_order_ids.update(str(order.client_order_id) for order in owned)
        if not self.enable_orders or self.orphans_checked:
            return
        # On restart every remote bot order is an orphan until the next signal
        # explicitly recreates it. A persisted order context proves that this
        # process can resume the order idempotently; human/other-strategy
        # orders are untouched.
        orphans = [order for order in owned if str(order.client_order_id) not in self.order_context]
        canceled_ids: set[str] = set()
        for order in orphans:
            try:
                self.adapter.cancel_order(order.client_order_id)
                canceled_ids.add(str(order.client_order_id))
            except AdapterError as error:
                self.risk_state.trigger(f"ORPHAN_CANCEL_FAILED:{getattr(error, 'code', 'UNKNOWN')}")
        self.active_orders = [order for order in self.active_orders if str(order.client_order_id) not in canceled_ids]
        self.created_order_ids.difference_update(canceled_ids)
        self.orphans_checked = True

    def _spot_quantity(self, instrument: Instrument) -> Decimal:
        return self.balances.get(instrument.base_currency.upper(), Decimal("0"))

    @staticmethod
    def _carry_strategy_context(source: TargetOrderPlan, rebuilt: TargetOrderPlan) -> TargetOrderPlan:
        return replace(
            rebuilt,
            strategy_action=source.strategy_action,
            strategy_confidence=source.strategy_confidence,
            strategy_signal_timestamp=source.strategy_signal_timestamp,
            strategy_risk_tags=source.strategy_risk_tags,
            strategy_basis=source.strategy_basis,
            strategy_source_symbols=source.strategy_source_symbols,
            strategy_source_signals=source.strategy_source_signals,
            strategy_reason_zh=source.strategy_reason_zh,
        )

    def _source_symbols(self, plan: TargetOrderPlan) -> tuple[str, ...]:
        return plan.strategy_source_symbols or (plan.symbol,)

    def _historical_symbol(self, plan: TargetOrderPlan) -> str:
        return self._source_symbols(plan)[0]

    def _instrument_for_plan(self, plan: TargetOrderPlan) -> Instrument:
        for historical_symbol in self._source_symbols(plan):
            instrument = self.instruments.get(historical_symbol)
            if instrument is not None:
                return instrument
        for instrument in self.instruments.values():
            if instrument.canonical_symbol == plan.symbol:
                return instrument
        raise KeyError(f"no instrument for canonical symbol {plan.symbol}")

    def _limit_for_plan(self, plan: TargetOrderPlan) -> Decimal:
        limits = [risk_envelope_for_symbol(self.bundle.risk_envelope, symbol) for symbol in self._source_symbols(plan)]
        positive = [limit for limit in limits if limit > 0]
        return min(positive) if positive else Decimal("0")

    def _rebuild_plan(self, plan: TargetOrderPlan, target: Decimal, equity: Decimal) -> TargetOrderPlan | None:
        instrument = self._instrument_for_plan(plan)
        kwargs = {
            "equity": equity,
            "target_exposure": target,
            "reference_price": plan.reference_price or Decimal("0"),
            "bid": plan.bid or Decimal("0"),
            "ask": plan.ask or Decimal("0"),
            "decision_time": datetime.now(timezone.utc),
            "active_orders": self.active_orders,
            "max_target_exposure": self._limit_for_plan(plan),
        }
        if instrument.instrument_type == InstrumentType.SPOT:
            rebuilt = plan_spot_order(instrument, current_base_quantity=plan.current_contracts, **kwargs)
        else:
            rebuilt = plan_target_order(instrument, current_contracts=plan.current_contracts, **kwargs)
        return self._carry_strategy_context(plan, rebuilt) if rebuilt is not None else None

    def _available_collateral_scales(self, plans: list[TargetOrderPlan], equity: Decimal) -> dict[str, Decimal]:
        """Keep each derivative bucket inside its available settle-currency margin.

        ``totalEq`` can include BTC/ETH/OKB while a swap order may require
        USDT margin.  The historical envelope is therefore not sufficient by
        itself: cap each settlement-currency bucket at 80% of its available
        balance before submitting any order.
        """

        if equity <= 0:
            return {}
        notional_by_currency: dict[str, Decimal] = {}
        for plan in plans:
            instrument = self._instrument_for_plan(plan)
            if instrument.instrument_type == InstrumentType.SPOT:
                continue
            currency = instrument.settlement_currency.upper()
            notional_by_currency[currency] = notional_by_currency.get(currency, Decimal("0")) + abs(plan.target_exposure) * equity
        scales: dict[str, Decimal] = {}
        for currency, target_notional in notional_by_currency.items():
            available = self.balances.get(currency, Decimal("0"))
            capacity = available * Decimal("0.80")
            if target_notional <= 0:
                scales[currency] = Decimal("1")
                continue
            if capacity <= 0:
                scales[currency] = Decimal("0")
                continue
            scales[currency] = min(Decimal("1"), capacity / target_notional)
        return scales

    def _engage_safety(self, reason: str) -> None:
        self.risk_state.trigger(reason)
        self.stop_reason = reason
        self.cancel_created_orders()
        self.stop_event.set()

    def _refresh_clock(self) -> None:
        try:
            if hasattr(self.adapter, "get_server_time_drift_seconds"):
                self.clock_drift_seconds = abs(Decimal(str(self.adapter.get_server_time_drift_seconds())))
            elif hasattr(self.adapter, "get_server_time"):
                server = self.adapter.get_server_time()
                self.clock_drift_seconds = abs(Decimal(str((server - datetime.now(timezone.utc)).total_seconds())))
        except AdapterError as error:
            self.clock_drift_seconds = Decimal("999")
            self.risk_state.trigger(f"CLOCK_SYNC_FAILED:{error.code}")

    def _market_fresh(self, symbol: str) -> bool:
        context = self.market_contexts.get(symbol)
        if context is None:
            return False
        if context.coverage.get("closed_bar") == "UNVERIFIED_ADAPTER_FALLBACK":
            # A quote plus a guessed bar boundary is not sufficient evidence
            # for an order. Adapters must provide a verified market context.
            return False
        now = datetime.now(timezone.utc)
        quote_age = (now - context.quote.observed_at).total_seconds()
        bar_age = ((now - context.closed_bar_time).total_seconds() if context.closed_bar_time else None)
        quote_ok = context.coverage.get("quote") == "OK" and 0 <= quote_age <= 30
        bar_ok = context.coverage.get("closed_bar") == "OK" and bar_age is not None and 0 <= bar_age <= 7200
        return quote_ok and bar_ok

    def _record_decision_snapshot(
        self,
        *,
        historical_symbol: str,
        venue_symbol: str,
        decision_time: datetime,
        equity: Decimal,
        current_quantity: Decimal,
        context: MarketContext,
        strategy_input: Any,
        signal: Any,
    ) -> bool:
        """Persist bounded, pre-order context for prospective replay analysis.

        This is written before order cancellation or submission. It records
        what this process observed and predicted, not a historical label. The
        bounded ring prevents a long-running Demo process from growing its
        state file without limit, and only strategy features are copied so
        credentials/raw adapter payloads cannot enter the journal.
        """

        features = {
            str(key): _audit_value(value)
            for key, value in dict(getattr(strategy_input, "features", {}) or {}).items()
        }
        snapshot = {
            "decision_time": decision_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "historical_symbol": historical_symbol,
            "venue_symbol": venue_symbol,
            "strategy_version": _audit_value(getattr(signal, "strategy_version", getattr(self.bundle, "model_version", "UNKNOWN"))),
            "pre_action": {
                "equity": str(equity),
                "current_quantity": str(current_quantity),
                "quote": {
                    "bid": str(context.quote.bid),
                    "ask": str(context.quote.ask),
                    "observed_at": context.quote.observed_at.isoformat().replace("+00:00", "Z"),
                    "source": context.quote.source,
                },
                "closed_bar_time": context.closed_bar_time.isoformat().replace("+00:00", "Z") if context.closed_bar_time else None,
                "funding_rate": _audit_value(context.funding_rate),
                "funding_source_time": context.funding_source_time.isoformat().replace("+00:00", "Z") if context.funding_source_time else None,
                "mark_price": _audit_value(context.mark_price),
                "mark_source_time": context.mark_source_time.isoformat().replace("+00:00", "Z") if context.mark_source_time else None,
                "index_price": _audit_value(context.index_price),
                "index_source_time": context.index_source_time.isoformat().replace("+00:00", "Z") if context.index_source_time else None,
                "coverage": {str(key): str(value) for key, value in context.coverage.items()},
                "features": features,
            },
            "model_output": {
                "action": _audit_value(getattr(signal, "action", "UNKNOWN")),
                "target_exposure": _audit_value(getattr(signal, "target_exposure", None)),
                "confidence": _audit_value(getattr(signal, "confidence", None)),
                "valid_until": _audit_value(getattr(signal, "valid_until", None)),
                "risk_tags": [_audit_value(item) for item in getattr(signal, "risk_tags", ())],
                "reason_zh": _audit_value(getattr(signal, "strategy_reason_zh", "")),
                "diagnostics": _audit_value(getattr(signal, "diagnostics", {})),
            },
        }
        try:
            self.decision_journal.append(snapshot)
        except DecisionAuditJournalError as error:
            self.last_error = f"DECISION_AUDIT_PERSISTENCE_FAILED: {error}"
            self._engage_safety("DECISION_AUDIT_PERSISTENCE_FAILED")
            return False
        self.decision_audit.append(snapshot)
        if len(self.decision_audit) > MAX_DECISION_AUDIT_ROWS:
            self.decision_audit = self.decision_audit[-MAX_DECISION_AUDIT_ROWS:]
        return True

    def on_private_message(self, message: dict[str, Any]) -> None:
        if message.get("success") is False or str(message.get("code", "0")) not in {"0", ""}:
            self.market_connected = False
            self.private_stream_error = str(message.get("msg") or message.get("code") or "private stream error")
            if self.enable_orders:
                self._engage_safety("PRIVATE_WEBSOCKET_ERROR")
            return
        channel = str((message.get("arg") or {}).get("channel", ""))
        if message.get("event") in {"login", "subscribe"} or channel in {"account", "positions", "orders", "fills"} or "data" in message:
            self.private_stream_seen = True
            self.market_connected = True

    def on_private_error(self, error: BaseException) -> None:
        self.market_connected = False
        self.private_stream_error = f"{type(error).__name__}: {str(error)[:160]}"
        if self.enable_orders:
            self._engage_safety("PRIVATE_WEBSOCKET_ERROR")

    def start_private_stream(self) -> None:
        if not hasattr(self.adapter, "stream_messages"):
            self.private_stream_available = False
            if self.enable_orders:
                self.market_connected = False
                self._engage_safety("PRIVATE_WEBSOCKET_NOT_CONFIGURED")
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
            self._write_heartbeat()
            if self.enable_orders and self.private_stream_available and self.private_stream_seen and not self.market_connected:
                self._engage_safety("PRIVATE_WEBSOCKET_DISCONNECTED")
                break
            if time.monotonic() - self.last_loop_monotonic > max(90, self.poll_seconds * 2 + 30):
                self._engage_safety("WATCHDOG_TIMEOUT")
                break

    def _cancel_stale_orders(self) -> None:
        now = datetime.now(timezone.utc)
        remaining: list[Order] = []
        for order in self.active_orders:
            if not self._is_bot_order(order):
                remaining.append(order)
                continue
            age = max(0.0, (now - order.created_at).total_seconds())
            if age <= MAX_ACTIVE_ORDER_AGE_SECONDS:
                remaining.append(order)
                continue
            try:
                self.adapter.cancel_order(order.client_order_id)
                self.created_order_ids.discard(order.client_order_id)
            except AdapterError as error:
                remaining.append(order)
                self._engage_safety(f"STALE_ORDER_CANCEL_FAILED:{error.code}")
        self.active_orders = remaining

    def _cancel_replaced_order(self, symbol: str, target_exposure: Decimal, current_contracts: Decimal, bid: Decimal, ask: Decimal) -> None:
        """Cancel only bot-owned orders whose target or quote is obsolete."""

        remaining: list[Order] = []
        for order in self.active_orders:
            if order.symbol != symbol or not self._is_bot_order(order):
                remaining.append(order)
                continue
            context = self.order_context.get(str(order.client_order_id), {})
            old_target = context.get("strategy_target_exposure")
            old_current = context.get("strategy_current_contracts")
            target_changed = old_target not in (None, "") and abs(Decimal(str(old_target)) - target_exposure) > Decimal("0.000001")
            partial_fill_changed = old_current not in (None, "") and abs(Decimal(str(old_current)) - current_contracts) > Decimal("0")
            reference = ask if order.side.value == "BUY" else bid
            price_drift = order.price is not None and reference > 0 and abs(order.price - reference) / reference > Decimal("0.01")
            if not (target_changed or partial_fill_changed or price_drift):
                remaining.append(order)
                continue
            try:
                self.adapter.cancel_order(order.client_order_id)
                self.created_order_ids.discard(order.client_order_id)
            except AdapterError as error:
                self._engage_safety(f"REPLACEMENT_CANCEL_FAILED:{error.code}")
        self.active_orders = remaining

    def _plan_symbol(self, historical_symbol: str, instrument: Instrument, equity: Decimal) -> TargetOrderPlan | None:
        venue_symbol = instrument.canonical_symbol
        decision_time = datetime.now(timezone.utc)
        bars = self.adapter.fetch_closed_bars(venue_symbol, limit=100)
        if not bars:
            raise AdapterError(self.venue, "MARKET_DATA_MISSING", f"no closed 1h bars available for {venue_symbol}")
        # Treat the adapter's closed-bar contract as untrusted input.  A
        # malformed/current candle must never become a model feature or order
        # reference price merely because its endpoint was called
        # ``fetch_closed_bars``.
        bars = sorted(
            [bar for bar in bars if bar.timestamp + __import__("datetime").timedelta(hours=1) <= decision_time],
            key=lambda item: item.timestamp,
        )
        if not bars:
            raise AdapterError(self.venue, "CLOSED_BAR_NOT_CONFIRMED", f"no closed 1h bar available for {venue_symbol}")
        if len(bars) < 2:
            raise AdapterError(self.venue, "MARKET_FEATURES_INCOMPLETE", f"fewer than two closed 1h bars available for {venue_symbol}")
        engine = self._engine_for(historical_symbol)
        engine.ingest_closed_bars(bars, now=decision_time)
        latest = bars[-1]
        current = self._spot_quantity(instrument) if instrument.instrument_type == InstrumentType.SPOT else self.positions.get(venue_symbol, Decimal("0"))
        if hasattr(self.adapter, "fetch_market_context"):
            context = self.adapter.fetch_market_context(venue_symbol, bars=bars)
        else:
            bid, ask = self.adapter.fetch_quote(venue_symbol)
            context = MarketContext(venue_symbol, MarketQuote(venue_symbol, bid, ask, decision_time, "adapter-quote"), latest.timestamp + __import__("datetime").timedelta(hours=1), None, None, None, None, decision_time, {"quote": "OK", "closed_bar": "UNVERIFIED_ADAPTER_FALLBACK", "funding": "MISSING", "mark_price": "MISSING", "index_price": "MISSING"})
        self.market_contexts[venue_symbol] = context
        engine.attach_market_context(funding_rate=float(context.funding_rate) if context.funding_rate is not None else None, funding_source_time=context.funding_source_time, mark_price=float(context.mark_price) if context.mark_price is not None else None, index_price=float(context.index_price) if context.index_price is not None else None, status=context.coverage)
        engine.attach_market_source_times(mark_source_time=context.mark_source_time, index_source_time=context.index_source_time)
        strategy_input = engine.build_input(decision_time=decision_time, current_qty=current, current_equity=equity)
        signal = self.bundle.model.predict(strategy_input)
        self.latest_signals[historical_symbol] = {
            "historical_symbol": historical_symbol,
            "venue_symbol": venue_symbol,
            "signal_timestamp": _audit_value(getattr(signal, "signal_timestamp", decision_time)),
            "action": _audit_value(getattr(signal, "action", "UNKNOWN")),
            "target_exposure": _audit_value(getattr(signal, "target_exposure", None)),
            "current_exposure": _audit_value(getattr(strategy_input, "current_strategy_position", None)),
            "confidence": _audit_value(getattr(signal, "confidence", None)),
            "reason_zh": _audit_value(getattr(signal, "strategy_reason_zh", "")),
            "basis": list(strategy_basis_from_features(strategy_input.features)),
            "risk_tags": [_audit_value(item) for item in getattr(signal, "risk_tags", ())],
            "coverage": {str(key): str(value) for key, value in context.coverage.items()},
            "indicators": {
                key: _audit_value(strategy_input.features.get(key))
                for key in (
                    "feature_rsi_14",
                    "feature_macd_line_12_26",
                    "feature_macd_signal_9",
                    "feature_macd_histogram",
                    "feature_bollinger_zscore_20",
                    "feature_bollinger_percent_b_20",
                    "feature_return_24bar",
                    "feature_realized_volatility_72bar",
                    "feature_volume_percentile_72bar",
                    "feature_funding_rate",
                    "feature_funding_rate_missing",
                    "feature_mark_index_basis",
                    "feature_mark_index_basis_missing",
                )
            },
            "diagnostics": _audit_value(getattr(signal, "diagnostics", {})),
        }
        recorded = self._record_decision_snapshot(
            historical_symbol=historical_symbol,
            venue_symbol=venue_symbol,
            decision_time=decision_time,
            equity=equity,
            current_quantity=current,
            context=context,
            strategy_input=strategy_input,
            signal=signal,
        )
        if not recorded:
            return None
        bid, ask = context.quote.bid, context.quote.ask
        self._cancel_replaced_order(venue_symbol, Decimal(str(signal.target_exposure)), current, bid, ask)
        limit = risk_envelope_for_symbol(self.bundle.risk_envelope, historical_symbol)
        if instrument.instrument_type == InstrumentType.SPOT:
            if not self.allow_spot_approximation:
                return None
            plan = plan_spot_order(instrument, current_base_quantity=current, target_exposure=Decimal(str(signal.target_exposure)), equity=equity, reference_price=latest.close, bid=bid, ask=ask, decision_time=decision_time, active_orders=self.active_orders, max_target_exposure=limit)
        else:
            plan = plan_target_order(instrument, current_contracts=current, target_exposure=Decimal(str(signal.target_exposure)), equity=equity, reference_price=latest.close, bid=bid, ask=ask, decision_time=decision_time, active_orders=self.active_orders, max_target_exposure=limit)
        if plan is None:
            return None
        confidence = getattr(signal, "confidence", None)
        return replace(
            plan,
            strategy_action=str(getattr(signal, "action", plan.reason)),
            strategy_confidence=Decimal(str(confidence)) if confidence is not None else None,
            strategy_signal_timestamp=str(getattr(signal, "signal_timestamp", "")),
            strategy_risk_tags=tuple(str(item) for item in getattr(signal, "risk_tags", ())),
            strategy_basis=strategy_basis_from_features(strategy_input.features),
            strategy_reason_zh=str(getattr(signal, "strategy_reason_zh", "") or strategy_reason_zh(getattr(signal, "action", plan.reason), strategy_input.current_strategy_position, signal.target_exposure, strategy_input.features)),
            strategy_source_symbols=(historical_symbol,),
            strategy_source_signals=({
                "historical_symbol": historical_symbol,
                "strategy_action": str(getattr(signal, "action", plan.reason)),
                "target_exposure": str(signal.target_exposure),
                "confidence": str(confidence) if confidence is not None else None,
                "strategy_basis": list(strategy_basis_from_features(strategy_input.features)),
                "strategy_reason_zh": str(getattr(signal, "strategy_reason_zh", "") or strategy_reason_zh(getattr(signal, "action", plan.reason), strategy_input.current_strategy_position, signal.target_exposure, strategy_input.features)),
            },),
        )

    def process_once(self) -> dict[str, Any]:
        self.last_loop_monotonic = time.monotonic()
        if KILL_SWITCH_PATH.exists():
            self._engage_safety("MANUAL_KILL_SWITCH")
            return self._result("BLOCKED" if self.enable_orders else "RUNNING_READ_ONLY", Decimal("0"), [], {"kill_switch": ["MANUAL_KILL_SWITCH"]})
        try:
            equity = self.refresh()
        except AdapterError as error:
            self.last_error = f"{error.code}: {error}"
            if self.enable_orders:
                self._engage_safety("ACCOUNT_REFRESH_FAILED")
            return self._result("BLOCKED" if self.enable_orders else "RUNNING_READ_ONLY", Decimal("0"), [], {"account_refresh": [error.code]})

        self._refresh_clock()
        self._cancel_stale_orders()

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

        # Crosswalks such as ADAUSD/ADAUSDT -> ADA-USDT-SWAP are one live
        # position, not two independent accounts. Collapse them before the
        # portfolio cap, collateral scaling, and submission loops.
        plans = merge_duplicate_target_plans(plans)
        duplicate_rebuilt: list[TargetOrderPlan] = []
        for plan in plans:
            if len(self._source_symbols(plan)) > 1:
                rebuilt = self._rebuild_plan(plan, plan.target_exposure, equity)
                if rebuilt is not None:
                    duplicate_rebuilt.append(rebuilt)
            else:
                duplicate_rebuilt.append(plan)
        plans = duplicate_rebuilt

        total_target = sum((abs(item.target_exposure) for item in plans), Decimal("0"))
        total_limit = Decimal(str(self.bundle.risk_envelope.get("historical_simultaneous_total_exposure_cap", "0")))
        self.portfolio_target_scale = portfolio_target_scale(total_target, total_limit)
        if plans and self.portfolio_target_scale < Decimal("1"):
            # Recompute each delta with the same cap applied to the behavioral
            # target.  This keeps the cap enforceable after aggregation.
            scaled: list[TargetOrderPlan] = []
            for plan in plans:
                target = plan.target_exposure * self.portfolio_target_scale
                rebuilt = self._rebuild_plan(plan, target, equity)
                if rebuilt is not None:
                    scaled.append(rebuilt)
            plans = scaled
            total_target = sum((abs(item.target_exposure) for item in plans), Decimal("0"))

        collateral_scales = self._available_collateral_scales(plans, equity)
        if plans and any(scale < Decimal("1") for scale in collateral_scales.values()):
            scaled = []
            applied_scales: list[Decimal] = []
            for plan in plans:
                instrument = self._instrument_for_plan(plan)
                collateral_scale = collateral_scales.get(instrument.settlement_currency.upper(), Decimal("0"))
                if collateral_scale <= 0:
                    continue
                applied_scales.append(collateral_scale)
                target = plan.target_exposure * collateral_scale
                rebuilt = self._rebuild_plan(plan, target, equity)
                if rebuilt is not None:
                    scaled.append(rebuilt)
            plans = scaled
            if applied_scales:
                self.portfolio_target_scale *= min(applied_scales)
            else:
                self.portfolio_target_scale = Decimal("0")
            total_target = sum((abs(item.target_exposure) for item in plans), Decimal("0"))

        submitted: list[str] = []
        order_errors: dict[str, str] = {}
        for plan in plans:
            historical_symbol = self._historical_symbol(plan)
            decision = check_testnet_order(
                enable_orders=self.enable_orders,
                confirm_testnet=self.confirm_testnet,
                symbol=historical_symbol,
                target_exposure=plan.target_exposure,
                total_target_exposure=total_target,
                envelope=self.bundle.risk_envelope,
                reconciliation_ok=self.reconciliation_ok,
                websocket_connected=self.market_connected,
                market_fresh=self._market_fresh(plan.symbol),
                clock_drift_seconds=self.clock_drift_seconds,
                consecutive_rejects=self.consecutive_rejects,
                daily_loss=self.risk_state.daily_loss,
                max_daily_loss=self.risk_state.max_daily_loss,
                drawdown=self.risk_state.drawdown,
                max_drawdown=self.risk_state.max_drawdown,
                risk_block_reasons=tuple(self.risk_state.block_reasons),
                kill_switch_engaged=self.risk_state.kill_switch_engaged,
                margin_mode=getattr(self.adapter, "margin_mode_by_symbol", {}).get(plan.symbol, getattr(self.adapter, "margin_mode", None)),
                required_margin_mode=getattr(self.adapter, "required_margin_mode", ""),
                current_leverage=getattr(self.adapter, "leverage_by_symbol", {}).get(plan.symbol, getattr(self.adapter, "max_position_leverage", None)),
                max_leverage=MAX_LEVERAGE if hasattr(self.adapter, "max_position_leverage") else Decimal("0"),
                risk_configuration_verified=getattr(self.adapter, "risk_configuration_verified", None),
                symbol_risk_configuration_verified=getattr(self.adapter, "risk_configuration_by_symbol", {}).get(plan.symbol),
            )
            if not decision.allowed:
                blocked[historical_symbol] = list(decision.reasons)
                continue
            strategy_context = {
                "strategy_action": plan.strategy_action,
                "strategy_reason": plan.reason,
                "strategy_confidence": str(plan.strategy_confidence) if plan.strategy_confidence is not None else None,
                "strategy_target_exposure": str(plan.target_exposure),
                "strategy_current_contracts": str(plan.current_contracts),
                "strategy_target_contracts": str(plan.target_contracts),
                "strategy_signal_timestamp": plan.strategy_signal_timestamp,
                "strategy_risk_tags": list(plan.strategy_risk_tags),
                "strategy_basis": list(plan.strategy_basis),
                "strategy_reason_zh": plan.strategy_reason_zh,
                "strategy_source_symbols": list(self._source_symbols(plan)),
                "strategy_source_signals": list(plan.strategy_source_signals),
            }
            order = Order(plan.client_order_id, plan.symbol, plan.side, plan.order_type, plan.quantity, datetime.now(timezone.utc), price=plan.price, reduce_only=plan.reduce_only, post_only=plan.post_only, metadata={"strategy_context": strategy_context})
            try:
                accepted = self.adapter.place_order(order)
            except AdapterError as error:
                self.consecutive_rejects += 1
                order_errors[historical_symbol] = f"{error.code}: {error}"
                if self.consecutive_rejects >= 3:
                    self._engage_safety("CONSECUTIVE_ORDER_REJECTS")
                continue
            self.consecutive_rejects = 0
            self.created_order_ids.add(accepted.client_order_id)
            self.order_context[accepted.client_order_id] = strategy_context
            submitted.append(accepted.client_order_id)
        if submitted:
            # Refresh immediately so the dashboard and the next idempotency
            # decision see remote orders/fills created in this cycle.
            try:
                self.refresh()
            except AdapterError as error:
                self.last_error = f"{error.code}: {error}"
                self._engage_safety("ACCOUNT_REFRESH_FAILED_AFTER_ORDER")
        return self._result("RUNNING" if self.enable_orders else "RUNNING_READ_ONLY", equity, plans, blocked, submitted, order_errors)

    def _result(self, status: str, equity: Decimal, plans: list[TargetOrderPlan], blocked: dict[str, list[str]], submitted: list[str] | None = None, order_errors: dict[str, str] | None = None) -> dict[str, Any]:
        if self.private_stream_available:
            connection = "PRIVATE_WEBSOCKET" if self.private_stream_seen else "PRIVATE_WEBSOCKET_WAITING"
        else:
            connection = "REST_POLLING"
        now = datetime.now(timezone.utc)
        ages = [(now - order.created_at).total_seconds() for order in self.active_orders if self._is_bot_order(order)]
        result = {
            "status": status,
            "venue": self.venue,
            "updated_at_utc": now.isoformat(),
            "runtime_heartbeat_at_utc": now.isoformat(),
            "heartbeat_only": False,
            "model_version": getattr(self.bundle, "model_version", "UNKNOWN"),
            "feature_contract_version": getattr(self.bundle, "feature_contract_version", "UNKNOWN"),
            "model_sha256": getattr(self.bundle, "model_sha256", ""),
            "training_data_sha256": getattr(self.bundle, "training_data_sha256", ""),
            "frozen_cutoff": getattr(self.bundle, "frozen_cutoff", ""),
            "equity": equity,
            "plans": len(plans),
            "submitted": submitted or [],
            "blocked": blocked,
            "market_connection": connection,
            "market_connected": self.market_connected,
            "private_stream_seen": self.private_stream_seen,
            "private_stream_error": self.private_stream_error,
            "order_submission_enabled": self.enable_orders and self.confirm_testnet and self.risk_state.safe(),
            "risk_configuration_verified": getattr(self.adapter, "risk_configuration_verified", None),
            "created_order_ids": sorted(self.created_order_ids),
            "account": self.account_snapshot,
            "risk": self.risk_state.snapshot(),
            "risk_metrics": dict(self.risk_metrics),
            "clock_drift_seconds": self.clock_drift_seconds,
            "market_context": {symbol: {"coverage": context.coverage, "quote_time": context.quote.observed_at, "closed_bar_time": context.closed_bar_time, "funding_source_time": context.funding_source_time, "mark_source_time": context.mark_source_time, "index_source_time": context.index_source_time, "quote_age_seconds": context.quote_age_seconds(now), "closed_bar_age_seconds": context.closed_bar_age_seconds(now)} for symbol, context in self.market_contexts.items()},
            "behavior_state": {
                "bootstrapped": self.behavior_state_bootstrapped,
                "seen_fill_ids": sorted(self.seen_fill_ids)[-2000:],
                "engine_state": {symbol: engine.snapshot() for symbol, engine in self.engines.items()},
                "realized_pnl_by_symbol": {symbol: str(value) for symbol, value in self.realized_pnl_by_symbol.items()},
                "order_context": self.order_context,
                "latest_feedback_at": self.latest_feedback_at,
                "decision_audit": self.decision_audit,
                "decision_audit_journal": {
                    "format": "JSONL_APPEND_ONLY_UTC_DAILY",
                    "runtime_state_ring_rows": MAX_DECISION_AUDIT_ROWS,
                    "max_record_bytes": 128 * 1024,
                },
            },
            "signals": self.latest_signals,
            "oldest_active_order_age_seconds": max(ages) if ages else None,
            "stop_reason": self.stop_reason,
            "last_error": self.last_error,
            "portfolio_target_scale": self.portfolio_target_scale,
            "order_errors": order_errors or {},
            "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        }
        with self._result_lock:
            self._last_result = result
            _write_json(self.output_path, result)
        return result

    def _write_heartbeat(self) -> None:
        """Refresh process liveness without fabricating fresher market data."""

        with self._result_lock:
            if not self._last_result:
                return
            heartbeat = dict(self._last_result)
            heartbeat["runtime_heartbeat_at_utc"] = datetime.now(timezone.utc).isoformat()
            heartbeat["heartbeat_only"] = True
            _write_json(self.output_path, heartbeat)
            self._last_result = heartbeat

    def cancel_created_orders(self) -> None:
        owned_ids = set(self.created_order_ids)
        owned_ids.update(str(order.client_order_id) for order in self.active_orders if self._is_bot_order(order))
        canceled_ids: set[str] = set()
        for client_id in sorted(owned_ids):
            try:
                self.adapter.cancel_order(client_id)
                canceled_ids.add(client_id)
            except AdapterError as error:
                self.risk_state.trigger("BOT_ORDER_CANCEL_FAILED")
                self.last_error = f"BOT_ORDER_CANCEL_FAILED:{error.code}"
        self.created_order_ids.difference_update(canceled_ids)
        self.active_orders = [order for order in self.active_orders if str(order.client_order_id) not in canceled_ids]

    def shutdown(self) -> None:
        self.stop_event.set()
        if self._async_stop is not None and self._async_loop is not None:
            # The websocket thread may have already exited and closed its
            # event loop (for example after a transient connection error).
            # Shutdown is a best-effort cleanup path; a closed loop must not
            # turn a safe, already-stopped runtime into RUNNER_EXCEPTION.
            try:
                self._async_loop.call_soon_threadsafe(self._async_stop.set)
            except RuntimeError:
                pass
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
    if venue == "binance-futures-testnet":
        return BinanceFuturesAdapter.from_environment(), ROOT / "quant" / "outputs" / "binance_futures_testnet_runtime_state.json"
    raise AdapterError(venue, "UNSUPPORTED_VENUE", f"unsupported unified runtime venue: {venue}")


def run_foreground_venue(*, venue: str, artifact_path: Path = DEFAULT_ARTIFACT, enable_orders: bool = False, confirm_testnet: bool = False, symbols: str = "auto", once: bool = False, poll_seconds: int = 60, allow_spot_approximation: bool = False, external_stop_event: threading.Event | None = None) -> dict[str, Any]:
    bundle = load_deployment_bundle(artifact_path, require_model_sha256=True)
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
    if enable_orders and hasattr(adapter, "verify_risk_configuration"):
        derivative_symbols = [item.canonical_symbol for item in selected.values() if item.instrument_type != InstrumentType.SPOT]
        if derivative_symbols:
            adapter.verify_risk_configuration(
                derivative_symbols,
                max_leverage=MAX_LEVERAGE,
                required_margin_mode=REQUIRED_MARGIN_MODE,
            )
    adapter.get_server_time()
    runtime = VenueRuntime(adapter, venue, bundle, enable_orders, confirm_testnet, allow_spot_approximation, selected, output_path, max(5, poll_seconds))
    bridge_stop = threading.Event()
    bridge_thread: threading.Thread | None = None
    if external_stop_event is not None:
        def bridge_external_stop() -> None:
            while not bridge_stop.wait(0.2):
                if external_stop_event.is_set():
                    runtime.stop_event.set()
                    return

        bridge_thread = threading.Thread(target=bridge_external_stop, name=f"{venue}-supervisor-stop", daemon=True)
        bridge_thread.start()
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
        bridge_stop.set()
        if bridge_thread is not None and bridge_thread.is_alive():
            bridge_thread.join(timeout=1)
    if last.get("status") == "RUNNING_READ_ONLY":
        last["status"] = "STOPPED_READ_ONLY"
    elif last.get("status") == "RUNNING":
        last["status"] = "STOPPED"
    last["stop_reason"] = runtime.stop_reason
    _write_json(output_path, last)
    return last


__all__ = ["ALLOWED_MAPPING_STATUSES", "DEFAULT_ARTIFACT", "KILL_SWITCH_PATH", "VenueRuntime", "build_venue_symbol_mapping", "run_foreground_venue"]
