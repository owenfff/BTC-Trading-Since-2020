from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from .http import AdapterError


OKX_DEMO_REST_BASE_URL = "https://us.okx.com"
OKX_DEMO_PUBLIC_WS_URL = "wss://wsuspap.okx.com:8443/ws/v5/public"
OKX_DEMO_PRIVATE_WS_URL = "wss://wsuspap.okx.com:8443/ws/v5/private"


@dataclass(frozen=True, repr=False)
class OKXDemoCredentials:
    api_key: str
    api_secret: str
    passphrase: str

    def __repr__(self) -> str:
        return "OKXDemoCredentials(api_key='<redacted>', api_secret='<redacted>', passphrase='<redacted>')"

    @classmethod
    def from_environment(cls) -> "OKXDemoCredentials":
        names = ("OKX_DEMO_API_KEY", "OKX_DEMO_API_SECRET", "OKX_DEMO_API_PASSPHRASE")
        values = tuple(os.environ.get(name, "").strip() for name in names)
        if not all(values):
            raise AdapterError("okx-demo", "DEMO_CREDENTIALS_REQUIRED", f"{names[0]}, {names[1]} and {names[2]} are required locally")
        for name, value in zip(names, values):
            try:
                value.encode("ascii")
            except UnicodeEncodeError as error:
                raise AdapterError("okx-demo", "NON_ASCII_CREDENTIAL", f"{name} contains non-ASCII characters; use the raw credential") from error
        return cls(*values)


def assert_okx_demo_url(url: str = OKX_DEMO_REST_BASE_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "us.okx.com":
        raise AdapterError("okx-demo", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only https://us.okx.com is allowed for OKX Demo")


def assert_okx_demo_ws_url(url: str = OKX_DEMO_PRIVATE_WS_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "wss" or parsed.netloc.lower() != "wsuspap.okx.com:8443":
        raise AdapterError("okx-demo", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only OKX Demo WebSocket endpoints are allowed")


def okx_signature(secret: str, timestamp: str, method: str, request_path: str, body: str = "") -> str:
    message = f"{timestamp}{method.upper()}{request_path}{body}".encode("utf-8")
    return base64.b64encode(hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")


def okx_websocket_signature(secret: str, timestamp_seconds: int) -> str:
    return okx_signature(secret, str(timestamp_seconds), "GET", "/users/self/verify")


class OKXDemoTransport:
    """Native REST transport pinned to the OKX Demo environment."""

    def __init__(self, credentials: OKXDemoCredentials, *, base_url: str = OKX_DEMO_REST_BASE_URL, timeout: float = 20.0, clock_ms: Any = lambda: int(time.time() * 1000)) -> None:
        assert_okx_demo_url(base_url)
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.clock_ms = clock_ms
        self.clock_offset_ms = 0
        self.last_rate_limit: dict[str, str] = {}

    def set_clock_offset_ms(self, offset_ms: int) -> None:
        self.clock_offset_ms = int(offset_ms)

    def _timestamp(self) -> str:
        value = datetime.fromtimestamp((int(self.clock_ms()) + self.clock_offset_ms) / 1000, timezone.utc)
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _body(body: dict[str, Any] | None) -> str:
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, private: bool = False) -> Any:
        if not path.startswith("/api/v5/"):
            raise AdapterError("okx-demo", "INVALID_PATH", "OKX paths must be /api/v5/... paths")
        verb = method.upper()
        body_text = self._body(body) if verb != "GET" else ""
        headers = {"Accept": "application/json", "User-Agent": "btc-trading-since-2020-okx-demo"}
        if body is not None and verb != "GET":
            headers["Content-Type"] = "application/json"
        if private:
            timestamp = self._timestamp()
            headers.update({
                "OK-ACCESS-KEY": self.credentials.api_key,
                "OK-ACCESS-SIGN": okx_signature(self.credentials.api_secret, timestamp, verb, path, body_text),
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.credentials.passphrase,
            })
        headers["x-simulated-trading"] = "1"
        request = urllib.request.Request(self.base_url + path, data=body_text.encode("utf-8") if body_text else None, headers=headers, method=verb)
        attempts = 3 if verb == "GET" else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.last_rate_limit = {key: value for key, value in response.headers.items() if "limit" in key.lower()}
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                if error.code in {408, 429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise AdapterError("okx-demo", str(error.code), "OKX Demo REST request failed", retryable=error.code in {408, 429, 500, 502, 503, 504}) from error
            except (OSError, TimeoutError) as error:
                if attempt + 1 >= attempts:
                    raise AdapterError("okx-demo", "NETWORK", "OKX Demo REST request failed", retryable=True) from error
                time.sleep(0.5 * (attempt + 1))
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as error:
            raise AdapterError("okx-demo", "SCHEMA", "OKX Demo returned non-JSON data") from error


__all__ = ["OKXDemoCredentials", "OKXDemoTransport", "OKX_DEMO_REST_BASE_URL", "OKX_DEMO_PUBLIC_WS_URL", "OKX_DEMO_PRIVATE_WS_URL", "assert_okx_demo_url", "assert_okx_demo_ws_url", "okx_signature", "okx_websocket_signature"]
