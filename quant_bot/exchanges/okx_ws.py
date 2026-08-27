from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from collections import defaultdict
from typing import Any, Callable

from .http import AdapterError
from .okx_http import OKXDemoCredentials, OKX_DEMO_PRIVATE_WS_URL, assert_okx_demo_ws_url, okx_websocket_signature


class OKXDemoWebSocket:
    """Private OKX Demo stream with login, subscriptions and reconnects."""

    def __init__(self, credentials: OKXDemoCredentials, *, url: str = OKX_DEMO_PRIVATE_WS_URL, connect_factory: Any | None = None, clock_seconds: Any = lambda: int(time.time())) -> None:
        assert_okx_demo_ws_url(url)
        self.credentials = credentials
        self.url = url
        self.connect_factory = connect_factory
        self.clock_seconds = clock_seconds
        self.clock_offset_seconds = 0
        self.socket: Any = None
        self.connected = False
        self.seen_messages: set[str] = set()
        self.latest: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.pending_messages: list[dict[str, Any]] = []

    def set_clock_offset_ms(self, offset_ms: int) -> None:
        self.clock_offset_seconds = int(offset_ms / 1000)

    def login_message(self) -> dict[str, Any]:
        timestamp = int(self.clock_seconds()) + self.clock_offset_seconds
        return {"op": "login", "args": [{"apiKey": self.credentials.api_key, "passphrase": self.credentials.passphrase, "timestamp": str(timestamp), "sign": okx_websocket_signature(self.credentials.api_secret, timestamp)}]}

    @staticmethod
    def message_id(message: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def accept_message(self, message: dict[str, Any]) -> bool:
        identifier = self.message_id(message)
        if identifier in self.seen_messages:
            return False
        self.seen_messages.add(identifier)
        arg = message.get("arg") if isinstance(message.get("arg"), dict) else {}
        channel = str(arg.get("channel") or "")
        data = message.get("data")
        if channel and isinstance(data, list):
            self.latest[channel] = [dict(item) for item in data if isinstance(item, dict)]
        return True

    async def connect(self, channels: list[Any]) -> None:
        if self.connect_factory is not None:
            factory = self.connect_factory
        else:
            try:
                import websockets
            except ImportError as error:
                raise AdapterError("okx-demo", "WEBSOCKET_DEPENDENCY_MISSING", "install the pinned websockets runtime dependency") from error
            factory = websockets.connect
        self.socket = await factory(self.url, ping_interval=20, ping_timeout=20, close_timeout=5)
        await self.socket.send(json.dumps(self.login_message(), separators=(",", ":")))
        try:
            raw_login = await asyncio.wait_for(self.socket.recv(), timeout=10)
        except asyncio.TimeoutError as error:
            raise AdapterError("okx-demo", "WEBSOCKET_AUTH_TIMEOUT", "OKX private WebSocket login acknowledgement timed out", retryable=True) from error
        try:
            login_message = json.loads(raw_login)
        except (TypeError, json.JSONDecodeError) as error:
            raise AdapterError("okx-demo", "WEBSOCKET_AUTH_SCHEMA", "OKX private WebSocket login acknowledgement was invalid") from error
        if not isinstance(login_message, dict):
            raise AdapterError("okx-demo", "WEBSOCKET_AUTH_SCHEMA", "OKX private WebSocket login acknowledgement was not an object")
        self.accept_message(login_message)
        self.pending_messages.append(login_message)
        if login_message.get("event") != "login" or str(login_message.get("code", "0")) != "0":
            raise AdapterError("okx-demo", "WEBSOCKET_AUTH_FAILED", str(login_message.get("msg") or login_message.get("code") or "OKX private WebSocket login failed"))
        if channels:
            arguments = [dict(channel) if isinstance(channel, dict) else {"channel": str(channel)} for channel in channels]
            await self.socket.send(json.dumps({"op": "subscribe", "args": arguments}, separators=(",", ":")))
        self.connected = True

    async def receive(self) -> dict[str, Any]:
        if self.socket is None:
            raise AdapterError("okx-demo", "WEBSOCKET_NOT_CONNECTED", "connect before receive")
        if self.pending_messages:
            return self.pending_messages.pop(0)
        raw = await self.socket.recv()
        message = json.loads(raw)
        if isinstance(message, dict):
            self.accept_message(message)
            return message
        raise AdapterError("okx-demo", "SCHEMA", "OKX private WebSocket returned a non-object message")

    async def close(self) -> None:
        self.connected = False
        self.pending_messages.clear()
        if self.socket is not None:
            await self.socket.close()
            self.socket = None

    async def run(self, on_message: Callable[[dict[str, Any]], Any], stop: asyncio.Event, channels: list[Any] | None = None, *, reconnect_delay: float = 2.0, on_error: Callable[[BaseException], Any] | None = None) -> None:
        channels = channels or ["account", "positions", "orders", "fills"]
        while not stop.is_set():
            try:
                await self.connect(channels)
                while not stop.is_set():
                    result = on_message(await self.receive())
                    if inspect.isawaitable(result):
                        await result
            except (OSError, asyncio.CancelledError, AdapterError, json.JSONDecodeError) as error:
                self.connected = False
                if on_error is not None and not stop.is_set() and not isinstance(error, asyncio.CancelledError):
                    result = on_error(error)
                    if inspect.isawaitable(result):
                        await result
                if stop.is_set():
                    break
                await asyncio.sleep(reconnect_delay)
            finally:
                await self.close()


__all__ = ["OKXDemoWebSocket"]
