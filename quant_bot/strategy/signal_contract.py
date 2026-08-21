from __future__ import annotations

from typing import Iterable


OPEN_ACTIONS = frozenset({"OPEN_LONG", "OPEN_SHORT"})
CLOSE_ACTIONS = frozenset({"CLOSE_LONG", "CLOSE_SHORT"})
ADD_ACTIONS = frozenset({"ADD_LONG", "ADD_SHORT"})
REDUCE_ACTIONS = frozenset({"REDUCE_LONG", "REDUCE_SHORT"})
FLIP_ACTIONS = frozenset({"FLIP_LONG_TO_SHORT", "FLIP_SHORT_TO_LONG"})
HOLD_ACTIONS = frozenset({"HOLD_LONG", "HOLD_SHORT", "NO_TRADE"})


def action_family(action: str) -> str:
    if action in OPEN_ACTIONS:
        return "OPEN"
    if action in CLOSE_ACTIONS:
        return "CLOSE"
    if action in ADD_ACTIONS:
        return "ADD"
    if action in REDUCE_ACTIONS:
        return "REDUCE"
    if action in FLIP_ACTIONS:
        return "FLIP"
    if action in HOLD_ACTIONS:
        return "HOLD"
    return "OTHER"


def is_action_in(action: str, actions: Iterable[str]) -> bool:
    return action in set(actions)
