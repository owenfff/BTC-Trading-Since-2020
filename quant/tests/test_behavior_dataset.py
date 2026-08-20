from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from behavior.confidence import overall_confidence, ordering_confidence  # noqa: E402
from behavior.decision_episodes import build_decision_episodes  # noqa: E402
from behavior.execution_batches import build_execution_batches  # noqa: E402
from behavior.order_episodes import build_order_episodes, build_trade_actions  # noqa: E402
from behavior.trade_cycles import build_trade_cycles  # noqa: E402


def event(exec_id: str, when: str, *, order_id: str = "o1", qty: int = 10, signed: int = 10, before: int = 0, after: int = 10, action: str = "OPEN_LONG", cum: int = 10) -> dict[str, object]:
    return {
        "execID": exec_id, "event_time": when, "timestamp": when, "source_row_number": len(exec_id),
        "symbol": "XBTUSD", "instrument_class": "DERIVATIVE", "execType": "Trade", "side": "Buy" if signed > 0 else "Sell",
        "orderID": order_id, "lastQty": qty, "signed_contract_qty": signed, "signed_qty": signed,
        "cumQty": cum, "position_before": before, "position_after": after, "action": action,
        "crossed_zero": "FLIP" in action, "normalization_status": "OK", "order_join_status": "MATCHED",
        "ordType": "Limit", "lastPx": "100", "price": "100", "timeInForce": "GoodTillCancel",
    }


def valuation(exec_id: str, *, fee: str = "1", pnl: str = "0") -> dict[str, object]:
    return {"execID": exec_id, "canonical_execution_price": "100", "canonical_price_status": "EXACT", "normalization_status": "PASS", "execCost_raw": "-100", "execComm_raw": fee, "realisedPnl_raw": pnl, "settlement_currency": "XBT"}


def accounting(exec_id: str, *, pnl: str = "0", cycle: str = "XBTUSD-C0001") -> dict[str, object]:
    return {"execID": exec_id, "accounting_status": "ACCOUNTING_ELIGIBLE", "accounting_eligibility": "ACCOUNTING_ELIGIBLE", "gross_realised_pnl_exact_raw": pnl, "reported_realisedPnl_raw": pnl, "position_cycle_id": cycle}


def test_confidence_keeps_ambiguous_order_low() -> None:
    assert ordering_confidence("AMBIGUOUS") == "LOW"
    assert overall_confidence("LOW", "HIGH", "HIGH", "HIGH", "AGGREGATE_ONLY") == "LOW"


def test_execution_batches_split_on_time_gap() -> None:
    rows = [event("e1", "2020-01-01T00:00:00Z", cum=10), event("e2", "2020-01-01T00:01:00Z", cum=20), event("e3", "2020-01-01T08:00:00Z", cum=30)]
    batches, mapping = build_execution_batches(rows)
    assert len(batches) == 2
    assert mapping["e1"] == mapping["e2"]
    assert mapping["e3"] != mapping["e1"]


def test_order_episode_aggregates_multiple_fills() -> None:
    rows = [event("e1", "2020-01-01T00:00:00Z", qty=10, signed=10, before=0, after=10, cum=10), event("e2", "2020-01-01T00:00:01Z", qty=5, signed=5, before=10, after=15, cum=15)]
    dimension = SimpleNamespace(dimension={"o1": {"orderQty": "15", "ordStatus": "Filled", "ordType": "Limit", "_version_count": "2"}})
    v = {"e1": valuation("e1"), "e2": valuation("e2")}
    a = {"e1": accounting("e1"), "e2": accounting("e2")}
    episodes = build_order_episodes(rows, dimension, v, a)
    assert len(episodes) == 1
    assert episodes[0]["execution_count"] == 2
    assert episodes[0]["filled_qty"] == 15
    assert episodes[0]["action"] == "OPEN_LONG"


def test_decisions_include_hold_and_no_trade_samples() -> None:
    rows = [event("e1", "2020-01-01T00:00:00Z", before=0, after=10), event("e2", "2020-01-03T00:00:00Z", before=10, after=0, signed=-10, action="CLOSE_LONG")]
    order_rows = [{"order_episode_id": "XBTUSD-o1", "symbol": "XBTUSD", "first_event_time": "2020-01-01T00:00:00Z", "action": "OPEN_LONG", "position_before": 0, "position_after": 10, "signed_contract_qty": 10, "execution_count": 1}]
    decisions = build_decision_episodes(order_rows, rows)
    assert any(row["action"] == "HOLD_LONG" for row in decisions)


def test_trade_actions_and_cycle_close() -> None:
    rows = [
        event("e1", "2020-01-01T00:00:00Z", before=0, after=10, action="OPEN_LONG"),
        event("e2", "2020-01-01T01:00:00Z", before=10, after=0, signed=-10, action="CLOSE_LONG", cum=20),
    ]
    v = {"e1": valuation("e1"), "e2": valuation("e2", pnl="25")}
    a = {"e1": accounting("e1"), "e2": accounting("e2", pnl="25")}
    actions = build_trade_actions(rows, v, a)
    cycles = build_trade_cycles(rows, v, a)
    assert [row["action"] for row in actions] == ["OPEN_LONG", "CLOSE_LONG"]
    assert len(cycles) == 1
    assert cycles[0]["close_type"] == "FULL_CLOSE"
    assert cycles[0]["terminal_qty"] == 0
    assert cycles[0]["gross_pnl_analytical"] == "25"
