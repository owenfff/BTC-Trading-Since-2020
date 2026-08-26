from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .base import StrategyInput


LEGACY_FEATURE_CONTRACT_VERSION = "m13-v2-cross-asset"
FEATURE_CONTRACT_VERSION = "m13-v3-cross-asset-indicators"
OPERATIONAL_FEATURE_CONTRACT_VERSION = "m13-v3.1-operational-parity"

FEATURE_COLUMNS = (
    "feature_symbol",
    "feature_instrument_class",
    "feature_payout_model",
    "feature_quote_currency",
    "feature_settlement_currency",
    "feature_market_bar_interval",
    "feature_contract_lot_size",
    "feature_multiplier_major",
    "feature_latest_bar_time",
    "feature_market_data_available",
    "feature_mark_index_missing",
    "feature_funding_source_time",
    "feature_return_1bar",
    "feature_return_3bar",
    "feature_return_6bar",
    "feature_return_12bar",
    "feature_return_24bar",
    "feature_return_72bar",
    "feature_realized_volatility_72bar",
    "feature_atr_14bar",
    "feature_volume_change_1bar",
    "feature_volume_percentile_72bar",
    "feature_ma_distance_24bar",
    "feature_trend_slope_24bar",
    "feature_distance_rolling_high_72bar",
    "feature_distance_rolling_low_72bar",
    "feature_funding_rate",
    "feature_funding_rate_missing",
    "feature_mark_index_basis",
    "feature_mark_index_basis_missing",
    "feature_rsi_14",
    "feature_macd_line_12_26",
    "feature_macd_signal_9",
    "feature_macd_histogram",
    "feature_bollinger_zscore_20",
    "feature_bollinger_percent_b_20",
    "feature_market_regime",
    "feature_time_of_day_fraction",
    "feature_day_of_week",
    "feature_day_of_week_sin",
    "feature_day_of_week_cos",
    "feature_current_net_position_contracts",
    "feature_current_normalized_exposure",
    "feature_position_scale_contracts",
    "feature_cycle_duration_seconds",
    "feature_latest_action",
    "feature_action_lag_1",
    "feature_action_lag_2",
    "feature_action_lag_3",
    "feature_recent_add_count_24h",
    "feature_recent_reduce_count_24h",
    "feature_recent_flip_count_24h",
    "feature_recent_realised_outcome",
    "feature_realised_drawdown",
    "feature_fee_accumulation_raw",
    "feature_funding_accumulation_raw",
    "feature_order_execution_style",
    "feature_ordering_confidence",
    "feature_accounting_confidence",
    "feature_history_last_decision_time",
)

FORBIDDEN_INPUT_PREFIXES = ("label_", "observed_")


def parse_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def validate_feature_mapping(features: Mapping[str, Any]) -> None:
    forbidden = [key for key in features if key.startswith(FORBIDDEN_INPUT_PREFIXES)]
    if forbidden:
        raise ValueError(f"future/observed columns cannot enter Strategy Core: {forbidden}")


def strategy_input_from_row(row: Mapping[str, Any]) -> StrategyInput:
    features = {key: row.get(key) for key in FEATURE_COLUMNS}
    validate_feature_mapping(features)
    risk_state = {
        "market_data_available": row.get("feature_market_data_available"),
        "mark_index_missing": row.get("feature_mark_index_missing"),
        "accounting_confidence": row.get("feature_accounting_confidence"),
    }
    return StrategyInput(
        decision_time=parse_time(row["decision_time"]),
        features=features,
        current_strategy_position=parse_float(row.get("feature_current_normalized_exposure"), 0.0) or 0.0,
        risk_state=risk_state,
    )
