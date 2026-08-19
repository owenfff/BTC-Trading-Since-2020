from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.execution_normalizer import (  # noqa: E402
    assert_unique_exec_ids,
    build_instrument_temporal_audit,
    load_settlement_evidence,
    load_instruments,
    normalize_executions,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.instrument_metadata import classify_instrument_typ  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402
from bitmex_replay.position_replayer import classify_action, replay_positions  # noqa: E402
from bitmex_replay.reconciliation import reconcile_snapshot  # noqa: E402


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


EXEC_HEADERS = [
    "timestamp", "transactTime", "execID", "execType", "symbol", "side",
    "orderQty", "lastQty", "cumQty", "leavesQty", "price", "lastPx", "avgPx",
    "currency", "settlCurrency", "execCost", "execComm", "realisedPnl",
    "homeNotional", "foreignNotional", "orderID", "ordType", "ordStatus",
]
ORDER_HEADERS = ["timestamp", "orderID", "ordStatus", "symbol", "side", "orderQty"]


def execution_row(
    exec_id: str,
    *,
    exec_type: str = "Trade",
    symbol: str = "XBTUSD",
    side: str = "Buy",
    last_qty: object = 10,
    order_id: str = "order-1",
    timestamp: str = "2020-01-01T00:00:00Z",
) -> list[object]:
    values = {
        "timestamp": timestamp,
        "transactTime": timestamp,
        "execID": exec_id,
        "execType": exec_type,
        "symbol": symbol,
        "side": side,
        "orderQty": 10,
        "lastQty": last_qty,
        "cumQty": 10,
        "leavesQty": 0,
        "price": "100",
        "lastPx": "100",
        "avgPx": "100",
        "currency": "XBt",
        "settlCurrency": "XBt",
        "execCost": "1000",
        "execComm": "1",
        "realisedPnl": "0",
        "homeNotional": "0.1",
        "foreignNotional": "10",
        "orderID": order_id,
        "ordType": "Limit",
        "ordStatus": "Filled",
    }
    return [values[header] for header in EXEC_HEADERS]


def make_inputs(tmp_path: Path, execution_rows: list[list[object]], order_rows: list[list[object]] | None = None) -> tuple[Path, Path, Path]:
    execution_path = tmp_path / "execution.csv"
    order_path = tmp_path / "order.csv"
    instrument_path = tmp_path / "instrument.csv"
    write_csv(execution_path, EXEC_HEADERS, execution_rows)
    write_csv(order_path, ORDER_HEADERS, order_rows or [["2020-01-01T00:00:00Z", "order-1", "Filled", "XBTUSD", "Buy", 10]])
    write_csv(instrument_path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [["XBTUSD", "FFWCSX", "2019-01-01T00:00:00Z", "", "", "XBt", "Open"]])
    return execution_path, order_path, instrument_path


@pytest.mark.parametrize(
    ("before", "signed", "after", "expected"),
    [
        (0, 10, 10, "OPEN_LONG"),
        (10, 5, 15, "ADD_LONG"),
        (10, -5, 5, "REDUCE_LONG"),
        (10, -10, 0, "CLOSE_LONG"),
        (10, -15, -5, "FLIP_LONG_TO_SHORT"),
        (0, -10, -10, "OPEN_SHORT"),
        (-10, -5, -15, "ADD_SHORT"),
        (-10, 5, -5, "REDUCE_SHORT"),
        (-10, 10, 0, "CLOSE_SHORT"),
        (-10, 15, 5, "FLIP_SHORT_TO_LONG"),
    ],
)
def test_classify_all_position_actions(before: int, signed: int, after: int, expected: str) -> None:
    assert classify_action(before, signed, after) == expected


def test_order_dimension_deduplicates_exact_rows_without_expanding_join(tmp_path: Path) -> None:
    duplicate_order = ["2020-01-01T00:00:00Z", "order-1", "Filled", "XBTUSD", "Buy", 10]
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("exec-1")], [duplicate_order, duplicate_order])
    dimension = build_order_dimension(order_path)
    normalized = normalize_executions(execution_path, dimension, load_instruments(instrument_path))
    assert dimension.rows_read == 2
    assert dimension.duplicate_full_rows == 1
    assert dimension.unique_order_ids == 1
    assert len(normalized["events"]) == 1
    assert normalized["events"][0]["order_join_status"] == "MATCHED"


def test_unmatched_and_missing_trade_order_id_are_retained(tmp_path: Path) -> None:
    execution_rows = [execution_row("exec-unmatched", order_id="missing-order"), execution_row("exec-no-order", order_id="")]
    execution_path, order_path, instrument_path = make_inputs(tmp_path, execution_rows)
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    assert len(normalized["events"]) == 2
    assert [event["order_join_status"] for event in normalized["events"]] == ["UNMATCHED", "NO_ORDER_ID"]
    assert all(event["signed_qty"] == 10 for event in normalized["events"])


