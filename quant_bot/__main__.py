from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import run_local
from .testnet_runtime import DEFAULT_ARTIFACT, preflight, run_foreground
from .venue_preflight import preflight_venue
from .venue_runtime import run_foreground_venue
from .multivenue_runtime import SUPPORTED_MULTI_VENUES, run_foreground_multivenue
from .supervisor import supervise_venue


def main() -> None:
    parser = argparse.ArgumentParser(prog="quant_bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--mode", choices=("shadow", "paper", "testnet"), required=True)
    run.add_argument("--venue", choices=("bybit-demo", "okx-demo", "binance-spot-testnet", "binance-futures-testnet"), default=None)
    run.add_argument("--input", default="quant/outputs/model_dataset.csv")
    run.add_argument("--state", default="quant/outputs/runtime_state.json")
    run.add_argument("--limit", type=int, default=100)
    run.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    run.add_argument("--symbols", default="auto")
    run.add_argument("--enable-orders", action="store_true")
    run.add_argument("--confirm-testnet", action="store_true", help="explicitly allow non-production orders; never enables mainnet")
    run.add_argument("--allow-spot-approximation", action="store_true", help="allow derivative-trained behavior to be adapted to cash Spot balances")
    run.add_argument("--once", action="store_true")
    run.add_argument("--poll-seconds", type=int, default=60)
    supervise = subparsers.add_parser("supervise", help="run one non-production venue with bounded safe restarts")
    supervise.add_argument("--mode", choices=("testnet",), default="testnet")
    supervise.add_argument("--venue", choices=("okx-demo", "binance-spot-testnet", "binance-futures-testnet"), required=True)
    supervise.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    supervise.add_argument("--symbols", default="auto")
    supervise.add_argument("--enable-orders", action="store_true")
    supervise.add_argument("--confirm-testnet", action="store_true")
    supervise.add_argument("--allow-spot-approximation", action="store_true")
    supervise.add_argument("--poll-seconds", type=int, default=60)
    supervise.add_argument("--max-restarts", type=int, default=3)
    run_all = subparsers.add_parser("run-all", help="run OKX Demo and Binance Spot Testnet under one supervisor")
    run_all.add_argument("--mode", choices=("testnet",), default="testnet")
    run_all.add_argument("--venues", default=",".join(SUPPORTED_MULTI_VENUES))
    run_all.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    run_all.add_argument("--symbols", default="auto")
    run_all.add_argument("--enable-orders", action="store_true")
    run_all.add_argument("--confirm-testnet", action="store_true", help="explicitly allow non-production orders; never enables mainnet")
    run_all.add_argument("--allow-spot-approximation", action="store_true", help="allow derivative-trained behavior to be adapted to cash Spot balances")
    run_all.add_argument("--once", action="store_true")
    run_all.add_argument("--poll-seconds", type=int, default=60)
    pre = subparsers.add_parser("preflight")
    pre.add_argument("--venue", choices=("bybit-demo", "okx-demo", "binance-spot-testnet", "binance-futures-testnet"), required=True)
    pre.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    args = parser.parse_args()
    if args.command == "run":
        if args.mode == "testnet":
            try:
                if args.venue in {"okx-demo", "binance-spot-testnet", "binance-futures-testnet"}:
                    result = run_foreground_venue(venue=args.venue, artifact_path=Path(args.model), enable_orders=args.enable_orders, confirm_testnet=args.confirm_testnet, symbols=args.symbols, once=args.once, poll_seconds=args.poll_seconds, allow_spot_approximation=args.allow_spot_approximation)
                else:
                    result = run_foreground(artifact_path=Path(args.model), enable_orders=args.enable_orders, confirm_testnet=args.confirm_testnet, symbols=args.symbols, once=args.once, poll_seconds=args.poll_seconds)
                print(json.dumps(result, ensure_ascii=False, default=str))
            except Exception as error:
                print(json.dumps({"status": "BLOCKED", "error_code": getattr(error, "code", "RUNTIME_FAILED"), "message": str(error)}, ensure_ascii=False))
                raise SystemExit(2)
        else:
            print(json.dumps(run_local(args.mode, Path(args.input), Path(args.state), args.limit), ensure_ascii=False))
    elif args.command == "supervise":
        try:
            result = supervise_venue(
                venue=args.venue,
                artifact_path=Path(args.model),
                enable_orders=args.enable_orders,
                confirm_testnet=args.confirm_testnet,
                symbols=args.symbols,
                poll_seconds=args.poll_seconds,
                allow_spot_approximation=args.allow_spot_approximation,
                max_restarts=args.max_restarts,
            )
            print(json.dumps(result, ensure_ascii=False, default=str))
            if result.get("status") == "BLOCKED":
                raise SystemExit(2)
        except Exception as error:
            print(json.dumps({"status": "BLOCKED", "error_code": getattr(error, "code", "RUNTIME_FAILED"), "message": str(error)}, ensure_ascii=False))
            raise SystemExit(2)
    elif args.command == "run-all":
        try:
            result = run_foreground_multivenue(
                venues=args.venues,
                artifact_path=Path(args.model),
                enable_orders=args.enable_orders,
                confirm_testnet=args.confirm_testnet,
                symbols=args.symbols,
                once=args.once,
                poll_seconds=args.poll_seconds,
                allow_spot_approximation=args.allow_spot_approximation,
            )
            print(json.dumps(result, ensure_ascii=False, default=str))
            if result["status"] == "BLOCKED":
                raise SystemExit(2)
        except Exception as error:
            print(json.dumps({"status": "BLOCKED", "error_code": getattr(error, "code", "RUNTIME_FAILED"), "message": str(error)}, ensure_ascii=False))
            raise SystemExit(2)
    elif args.command == "preflight":
        try:
            result = preflight(artifact_path=Path(args.model)) if args.venue == "bybit-demo" else preflight_venue(args.venue, artifact_path=args.model)
            print(json.dumps(result, ensure_ascii=False, default=str))
        except Exception as error:
            print(json.dumps({"status": "BLOCKED", "error_code": getattr(error, "code", "PREFLIGHT_FAILED"), "message": str(error)}, ensure_ascii=False))
            raise SystemExit(2)


if __name__ == "__main__":
    main()
