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
