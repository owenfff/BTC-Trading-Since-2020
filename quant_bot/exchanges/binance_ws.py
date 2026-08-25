from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from typing import Any, Callable
from urllib.parse import quote

from .binance_http import BINANCE_SPOT_TESTNET_WS_URL, BinanceSpotTestnetTransport, assert_binance_spot_testnet_ws_url
from .http import AdapterError


class BinanceSpotTestnetWebSocket:
    """Spot Testnet user-data stream backed by a REST listen key."""

    def __init__(self, transport: BinanceSpotTestnetTransport, *, url: str = BINANCE_SPOT_TESTNET_WS_URL, connect_factory: Any | None = None) -> None:
        assert_binance_spot_testnet_ws_url(url)
        self.transport = transport
        self.url = url.rstrip("/")
        self.connect_factory = connect_factory
        self.socket: Any = None
        self.connected = False
        self.listen_key: str | None = None
        self.seen_messages: set[str] = set()

    @staticmethod
    def message_id(message: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def accept_message(self, message: dict[str, Any]) -> bool:
        identifier = self.message_id(message)
        if identifier in self.seen_messages:
            return False
        self.seen_messages.add(identifier)
        return True

    def _create_listen_key(self) -> str:
        response = self.transport.request_api_key("POST", "/api/v3/userDataStream")
        if not isinstance(response, dict) or not response.get("listenKey"):
            raise AdapterError("binance-spot-testnet", "SCHEMA", "Binance user-data stream response missing listenKey")
        return str(response["listenKey"])

    def _keepalive(self) -> None:
        if self.listen_key:
            self.transport.request_api_key("PUT", f"/api/v3/userDataStream?listenKey={quote(self.listen_key, safe='')}" )

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as error:
            raise AdapterError("binance-spot-testnet", "WEBSOCKET_DEPENDENCY_MISSING", "install the pinned websockets runtime dependency") from error
        self.listen_key = self._create_listen_key()
        factory = self.connect_factory or websockets.connect
        self.socket = await factory(f"{self.url}/{quote(self.listen_key, safe='')}", ping_interval=20, ping_timeout=20, close_timeout=5)
        self.connected = True

    async def receive(self) -> dict[str, Any]:
        if self.socket is None:
            raise AdapterError("binance-spot-testnet", "WEBSOCKET_NOT_CONNECTED", "connect before receive")
        raw = await self.socket.recv()
        message = json.loads(raw)
        if isinstance(message, dict):
            self.accept_message(message)
            return message
        raise AdapterError("binance-spot-testnet", "SCHEMA", "Binance user-data stream returned a non-object message")

    async def close(self) -> None:
        self.connected = False
        if self.socket is not None:
            await self.socket.close()
            self.socket = None
        self.listen_key = None

    async def run(self, on_message: Callable[[dict[str, Any]], Any], stop: asyncio.Event, *, reconnect_delay: float = 2.0, on_error: Callable[[BaseException], Any] | None = None) -> None:
        while not stop.is_set():
            keepalive_task: asyncio.Task[Any] | None = None
            try:
                await self.connect()
                async def keepalive() -> None:
                    while not stop.is_set():
                        await asyncio.sleep(25 * 60)
                        if not stop.is_set():
                            self._keepalive()
                keepalive_task = asyncio.create_task(keepalive())
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
                if keepalive_task is not None:
                    keepalive_task.cancel()
                await self.close()


__all__ = ["BinanceSpotTestnetWebSocket"]
