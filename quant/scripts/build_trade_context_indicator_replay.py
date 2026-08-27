#!/usr/bin/env python3
"""Build a causal, per-trade indicator-context replay audit.

This is a descriptive research artifact.  It answers: "what was visible to
the model immediately before each recorded next action?"  Historical labels
are used only after prediction for evaluation; they are never passed into the
model input.  The script does not connect to an exchange and never changes
the active deployment model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_bot.strategy.feature_contract import FEATURE_COLUMNS, strategy_input_from_row  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402


UTC = timezone.utc
DATASET = ROOT / "quant" / "outputs" / "cross_venue_model_dataset_v3.csv"
MODEL = ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v3.json"
REPORT_JSON = ROOT / "quant" / "reports" / "trade_context_indicator_replay.json"
REPORT_MD = ROOT / "quant" / "reports" / "trade_context_indicator_replay.md"
DETAIL_CSV = ROOT / "quant" / "outputs" / "trade_context_indicator_replay.csv"
INDICATORS = (
    "feature_rsi_14",
    "feature_macd_histogram",
    "feature_bollinger_percent_b_20",
    "feature_volume_percentile_72bar",
    "feature_return_24bar",
    "feature_atr_14bar",
)
ACTION_FIELDS = ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP", "HOLD")
IDLE_ACTIONS = {"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"}
DETAIL_FIELDS = (
    "decision_episode_id",
    "decision_time",
    "source_venue",
    "source_symbol",
    "canonical_asset",
    "feature_latest_bar_time",
    "feature_market_regime",
    "row_market_coverage_status",
    "label_next_action",
    "actual_action_family",
    "predicted_action",
    "predicted_action_family",
    "model_confidence",
    "label_next_target_exposure",
    "predicted_target_exposure",
    "feature_current_normalized_exposure",
    "feature_rsi_14",
    "feature_macd_histogram",
    "feature_bollinger_percent_b_20",
    "feature_volume_percentile_72bar",
    "feature_return_24bar",
    "feature_atr_14bar",
    "causal_market_context",
    "funding_context_status",
    "strategy_reason_zh",
)


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (result if result.tzinfo else result.replace(tzinfo=UTC)).astimezone(UTC)


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def action_family(action: Any) -> str:
    value = str(action or "").upper()
    if value.startswith("OPEN"):
        return "OPEN"
    if value.startswith("ADD"):
        return "ADD"
    if value.startswith("REDUCE"):
        return "REDUCE"
    if value.startswith("CLOSE"):
        return "CLOSE"
    if value.startswith("FLIP"):
        return "FLIP"
    return "HOLD"


def causal_row_audit(row: Mapping[str, Any]) -> dict[str, str]:
    """Audit timestamps that are available before a decision.

    A missing market bar is reported separately from a future/equal bar.  A
    missing funding timestamp is also distinct from a valid prior timestamp;
    neither is silently filled with zero.
    """

    decision = parse_time(row.get("decision_time"))
    bar = parse_time(row.get("feature_latest_bar_time"))
    funding = parse_time(row.get("feature_funding_source_time"))
    next_decision = parse_time(row.get("label_next_decision_time"))
    result = {
        "decision_time": "PASS" if decision else "PARSE_FAILED",
        "closed_bar": "MISSING" if not bar else "PASS" if decision and bar < decision else "FUTURE_OR_EQUAL",
        "funding": "MISSING" if not funding else "PASS" if decision and funding <= decision else "FUTURE_OR_EQUAL",
        "next_label": "NOT_APPLICABLE" if str(row.get("label_status")) != "AVAILABLE" else "PASS" if decision and next_decision and next_decision > decision else "FUTURE_OR_EQUAL",
    }
    return result


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: Any) -> None:
        parsed = number(value)
        if parsed is None:
            return
        self.count += 1
        self.total += parsed
        self.minimum = parsed if self.minimum is None else min(self.minimum, parsed)
        self.maximum = parsed if self.maximum is None else max(self.maximum, parsed)

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "count": self.count,
            "mean": self.total / self.count if self.count else None,
            "min": self.minimum,
            "max": self.maximum,
        }


@dataclass
class GroupStats:
    rows: int = 0
    labeled_rows: int = 0
    observed_actions: int = 0
    predicted_actions: int = 0
    exact_matches: int = 0
    target_error_total: float = 0.0
    target_error_rows: int = 0
    labels: Counter[str] = field(default_factory=Counter)
    predictions: Counter[str] = field(default_factory=Counter)
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)
    indicators: dict[str, RunningStats] = field(default_factory=dict)

    def add(self, row: Mapping[str, Any], predicted_action: str | None, predicted_target: float | None) -> None:
        self.rows += 1
        for key in INDICATORS:
            self.indicators.setdefault(key, RunningStats()).add(row.get(key))
        if not predicted_action or str(row.get("label_status")) != "AVAILABLE" or not row.get("label_next_action"):
            return
        actual = str(row["label_next_action"])
        self.labeled_rows += 1
        self.labels[actual] += 1
        self.predictions[predicted_action] += 1
        self.confusion[(actual, predicted_action)] += 1
        self.exact_matches += int(actual == predicted_action)
        self.observed_actions += int(actual not in IDLE_ACTIONS)
        self.predicted_actions += int(predicted_action not in IDLE_ACTIONS)
        actual_target = number(row.get("label_next_target_exposure"))
        if actual_target is not None and predicted_target is not None:
            self.target_error_total += abs(actual_target - predicted_target)
            self.target_error_rows += 1

    def as_dict(self) -> dict[str, Any]:
        labels = set(self.labels) | set(self.predictions)
        f1_values: list[float] = []
        for label in sorted(labels):
            tp = self.confusion[(label, label)]
            fp = sum(self.confusion[(actual, label)] for actual in labels if actual != label)
            fn = sum(self.confusion[(label, predicted)] for predicted in labels if predicted != label)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1_values.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        family_recall: dict[str, float | None] = {}
        for family in ACTION_FIELDS[:-1]:
            actual_count = sum(count for (actual, _), count in self.confusion.items() if action_family(actual) == family)
            correct = sum(count for (actual, predicted), count in self.confusion.items() if action_family(actual) == family and action_family(predicted) == family)
            family_recall[f"{family.lower()}_recall"] = correct / actual_count if actual_count else None
        return {
            "rows": self.rows,
            "labeled_rows": self.labeled_rows,
            "observed_action_rate": self.observed_actions / self.labeled_rows if self.labeled_rows else None,
            "predicted_action_rate": self.predicted_actions / self.labeled_rows if self.labeled_rows else None,
            "action_accuracy": self.exact_matches / self.labeled_rows if self.labeled_rows else None,
            "action_macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
            "target_exposure_mae": self.target_error_total / self.target_error_rows if self.target_error_rows else None,
            "target_rows": self.target_error_rows,
            "action_counts": dict(self.labels),
            "predicted_action_counts": dict(self.predictions),
            "family_recall": family_recall,
            "indicator_summary": {key: value.as_dict() for key, value in sorted(self.indicators.items())},
        }


def strategy_reason_zh(row: Mapping[str, Any], predicted_action: str) -> str:
    """Explain model inputs in Chinese without claiming trader intent."""

    values: list[str] = []
    rsi = number(row.get("feature_rsi_14"))
    macd = number(row.get("feature_macd_histogram"))
    bb = number(row.get("feature_bollinger_percent_b_20"))
    momentum = number(row.get("feature_return_24bar"))
    if rsi is not None:
        values.append(f"RSI14={rsi:.1f}")
    if macd is not None:
        values.append(f"MACD柱={macd:.6f}")
    if bb is not None:
        values.append(f"布林带位置={bb:.3f}")
    if momentum is not None:
        values.append(f"24小时动量={momentum:.4%}")
    if not values:
        return "指标覆盖不足，仅依据可用历史行为特征；不是原交易员真实理由"
    return f"模型输入依据：{'、'.join(values)}；模型动作：{predicted_action}（不等同于原交易员当时的真实规则）"


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _model_from_artifact(path: Path) -> tuple[CrossAssetNumpyLogisticStrategy, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = CrossAssetNumpyLogisticStrategy.from_dict(payload.get("model", {}))
    return model, {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256_file(path),
        "model_version": payload.get("model_version"),
        "feature_contract_version": payload.get("feature_contract_version"),
        "training_data_sha256": payload.get("training_data_sha256"),
        "frozen_cutoff": payload.get("frozen_cutoff"),
    }


def _strict_reference() -> dict[str, Any]:
    path = ROOT / "quant" / "reports" / "cross_venue_indicator_autonomous_audit.json"
    if not path.exists():
        return {"status": "NOT_AVAILABLE", "report": str(path.relative_to(ROOT)).replace("\\", "/")}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "UNREADABLE", "error": str(exc)}
    return {
        "status": payload.get("status", "UNKNOWN"),
        "report": str(path.relative_to(ROOT)).replace("\\", "/"),
        "live_trading_allowed": payload.get("live_trading_allowed"),
        "demo_model_auto_switch": payload.get("demo_model_auto_switch"),
        "candidate_artifact_status": (payload.get("candidate_model_manifest") or {}).get("artifact_status"),
    }


def build(
    dataset_path: Path = DATASET,
    model_path: Path = MODEL,
    report_json: Path = REPORT_JSON,
    report_md: Path = REPORT_MD,
    detail_csv: Path = DETAIL_CSV,
) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"deployment model not found: {model_path}")

    model, model_meta = _model_from_artifact(model_path)
    groups: dict[str, GroupStats] = {"ALL": GroupStats()}
    venue_groups: defaultdict[str, GroupStats] = defaultdict(GroupStats)
    symbol_groups: defaultdict[str, GroupStats] = defaultdict(GroupStats)
    action_context: defaultdict[str, GroupStats] = defaultdict(GroupStats)
    row_status = Counter()
    causal_status = Counter()
    indicator_missing = Counter()
    parse_failures = Counter()
    prediction_errors = Counter()
    total_rows = 0
    eligible_rows = 0
    labeled_rows = 0
    detail_csv.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("r", encoding="utf-8", newline="") as source, detail_csv.open("w", encoding="utf-8", newline="") as detail:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("dataset CSV is empty")
        missing_features = [key for key in FEATURE_COLUMNS if key not in reader.fieldnames]
        writer = csv.DictWriter(detail, fieldnames=list(DETAIL_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            total_rows += 1
            venue = str(row.get("source_venue") or "UNKNOWN")
            symbol = str(row.get("source_symbol") or row.get("symbol") or "UNKNOWN")
            status = causal_row_audit(row)
            row_status[str(row.get("row_market_coverage_status") or row.get("market_coverage_status") or "UNKNOWN")] += 1
            for key, value in status.items():
                causal_status[f"{key}:{value}"] += 1
            for key in INDICATORS:
                if number(row.get(key)) is None:
                    indicator_missing[key] += 1
            if not _bool(row.get("model_eligible")):
                continue
            eligible_rows += 1
            try:
                signal = model.predict(strategy_input_from_row(row))
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                prediction_errors[type(exc).__name__] += 1
                continue
            predicted = str(signal.action)
            predicted_target = float(signal.target_exposure)
            groups["ALL"].add(row, predicted, predicted_target)
            venue_groups[venue].add(row, predicted, predicted_target)
            symbol_groups[symbol].add(row, predicted, predicted_target)
            if row.get("label_next_action"):
                label = str(row["label_next_action"])
                action_context[f"{venue}:{action_family(label)}"].add(row, predicted, predicted_target)
            if str(row.get("label_status")) == "AVAILABLE" and row.get("label_next_action"):
                labeled_rows += 1
            writer.writerow({
                "decision_episode_id": row.get("decision_episode_id", ""),
                "decision_time": row.get("decision_time", ""),
                "source_venue": venue,
                "source_symbol": symbol,
                "canonical_asset": row.get("canonical_asset", ""),
                "feature_latest_bar_time": row.get("feature_latest_bar_time", ""),
                "feature_market_regime": row.get("feature_market_regime", ""),
                "row_market_coverage_status": row.get("row_market_coverage_status", row.get("market_coverage_status", "")),
                "label_next_action": row.get("label_next_action", ""),
                "actual_action_family": action_family(row.get("label_next_action")),
                "predicted_action": predicted,
                "predicted_action_family": action_family(predicted),
                "model_confidence": f"{float(signal.confidence):.12g}",
                "label_next_target_exposure": row.get("label_next_target_exposure", ""),
                "predicted_target_exposure": f"{predicted_target:.12g}",
                "feature_current_normalized_exposure": row.get("feature_current_normalized_exposure", ""),
                **{key: row.get(key, "") for key in INDICATORS},
                "causal_market_context": status["closed_bar"],
                "funding_context_status": status["funding"],
                "strategy_reason_zh": strategy_reason_zh(row, predicted),
            })

    causal_violations = sum(value for key, value in causal_status.items() if key.endswith(":FUTURE_OR_EQUAL") or key.endswith(":PARSE_FAILED"))
    report: dict[str, Any] = {
        "report_version": "M15.24-TRADE-CONTEXT-INDICATOR-REPLAY-1.0",
        "status": "PASS_WITH_STRATEGY_LIMITS" if not causal_violations and not prediction_errors else "BLOCKED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "research_only": True,
        "live_trading_allowed": False,
        "demo_model_switched": False,
        "analysis_commit": git_head(),
        "data_source": {
            "dataset": str(dataset_path.relative_to(ROOT)).replace("\\", "/"),
            "dataset_sha256": sha256_file(dataset_path),
            "model": model_meta,
            "detail_output": str(detail_csv.relative_to(ROOT)).replace("\\", "/"),
        },
        "scope": {
            "total_rows": total_rows,
            "model_eligible_rows": eligible_rows,
            "labeled_rows_predicted": labeled_rows,
            "model_input_contract_columns": len(FEATURE_COLUMNS),
            "dataset_missing_contract_columns": missing_features,
            "labels_used_as_model_input": False,
            "observed_dynamic_state_in_conditional_track": True,
            "conditional_track_note": "Teacher position/state fields describe the recorded pre-action context; they are not strict autonomous evidence.",
        },
        "coverage": {
            "row_market_coverage": dict(row_status),
            "indicator_missing_counts": dict(indicator_missing),
            "indicator_missing_rates": {key: value / total_rows if total_rows else None for key, value in indicator_missing.items()},
        },
        "historical_orderbook": {
            "available": False,
            "status": "NOT_AVAILABLE_FROM_CURRENT_PUBLIC_SOURCE",
            "note": "The pinned public replay provides candles, fills, orders, funding and snapshots; it does not provide a verified historical L2/order-book stream. This report therefore replays closed-bar indicators, not historical bid/ask depth.",
        },
        "causal_audit": {
            "violations": causal_violations,
            "counts": dict(causal_status),
            "definition": "feature_latest_bar_time must be strictly earlier than decision_time; funding source time must not be after decision_time; next labels must be strictly later.",
        },
        "conditional_behavior": groups["ALL"].as_dict(),
        "by_venue": {key: value.as_dict() for key, value in sorted(venue_groups.items())},
        "by_symbol": {key: value.as_dict() for key, value in sorted(symbol_groups.items())},
        "by_venue_action_family": {key: value.as_dict() for key, value in sorted(action_context.items())},
        "model_prediction_errors": dict(prediction_errors),
        "strict_autonomous_reference": _strict_reference(),
        "strategy_reason_contract": {
            "language": "zh-CN",
            "label": "模型输入依据，不代表原交易员真实使用的指标或规则",
            "fields": list(INDICATORS),
        },
        "next_step": "Use the detail CSV to render historical trade contexts and compare against K-lines. Keep the active model unchanged until strict autonomous time-out replay passes its promotion gates.",
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_markdown(report_md, report)
    return report


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _write_markdown(path: Path, report: Mapping[str, Any]) -> None:
    scope = report["scope"]
    coverage = report["coverage"]
    metrics = report["conditional_behavior"]
    lines = [
        "# 历史交易前指标上下文回放",
        "",
        "> 本报告是 `CONDITIONAL_BEHAVIOR` 描述性审计：它回看每条记录的决策时刻之前可见的已收盘 K 线和指标。标签只在模型预测之后用于比较，不进入模型输入。结果仍是 `BEHAVIORAL_APPROXIMATION`，不代表已经精确恢复原交易员策略。",
        "",
        "## 结论",
        "",
        f"- 状态：**{report['status']}**；研究模式，禁止主网和真实下单。",
        f"- 数据集：{scope['total_rows']:,} 行；模型可用 {scope['model_eligible_rows']:,} 行；完成预测并有下一动作标签 {scope['labeled_rows_predicted']:,} 行。",
        f"- 因果时间违规：**{report['causal_audit']['violations']:,}**。最后已收盘 K 线必须严格早于决策时刻。",
        f"- 模型输入不含 label/observed 字段：**{scope['labels_used_as_model_input'] is False}**。",
        "- 当前 Demo 模型未切换；本报告不会授权自动下单。",
        "",
        "## 当前模型在历史交易前上下文上的对照",
        "",
        f"- Action Accuracy：{_fmt(metrics['action_accuracy'])}",
        f"- Action Macro-F1：{_fmt(metrics['action_macro_f1'])}",
        f"- 目标暴露 MAE：{_fmt(metrics['target_exposure_mae'])}",
        f"- 原记录非空动作比例：{_fmt(metrics['observed_action_rate'])}",
        f"- 模型非空动作比例：{_fmt(metrics['predicted_action_rate'])}",
        "",
        "## 数据和指标覆盖",
        "",
        "| 项目 | 结果 |",
        "| --- | ---: |",
        f"| 行情覆盖状态 | `{json.dumps(coverage['row_market_coverage'], ensure_ascii=False)}` |",
    ]
    for key in INDICATORS:
        lines.append(f"| {key} 缺失率 | {_fmt(coverage['indicator_missing_rates'].get(key))} |")
    lines.extend([
        "",
        "## 历史盘口边界",
        "",
        "当前固定公开来源没有经过验证的历史 L2/盘口深度流，因此本次可以严格退回查看已收盘 K 线和指标，但不能声称复原交易发生前的买一卖一、盘口深度或撤单队列。盘口状态为 `NOT_AVAILABLE_FROM_CURRENT_PUBLIC_SOURCE`。",
        "",
        "## 各交易所动作结果",
        "",
        "| 交易所 | 标签行数 | Accuracy | Macro-F1 | 目标 MAE |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for venue, item in sorted(report["by_venue"].items()):
        lines.append(f"| {venue} | {item['labeled_rows']:,} | {_fmt(item['action_accuracy'])} | {_fmt(item['action_macro_f1'])} | {_fmt(item['target_exposure_mae'])} |")
    lines.extend([
        "",
        "## 实际动作前的指标分组",
        "",
        "下表是按交易所和历史下一动作族聚合的输入均值。它回答“该类动作发生前模型看到了什么”，不是事后声称原交易员使用了这些指标。",
        "",
        "| 交易所/动作 | 行数 | RSI14 均值 | MACD 柱均值 | 布林 %B 均值 | 24h 动量均值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for key, item in sorted(report["by_venue_action_family"].items()):
        indicator = item["indicator_summary"]
        lines.append("| {} | {:,} | {} | {} | {} | {} |".format(
            key,
            item["labeled_rows"],
            _fmt((indicator.get("feature_rsi_14") or {}).get("mean")),
            _fmt((indicator.get("feature_macd_histogram") or {}).get("mean"), 6),
            _fmt((indicator.get("feature_bollinger_percent_b_20") or {}).get("mean")),
            _fmt((indicator.get("feature_return_24bar") or {}).get("mean"), 6),
        ))
    lines.extend([
        "",
        "## 如何回看",
        "",
        f"逐行上下文已经生成到 `{report['data_source']['detail_output']}`（位于被忽略的 `quant/outputs/`）。其中包含决策时间、最后已收盘 K 线时间、RSI14、MACD 柱、布林 %B、成交量分位数、24 小时动量、原动作、模型动作和中文解释，可供前端回放使用。",
        "",
        "中文策略原因统一标记为：**模型输入依据，不代表原交易员真实使用的指标或规则**。若指标缺失，会明确显示“指标覆盖不足”，不会用 0 伪造。",
        "",
        "## 严格自主回放边界",
        "",
        f"现有严格自主回放参考：`{report['strict_autonomous_reference'].get('report', '—')}`，状态为 `{report['strict_autonomous_reference'].get('status', '—')}`。本次上下文回放使用历史记录的条件状态来回答“交易前看到了什么”，不能替代从零仓位、机器人自有状态的严格自主回放。",
        "",
        "## 安全边界",
        "",
        "- 没有连接交易所、没有读取 API 密钥、没有提交订单。",
        "- 没有修改任何仓库根目录原始 CSV/JSON。",
        "- 没有训练新模型，也没有替换 v2/v3 Demo 部署模型。",
        "- 结论不构成盈利保证；进入 Demo 或实盘前仍需独立通过严格自主时序测试、成本压力测试和风险验收。",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--report-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=REPORT_MD)
    parser.add_argument("--detail-csv", type=Path, default=DETAIL_CSV)
    args = parser.parse_args()
    report = build(args.dataset, args.model, args.report_json, args.report_md, args.detail_csv)
    print(json.dumps({
        "status": report["status"],
        "total_rows": report["scope"]["total_rows"],
        "model_eligible_rows": report["scope"]["model_eligible_rows"],
        "causal_violations": report["causal_audit"]["violations"],
        "report_md": str(args.report_md),
        "report_json": str(args.report_json),
        "detail_csv": str(args.detail_csv),
    }, ensure_ascii=False))
    return 0 if report["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
