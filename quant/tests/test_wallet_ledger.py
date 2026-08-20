from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.wallet_ledger import (  # noqa: E402
    build_daily_wallet_ledger,
    compare_wallet_execution_aggregates,
    load_asset_scale_registry,
    load_wallet_ledger,
    normalize_wallet_row,
    reconcile_equity_curve,
    summarize_wallet_by_type,
)


def assets() -> dict[str, dict[str, object]]:
    return {"XBT": {"scale": 8, "currency": "XBT"}, "USDT": {"scale": 6, "currency": "USDT"}}


def wallet_row(**updates: str) -> dict[str, str]:
    row = {
        "timestamp": "2020-01-01T00:00:00Z", "transactTime": "2020-01-01T00:00:00Z",
        "transactType": "Deposit", "transactStatus": "Completed", "currency": "XBt",
        "network": "", "amount": "100000000", "fee": "0", "walletBalance": "100000000",
        "orderID": "", "transactID": "t1", "address": "", "marginBalance": "",
    }
    row.update(updates)
    return row


def test_normalize_wallet_row_preserves_raw_and_major() -> None:
    row = normalize_wallet_row(2, wallet_row(), assets())
    assert row["currency"] == "XBT"
    assert row["amount_raw"] == "100000000"
    assert row["amount_major"] == "1"
    assert row["wallet_type_group"] == "DEPOSIT"


def test_wallet_ledger_continuity_passes(tmp_path: Path) -> None:
    path = tmp_path / "wallet.csv"
    fieldnames = list(wallet_row().keys())
    import csv
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(wallet_row())
        writer.writerow(wallet_row(timestamp="2020-01-02T00:00:00Z", transactTime="2020-01-02T00:00:00Z", amount="5", walletBalance="100000005", transactID="t2"))
    rows = load_wallet_ledger(path, assets())
    assert [row["continuity_status"] for row in rows] == ["BASELINE_FIRST_OBSERVATION", "PASS"]


def test_wallet_ledger_daily_aggregation() -> None:
    rows = [normalize_wallet_row(2, wallet_row(), assets()), normalize_wallet_row(3, wallet_row(amount="5", walletBalance="100000005", transactID="t2"), assets())]
    daily = build_daily_wallet_ledger(rows)
    assert daily[0]["event_count"] == 2
    assert daily[0]["net_amount_raw"] == "100000005"


def test_wallet_ledger_batches_same_final_balance(tmp_path: Path) -> None:
    path = tmp_path / "wallet.csv"
    fieldnames = list(wallet_row().keys())
    import csv
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(wallet_row())
        writer.writerow(wallet_row(timestamp="2020-01-02T00:00:00Z", transactTime="2020-01-02T00:00:00Z", amount="-2", walletBalance="99999995", transactID="t2"))
        writer.writerow(wallet_row(timestamp="2020-01-02T00:00:00Z", transactTime="2020-01-02T00:00:00Z", amount="-3", walletBalance="99999995", transactID="t3"))
    loaded = load_wallet_ledger(path, assets())
    assert [row["continuity_status"] for row in loaded] == ["BASELINE_FIRST_OBSERVATION", "PASS", "PASS"]
    assert loaded[1]["continuity_batch_row_count"] == 2
    assert loaded[1]["balance_expected_delta_raw"] == "-5"


def test_wallet_ledger_uses_timestamp_for_balance_order(tmp_path: Path) -> None:
    path = tmp_path / "wallet.csv"
    fieldnames = list(wallet_row().keys())
    import csv
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(wallet_row(timestamp="2020-01-01T02:00:00Z", transactTime="2020-01-01T01:00:00Z", amount="100", walletBalance="100"))
        writer.writerow(wallet_row(timestamp="2020-01-01T03:00:00Z", transactTime="2020-01-01T01:30:00Z", amount="5", walletBalance="105", transactID="t2"))
    loaded = load_wallet_ledger(path, assets())
    assert [row["continuity_status"] for row in loaded] == ["BASELINE_FIRST_OBSERVATION", "PASS"]


def test_wallet_type_summary_separates_conversion() -> None:
    rows = [normalize_wallet_row(2, wallet_row(transactType="Conversion", amount="-5"), assets())]
    summary = summarize_wallet_by_type(rows)
    assert summary[0]["wallet_type_group"] == "CONVERSION"


def test_pending_rows_do_not_enter_completed_daily_ledger() -> None:
    rows = [normalize_wallet_row(2, wallet_row(transactStatus="Pending"), assets())]
    assert build_daily_wallet_ledger(rows) == []


def test_unknown_wallet_type_is_retained_as_other() -> None:
    row = normalize_wallet_row(2, wallet_row(transactType="NewFutureType"), assets())
    assert row["wallet_type_group"] == "OTHER"


def test_execution_comparison_is_aggregate_only() -> None:
    wallet = [{"transactType": "RealisedPNL", "currency": "XBT", "amount_raw_completed_sum": "10"}]
    execution = [{"execType": "Trade", "currency": "XBT", "realisedPnl_raw_sum": "8", "execComm_raw_sum": "0", "execution_count": 1}]
    result = compare_wallet_execution_aggregates(wallet, execution)
    assert result[0]["status"] == "AGGREGATE_DIFFERENCE"
    assert "one-to-one" in result[0]["note"]


def test_real_asset_registry_loads() -> None:
    registry = load_asset_scale_registry(ROOT / "api-v1-wallet-assets.csv")
    assert registry["XBT"]["scale"] == 8


def test_equity_curve_reconciliation_reads_stream_rows(tmp_path: Path) -> None:
    rows = [normalize_wallet_row(2, wallet_row(), assets())]
    path = tmp_path / "equity.csv"
    path.write_text("timestamp,walletBalanceXBT\n2020-01-01T00:00:00Z,1\n", encoding="utf-8")
    result = reconcile_equity_curve(rows, path)
    assert result["status"] == "PASS"
    assert result["equity_row_count"] == 1
