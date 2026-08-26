from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar
from features.technical_indicators import calculate_technical_indicators

from .base import StrategyInput
from .feature_contract import FEATURE_CONTRACT_VERSION, FEATURE_COLUMNS, LEGACY_FEATURE_CONTRACT_VERSION, validate_feature_mapping


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


class RealtimeFeatureEngine:
    """Closed-bar-only feature state; no labels or remote future state enter it."""

    def __init__(self, instrument: Instrument, *, feature_symbol: str | None = None, position_scale: float = 1.0, feature_contract_version: str = FEATURE_CONTRACT_VERSION) -> None:
        self.instrument = instrument
        self.feature_symbol = feature_symbol or instrument.canonical_symbol
        self.position_scale = max(float(position_scale), 1.0)
        self.feature_contract_version = feature_contract_version
        self.bars: deque[MarketBar] = deque(maxlen=100)
        self.latest_decision: datetime | None = None
        self.latest_action = "UNKNOWN"
        self.add_count = self.reduce_count = self.flip_count = 0
        self.realised_outcome = 0.0
        self.drawdown = 0.0
        self.fees = 0.0
        self.funding = 0.0
        self.latest_funding_rate: float | None = None
        self.latest_funding_source_time: datetime | None = None
        self.latest_mark_price: float | None = None
        self.latest_index_price: float | None = None
        self.latest_market_context_status: dict[str, str] = {}

    def ingest_closed_bars(self, bars: list[MarketBar], *, now: datetime | None = None) -> None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        for bar in sorted(bars, key=lambda item: item.timestamp):
            if bar.timestamp + __import__("datetime").timedelta(hours=1) >= current:
                continue
            if self.bars and bar.timestamp <= self.bars[-1].timestamp:
                continue
            self.bars.append(bar)

    def record_action(self, action: str, realised_outcome: float = 0.0, fee: float = 0.0, funding: float = 0.0) -> None:
        previous = self.latest_action
        self.latest_action = action or "UNKNOWN"
        if "ADD" in self.latest_action or "OPEN" in self.latest_action:
            self.add_count += 1
        if "REDUCE" in self.latest_action or "CLOSE" in self.latest_action:
            self.reduce_count += 1
        if "FLIP" in self.latest_action or (previous.endswith("LONG") and self.latest_action.endswith("SHORT")) or (previous.endswith("SHORT") and self.latest_action.endswith("LONG")):
            self.flip_count += 1
        self.realised_outcome += realised_outcome
        self.fees += fee
        self.funding += funding

    def attach_market_context(
        self,
        *,
        funding_rate: float | None = None,
        funding_source_time: datetime | None = None,
        mark_price: float | None = None,
        index_price: float | None = None,
        status: dict[str, str] | None = None,
    ) -> None:
        """Attach as-of public context without converting missing values to zero."""

        self.latest_funding_rate = funding_rate
        self.latest_funding_source_time = funding_source_time
        self.latest_mark_price = mark_price
        self.latest_index_price = index_price
        self.latest_market_context_status = dict(status or {})

    def snapshot(self) -> dict[str, Any]:
        return {
            "latest_action": self.latest_action,
            "add_count": self.add_count,
            "reduce_count": self.reduce_count,
            "flip_count": self.flip_count,
            "realised_outcome": self.realised_outcome,
            "drawdown": self.drawdown,
            "fees": self.fees,
            "funding": self.funding,
            "latest_decision": self.latest_decision.isoformat() if self.latest_decision else None,
            "latest_funding_rate": self.latest_funding_rate,
            "latest_funding_source_time": self.latest_funding_source_time.isoformat() if self.latest_funding_source_time else None,
            "latest_mark_price": self.latest_mark_price,
            "latest_index_price": self.latest_index_price,
            "latest_market_context_status": dict(self.latest_market_context_status),
        }

    def restore(self, payload: dict[str, Any]) -> None:
        self.latest_action = str(payload.get("latest_action") or "UNKNOWN")
        self.add_count = int(payload.get("add_count", 0) or 0)
        self.reduce_count = int(payload.get("reduce_count", 0) or 0)
        self.flip_count = int(payload.get("flip_count", 0) or 0)
        self.realised_outcome = _f(payload.get("realised_outcome"))
        self.drawdown = _f(payload.get("drawdown"))
        self.fees = _f(payload.get("fees"))
        self.funding = _f(payload.get("funding"))
        for name in ("latest_decision", "latest_funding_source_time"):
            value = payload.get(name)
            if value:
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    setattr(self, name, parsed.astimezone(timezone.utc))
                except ValueError:
                    pass
        self.latest_funding_rate = payload.get("latest_funding_rate")
        self.latest_mark_price = payload.get("latest_mark_price")
        self.latest_index_price = payload.get("latest_index_price")
        self.latest_market_context_status = dict(payload.get("latest_market_context_status") or {})

    def _features(self, decision_time: datetime, current_qty: Decimal, current_equity: Decimal) -> dict[str, Any]:
        bars = [bar for bar in self.bars if bar.timestamp + __import__("datetime").timedelta(hours=1) <= decision_time]
        closes = [_f(bar.close) for bar in bars]
        volumes = [_f(bar.volume) for bar in bars]
        latest = bars[-1] if bars else None
        def ret(lag: int) -> float:
            return closes[-1] / closes[-1 - lag] - 1.0 if len(closes) > lag and closes[-1 - lag] else 0.0
        returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes)) if closes[index - 1]]
        vol = (sum(value * value for value in returns[-72:]) / max(len(returns[-72:]), 1)) ** 0.5
        ma = sum(closes[-24:]) / max(len(closes[-24:]), 1) if closes else 0.0
        latest_close = closes[-1] if closes else 0.0
        regime = "UP" if latest_close > ma and ret(6) > 0 else ("DOWN" if latest_close < ma and ret(6) < 0 else "RANGE")
        indicators = calculate_technical_indicators(
            [bar.close for bar in bars],
            [bar.high for bar in bars],
            [bar.low for bar in bars],
            [bar.volume for bar in bars],
        )
        legacy_contract = self.feature_contract_version == LEGACY_FEATURE_CONTRACT_VERSION
        values: dict[str, Any] = {key: "" for key in FEATURE_COLUMNS}
        values.update({
            "feature_symbol": self.feature_symbol,
            "feature_instrument_class": "SPOT" if self.instrument.instrument_type == InstrumentType.SPOT else "DERIVATIVE",
            "feature_payout_model": "INVERSE" if self.instrument.instrument_type == InstrumentType.INVERSE_PERPETUAL else "LINEAR",
            "feature_quote_currency": self.instrument.quote_currency,
            "feature_settlement_currency": self.instrument.settlement_currency,
            "feature_market_bar_interval": "1h",
            "feature_contract_lot_size": float(self.instrument.lot_size),
            "feature_multiplier_major": float(self.instrument.contract_multiplier),
            "feature_latest_bar_time": latest.timestamp.isoformat().replace("+00:00", "Z") if latest else "",
            "feature_market_data_available": bool(latest and len(closes) >= 2),
            "feature_mark_index_missing": True,
            "feature_return_1bar": ret(1), "feature_return_3bar": ret(3), "feature_return_6bar": ret(6), "feature_return_12bar": ret(12), "feature_return_24bar": ret(24), "feature_return_72bar": ret(72),
            "feature_realized_volatility_72bar": vol,
            "feature_atr_14bar": (sum(abs(_f(bar.high) - _f(bar.low)) for bar in bars[-14:]) / max(len(bars[-14:]), 1)) / latest_close if latest_close else 0.0,
            "feature_volume_change_1bar": volumes[-1] / volumes[-2] - 1.0 if len(volumes) > 1 and volumes[-2] else 0.0,
            "feature_volume_percentile_72bar": 0.5 if legacy_contract else indicators["feature_volume_percentile_72bar"],
            "feature_ma_distance_24bar": latest_close / ma - 1.0 if ma else 0.0,
            "feature_trend_slope_24bar": ret(24) / 24.0,
            "feature_distance_rolling_high_72bar": latest_close / max(closes[-72:]) - 1.0 if closes else 0.0,
            "feature_distance_rolling_low_72bar": latest_close / min(closes[-72:]) - 1.0 if closes and min(closes[-72:]) else 0.0,
            "feature_funding_rate": 0.0 if legacy_contract else self.latest_funding_rate,
            "feature_funding_rate_missing": False if legacy_contract else self.latest_funding_rate is None,
            "feature_mark_index_basis": 0.0 if legacy_contract else None,
            "feature_mark_index_basis_missing": False if legacy_contract else True,
            "feature_market_regime": regime,
            "feature_time_of_day_fraction": (decision_time.hour * 3600 + decision_time.minute * 60) / 86400,
            "feature_day_of_week": decision_time.weekday(), "feature_day_of_week_sin": math.sin(2 * math.pi * decision_time.weekday() / 7), "feature_day_of_week_cos": math.cos(2 * math.pi * decision_time.weekday() / 7),
            "feature_current_net_position_contracts": float(current_qty), "feature_current_normalized_exposure": float(current_qty) / self.position_scale, "feature_position_scale_contracts": self.position_scale,
            "feature_cycle_duration_seconds": 0.0, "feature_latest_action": self.latest_action, "feature_recent_add_count_24h": self.add_count, "feature_recent_reduce_count_24h": self.reduce_count, "feature_recent_flip_count_24h": self.flip_count,
            "feature_recent_realised_outcome": self.realised_outcome, "feature_realised_drawdown": self.drawdown, "feature_fee_accumulation_raw": self.fees, "feature_funding_accumulation_raw": self.funding,
            "feature_order_execution_style": "Limit_POST_ONLY", "feature_ordering_confidence": "HIGH", "feature_accounting_confidence": "HIGH", "feature_history_last_decision_time": self.latest_decision.isoformat().replace("+00:00", "Z") if self.latest_decision else "",
        })
        if not legacy_contract:
            values.update({key: indicators[key] for key in indicators if key != "feature_volume_percentile_72bar"})
            funding_time = self.latest_funding_source_time or (getattr(latest, "funding_source_time", None) if latest else None)
            if funding_time is not None and funding_time <= decision_time:
                values["feature_funding_source_time"] = funding_time.isoformat().replace("+00:00", "Z")
            mark = self.latest_mark_price or (getattr(latest, "mark_price", None) if latest else None)
            index_price = self.latest_index_price or (getattr(latest, "index_price", None) if latest else None)
            if mark is not None and index_price is not None and float(index_price) > 0:
                values["feature_mark_index_missing"] = False
                values["feature_mark_index_basis"] = float(mark) / float(index_price) - 1.0
                values["feature_mark_index_basis_missing"] = False
        return values

    def build_input(self, *, decision_time: datetime, current_qty: Decimal, current_equity: Decimal) -> StrategyInput:
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=timezone.utc)
        decision_time = decision_time.astimezone(timezone.utc)
        features = self._features(decision_time, current_qty, current_equity)
        validate_feature_mapping(features)
        if features["feature_latest_bar_time"] and features["feature_latest_bar_time"] >= decision_time.isoformat().replace("+00:00", "Z"):
            raise ValueError("realtime feature engine attempted to use an open or future bar")
        self.latest_decision = decision_time
        return StrategyInput(decision_time=decision_time, features=features, current_strategy_position=float(current_qty) / self.position_scale, risk_state={"feature_contract_version": self.feature_contract_version, "market_data_available": features["feature_market_data_available"], "market_context_status": dict(self.latest_market_context_status)})


__all__ = ["RealtimeFeatureEngine"]
