from __future__ import annotations

from collections.abc import Iterable


CONFIDENCE_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NOT_APPLICABLE": 3}


def _rank(value: str) -> int:
    return CONFIDENCE_ORDER.get(str(value or "").upper(), 1)


def combine_confidences(values: Iterable[str]) -> str:
    normalized = [str(value or "").upper() for value in values if value not in (None, "")]
    if not normalized:
        return "LOW"
    minimum = min(_rank(value) for value in normalized)
    return {3: "HIGH", 2: "MEDIUM", 1: "LOW"}[minimum]


def ordering_confidence(chain_status: str) -> str:
    status = str(chain_status or "")
    if status == "AMBIGUOUS":
        return "LOW"
    if status in {"UNIQUE_CUMQTY_CHAIN", "NOT_IN_MULTI_TRADE_GROUP"}:
        return "HIGH"
    return "MEDIUM"


def action_confidence(normalization_status: str, order_join_status: str, action: str) -> str:
    if str(normalization_status or "") in {"ERROR", "UNRESOLVED", "BLOCKED"}:
        return "LOW"
    if str(order_join_status or "") in {"UNMATCHED", "NO_ORDER_ID"}:
        return "MEDIUM"
    if not action or action == "UNRESOLVED":
        return "LOW"
    return "HIGH"


def accounting_confidence(accounting_status: str, normalization_status: str = "") -> str:
    status = str(accounting_status or normalization_status or "")
    if "BLOCKED" in status or status in {"ERROR", "UNRESOLVED"}:
        return "LOW"
    if "WARNING" in status or status in {"READY_WITH_WARNINGS", "ACCOUNTING_ELIGIBLE_WITH_WARNING"}:
        return "MEDIUM"
    if status in {"PASS", "ACCOUNTING_ELIGIBLE", "OK", "OK_WITHOUT_ORDER_ID", "OK_WITH_UNMATCHED_ORDER"}:
        return "HIGH"
    return "MEDIUM"


def price_confidence(price_status: str) -> str:
    status = str(price_status or "")
    if "UNRESOLVED" in status or "MISSING" in status or "BLOCKED" in status:
        return "LOW"
    if "RECOVERED" in status or "COARSENED" in status or "RAW_LASTPX" not in status and "EXACT" not in status:
        return "MEDIUM"
    return "HIGH"


def wallet_confidence(*, terminal_status: str = "PASS", direct_link: bool = False) -> str:
    if direct_link:
        return "HIGH" if terminal_status == "PASS" else "MEDIUM"
    if terminal_status in {"PASS", "READY_WITH_WARNINGS"}:
        return "AGGREGATE_ONLY"
    return "LOW"


def overall_confidence(
    ordering: str,
    action: str,
    accounting: str,
    price: str,
    wallet: str,
) -> str:
    # Wallet aggregate-only evidence is deliberately not collapsed into HIGH.
    wallet_value = "MEDIUM" if wallet == "AGGREGATE_ONLY" else wallet
    return combine_confidences((ordering, action, accounting, price, wallet_value))


__all__ = [
    "CONFIDENCE_ORDER",
    "accounting_confidence",
    "action_confidence",
    "combine_confidences",
    "ordering_confidence",
    "overall_confidence",
    "price_confidence",
    "wallet_confidence",
]
