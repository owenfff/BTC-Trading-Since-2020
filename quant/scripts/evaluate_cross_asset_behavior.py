#!/usr/bin/env python3
"""Evaluate the unified cross-asset behavior model without exchange access."""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.backtest import BacktestConfig, MarketBar, MarketSeries, SignalEvent, simulate  # noqa: E402
from quant_bot.strategy.base import StrategySignal  # noqa: E402
from quant_bot.strategy.distilled_rules import DistilledRuleStrategy  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from quant_bot.strategy.imitation_model import HistoricalBehaviorBaseline  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from quant.scripts.evaluate_strategy_distillation import (  # noqa: E402
    _corr,
    _evaluate,
    _f1_scores,
    _float,
    _mean,
)


DATASET = ROOT / "quant" / "outputs" / "cross_asset_model_dataset.csv"
MARKET = ROOT / "quant" / "outputs" / "cross_asset_market_context.csv"
REPORTS = ROOT / "quant" / "reports"
FEE_RATE = 0.0005142955428165985
UTC = timezone.utc


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _read_rows() -> list[dict[str, Any]]:
    with DATASET.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_market() -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    with MARKET.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = parse_utc(row.get("timestamp"))
            if timestamp is None:
                continue
            grouped[str(row.get("symbol") or "")].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: parse_utc(row.get("timestamp")) or datetime.max.replace(tzinfo=UTC))
    return dict(grouped)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _model_metrics(rows: list[dict[str, Any]], predictions: list[tuple[dict[str, Any], StrategySignal]]) -> dict[str, Any]:
    return _evaluate(rows, predictions)


