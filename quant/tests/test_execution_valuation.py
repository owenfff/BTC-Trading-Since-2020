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
from bitmex_replay.execution_price_reconciler import reconcile_execution_prices  # noqa: E402
from bitmex_replay.execution_valuation import (  # noqa: E402
    AssetScaleError,
    FUNDING_PAYMENT,
    MISSING,
    NON_INTEGER_RAW_AMOUNT,
    POSITION_COST,
    REPORTED_REALISED_PNL,
    SETTLEMENT_COMMISSION,
    SETTLEMENT_POSITION_VALUE_REFERENCE,
    TRADE_FEE_OR_REBATE,
    build_component_ledger,
    build_execution_valuation,
    classify_execution_components,
    load_asset_scale_registry,
    major_to_raw,
    normalize_currency_code,
    normalize_execution_value,
    parse_raw_integer_decimal,
    raw_to_major,
    summarize_execution_valuation,
    validate_raw_major_roundtrip,
)
from bitmex_replay.historical_spec_registry import (  # noqa: E402
    load_historical_specs,
    resolve_specs_for_events,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402


ASSETS = {
    "XBT": {"currency": "XBT", "scale": 8},
    "USDT": {"currency": "USDT", "scale": 6},
}


def make_spec(
    *,
    spec_id: str = "TEST-XBT",
    symbol: str = "TESTUSD",
    settlement_currency: str = "XBT",
) -> dict[str, object]:
    return {
        "spec_id": spec_id,
        "symbol": symbol,
        "payout_model": "QUANTO",
        "settlement_currency": settlement_currency,
    }


def make_event(
    *,
    exec_type: str = "Trade",
    exec_id: str = "exec-1",
    symbol: str = "TESTUSD",
    settlement_currency: str = "XBt",
    commission_currency: str = "XBt",
    exec_cost: str = "100000000",
    exec_comm: str = "-1000",
    realised_pnl: str = "2000",
    instrument_class: str = "DERIVATIVE",
) -> dict[str, object]:
    return {
        "event_time": "2021-01-01T00:00:00Z",
        "source_row_number": 2,
        "execID": exec_id,
        "execType": exec_type,
        "symbol": symbol,
        "side": "Buy",
        "signed_contract_qty": 10,
        "instrument_class": instrument_class,
        "instrument_typ": "FFWCSX",
        "settlCurrency": settlement_currency,
        "execCommCcy": commission_currency,
        "execCost": exec_cost,
        "execComm": exec_comm,
        "realisedPnl": realised_pnl,
        "commission": "0.0001",
        "lastPx": "100",
        "avgPx": "100",
        "homeNotional": "0.1",
        "foreignNotional": "1000",
        "lastLiquidityInd": "AddedLiquidity",
    }


def test_currency_aliases_are_normalized_without_conversion() -> None:
    assert normalize_currency_code("XBt") == "XBT"
    assert normalize_currency_code("USDt") == "USDT"
    assert normalize_currency_code("xbt") == "XBT"


def test_xbt_scale_eight_conversion_is_decimal() -> None:
    assert raw_to_major("100000000", "XBt", ASSETS) == Decimal("1")
    assert major_to_raw("1.25", "XBT", ASSETS) == Decimal("125000000")


def test_usdt_scale_six_conversion_is_decimal() -> None:
    assert raw_to_major("1000000", "USDT", ASSETS) == Decimal("1")
    assert major_to_raw("1.25", "USDT", ASSETS) == Decimal("1250000")


def test_negative_amount_sign_is_preserved() -> None:
    assert raw_to_major("-125000000", "XBT", ASSETS) == Decimal("-1.25")


def test_raw_major_raw_roundtrip_is_exact() -> None:
    result = validate_raw_major_roundtrip("-125000000", "XBT", ASSETS)
    assert result["status"] == "PASS"
    assert result["raw"] == "-125000000"
    assert result["roundtrip_raw"] == "-125000000"


def test_integer_like_raw_amount_is_accepted() -> None:
    assert parse_raw_integer_decimal("1000.000") == Decimal("1000")


def test_fractional_raw_amount_is_blocked() -> None:
    with pytest.raises(ValueError) as error:
        parse_raw_integer_decimal("1000.5")
    assert getattr(error.value, "status") == NON_INTEGER_RAW_AMOUNT


def test_missing_is_distinct_from_zero() -> None:
    assert parse_raw_integer_decimal("") is None
    assert parse_raw_integer_decimal("0") == Decimal("0")
    assert validate_raw_major_roundtrip("", "XBT", ASSETS)["status"] == MISSING


def test_missing_asset_scale_is_blocked() -> None:
    with pytest.raises(AssetScaleError):
        raw_to_major("1", "DOGE", ASSETS)


def test_currency_conflict_blocks_execution_value() -> None:
    event = make_event(settlement_currency="USDT")
    result = normalize_execution_value(event, make_spec(settlement_currency="XBT"), ASSETS)
    assert result["normalization_status"] == "BLOCKED"
    assert "settlement currency conflict" in result["normalization_reason"]


def test_trade_exec_cost_is_position_cost() -> None:
    definitions = {item["source_field"]: item for item in classify_execution_components(make_event())}
    assert definitions["execCost"]["component_type"] == POSITION_COST
    assert definitions["execCost"]["is_wallet_cashflow_candidate"] is False


def test_trade_exec_comm_is_fee_or_rebate() -> None:
    definitions = {item["source_field"]: item for item in classify_execution_components(make_event())}
    assert definitions["execComm"]["component_type"] == TRADE_FEE_OR_REBATE


def test_funding_exec_comm_is_funding_payment() -> None:
    definitions = {item["source_field"]: item for item in classify_execution_components(make_event(exec_type="Funding"))}
    assert definitions["execComm"]["component_type"] == FUNDING_PAYMENT


def test_funding_exec_cost_is_not_funding_payment() -> None:
    definitions = {item["source_field"]: item for item in classify_execution_components(make_event(exec_type="Funding"))}
    assert definitions["execCost"]["component_type"] != FUNDING_PAYMENT


def test_settlement_exec_comm_is_settlement_commission() -> None:
    definitions = {item["source_field"]: item for item in classify_execution_components(make_event(exec_type="Settlement"))}
    assert definitions["execComm"]["component_type"] == SETTLEMENT_COMMISSION
    assert definitions["execCost"]["component_type"] == SETTLEMENT_POSITION_VALUE_REFERENCE


def test_realised_pnl_is_independent_overlap_component() -> None:
    valuation = normalize_execution_value(make_event(), make_spec(), ASSETS)
    components = build_component_ledger([valuation])
    realised = [row for row in components if row["component_type"] == REPORTED_REALISED_PNL]
    assert len(realised) == 1
    assert "OVERLAP" in realised[0]["overlap_status"]


def test_realised_pnl_is_not_summed_into_fee_or_cost() -> None:
    valuation = normalize_execution_value(make_event(), make_spec(), ASSETS)
    components = build_component_ledger([valuation])
    summary = summarize_execution_valuation([valuation], components)
    types = {row["component_type"] for row in summary["component_summary"]}
    assert POSITION_COST in types
    assert TRADE_FEE_OR_REBATE in types
    assert REPORTED_REALISED_PNL in types
    assert summary["component_type_counts"][REPORTED_REALISED_PNL] == 1


def test_no_cross_currency_total_is_created() -> None:
    xbt = normalize_execution_value(make_event(), make_spec(), ASSETS)
    usdt_event = make_event(
        exec_id="exec-usdt",
        symbol="TESTUSDT",
        settlement_currency="USDT",
        commission_currency="USDT",
        exec_cost="1000000",
        exec_comm="-100",
        realised_pnl="200",
    )
    usdt = normalize_execution_value(
        usdt_event,
        make_spec(spec_id="TEST-USDT", symbol="TESTUSDT", settlement_currency="USDT"),
        ASSETS,
    )
    summary = summarize_execution_valuation([xbt, usdt], build_component_ledger([xbt, usdt]))
    currencies = {(row["component_type"], row["currency"]) for row in summary["component_summary"]}
    assert (POSITION_COST, "XBT") in currencies
    assert (POSITION_COST, "USDT") in currencies
    assert not any("total" in row for row in summary["component_summary"])


def test_spot_is_excluded_from_valuation_build() -> None:
    derivative = make_event(exec_id="derivative")
    spot = make_event(exec_id="spot", instrument_class="SPOT")
    mapping = [{
        "execID": "derivative",
        "spec_id": "TEST-XBT",
        "spec_resolution_status": "MATCHED",
        "compatibility_status": "PASS",
    }]
    result = build_execution_valuation(
        [derivative, spot],
        {"specs": [make_spec()]},
        mapping,
        ASSETS,
    )
    assert [row["execID"] for row in result["valuations"]] == ["derivative"]


def test_empty_build_has_no_rows() -> None:
    result = build_execution_valuation([], {"specs": []}, [], ASSETS)
    assert result["valuations"] == []
    assert result["components"] == []
    assert result["summary"]["execution_count"] == 0


def test_corrupt_asset_scale_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wallet-assets.csv"
    path.write_text("currency,majorCurrency,scale\nXBt,XBT,8.5\n", encoding="utf-8")
    with pytest.raises(AssetScaleError):
        load_asset_scale_registry(path)


@pytest.fixture(scope="module")
def real_valuation() -> dict[str, object]:
    order = build_order_dimension(ROOT / "api-v1-order.csv")
    instruments = load_instruments(ROOT / "api-v1-instrument.all.csv")
    evidence = load_settlement_evidence(ROOT / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(ROOT / "api-v1-execution-tradeHistory.csv", order, instruments, evidence)
    registry = load_historical_specs(
        ROOT / "quant" / "config" / "historical_instrument_specs.json",
        ROOT / "api-v1-instrument.all.csv",
        "f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6",
    )
    mapping = resolve_specs_for_events(normalized["events"], registry)
    price = reconcile_execution_prices(normalized["events"], registry, mapping)
    assets = load_asset_scale_registry(ROOT / "api-v1-wallet-assets.csv")
    result = build_execution_valuation(
        normalized["events"], registry, mapping, assets, price_reconciliation=price
    )
    return {
        "normalized": normalized,
        "mapping": mapping,
        "price": price,
        "result": result,
    }


def test_real_output_has_one_row_per_derivative_execution(real_valuation: dict[str, object]) -> None:
    normalized = real_valuation["normalized"]
    result = real_valuation["result"]
    derivative_count = sum(event["instrument_class"] == "DERIVATIVE" for event in normalized["events"])
    assert derivative_count == 173226
    assert len(result["valuations"]) == 173226
    assert len({row["execID"] for row in result["valuations"]}) == 173226
    assert all(row["instrument_class"] == "DERIVATIVE" for row in result["valuations"])


def test_real_execution_type_counts_are_preserved(real_valuation: dict[str, object]) -> None:
    counts = {}
    for row in real_valuation["result"]["valuations"]:
        counts[row["execType"]] = counts.get(row["execType"], 0) + 1
    assert counts == {"Trade": 160302, "Funding": 12905, "Settlement": 19}


def test_real_components_are_long_form_and_nonempty(real_valuation: dict[str, object]) -> None:
    components = real_valuation["result"]["components"]
    assert components
    assert all(":" in row["component_id"] for row in components)
    assert all(row["currency"] for row in components)
    assert all(row["source_field"] in {"execCost", "execComm", "realisedPnl"} for row in components)


def test_real_canonical_price_counts_match_m0_02b0_2(real_valuation: dict[str, object]) -> None:
    summary = real_valuation["result"]["summary"]
    price_summary = real_valuation["price"]["summary"]
    assert summary["canonical_historical_exact_count"] == 5809
    assert summary["canonical_historical_recovered_count"] == 1425
    assert summary["canonical_historical_unresolved_count"] == 0
    assert price_summary["canonical_reproduction_fail_count"] == 0


def test_real_funding_does_not_change_contract_quantity(real_valuation: dict[str, object]) -> None:
    funding = [row for row in real_valuation["result"]["valuations"] if row["execType"] == "Funding"]
    assert len(funding) == 12905
    assert all(row["signed_contract_qty"] == "0" for row in funding)
    funding_cost_components = [
        row for row in real_valuation["result"]["components"]
        if row["execType"] == "Funding" and row["source_field"] == "execCost"
    ]
    assert funding_cost_components
    assert all(row["component_type"] != FUNDING_PAYMENT for row in funding_cost_components)


def test_real_settlements_have_scale_and_no_trade_position_cost(real_valuation: dict[str, object]) -> None:
    settlements = [row for row in real_valuation["result"]["valuations"] if row["execType"] == "Settlement"]
    assert len(settlements) == 19
    assert all(row["settlement_asset_scale"] is not None for row in settlements)
    assert all(row["position_cost_role"] != POSITION_COST for row in settlements)
    assert all(row["normalization_status"] != "BLOCKED" for row in settlements)


def test_real_raw_hashes_remain_unchanged(real_valuation: dict[str, object]) -> None:
    protected = [
        "api-v1-execution-tradeHistory.csv",
        "api-v1-order.csv",
        "api-v1-user-walletHistory.csv",
        "api-v1-position.snapshot.csv",
        "api-v1-user-wallet.snapshot-all.csv",
        "api-v1-user-margin.snapshot-all.csv",
        "api-v1-instrument.all.csv",
        "api-v1-wallet-assets.csv",
        "derived-equity-curve.csv",
        "manifest.json",
    ]
    before = hash_files(ROOT, protected)
    _ = real_valuation["result"]["valuations"]
    after = hash_files(ROOT, protected)
    assert before == after