def test_funding_is_retained_as_cashflow_only(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("fund-1", exec_type="Funding", side="", last_qty="", order_id="")])
    event = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))["events"][0]
    assert event["normalization_status"] == "OK"
    assert event["position_effect"] == "CASHFLOW_ONLY"
    assert event["signed_qty"] == 0


def test_settlement_applies_only_when_instrument_is_expiring(tmp_path: Path) -> None:
    settlement = execution_row("settle-1", exec_type="Settlement", side="Sell", last_qty=25, order_id="")
    trade = execution_row("trade-1", last_qty=25)
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [trade, settlement])
    write_csv(instrument_path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [["XBTUSD", "FFWCSX", "2019-01-01T00:00:00Z", "2020-03-27T08:00:00Z", "XBT", "XBt", "Settled"]])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    replay_positions(normalized["events"])
    event = next(event for event in normalized["events"] if event["execType"] == "Settlement")
    assert event["settlement_status"] == "APPLIED_POSITION_DELTA"
    assert event["position_effect"] == "POSITION_DELTA"
    assert event["signed_qty"] == -25
    assert event["position_before"] == 25
    assert event["position_after"] == 0


def test_settlement_without_expiry_is_unresolved(tmp_path: Path) -> None:
    settlement = execution_row("settle-1", exec_type="Settlement", side="Sell", last_qty=25, order_id="")
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("trade-1", last_qty=25), settlement])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    replay_positions(normalized["events"])
    event = next(event for event in normalized["events"] if event["execType"] == "Settlement")
    assert event["settlement_status"] == "UNRESOLVED"
    assert event["normalization_status"] == "UNRESOLVED"
    assert event["signed_qty"] == 0


def test_same_timestamp_uses_source_row_as_stable_tiebreaker(tmp_path: Path) -> None:
    rows = [
        execution_row("exec-2", timestamp="2020-01-01T00:00:00Z"),
        execution_row("exec-1", timestamp="2020-01-01T00:00:00Z"),
    ]
    execution_path, order_path, instrument_path = make_inputs(tmp_path, rows)
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    assert [event["execID"] for event in normalized["events"]] == ["exec-2", "exec-1"]
    assert [event["source_row_number"] for event in normalized["events"]] == [2, 3]


def test_duplicate_exec_id_is_rejected(tmp_path: Path) -> None:
    rows = [execution_row("duplicate"), execution_row("duplicate", timestamp="2020-01-01T00:00:01Z")]
    execution_path, order_path, instrument_path = make_inputs(tmp_path, rows)
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    with pytest.raises(AssertionError, match="Duplicate execID"):
        assert_unique_exec_ids(normalized)


def test_invalid_trade_is_reported_and_not_applied(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("bad", side="Other", last_qty=0)])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    assert normalized["events"][0]["normalization_status"] == "ERROR"
    assert replay_positions(normalized["events"])["terminal_positions"][0]["reconstructed_position"] == 0


@pytest.mark.parametrize("last_qty", [0, -1, "not-an-integer"])
def test_non_positive_or_unparseable_last_qty_is_reported(tmp_path: Path, last_qty: object) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("bad-qty", last_qty=last_qty)])
    event = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))["events"][0]
    assert event["normalization_status"] == "ERROR"
    assert event["signed_qty"] == 0


def test_reconciliation_passes_and_fails(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("exec-1")])
    events = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))["events"]
    position_events = replay_positions(events)["position_events"]
    snapshot = {"symbol": "XBTUSD", "timestamp": "2020-01-01T00:00:01Z", "currentQty": 10}
    assert reconcile_snapshot(position_events, snapshot)["reconciliation_status"] == "PASS"
    snapshot["currentQty"] = 11
    assert reconcile_snapshot(position_events, snapshot)["reconciliation_status"] == "FAIL"


def test_empty_inputs_produce_empty_outputs(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [])
    dimension = build_order_dimension(order_path)
    normalized = normalize_executions(execution_path, dimension, load_instruments(instrument_path))
    assert dimension.rows_read == 1
    assert normalized["raw_rows"] == 0
    assert normalized["events"] == []
    assert replay_positions(normalized["events"])["position_events"] == []


def test_protected_hash_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "protected.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    before = hash_files(tmp_path, ["protected.csv"])
    after = hash_files(tmp_path, ["protected.csv"])
    assert before == after


def test_instrument_typ_classifies_spot() -> None:
    assert classify_instrument_typ("IFXXXP") == "SPOT"
    assert classify_instrument_typ("FFWCSX") == "DERIVATIVE"
    assert classify_instrument_typ("MRBXXX") == "REFERENCE_INDEX"
    assert classify_instrument_typ("not-known") == "UNKNOWN"


