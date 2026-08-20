from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.execution_normalizer import (  # noqa: E402
    assert_unique_exec_ids,
    load_instruments,
    load_settlement_evidence,
    normalize_executions,
)
from bitmex_replay.execution_price_reconciler import reconcile_execution_prices  # noqa: E402
from bitmex_replay.execution_valuation import (  # noqa: E402
    build_execution_valuation,
    load_asset_scale_registry,
)
from bitmex_replay.historical_spec_registry import (  # noqa: E402
    load_historical_specs,
    resolve_specs_for_events,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402
from bitmex_replay.position_accounting import (  # noqa: E402
    ACCOUNTING_BLOCKED,
    ACCOUNTING_ELIGIBLE,
    ACCOUNTING_ELIGIBLE_WITH_WARNING,
    BLOCKED,
    PASS,
    PositionAccountingError,
    accounting_eligibility,
    build_position_accounting,
    load_accounting_policy,
    replay_position_accounting,
    split_signed_exec_cost,
    update_average_entry,
)
from bitmex_replay.position_replayer import replay_positions  # noqa: E402


def make_policy() -> dict[str, object]:
    return {
        "candidate_rounding_modes": ["ROUND_DOWN", "ROUND_FLOOR", "ROUND_CEILING", "ROUND_HALF_UP", "ROUND_HALF_EVEN"],
        "canonical_tiebreak": {"average_cost_release": "ROUND_DOWN", "flip_exec_cost_split": "ROUND_DOWN"},
        "inverse_basis": {"decimal_places": 8, "long_rounding": "ROUND_FLOOR", "short_rounding": "ROUND_HALF_UP"},
        "snapshot_display": {"quantum": "0.0001", "rounding": "ROUND_HALF_UP"},
        "scope": {"symbol_overrides": False, "execid_overrides": False},
    }


def make_spec(*, payout_model: str = "QUANTO", lot_size: str | None = None) -> dict[str, object]:
    return {"spec_id": "S", "symbol": "TESTUSD", "payout_model": payout_model, "settlement_currency": "XBT", "lot_size": lot_size}


def make_position_event(exec_id: str, quantity: int) -> dict[str, object]:
    return {"execID": exec_id, "signed_contract_qty": str(quantity), "position_after": quantity}


def make_valuation(
    exec_id: str,
    *,
    exec_type: str = "Trade",
    quantity: int = 10,
    cost: int = -1000,
    price: int | Decimal | None = 100,
    side: str = "Buy",
    payout_model: str = "QUANTO",
    normalization_status: str = PASS,
) -> dict[str, object]:
    return {
        "event_time": f"2020-01-01T00:00:{len(exec_id):02d}.000Z",
        "source_row_number": len(exec_id),
        "execID": exec_id,
        "execType": exec_type,
        "symbol": "TESTUSD",
        "side": side,
        "signed_contract_qty": str(quantity),
        "spec_id": "S",
        "payout_model": payout_model,
        "instrument_class": "DERIVATIVE",
        "settlement_currency": "XBT",
        "execCost_raw": str(cost),
        "execComm_raw": "123",
        "realisedPnl_raw": None,
        "canonical_execution_price": None if price is None else str(price),
        "canonical_price_status": "RAW_LASTPX_PRESERVED",
        "normalization_status": normalization_status,
    }


def replay(rows: list[dict[str, object]]) -> dict[str, object]:
    position_events = {str(row["execID"]): make_position_event(str(row["execID"]), int(row["signed_contract_qty"])) for row in rows}
    return replay_position_accounting(rows, position_events, {"S": make_spec()}, make_policy(), "ROUND_DOWN", "ROUND_DOWN")




def test_warning_valuation_remains_accounting_eligible() -> None:
    assert accounting_eligibility(PASS) == ACCOUNTING_ELIGIBLE
    assert accounting_eligibility("WARNING") == ACCOUNTING_ELIGIBLE_WITH_WARNING


def test_blocked_valuation_blocks_build() -> None:
    valuation = make_valuation("blocked", quantity=10, normalization_status=BLOCKED)
    result = build_position_accounting(
        [valuation],
        [make_position_event("blocked", 10)],
        {"S": make_spec()},
        make_policy(),
    )
    assert result["status"] == BLOCKED
    assert result["events"] == []
    assert "BLOCKED" in result["blockers"][0]


def test_invalid_valuation_status_is_rejected() -> None:
    with pytest.raises(PositionAccountingError):
        accounting_eligibility("UNKNOWN")


def test_empty_input() -> None:
    result = replay([])
    assert result["rows"] == []
    assert result["terminal"] == []
    assert result["accounting_blocked_count"] == 0


def test_funding_does_not_change_qty_cost_or_aep() -> None:
    result = replay([
        make_valuation("open", quantity=10, cost=-1000, price=100),
        make_valuation("fund", exec_type="Funding", quantity=0, cost=0, price=None),
    ])
    row = result["rows"][1]
    assert row["action"] == "NO_POSITION_CHANGE"
    assert row["position_before"] == row["position_after"] == 10
    assert row["current_cost_after_api_raw"] == "-1000"
    assert row["average_entry_price_after"] == "100"
    assert row["gross_realised_pnl_api_raw"] == "0"


@pytest.mark.parametrize(
    ("name", "rows", "expected_action"),
    [
        ("open_long", [make_valuation("e1", quantity=10)], "OPEN_LONG"),
        ("add_long", [make_valuation("e1", quantity=10), make_valuation("e2", quantity=5)], "ADD_LONG"),
        ("reduce_long", [make_valuation("e1", quantity=10), make_valuation("e2", quantity=-5, cost=200)], "REDUCE_LONG"),
        ("close_long", [make_valuation("e1", quantity=10), make_valuation("e2", quantity=-10, cost=200)], "CLOSE_LONG"),
        ("flip_to_short", [make_valuation("e1", quantity=10), make_valuation("e2", quantity=-15, cost=300)], "FLIP_LONG_TO_SHORT"),
        ("open_short", [make_valuation("e1", quantity=-10, side="Sell")], "OPEN_SHORT"),
        ("add_short", [make_valuation("e1", quantity=-10, side="Sell"), make_valuation("e2", quantity=-5, side="Sell")], "ADD_SHORT"),
        ("reduce_short", [make_valuation("e1", quantity=-10, side="Sell"), make_valuation("e2", quantity=5, side="Buy", cost=-200)], "REDUCE_SHORT"),
        ("close_short", [make_valuation("e1", quantity=-10, side="Sell"), make_valuation("e2", quantity=10, side="Buy", cost=-200)], "CLOSE_SHORT"),
        ("flip_to_long", [make_valuation("e1", quantity=-10, side="Sell"), make_valuation("e2", quantity=15, side="Buy", cost=-300)], "FLIP_SHORT_TO_LONG"),
    ],
)
def test_action_classification(name: str, rows: list[dict[str, object]], expected_action: str) -> None:
    del name
    assert replay(rows)["rows"][-1]["action"] == expected_action


def test_no_position_change_funding_action() -> None:
    result = replay([make_valuation("fund", exec_type="Funding", quantity=0, cost=0, price=None)])
    assert result["rows"][0]["action"] == "NO_POSITION_CHANGE"


def test_full_close_releases_all_current_cost() -> None:
    result = replay([
        make_valuation("open", quantity=10, cost=-1000),
        make_valuation("close", quantity=-10, cost=200),
    ])
    row = result["rows"][1]
    assert row["released_open_cost_exact_raw"] == "-1000"
    assert row["current_cost_after_api_raw"] == "0"
    assert row["average_entry_price_after"] is None


def test_partial_close_uses_average_cost_proportion() -> None:
    result = replay([
        make_valuation("open", quantity=10, cost=-1000),
        make_valuation("reduce", quantity=-4, cost=200),
    ])
    row = result["rows"][1]
    assert row["released_open_cost_exact_raw"] == "-400"
    assert row["current_cost_after_api_raw"] == "-600"
    assert row["gross_realised_pnl_exact_raw"] == "200"


def test_realised_cost_and_gross_pnl_identity() -> None:
    row = replay([
        make_valuation("open", quantity=10, cost=-1000),
        make_valuation("reduce", quantity=-4, cost=200),
    ])["rows"][1]
    assert Decimal(row["realised_cost_delta_exact_raw"]) == Decimal("-200")
    assert Decimal(row["gross_realised_pnl_exact_raw"]) == -Decimal(row["realised_cost_delta_exact_raw"])
    assert row["exact_conservation_status"] == PASS
    assert row["api_conservation_status"] == PASS


def test_flip_cost_split_preserves_signed_original_cost() -> None:
    split = split_signed_exec_cost("-301", 10, 5, -15, "ROUND_HALF_UP")
    assert split["close_api"] + split["open_api"] == Decimal("-301")
    assert split["close_api"] == Decimal("-201")
    assert split["open_api"] == Decimal("-100")


def test_flip_new_cost_does_not_inherit_old_cost() -> None:
    row = replay([
        make_valuation("open", quantity=10, cost=-1000),
        make_valuation("flip", quantity=-15, cost=300),
    ])["rows"][1]
    assert row["position_after"] == -5
    assert row["current_cost_after_api_raw"] == "100"
    assert row["open_exec_cost_api_raw"] == "100"


def test_flip_new_aep_resets() -> None:
    rows = [
        make_valuation("open", quantity=10, price=100),
        make_valuation("flip", quantity=-15, price=200, cost=300),
    ]
    result = replay(rows)
    assert result["rows"][0]["average_entry_price_after"] == "100"
    assert result["rows"][1]["average_entry_price_after"] == "200"
    assert result["rows"][1]["closing_cycle_id"] == "TESTUSD-C0001"
    assert result["rows"][1]["opening_cycle_id"] == "TESTUSD-C0002"


def test_reduction_does_not_change_aep() -> None:
    result = replay([
        make_valuation("open", quantity=10, price=100),
        make_valuation("reduce", quantity=-4, price=999, cost=200),
    ])
    assert result["rows"][1]["average_entry_price_after"] == "100"


def test_quanto_weighted_aep() -> None:
    result = replay([
        make_valuation("e1", quantity=10, price=100),
        make_valuation("e2", quantity=5, price=200),
    ])
    assert Decimal(result["rows"][1]["average_entry_price_after"]).quantize(Decimal("0.00000001")) == Decimal("133.33333333")


def test_linear_weighted_aep() -> None:
    rows = [make_valuation("e1", quantity=10, price=100, payout_model="LINEAR"), make_valuation("e2", quantity=5, price=200, payout_model="LINEAR")]
    assert Decimal(replay(rows)["rows"][1]["average_entry_price_after"]).quantize(Decimal("0.00000001")) == Decimal("133.33333333")


def test_inverse_long_basis_uses_eight_place_floor() -> None:
    price = Decimal(1000000000) / Decimal("123456785")
    aep, basis = update_average_entry(
        before_price=None,
        before_basis=None,
        position_before=0,
        position_after=1,
        open_qty_abs=1,
        fill_price=price,
        payout_model="INVERSE",
        spec=make_spec(payout_model="INVERSE", lot_size="1"),
        policy=make_policy(),
        reset_on_flip=False,
    )
    assert basis == Decimal("0.12345678")
    assert aep == Decimal("1") / Decimal("0.12345678")


def test_inverse_short_basis_uses_eight_place_round() -> None:
    price = Decimal(1000000000) / Decimal("123456785")
    _, basis = update_average_entry(
        before_price=None,
        before_basis=None,
        position_before=0,
        position_after=-1,
        open_qty_abs=1,
        fill_price=price,
        payout_model="INVERSE",
        spec=make_spec(payout_model="INVERSE", lot_size="1"),
        policy=make_policy(),
        reset_on_flip=False,
    )
    assert basis == Decimal("0.12345679")


def test_inverse_missing_lot_size_blocks_aep() -> None:
    with pytest.raises(PositionAccountingError):
        update_average_entry(
            before_price=None,
            before_basis=None,
            position_before=0,
            position_after=1,
            open_qty_abs=1,
            fill_price=Decimal("100"),
            payout_model="INVERSE",
            spec=make_spec(payout_model="INVERSE", lot_size=None),
            policy=make_policy(),
            reset_on_flip=False,
        )


def test_avgpx_is_not_used_as_fill_price() -> None:
    valuation = make_valuation("e1", quantity=1, price=123)
    valuation["avgPx"] = "999"
    row = replay([valuation])["rows"][0]
    assert row["average_entry_price_after"] == "123"


def test_canonical_recovered_price_is_used() -> None:
    valuation = make_valuation("e1", quantity=1, price=321)
    valuation["canonical_price_status"] = "AUDITED_RECOVERED_FROM_EXECCOST"
    valuation["lastPx"] = "999"
    assert replay([valuation])["rows"][0]["average_entry_price_after"] == "321"


def test_raw_lastpx_preserved_trade_is_allowed() -> None:
    valuation = make_valuation("e1", quantity=1, price=321)
    valuation["canonical_price_status"] = "RAW_LASTPX_PRESERVED"
    assert replay([valuation])["accounting_blocked_count"] == 0


def test_settlement_completely_closes_position() -> None:
    result = replay([
        make_valuation("open", quantity=10, cost=-1000),
        make_valuation("settle", exec_type="Settlement", quantity=-10, cost=200),
    ])
    row = result["rows"][1]
    assert row["position_after"] == 0
    assert row["current_cost_after_api_raw"] == "0"
    assert row["average_entry_price_after"] is None
    assert result["settlement_residual_cost_count"] == 0


def test_position_cycles_open_close_and_flip() -> None:
    result = replay([
        make_valuation("e1", quantity=10),
        make_valuation("e2", quantity=-10, cost=100),
        make_valuation("e3", quantity=-5, side="Sell"),
    ])
    assert result["rows"][0]["opening_cycle_id"] == "TESTUSD-C0001"
    assert result["rows"][1]["closing_cycle_id"] == "TESTUSD-C0001"
    assert result["rows"][2]["opening_cycle_id"] == "TESTUSD-C0002"


def test_reported_realised_pnl_does_not_update_state() -> None:
    valuation = make_valuation("e1", quantity=10, cost=-1000)
    valuation["realisedPnl_raw"] = "999999"
    row = replay([valuation])["rows"][0]
    assert row["current_cost_after_api_raw"] == "-1000"
    assert row["gross_realised_pnl_api_raw"] == "0"


def test_exec_comm_is_not_added_to_gross_realised_pnl() -> None:
    valuation = make_valuation("e1", quantity=10, cost=-1000)
    valuation["execComm_raw"] = "123456"
    row = replay([valuation])["rows"][0]
    assert row["gross_realised_pnl_api_raw"] == "0"


def test_funding_is_not_added_to_gross_trading_pnl() -> None:
    result = replay([make_valuation("fund", exec_type="Funding", quantity=0, cost=0, price=None)])
    assert result["reported_pnl"]["exact"] == 0
    assert result["rows"][0]["gross_realised_pnl_exact_raw"] == "0"


def test_invalid_payout_model_blocks_row() -> None:
    result = replay([make_valuation("bad", quantity=1, payout_model="UNKNOWN")])
    assert result["accounting_blocked_count"] == 1
    assert result["rows"][0]["accounting_status"] == ACCOUNTING_BLOCKED


def test_invalid_rounding_policy_is_rejected() -> None:
    with pytest.raises(PositionAccountingError):
        replay_position_accounting([], {}, {}, make_policy(), "INVALID", "ROUND_DOWN")


@pytest.mark.parametrize("mode", ["ROUND_DOWN", "ROUND_FLOOR", "ROUND_CEILING", "ROUND_HALF_UP", "ROUND_HALF_EVEN"])
def test_all_candidate_rounding_modes_are_executable(mode: str) -> None:
    rows = [make_valuation("e1", quantity=10), make_valuation("e2", quantity=-4, cost=201)]
    position_events = {row["execID"]: make_position_event(row["execID"], int(row["signed_contract_qty"])) for row in rows}
    result = replay_position_accounting(rows, position_events, {"S": make_spec()}, make_policy(), mode, mode)
    assert result["accounting_blocked_count"] == 0


@pytest.mark.parametrize("cost", ["-301", "301", "0", "-1", "1"])
def test_signed_flip_split_always_conserves_original(cost: str) -> None:
    split = split_signed_exec_cost(cost, 10, 5, -15, "ROUND_HALF_EVEN")
    assert split["close_api"] + split["open_api"] == Decimal(cost)


def test_conflicting_symbol_override_policy_is_rejected(tmp_path: Path) -> None:
    payload = make_policy()
    payload["scope"]["symbol_overrides"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PositionAccountingError):
        load_accounting_policy(path)


@pytest.fixture(scope="module")
def real_dataset() -> dict[str, object]:
    protected = [
        "api-v1-execution-tradeHistory.csv", "api-v1-order.csv", "api-v1-user-walletHistory.csv",
        "api-v1-position.snapshot.csv", "api-v1-user-wallet.snapshot-all.csv", "api-v1-user-margin.snapshot-all.csv",
        "api-v1-instrument.all.csv", "api-v1-wallet-assets.csv", "derived-equity-curve.csv", "manifest.json",
    ]
    before = hash_files(ROOT, protected)
    order = build_order_dimension(ROOT / "api-v1-order.csv")
    instruments = load_instruments(ROOT / "api-v1-instrument.all.csv")
    evidence = load_settlement_evidence(ROOT / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(ROOT / "api-v1-execution-tradeHistory.csv", order, instruments, evidence)
    assert_unique_exec_ids(normalized)
    position_replay = replay_positions(normalized["events"])
    registry = load_historical_specs(
        ROOT / "quant" / "config" / "historical_instrument_specs.json",
        ROOT / "api-v1-instrument.all.csv",
        "test-source",
    )
    mapping = resolve_specs_for_events(normalized["events"], registry)
    price = reconcile_execution_prices(normalized["events"], registry, mapping)
    assets = load_asset_scale_registry(ROOT / "api-v1-wallet-assets.csv")
    valuation = build_execution_valuation(normalized["events"], registry, mapping, assets, price_reconciliation=price)
    specs = {str(spec.get("spec_id")): spec for spec in registry.get("specs", [])}
    policy = load_accounting_policy(ROOT / "quant" / "config" / "position_accounting_policy.json")
    accounting = replay_position_accounting(
        valuation["valuations"],
        {row["execID"]: row for row in position_replay["position_events"]},
        specs,
        policy,
        "ROUND_DOWN",
        "ROUND_DOWN",
        collect_rows=True,
    )
    after = hash_files(ROOT, protected)
    return {
        "normalized": normalized,
        "position_replay": position_replay,
        "valuation": valuation,
        "accounting": accounting,
        "before_hashes": before,
        "after_hashes": after,
        "built_from_raw": True,
    }


def test_real_dataset_full_coverage(real_dataset: dict[str, object]) -> None:
    assert len(real_dataset["accounting"]["rows"]) == 173226
    assert real_dataset["built_from_raw"] is True


def test_real_dataset_type_counts(real_dataset: dict[str, object]) -> None:
    counts = Counter(row["execType"] for row in real_dataset["valuation"]["valuations"])
    assert counts == Counter({"Trade": 160302, "Funding": 12905, "Settlement": 19})


def test_real_dataset_eligibility_counts(real_dataset: dict[str, object]) -> None:
    counts = Counter(row["normalization_status"] for row in real_dataset["valuation"]["valuations"])
    assert counts[PASS] == 22926
    assert counts["WARNING"] == 150300
    assert counts[BLOCKED] == 0


def test_real_dataset_actions(real_dataset: dict[str, object]) -> None:
    counts = Counter(row["action"] for row in real_dataset["accounting"]["rows"])
    assert counts["OPEN_LONG"] == 898
    assert counts["ADD_LONG"] == 50952
    assert counts["REDUCE_LONG"] == 53580
    assert counts["CLOSE_LONG"] == 886
    assert counts["OPEN_SHORT"] == 333
    assert counts["ADD_SHORT"] == 27978
    assert counts["REDUCE_SHORT"] == 25180
    assert counts["CLOSE_SHORT"] == 344
    assert counts["FLIP_LONG_TO_SHORT"] == 91
    assert counts["FLIP_SHORT_TO_LONG"] == 79


def test_real_dataset_funding_and_settlement(real_dataset: dict[str, object]) -> None:
    rows = real_dataset["accounting"]["rows"]
    funding = [row for row in rows if row["execType"] == "Funding"]
    settlements = [row for row in rows if row["execType"] == "Settlement"]
    assert len(funding) == 12905
    assert all(row["position_before"] == row["position_after"] for row in funding)
    assert len(settlements) == 19
    assert all(row["position_after"] == 0 and row["current_cost_after_api_raw"] == "0" for row in settlements)


def test_real_dataset_position_after_matches_m0_02a(real_dataset: dict[str, object]) -> None:
    expected = {row["execID"]: row["position_after"] for row in real_dataset["position_replay"]["position_events"]}
    assert all(row["position_after"] == expected[row["execID"]] for row in real_dataset["accounting"]["rows"])


def test_real_dataset_conservation(real_dataset: dict[str, object]) -> None:
    result = real_dataset["accounting"]
    assert result["exact_conservation_failure_count"] == 0
    assert result["api_conservation_failure_count"] == 0
    assert result["flip_exec_cost_split_failure_count"] == 0
    assert result["full_close_residual_cost_count"] == 0
    assert result["settlement_residual_cost_count"] == 0


def test_real_dataset_xbtusd_terminal_quantity_and_cost(real_dataset: dict[str, object]) -> None:
    xbt = next(row for row in real_dataset["accounting"]["terminal"] if row["symbol"] == "XBTUSD")
    assert xbt["position_qty"] == -998000
    assert xbt["current_cost_api_raw"] == "1386445848"


def test_real_dataset_flat_and_nonzero_terminal_symbols(real_dataset: dict[str, object]) -> None:
    terminal = real_dataset["accounting"]["terminal"]
    assert all(row["position_qty"] != 0 or row["current_cost_api_raw"] == "0" for row in terminal)
    assert [row["symbol"] for row in terminal if row["position_qty"] != 0] == ["XBTUSD"]


def test_real_dataset_raw_hashes_unchanged(real_dataset: dict[str, object]) -> None:
    assert real_dataset["before_hashes"] == real_dataset["after_hashes"]


def test_real_report_is_compact_and_analysis_commit_is_sha() -> None:
    report = json.loads((ROOT / "quant" / "reports" / "position_accounting.json").read_text(encoding="utf-8"))
    assert len(report["analysis_commit"]) == 40
    assert "events" not in report
    assert "cycles" not in report


def test_large_position_parquet_is_not_tracked() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "quant/outputs/position_accounting_events.parquet"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def make_policy() -> dict[str, object]:
    return {
        "candidate_rounding_modes": ["ROUND_DOWN", "ROUND_FLOOR", "ROUND_CEILING", "ROUND_HALF_UP", "ROUND_HALF_EVEN"],
        "canonical_tiebreak": {"average_cost_release": "ROUND_DOWN", "flip_exec_cost_split": "ROUND_DOWN"},
        "inverse_basis": {"decimal_places": 8, "long_rounding": "ROUND_FLOOR", "short_rounding": "ROUND_HALF_UP"},
        "snapshot_display": {"quantum": "0.0001", "rounding": "ROUND_HALF_UP"},
        "scope": {"symbol_overrides": False, "execid_overrides": False},
    }


def make_spec(*, payout_model: str = "QUANTO", lot_size: str | None = None) -> dict[str, object]:
    return {"spec_id": "S", "symbol": "TESTUSD", "payout_model": payout_model, "settlement_currency": "XBT", "lot_size": lot_size}


def make_position_event(exec_id: str, quantity: int) -> dict[str, object]:
    return {"execID": exec_id, "signed_contract_qty": str(quantity), "position_after": quantity}


def make_valuation(
    exec_id: str,
    *,
    exec_type: str = "Trade",
    quantity: int = 10,
    cost: int = -1000,
    price: int | Decimal | None = 100,
    side: str = "Buy",
    payout_model: str = "QUANTO",
    normalization_status: str = PASS,
) -> dict[str, object]:
    return {
        "event_time": f"2020-01-01T00:00:{len(exec_id):02d}.000Z",
        "source_row_number": len(exec_id),
        "execID": exec_id,
        "execType": exec_type,
        "symbol": "TESTUSD",
        "side": side,
        "signed_contract_qty": str(quantity),
        "spec_id": "S",
        "payout_model": payout_model,
        "instrument_class": "DERIVATIVE",
        "settlement_currency": "XBT",
        "execCost_raw": str(cost),
        "execComm_raw": "123",
        "realisedPnl_raw": None,
        "canonical_execution_price": None if price is None else str(price),
        "canonical_price_status": "RAW_LASTPX_PRESERVED",
        "normalization_status": normalization_status,
    }


def replay(rows: list[dict[str, object]]) -> dict[str, object]:
    position_events = {str(row["execID"]): make_position_event(str(row["execID"]), int(row["signed_contract_qty"])) for row in rows}
    return replay_position_accounting(rows, position_events, {"S": make_spec()}, make_policy(), "ROUND_DOWN", "ROUND_DOWN")
