from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from bitmex_replay.io_utils import parse_datetime

from .confidence import overall_confidence, wallet_confidence


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date(value: Any) -> date | None:
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def _base_decision(row: dict[str, Any], *, decision_id: str, decision_type: str) -> dict[str, Any]:
    return {
        "decision_episode_id": decision_id,
        "decision_type": decision_type,
        "decision_time": row.get("first_event_time", row.get("event_time", "")),
        "decision_date": (_date(row.get("first_event_time", row.get("event_time", ""))) or date.min).isoformat(),
        "symbol": row.get("symbol", ""),
        "is_btc_first_scope": row.get("symbol") == "XBTUSD",
        "source_order_episode_id": row.get("order_episode_id", ""),
        "action": row.get("action", "NO_TRADE"),
        "position_before": _int(row.get("position_before")),
        "target_position": _int(row.get("position_after", row.get("target_position"))),
        "position_delta": _int(row.get("signed_contract_qty", row.get("position_delta"))),
        "execution_count": _int(row.get("execution_count")),
        "synthetic_negative_sample": decision_type != "ORDER",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "ordering_confidence": row.get("ordering_confidence", "HIGH"),
        "action_confidence": row.get("action_confidence", "HIGH"),
        "accounting_confidence": row.get("accounting_confidence", "MEDIUM"),
        "price_confidence": row.get("price_confidence", "NOT_APPLICABLE"),
        "wallet_confidence": row.get("wallet_confidence", wallet_confidence()),
        "overall_confidence": row.get("overall_confidence", "MEDIUM"),
    }


def _synthetic_row(day: date, position: int, last_event_time: str) -> dict[str, Any]:
    action = "HOLD_LONG" if position > 0 else ("HOLD_SHORT" if position < 0 else "NO_TRADE")
    return {
        "decision_episode_id": f"XBTUSD-DAY-{day.isoformat()}",
        "decision_type": "SYNTHETIC_DAY",
        "decision_time": f"{day.isoformat()}T23:59:59.999999Z",
        "decision_date": day.isoformat(),
        "symbol": "XBTUSD",
        "is_btc_first_scope": True,
        "source_order_episode_id": "",
        "action": action,
        "position_before": position,
        "target_position": position,
        "position_delta": 0,
        "execution_count": 0,
        "synthetic_negative_sample": True,
        "last_observed_trade_time": last_event_time,
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "ordering_confidence": "HIGH",
        "action_confidence": "HIGH",
        "accounting_confidence": "HIGH",
        "price_confidence": "NOT_APPLICABLE",
        "wallet_confidence": wallet_confidence(),
        "overall_confidence": overall_confidence("HIGH", "HIGH", "HIGH", "NOT_APPLICABLE", wallet_confidence()),
    }


def build_decision_episodes(
    order_episodes: Iterable[dict[str, Any]],
    position_events: Iterable[dict[str, Any]],
    *,
    btc_symbol: str = "XBTUSD",
) -> list[dict[str, Any]]:
    """Create order decisions plus daily HOLD/NO_TRADE observations for BTC."""

    order_rows = list(order_episodes)
    decisions = [
        _base_decision(row, decision_id=f"DE-{row['order_episode_id']}", decision_type="ORDER")
        for row in order_rows
    ]
    btc_events = [
        row for row in position_events
        if row.get("symbol") == btc_symbol and row.get("execType") in {"Trade", "Settlement"}
    ]
    btc_events.sort(key=lambda row: parse_datetime(row.get("event_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"))
    if btc_events:
        first_day = _date(btc_events[0].get("event_time"))
        last_day = _date(btc_events[-1].get("event_time"))
        trade_days = {_date(row.get("event_time")) for row in btc_events}
        position = 0
        by_day: dict[date, int] = {}
        last_seen = ""
        for row in btc_events:
            day = _date(row.get("event_time"))
            if day is None:
                continue
            if day != _date(last_seen):
                by_day.setdefault(day, position)
            position = _int(row.get("position_after"))
            last_seen = str(row.get("event_time", ""))
            by_day[day] = position
        if first_day is not None and last_day is not None:
            day = first_day
            previous_position = 0
            for row in btc_events:
                event_day = _date(row.get("event_time"))
                if event_day is not None and event_day != day:
                    previous_position = _int(row.get("position_before"), previous_position)
            while day <= last_day:
                if day not in trade_days:
                    position_at_start = 0
                    for event_day in sorted(by_day):
                        if event_day < day:
                            position_at_start = by_day[event_day]
                    decisions.append(_synthetic_row(day, position_at_start, last_seen))
                day += timedelta(days=1)
    decisions.sort(key=lambda row: (parse_datetime(row.get("decision_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"), row.get("decision_episode_id", "")))
    return decisions


__all__ = ["build_decision_episodes"]
