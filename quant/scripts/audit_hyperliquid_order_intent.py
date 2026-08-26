#!/usr/bin/env python3
"""Audit the Hyperliquid snapshot's pre-fill order-intent evidence.

The snapshot contains order creation terms and later lifecycle statuses.  This
is stronger than a fills-only export for describing execution intent, but it
is still not a complete historical quote/order-book or private-trigger feed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_ROOT = ROOT / "quant" / "data" / "external" / "hyperliquid" / "paul"
REPORT = ROOT / "quant" / "reports" / "hyperliquid_order_intent_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "hyperliquid_order_intent_audit.md"
UTC = timezone.utc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_dir(root: Path = EXTERNAL_ROOT) -> Path:
    candidates = sorted(path.parent for path in root.rglob("historicalOrders.json"))
    if not candidates:
        raise FileNotFoundError(f"historicalOrders.json under {root}")
    return candidates[-1]


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _timestamp(value: Any) -> int:
    return int(value)


def _verify_manifest(base: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    files = manifest.get("files", {})
    results: dict[str, Any] = {}
    for name, expected in files.items():
        path = base / str(name)
        actual = {"exists": path.exists()}
        if path.exists():
            actual["bytes"] = path.stat().st_size
            actual["sha256"] = _sha256(path)
        actual["status"] = "PASS" if actual.get("exists") and actual.get("bytes") == expected.get("bytes") and actual.get("sha256") == expected.get("sha256") else "FAIL"
        results[str(name)] = {"expected": expected, "actual": actual}
    return results


def analyze_order_intent(orders: Iterable[Mapping[str, Any]], fills: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    order_rows = [dict(row) for row in orders]
    fill_rows = [dict(row) for row in fills]
    by_oid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in order_rows:
        nested = row.get("order") or {}
        by_oid[str(nested.get("oid"))].append(row)
    fills_by_oid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fill_rows:
        if row.get("oid") is not None:
            fills_by_oid[str(row["oid"])].append(row)

    filled_status_oids = {oid for oid, rows in by_oid.items() if any(row.get("status") == "filled" for row in rows)}
    fill_oids = set(fills_by_oid)
    overlap = filled_status_oids & fill_oids
    create_before_fill = 0
    for oid in sorted(overlap):
        created = min(_timestamp(row["order"]["timestamp"]) for row in by_oid[oid])
        first_fill = min(_timestamp(row["time"]) for row in fills_by_oid[oid])
        if created <= first_fill:
            create_before_fill += 1

    intent_fields = ("coin", "side", "limitPx", "sz", "origSz", "orderType", "tif", "reduceOnly", "isTrigger", "triggerPx", "timestamp")
    present = {
        field: sum(bool((row.get("order") or {}).get(field) is not None) for row in order_rows)
        for field in intent_fields
    }
    status_counts = Counter(str(row.get("status") or "MISSING") for row in order_rows)
    type_counts = Counter(str((row.get("order") or {}).get("orderType") or "MISSING") for row in order_rows)
    tif_counts = Counter(str((row.get("order") or {}).get("tif") or "MISSING") for row in order_rows)
    timestamps = [_timestamp((row.get("order") or {}).get("timestamp")) for row in order_rows if (row.get("order") or {}).get("timestamp") is not None]
    return {
        "order_records": len(order_rows),
        "unique_order_ids": len(by_oid),
        "orders_per_id": dict(sorted(Counter(len(rows) for rows in by_oid.values()).items())),
        "status_counts": dict(sorted(status_counts.items())),
        "order_type_counts": dict(sorted(type_counts.items())),
        "time_in_force_counts": dict(sorted(tif_counts.items())),
        "reduce_only_count": sum(bool((row.get("order") or {}).get("reduceOnly")) for row in order_rows),
        "trigger_order_count": sum(bool((row.get("order") or {}).get("isTrigger")) for row in order_rows),
        "intent_field_presence": present,
        "fill_records": len(fill_rows),
        "fill_order_ids": len(fill_oids),
        "filled_status_order_ids": len(filled_status_oids),
        "filled_status_fill_overlap": len(overlap),
        "order_created_at_or_before_first_fill": create_before_fill,
        "order_time_range_utc": {
            "min": datetime.fromtimestamp(min(timestamps) / 1000, UTC).isoformat().replace("+00:00", "Z") if timestamps else None,
            "max": datetime.fromtimestamp(max(timestamps) / 1000, UTC).isoformat().replace("+00:00", "Z") if timestamps else None,
        },
    }


def build(*, source_dir: Path | None = None, report_path: Path = REPORT, markdown_path: Path = REPORT_MD) -> dict[str, Any]:
    base = source_dir or _source_dir()
    orders_path = base / "historicalOrders.json"
    fills_path = base / "userFillsByTime.json"
    manifest_path = base / "source-manifest.json"
    manifest = _read_json(manifest_path)
    verification = _verify_manifest(base, manifest)
    orders = _read_json(orders_path)
    fills = _read_json(fills_path)
    stats = analyze_order_intent(orders, fills)
    overlap = stats["filled_status_fill_overlap"]
    filled = stats["filled_status_order_ids"]
    before = stats["order_created_at_or_before_first_fill"]
    output = {
        "report_version": "M15-HYPERLIQUID-ORDER-INTENT-1.0",
        "status": "PARTIAL_PRE_ACTION_CONTEXT",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "directory": str(base.relative_to(ROOT)),
            "repository": manifest.get("source", {}).get("repository"),
            "revision": manifest.get("source", {}).get("revision"),
            "target_user": manifest.get("targetUser"),
            "manifest_verification": verification,
        },
        "order_intent": stats,
        "available_before_fill": [
            "coin",
            "side",
            "limitPx",
            "sz",
            "origSz",
            "orderType",
            "tif",
            "reduceOnly",
            "isTrigger",
            "triggerPx",
            "timestamp",
        ],
        "limitations": {
            "historical_order_endpoint_is_recent_window": True,
            "independent_historical_quote_or_orderbook_present": False,
            "private_trigger_or_subjective_intent_present": False,
            "complete_pre_action_trigger_context_available": False,
            "reason": "Historical orders expose submitted terms and lifecycle timing, but not the quote/order-book state or private rule that caused submission; coverage is also limited to the source snapshot's recent order window.",
        },
        "interpretation": "Hyperliquid order-intent evidence is stronger than fills-only data and can support execution-style analysis. It still cannot establish the original trader's exact autonomous timing or complete private strategy.",
        "raw_inputs_untouched": True,
        "active_demo_unchanged": True,
        "promotion_allowed": False,
    }
    output["quality_checks"] = {
        "all_manifest_files_pass": all(item.get("status") == "PASS" for item in verification.values()),
        "filled_order_join_rate": overlap / filled if filled else None,
        "created_before_or_at_fill_rate": before / overlap if overlap else None,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown = [
        "# Hyperliquid Order Intent Audit",
        "",
        "> `PARTIAL_PRE_ACTION_CONTEXT`: the snapshot exposes submitted order terms before fills, but not a complete trigger context.",
        "",
        "## Result",
        "",
        f"- Order records: `{stats['order_records']}`; unique order IDs: `{stats['unique_order_ids']}`.",
        f"- Filled-status order IDs: `{filled}`; matching fill order IDs: `{overlap}`; creation before/at first fill: `{before}`.",
        f"- All order records are `{', '.join(stats['order_type_counts'])}` / `{', '.join(stats['time_in_force_counts'])}` in this snapshot.",
        "- Available intent fields include side, limit price, size, GTC, reduce-only/trigger flags and order timestamp.",
        "",
        "## What this adds",
        "",
        "It supports a stronger description of Hyperliquid execution style: submitted limit-order terms and their later open/canceled/filled lifecycle can be analyzed before looking at the fill result.",
        "",
        "## What it does not add",
        "",
        "It does not provide the historical quote/order-book state, the trader's private trigger, subjective conviction, or a complete all-time order archive. The official historical-orders endpoint is a recent-window source, so this snapshot cannot be treated as complete history.",
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection or order was used. Raw source files remain unchanged; the active Demo model remains unchanged and promotion is not allowed.",
    ]
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    try:
        output = build(source_dir=args.source_dir.resolve() if args.source_dir else None)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "HYPERLIQUID_ORDER_INTENT_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": output["status"], "report": str(REPORT), "filled_join_rate": output["quality_checks"]["filled_order_join_rate"], "promotion_allowed": output["promotion_allowed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
