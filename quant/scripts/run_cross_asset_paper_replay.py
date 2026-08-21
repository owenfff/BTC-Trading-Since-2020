#!/usr/bin/env python3
"""Replay the unified cross-asset model through the local paper engine only."""

from __future__ import annotations

import bisect
import csv
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.paper import PaperTradingEngine  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402


UTC = timezone.utc
DATASET = ROOT / "quant" / "outputs" / "cross_asset_model_dataset.csv"
MARKET = ROOT / "quant" / "outputs" / "cross_asset_market_context.csv"
REPORTS = ROOT / "quant" / "reports"


def parse_utc(value: Any) -> datetime:
    text = str(value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _market_closes() -> dict[str, tuple[list[datetime], list[Decimal]]]:
    grouped: defaultdict[str, list[tuple[datetime, Decimal]]] = defaultdict(list)
    if not MARKET.exists():
        return {}
    with MARKET.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("open") in (None, "") or row.get("close") in (None, ""):
                continue
            try:
                grouped[str(row.get("symbol") or "")].append((parse_utc(row["timestamp"]), Decimal(str(row["close"]))))
            except (ValueError, ArithmeticError):
                continue
    return {symbol: (list(zip(*sorted(values)))[0], list(zip(*sorted(values)))[1]) for symbol, values in grouped.items()}


def _reference_price(closes: dict[str, tuple[list[datetime], list[Decimal]]], symbol: str, when: datetime) -> Decimal:
    times_values = closes.get(symbol)
    if not times_values:
        return Decimal("1")
    times, values = times_values
    index = bisect.bisect_right(times, when) - 1
    return values[max(0, index)]


def build() -> dict[str, Any]:
    if not DATASET.exists():
        raise FileNotFoundError(DATASET)
    with DATASET.open("r", encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    rows = [row for row in source_rows if str(row.get("model_eligible", "")).lower() == "true"]
    train = [row for row in rows if row.get("dataset_split") == "TRAIN"]
    replay_rows = [row for row in rows if row.get("dataset_split") in {"VALIDATION", "TEST"}]
    if not train or not replay_rows:
        raise ValueError("cross-asset paper replay requires eligible TRAIN and out-of-time rows")
    model = CrossAssetNumpyLogisticStrategy().fit(train)
    closes = _market_closes()
    engines: dict[str, PaperTradingEngine] = {}
    signal_count = 0
    action_counts: defaultdict[str, int] = defaultdict(int)
    for row in replay_rows:
        symbol = str(row["symbol"])
        engine = engines.setdefault(symbol, PaperTradingEngine())
        signal = model.predict(strategy_input_from_row(row))
        engine.apply_signal(
            signal,
            reference_price=_reference_price(closes, symbol, parse_utc(row["decision_time"])),
        )
        signal_count += 1
        action_counts[signal.action] += 1
    snapshots = {symbol: engine.snapshot() for symbol, engine in engines.items()}
    result = {
        "report_version": "M13-CROSS-ASSET-PAPER-REPLAY-1.0",
        "analysis_commit": _git_head(),
        "status": "PAPER_REPLAY_PASS",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "strategy_version": model.version,
        "train_rows": len(train),
        "replay_rows": len(replay_rows),
        "replay_symbols": len(engines),
        "signal_count": signal_count,
        "action_counts": dict(sorted(action_counts.items())),
        "paper_filled_orders": sum(int(state["filled_orders"]) for state in snapshots.values()),
        "paper_partial_orders": sum(int(state["partial_orders"]) for state in snapshots.values()),
        "paper_rejected_orders": sum(int(state["rejected_orders"]) for state in snapshots.values()),
        "per_symbol_state": snapshots,
        "reference_price_source": "latest public hourly close at or before decision; local fallback only if unavailable",
        "private_api_used": False,
        "real_funds_used": False,
        "profitability_claim": False,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "cross_asset_paper_replay.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS / "cross_asset_paper_replay.md").write_text(
        "\n".join([
            "# Cross-Asset Paper Replay",
            "",
            f"- status: **{result['status']}**",
            f"- strategy version: `{result['strategy_version']}`",
            f"- out-of-time replay rows: `{result['replay_rows']}`",
            f"- symbols replayed independently: `{result['replay_symbols']}`",
            f"- signals processed: `{result['signal_count']}`",
            f"- local partial orders: `{result['paper_partial_orders']}`",
            "- market reference: latest public hourly close at or before each decision",
            "- private API, credentials, live orders, and real funds: **not used**",
            "",
            "This is a deterministic local paper replay of a behavioral approximation. It is not evidence of live stability, exact strategy recovery, or future profitability.",
        ]) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
