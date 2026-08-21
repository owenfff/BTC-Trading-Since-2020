from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_bot.paper import PaperTradingEngine
from quant_bot.strategy.base import StrategySignal
from quant_bot.strategy.distilled_rules import DistilledRuleStrategy
from quant_bot.strategy.feature_contract import strategy_input_from_row


@dataclass
class JsonStateStore:
    path: Path

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))


@dataclass
class SignalDeduplicator:
    seen: set[str] = field(default_factory=set)

    def accept(self, signal: StrategySignal) -> bool:
        key = f"{signal.strategy_version}|{signal.signal_timestamp}|{signal.target_exposure}|{signal.action}"
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


def run_local(mode: str, dataset_path: Path, state_path: Path, limit: int = 100) -> dict[str, Any]:
    if mode not in {"shadow", "paper"}:
        raise ValueError("mode must be shadow or paper")
    with dataset_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))[:limit]
    strategy = DistilledRuleStrategy()
    deduplicator = SignalDeduplicator()
    paper = PaperTradingEngine() if mode == "paper" else None
    signal_count = duplicate_count = 0
    signals: list[dict[str, Any]] = []
    for row in rows:
        signal = strategy.predict(strategy_input_from_row(row))
        if not deduplicator.accept(signal):
            duplicate_count += 1
            continue
        signal_count += 1
        signals.append(signal.as_dict())
        if paper is not None:
            # Local smoke only: no exchange price/feed is queried.
            paper.apply_signal(signal, reference_price=Decimal("1"))
    state = {"mode": mode, "status": "SHADOW_SMOKE_PASS" if mode == "shadow" else "PAPER_SMOKE_PASS", "signal_count": signal_count, "duplicate_count": duplicate_count, "signals": signals[-5:]}
    if paper is not None:
        state["paper"] = paper.snapshot()
    JsonStateStore(state_path).save(state)
    return state