def test_spot_trade_is_retained_but_does_not_change_derivative_position(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("spot-1", symbol="BMEX_USDT")])
    write_csv(instrument_path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [["BMEX_USDT", "IFXXXP", "2022-01-01T00:00:00Z", "", "", "", "Open"]])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    replay = replay_positions(normalized["events"])
    event = normalized["events"][0]
    assert len(normalized["events"]) == 1
    assert event["instrument_class"] == "SPOT"
    assert event["position_effect"] == "SPOT_BALANCE_DELTA"
    assert event["normalization_status"] == "OK_SPOT_TRADE"
    assert event["signed_contract_qty"] == 0
    assert replay["position_events"][0]["action"] == "NO_POSITION_CHANGE"
    assert replay["terminal_derivative_positions"] == []
    assert replay["spot_execution_summary"][0]["trade_count"] == 1


def test_unknown_trade_is_not_defaulted_to_derivative(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("unknown-1", symbol="UNKNOWN")])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    event = normalized["events"][0]
    assert event["instrument_class"] == "UNKNOWN"
    assert event["normalization_status"] == "ERROR"
    assert event["signed_contract_qty"] == 0


def test_historical_settlement_evidence_closes_aave_position(tmp_path: Path) -> None:
    evidence_path = tmp_path / "historical_settlement_evidence.json"
    evidence_path.write_text(json.dumps({"settlements": [{
        "symbol": "AAVEUSDT",
        "execID": "aave-settle",
        "announced_settlement_time": "2021-11-02T12:00:00Z",
        "resolution": "OFFICIAL_EARLY_SETTLEMENT",
        "source_title": "Early settlement",
        "source_url": "https://example.test/aave",
    }]}), encoding="utf-8")
    evidence = load_settlement_evidence(evidence_path)
    settlement = execution_row("aave-settle", exec_type="Settlement", symbol="AAVEUSDT", side="Sell", last_qty=7439, order_id="", timestamp="2021-11-02T11:59:59.999Z")
    trade = execution_row("aave-trade", symbol="AAVEUSDT", side="Buy", last_qty=7439, timestamp="2021-11-02T11:00:00Z")
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [trade, settlement])
    write_csv(instrument_path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [["AAVEUSDT", "FFWCSX", "2024-09-04T12:00:00Z", "", "", "USDt", "Open"]])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path), evidence)
    replay = replay_positions(normalized["events"])
    event = next(event for event in normalized["events"] if event["execType"] == "Settlement")
    assert event["instrument_temporal_status"] == "SYMBOL_REUSE_SUSPECTED"
    assert event["settlement_status"] == "APPLIED_POSITION_DELTA"
    assert event["position_before"] == 7439
    assert event["signed_contract_qty"] == -7439
    assert event["position_after"] == 0
    assert event["settlement_resolution_method"] == "OFFICIAL_EARLY_SETTLEMENT_AND_POSITION_CLOSE_INVARIANT"
    assert next(row for row in replay["terminal_positions"] if row["symbol"] == "AAVEUSDT")["reconstructed_position"] == 0


@pytest.mark.parametrize(
    ("side", "qty"),
    [("Sell", 5), ("Buy", 15)],
)
def test_settlement_that_does_not_fully_close_is_error(tmp_path: Path, side: str, qty: int) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("trade-1", last_qty=10), execution_row("settle-1", exec_type="Settlement", side=side, last_qty=qty, order_id="")])
    write_csv(instrument_path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [["XBTUSD", "FFWCSX", "2019-01-01T00:00:00Z", "2020-03-27T08:00:00Z", "XBT", "XBt", "Settled"]])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    replay_positions(normalized["events"])
    event = next(event for event in normalized["events"] if event["execType"] == "Settlement")
    assert event["settlement_status"] == "ERROR"
    assert event["normalization_status"] == "ERROR"
    assert event["position_after"] == 10


def test_instrument_temporal_audit_marks_execution_before_listing(tmp_path: Path) -> None:
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [execution_row("early-1", timestamp="2020-01-01T00:00:00Z")])
    write_csv(instrument_path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [["XBTUSD", "FFWCSX", "2021-01-01T00:00:00Z", "", "", "XBt", "Open"]])
    normalized = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))
    audit = build_instrument_temporal_audit(normalized["events"], load_instruments(instrument_path))
    assert audit[0]["metadata_temporal_status"] == "EXECUTION_BEFORE_CURRENT_LISTING"
    assert audit[0]["requires_historical_spec"] is True


def test_instrument_metadata_records_are_not_silently_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "instrument.csv"
    write_csv(path, ["symbol", "typ", "listing", "expiry", "settle", "settlCurrency", "state"], [
        ["REUSED", "FFWCSX", "2020-01-01T00:00:00Z", "", "", "XBt", "Settled"],
        ["REUSED", "FFWCSX", "2024-01-01T00:00:00Z", "", "", "USDt", "Open"],
    ])
    records = load_instruments(path)
    assert len(records["REUSED"]) == 2
