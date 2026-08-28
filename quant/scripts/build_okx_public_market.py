#!/usr/bin/env python3
"""Backfill OKX public market history for causal indicator replay.

Usage from the repository root::

    python quant/scripts/build_okx_public_market.py \
      --inst-id BTC-USDT-SWAP --bar 1H \
      --start 2020-01-01T00:00:00Z --end now

The command never reads credentials and never calls an account or trading
endpoint.  Raw page caches and generated row-level CSVs are written below
``quant/outputs/okx_public_market`` and are intentionally ignored by Git.
Only compact lineage and coverage summaries are tracked.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.io_utils import sha256_file  # noqa: E402
from market.okx_public import (  # noqa: E402
    OKX_PUBLIC_API_ROOT,
    OKX_PUBLIC_DOCUMENTATION,
    OkxPublicClient,
    OkxPublicError,
    attach_okx_context,
    audit_okx_grid,
    build_causal_indicator_rows,
    fetch_funding_history,
    fetch_history_candles,
    infer_index_id,
    write_rows_csv,
)
from market.download import parse_utc  # noqa: E402


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


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _hash_existing(root: Path) -> dict[str, str]:
    return {name: sha256_file(root / name) for name in PROTECTED_FILES if (root / name).exists()}


def _time_arg(value: str) -> datetime:
    if value.strip().lower() == "now":
        return datetime.now(timezone.utc)
    parsed = parse_utc(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"invalid UTC time: {value}")
    return parsed


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _fetch_optional(fetcher, *, kind: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        return fetcher()
    except (OkxPublicError, ValueError) as exc:
        return [], {
            "status": "UNAVAILABLE",
            "source_kind": kind,
            "row_count": 0,
            "credentials": "none",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "note": "Context is retained as missing; no zero-value substitution is performed.",
        }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# OKX Public Market History Audit",
        "",
        f"- status: **{report['status']}**",
        f"- analysis commit: `{report['analysis_commit']}`",
        f"- source: `{report['source']['base_url']}`; credentials: `none`",
        f"- requested range: `{report['start_time_utc']}` to `{report['end_time_utc']}`",
        "",
        "## What was imported",
        "",
        "The importer uses OKX public history endpoints only. Candle rows are filtered to `confirm=1`; the source opening timestamp is retained and the normalized `timestamp` is the bar close. All context joins are previous-or-equal to that closed bar.",
        "",
        "| instrument | candle rows | mark rows | index rows | funding rows | candle audit | causal violations | status |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for item in report["instruments"]:
        lines.append(
            f"| {item['inst_id']} | {item['candles'].get('normalized_row_count', 0)} | {item['mark_price'].get('normalized_row_count', 0)} | {item['index_price'].get('normalized_row_count', 0)} | {item['funding'].get('normalized_row_count', 0)} | {item['candle_audit'].get('status', '')} | {item['feature_audit'].get('causal_timestamp_violation_count', 0)} | {item['status']} |"
        )
    lines.extend([
        "",
        "## Coverage interpretation",
        "",
        "- OKX historical candles are the primary market series for replay; no BitMEX price is substituted.",
        "- Funding is best-effort and may be limited by OKX public retention. Missing funding remains `None` with a missing mask.",
        "- Mark/index history is attached only when its source timestamp is not later than the closed candle. A missing context value is not replaced with zero.",
        "- Public trade history is not used as a multi-year replacement for the original trader's private BitMEX fills. This output is market context, not teacher labels.",
        "",
        "## Lineage and safety",
        "",
        f"- documentation: [{OKX_PUBLIC_DOCUMENTATION}]({OKX_PUBLIC_DOCUMENTATION})",
        f"- protected raw account inputs unchanged: `{report['raw_account_inputs_unchanged']}`",
        f"- changed protected files: `{report['changed_protected_files']}`",
        "- raw API page caches and row-level outputs are under ignored `quant/outputs/okx_public_market/`.",
        "- no API key, secret, passphrase, private endpoint, Demo account, or order endpoint is used by this command.",
        "",
        "## Next use",
        "",
        "Use the generated `features.csv` as a market-context input to the existing historical replay. Keep the BitMEX CSV events as the separate teacher behavior source, and evaluate any model with strict autonomous replay before changing the active Demo model.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    *,
    inst_ids: list[str],
    bar: str,
    start: datetime,
    end: datetime,
    include_context: bool = True,
    max_pages: int = 1000,
    base_url: str = OKX_PUBLIC_API_ROOT,
    timeout: float = 90.0,
    cache_root: Path | None = None,
    client: OkxPublicClient | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    root = Path(root)
    report_dir = root / "quant" / "reports"
    output_root = Path(cache_root) if cache_root is not None else root / "quant" / "outputs" / "okx_public_market"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    before = _hash_existing(root)
    public_client = client or OkxPublicClient(base_url=base_url, timeout=timeout)
    interval_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "2H": 7200, "4H": 14400}.get(bar, 3600)
    instruments: list[dict[str, Any]] = []
    for inst_id in inst_ids:
        normalized_inst_id = inst_id.strip().upper()
        stem = "".join(char if char.isalnum() or char in "._-" else "_" for char in f"{normalized_inst_id}_{bar}")
        instrument_root = output_root / stem
        cache_dir = instrument_root / "raw_pages"
        try:
            candles, candles_lineage = fetch_history_candles(
                public_client,
                inst_id=normalized_inst_id,
                bar=bar,
                start=start,
                end=end,
                max_pages=max_pages,
                cache_dir=cache_dir / "candles",
            )
        except (OkxPublicError, ValueError) as exc:
            candles = []
            candles_lineage = {
                "status": "UNAVAILABLE",
                "source_kind": "candles",
                "normalized_row_count": 0,
                "credentials": "none",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "note": "Primary public candles are unavailable; no synthetic bars were created.",
            }
        mark_rows: list[dict[str, Any]] = []
        index_rows: list[dict[str, Any]] = []
        funding_rows: list[dict[str, Any]] = []
        mark_lineage: dict[str, Any] = {"status": "SKIPPED", "normalized_row_count": 0}
        index_lineage: dict[str, Any] = {"status": "SKIPPED", "normalized_row_count": 0}
        funding_lineage: dict[str, Any] = {"status": "SKIPPED", "normalized_row_count": 0}
        if include_context and candles:
            mark_rows, mark_lineage = _fetch_optional(
                lambda: fetch_history_candles(
                    public_client,
                    inst_id=normalized_inst_id,
                    bar=bar,
                    start=start,
                    end=end,
                    max_pages=max_pages,
                    cache_dir=cache_dir / "mark_price",
                    source_kind="mark_price",
                ),
                kind="mark_price",
            )
            index_id = infer_index_id(normalized_inst_id)
            index_rows, index_lineage = _fetch_optional(
                lambda: fetch_history_candles(
                    public_client,
                    inst_id=index_id,
                    bar=bar,
                    start=start,
                    end=end,
                    max_pages=max_pages,
                    cache_dir=cache_dir / "index",
                    source_kind="index",
                ),
                kind="index",
            )
            funding_rows, funding_lineage = _fetch_optional(
                lambda: fetch_funding_history(
                    public_client,
                    inst_id=normalized_inst_id,
                    start=start,
                    end=end,
                    max_pages=max_pages,
                    cache_dir=cache_dir / "funding",
                ),
                kind="funding",
            )
        context_rows, context_audit = attach_okx_context(candles, mark_rows=mark_rows, index_rows=index_rows, funding_rows=funding_rows)
        feature_rows, feature_audit = build_causal_indicator_rows(context_rows, interval_seconds=interval_seconds)
        paths = {
            "candles": str((instrument_root / "candles.csv").relative_to(root)),
            "context": str((instrument_root / "context.csv").relative_to(root)),
            "features": str((instrument_root / "features.csv").relative_to(root)),
        }
        hashes = {
            "candles": write_rows_csv(root / paths["candles"], candles),
            "context": write_rows_csv(root / paths["context"], context_rows),
            "features": write_rows_csv(root / paths["features"], feature_rows),
        }
        candle_audit = audit_okx_grid(candles, interval_seconds=interval_seconds)
        context_status = context_audit.get("status_counts", {})
        status = "PASS" if candles and candles_lineage.get("status") == "PASS" and candle_audit["status"] == "PASS" and feature_audit["causal_timestamp_violation_count"] == 0 else ("READY_WITH_WARNINGS" if candles else "BLOCKED")
        instruments.append({
            "inst_id": normalized_inst_id,
            "instrument_class": "SWAP" if normalized_inst_id.endswith("-SWAP") else ("FUTURES" if "-" in normalized_inst_id else "UNKNOWN"),
            "bar": bar,
            "interval_seconds": interval_seconds,
            "candles": candles_lineage,
            "mark_price": mark_lineage,
            "index_price": index_lineage,
            "funding": funding_lineage,
            "candle_audit": candle_audit,
            "context_audit": context_audit,
            "context_status_counts": context_status,
            "feature_audit": feature_audit,
            "output_paths": paths,
            "output_sha256": hashes,
            "status": status,
            "notes": [
                "OKX public market rows are not teacher labels.",
                "Contract multiplier, tick size, minimum size, fees, and margin remain exchange-adapter fields.",
            ],
        })
    after = _hash_existing(root)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    any_blocked = any(item["status"] == "BLOCKED" for item in instruments)
    report: dict[str, Any] = {
        "report_version": "OKX-PUBLIC-MARKET-1.0",
        "status": "BLOCKED" if any_blocked else ("READY_WITH_WARNINGS" if any(item["status"] == "READY_WITH_WARNINGS" for item in instruments) else "PASS"),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "analysis_commit": _git(["rev-parse", "HEAD"]),
        "analysis_branch": _git(["branch", "--show-current"]),
        "run_time_utc": datetime.now(timezone.utc),
        "start_time_utc": start,
        "end_time_utc": end,
        "source": {
            "provider": "OKX",
            "base_url": public_client.base_url,
            "credentials": "none",
            "public_only": True,
            "documentation": OKX_PUBLIC_DOCUMENTATION,
            "endpoints": {
                "candles": "/api/v5/market/history-candles",
                "mark_price": "/api/v5/market/history-mark-price-candles",
                "index": "/api/v5/market/history-index-candles",
                "funding": "/api/v5/public/funding-rate-history",
            },
        },
        "pagination": {
            "direction": "backward_by_after_timestamp",
            "max_pages": max_pages,
            "no_synthetic_fill": True,
        },
        "instruments": instruments,
        "raw_account_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "next_action": "Use the generated features.csv as market context in a separate causal replay; do not merge it with BitMEX private fills or promote a model without strict autonomous validation.",
    }
    json_path = report_dir / "okx_public_market_audit.json"
    json_path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report, report_dir / "okx_public_market_audit.md")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inst-id", action="append", dest="inst_ids", default=None, help="OKX instrument ID; repeat for multiple instruments")
    parser.add_argument("--bar", default="1H", choices=["1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H"], help="OKX candle interval")
    parser.add_argument("--start", type=_time_arg, default=_time_arg("2020-01-01T00:00:00Z"), help="inclusive UTC range start")
    parser.add_argument("--end", type=_time_arg, default=_time_arg("now"), help="inclusive UTC range end or now")
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--skip-context", action="store_true", help="only download candles, not mark/index/funding history")
    parser.add_argument("--base-url", default=OKX_PUBLIC_API_ROOT, help="HTTPS OKX public host only")
    parser.add_argument("--timeout", type=float, default=90.0, help="public request timeout in seconds")
    args = parser.parse_args(argv)
    report = run(
        inst_ids=args.inst_ids or ["BTC-USDT-SWAP"],
        bar=args.bar,
        start=args.start,
        end=args.end,
        include_context=not args.skip_context,
        max_pages=args.max_pages,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    print(json.dumps(_jsonable({
        "status": report["status"],
        "instruments": [{"inst_id": item["inst_id"], "status": item["status"], "candle_rows": item["candles"].get("normalized_row_count", 0), "causal_violations": item["feature_audit"].get("causal_timestamp_violation_count", 0)} for item in report["instruments"]],
        "raw_account_inputs_unchanged": report["raw_account_inputs_unchanged"],
        "reports": ["quant/reports/okx_public_market_audit.md", "quant/reports/okx_public_market_audit.json"],
    }), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
