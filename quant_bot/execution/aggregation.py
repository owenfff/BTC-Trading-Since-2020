from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Iterable

from .target_planner import TargetOrderPlan


def _weight(plan: TargetOrderPlan) -> Decimal:
    if plan.strategy_confidence is None or plan.strategy_confidence <= 0:
        return Decimal("1")
    return plan.strategy_confidence


def _merged_action(current: Decimal, target: Decimal) -> str:
    if current == 0:
        return "NO_TRADE" if target == 0 else "OPEN_LONG" if target > 0 else "OPEN_SHORT"
    if current > 0:
        if target > current:
            return "ADD_LONG"
        if target == 0:
            return "CLOSE_LONG"
        if target < current:
            return "REDUCE_LONG"
        return "HOLD_LONG"
    if target < current:
        return "ADD_SHORT"
    if target == 0:
        return "CLOSE_SHORT"
    if target > current:
        return "REDUCE_SHORT"
    return "HOLD_SHORT"


def merge_duplicate_target_plans(plans: Iterable[TargetOrderPlan]) -> list[TargetOrderPlan]:
    """Collapse one decision into one net plan per canonical venue symbol.

    Historical symbols can intentionally crosswalk to one live contract. The
    weighted target is the confidence-weighted mean, while all source signals
    remain attached for auditability.
    """

    groups: dict[str, list[TargetOrderPlan]] = {}
    for plan in plans:
        groups.setdefault(plan.symbol, []).append(plan)
    merged: list[TargetOrderPlan] = []
    for symbol, group in groups.items():
        if len(group) == 1:
            plan = group[0]
            if plan.strategy_source_symbols:
                merged.append(plan)
            else:
                merged.append(replace(plan, strategy_source_symbols=(symbol,)))
            continue
        weights = [_weight(plan) for plan in group]
        total_weight = sum(weights, Decimal("0"))
        target = sum((plan.target_exposure * weight for plan, weight in zip(group, weights)), Decimal("0")) / total_weight
        confidence = sum(((_weight(plan) * (plan.strategy_confidence or Decimal("1"))) for plan in group), Decimal("0")) / total_weight
        sources: list[str] = []
        source_signals: list[dict[str, object]] = []
        basis: list[str] = ["MERGED_DUPLICATE_SYMBOLS"]
        for plan in group:
            plan_sources = plan.strategy_source_symbols or (symbol,)
            for source in plan_sources:
                if source not in sources:
                    sources.append(source)
            source_signals.extend(plan.strategy_source_signals or ({
                "historical_symbol": plan_sources[0],
                "strategy_action": plan.strategy_action,
                "target_exposure": str(plan.target_exposure),
                "confidence": str(plan.strategy_confidence) if plan.strategy_confidence is not None else None,
                "strategy_basis": list(plan.strategy_basis),
            },))
            for item in plan.strategy_basis:
                if item not in basis:
                    basis.append(item)
        first = group[0]
        merged.append(replace(
            first,
            target_exposure=target,
            strategy_action=_merged_action(first.current_contracts, target),
            strategy_confidence=confidence,
            strategy_basis=tuple(basis),
            strategy_source_symbols=tuple(sources),
            strategy_source_signals=tuple(source_signals),
        ))
    return merged


__all__ = ["merge_duplicate_target_plans"]
