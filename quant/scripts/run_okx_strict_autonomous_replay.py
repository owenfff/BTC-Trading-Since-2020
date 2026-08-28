#!/usr/bin/env python3
"""Run the frozen v3 model through a strict OKX public-market replay."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from research.okx_autonomous_replay import load_feature_rows, run_buy_and_hold, run_strict_replay  # noqa: E402


DEFAULT_FEATURES = ROOT / "quant" / "outputs" / "okx_public_market" / "BTC-USDT-SWAP_1H" / "features.csv"
DEFAULT_MODEL = ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v3.json"
DEFAULT_REPORT_JSON = ROOT / "quant" / "reports" / "okx_strict_autonomous_replay.json"
DEFAULT_REPORT_MD = ROOT / "quant" / "reports" / "okx_strict_autonomous_replay.md"
DEFAULT_DETAILS = ROOT / "quant" / "outputs" / "okx_strict_autonomous_replay.csv"


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


def write_details(path: Path, details: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "decision_time", "bar_open_time", "bar_close_time", "close", "current_exposure",
        "raw_model_action", "predicted_action", "predicted_target_exposure", "confidence", "equity_after_decision",
        "context_status", "funding_missing", "mark_index_missing",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(details)


def window_summary(details: list[dict[str, Any]], window_count: int = 3) -> list[dict[str, Any]]:
    if not details:
        return []
    result: list[dict[str, Any]] = []
    size = max(1, len(details) // window_count)
    for index in range(window_count):
        start = index * size
        end = len(details) if index == window_count - 1 else min(len(details), (index + 1) * size)
        part = details[start:end]
        if not part:
            continue
        first_equity = float(part[0]["equity_after_decision"])
        last_equity = float(part[-1]["equity_after_decision"])
        values = [float(item["equity_after_decision"]) for item in part]
        peak = first_equity
        drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak if peak else 0.0)
        counts = Counter(str(item["predicted_action"]) for item in part if item["predicted_action"] != "WARMUP")
        result.append(
            {
                "window": f"WF{index + 1}",
                "start": part[0]["decision_time"],
                "end": part[-1]["decision_time"],
                "rows": len(part),
                "net_return": last_equity / first_equity - 1.0 if first_equity else None,
                "max_drawdown": drawdown,
                "action_counts": dict(sorted(counts.items())),
            }
        )
    return result


def _markdown(report: dict[str, Any]) -> str:
    replay = report["strict_autonomous_replay"]
    metrics = replay["metrics"]
    baseline = report["baselines"]
    lines = [
        "# OKX Strict Autonomous Replay",
        "",
        f"- status: **{report['status']}**",
        f"- strategy: `{report['strategy_version']}`",
        "- track: `STRICT_AUTONOMOUS_REPLAY`",
        "- fidelity: `BEHAVIORAL_APPROXIMATION`",
        f"- market rows: `{report['market_rows']}`; warmup rows: `{replay['warmup_rows']}`; signal rows: `{replay['signal_rows']}`",
        f"- period: `{report['period']['start']}` → `{report['period']['end']}`",
        "",
        "## 结果",
        "",
        f"- 净结果：`{metrics['net_return']:.6%}`",
        f"- 最终权益（初始=1）：`{metrics['final_equity']:.8f}`",
        f"- 最大回撤：`{metrics['max_drawdown']:.6%}`",
        f"- Profit Factor：`{metrics['profit_factor'] if metrics['profit_factor'] is not None else 'N/A'}`",
        f"- 交易次数：`{metrics['trade_count']}`；换手暴露：`{metrics['turnover_exposure']:.6f}`",
        f"- 原始动作与目标仓位推导动作不一致：`{replay['raw_action_mismatch_count']}`；目标暴露饱和（±1）行数：`{replay['target_saturated_rows']}`",
        f"- 手续费：`{metrics['fees']:.8f}`；滑点：`{metrics['slippage_cost']:.8f}`；资金费净支付：`{metrics['funding_payment_net']:.8f}`",
        "",
        "## 基线",
        "",
        f"- 不交易：净结果 `{baseline['no_trade']['net_return']:.6%}`",
        f"- 买入并持有：净结果 `{baseline['buy_and_hold']['net_return']:.6%}`",
        "",
        "## 时间因果与覆盖",
        "",
        f"- 因果时间违规：`{replay['causal_timestamp_violation_count']}`",
        f"- 指标缺失计数：`{json.dumps(replay['indicator_missing_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- 上下文覆盖：`{json.dumps(report['context_status_counts'], ensure_ascii=False, sort_keys=True)}`",
        "- 回放只使用已确认关闭的 OKX K 线；成交执行价取下一根 K 线开盘价。",
        "- 本报告没有读取 BitMEX 未来仓位、未来成交或账户结果。",
        "",
        "## 结论",
        "",
        f"- 模型升级：**{report['model_upgrade_decision']}**",
        f"- 模型可用性：**{report['model_readiness']}**；原因：{ '；'.join(report['readiness_reasons']) }",
        "- 本次只是用 OKX 公共行情验证当前冻结 v3 的可执行性，不代表已经训练出新的 v4/v5，也不代表未来盈利。",
        "- OKX 公共行情是市场环境输入；BitMEX 原始成交仍是行为教师来源，二者没有被混成一份账户记录。",
        "",
        "## 三段时间窗口",
        "",
        "| window | start | end | rows | net return | max drawdown |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in replay["windows"]:
        lines.append(f"| {item['window']} | {item['start']} | {item['end']} | {item['rows']} | {item['net_return']:.6%} | {item['max_drawdown']:.6%} |")
    return "\n".join(lines) + "\n"


def build(
    features_path: Path = DEFAULT_FEATURES,
    model_path: Path = DEFAULT_MODEL,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
    details_path: Path = DEFAULT_DETAILS,
    *,
    warmup_bars: int = 72,
    fill_ratio: float = 1.0,
    fee_rate: float = 0.0005,
    slippage_rate: float = 0.0001,
) -> dict[str, Any]:
    if not features_path.exists():
        raise FileNotFoundError(features_path)
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    rows = load_feature_rows(features_path)
    if len(rows) < warmup_bars + 2:
        raise ValueError(f"not enough closed rows for strict replay: {len(rows)}")
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    model = CrossAssetNumpyLogisticStrategy.from_dict(payload.get("model", {}))
    replay = run_strict_replay(rows, model, warmup_bars=warmup_bars, fill_ratio=fill_ratio, fee_rate=fee_rate, slippage_rate=slippage_rate)
    replay["windows"] = window_summary(replay["details"])
    buy_hold = run_buy_and_hold(rows, warmup_bars=warmup_bars, fee_rate=fee_rate, slippage_rate=slippage_rate)
    context_status = Counter(str(row.get("feature_context_status") or row.get("context_status") or "UNKNOWN") for row in rows)
    readiness_reasons: list[str] = []
    if replay["raw_action_mismatch_count"] > max(1, int(replay["signal_rows"] * 0.05)):
        readiness_reasons.append("动作分类头与目标暴露推导不一致")
    if replay["target_saturated_rows"] > max(1, int(replay["signal_rows"] * 0.5)):
        readiness_reasons.append("目标暴露长期饱和在边界")
    if replay["metrics"]["trade_count"] < 3:
        readiness_reasons.append("有效仓位调整次数过少，无法证明稳定捕捉信号")
    model_readiness = "NOT_READY_FOR_DEMO" if readiness_reasons else "RESEARCH_ONLY"
    report: dict[str, Any] = {
        "report_version": "M18.2-OKX-STRICT-AUTONOMOUS-REPLAY-1.0",
        "status": "PASS_WITH_WARNINGS" if replay["causal_timestamp_violation_count"] == 0 else "BLOCKED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "strategy_version": payload.get("model_version") or model.version,
        "analysis_commit": git_head(),
        "market_rows": len(rows),
        "period": {
            "start": rows[0]["_decision_time"].isoformat().replace("+00:00", "Z"),
            "end": rows[-1]["_decision_time"].isoformat().replace("+00:00", "Z"),
        },
        "source": {
            "features": str(features_path.relative_to(ROOT)).replace("\\", "/"),
            "features_sha256": sha256_file(features_path),
            "model": str(model_path.relative_to(ROOT)).replace("\\", "/"),
            "model_sha256": sha256_file(model_path),
            "market_source": "OKX_PUBLIC_API_CLOSED_CANDLES",
            "credentials": "none",
        },
        "strict_autonomous_replay": {
            "metrics": replay["metrics"],
            "action_counts": replay["action_counts"],
            "raw_action_mismatch_count": replay["raw_action_mismatch_count"],
            "target_saturated_rows": replay["target_saturated_rows"],
            "windows": replay["windows"],
            "warmup_bars": replay["warmup_bars"],
            "warmup_rows": replay["warmup_rows"],
            "signal_rows": replay["signal_rows"],
            "causal_timestamp_violation_count": replay["causal_timestamp_violation_count"],
            "indicator_missing_counts": replay["indicator_missing_counts"],
            "state_source": replay["state_source"],
            "teacher_dynamic_state_consumed": replay["teacher_dynamic_state_consumed"],
            "execution_rule": "NEXT_CLOSED_BAR_OPEN; FILL_RATIO_CONFIGURED; COSTS_INCLUDED",
        },
        "baselines": {
            "no_trade": {"net_return": 0.0, "final_equity": 1.0, "trade_count": 0},
            "buy_and_hold": buy_hold,
        },
        "context_status_counts": dict(sorted(context_status.items())),
        "conditional_behavior": {
            "status": "NOT_RUN",
            "reason": "This run is intentionally strict autonomous and has no teacher labels in the OKX market-context file.",
        },
        "model_upgrade_decision": "NOT_PROMOTED_CURRENT_V3_MARKET_CONTEXT_ONLY",
        "model_readiness": model_readiness,
        "readiness_reasons": readiness_reasons,
        "live_trading_allowed": False,
        "demo_model_switched": False,
        "private_api_used": False,
        "orders_submitted": False,
        "real_funds_used": False,
        "raw_account_inputs_unchanged": True,
        "detail_output": str(details_path.relative_to(ROOT)).replace("\\", "/"),
    }
    write_details(details_path, replay["details"])
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_md.write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--warmup-bars", type=int, default=72)
    parser.add_argument("--fill-ratio", type=float, default=1.0)
    parser.add_argument("--fee-rate", type=float, default=0.0005)
    parser.add_argument("--slippage-rate", type=float, default=0.0001)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    args = parser.parse_args()
    try:
        report = build(args.features, args.model, args.report_json, args.report_md, args.details, warmup_bars=args.warmup_bars, fill_ratio=args.fill_ratio, fee_rate=args.fee_rate, slippage_rate=args.slippage_rate)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": report["status"],
        "strategy_version": report["strategy_version"],
        "market_rows": report["market_rows"],
        "period": report["period"],
        "strict_metrics": report["strict_autonomous_replay"]["metrics"],
        "action_counts": report["strict_autonomous_replay"]["action_counts"],
        "causal_timestamp_violation_count": report["strict_autonomous_replay"]["causal_timestamp_violation_count"],
        "model_upgrade_decision": report["model_upgrade_decision"],
        "model_readiness": report["model_readiness"],
        "report_json": str(args.report_json),
        "report_md": str(args.report_md),
        "orders_submitted": report["orders_submitted"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
