from __future__ import annotations

import json

from quant_bot.supervisor import supervise_venue


def test_supervisor_restarts_only_recoverable_runtime_stop(tmp_path) -> None:
    results = iter([
        {"status": "STOPPED", "stop_reason": "WATCHDOG_TIMEOUT", "last_error": None},
        {"status": "STOPPED", "stop_reason": None, "last_error": None},
    ])
    calls: list[dict[str, object]] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return next(results)

    final = supervise_venue(
        venue="okx-demo",
        enable_orders=True,
        confirm_testnet=True,
        max_restarts=2,
        state_path=tmp_path / "supervisor.json",
        run_fn=fake_run,
        sleep_fn=lambda _seconds: None,
    )

    assert len(calls) == 2
    assert calls[0]["external_stop_event"] is calls[1]["external_stop_event"]
    assert final["status"] == "STOPPED"
    assert final["supervisor_restart_count"] == 1
    state = json.loads((tmp_path / "supervisor.json").read_text(encoding="utf-8"))
    assert state["restart_count"] == 1


def test_supervisor_does_not_restart_order_rejects(tmp_path) -> None:
    calls = 0

    def fake_run(**_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "STOPPED", "stop_reason": "CONSECUTIVE_ORDER_REJECTS"}

    final = supervise_venue(
        venue="binance-futures-testnet",
        enable_orders=True,
        confirm_testnet=True,
        max_restarts=3,
        state_path=tmp_path / "supervisor.json",
        run_fn=fake_run,
        sleep_fn=lambda _seconds: (_ for _ in ()).throw(AssertionError("must not back off")),
    )

    assert calls == 1
    assert final["status"] == "BLOCKED"
    assert final["supervisor_restart_count"] == 0
