from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping


PERSISTED_BLOCK_REASONS = frozenset({
    "DAILY_LOSS_LIMIT",
    "PEAK_DRAWDOWN_LIMIT",
    "CONSECUTIVE_ORDER_REJECTS",
})


def _utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - state files must never crash recovery
        return default


@dataclass
class RuntimeRiskState:
    """Runtime risk ledger used before every order submission.

    It deliberately only stops new orders and cancels bot-owned orders.  It
    never creates a liquidation instruction, so existing positions remain
    untouched when a safety condition is triggered.
    """

    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.05")
    initial_equity: Decimal = Decimal("0")
    day_start_equity: Decimal = Decimal("0")
    peak_equity: Decimal = Decimal("0")
    current_equity: Decimal = Decimal("0")
    daily_loss: Decimal = Decimal("0")
    drawdown: Decimal = Decimal("0")
    total_notional: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    day_key: str = ""
    updated_at: str | None = None
    block_reasons: list[str] = field(default_factory=list)
    kill_switch_engaged: bool = False

    def update(
        self,
        equity: Decimal,
        *,
        now: datetime | None = None,
        total_notional: Decimal = Decimal("0"),
        margin_used: Decimal = Decimal("0"),
    ) -> None:
        current_time = _utc(now)
        equity = _dec(equity)
        key = current_time.date().isoformat()
        if self.initial_equity <= 0:
            self.initial_equity = equity
        if not self.day_key or self.day_key != key:
            self.day_key = key
            self.day_start_equity = equity
        if self.day_start_equity <= 0:
            self.day_start_equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        self.current_equity = equity
        self.daily_loss = max(Decimal("0"), (self.day_start_equity - equity) / self.day_start_equity) if self.day_start_equity > 0 else Decimal("0")
        self.drawdown = max(Decimal("0"), (self.peak_equity - equity) / self.peak_equity) if self.peak_equity > 0 else Decimal("0")
        self.total_notional = max(Decimal("0"), _dec(total_notional))
        self.margin_used = max(Decimal("0"), _dec(margin_used))
        self.updated_at = current_time.isoformat()
        automatic: list[str] = []
        if self.daily_loss >= self.max_daily_loss:
            automatic.append("DAILY_LOSS_LIMIT")
        if self.drawdown >= self.max_drawdown:
            automatic.append("PEAK_DRAWDOWN_LIMIT")
        self.block_reasons = sorted(set(self.block_reasons).union(automatic))

    def trigger(self, reason: str) -> None:
        if reason:
            self.block_reasons = sorted(set(self.block_reasons).union({str(reason)}))

    def engage_kill_switch(self) -> None:
        self.kill_switch_engaged = True
        self.trigger("MANUAL_KILL_SWITCH")

    def safe(self) -> bool:
        return not self.kill_switch_engaged and not self.block_reasons and self.daily_loss < self.max_daily_loss and self.drawdown < self.max_drawdown

    def snapshot(self) -> dict[str, Any]:
        return {
            "initial_equity": str(self.initial_equity),
            "day_start_equity": str(self.day_start_equity),
            "peak_equity": str(self.peak_equity),
            "current_equity": str(self.current_equity),
            "daily_loss": str(self.daily_loss),
            "drawdown": str(self.drawdown),
            "total_notional": str(self.total_notional),
            "margin_used": str(self.margin_used),
            "max_daily_loss": str(self.max_daily_loss),
            "max_drawdown": str(self.max_drawdown),
            "day_key": self.day_key,
            "updated_at": self.updated_at,
            "block_reasons": list(self.block_reasons),
            "kill_switch_engaged": self.kill_switch_engaged,
        }

    def restore(self, payload: Mapping[str, Any] | None) -> None:
        data = dict(payload or {})
        for name in ("initial_equity", "day_start_equity", "peak_equity", "current_equity", "daily_loss", "drawdown", "total_notional", "margin_used", "max_daily_loss", "max_drawdown"):
            if name in data:
                setattr(self, name, _dec(data[name], getattr(self, name)))
        self.day_key = str(data.get("day_key") or self.day_key)
        self.updated_at = str(data.get("updated_at")) if data.get("updated_at") else self.updated_at
        # Operational failures are re-evaluated on a fresh start. Persisting
        # them would make a recovered WebSocket or clock remain blocked
        # forever. Hard loss/reject limits remain sticky until an operator
        # explicitly handles them; the file-backed manual kill switch is
        # re-engaged by VenueRuntime when its file is present.
        self.block_reasons = [str(item) for item in data.get("block_reasons", []) if str(item) in PERSISTED_BLOCK_REASONS]
        self.kill_switch_engaged = bool(data.get("kill_switch_engaged", False))


__all__ = ["RuntimeRiskState"]
