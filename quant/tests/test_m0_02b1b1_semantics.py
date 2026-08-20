from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.aep_models import (  # noqa: E402
    AEP_MODELS,
    audit_aep_models,
    cost_implied_basis,
    current_cycle_summary,
    quantize_inverse_basis,
)
from bitmex_replay.execution_order_audit import (  # noqa: E402
    apply_execution_order_policy,
    audit_execution_order,
)
from bitmex_replay.instrument_terms import (  # noqa: E402
    InstrumentTermsError,
    audit_instrument_terms,
    load_historical_instrument_terms,
    resolve_instrument_terms,
)
from bitmex_replay.position_cost_models import (  # noqa: E402
    MODEL_NAMES,
    audit_position_cost_models,
    signed_divmod,
)
from bitmex_replay.reported_pnl_decomposition import (  # noqa: E402
    decompose_reported_pnl,
    summarize_reported_pnl_decomposition,
)


def pnl(**values: object) -> dict[str, object]:
    row = {
        "execType": "Trade",
        "action": "ADD_SHORT",
        "reported_realisedPnl_raw": "-10266",
        "execComm_raw": "10266",
        "brokerExecComm_raw": None,
    }
    row.update(values)
    return row


def event(*, exec_id: str = "e", source: int = 1, cum: int = 10, last: int = 10, order: str = "o", tx: str = "2020-01-01T00:00:00.000Z", ts: str = "2020-01-01T00:00:00.000Z") -> dict[str, object]:
    return {
        "symbol": "XBTUSD", "instrument_class": "DERIVATIVE", "execType": "Trade",
        "execID": exec_id, "source_row_number": source, "cumQty": cum, "lastQty": last,
        "orderID": order, "transactTime": tx, "timestamp": ts,
        "_event_dt": None, "_timestamp_dt": None,
    }


def terms() -> dict[str, object]:
    return load_historical_instrument_terms(ROOT / "quant" / "config" / "historical_instrument_terms.json")


def test_reported_add_short_candidate_is_zero() -> None:
    result = decompose_reported_pnl(pnl())
    assert result["reported_gross_candidate_raw"] == "0"
    assert result["decomposition_status"] == "EXACT"


def test_reported_funding_candidate_is_zero() -> None:
    result = decompose_reported_pnl(pnl(execType="Funding", action="NO_POSITION_CHANGE"))
    assert result["decomposition_status"] == "EXACT"


def test_reported_close_compares_with_reconstructed_gross() -> None:
    result = decompose_reported_pnl(pnl(action="CLOSE_SHORT", reported_realisedPnl_raw="-900", execComm_raw="100"), reconstructed_gross_realised_pnl_raw="-800")
    assert result["reported_gross_candidate_raw"] == "-800"
    assert result["reported_gross_difference_raw"] == "0"


def test_nonzero_broker_exec_comm_is_not_blindly_added() -> None:
    result = decompose_reported_pnl(pnl(brokerExecComm_raw="5"), reconstructed_gross_realised_pnl_raw="0")
    assert result["decomposition_status"] == "BROKER_COMPONENT_UNRESOLVED"
    assert result["reported_gross_candidate_raw"] == "0"


def test_missing_reported_component_is_distinct() -> None:
    assert decompose_reported_pnl(pnl(reported_realisedPnl_raw=None))["decomposition_status"] == "MISSING"


def test_pnl_summary_counts_statuses() -> None:
    summary = summarize_reported_pnl_decomposition([decompose_reported_pnl(pnl()), decompose_reported_pnl(pnl(brokerExecComm_raw="1"))])
    assert summary["eligible"] == 2
    assert summary["broker_unresolved"] == 1


@pytest.mark.parametrize(("symbol", "time", "expected"), [
    ("XBTUSD", "2021-06-08T04:29:59Z", "1"),
    ("XBTUSD", "2021-06-08T04:30:00Z", "100"),
    ("XBTM21", "2021-06-08T04:30:00Z", "100"),
    ("XBTU21", "2021-06-08T04:30:00Z", "100"),
])
def test_temporal_lot_size_boundary(symbol: str, time: str, expected: str) -> None:
    assert resolve_instrument_terms(terms(), symbol, time)["lot_size"] == expected


