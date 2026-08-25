from __future__ import annotations

import os

import frontend.server as dashboard


class FakeProcess:
    pid = 4321

    def __init__(self) -> None:
        self.return_code: int | None = None
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.return_code

    def send_signal(self, value: int) -> None:
        self.signals.append(value)
        self.return_code = 0

    def terminate(self) -> None:
        self.return_code = 0


def _reset(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", False)
    monkeypatch.setattr(dashboard, "CONTROL_HOST", "127.0.0.1")
    monkeypatch.setattr(dashboard, "CONTROL_PROCESS", None)
    monkeypatch.setattr(dashboard, "CONTROL_META", {})
    monkeypatch.setattr(dashboard, "CONTROL_CREDENTIALS_PATH", None)


def test_dashboard_control_is_disabled_by_default(monkeypatch) -> None:
    _reset(monkeypatch)
    status, payload = dashboard.start_control({"venue": "okx-demo", "mode": "readonly"})
    assert status == 403
    assert payload["error"] == "LOCAL_CONTROL_DISABLED"


def test_dashboard_control_rejects_credentials(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    status, payload = dashboard.start_control({"venue": "okx-demo", "mode": "readonly", "api_key": "must-not-enter"})
    assert status == 400
    assert payload["error"] == "CREDENTIALS_MUST_NOT_BE_SENT_TO_DASHBOARD"


def test_dashboard_control_is_loopback_only(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    monkeypatch.setattr(dashboard, "CONTROL_HOST", "0.0.0.0")
    status, payload = dashboard.start_control({"venue": "okx-demo", "mode": "readonly"})
    assert status == 403
    assert payload["error"] == "LOCAL_CONTROL_DISABLED"


def test_dashboard_control_starts_one_launcher_without_secret_payload(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    fake = FakeProcess()
    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake

    monkeypatch.setattr(dashboard.subprocess, "Popen", fake_popen)
    status, payload = dashboard.start_control({"venue": "binance-futures-testnet", "mode": "readonly"})
    assert status == 202
    assert payload["status"] == "STARTING_LOCAL"
    assert payload["control"]["venue"] == "binance-futures-testnet"
    args = captured["args"]
    command_text = " ".join(str(item) for item in args)
    if os.name == "nt":
        assert "start-binance-futures-testnet.ps1" in command_text
    else:
        assert "quant_bot" in command_text
    assert "secret" not in command_text.lower()
    assert "api_key" not in command_text.lower()
    stop_status, stop_payload = dashboard.stop_control()
    assert stop_status == 202
    assert stop_payload["status"] == "STOP_REQUESTED"


def test_dashboard_control_requires_explicit_testnet_confirmation(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    status, payload = dashboard.start_control({"venue": "okx-demo", "mode": "testnet"})
    assert status == 400
    assert payload["error"] == "TESTNET_CONFIRMATION_REQUIRED"


def test_loopback_credentials_are_saved_without_returning_values(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    monkeypatch.setattr(dashboard, "_file_credentials_supported", lambda: True)
    credential_path = tmp_path / "quant-bot" / "credentials.env"
    monkeypatch.setattr(dashboard, "CONTROL_CREDENTIALS_PATH", credential_path)
    secret = "secret-value-should-not-be-in-response"

    status, payload = dashboard.configure_credentials(
        {
            "venue": "okx-demo",
            "api_key": "demo-key",
            "api_secret": secret,
            "passphrase": "demo-passphrase",
        }
    )

    assert status == 200
    assert payload["status"] == "CREDENTIALS_SAVED"
    assert payload["credential_status"] == "CONFIGURED"
    assert secret not in str(payload)
    assert credential_path.exists()
    assert dashboard._credential_status("okx-demo") == "CONFIGURED"
    assert dashboard._load_credentials_for_venue("okx-demo")["OKX_DEMO_API_SECRET"] == secret
    assert "OKX_DEMO_API_KEY=demo-key" in credential_path.read_text(encoding="utf-8")


def test_loopback_credentials_reject_unicode_and_wrong_venue(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    monkeypatch.setattr(dashboard, "_file_credentials_supported", lambda: True)
    monkeypatch.setattr(dashboard, "CONTROL_CREDENTIALS_PATH", tmp_path / "credentials.env")
    status, payload = dashboard.configure_credentials(
        {"venue": "okx-demo", "api_key": "key", "api_secret": "secret", "passphrase": "’"}
    )
    assert status == 400
    assert payload["error"] == "passphrase_MUST_BE_ASCII"

    status, payload = dashboard.configure_credentials(
        {"venue": "unsupported", "api_key": "key", "api_secret": "secret"}
    )
    assert status == 400
    assert payload["error"] == "UNSUPPORTED_CREDENTIAL_VENUE"


def test_testnet_control_requires_local_credentials(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setattr(dashboard, "CONTROL_ENABLED", True)
    monkeypatch.setattr(dashboard, "_file_credentials_supported", lambda: True)
    monkeypatch.setattr(dashboard, "CONTROL_CREDENTIALS_PATH", tmp_path / "credentials.env")
    status, payload = dashboard.start_control({"venue": "okx-demo", "mode": "testnet", "confirm_testnet": True})
    assert status == 400
    assert payload["error"] == "LOCAL_CREDENTIALS_REQUIRED"


def test_replay_payload_keeps_endpoints_when_downsampling(monkeypatch) -> None:
    dashboard.REPLAY_CACHE.clear()
    monkeypatch.setitem(
        dashboard.REPLAY_CACHE,
        "XBTUSD",
        {
            "symbol": "XBTUSD",
            "bars": [{"ts": index, "close": float(index)} for index in range(10)],
            "orders": [],
            "pnl": [],
            "available": True,
            "start_ts": 0,
            "end_ts": 9,
            "pnl_unit": "XBT (scale 8) analytical realised PnL",
            "source": "test",
        },
    )
    payload = dashboard.replay_payload({"symbol": ["XBTUSD"], "limit": ["4"]})
    assert payload["status"] == "READY"
    assert len(payload["bars"]) == 4
    assert payload["bars"][0]["ts"] == 0
    assert payload["bars"][-1]["ts"] == 9


def test_replay_payload_is_waiting_for_missing_local_outputs(monkeypatch) -> None:
    dashboard.REPLAY_CACHE.clear()
    monkeypatch.setattr(dashboard, "_read_replay_dataset", lambda symbol: {
        "symbol": symbol,
        "bars": [],
        "orders": [],
        "pnl": [],
        "available": False,
        "start_ts": None,
        "end_ts": None,
        "pnl_unit": "raw analytical realised PnL (scale unresolved)",
        "source": "test",
    })
    payload = dashboard.replay_payload({"symbol": ["XBTUSD"]})
    assert payload["status"] == "WAITING"
    assert payload["available"] is False
    assert payload["bars"] == []
