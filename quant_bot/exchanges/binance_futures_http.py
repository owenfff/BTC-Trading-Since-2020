from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from .http import AdapterError


BINANCE_FUTURES_TESTNET_REST_BASE_URL = "https://demo-fapi.binance.com"
BINANCE_FUTURES_TESTNET_WS_URL = "wss://demo-fstream.binance.com/ws"


@dataclass(frozen=True, repr=False)
class BinanceFuturesTestnetCredentials:
    api_key: str
    api_secret: str

    def __repr__(self) -> str:
        return "BinanceFuturesTestnetCredentials(api_key='<redacted>', api_secret='<redacted>')"

    @classmethod
    def from_environment(cls) -> "BinanceFuturesTestnetCredentials":
        names = ("BINANCE_FUTURES_TESTNET_API_KEY", "BINANCE_FUTURES_TESTNET_API_SECRET")
        values = tuple(os.environ.get(name, "").strip() for name in names)
        if not all(values):
            raise AdapterError("binance-futures-testnet", "TESTNET_CREDENTIALS_REQUIRED", f"{names[0]} and {names[1]} are required locally")
        for name, value in zip(names, values):
            try:
                value.encode("ascii")
            except UnicodeEncodeError as error:
                raise AdapterError("binance-futures-testnet", "NON_ASCII_CREDENTIAL", f"{name} contains non-ASCII characters; use the raw credential") from error
        return cls(*values)


def assert_binance_futures_testnet_url(url: str = BINANCE_FUTURES_TESTNET_REST_BASE_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "demo-fapi.binance.com":
        raise AdapterError("binance-futures-testnet", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only https://demo-fapi.binance.com is allowed")


def assert_binance_futures_testnet_ws_url(url: str = BINANCE_FUTURES_TESTNET_WS_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "wss" or parsed.netloc.lower() != "demo-fstream.binance.com" or parsed.path not in {"", "/", "/ws"}:
        raise AdapterError("binance-futures-testnet", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only wss://demo-fstream.binance.com/ws is allowed")


def binance_futures_signature(secret: str, query_string: str) -> str:
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


class BinanceFuturesTestnetTransport:
    """Native HMAC REST transport pinned to Binance USDⓈ-M Futures Testnet."""

    def __init__(self, credentials: BinanceFuturesTestnetCredentials, *, base_url: str = BINANCE_FUTURES_TESTNET_REST_BASE_URL, recv_window: int = 5000, timeout: float = 20.0, clock_ms: Any = lambda: int(time.time() * 1000)) -> None:
        assert_binance_futures_testnet_url(base_url)
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout = timeout
        self.clock_ms = clock_ms
        self.clock_offset_ms = 0
        self.last_rate_limit: dict[str, str] = {}

    def set_clock_offset_ms(self, offset_ms: int) -> None:
        self.clock_offset_ms = int(offset_ms)

    def _signed_query(self, path: str, body: dict[str, Any] | None) -> str:
        parsed = urlsplit(path)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if body:
            pairs.extend((str(key), str(value)) for key, value in body.items())
        pairs.extend((("timestamp", str(int(self.clock_ms()) + self.clock_offset_ms)), ("recvWindow", str(self.recv_window))))
        query = urlencode(pairs)
        return query + "&signature=" + binance_futures_signature(self.credentials.api_secret, query)

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, private: bool = False, api_key_only: bool = False) -> Any:
        parsed = urlsplit(path)
        if not (parsed.path.startswith("/fapi/v1/") or parsed.path.startswith("/fapi/v2/") or parsed.path.startswith("/fapi/v3/")):
            raise AdapterError("binance-futures-testnet", "INVALID_PATH", "Binance Futures Testnet paths must be /fapi/v1, /fapi/v2 or /fapi/v3 paths")
        query = self._signed_query(path, body) if private else parsed.query
        url = self.base_url + parsed.path + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": "btc-trading-since-2020-binance-futures-testnet"}
        if private or api_key_only:
            headers["X-MBX-APIKEY"] = self.credentials.api_key
        request = urllib.request.Request(url, headers=headers, method=method.upper())
        attempts = 3 if method.upper() == "GET" else 1
        raw = ""
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.last_rate_limit = {key: value for key, value in response.headers.items() if "weight" in key.lower() or "order" in key.lower()}
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                if error.code in {403, 451}:
                    raise AdapterError("binance-futures-testnet", "BINANCE_REGION_BLOCKED", "Binance Futures Testnet rejected this server's country or region", retryable=False) from error
                if error.code in {408, 429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise AdapterError("binance-futures-testnet", str(error.code), "Binance Futures Testnet REST request failed", retryable=error.code in {408, 429, 500, 502, 503, 504}) from error
            except (OSError, TimeoutError) as error:
                if attempt + 1 >= attempts:
                    raise AdapterError("binance-futures-testnet", "NETWORK", "Binance Futures Testnet REST request failed", retryable=True) from error
                time.sleep(0.5 * (attempt + 1))
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as error:
            raise AdapterError("binance-futures-testnet", "SCHEMA", "Binance Futures Testnet returned non-JSON data") from error

    def request_api_key(self, method: str, path: str) -> Any:
        return self.request(method, path, api_key_only=True)


__all__ = [
    "BINANCE_FUTURES_TESTNET_REST_BASE_URL",
    "BINANCE_FUTURES_TESTNET_WS_URL",
    "BinanceFuturesTestnetCredentials",
    "BinanceFuturesTestnetTransport",
    "assert_binance_futures_testnet_url",
    "assert_binance_futures_testnet_ws_url",
    "binance_futures_signature",
]
