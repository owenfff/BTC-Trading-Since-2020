from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quant" / "scripts"))

from audit_hyperliquid_l2_archive_access import build, probe_url


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_probe_uses_head_and_does_not_send_requester_pays_header() -> None:
    seen = {}

    def opener(request, timeout):
        seen["method"] = request.method
        seen["requester_pays"] = request.headers.get("X-amz-request-payer")
        seen["timeout"] = timeout
        return _Response()

    result = probe_url("https://example.test/object", opener=opener)
    assert result["status"] == "ACCESSIBLE_HEAD"
    assert seen == {"method": "HEAD", "requester_pays": None, "timeout": 15.0}


def test_probe_classifies_http_403_as_access_boundary() -> None:
    class _Forbidden:
        def __call__(self, _request, timeout):
            import urllib.error

            raise urllib.error.HTTPError("https://example.test/object", 403, "Forbidden", {}, None)

    result = probe_url("https://example.test/object", opener=_Forbidden())
    assert result["status"] == "HTTP_ERROR"
    assert result["http_status"] == 403


def test_no_probe_build_is_explicit_and_never_downloads(tmp_path: Path) -> None:
    output = build(report_path=tmp_path / "report.json", markdown_path=tmp_path / "report.md", probe=False)
    assert output["status"] == "NOT_PROBED"
    assert output["download_performed"] is False
    assert output["requester_pays_header_sent"] is False
