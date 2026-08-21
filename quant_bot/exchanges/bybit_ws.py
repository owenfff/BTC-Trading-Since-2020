from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from .bybit_http import BybitCredentials, DEMO_WS_URL, assert_demo_ws_url, bybit_websocket_signature
from .http import AdapterError


class BybitDemoWebSocket:
    """Private Demo stream for wallet, order, execution and position events."""

    def __init__(self, credentials: BybitCredentials, *, url: str = DEMO_WS_URL, connect_factory: Any | None = None, clock_ms: Any = lambda: int(time.time() * 1000)) -> None:
        assert_demo_ws_url(url)
        self.credentials = credentials
        self.url = url
        self.connect_factory = connect_factory
        self.clock_ms = clock_ms
        self.socket: Any = None
        self.connected = False
        self.seen_messages: set[str] = set()
        self.latest: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def auth_message(self) -> dict[str, Any]:
        expires = int(self.clock_ms()) + 10_000
        sign = bybit_websocket_signature(self.credentials.api_secret, expires)
        return {"op": "auth", "args": [self.credentials.api_key, expires, sign]}

    @staticmethod
    def message_id(message: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(message, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def accept_message(self, message: dict[str, Any]) -> bool:
        identifier = self.message_id(message)
        if identifier in self.seen_messages:
            return False
        self.seen_messages.add(identifier)
        topic = str(message.get("topic") or "")
        data = message.get("data")
        if topic and isinstance(data, list):
            self.latest[topic] = [dict(item) for item in data if isinstance(item, dict)]
        return True

    async def connect(self, topics: list[str]) -> None:
        try:
            import websockets
        except ImportError as error:
            raise AdapterError("bybit-demo", "WEBSOCKET_DEPENDENCY_MISSING", "install the pinned websockets runtime dependency") from error
        factory = self.connect_factory or websockets.connect
        self.socket = await factory(self.url, ping_interval=20, ping_timeout=20, close_timeout=5)
        await self.socket.send(json.dumps(self.auth_message(), separators=(",", ":")))
        if topics:
            await self.socket.send(json.dumps({"op": "subscribe", "args": topics}, separators=(",", ":")))
        self.connected = True

    async def receive(self) -> dict[str, Any]:
        if self.socket is None:
            raise AdapterError("bybit-demo", "WEBSOCKET_NOT_CONNECTED", "connect before receive")
        raw = await self.socket.recv()
        message = json.loads(raw)
        if isinstance(message, dict):
            self.accept_message(message)
        return message

    async def close(self) -> None:
        self.connected = False
        if self.socket is not None:
            await self.socket.close()
            self.socket = None

    async def run(self, on_message: Callable[[dict[str, Any]], Awaitable[None]], stop: asyncio.Event, topics: list[str], *, reconnect_delay: float = 2.0) -> None:
        while not stop.is_set():
            heartbeat_task: asyncio.Task[Any] | None = None
            try:
                await self.connect(topics)
                async def heartbeat() -> None:
                    while not stop.is_set() and self.socket is not None:
                        await asyncio.sleep(20)
                        if self.socket is not None:
                            await self.socket.send(json.dumps({"op": "ping"}, separators=(",", ":")))
                heartbeat_task = asyncio.create_task(heartbeat())
                while not stop.is_set():
                    await on_message(await self.receive())
            except (OSError, asyncio.CancelledError, AdapterError):
                self.connected = False
                if stop.is_set():
                    break
                await asyncio.sleep(reconnect_delay)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                await self.close()


__all__ = ["BybitDemoWebSocket"]
