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


BINANCE_SPOT_TESTNET_REST_BASE_URL = "https://testnet.binance.vision"
BINANCE_SPOT_TESTNET_WS_URL = "wss://stream.testnet.binance.vision/ws"


@dataclass(frozen=True, repr=False)
class BinanceTestnetCredentials:
    api_key: str
    api_secret: str

    def __repr__(self) -> str:
        return "BinanceTestnetCredentials(api_key='<redacted>', api_secret='<redacted>')"

    @classmethod
    def from_environment(cls) -> "BinanceTestnetCredentials":
        names = ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET")
        values = tuple(os.environ.get(name, "").strip() for name in names)
        if not all(values):
            raise AdapterError("binance-spot-testnet", "TESTNET_CREDENTIALS_REQUIRED", f"{names[0]} and {names[1]} are required locally")
        for name, value in zip(names, values):
            try:
                value.encode("ascii")
            except UnicodeEncodeError as error:
                raise AdapterError("binance-spot-testnet", "NON_ASCII_CREDENTIAL", f"{name} contains non-ASCII characters; use the raw credential") from error
        return cls(*values)


def assert_binance_spot_testnet_url(url: str = BINANCE_SPOT_TESTNET_REST_BASE_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "testnet.binance.vision":
        raise AdapterError("binance-spot-testnet", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only https://testnet.binance.vision is allowed")


def assert_binance_spot_testnet_ws_url(url: str = BINANCE_SPOT_TESTNET_WS_URL) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "wss" or parsed.netloc.lower() != "stream.testnet.binance.vision":
        raise AdapterError("binance-spot-testnet", "MAINNET_OR_UNTRUSTED_ENDPOINT", "only wss://stream.testnet.binance.vision is allowed")


def binance_signature(secret: str, query_string: str) -> str:
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


class BinanceSpotTestnetTransport:
    """Native HMAC REST transport pinned to Binance Spot Testnet."""

    def __init__(self, credentials: BinanceTestnetCredentials, *, base_url: str = BINANCE_SPOT_TESTNET_REST_BASE_URL, recv_window: int = 5000, timeout: float = 20.0, clock_ms: Any = lambda: int(time.time() * 1000)) -> None:
        assert_binance_spot_testnet_url(base_url)
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
        return query + "&signature=" + binance_signature(self.credentials.api_secret, query)

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, private: bool = False, api_key_only: bool = False) -> Any:
        if not path.startswith("/api/v3/"):
            raise AdapterError("binance-spot-testnet", "INVALID_PATH", "Binance Spot Testnet paths must be /api/v3/... paths")
        parsed = urlsplit(path)
        query = self._signed_query(path, body) if private else parsed.query
        url = self.base_url + parsed.path + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": "btc-trading-since-2020-binance-testnet"}
        if private or api_key_only:
            headers["X-MBX-APIKEY"] = self.credentials.api_key
        request = urllib.request.Request(url, headers=headers, method=method.upper())
        attempts = 3 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.last_rate_limit = {key: value for key, value in response.headers.items() if "weight" in key.lower() or "order" in key.lower()}
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                if error.code in {403, 451}:
                    raise AdapterError("binance-spot-testnet", "BINANCE_REGION_BLOCKED", "Binance Spot Testnet rejected this server's country or region", retryable=False) from error
                if error.code in {408, 429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise AdapterError("binance-spot-testnet", str(error.code), "Binance Spot Testnet REST request failed", retryable=error.code in {408, 429, 500, 502, 503, 504}) from error
            except (OSError, TimeoutError) as error:
                if attempt + 1 >= attempts:
                    raise AdapterError("binance-spot-testnet", "NETWORK", "Binance Spot Testnet REST request failed", retryable=True) from error
                time.sleep(0.5 * (attempt + 1))
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as error:
            raise AdapterError("binance-spot-testnet", "SCHEMA", "Binance Spot Testnet returned non-JSON data") from error

    def request_api_key(self, method: str, path: str) -> Any:
        """Call a user-data endpoint with the API key but without HMAC signing."""

        return self.request(method, path, api_key_only=True)


__all__ = ["BinanceTestnetCredentials", "BinanceSpotTestnetTransport", "BINANCE_SPOT_TESTNET_REST_BASE_URL", "BINANCE_SPOT_TESTNET_WS_URL", "assert_binance_spot_testnet_url", "assert_binance_spot_testnet_ws_url", "binance_signature"]
