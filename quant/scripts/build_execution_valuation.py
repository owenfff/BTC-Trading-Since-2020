#!/usr/bin/env python3
"""M0-02B-1A: normalize execution values, fees, and BitMEX asset units."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
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
from bitmex_replay.execution_price_reconciler import reconcile_execution_prices  # noqa: E402
from bitmex_replay.execution_valuation import (  # noqa: E402
    build_execution_valuation,
    load_asset_scale_registry,
)
from bitmex_replay.historical_spec_registry import (  # noqa: E402
    load_historical_specs,
    resolve_specs_for_events,
)
from bitmex_replay.io_utils import hash_files, iter_csv_dicts  # noqa: E402
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
EXPECTED_RAW_EXECUTIONS = 173434
EXPECTED_DERIVATIVE_EXECUTIONS = 173226
EXPECTED_DERIVATIVE_TRADES = 160302
EXPECTED_FUNDING = 12905
EXPECTED_SETTLEMENTS = 19
EXPECTED_SPOT_TRADES = 208
EXPECTED_CANONICAL_EXACT = 5809
EXPECTED_CANONICAL_RECOVERED = 1425
EXPECTED_CANONICAL_UNRESOLVED = 0


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
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
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): jsonable(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(jsonable(item) for item in value)
    return value


def count_csv_rows(path: Path) -> int:
    return sum(1 for _ in iter_csv_dicts(path))


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")

    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *[
                "| " + " | ".join(cell(value) for value in row) + " |"
                for row in rows
            ],
        ]
    )


def write_summary_csvs(reports: Path, summary: dict[str, Any], anomalies: list[dict[str, Any]]) -> None:
    component_rows = summary.get("component_summary", [])
    write_csv(
        component_rows,
        reports / "execution_valuation.csv",
        [
            "component_type",
            "currency",
            "component_count",
            "raw_sum_signed",
            "major_sum_signed",
            "normalization_failure_count",
        ],
    )
    write_csv(
        summary.get("scale_coverage", []),
        reports / "currency_scale_coverage.csv",
        [
            "currency",
            "asset_scale",
            "execution_count",
            "scale_available_count",
            "scale_missing_count",
            "coverage_ratio",
        ],
    )
    write_csv(
        component_rows,
        reports / "execution_component_summary.csv",
        [
            "component_type",
            "currency",
            "component_count",
            "raw_sum_signed",
            "major_sum_signed",
            "normalization_failure_count",
        ],
    )
    write_csv(
        summary.get("funding_summary", []),
        reports / "funding_summary.csv",
        [
            "symbol",
            "settlement_currency",
            "funding_event_count",
            "positive_execComm_count",
            "negative_execComm_count",
            "zero_execComm_count",
            "missing_execComm_count",
            "execComm_raw_sum",
            "execComm_major_sum",
            "first_event_time",
            "last_event_time",
            "normalization_failure_count",
        ],
    )
    write_csv(
        summary.get("trade_fee_summary", []),
        reports / "trade_fee_summary.csv",
        [
            "symbol",
            "settlement_currency",
            "lastLiquidityInd",
            "trade_count",
            "positive_execComm_count",
            "negative_execComm_count",
            "zero_execComm_count",
            "missing_execComm_count",
            "positive_commission_count",
            "negative_commission_count",
            "zero_commission_count",
            "fee_formula_exact_count",
            "fee_formula_difference_count",
            "fee_formula_difference_raw_sum",
        ],
    )
    write_csv(
        summary.get("settlement_summary", []),
        reports / "settlement_value_summary.csv",
        [
            "event_time",
            "execID",
            "symbol",
            "spec_id",
            "settlement_currency",
            "asset_scale",
            "execCost_raw",
            "execCost_major",
            "execComm_raw",
            "execComm_major",
            "realisedPnl_raw",
            "realisedPnl_major",
            "settlement_status",
            "normalization_status",
        ],
    )
    write_csv(
        anomalies,
        reports / "execution_value_anomalies.csv",
        [
            "execID",
            "event_time",
            "symbol",
            "execType",
            "anomaly_type",
            "normalization_status",
            "reason",
        ],
    )


def build_reports(
    *,
    reports: Path,
    summary: dict[str, Any],
    result: dict[str, Any],
    normalized: dict[str, Any],
    mapping_rows: list[dict[str, Any]],
    price_reconciliation: dict[str, Any],
    source: str,
    analysis: str,
    protected: dict[str, Any],
    wallet_history_rows: int,
    order_rows: int,
    blockers: list[str],
    warnings: list[str],
) -> None:
    reports.mkdir(parents=True, exist_ok=True)
    write_summary_csvs(reports, summary, result["anomalies"])

    price_summary = price_reconciliation.get("summary", {})
    derivative_events = [
        event
        for event in normalized["events"]
        if event.get("instrument_class") == "DERIVATIVE"
    ]
    raw_type_counts = Counter(event.get("execType", "") for event in normalized["events"])
    mapping_status_counts = Counter(row.get("spec_resolution_status", "") for row in mapping_rows)
    compatibility_counts = Counter(row.get("compatibility_status", "") for row in mapping_rows)
    normalization_counts = summary.get("normalization_status_counts", {})
    field_stats = summary.get("field_statistics", {})

    compact = {
        "report_version": "M0-02B-1A/1.0",
        "source_repository": "bwjoke/BTC-Trading-Since-2020",
        "fork_repository": "owenfff/BTC-Trading-Since-2020",
        "source_commit": source,
        "analysis_commit": analysis,
        "analysis_branch": git_value(["branch", "--show-current"]),
        "status": "BLOCKED" if blockers else ("READY_WITH_WARNINGS" if warnings else "PASS"),
        "readiness": (
            "BLOCKED_BY_EXECUTION_VALUE_NORMALIZATION"
            if blockers
            else "READY_FOR_POSITION_ACCOUNTING_REPLAY"
        ),
        "blockers": blockers,
        "warnings": warnings,
        "input": {
            "raw_execution_rows": normalized["raw_rows"],
            "raw_execution_type_counts": dict(raw_type_counts),
            "derivative_execution_rows": len(derivative_events),
            "derivative_trade_rows": sum(event.get("execType") == "Trade" for event in derivative_events),
            "funding_rows": sum(event.get("execType") == "Funding" for event in derivative_events),
            "settlement_rows": sum(event.get("execType") == "Settlement" for event in derivative_events),
            "spot_trade_rows": sum(
                event.get("instrument_class") == "SPOT" and event.get("execType") == "Trade"
                for event in normalized["events"]
            ),
            "order_rows": order_rows,
            "wallet_history_rows": wallet_history_rows,
            "unique_execID_rows": len(normalized["exec_ids"]),
            "duplicate_execID_count": len(normalized.get("duplicate_exec_ids", [])),
        },
        "joins": {
            "mapping_rows": len(mapping_rows),
            "mapping_spec_status_counts": dict(mapping_status_counts),
            "mapping_compatibility_status_counts": dict(compatibility_counts),
            "valuation_rows": len(result["valuations"]),
            "component_rows": len(result["components"]),
            "input_output_join_equal": len(derivative_events) == len(result["valuations"]),
        },
        "summary": summary,
        "price_reconciliation": {
            "trade_count": price_summary.get("trade_count", 0),
            "exact_count": price_summary.get("exact_count", 0),
            "recovered_count": price_summary.get("recovered_count", 0),
            "unresolved_count": price_summary.get("unresolved_count", 0),
            "canonical_reproduction_fail_count": price_summary.get("canonical_reproduction_fail_count", 0),
        },
        "protected_files": protected,
    }
    (reports / "execution_valuation.json").write_text(
        json.dumps(jsonable(compact), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    scale_rows = summary.get("scale_coverage", [])
    component_rows = summary.get("component_summary", [])
    funding_rows = summary.get("funding_summary", [])
    fee_rows = summary.get("trade_fee_summary", [])
    settlement_rows = summary.get("settlement_summary", [])
    md: list[str] = [
        "# M0-02B-1A Execution 价值、费用与币种单位标准化",
        "",
        "> 本报告只做 Execution 价值字段的单位标准化与组件拆分；不计算平均成本、策略 PnL、未实现 PnL、净值、杠杆或保证金，也不连接交易所。",
        "",
        "## 执行摘要",
        "",
        f"- Status: **{compact['status']}**",
        f"- Readiness: **{compact['readiness']}**",
        f"- Source commit: `{source}`",
        f"- Analysis commit: `{analysis}`",
        f"- Raw Execution rows: `{normalized['raw_rows']}`; derivative rows: `{len(derivative_events)}`; output rows: `{len(result['valuations'])}`.",
        f"- Components: `{len(result['components'])}`; each component remains separate and no cross-currency net cashflow is produced.",
        "",
        "## 数据边界与关联",
        "",
        table(
            ["检查", "结果", "预期/说明"],
            [
                ["Raw Execution", normalized["raw_rows"], EXPECTED_RAW_EXECUTIONS],
                ["Trade / Funding / Settlement", "/".join(str(raw_type_counts.get(item, 0)) for item in ("Trade", "Funding", "Settlement")), "160510 / 12905 / 19"],
                ["Derivative executions", len(derivative_events), EXPECTED_DERIVATIVE_EXECUTIONS],
                ["Derivative Trade", summary.get("exec_type_counts", {}).get("Trade", 0), EXPECTED_DERIVATIVE_TRADES],
                ["Spot Trade excluded", compact["input"]["spot_trade_rows"], EXPECTED_SPOT_TRADES],
                ["execID uniqueness", len(normalized["duplicate_exec_ids"]), "0 duplicates"],
                ["Order rows read", order_rows, "dimension input only"],
                ["Wallet history rows read", wallet_history_rows, "cash ledger is not reconstructed here"],
            ],
        ),
        "",
        f"- Derivative input/output join equality: **{compact['joins']['input_output_join_equal']}** (`{len(derivative_events)}` → `{len(result['valuations'])}`).",
        f"- Historical spec mapping rows: `{len(mapping_rows)}`; status counts: `{json.dumps(dict(mapping_status_counts), ensure_ascii=False)}`.",
        f"- Compatibility status counts: `{json.dumps(dict(compatibility_counts), ensure_ascii=False)}`.",
        "",
        "## 币种与 scale",
        "",
        "`api-v1-wallet-assets.csv` is the frozen scale registry. Raw monetary fields are interpreted as integer smallest units and converted with `major = raw / 10**scale` using Decimal only.",
        "",
        table(
            ["settlement currency", "scale", "executions", "scale coverage", "missing"],
            [
                [row.get("currency"), row.get("asset_scale"), row.get("execution_count"), row.get("coverage_ratio"), row.get("scale_missing_count")]
                for row in scale_rows
            ],
        ) if scale_rows else "No settlement currency rows.",
        "",
        f"- Commission currency source counts: `{json.dumps(summary.get('commission_currency_source_counts', {}), ensure_ascii=False)}`.",
        "- Commission source priority: `execCommCcy` → event `settlCurrency` only when it matches the resolved specification → specification settlement currency. No quote-currency fallback is used.",
        "- `homeNotional` and `foreignNotional` are retained as Decimal text fields without applying wallet-asset scale.",
        "",
        "## 字段拆分与会计边界",
        "",
        table(
            ["component type", "currency", "count", "raw signed sum", "major signed sum", "failures"],
            [
                [row.get("component_type"), row.get("currency"), row.get("component_count"), row.get("raw_sum_signed"), row.get("major_sum_signed"), row.get("normalization_failure_count")]
                for row in component_rows
            ],
        ) if component_rows else "No component rows.",
        "",
        "- `execCost` on Trade is `POSITION_COST`, not wallet cashflow; on Funding it is a non-cash execution-cost reference; on Settlement it is a position-value reference.",
        "- `execComm` keeps the original signed value and is classified as trade fee/rebate, funding payment, or settlement commission according to `execType`.",
        "- `realisedPnl` remains an independent reported field/component. It is not added to fees or funding; its overlap with future wallet/PnL reconciliation is explicitly left unresolved.",
        "",
        "## 原始金额字段统计与 round-trip",
        "",
        table(
            ["field", "total", "missing", "zero", "positive", "negative", "invalid", "non-integer"],
            [
                [field, stats.get("total"), stats.get("missing"), stats.get("zero"), stats.get("positive"), stats.get("negative"), stats.get("invalid"), stats.get("non_integer")]
                for field, stats in field_stats.items()
            ],
        ),
        "",
        f"- Raw → major → raw exact round-trip failures: `{summary.get('raw_major_roundtrip_failure_count', 0)}`.",
        f"- Normalization status counts: `{json.dumps(normalization_counts, ensure_ascii=False)}`.",
        "- Missing remains distinct from zero. Fractional raw amounts and malformed raw amounts are blocking anomalies; this run does not auto-repair them.",
        "",
        "## Funding",
        "",
        table(
            ["symbol", "currency", "events", "+ execComm", "- execComm", "zero", "missing", "raw sum", "major sum", "failures"],
            [
                [row.get("symbol"), row.get("settlement_currency"), row.get("funding_event_count"), row.get("positive_execComm_count"), row.get("negative_execComm_count"), row.get("zero_execComm_count"), row.get("missing_execComm_count"), row.get("execComm_raw_sum"), row.get("execComm_major_sum"), row.get("normalization_failure_count")]
                for row in funding_rows
            ],
        ) if funding_rows else "No Funding rows.",
        "",
        "- Funding does not change contract quantity. Its signed `execComm` is retained as the funding-payment component; `execCost` is not silently treated as funding cashflow.",
        "",
        "## Trade fees / rebates",
        "",
        table(
            ["symbol", "currency", "liquidity", "trades", "+ fee", "- fee", "zero", "formula exact", "diagnostic diff"],
            [
                [row.get("symbol"), row.get("settlement_currency"), row.get("lastLiquidityInd"), row.get("trade_count"), row.get("positive_execComm_count"), row.get("negative_execComm_count"), row.get("zero_execComm_count"), row.get("fee_formula_exact_count"), row.get("fee_formula_difference_count")]
                for row in fee_rows
            ],
        ) if fee_rows else "No derivative Trade fee rows.",
        "",
        "- `execComm` is the reported signed fee/rebate value and is preserved as authoritative for this milestone. The commission-rate multiplication is diagnostic only and is not used to overwrite `execComm`.",
        "",
        "## Settlement",
        "",
        table(
            ["time", "execID", "symbol", "currency", "scale", "execCost major", "execComm major", "realisedPnl major", "status"],
            [
                [row.get("event_time"), row.get("execID"), row.get("symbol"), row.get("settlement_currency"), row.get("asset_scale"), row.get("execCost_major"), row.get("execComm_major"), row.get("realisedPnl_major"), row.get("normalization_status")]
                for row in settlement_rows
            ],
        ) if settlement_rows else "No Settlement rows.",
        "",
        f"- Settlement rows normalized: `{len(settlement_rows)}`; expected `{EXPECTED_SETTLEMENTS}`.",
        "- Settlement `execCost` is reported as a position-value reference; it is not merged into a cashflow total.",
        "",
        "## Canonical execution price reuse",
        "",
        f"- The builder re-runs the existing M0-02B-0.2 Decimal price reconciler from raw normalized events; it does not trust an existing generated CSV as input.",
        f"- Configured historical Trade rows: `{price_summary.get('trade_count', 0)}`.",
        f"- EXACT: `{price_summary.get('exact_count', 0)}`; RECOVERED: `{price_summary.get('recovered_count', 0)}`; UNRESOLVED: `{price_summary.get('unresolved_count', 0)}`.",
        f"- Canonical execCost reproduction failures: `{price_summary.get('canonical_reproduction_fail_count', 0)}`.",
        "- Non-audited current/snapshot Trade rows keep raw `lastPx` and are not promoted to historical canonical price in this milestone.",
        "",
        "## 异常、阻塞与后续边界",
        "",
        f"- Blocking findings: `{json.dumps(blockers, ensure_ascii=False)}`.",
        f"- Warnings: `{json.dumps(warnings, ensure_ascii=False)}`.",
        "- Full anomaly rows are capped at 200 in `execution_value_anomalies.csv`; the complete valuation and component ledgers remain ignored Parquet outputs.",
        "- This milestone does not calculate average entry price, realised strategy PnL, unrealised PnL, net worth, leverage, margin, signals, or trades.",
        "",
        "## 输出文件",
        "",
        "- Ignored: `quant/outputs/execution_valuation.parquet`, `quant/outputs/execution_components.parquet`.",
        "- Committed summaries: `execution_valuation.json`, `execution_valuation.csv`, `execution_component_summary.csv`, `currency_scale_coverage.csv`, `funding_summary.csv`, `trade_fee_summary.csv`, `settlement_value_summary.csv`, `execution_value_anomalies.csv`.",
        "- Protected raw-file hashes were captured before and after generation; any changed raw file blocks the run.",
    ]
    (reports / "execution_valuation.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    data = {
        "execution": ROOT / "api-v1-execution-tradeHistory.csv",
        "order": ROOT / "api-v1-order.csv",
        "wallet_history": ROOT / "api-v1-user-walletHistory.csv",
        "instruments": ROOT / "api-v1-instrument.all.csv",
        "wallet_assets": ROOT / "api-v1-wallet-assets.csv",
        "settlements": ROOT / "quant" / "config" / "historical_settlement_evidence.json",
        "spec_config": ROOT / "quant" / "config" / "historical_instrument_specs.json",
    }
    outputs = ROOT / "quant" / "outputs"
    reports = ROOT / "quant" / "reports"
    outputs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    before_hashes = hash_files(ROOT, PROTECTED_FILES)

    order_dimension = build_order_dimension(data["order"])
    instruments = load_instruments(data["instruments"])
    settlement_evidence = load_settlement_evidence(data["settlements"])
    normalized = normalize_executions(
        data["execution"], order_dimension, instruments, settlement_evidence
    )
    assert_unique_exec_ids(normalized)
    registry = load_historical_specs(
        data["spec_config"], data["instruments"], source_commit()
    )
    mapping_rows = resolve_specs_for_events(normalized["events"], registry)
    price_reconciliation = reconcile_execution_prices(
        normalized["events"], registry, mapping_rows
    )
    asset_registry = load_asset_scale_registry(data["wallet_assets"])
    result = build_execution_valuation(
        normalized["events"],
        registry,
        mapping_rows,
        asset_registry,
        price_reconciliation=price_reconciliation,
    )
    write_parquet(result["valuations"], outputs / "execution_valuation.parquet")
    write_parquet(result["components"], outputs / "execution_components.parquet")

    derivative_events = [
        event
        for event in normalized["events"]
        if event.get("instrument_class") == "DERIVATIVE"
    ]
    raw_counts = Counter(event.get("execType", "") for event in normalized["events"])
    valuation_summary = result["summary"]
    blockers: list[str] = []
    warnings: list[str] = []
    if normalized["raw_rows"] != EXPECTED_RAW_EXECUTIONS:
        blockers.append(f"raw execution count {normalized['raw_rows']} != {EXPECTED_RAW_EXECUTIONS}")
    if dict(raw_counts) != {"Trade": 160510, "Funding": EXPECTED_FUNDING, "Settlement": EXPECTED_SETTLEMENTS}:
        blockers.append(f"raw execution type counts differ: {dict(raw_counts)}")
    if len(derivative_events) != EXPECTED_DERIVATIVE_EXECUTIONS:
        blockers.append(f"derivative execution count {len(derivative_events)} != {EXPECTED_DERIVATIVE_EXECUTIONS}")
    if sum(event.get("execType") == "Trade" for event in derivative_events) != EXPECTED_DERIVATIVE_TRADES:
        blockers.append("derivative Trade count differs from the frozen M0-02A baseline")
    if sum(event.get("execType") == "Funding" for event in derivative_events) != EXPECTED_FUNDING:
        blockers.append("Funding count differs from the frozen M0-02A baseline")
    if sum(event.get("execType") == "Settlement" for event in derivative_events) != EXPECTED_SETTLEMENTS:
        blockers.append("Settlement count differs from the frozen M0-02A baseline")
    spot_trades = sum(
        event.get("instrument_class") == "SPOT" and event.get("execType") == "Trade"
        for event in normalized["events"]
    )
    if spot_trades != EXPECTED_SPOT_TRADES:
        blockers.append(f"spot Trade count {spot_trades} != {EXPECTED_SPOT_TRADES}")
    if normalized.get("duplicate_exec_ids"):
        blockers.append(f"duplicate execID values: {len(normalized['duplicate_exec_ids'])}")
    if len(mapping_rows) != len(derivative_events):
        blockers.append("historical specification mapping does not cover every derivative execution")
    if valuation_summary.get("duplicate_mapping_execID_count", 0):
        blockers.append("duplicate execution IDs exist in the specification mapping")
    if len(result["valuations"]) != len(derivative_events):
        blockers.append("valuation output row count does not equal derivative input row count")
    if any(row.get("instrument_class") != "DERIVATIVE" for row in result["valuations"]):
        blockers.append("a Spot or non-derivative row entered the valuation output")

    matched = sum(
        row.get("spec_resolution_status") == "MATCHED" and row.get("compatibility_status") == "PASS"
        for row in mapping_rows
    )
    if matched != len(derivative_events):
        blockers.append(f"matched compatible specification rows {matched} != {len(derivative_events)}")
    if valuation_summary.get("raw_major_roundtrip_failure_count", 0):
        blockers.append("one or more raw-major-raw round trips failed")
    for field, stats in valuation_summary.get("field_statistics", {}).items():
        if stats.get("invalid", 0) or stats.get("non_integer", 0):
            blockers.append(f"{field} contains invalid or non-integer raw amounts")
    if any(row.get("scale_missing_count", 0) for row in valuation_summary.get("scale_coverage", [])):
        blockers.append("one or more settlement currencies lack a wallet-assets scale")
    if any(row.get("normalization_failure_count", 0) for row in valuation_summary.get("component_summary", [])):
        blockers.append("one or more component rows failed amount normalization")
    settlement_summary = valuation_summary.get("settlement_summary", [])
    if len(settlement_summary) != EXPECTED_SETTLEMENTS:
        blockers.append("settlement summary does not contain all 19 historical Settlement rows")
    if any(row.get("normalization_status") == "BLOCKED" for row in settlement_summary):
        blockers.append("at least one Settlement value is blocked")

    price_summary = price_reconciliation.get("summary", {})
    if price_summary.get("unresolved_count") != EXPECTED_CANONICAL_UNRESOLVED:
        blockers.append("M0-02B-0.2 has unresolved canonical historical prices")
    if price_summary.get("exact_count") != EXPECTED_CANONICAL_EXACT:
        blockers.append(f"canonical EXACT count {price_summary.get('exact_count')} != {EXPECTED_CANONICAL_EXACT}")
    if price_summary.get("recovered_count") != EXPECTED_CANONICAL_RECOVERED:
        blockers.append(f"canonical RECOVERED count {price_summary.get('recovered_count')} != {EXPECTED_CANONICAL_RECOVERED}")
    if price_summary.get("canonical_reproduction_fail_count", 0):
        blockers.append("canonical price reproduction does not reproduce raw execCost exactly")

    fallback_count = sum(
        count
        for source, count in valuation_summary.get("commission_currency_source_counts", {}).items()
        if source != "EXEC_COMM_CCY"
    )
    if fallback_count:
        warnings.append(f"{fallback_count} rows use the documented commission-currency fallback chain")
    fee_diagnostic_count = sum(
        row.get("fee_formula_difference_count", 0)
        for row in valuation_summary.get("trade_fee_summary", [])
    )
    non_comparable_count = sum(
        row.get("trade_count", 0)
        for row in valuation_summary.get("trade_fee_summary", [])
        if row.get("settlement_currency")
    )
    if fee_diagnostic_count:
        warnings.append(f"{fee_diagnostic_count} Trade rows differ from the commission-rate diagnostic; reported execComm is retained")
    if non_comparable_count:
        warnings.append("commission-rate diagnostic is informational and does not create a wallet cashflow")
    warnings.append("realisedPnl remains independent; overlap with future wallet/PnL reconciliation is not resolved in M0-02B-1A")

    after_hashes = hash_files(ROOT, PROTECTED_FILES)
    changed = [filename for filename in PROTECTED_FILES if before_hashes.get(filename) != after_hashes.get(filename)]
    if changed:
        blockers.append(f"protected raw files changed during build: {changed}")
    protected = {"unchanged": not changed, "changed_files": changed, "before": before_hashes, "after": after_hashes}

    analysis = git_value(["rev-parse", "HEAD"])
    build_reports(
        reports=reports,
        summary=valuation_summary,
        result=result,
        normalized=normalized,
        mapping_rows=mapping_rows,
        price_reconciliation=price_reconciliation,
        source=source_commit(),
        analysis=analysis,
        protected=protected,
        wallet_history_rows=count_csv_rows(data["wallet_history"]),
        order_rows=order_dimension.rows_read,
        blockers=blockers,
        warnings=warnings,
    )

    status = "BLOCKED" if blockers else ("READY_WITH_WARNINGS" if warnings else "PASS")
    print(f"execution_valuation_status={status}")
    print(f"analysis_commit={analysis}")
    print(f"raw_execution_rows={normalized['raw_rows']}")
    print(f"derivative_execution_rows={len(derivative_events)}")
    print(f"valuation_rows={len(result['valuations'])}")
    print(f"component_rows={len(result['components'])}")
    print(f"canonical_exact={price_summary.get('exact_count', 0)}")
    print(f"canonical_recovered={price_summary.get('recovered_count', 0)}")
    print(f"canonical_unresolved={price_summary.get('unresolved_count', 0)}")
    print(f"raw_files_unchanged={not changed}")
    if blockers:
        print("blockers:")
        for item in blockers:
            print(f"- {item}")
        return 1
    if warnings:
        print("warnings:")
        for item in warnings:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
