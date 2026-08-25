#!/usr/bin/env python3
"""Audit a public Hyperliquid trader snapshot without mixing it into the teacher model."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SOURCE_FILES = (
    "historicalOrders.json",
    "userFillsByTime.json",
    "userFunding.json",
    "userNonFundingLedgerUpdates.json",
    "frontendOpenOrders.json",
    "clearinghouseState.json",
    "spotClearinghouseState.json",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"not a decimal: {value!r}") from error


def snapshots(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in document.get("snapshots", []) if isinstance(row, dict)]


def latest_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    rows = snapshots(document)
    return max(rows, key=lambda row: str(row.get("capturedAt", ""))) if rows else {}


def latest_response(document: dict[str, Any]) -> Any:
    return latest_snapshot(document).get("response")


def classify_action(before: Decimal, after: Decimal) -> str:
    if before == 0 and after > 0:
        return "OPEN_LONG"
    if before == 0 and after < 0:
        return "OPEN_SHORT"
    if before > 0 and after > before:
        return "ADD_LONG"
    if before < 0 and after < before:
        return "ADD_SHORT"
    if before > 0 and after == 0:
        return "CLOSE_LONG"
    if before < 0 and after == 0:
        return "CLOSE_SHORT"
    if before > 0 and 0 < after < before:
        return "REDUCE_LONG"
    if before < 0 and before < after < 0:
        return "REDUCE_SHORT"
    if before > 0 and after < 0:
        return "FLIP_SHORT"
    if before < 0 and after > 0:
        return "FLIP_LONG"
    return "NO_POSITION_CHANGE"


def _ratio(numerator: int | Decimal, denominator: int | Decimal) -> str:
    if denominator == 0:
        return "0"
    return str((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.00000001")))


def _median(values: list[int | Decimal]) -> str | None:
    if not values:
        return None
    ordered = sorted(Decimal(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return str(ordered[middle])
    return str((ordered[middle - 1] + ordered[middle]) / Decimal("2"))


def _percentile(values: list[int | Decimal], fraction: Decimal) -> str | None:
    if not values:
        return None
    ordered = sorted(Decimal(value) for value in values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return str(ordered[index])


def build_behavior_profile(
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    replay_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build descriptive behavior metrics from public events only.

    The profile intentionally contains no predictive labels. It describes what was
    publicly observed, including the fact that an order was cancelled or crossed.
    """
    orders_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in orders:
        order = row.get("order", {})
        orders_by_id.setdefault(str(order.get("oid")), []).append(row)

    order_lifetimes: list[int] = []
    for events in orders_by_id.values():
        timestamps = [
            int(row.get("statusTimestamp", row.get("order", {}).get("timestamp", 0)))
            for row in events
        ]
        if len(timestamps) > 1:
            order_lifetimes.append(max(timestamps) - min(timestamps))

    order_creation_times = {
        oid: min(
            int(row.get("statusTimestamp", row.get("order", {}).get("timestamp", 0)))
            for row in events
        )
        for oid, events in orders_by_id.items()
    }
    fill_latencies: list[int] = []
    for fill in fills:
        created = order_creation_times.get(str(fill.get("oid")))
        if created is not None:
            fill_latencies.append(max(0, int(fill.get("time", 0)) - created))

    crossed = sum(1 for row in fills if bool(row.get("crossed")))
    gross_notional = sum((decimal(row.get("px", "0")) * decimal(row.get("sz", "0")) for row in fills), Decimal("0"))
    gross_size = sum((decimal(row.get("sz", "0")) for row in fills), Decimal("0"))
    fees = sum((decimal(row.get("fee", "0")) for row in fills), Decimal("0"))

    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in replay_rows:
        before = decimal(row["before"])
        after = decimal(row["after"])
        timestamp = int(row["time"])
        if before == 0 and after != 0:
            current = {
                "start_time_ms": timestamp,
                "side": "LONG" if after > 0 else "SHORT",
                "fills": 0,
                "maximum_abs_position": Decimal("0"),
            }
        if current is None:
            continue
        current["fills"] += 1
        current["maximum_abs_position"] = max(current["maximum_abs_position"], abs(after))
        flipped = before != 0 and after != 0 and ((before > 0) != (after > 0))
        closed = before != 0 and after == 0
        if flipped or closed:
            current["end_time_ms"] = timestamp
            current["duration_ms"] = timestamp - int(current["start_time_ms"])
            current["open_at_end"] = False
            episodes.append(current)
            if flipped:
                current = {
                    "start_time_ms": timestamp,
                    "side": "LONG" if after > 0 else "SHORT",
                    "fills": 1,
                    "maximum_abs_position": abs(after),
                }
            else:
                current = None
    if current is not None:
        last_time = int(replay_rows[-1]["time"])
        current["end_time_ms"] = last_time
        current["duration_ms"] = last_time - int(current["start_time_ms"])
        current["open_at_end"] = True
        episodes.append(current)

    durations = [int(row["duration_ms"]) for row in episodes]
    return {
        "orders": {
            "unique_order_ids": len(orders_by_id),
            "orders_with_filled_event": len({str(row.get("order", {}).get("oid")) for row in orders if row.get("status") == "filled"}),
            "orders_with_canceled_event": len({str(row.get("order", {}).get("oid")) for row in orders if row.get("status") == "canceled"}),
            "ever_filled_fraction": _ratio(
                len({str(row.get("order", {}).get("oid")) for row in orders if row.get("status") == "filled"}),
                len(orders_by_id),
            ),
            "ever_canceled_fraction": _ratio(
                len({str(row.get("order", {}).get("oid")) for row in orders if row.get("status") == "canceled"}),
                len(orders_by_id),
            ),
            "all_limit_orders": all(row.get("order", {}).get("orderType") == "Limit" for row in orders),
            "all_gtc_orders": all(row.get("order", {}).get("tif") == "Gtc" for row in orders),
            "reduce_only_event_count": sum(bool(row.get("order", {}).get("reduceOnly")) for row in orders),
            "lifetime_ms_median": _median(order_lifetimes),
            "lifetime_ms_p90": _percentile(order_lifetimes, Decimal("0.90")),
            "lifetime_ms_max": str(max(order_lifetimes)) if order_lifetimes else None,
        },
        "execution": {
            "fill_count": len(fills),
            "crossed_fill_count": crossed,
            "non_crossed_fill_count": len(fills) - crossed,
            "crossed_fill_fraction": _ratio(crossed, len(fills)),
            "gross_size_btc": str(gross_size),
            "gross_notional_usdc": str(gross_notional),
            "fee_total_usdc": str(fees),
            "fee_bps_on_gross_notional": _ratio(fees * Decimal("10000"), gross_notional),
            "fill_latency_ms_median": _median(fill_latencies),
            "fill_latency_ms_p90": _percentile(fill_latencies, Decimal("0.90")),
            "fill_latency_ms_max": str(max(fill_latencies)) if fill_latencies else None,
            "fills_per_order_median": _median([
                sum(1 for fill in fills if str(fill.get("oid")) == oid)
                for oid in {str(fill.get("oid")) for fill in fills}
            ]),
        },
        "position_episodes": {
            "episode_count": len(episodes),
            "closed_episode_count": sum(not row.get("open_at_end") for row in episodes),
            "open_at_end_count": sum(bool(row.get("open_at_end")) for row in episodes),
            "long_episode_count": sum(row.get("side") == "LONG" for row in episodes),
            "short_episode_count": sum(row.get("side") == "SHORT" for row in episodes),
            "duration_ms_median": _median(durations),
            "duration_ms_max": str(max(durations)) if durations else None,
            "fills_per_episode_median": _median([int(row["fills"]) for row in episodes]),
            "episodes": [
                {
                    **row,
                    "maximum_abs_position": str(row["maximum_abs_position"]),
                }
                for row in episodes
            ],
        },
        "interpretation_boundary": [
            "This profile describes public order, fill and account events; it does not recover private intent or a guaranteed trading rule.",
            "crossed is reported from the public fill field and is not independently reclassified as maker or taker.",
            "The profile is an external Hyperliquid reference and is excluded from the BitMEX teacher-model training set.",
        ],
    }


