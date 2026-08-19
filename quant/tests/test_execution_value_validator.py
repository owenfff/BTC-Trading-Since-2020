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
from bitmex_replay.execution_value_validator import (  # noqa: E402
    PARTIAL_EVIDENCE,
    build_multiplier_validation_report,
    load_wallet_asset_scales,
    normalize_raw_settlement_amount,
    validate_configured_multiplier,
    validate_partial_evidence_specs,
)
from bitmex_replay.historical_spec_registry import (  # noqa: E402
    load_historical_specs,
    resolve_specs_for_events,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402


WALLET_ASSETS = {"XBT": {"scale": 8}, "USDT": {"scale": 6}}
CONFIG = ROOT / "quant" / "config" / "historical_instrument_specs.json"
INSTRUMENTS = ROOT / "api-v1-instrument.all.csv"
PROTECTED_FILES = [
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


def make_spec(multiplier_raw: str = "100", evidence: str = PARTIAL_EVIDENCE) -> dict[str, object]:
    return {
        "spec_id": "TEST-QUANTO",
        "symbol": "TESTUSDT",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to_exclusive": "2022-01-01T00:00:00Z",
        "typ": "FFWCSX",
        "instrument_class": "DERIVATIVE",
        "payout_model": "QUANTO",
        "underlying": None,
        "quote_currency": "USDT",
        "settlement_currency": "XBT",
        "margin_currency": "XBT",
        "is_inverse": False,
        "is_quanto": True,
        "multiplier_major": "0.000001",
        "multiplier_currency": "XBT",
        "multiplier_raw": multiplier_raw,
        "evidence_confidence": evidence,
        "sources": [{"source_type": "TEST", "source_url": "https://example.invalid"}],
    }


def make_event(exec_id: str = "e1", *, side: str = "Buy", qty: int = 10, px: str = "2", cost: str | None = "2000", exec_type: str = "Trade") -> dict[str, object]:
    signed = qty if side == "Buy" else -qty
    return {
        "execID": exec_id,
        "event_time": "2020-06-01T00:00:00Z",
        "instrument_class": "DERIVATIVE",
        "execType": exec_type,
        "symbol": "TESTUSDT",
        "side": side,
        "signed_contract_qty": signed,
        "lastPx": px,
        "execCost": cost or "",
        "settlCurrency": "XBt",
    }


def validation_for(events: list[dict[str, object]], *, multiplier_raw: str = "100", evidence: str = PARTIAL_EVIDENCE) -> dict[str, object]:
    spec = make_spec(multiplier_raw, evidence)
    registry = {"specs": [spec], "configured_specs": [spec]}
    mapping = [{"execID": event["execID"], "spec_id": "TEST-QUANTO"} for event in events]
    return validate_configured_multiplier(events, registry, mapping, WALLET_ASSETS)


@pytest.fixture(scope="module")
def real_validation() -> dict[str, object]:
    order_dimension = build_order_dimension(ROOT / "api-v1-order.csv")
    instruments = load_instruments(INSTRUMENTS)
    evidence = load_settlement_evidence(ROOT / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(ROOT / "api-v1-execution-tradeHistory.csv", order_dimension, instruments, evidence)
    registry = load_historical_specs(CONFIG, INSTRUMENTS, "f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6")
    mapping = resolve_specs_for_events(normalized["events"], registry)
    assets = load_wallet_asset_scales(ROOT / "api-v1-wallet-assets.csv")
    validation = validate_configured_multiplier(normalized["events"], registry, mapping, assets)
    partial = validate_partial_evidence_specs(validation)
    report = build_multiplier_validation_report(validation)
    return {"normalized": normalized, "mapping": mapping, "registry": registry, "validation": validation, "partial": partial, "report": report}


def test_decimal_normalization_uses_decimal_and_wallet_scale() -> None:
    value = normalize_raw_settlement_amount("123456789", "XBt", WALLET_ASSETS)
    assert isinstance(value, Decimal)
    assert value == Decimal("1.23456789")


def test_quanto_buy_exec_cost_sign_is_positive() -> None:
    result = validation_for([make_event(side="Buy", cost="2000")])
    row = result["rows"][0]
    assert row["exact_match_count"] == 1
    assert row["sign_validation_status"] == "PASS"


def test_quanto_sell_exec_cost_sign_is_negative() -> None:
    result = validation_for([make_event(side="Sell", cost="-2000")])
    row = result["rows"][0]
    assert row["exact_match_count"] == 1
    assert row["sign_validation_status"] == "PASS"


def test_correct_multiplier_is_exact_match() -> None:
    result = validation_for([make_event(qty=3, px="12.5", cost="3750")])
    assert result["exact_count"] == 1
    assert result["mismatch_count"] == 0


def test_wrong_multiplier_is_mismatch() -> None:
    result = validation_for([make_event(qty=3, px="12.5", cost="3750")], multiplier_raw="101")
    row = result["rows"][0]
    assert row["exact_match_count"] == 0
    assert row["mismatch_count"] == 1
    assert row["multiplier_validation_status"] == "BLOCKED_MISMATCH"


def test_absolute_value_cannot_hide_sign_conflict() -> None:
    result = validation_for([make_event(side="Buy", cost="-2000")])
    row = result["rows"][0]
    assert row["mismatch_count"] == 1
    assert row["sign_validation_status"] == "CONFLICT"
    assert row["exact_match_count"] == 0


def test_missing_exec_cost_is_not_eligible_or_exact() -> None:
    result = validation_for([make_event(cost=None)])
    row = result["rows"][0]
    assert row["eligible_validation_count"] == 0
    assert row["exact_match_count"] == 0
    assert row["multiplier_validation_status"] == "BLOCKED_NO_ELIGIBLE_ROWS"


def test_zero_eligible_partial_evidence_is_blocked() -> None:
    validation = validation_for([make_event(cost=None)])
    partial = validate_partial_evidence_specs(validation)
    assert partial["all_passed"] is False
    assert partial["rows"][0]["effective_evidence_confidence"] == "UNRESOLVED"


def test_declared_partial_evidence_does_not_directly_become_effective() -> None:
    validation = validation_for([make_event(cost="2010")])
    assert validation["rows"][0]["declared_evidence_confidence"] == PARTIAL_EVIDENCE
    partial = validate_partial_evidence_specs(validation)
    assert partial["rows"][0]["effective_evidence_confidence"] == "EXECUTION_INFERRED"


def test_real_uni_validation_passes_without_ignored_parquet(real_validation: dict[str, object]) -> None:
    row = next(item for item in real_validation["report"]["rows"] if item["symbol"] == "UNIUSDT")
    assert row["eligible_validation_count"] == row["exact_match_count"]
    assert row["eligible_validation_count"] == 806
    assert row["mismatch_count"] == 0
    assert row["multiplier_validation_status"] == "PASS"


def test_real_xlm_validation_passes_without_ignored_parquet(real_validation: dict[str, object]) -> None:
    row = next(item for item in real_validation["report"]["rows"] if item["symbol"] == "XLMUSDT")
    assert row["eligible_validation_count"] == row["exact_match_count"]
    assert row["eligible_validation_count"] == 53
    assert row["mismatch_count"] == 0
    assert row["multiplier_validation_status"] == "PASS"


def test_real_uni_counts_are_dynamic_and_exact(real_validation: dict[str, object]) -> None:
    row = next(item for item in real_validation["report"]["rows"] if item["symbol"] == "UNIUSDT")
    assert int(row["eligible_validation_count"]) == int(row["exact_match_count"])
    assert row["match_ratio"] == "1.000000000000"


def test_real_xlm_counts_are_dynamic_and_exact(real_validation: dict[str, object]) -> None:
    row = next(item for item in real_validation["report"]["rows"] if item["symbol"] == "XLMUSDT")
    assert int(row["eligible_validation_count"]) == int(row["exact_match_count"])
    assert row["match_ratio"] == "1.000000000000"


def test_all_eleven_historical_specs_get_diagnostics(real_validation: dict[str, object]) -> None:
    rows = real_validation["report"]["rows"]
    assert len(rows) == 11
    assert {row["symbol"] for row in rows} == {
        "AAVEUSDT", "ADAUSDT", "BNBUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
        "LUNAUSD", "ORDIUSD", "TRXUSDT", "UNIUSDT", "XLMUSDT",
    }


def test_lastpx_mismatch_blocks_multiplier_gate(real_validation: dict[str, object]) -> None:
    rows = real_validation["report"]["rows"]
    assert any(row["mismatch_count"] > 0 and row["multiplier_validation_status"] == "BLOCKED_MISMATCH" for row in rows)
    assert real_validation["partial"]["all_passed"] is True


def test_all_passed_partial_validation_is_ready_for_partial_specs() -> None:
    validation = validation_for([make_event(cost="2000")])
    partial = validate_partial_evidence_specs(validation)
    assert partial["all_passed"] is True
    assert partial["rows"][0]["effective_evidence_confidence"] == PARTIAL_EVIDENCE


def test_raw_hashes_are_unchanged_after_real_validation(real_validation: dict[str, object]) -> None:
    before = hash_files(ROOT, PROTECTED_FILES)
    _ = real_validation["report"]
    after = hash_files(ROOT, PROTECTED_FILES)
    assert before == after


def test_spot_is_excluded_from_multiplier_validation() -> None:
    result = validation_for([{
        **make_event(),
        "instrument_class": "SPOT",
    }])
    assert result["eligible_count"] == 0
    assert result["rows"][0]["derivative_trade_count"] == 0


def test_funding_is_excluded_from_trade_multiplier_denominator() -> None:
    result = validation_for([make_event(exec_type="Funding")])
    assert result["eligible_count"] == 0
    assert result["rows"][0]["derivative_trade_count"] == 0


def test_settlement_is_excluded_and_separately_not_counted_as_trade() -> None:
    result = validation_for([make_event(exec_type="Settlement")])
    assert result["eligible_count"] == 0
    assert result["rows"][0]["derivative_trade_count"] == 0


def test_real_mapping_is_built_from_events_not_ignored_parquet(real_validation: dict[str, object]) -> None:
    mapping = real_validation["mapping"]
    assert len(mapping) == 173226
    assert all(row["spec_resolution_status"] == "MATCHED" for row in mapping)
