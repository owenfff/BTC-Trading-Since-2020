#!/usr/bin/env python3
"""Probe Hyperliquid historical L2 archive access without downloading data.

The official archive may be requester-pays and may have gaps.  This command
only sends HEAD requests to representative object keys and records the access
boundary; it never sends credentials, a requester-pays header, or downloads a
market file.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "quant" / "reports" / "hyperliquid_l2_archive_access.json"
REPORT_MD = ROOT / "quant" / "reports" / "hyperliquid_l2_archive_access.md"
UTC = timezone.utc

PROBE_KEYS = (
    "market_data/20251115/17/l2Book/BTC.lz4",
    "market_data/20251115/18/l2Book/BTC.lz4",
    "market_data/20260101/00/l2Book/BTC.lz4",
    "market_data/20260718/20/l2Book/BTC.lz4",
)
BASE_URL = "https://hyperliquid-archive.s3.amazonaws.com/"


def probe_url(url: str, *, opener: Callable[..., Any] = urllib.request.urlopen, timeout: float = 15.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "quant-public-archive-audit/1.0"})
    try:
        with opener(request, timeout=timeout) as response:
            return {"url": url, "http_status": int(response.status), "status": "ACCESSIBLE_HEAD"}
    except urllib.error.HTTPError as error:
        return {"url": url, "http_status": int(error.code), "status": "HTTP_ERROR", "error_reason": str(error.reason)}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"url": url, "http_status": None, "status": "NETWORK_ERROR", "error_reason": str(error)}


def build(*, report_path: Path = REPORT, markdown_path: Path = REPORT_MD, probe: bool = True) -> dict[str, Any]:
    results = [probe_url(BASE_URL + key) for key in PROBE_KEYS] if probe else []
    if not results:
        access_status = "NOT_PROBED"
    elif all(item.get("http_status") == 403 for item in results):
        access_status = "REQUESTER_OR_OBJECT_ACCESS_BLOCKED"
    elif all(item.get("status") == "ACCESSIBLE_HEAD" for item in results):
        access_status = "HEAD_ACCESSIBLE_DOWNLOAD_NOT_ATTEMPTED"
    else:
        access_status = "MIXED_OR_INCONCLUSIVE"
    output = {
        "report_version": "M15-HYPERLIQUID-L2-ARCHIVE-ACCESS-1.0",
        "status": access_status,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "archive_base_url": BASE_URL,
        "probe_method": "HTTP HEAD only; no body download",
        "requester_pays_header_sent": False,
        "download_performed": False,
        "probe_keys": list(PROBE_KEYS),
        "probe_results": results,
        "interpretation": "A 403 response is an access boundary, not proof that an object is absent. The archive remains unverified in this environment and must not be treated as complete historical quote/order-book context.",
        "impact_on_strategy_learning": "Historical L2 context is not available to the current reproducible pipeline; exact pre-action trigger recovery remains incomplete.",
        "raw_inputs_untouched": True,
        "active_demo_unchanged": True,
        "promotion_allowed": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Hyperliquid Historical L2 Archive Access Audit",
        "",
        f"> Status: **`{access_status}`**. This was a no-download access probe, not a data import.",
        "",
        "## Probe",
        "",
        "- Method: HTTP `HEAD` only.",
        "- Requester-pays header: not sent.",
        "- Market-file body downloaded: no.",
        "- Representative object keys checked:",
    ]
    lines.extend(f"  - `{key}`" for key in PROBE_KEYS)
    lines += [
        "",
        "## Result",
        "",
        "| HTTP status | count |",
        "|---:|---:|",
    ]
    counts: dict[str, int] = {}
    for result in results:
        key = str(result.get("http_status") or result.get("status"))
        counts[key] = counts.get(key, 0) + 1
    lines.extend(f"| `{key}` | {value} |" for key, value in sorted(counts.items()))
    lines += [
        "",
        "A `403` is ambiguous between requester-pays/object authorization and an unavailable key. It is not evidence that historical L2 is absent, but the data cannot be used until access, cost, and coverage are independently verified.",
        "",
        "## Boundary",
        "",
        "No credentials, requester-pays header, private endpoint, mainnet connection, order, or market-file download was used. The active Demo model remains unchanged and promotion is not allowed.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-probe", action="store_true", help="write a schema-only report without network access")
    args = parser.parse_args()
    try:
        output = build(probe=not args.no_probe)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "HYPERLIQUID_L2_ARCHIVE_ACCESS_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": output["status"], "report": str(REPORT), "download_performed": output["download_performed"], "requester_pays_header_sent": output["requester_pays_header_sent"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