def audit(data_dir: Path, manifest_path: Path | None = None, comparison_dir: Path | None = None) -> dict[str, Any]:
    files = {name: data_dir / name for name in SOURCE_FILES}
    payloads = {Path(name).stem: read_json(path) for name, path in files.items() if path.exists()}
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    manifest = read_json(manifest_path) if manifest_path and manifest_path.exists() else {}
    manifest_files = manifest.get("files", {}) if isinstance(manifest, dict) else {}
    file_report: dict[str, Any] = {}
    for name in SOURCE_FILES:
        path = files[name]
        exists = path.exists()
        actual = {"bytes": path.stat().st_size, "sha256": sha256(path)} if exists else {}
        expected = manifest_files.get(name, {}) if isinstance(manifest_files, dict) else {}
        file_report[name] = {"exists": exists, "actual": actual, "expected": expected}
        check(
            f"manifest_{name}",
            exists and (not expected or (actual == {"bytes": expected.get("bytes"), "sha256": expected.get("sha256")})),
            {"actual": actual, "expected": expected},
        )

    comparison: dict[str, Any] = {}
    if comparison_dir:
        for name in SOURCE_FILES:
            path = comparison_dir / name
            actual = {"bytes": path.stat().st_size, "sha256": sha256(path)} if path.exists() else {}
            website_actual = file_report[name]["actual"]
            comparison[name] = {"website_snapshot": website_actual, "comparison_directory": actual, "same": website_actual == actual}

    orders = payloads.get("historicalOrders", [])
    fills = payloads.get("userFillsByTime", [])
    funding = payloads.get("userFunding", [])
    order_ids = [str(row.get("order", {}).get("oid")) for row in orders if isinstance(row, dict)]
    fill_oids = [str(row.get("oid")) for row in fills if isinstance(row, dict) and row.get("oid") is not None]
    fill_tids = [str(row.get("tid")) for row in fills if isinstance(row, dict)]
    order_id_set = set(order_ids)
    fill_oid_set = set(fill_oids)
    order_keys = [
        (order_id, str(row.get("status")), row.get("statusTimestamp", row.get("order", {}).get("timestamp")))
        for order_id, row in zip(order_ids, orders)
    ]
    check("historical_order_event_identity_unique", len(order_keys) == len(set(order_keys)), len(orders))
    check("historical_order_ids_present", all(value != "None" for value in order_ids), len(order_ids))
    check("fill_identity_unique", len(fill_tids) == len(set(fill_tids)), len(fill_tids))
    check("fill_order_reference_coverage", fill_oid_set.issubset(order_id_set), {"matched": len(fill_oid_set & order_id_set), "fill_order_ids": len(fill_oid_set), "missing": sorted(fill_oid_set - order_id_set)[:20]})

    position = Decimal("0")
    action_counts: Counter[str] = Counter()
    replay_rows: list[dict[str, Any]] = []
    for fill in sorted(fills, key=lambda row: (int(row.get("time", 0)), int(row.get("tid", 0)))):
        before = position
        size = decimal(fill["sz"])
        position += size if fill.get("side") == "B" else -size
        action = classify_action(before, position)
        action_counts[action] += 1
        replay_rows.append({"time": int(fill["time"]), "tid": str(fill["tid"]), "before": str(before), "after": str(position), "action": action})

    state_document = payloads.get("clearinghouseState", {})
    latest_state = latest_response(state_document) or {}
    positions = latest_state.get("assetPositions", []) if isinstance(latest_state, dict) else []
    btc_position = next((row.get("position", {}) for row in positions if row.get("position", {}).get("coin") == "BTC"), {})
    stated_position = decimal(btc_position.get("szi", "0"))
    check("latest_position_replay_matches_snapshot", position == stated_position, {"replayed": str(position), "snapshot": str(stated_position)})

    snapshot_sets = {}
    for name in ("frontendOpenOrders", "clearinghouseState", "spotClearinghouseState"):
        snapshot_sets[name] = {str(row.get("runId")) for row in snapshots(payloads.get(name, {}))}
    snapshot_sets_report = {name: sorted(values) for name, values in snapshot_sets.items()}
    check("snapshot_run_sets_align", len({tuple(values) for values in snapshot_sets_report.values()}) <= 1, snapshot_sets_report)

    funding_total = sum((decimal(row.get("delta", {}).get("usdc", "0")) for row in funding), Decimal("0"))
    current_orders = latest_response(payloads.get("frontendOpenOrders", {})) or []
    current_orders = current_orders if isinstance(current_orders, list) else []
    order_statuses = Counter(str(row.get("status", "UNKNOWN")) for row in orders if isinstance(row, dict))
    latest_margin = (latest_state.get("marginSummary") or {}) if isinstance(latest_state, dict) else {}
    position_value = decimal(latest_margin.get("totalNtlPos", "0"))
    account_value = decimal(latest_margin.get("accountValue", "0"))
    leverage = position_value / account_value if account_value else Decimal("0")
    behavior_profile = build_behavior_profile(orders, fills, replay_rows)

    result = {
        "status": "PASS" if all(item["passed"] for item in checks) else "WARNING",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "venue": "Hyperliquid",
            "target_user": manifest.get("targetUser"),
            "source_repository": manifest.get("source", {}).get("repository"),
            "source_revision": manifest.get("source", {}).get("revision"),
            "website_snapshot_synced_at": manifest.get("syncedAt"),
            "audit_only": True,
            "model_training_inclusion": False,
        },
        "coverage": {
            "historical_order_events": len(orders),
            "historical_order_ids": len(order_id_set),
            "fills": len(fills),
            "funding_records": len(funding),
            "funding_total_usdc": str(funding_total),
            "snapshot_checkpoints": {name: len(snapshots(payloads.get(name, {}))) for name in snapshot_sets_report},
            "current_open_orders": len(current_orders),
        },
        "behavior": {
            "first_fill_time_ms": replay_rows[0]["time"] if replay_rows else None,
            "last_fill_time_ms": replay_rows[-1]["time"] if replay_rows else None,
            "terminal_position": str(position),
            "maximum_abs_position": str(max((abs(decimal(row["after"])) for row in replay_rows), default=Decimal("0"))),
            "action_counts": dict(action_counts),
            "historical_order_status_counts": dict(order_statuses),
            "current_order_sides": dict(Counter(str(row.get("side", "UNKNOWN")) for row in current_orders)),
        },
        "behavior_profile": behavior_profile,
        "latest_snapshot": {
            "captured_at": latest_snapshot(state_document).get("capturedAt"),
            "account_value_usdc": str(account_value),
            "total_notional_usdc": str(position_value),
            "signed_notional_over_account_value": str(leverage),
            "btc_position": str(stated_position),
            "entry_price": btc_position.get("entryPx"),
            "unrealized_pnl": btc_position.get("unrealizedPnl"),
            "cross_leverage_value": (btc_position.get("leverage") or {}).get("value"),
        },
        "files": file_report,
        "version_boundary": {
            "comparison": comparison,
            "website_snapshot_is_authoritative": True,
            "rule": "Do not mix files from a different checkout or refresh unless its own manifest and hashes are verified.",
        },
        "checks": checks,
        "limitations": [
            "This is a separate Hyperliquid trader reference, not the BitMEX teacher account.",
            "It is not mixed into the current behavioral-distillation model.",
            "Website portfolio values are derived from snapshots, fills, funding and public candles; they are not imported as labels.",
            "Public data availability and the source-manifest revision must be rechecked before any future refresh.",
        ],
    }
    return result