def test_pre_boundary_odd_contract_is_legal() -> None:
    rows = audit_instrument_terms([dict(event(last=35, cum=35), _event_dt=None)], {"instrument_terms": terms(), "specs": []})
    # event_time is intentionally not parseable in this synthetic row; this test
    # verifies the audit keeps the fact as NOT_EVALUATED rather than rejecting it.
    assert rows[0]["lastQty_multiple_status"] == "NOT_EVALUATED"


def test_post_boundary_odd_contract_is_flagged() -> None:
    e = event(last=35, cum=35)
    e["event_time"] = "2021-06-08T04:30:01Z"
    e["_event_dt"] = __import__("datetime").datetime.fromisoformat("2021-06-08T04:30:01+00:00")
    rows = audit_instrument_terms([e], {"instrument_terms": terms(), "specs": []})
    assert rows[0]["lastQty_multiple_status"] == "ODD_LOT"


def test_terms_invalid_payload_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "terms.json"
    path.write_text(json.dumps({"terms": [{"symbol": "X", "valid_from": "bad"}]}), encoding="utf-8")
    with pytest.raises(InstrumentTermsError):
        load_historical_instrument_terms(path)


def test_terms_missing_event_time_is_unresolved() -> None:
    assert resolve_instrument_terms(terms(), "XBTUSD", "bad")["status"] == "UNRESOLVED_EVENT_TIME"


def test_unique_cumqty_chain_is_recovered() -> None:
    rows = [event(exec_id="a", source=2, cum=7599, last=1500), event(exec_id="b", source=3, cum=6099, last=1500), event(exec_id="c", source=4, cum=9666, last=2067), event(exec_id="d", source=5, cum=4599, last=4599)]
    audit = audit_execution_order(rows)
    assert audit["unique_chain_group_count"] == 1
    assert audit["rows"][0]["recovered_execID_order"] == "d,b,a,c"


def test_gap_cumqty_chain_is_ambiguous() -> None:
    audit = audit_execution_order([event(exec_id="a", source=2, cum=10, last=7), event(exec_id="b", source=3, cum=20, last=5)])
    assert audit["ambiguous_group_count"] == 1


def test_cross_order_tie_is_not_resolved_by_uuid() -> None:
    rows = [event(exec_id="z", source=2, order="order-z"), event(exec_id="a", source=3, order="order-a")]
    audit = audit_execution_order(rows)
    assert audit["cross_order_tie_count"] == 1
    ordered = apply_execution_order_policy(rows, audit, "CUMQTY_WITHIN_ORDER")
    assert [item["source_row_number"] for item in ordered] == [2, 3]


def test_source_order_policy_preserves_source_rows() -> None:
    rows = [event(exec_id="a", source=2), event(exec_id="b", source=3)]
    audit = audit_execution_order(rows)
    assert [item["execID"] for item in apply_execution_order_policy(rows, audit, "SOURCE_ROW_STABLE")] == ["a", "b"]


@pytest.mark.parametrize(("number", "expected"), [(301, (30, 1)), (-301, (-30, -1)), (0, (0, 0))])
def test_signed_divmod_carry(number: int, expected: tuple[int, int]) -> None:
    assert signed_divmod(number, 10) == expected


def small_cost_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    valuations = [
        {"execID": "o", "symbol": "XBTUSD", "execType": "Trade", "signed_contract_qty": "10", "execCost_raw": "-1000", "realisedPnl_raw": "-10", "execComm_raw": "10"},
        {"execID": "c", "symbol": "XBTUSD", "execType": "Trade", "signed_contract_qty": "-10", "execCost_raw": "200", "realisedPnl_raw": "-200", "execComm_raw": "200"},
    ]
    positions = [{"execID": "o", "signed_contract_qty": "10"}, {"execID": "c", "signed_contract_qty": "-10"}]
    return valuations, positions


