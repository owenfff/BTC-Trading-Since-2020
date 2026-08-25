from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Sequence

from .exchanges.http import AdapterError
from .venue_runtime import DEFAULT_ARTIFACT, run_foreground_venue


SUPPORTED_MULTI_VENUES = ("okx-demo", "binance-spot-testnet")


def _blocked_result(venue: str, error: BaseException) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "venue": venue,
        "error_code": getattr(error, "code", "RUNTIME_FAILED"),
        "message": str(error),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
    }


def _normalize_venues(venues: Sequence[str] | str) -> tuple[str, ...]:
    values = [venues] if isinstance(venues, str) else list(venues)
    normalized: list[str] = []
    for value in values:
        for item in str(value).split(","):
            venue = item.strip().lower()
            if not venue:
                continue
            if venue not in SUPPORTED_MULTI_VENUES:
                raise AdapterError(venue, "UNSUPPORTED_VENUE", f"run-all supports only: {', '.join(SUPPORTED_MULTI_VENUES)}")
            if venue not in normalized:
                normalized.append(venue)
    if not normalized:
        raise AdapterError("run-all", "NO_VENUES", "at least one venue is required")
    return tuple(normalized)


def run_foreground_multivenue(
    *,
    venues: Sequence[str] | str = SUPPORTED_MULTI_VENUES,
    artifact_path: Path = DEFAULT_ARTIFACT,
    enable_orders: bool = False,
    confirm_testnet: bool = False,
    symbols: str = "auto",
    once: bool = False,
    poll_seconds: int = 60,
    allow_spot_approximation: bool = False,
) -> dict[str, Any]:
    """Run the exchange-neutral Strategy Core against several non-production venues.

    Each venue has its own adapter, reconciliation state, report and runtime
    state. A missing credential or venue-specific failure is returned as a
    sanitized BLOCKED result for that venue. A shared stop event makes Ctrl+C
    and any fail-closed runtime stop all active workers.
    """

    selected = _normalize_venues(venues)
    stop_event = threading.Event()
    results: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()

    def worker(venue: str) -> None:
        try:
            result = run_foreground_venue(
                venue=venue,
                artifact_path=artifact_path,
                enable_orders=enable_orders,
                confirm_testnet=confirm_testnet,
                symbols=symbols,
                once=once,
                poll_seconds=poll_seconds,
                allow_spot_approximation=allow_spot_approximation,
                external_stop_event=stop_event,
            )
        except BaseException as error:  # noqa: BLE001 - convert each venue failure to a safe result
            result = _blocked_result(venue, error)
        with lock:
            results[venue] = result

    threads = [threading.Thread(target=worker, args=(venue,), name=f"{venue}-supervisor", daemon=True) for venue in selected]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=max(2, poll_seconds + 2))

    blocked = [venue for venue in selected if results.get(venue, {}).get("status") == "BLOCKED"]
    active = [venue for venue in selected if venue in results and venue not in blocked]
    if not results:
        status = "BLOCKED"
    elif blocked and not active:
        status = "BLOCKED"
    elif enable_orders and any(results.get(venue, {}).get("status") in {"STOPPED", "RUNNING"} for venue in active):
        status = "STOPPED"
    else:
        status = "STOPPED_READ_ONLY"
    return {
        "status": status,
        "venues": results,
        "selected_venues": list(selected),
        "blocked_venues": blocked,
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "order_submission_enabled": bool(enable_orders and confirm_testnet),
    }


__all__ = ["SUPPORTED_MULTI_VENUES", "run_foreground_multivenue"]
