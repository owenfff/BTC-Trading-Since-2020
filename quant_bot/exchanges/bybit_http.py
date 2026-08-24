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
from typing import Any
from urllib.parse import urlsplit

from .http import AdapterError


DEMO_REST_BASE_URL = "https://api-demo.bybit.com"
DEMO_WS_URL = "wss://stream-demo.bybit.com/v5/private"


@dataclass(frozen=True, repr=False)
class BybitCredentials:
    api_key: str
    api_secret: str

    def __repr__(self) -> str:
        return "BybitCredentials(api_key='<redacted>', api_secret='<redacted>')"

    @classmethod
    def from_environment(cls) -> "BybitCredentials":
        key = os.environ.get("BYBIT_DEMO_API_KEY", "").strip()
        secret = os.environ.get("BYBIT_DEMO_API_SECRET", "").strip()
        if not key or not secret:
            raise AdapterError("bybit-demo", "DEMO_CREDENTIALS_REQUIRED", "BYBIT_DEMO_API_KEY and BYBIT_DEMO_API_SECRET are required locally")
        for name, value in (("BYBIT_DEMO_API_KEY", key), ("BYBIT_DEMO_API_SECRET", secret)):
            try:
                value.encode("ascii")
            except UnicodeEncodeError as error:
                raise AdapterError("bybit-demo", "NON_ASCII_CREDENTIAL", f"{name} contains non-ASCII characters; use the raw Bybit credential") from error
        return cls(key, secret)


def assert_demo_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "api-demo.bybit.com":
        raise AdapterError("bybit-demo", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only https://api-demo.bybit.com is allowed")


def assert_demo_ws_url(url: str = DEMO_WS_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "wss" or parsed.netloc.lower() != "stream-demo.bybit.com":
        raise AdapterError("bybit-demo", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only wss://stream-demo.bybit.com is allowed")


def bybit_signature(secret: str, timestamp_ms: int, api_key: str, recv_window: int, payload: str) -> str:
    message = f"{timestamp_ms}{api_key}{recv_window}{payload}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def bybit_websocket_signature(secret: str, expires_ms: int) -> str:
    return hmac.new(secret.encode("utf-8"), f"GET/realtime{expires_ms}".encode("utf-8"), hashlib.sha256).hexdigest()


class BybitDemoTransport:
    """V5 REST transport pinned to Bybit Demo Trading."""

    def __init__(self, credentials: BybitCredentials, *, base_url: str = DEMO_REST_BASE_URL, recv_window: int = 30_000, timeout: float = 20.0, clock_ms: Any = lambda: int(time.time() * 1000)) -> None:
        assert_demo_url(base_url)
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout = timeout
        self.clock_ms = clock_ms
        self.clock_offset_ms = 0
        self.clock_synced_at_ms = 0
        self.last_rate_limit: dict[str, str] = {}

    def set_clock_offset_ms(self, offset_ms: int) -> None:
        """Apply a server-minus-local clock offset to signed requests."""

        self.clock_offset_ms = int(offset_ms)
        self.clock_synced_at_ms = int(self.clock_ms())

    def _sync_clock(self) -> None:
        local_before_ms = int(self.clock_ms())
        response = self.request("GET", "/v5/market/time")
        local_after_ms = int(self.clock_ms())
        if not isinstance(response, dict) or str(response.get("retCode", "0")) != "0":
            raise AdapterError("bybit-demo", str(response.get("retCode", "SCHEMA")), str(response.get("retMsg", "invalid server time response")))
        timestamp = response.get("time") or response.get("result", {}).get("timeNano", "")
        if not timestamp:
            raise AdapterError("bybit-demo", "SCHEMA", "Bybit Demo returned no server time")
        server_ms = int(str(timestamp)[:13])
        midpoint_ms = (local_before_ms + local_after_ms) // 2
        self.clock_offset_ms = server_ms - midpoint_ms
        self.clock_synced_at_ms = local_after_ms

    def _clock_sync_stale(self) -> bool:
        return self.clock_synced_at_ms <= 0 or abs(int(self.clock_ms()) - self.clock_synced_at_ms) > 30_000

    @staticmethod
    def _payload(body: dict[str, Any] | None) -> str:
        return json.dumps(body or {}, separators=(",", ":"), ensure_ascii=False) if body is not None else ""

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, private: bool = False, _timestamp_retry: bool = False) -> Any:
        if not path.startswith("/v5/"):
            raise AdapterError("bybit-demo", "INVALID_PATH", "Bybit paths must be /v5/... paths")
        verb = method.upper()
        if private and self._clock_sync_stale():
            self._sync_clock()
        query = path.split("?", 1)[1] if "?" in path else ""
        payload = self._payload(body) if verb != "GET" else query
        url = self.base_url + path
        headers = {"Accept": "application/json", "User-Agent": "btc-trading-since-2020-bybit-demo"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if private:
            timestamp = int(self.clock_ms()) + self.clock_offset_ms
            headers.update({
                "X-BAPI-API-KEY": self.credentials.api_key,
                "X-BAPI-TIMESTAMP": str(timestamp),
                "X-BAPI-RECV-WINDOW": str(self.recv_window),
                "X-BAPI-SIGN": bybit_signature(self.credentials.api_secret, timestamp, self.credentials.api_key, self.recv_window, payload),
                "X-BAPI-SIGN-TYPE": "2",
            })
        request = urllib.request.Request(url, data=payload.encode("utf-8") if body is not None else None, headers=headers, method=verb)
        network_attempts = 3 if verb == "GET" else 1
        for attempt in range(network_attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.last_rate_limit = {key: value for key, value in response.headers.items() if "ratelimit" in key.lower()}
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                raw_error = error.read().decode("utf-8", errors="replace")
                if error.code in {408, 429, 500, 502, 503, 504} and attempt + 1 < network_attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if error.code == 403 and "configured to block access from your country" in raw_error.lower():
                    raise AdapterError(
                        "bybit-demo",
                        "BYBIT_REGION_BLOCKED",
                        "Bybit Demo blocked this server's country or region",
                        retryable=False,
                    ) from error
                raise AdapterError("bybit-demo", str(error.code), "Bybit Demo REST request failed", retryable=error.code in {408, 429, 500, 502, 503, 504}) from error
            except (OSError, TimeoutError) as error:
                if attempt + 1 >= network_attempts:
                    raise AdapterError("bybit-demo", "NETWORK", "Bybit Demo REST request failed", retryable=True) from error
                time.sleep(0.5 * (attempt + 1))
        try:
            result = json.loads(raw) if raw else {}
            if private and not _timestamp_retry and isinstance(result, dict) and str(result.get("retCode", "")) == "10002":
                self._sync_clock()
                return self.request(method, path, body=body, private=True, _timestamp_retry=True)
            return result
        except json.JSONDecodeError as error:
            raise AdapterError("bybit-demo", "SCHEMA", "Bybit returned non-JSON data") from error


__all__ = ["BybitCredentials", "BybitDemoTransport", "DEMO_REST_BASE_URL", "DEMO_WS_URL", "assert_demo_url", "assert_demo_ws_url", "bybit_signature", "bybit_websocket_signature"]