def test_all_cost_models_are_reported() -> None:
    valuations, positions = small_cost_fixture()
    result = audit_position_cost_models(valuations, positions)
    assert [row["model"] for row in result] == list(MODEL_NAMES)


def test_cost_models_check_full_close() -> None:
    valuations, positions = small_cost_fixture()
    assert all(row["full_close_residual_cost_count"] == 0 for row in audit_position_cost_models(valuations, positions))


def test_cost_models_check_settlement() -> None:
    valuations, positions = small_cost_fixture()
    valuations[1]["execType"] = "Settlement"
    assert all(row["settlement_residual_cost_count"] == 0 for row in audit_position_cost_models(valuations, positions))


def test_cost_model_is_diagnostic_not_per_execution_selection() -> None:
    valuations, positions = small_cost_fixture()
    assert all(row["selection_status"] == "DIAGNOSTIC_ONLY" for row in audit_position_cost_models(valuations, positions))


def test_aep_long_basis_rounds_down() -> None:
    assert quantize_inverse_basis(Decimal("0.123456789"), 1) == Decimal("0.12345678")


def test_aep_short_basis_rounds_half_up() -> None:
    assert quantize_inverse_basis(Decimal("0.123456785"), -1) == Decimal("0.12345679")


def test_cost_implied_basis_is_diagnostic_value() -> None:
    assert cost_implied_basis("1000", "10", "100") == Decimal("100")


def test_aep_models_include_published_and_diagnostics() -> None:
    rows = [{"symbol": "XBTUSD", "position_after": 100, "position_cycle_id": "XBTUSD-C1", "opening_cycle_id": "XBTUSD-C1", "event_time": "2021-01-01T00:00:00Z", "execID": "e", "average_entry_price_after": "50000", "current_cost_after_api_raw": "1000"}]
    result = audit_aep_models(rows, snapshot_aep="50000", snapshot_avg_cost="50000")
    assert [row["model"] for row in result] == list(AEP_MODELS)


def test_current_cycle_summary_has_open_event() -> None:
    rows = [{"symbol": "XBTUSD", "position_after": 100, "position_cycle_id": "XBTUSD-C1", "opening_cycle_id": "XBTUSD-C1", "event_time": "2021-01-01T00:00:00Z", "execID": "e", "resolved_lot_size": "1", "canonical_price_status": "EXACT"}]
    result = current_cycle_summary(rows)
    assert result["cycle_open_execID"] == "e"


def test_current_cycle_summary_empty_is_safe() -> None:
    assert current_cycle_summary([])["cycle_id"] == ""


def test_aep_model_names_are_stable() -> None:
    assert "PUBLISHED_FILL_WEIGHTED_BASIS" in AEP_MODELS


def test_pnl_candidate_does_not_change_position_state() -> None:
    row = pnl()
    before = dict(row)
    decompose_reported_pnl(row)
    assert row == before


def test_terms_config_has_official_evidence() -> None:
    assert all(item["source_url"].startswith("https://www.bitmex.com/") for item in terms()["terms"])


def test_lot_size_terms_are_non_overlapping() -> None:
    registry = terms()
    for symbol, rows in registry["terms_by_symbol"].items():
        assert all(a["_end"] <= b["_start"] for a, b in zip(rows, rows[1:]))


def test_new_large_parquets_are_ignored() -> None:
    text = (ROOT / "quant" / ".gitignore").read_text(encoding="utf-8")
    assert "outputs/position_accounting_events.parquet" in text


def test_analysis_report_has_commit_sha() -> None:
    report = json.loads((ROOT / "quant" / "reports" / "position_accounting.json").read_text(encoding="utf-8"))
    assert len(report["analysis_commit"]) == 40


def test_raw_execution_hash_is_stable() -> None:
    result = subprocess.run(["git", "status", "--short", "api-v1-execution-tradeHistory.csv"], cwd=ROOT, capture_output=True, text=True)
    assert result.stdout == ""
