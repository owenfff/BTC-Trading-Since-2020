from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.execution_normalizer import (  # noqa: E402
    assert_unique_exec_ids,
    load_instruments,
    normalize_executions,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402
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
    write_csv(instrument_path, ["symbol", "expiry", "settle", "settlCurrency"], [["XBTUSD", "", "", "XBt"]])
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
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [settlement])
    write_csv(instrument_path, ["symbol", "expiry", "settle", "settlCurrency"], [["XBTUSD", "2020-03-27T08:00:00Z", "XBT", "XBt"]])
    event = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))["events"][0]
    assert event["settlement_status"] == "APPLIED_POSITION_DELTA"
    assert event["position_effect"] == "POSITION_DELTA"
    assert event["signed_qty"] == -25


def test_settlement_without_expiry_is_unresolved(tmp_path: Path) -> None:
    settlement = execution_row("settle-1", exec_type="Settlement", side="Sell", last_qty=25, order_id="")
    execution_path, order_path, instrument_path = make_inputs(tmp_path, [settlement])
    event = normalize_executions(execution_path, build_order_dimension(order_path), load_instruments(instrument_path))["events"][0]
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
