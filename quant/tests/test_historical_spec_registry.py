from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.historical_spec_registry import (  # noqa: E402
    load_historical_specs,
    normalize_currency,
    resolve_spec,
    resolve_specs_for_events,
    validate_execution_spec_compatibility,
    validate_spec_intervals,
    validate_spec_schema,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402


CONFIG = ROOT / "quant" / "config" / "historical_instrument_specs.json"
INSTRUMENTS = ROOT / "api-v1-instrument.all.csv"
MAPPING = ROOT / "quant" / "outputs" / "execution_spec_mapping.parquet"
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


def spec(
    spec_id: str = "TEST-OLD",
    symbol: str = "TESTUSD",
    valid_from: str = "2020-01-01T00:00:00Z",
    valid_to: str = "2021-01-01T00:00:00Z",
    *,
    payout_model: str = "QUANTO",
    is_inverse: bool = False,
    is_quanto: bool = True,
) -> dict[str, object]:
    return {
        "spec_id": spec_id,
        "symbol": symbol,
        "valid_from": valid_from,
        "valid_to_exclusive": valid_to,
        "typ": "FFWCSX",
        "instrument_class": "DERIVATIVE",
        "payout_model": payout_model,
        "underlying": ".TESTT",
        "quote_currency": "USDT",
        "settlement_currency": "XBT",
        "margin_currency": "XBT",
        "is_inverse": is_inverse,
        "is_quanto": is_quanto,
        "multiplier_major": "0.001",
        "multiplier_currency": "XBT",
        "multiplier_raw": "100000",
        "lot_size": None,
        "tick_size": None,
        "evidence_confidence": "OFFICIAL_EXPLICIT",
        "sources": [{"source_type": "TEST", "source_url": "https://example.invalid/spec"}],
    }


@pytest.fixture(scope="module")
def registry() -> dict[str, object]:
    return load_historical_specs(CONFIG, INSTRUMENTS, "f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6")


def test_decimal_multiplier_configuration_has_no_float_values() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    for item in payload["specs"]:
        for field in ("multiplier_major", "multiplier_raw", "lot_size", "tick_size"):
            assert item[field] is None or isinstance(item[field], str)


def test_interval_is_left_closed_and_right_open() -> None:
    registry = {"specs": [spec()]}
    assert resolve_spec(registry, "TESTUSD", "2020-01-01T00:00:00Z")["status"] == "MATCHED"
    assert resolve_spec(registry, "TESTUSD", "2021-01-01T00:00:00Z")["status"] == "MISSING_SPEC"


def test_boundary_one_millisecond_before_matches_old_version() -> None:
    old = spec(valid_to="2021-01-01T00:00:00Z")
    new = spec("TEST-NEW", valid_from="2021-01-01T00:00:00Z", valid_to="2022-01-01T00:00:00Z")
    result = resolve_spec({"specs": [old, new]}, "TESTUSD", "2020-12-31T23:59:59.999Z")
    assert result["spec"]["spec_id"] == "TEST-OLD"


def test_boundary_exactly_matches_new_version() -> None:
    old = spec(valid_to="2021-01-01T00:00:00Z")
    new = spec("TEST-NEW", valid_from="2021-01-01T00:00:00Z", valid_to="2022-01-01T00:00:00Z")
    result = resolve_spec({"specs": [old, new]}, "TESTUSD", "2021-01-01T00:00:00Z")
    assert result["spec"]["spec_id"] == "TEST-NEW"


def test_same_symbol_multiple_versions_resolve_by_time() -> None:
    versions = [
        spec(valid_to="2021-01-01T00:00:00Z"),
        spec("TEST-NEW", valid_from="2021-01-01T00:00:00Z", valid_to="2022-01-01T00:00:00Z"),
    ]
    assert resolve_spec({"specs": versions}, "TESTUSD", "2020-06-01T00:00:00Z")["spec"]["spec_id"] == "TEST-OLD"
    assert resolve_spec({"specs": versions}, "TESTUSD", "2021-06-01T00:00:00Z")["spec"]["spec_id"] == "TEST-NEW"


def test_overlapping_intervals_are_reported() -> None:
    errors = validate_spec_intervals([
        spec(valid_to="2021-06-01T00:00:00Z"),
        spec("TEST-NEW", valid_from="2021-05-01T00:00:00Z", valid_to="2022-01-01T00:00:00Z"),
    ])
    assert any("OVERLAPPING_SPECS" in error for error in errors)


def test_event_without_spec_is_missing_spec() -> None:
    result = resolve_spec({"specs": [spec()]}, "UNKNOWNUSD", "2020-06-01T00:00:00Z")
    assert result["status"] == "MISSING_SPEC"


def test_event_matching_multiple_specs_is_not_silently_latest() -> None:
    first = spec(valid_to="2021-06-01T00:00:00Z")
    second = spec("TEST-OVERLAP", valid_from="2021-05-01T00:00:00Z", valid_to="2022-01-01T00:00:00Z")
    result = resolve_spec({"specs": [first, second]}, "TESTUSD", "2021-05-15T00:00:00Z")
    assert result["status"] == "OVERLAPPING_SPECS"
    assert result["spec"] is None
    assert len(result["matches"]) == 2


def test_aave_2021_resolves_to_old_quanto(registry: dict[str, object]) -> None:
    result = resolve_spec(registry, "AAVEUSDT", "2021-08-01T00:00:00Z")
    assert result["status"] == "MATCHED"
    assert result["spec"]["spec_id"] == "AAVEUSDT-QUANTO-XBT-2021"
    assert result["spec"]["payout_model"] == "QUANTO"


def test_aave_2024_resolves_to_current_snapshot(registry: dict[str, object]) -> None:
    result = resolve_spec(registry, "AAVEUSDT", "2024-09-04T12:00:00Z")
    assert result["status"] == "MATCHED"
    assert result["spec"]["source_type"] == "BITMEX_INSTRUMENT_SNAPSHOT"
    assert result["spec"]["payout_model"] == "LINEAR"


def test_current_snapshot_does_not_override_old_aave(registry: dict[str, object]) -> None:
    old = resolve_spec(registry, "AAVEUSDT", "2021-08-01T00:00:00Z")
    assert old["spec"]["spec_id"] != "AAVEUSDT-SNAPSHOT-19d9fb1b3d79"
    assert old["spec"]["source_type"] == "CONFIGURED_HISTORICAL"


def test_xbt_and_xbt_case_variants_normalize_identically() -> None:
    assert normalize_currency("XBt") == "XBT"
    assert normalize_currency("XBT") == "XBT"
    assert normalize_currency("xbt") == "XBT"


def test_usdt_and_usdt_case_variants_normalize_identically() -> None:
    assert normalize_currency("USDt") == "USDT"
    assert normalize_currency("USDT") == "USDT"
    assert normalize_currency("usdt") == "USDT"


def test_settlement_currency_conflict_is_reported() -> None:
    event = {"symbol": "TESTUSD", "instrument_class": "DERIVATIVE", "execType": "Trade", "settlCurrency": "USDT", "event_time": "2020-06-01T00:00:00Z"}
    result = validate_execution_spec_compatibility(event, spec())
    assert result["compatibility_status"] == "CONFLICT"
    assert "settlement currency mismatch" in result["compatibility_reason"]


def test_payout_model_and_flags_conflict_is_reported() -> None:
    invalid = spec(payout_model="INVERSE", is_inverse=True, is_quanto=True)
    event = {"symbol": "TESTUSD", "instrument_class": "DERIVATIVE", "execType": "Trade", "settlCurrency": "XBT", "event_time": "2020-06-01T00:00:00Z"}
    result = validate_execution_spec_compatibility(event, invalid)
    assert result["compatibility_status"] == "CONFLICT"
    assert "payout_model/isInverse/isQuanto conflict" in result["compatibility_reason"]


def test_spot_events_are_excluded_from_derivative_mapping() -> None:
    events = [
        {"symbol": "XBTUSD", "instrument_class": "SPOT", "event_time": "2020-06-01T00:00:00Z", "execType": "Trade"},
        {"symbol": "TESTUSD", "instrument_class": "DERIVATIVE", "event_time": "2020-06-01T00:00:00Z", "execType": "Trade"},
    ]
    rows = resolve_specs_for_events(events, {"specs": [spec()]})
    assert len(rows) == 1
    assert all(row["instrument_class"] == "DERIVATIVE" for row in rows)


def test_settlement_event_passes_interval_and_currency_compatibility() -> None:
    event = {"symbol": "TESTUSD", "instrument_class": "DERIVATIVE", "execType": "Settlement", "settlCurrency": "XBt", "event_time": "2020-06-01T00:00:00Z"}
    result = validate_execution_spec_compatibility(event, spec())
    assert result["compatibility_status"] == "PASS"


@pytest.mark.skipif(not MAPPING.is_file(), reason="run build_historical_specs.py first to create the real-data mapping")
def test_all_nineteen_real_settlements_map_to_a_spec() -> None:
    import pyarrow.parquet as pq

    rows = pq.read_table(MAPPING).to_pylist()
    settlements = [row for row in rows if row["execType"] == "Settlement"]
    assert len(settlements) == 19
    assert all(row["spec_resolution_status"] == "MATCHED" for row in settlements)
    assert all(row["compatibility_status"] == "PASS" for row in settlements)


@pytest.mark.skipif(not MAPPING.is_file(), reason="run build_historical_specs.py first to create the real-data mapping")
def test_all_real_derivative_executions_have_exactly_one_spec() -> None:
    import pyarrow.parquet as pq

    rows = pq.read_table(MAPPING).to_pylist()
    assert len(rows) == 173226
    assert all(row["spec_resolution_status"] == "MATCHED" for row in rows)
    assert all(row["compatibility_status"] == "PASS" for row in rows)


def test_raw_csv_and_json_hashes_are_unchanged_after_registry_load(registry: dict[str, object]) -> None:
    before = hash_files(ROOT, PROTECTED_FILES)
    _ = registry["specs"]
    after = hash_files(ROOT, PROTECTED_FILES)
    assert before == after


def test_empty_config_corrupt_json_and_missing_fields(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"schema_version": "M0-02B-0/1.0", "specs": []}), encoding="utf-8")
    assert load_historical_specs(empty)["specs"] == []

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_historical_specs(corrupt)

    errors = validate_spec_schema({})
    assert any(error == "missing field: spec_id" for error in errors)
    assert any(error == "missing field: sources" for error in errors)


def test_materialized_snapshot_keeps_required_raw_fields_and_hash(registry: dict[str, object]) -> None:
    snapshots = [item for item in registry["specs"] if item.get("source_type") == "BITMEX_INSTRUMENT_SNAPSHOT"]
    assert snapshots
    required = {
        "typ", "listing", "expiry", "settle", "settlCurrency", "positionCurrency",
        "isInverse", "isQuanto", "multiplier", "underlyingToPositionMultiplier",
        "underlyingToSettleMultiplier", "quoteToSettleMultiplier", "lotSize", "tickSize",
    }
    assert required <= set(snapshots[0]["snapshot_fields"])
    assert len(snapshots[0]["metadata_row_sha256"]) == 64


def test_runtime_registry_decimal_fields_are_strings_or_null(registry: dict[str, object]) -> None:
    for item in registry["specs"]:
        for field in ("multiplier_major", "multiplier_raw", "lot_size", "tick_size"):
            assert item.get(field) is None or isinstance(item.get(field), str)