def write_outputs(result: dict[str, Any], markdown_path: Path, json_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scope = result["scope"]
    coverage = result["coverage"]
    behavior = result["behavior"]
    profile = result["behavior_profile"]
    order_profile = profile["orders"]
    execution_profile = profile["execution"]
    episode_profile = profile["position_episodes"]
    latest = result["latest_snapshot"]
    comparison = result.get("version_boundary", {}).get("comparison", {})
    differing_files = [name for name, item in comparison.items() if not item.get("same")]
    lines = [
        "# External Hyperliquid Public Source Audit",
        "",
        f"- Status: **{result['status']}**",
        f"- Website snapshot synced at: `{scope.get('website_snapshot_synced_at')}`",
        f"- Source repository: `{scope.get('source_repository')}`",
        f"- Source revision: `{scope.get('source_revision')}`",
        f"- Target wallet: `{scope.get('target_user')}`",
        "- Model inclusion: **false** (audit-only external reference)",
        "",
        "## Coverage",
        "",
        f"- Historical order events / unique order IDs: {coverage['historical_order_events']} / {coverage['historical_order_ids']}",
        f"- Fills: {coverage['fills']}",
        f"- Funding records / total USDC: {coverage['funding_records']} / {coverage['funding_total_usdc']}",
        f"- Aligned state checkpoints: {coverage['snapshot_checkpoints']}",
        f"- Latest public open orders: {coverage['current_open_orders']}",
        "",
        "## Replayed behavior",
        "",
        f"- Fill window: `{behavior['first_fill_time_ms']}` → `{behavior['last_fill_time_ms']}` (Unix ms)",
        f"- Terminal position: `{behavior['terminal_position']} BTC`",
        f"- Maximum absolute position: `{behavior['maximum_abs_position']} BTC`",
        f"- Action counts: `{behavior['action_counts']}`",
        "",
        "## Independent behavior profile",
        "",
        "The following metrics are derived from the public order and fill events. They are descriptive observations, not recovered private rules and not training labels.",
        "",
        f"- Orders ever observed with a filled event: `{order_profile['orders_with_filled_event']}` / `{order_profile['unique_order_ids']}` (`{order_profile['ever_filled_fraction']}`)",
        f"- Orders ever observed with a canceled event: `{order_profile['orders_with_canceled_event']}` / `{order_profile['unique_order_ids']}` (`{order_profile['ever_canceled_fraction']}`)",
        f"- Order shape: all Limit=`{order_profile['all_limit_orders']}`, all GTC=`{order_profile['all_gtc_orders']}`, reduce-only events=`{order_profile['reduce_only_event_count']}`",
        f"- Order lifetime median / P90 / max: `{order_profile['lifetime_ms_median']}` / `{order_profile['lifetime_ms_p90']}` / `{order_profile['lifetime_ms_max']}` ms",
        f"- Fill crossed fraction: `{execution_profile['crossed_fill_fraction']}` ({execution_profile['crossed_fill_count']} / {execution_profile['fill_count']})",
        f"- Gross fill size / notional: `{execution_profile['gross_size_btc']} BTC` / `{execution_profile['gross_notional_usdc']} USDC`",
        f"- Reported fees / fee rate on gross notional: `{execution_profile['fee_total_usdc']} USDC` / `{execution_profile['fee_bps_on_gross_notional']} bps`",
        f"- Fill latency median / P90 / max: `{execution_profile['fill_latency_ms_median']}` / `{execution_profile['fill_latency_ms_p90']}` / `{execution_profile['fill_latency_ms_max']}` ms",
        f"- Position episodes: `{episode_profile['episode_count']}` total, `{episode_profile['closed_episode_count']}` closed, `{episode_profile['open_at_end_count']}` open at end",
        f"- Episode sides: `{episode_profile['long_episode_count']}` long / `{episode_profile['short_episode_count']}` short",
        f"- Episode duration median / max: `{episode_profile['duration_ms_median']}` / `{episode_profile['duration_ms_max']}` ms",
        f"- Fills per episode median: `{episode_profile['fills_per_episode_median']}`",
        "",
        "## Latest state",
        "",
        f"- Perpetual account value: `{latest['account_value_usdc']} USDC`",
        f"- Total perpetual notional: `{latest['total_notional_usdc']} USDC`",
        f"- Signed notional / account value: `{latest['signed_notional_over_account_value']}`",
        f"- BTC position: `{latest['btc_position']}`; entry: `{latest['entry_price']}`; unrealised: `{latest['unrealized_pnl']}`",
        "",
        "## Why this source matters",
        "",
        "The site demonstrates a reproducible public-account pipeline: pin the source revision and file hashes, preserve raw events, keep daily state checkpoints, collapse orders by lifecycle, replay fills into position, normalize funding aggregation, and only then derive leverage/PnL timelines.",
        "",
        "This report is an external reference for data engineering and behavior-audit design. It does not claim that the Hyperliquid trader and the BitMEX teacher used the same strategy, and it is not used as a training label.",
        "",
        "## Version boundary",
        "",
        "The website's published snapshot is treated as its own data version. A separate checkout of the same-named GitHub revision may contain different data-file bytes; if a comparison is supplied, those differences are retained here rather than silently merged.",
        "",
        *([f"- Compared files with different bytes: {', '.join(differing_files)}"] if differing_files else []),
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in result["limitations"]],
        "",
    ]
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--compare-data-dir", type=Path)
    parser.add_argument("--report-md", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.data_dir, args.manifest, args.compare_data_dir)
    write_outputs(result, args.report_md, args.report_json)
    print(json.dumps({"status": result["status"], "checks": len(result["checks"]), "report_md": str(args.report_md), "report_json": str(args.report_json)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
