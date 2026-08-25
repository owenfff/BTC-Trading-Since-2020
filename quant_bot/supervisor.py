from __future__ import annotations

import json
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .venue_runtime import DEFAULT_ARTIFACT, run_foreground_venue


ROOT = Path(__file__).resolve().parents[1]
RECOVERABLE_STOP_REASONS = frozenset({"PRIVATE_WEBSOCKET_DISCONNECTED", "WATCHDOG_TIMEOUT"})
DEFAULT_MAX_RESTARTS = 3
DEFAULT_BACKOFF_SECONDS = (5, 15, 30)


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _state_payload(venue: str, *, status: str, restart_count: int, last_result: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "venue": venue,
        "restart_count": restart_count,
        "last_runtime_status": last_result.get("status"),
        "last_stop_reason": last_result.get("stop_reason"),
        "last_error": error or last_result.get("last_error"),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
    }


def supervise_venue(
    *,
    venue: str,
    artifact_path: Path = DEFAULT_ARTIFACT,
    enable_orders: bool = False,
    confirm_testnet: bool = False,
    symbols: str = "auto",
    poll_seconds: int = 60,
    allow_spot_approximation: bool = False,
    max_restarts: int = DEFAULT_MAX_RESTARTS,
    backoff_seconds: tuple[int, ...] = DEFAULT_BACKOFF_SECONDS,
    state_path: Path | None = None,
    run_fn: Callable[..., dict[str, Any]] = run_foreground_venue,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run one venue and restart only for bounded, explicitly recoverable stops."""

    if max_restarts < 0:
        raise ValueError("max_restarts must be non-negative")
    if not backoff_seconds:
        raise ValueError("backoff_seconds must not be empty")
    output_path = state_path or ROOT / "quant" / "outputs" / f"{venue.replace('-', '_')}_supervisor_state.json"
    stop_event = threading.Event()
    restart_count = 0
    last: dict[str, Any] = {}
    old_handlers: dict[int, Any] = {}

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    # Signal handlers are only installed by the foreground CLI, never by the
    # library tests or background threads. Restore them before returning.
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            old_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        except (ValueError, OSError):
            pass

    try:
        while not stop_event.is_set():
            try:
                last = run_fn(
                    venue=venue,
                    artifact_path=artifact_path,
                    enable_orders=enable_orders,
                    confirm_testnet=confirm_testnet,
                    symbols=symbols,
                    once=False,
                    poll_seconds=poll_seconds,
                    allow_spot_approximation=allow_spot_approximation,
                    external_stop_event=stop_event,
                )
            except Exception as error:  # noqa: BLE001 - persist a safe supervisor boundary
                last = {"status": "BLOCKED", "stop_reason": "RUNNER_EXCEPTION", "last_error": f"{type(error).__name__}: {str(error)[:200]}"}
                _write_state(output_path, _state_payload(venue, status="BLOCKED", restart_count=restart_count, last_result=last, error=last["last_error"]))
                return last

            if stop_event.is_set():
                break
            reason = str(last.get("stop_reason") or "")
            if reason not in RECOVERABLE_STOP_REASONS or restart_count >= max_restarts:
                if reason:
                    status = "BLOCKED"
                else:
                    status = str(last.get("status") or ("STOPPED_READ_ONLY" if not enable_orders else "STOPPED"))
                final = {**last, "status": status, "supervisor_restart_count": restart_count}
                _write_state(output_path, _state_payload(venue, status=status, restart_count=restart_count, last_result=final))
                return final

            restart_count += 1
            _write_state(output_path, _state_payload(venue, status="BACKOFF", restart_count=restart_count, last_result=last))
            sleep_fn(backoff_seconds[min(restart_count - 1, len(backoff_seconds) - 1)])

        final = {**last, "status": "STOPPED_BY_OPERATOR", "supervisor_restart_count": restart_count}
        _write_state(output_path, _state_payload(venue, status="STOPPED_BY_OPERATOR", restart_count=restart_count, last_result=final))
        return final
    finally:
        for signum, handler in old_handlers.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass


__all__ = ["DEFAULT_MAX_RESTARTS", "RECOVERABLE_STOP_REASONS", "supervise_venue"]
