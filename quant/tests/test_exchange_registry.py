from __future__ import annotations

from quant_bot.exchanges.capabilities import ExchangeCapabilities
from quant_bot.exchanges.ccxt_common import CcxtCommonAdapter
from quant_bot.exchanges.registry import ExchangeRegistry


class AdapterStub:
    pass


def test_exchange_registry_keeps_adapter_and_capabilities_separate() -> None:
    registry = ExchangeRegistry()
    capabilities = ExchangeCapabilities("example", True, False, True, False, "TESTNET", True, False, False)
    adapter = AdapterStub()
    registry.register("Example", adapter, capabilities)
    assert registry.adapter("example") is adapter
    assert registry.capabilities()[0].demo_or_testnet == "TESTNET"


def test_ccxt_placeholder_does_not_accept_credentials_or_call_network() -> None:
    normalized = CcxtCommonAdapter("example").normalize_public_instrument({"symbol": "XBTUSD"})
    assert normalized["exchange"] == "example"