def _fit_models(train_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not train_rows:
        raise ValueError("cross-asset model has no eligible TRAIN rows")
    return {
        "frequency_baseline": HistoricalBehaviorBaseline().fit(train_rows),
        "distilled_rules": DistilledRuleStrategy(),
        "cross_asset_logistic": CrossAssetNumpyLogisticStrategy().fit(train_rows),
    }


def _predict(rows: list[dict[str, Any]], models: dict[str, Any]) -> dict[str, list[tuple[dict[str, Any], StrategySignal]]]:
    output: dict[str, list[tuple[dict[str, Any], StrategySignal]]] = {}
    for name, model in models.items():
        output[name] = [(row, model.predict(strategy_input_from_row(row))) for row in rows]
    return output


def _walk_forward(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows = [
        ("WF1", datetime(2020, 1, 1, tzinfo=UTC), datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
        ("WF2", datetime(2020, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        ("WF3", datetime(2020, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)),
    ]
    output: list[dict[str, Any]] = []
    for name, start, train_end, validation_end, test_end in windows:
        train = [row for row in rows if start <= (parse_utc(row["decision_time"]) or datetime.max.replace(tzinfo=UTC)) < train_end]
        validation = [row for row in rows if train_end <= (parse_utc(row["decision_time"]) or datetime.min.replace(tzinfo=UTC)) < validation_end]
        test = [row for row in rows if validation_end <= (parse_utc(row["decision_time"]) or datetime.min.replace(tzinfo=UTC)) < test_end]
        if not train:
            continue
        models = _fit_models(train)
        for split_name, split_rows in (("VALIDATION", validation), ("TEST", test)):
            predictions = _predict(split_rows, models)
            for model_name, values in predictions.items():
                metrics = _model_metrics(split_rows, values)
                output.append({"window": name, "split": split_name, "model": model_name, "train_rows": len(train), **metrics})
    return output


def _tick_sizes() -> dict[str, float]:
    path = ROOT / "api-v1-instrument.all.csv"
    output: dict[str, float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "")
            if symbol in output:
                continue
            value = _float(row.get("tickSize"))
            if value is not None and value > 0:
                output[symbol] = value
    return output


def _sensitivity(rows: list[dict[str, Any]], predictions: list[tuple[dict[str, Any], StrategySignal]], market: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    tick_sizes = _tick_sizes()
    by_symbol: defaultdict[str, list[tuple[dict[str, Any], StrategySignal]]] = defaultdict(list)
    for row, signal in predictions:
        by_symbol[str(row["symbol"])].append((row, signal))
    output: list[dict[str, Any]] = []
    for fee_multiplier in (0.5, 1.0, 2.0):
        for slippage_ticks in (0.0, 1.0, 5.0):
            for exposure_limit in (0.10, 0.25, 0.50):
                results = []
                for symbol, values in by_symbol.items():
                    bars = market.get(symbol, [])
                    if not bars:
                        continue
                    series = MarketSeries([
                        MarketBar(
                            timestamp=parse_utc(row["timestamp"]) or datetime.min.replace(tzinfo=UTC),
                            open=float(row.get("open") or 0.0),
                            close=float(row.get("close") or 0.0),
                            funding_rate=(float(row["funding_rate"]) if row.get("funding_source_timestamp_utc") == row.get("timestamp") and row.get("funding_rate") not in (None, "") else 0.0),
                        )
                        for row in bars if row.get("open") not in (None, "") and row.get("close") not in (None, "")
                    ])
                    events = [SignalEvent(parse_utc(row["decision_time"]) or datetime.min.replace(tzinfo=UTC), signal.target_exposure, signal.action, signal.confidence, "cross_asset_logistic") for row, signal in values]
                    result = simulate(
                        series,
                        events,
                        BacktestConfig(
                            fee_rate=FEE_RATE * fee_multiplier,
                            tick_size=tick_sizes.get(symbol, 0.1),
                            slippage_ticks=slippage_ticks,
                            max_abs_exposure=exposure_limit,
                            min_exposure_step=0.00001,
                        ),
                        start_time=series.times[0],
                        end_time=series.times[-1],
                        strategy="cross_asset_logistic",
                    )
                    results.append(result)
                output.append({
                    "model": "cross_asset_logistic",
                    "fee_multiplier": fee_multiplier,
                    "slippage_ticks": slippage_ticks,
                    "max_abs_exposure": exposure_limit,
                    "symbols_simulated": len(results),
                    "total_return_sum": sum(float(result.metrics.get("total_return") or 0.0) for result in results),
                    "turnover_sum": sum(result.turnover for result in results),
                    "fees_sum": sum(result.fees for result in results),
                    "funding_sum": sum(result.funding for result in results),
                    "slippage_sum": sum(result.slippage for result in results),
                    "executed_events": sum(result.executed_events for result in results),
                    "interpretation": "normalized exposure-return proxy; not wallet or account PnL",
                })
    return output


def build() -> dict[str, Any]:
    rows = [row for row in _read_rows() if str(row.get("model_eligible", "")).lower() == "true"]
    if not rows:
        raise ValueError("cross-asset dataset contains no model-eligible rows")
    train_rows = [row for row in rows if row.get("dataset_split") == "TRAIN"]
    models = _fit_models(train_rows)
    predictions = _predict(rows, models)
    global_metrics = {name: _model_metrics(rows, values) for name, values in predictions.items()}
    per_symbol: list[dict[str, Any]] = []
    for symbol in sorted({str(row["symbol"]) for row in rows}):
        symbol_rows = [row for row in rows if row["symbol"] == symbol]
        for name, values in predictions.items():
            symbol_values = [(row, signal) for row, signal in values if row["symbol"] == symbol]
            per_symbol.append({"symbol": symbol, "model": name, **_model_metrics(symbol_rows, symbol_values)})
    walk_forward = _walk_forward(rows)
    sensitivity = _sensitivity(rows, predictions["cross_asset_logistic"], _read_market())
    result = {
        "report_version": "M13-CROSS-ASSET-STRATEGY-1.0",
        "analysis_commit": _git_head(),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "dataset_rows": len(rows),
        "train_rows": len(train_rows),
        "models": list(models),
        "global_metrics": global_metrics,
        "per_symbol_metric_rows": len(per_symbol),
        "walk_forward_rows": len(walk_forward),
        "sensitivity_rows": len(sensitivity),
        "market_data_policy": "public no-key hourly bars; no synthetic market data",
        "profitability_claim": False,
        "raw_account_inputs_unchanged": True,
        "next_stage": "paper replay only after model review; no private exchange connectivity",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "cross_asset_strategy_fidelity.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_csv(REPORTS / "cross_asset_per_symbol_metrics.csv", per_symbol)
    _write_csv(REPORTS / "cross_asset_walk_forward.csv", walk_forward)
    _write_csv(REPORTS / "cross_asset_sensitivity.csv", sensitivity)
    lines = [
        "# Cross-Asset Strategy Fidelity",
        "",
        f"- strategy fidelity: **{result['strategy_fidelity']}**",
        f"- eligible rows: `{len(rows)}`",
        f"- eligible symbols: `{len({row['symbol'] for row in rows})}`",
        f"- analysis commit: `{result['analysis_commit']}`",
        "- models: frequency baseline, deterministic rules, and unified NumPy cross-asset logistic model",
        "- all fits use chronological TRAIN rows only",
        "- no exchange SDK, private API, credential, or live capital was used",
        "",
        "## Interpretation",
        "",
        "This is a behavioral approximation. Per-symbol metrics, walk-forward rows, and sensitivity rows are descriptive validation artifacts. The return columns are normalized exposure-return proxies and are not wallet, account, or strategy PnL claims.",
    ]
    (REPORTS / "cross_asset_strategy_fidelity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
