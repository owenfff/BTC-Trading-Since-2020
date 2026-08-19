from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.execution_normalizer import (  # noqa: E402
    load_instruments,
    load_settlement_evidence,
    normalize_executions,
)
from bitmex_replay.execution_price_reconciler import (  # noqa: E402
    EXACT,
    OFF_TICK_GRID,
    OBSERVED_LAST_PX_EXACT,
    OBSERVED_PRICE_COARSENED_BY_ONE_TICK,
    RECOVERED,
    RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER,
    UNRESOLVED,
    classify_price_precision_difference,
    derive_cost_implied_price,
    reconcile_execution_price,
    reconcile_execution_prices,
    validate_price_tick_grid,
)
from bitmex_replay.historical_spec_registry import load_historical_specs, resolve_specs_for_events  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402


def official_spec(evidence: str = "OFFICIAL_EXPLICIT") -> dict[str, str]:
    return {
        "spec_id": "LINKUSDT-QUANTO-XBT-2020",
        "symbol": "LINKUSDT",
        "payout_model": "QUANTO",
        "multiplier_raw": "10000",
        "tick_size": "0.0005",
        "tick_size_evidence_confidence": "OFFICIAL_EXPLICIT",
        "evidence_confidence": evidence,
    }


def link_event(*, side: str = "Buy", quantity: str = "111", last_px: str = "23.634", cost: str = "26233185") -> dict[str, str]:
    return {
        "event_time": "2020-10-16T04:00:00Z",
        "source_row_number": 2,
        "execID": "test-exec",
        "symbol": "LINKUSDT",
        "instrument_class": "DERIVATIVE",
        "execType": "Trade",
        "side": side,
        "signed_contract_qty": quantity if side == "Buy" else f"-{quantity}",
        "lastPx": last_px,
        "price": last_px,
        "avgPx": last_px,
        "execCost": cost if side == "Buy" else f"-{cost}",
    }


def test_cost_implied_price_uses_decimal_for_buy_and_sell() -> None:
    assert derive_cost_implied_price("26233185", "111", "10000") == Decimal("23.6335")
    assert derive_cost_implied_price("-26233185", "-111", "10000") == Decimal("23.6335")


def test_sign_is_not_hidden_by_absolute_value() -> None:
    assert derive_cost_implied_price("-26233185", "111", "10000") == Decimal("-23.6335")


def test_tick_grid_is_exact_and_not_equality_tolerance() -> None:
    assert validate_price_tick_grid("23.6335", "0.0005")
    assert validate_price_tick_grid("23.634", "0.0005")
    assert Decimal("23.634") != Decimal("23.6335")
    assert classify_price_precision_difference("23.634", "23.6335", "0.0005") == RECOVERED


def test_exact_last_px_is_observed_exact() -> None:
    event = link_event(last_px="23.6335")
    row = reconcile_execution_price(event, official_spec())
    assert row["price_resolution_method"] == OBSERVED_LAST_PX_EXACT
    assert row["price_precision_status"] == EXACT
    assert row["canonical_execution_price"] == "23.6335"
    assert row["canonical_exec_cost_exact"] is True


def test_precision_mismatch_recovers_only_with_official_multiplier_and_tick() -> None:
    row = reconcile_execution_price(link_event(), official_spec())
    assert row["price_resolution_method"] == RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER
    assert row["price_precision_status"] == OBSERVED_PRICE_COARSENED_BY_ONE_TICK
    assert row["canonical_execution_price"] == "23.6335"
    assert row["price_delta"] == "-0.0005"
    assert row["abs_price_delta"] == "0.0005"
    assert row["delta_in_ticks"] == "-1"
    assert row["difference_raw_per_signed_qty"] == "-5.000"


def test_off_grid_price_is_unresolved() -> None:
    row = reconcile_execution_price(link_event(last_px="23.634", cost="26233296"), official_spec())
    assert row["price_precision_status"] == OFF_TICK_GRID
    assert row["price_resolution_method"] == UNRESOLVED
    assert row["canonical_execution_price"] is None


def test_non_official_multiplier_cannot_self_validate_through_price_recovery() -> None:
    row = reconcile_execution_price(link_event(), official_spec("OFFICIAL_PARTIAL_EXECUTION_VALIDATED"))
    assert row["price_resolution_method"] == UNRESOLVED
    assert row["reconciliation_status"] == UNRESOLVED


@pytest.fixture(scope="module")
def real_precision() -> dict[str, object]:
    order_dimension = build_order_dimension(ROOT / "api-v1-order.csv")
    instruments = load_instruments(ROOT / "api-v1-instrument.all.csv")
    evidence = load_settlement_evidence(ROOT / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(ROOT / "api-v1-execution-tradeHistory.csv", order_dimension, instruments, evidence)
    registry = load_historical_specs(
        ROOT / "quant" / "config" / "historical_instrument_specs.json",
        ROOT / "api-v1-instrument.all.csv",
        "f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6",
    )
    mapping = resolve_specs_for_events(normalized["events"], registry)
    return reconcile_execution_prices(normalized["events"], registry, mapping)


def test_real_dot_and_link_rows_are_all_resolved(real_precision: dict[str, object]) -> None:
    by_spec = real_precision["summary"]["by_spec"]
    dot = by_spec["DOTUSDT-QUANTO-XBT-2021"]
    link = by_spec["LINKUSDT-QUANTO-XBT-2020"]
    assert (dot["trade_count"], dot["observed_exact_count"], dot["recovered_count"], dot["unresolved_count"]) == (3359, 1990, 1369, 0)
    assert (link["trade_count"], link["observed_exact_count"], link["recovered_count"], link["unresolved_count"]) == (232, 176, 56, 0)
    assert real_precision["summary"]["raw_lastPx_mismatch_count"] == 1425
    assert real_precision["summary"]["unresolved_count"] == 0
    assert real_precision["summary"]["canonical_reproduction_fail_count"] == 0


def test_real_price_delta_and_tick_distributions_are_explicit(real_precision: dict[str, object]) -> None:
    by_spec = real_precision["summary"]["by_spec"]
    assert set(by_spec["DOTUSDT-QUANTO-XBT-2021"]["unique_price_deltas"]) == {"-0.0005", "0", "0.0005"}
    assert set(by_spec["LINKUSDT-QUANTO-XBT-2020"]["unique_price_deltas"]) == {"-0.0005", "0", "0.0005"}
    assert by_spec["DOTUSDT-QUANTO-XBT-2021"]["cost_implied_on_tick_ratio"] == "1.000000000000"
    assert by_spec["LINKUSDT-QUANTO-XBT-2020"]["cost_implied_on_tick_ratio"] == "1.000000000000"
