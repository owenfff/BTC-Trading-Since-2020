#!/usr/bin/env python3
"""M0-02B-0: build a time-versioned BitMEX instrument-spec coverage audit."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
from bitmex_replay.historical_spec_registry import (  # noqa: E402
    EVIDENCE_LEVELS,
    load_historical_specs,
    normalize_currency,
    resolve_specs_for_events,
    validate_spec_intervals,
)
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402
from bitmex_replay.reconciliation import write_csv, write_parquet  # noqa: E402


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
RISK_SYMBOLS = [
    "AAVEUSDT", "ADAUSDT", "BNBUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "LUNAUSD", "ORDIUSD", "TRXUSDT", "UNIUSDT", "XLMUSDT",
]
EXPECTED_DERIVATIVE_EVENTS = 173226
EXPECTED_SETTLEMENTS = 19
EXPECTED_SPOT_TRADES = 208


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def source_commit() -> str:
    path = ROOT / "quant" / "SOURCE_VERSION.md"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("- source commit:"):
            return line.split(":", 1)[1].strip().strip("`")
    return ""


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, (datetime,)):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")

    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(cell(value) for value in row) + " |" for row in rows],
    ])


def build_symbol_coverage(mapping_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mapping_rows:
        grouped[row["symbol"]].append(row)
    rows: list[dict[str, Any]] = []
    for symbol in sorted(grouped):
        items = grouped[symbol]
        resolution_counts = Counter(item["spec_resolution_status"] for item in items)
        compatibility_counts = Counter(item["compatibility_status"] for item in items)
        specs = sorted({item["spec_id"] for item in items if item["spec_id"]})
        times = sorted(item["event_time"] for item in items if item["event_time"])
        rows.append({
            "symbol": symbol,
            "derivative_execution_count": len(items),
            "matched_count": resolution_counts.get("MATCHED", 0),
            "missing_spec_count": resolution_counts.get("MISSING_SPEC", 0),
            "overlapping_spec_count": resolution_counts.get("OVERLAPPING_SPECS", 0),
            "compatibility_pass_count": compatibility_counts.get("PASS", 0),
            "compatibility_conflict_count": compatibility_counts.get("CONFLICT", 0),
            "settlement_currency_conflict_count": sum("settlement currency mismatch" in item["compatibility_reason"] for item in items),
            "payout_model_conflict_count": sum("payout_model" in item["compatibility_reason"] for item in items),
            "spec_version_count_used": len(specs),
            "spec_ids_used": ";".join(specs),
            "evidence_confidences": ";".join(sorted({item["spec_evidence_confidence"] for item in items if item["spec_evidence_confidence"]})),
            "first_event_time": times[0] if times else "",
            "last_event_time": times[-1] if times else "",
        })
    return rows


def build_evidence_matrix(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for spec in specs:
        missing = [field for field in ("underlying", "quote_currency", "settlement_currency", "margin_currency", "multiplier_major", "multiplier_raw") if spec.get(field) in {None, ""}]
        rows.append({
            "spec_id": spec.get("spec_id", ""),
            "symbol": spec.get("symbol", ""),
            "source_type": spec.get("source_type", "CONFIGURED_HISTORICAL"),
            "valid_from": spec.get("valid_from", ""),
            "valid_to_exclusive": spec.get("valid_to_exclusive", ""),
            "payout_model": spec.get("payout_model", ""),
            "underlying": spec.get("underlying"),
            "quote_currency": spec.get("quote_currency"),
            "settlement_currency": spec.get("settlement_currency"),
            "margin_currency": spec.get("margin_currency"),
            "multiplier_major": spec.get("multiplier_major"),
            "multiplier_currency": spec.get("multiplier_currency"),
            "multiplier_raw": spec.get("multiplier_raw"),
            "evidence_confidence": spec.get("evidence_confidence", ""),
            "missing_fields": ";".join(missing),
            "field_provenance": json.dumps(spec.get("field_provenance", {}), ensure_ascii=False, sort_keys=True),
            "source_urls": ";".join(item.get("source_url", "") for item in spec.get("sources", [])),
            "data_source_commit": spec.get("data_source_commit", ""),
            "metadata_row_sha256": spec.get("metadata_row_sha256", ""),
            "notes": spec.get("notes", ""),
        })
    return rows


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    readiness = report["readiness"]
    coverage = report["coverage"]
    risk_rows = report["risk_symbols"]
    lines = [
        "# M0-02B-0 Historical BitMEX Instrument Specification Coverage",
        "",
        f"Data source commit: `{report['source']['data_source_commit']}`; analysis commit: `{report['source']['analysis_commit']}`; branch: `{report['source']['branch']}`.",
        "",
        "## Execution summary",
        "",
        f"- `m0_02b_spec_readiness`: **{readiness['m0_02b_spec_readiness']}**",
        f"- Registry: `{report['registry']['schema_version']}`; total materialized specs: `{report['registry']['spec_count']}` (`{report['registry']['configured_historical_spec_count']}` configured historical + `{report['registry']['snapshot_spec_count']}` frozen snapshot versions).",
        f"- Derivative execution denominator: `{coverage['derivative_execution_count']:,}`; mapped: `{coverage['matched_count']:,}`; coverage: `{coverage['coverage_percent']}`%.",
        f"- `MISSING_SPEC`: `{coverage['missing_spec_count']}`; `OVERLAPPING_SPECS`: `{coverage['overlapping_spec_count']}`.",
        f"- Settlement mapping: `{coverage['settlement_mapped_count']}/{coverage['settlement_count']}`; settlement currency conflicts: `{coverage['settlement_currency_conflict_count']}`; payout-model conflicts: `{coverage['payout_model_conflict_count']}`.",
        f"- Spot executions excluded from denominator: `{report['execution']['spot_trade_count']}` Spot Trade rows.",
        "",
        "This report only resolves instrument specifications. It does not calculate average cost, realised/unrealised PnL, equity, leverage, margin, candles or trading signals.",
        "",
        "## Registry and interval policy",
        "",
        "Resolution uses exact symbol matching and the UTC interval `valid_from <= event_time < valid_to_exclusive`. No latest-version fallback is permitted. Snapshot rows retain the requested raw fields, the frozen data commit and a stable complete-row SHA256.",
        "",
        table(["item", "value"], [
            ["configured historical versions", report["registry"]["configured_historical_spec_count"]],
            ["snapshot versions", report["registry"]["snapshot_spec_count"]],
            ["spec versions used by derivative executions", report["registry"]["used_spec_count"]],
            ["interval validation errors", len(report["registry"]["interval_errors"])],
        ]),
        "",
        "## Risk symbols",
        "",
        table(["symbol", "events", "matched", "specs used", "evidence", "status"], [[
            row["symbol"], row["derivative_execution_count"], row["matched_count"], row["spec_ids_used"], row["evidence_confidences"],
            "PASS" if row["missing_spec_count"] == 0 and row["overlapping_spec_count"] == 0 and row["compatibility_conflict_count"] == 0 else "BLOCKED",
        ] for row in risk_rows]),
        "",
        "AAVEUSDT historical rows resolve to `AAVEUSDT-QUANTO-XBT-2021`; the 2024 linear snapshot is outside the historical interval and does not match them.",
        "",
        "## Acceptance checks",
        "",
        f"- XBTUSD mapped specification(s): `{report['key_checks']['XBTUSD']['spec_ids']}`; payout model(s): `{report['key_checks']['XBTUSD']['payout_models']}`; all mapped XBTUSD rows are inverse: **{report['key_checks']['XBTUSD']['all_inverse']}**.",
        f"- AAVEUSDT 2021 mapped specification(s): `{report['key_checks']['AAVEUSDT_2021']['spec_ids']}`; payout model(s): `{report['key_checks']['AAVEUSDT_2021']['payout_models']}`.",
        "",
        "## Coverage by symbol",
        "",
        table(["symbol", "derivative events", "matched", "missing", "overlap", "compatibility conflicts", "first event", "last event"], [[
            row["symbol"], row["derivative_execution_count"], row["matched_count"], row["missing_spec_count"], row["overlapping_spec_count"], row["compatibility_conflict_count"], row["first_event_time"], row["last_event_time"],
        ] for row in report["symbol_coverage"]]),
        "",
        "## Evidence confidence",
        "",
        table(["evidence_confidence", "mapped execution rows"], [[key, value] for key, value in sorted(report["execution"]["evidence_confidence_counts"].items())]),
        "",
        "Historical `UNIUSDT` and `XLMUSDT` multiplier values are `OFFICIAL_PARTIAL_EXECUTION_VALIDATED`: the official BitMEX announcement confirms the Quanto/XBT product, while the numeric multiplier is validated against all observed non-zero `execCost` Trade rows. Missing old underlying fields remain explicit nulls rather than guesses.",
        "",
    ]
    lines.extend(["## Evidence gaps", ""])
    missing_core_fields = report["missing_core_fields"]
    if missing_core_fields:
        lines.extend([
            "The following materialized snapshot versions still lack `multiplier_major`. They are currently unused by the frozen execution set, so they do not block this historical replay gate:",
            "",
            table(["symbol", "spec_id", "missing fields", "used in execution"], [[
                item["symbol"], item["spec_id"], ";".join(item["fields"]), item["used_in_execution"]
            ] for item in missing_core_fields]),
            "",
        ])
    else:
        lines.extend(["No materialized specification is missing a core payout or multiplier field.", ""])
    lines.extend(["## Readiness and blockers", ""])
    if readiness["blockers"]:
        lines.extend([f"- {item}" for item in readiness["blockers"]])
    else:
        lines.append("- No coverage, interval, settlement-currency or core payout/multiplier blocker was found.")
    lines.extend([
        "",
        f"Cost/PnL replay gate: **{readiness['m0_02b_spec_readiness']}**. Core-field blockers are evaluated over specification versions actually used by the frozen derivative execution mapping. Unused current-snapshot rows with unavailable derivations remain listed in `spec_evidence_matrix.csv`; they are not silently filled and do not block this historical dataset gate.",
        "",
        "## Raw-data protection",
        "",
        f"Protected CSV/JSON SHA256 unchanged: **{report['protected_files']['unchanged']}**; changed files: `{report['protected_files']['changed_files'] or 'none'}`.",
        "",
        "References: [Get Instruments](https://docs.bitmex.com/api-explorer/get-instruments), [contract-size formulas](https://support.bitmex.com/hc/en-gb/articles/16797952159261-How-Do-I-Calculate-Contract-Size-and-Minimum-Trade-Amount-Using-the-instrument-Endpoint). Historical URLs are retained in `spec_evidence_matrix.csv` and the versioned JSON configuration.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)

    order_dimension = build_order_dimension(root / "api-v1-order.csv")
    instruments = load_instruments(root / "api-v1-instrument.all.csv")
    settlement_evidence = load_settlement_evidence(root / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(root / "api-v1-execution-tradeHistory.csv", order_dimension, instruments, settlement_evidence)
    assert_unique_exec_ids(normalized)
    registry = load_historical_specs(root / "quant" / "config" / "historical_instrument_specs.json", root / "api-v1-instrument.all.csv", source_commit())
    interval_errors = validate_spec_intervals(registry)
    mapping_rows = resolve_specs_for_events(normalized["events"], registry)
    write_parquet(mapping_rows, outputs / "execution_spec_mapping.parquet")

    used_spec_ids = {row["spec_id"] for row in mapping_rows if row.get("spec_id")}
    used_specs = [spec for spec in registry["specs"] if spec.get("spec_id") in used_spec_ids]

    symbol_coverage = build_symbol_coverage(mapping_rows)
    evidence_matrix = build_evidence_matrix(registry["specs"])
    write_csv(symbol_coverage, reports / "historical_spec_coverage.csv", list(symbol_coverage[0]) if symbol_coverage else ["symbol"])
    write_csv(evidence_matrix, reports / "spec_evidence_matrix.csv", list(evidence_matrix[0]) if evidence_matrix else ["spec_id"])

    derivative_events = [event for event in normalized["events"] if event.get("instrument_class") == "DERIVATIVE"]
    settlements = [event for event in derivative_events if event.get("execType") == "Settlement"]
    resolution_counts = Counter(row["spec_resolution_status"] for row in mapping_rows)
    compatibility_counts = Counter(row["compatibility_status"] for row in mapping_rows)
    confidence_counts = Counter(row["spec_evidence_confidence"] for row in mapping_rows)
    def key_check(symbol: str) -> dict[str, Any]:
        rows = [row for row in mapping_rows if row["symbol"] == symbol]
        return {
            "spec_ids": sorted({row["spec_id"] for row in rows if row.get("spec_id")}),
            "payout_models": sorted({row["payout_model"] for row in rows if row.get("payout_model")}),
            "all_inverse": bool(rows) and all(row.get("payout_model") == "INVERSE" for row in rows),
        }
    settlement_currency_conflicts = sum("settlement currency mismatch" in row["compatibility_reason"] for row in mapping_rows)
    payout_model_conflicts = sum("payout_model" in row["compatibility_reason"] for row in mapping_rows)
    core_fields = ("payout_model", "settlement_currency", "multiplier_major", "multiplier_currency")
    blocking_specs = [
        spec for spec in used_specs
        if any(spec.get(field) in {None, ""} for field in core_fields)
        or spec.get("evidence_confidence") in {"EXECUTION_INFERRED", "UNRESOLVED"}
    ]
    blockers: list[str] = []
    if len(derivative_events) != EXPECTED_DERIVATIVE_EVENTS:
        blockers.append(f"derivative execution denominator {len(derivative_events)} != frozen M0-02A.1 fact {EXPECTED_DERIVATIVE_EVENTS}")
    if resolution_counts.get("MATCHED", 0) != len(derivative_events):
        blockers.append("not every derivative execution matched exactly one specification")
    if resolution_counts.get("MISSING_SPEC", 0):
        blockers.append(f"{resolution_counts['MISSING_SPEC']} derivative events have MISSING_SPEC")
    if resolution_counts.get("OVERLAPPING_SPECS", 0):
        blockers.append(f"{resolution_counts['OVERLAPPING_SPECS']} derivative events have OVERLAPPING_SPECS")
    if interval_errors:
        blockers.append("registry interval validation failed")
    if settlement_currency_conflicts:
        blockers.append(f"{settlement_currency_conflicts} settlement-currency compatibility conflicts")
    if payout_model_conflicts:
        blockers.append(f"{payout_model_conflicts} payout-model compatibility conflicts")
    if blocking_specs:
        blockers.append("at least one materialized spec lacks a core PnL field or has insufficient multiplier/payout evidence")
    readiness_status = "READY_FOR_COST_BASIS_REPLAY" if not blockers else "BLOCKED"
    protected = {
        "before": before,
        "after": hash_files(root, PROTECTED_FILES),
    }
    protected["changed_files"] = [name for name in PROTECTED_FILES if protected["before"].get(name) != protected["after"].get(name)]
    protected["unchanged"] = not protected["changed_files"]

    risk_rows = [row for row in symbol_coverage if row["symbol"] in RISK_SYMBOLS]
    report: dict[str, Any] = {
        "report_version": "M0-02B-0/1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "repository": "owenfff/BTC-Trading-Since-2020",
            "data_source_commit": source_commit(),
            "analysis_commit": git_value(["rev-parse", "HEAD"]),
            "branch": git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        },
        "registry": {
            "schema_version": registry["schema_version"],
            "spec_count": len(registry["specs"]),
            "configured_historical_spec_count": len(registry["configured_specs"]),
            "snapshot_spec_count": len(registry["snapshot_specs"]),
            "used_spec_count": len(used_specs),
            "symbols_with_specs": len(registry["specs_by_symbol"]),
            "interval_errors": interval_errors,
            "config_path": registry["config_path"],
        },
        "execution": {
            "normalized_execution_count": len(normalized["events"]),
            "derivative_execution_count": len(derivative_events),
            "derivative_trade_count": sum(event.get("execType") == "Trade" for event in derivative_events),
            "funding_count": sum(event.get("execType") == "Funding" for event in derivative_events),
            "settlement_count": len(settlements),
            "spot_trade_count": sum(event.get("instrument_class") == "SPOT" and event.get("execType") == "Trade" for event in normalized["events"]),
            "resolution_status_counts": dict(resolution_counts),
            "compatibility_status_counts": dict(compatibility_counts),
            "evidence_confidence_counts": dict(confidence_counts),
        },
        "coverage": {
            "derivative_execution_count": len(derivative_events),
            "matched_count": resolution_counts.get("MATCHED", 0),
            "coverage_percent": f"{(resolution_counts.get('MATCHED', 0) / len(derivative_events) * 100) if derivative_events else 0:.6f}",
            "missing_spec_count": resolution_counts.get("MISSING_SPEC", 0),
            "overlapping_spec_count": resolution_counts.get("OVERLAPPING_SPECS", 0),
            "settlement_count": len(settlements),
            "settlement_mapped_count": sum(row["execType"] == "Settlement" and row["spec_resolution_status"] == "MATCHED" for row in mapping_rows),
            "settlement_currency_conflict_count": settlement_currency_conflicts,
            "payout_model_conflict_count": payout_model_conflicts,
        },
        "risk_symbols": risk_rows,
        "key_checks": {
            "XBTUSD": key_check("XBTUSD"),
            "AAVEUSDT_2021": key_check("AAVEUSDT"),
        },
        "symbol_coverage": symbol_coverage,
        "missing_core_fields": [{
            "spec_id": spec.get("spec_id"),
            "symbol": spec.get("symbol"),
            "used_in_execution": spec.get("spec_id") in used_spec_ids,
            "fields": [field for field in core_fields if spec.get(field) in {None, ""}],
        } for spec in registry["specs"] if any(spec.get(field) in {None, ""} for field in core_fields)],
        "readiness": {"m0_02b_spec_readiness": readiness_status, "blockers": blockers},
        "protected_files": protected,
    }
    report_json = reports / "historical_spec_coverage.json"
    report_json.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(report, reports / "historical_spec_coverage.md")
    return report


def main() -> int:
    report = run(ROOT)
    print(f"M0-02B-0 readiness: {report['readiness']['m0_02b_spec_readiness']}")
    print(f"Historical configured specs: {report['registry']['configured_historical_spec_count']}")
    print(f"Materialized specs: {report['registry']['spec_count']}")
    print(f"Derivative coverage: {report['coverage']['matched_count']}/{report['coverage']['derivative_execution_count']} ({report['coverage']['coverage_percent']}%)")
    print(f"MISSING_SPEC: {report['coverage']['missing_spec_count']}")
    print(f"OVERLAPPING_SPECS: {report['coverage']['overlapping_spec_count']}")
    print(f"Settlement mapping: {report['coverage']['settlement_mapped_count']}/{report['coverage']['settlement_count']}")
    print(f"Protected raw files unchanged: {report['protected_files']['unchanged']}")
    print(f"Report: {ROOT / 'quant' / 'reports' / 'historical_spec_coverage.md'}")
    return 0 if report["readiness"]["m0_02b_spec_readiness"] == "READY_FOR_COST_BASIS_REPLAY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
