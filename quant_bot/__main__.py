from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import run_local
from .testnet_runtime import DEFAULT_ARTIFACT, preflight, run_foreground


def main() -> None:
    parser = argparse.ArgumentParser(prog="quant_bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--mode", choices=("shadow", "paper", "testnet"), required=True)
    run.add_argument("--venue", choices=("bybit-demo",), default=None)
    run.add_argument("--input", default="quant/outputs/model_dataset.csv")
    run.add_argument("--state", default="quant/outputs/runtime_state.json")
    run.add_argument("--limit", type=int, default=100)
    run.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    run.add_argument("--symbols", default="auto")
    run.add_argument("--enable-orders", action="store_true")
    run.add_argument("--confirm-testnet", action="store_true", help="explicitly allow Bybit Demo orders; never enables mainnet")
    run.add_argument("--once", action="store_true")
    run.add_argument("--poll-seconds", type=int, default=60)
    pre = subparsers.add_parser("preflight")
    pre.add_argument("--venue", choices=("bybit-demo",), required=True)
    pre.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    args = parser.parse_args()
    if args.command == "run":
        if args.mode == "testnet":
            print(json.dumps(run_foreground(artifact_path=Path(args.model), enable_orders=args.enable_orders, confirm_testnet=args.confirm_testnet, symbols=args.symbols, once=args.once, poll_seconds=args.poll_seconds), ensure_ascii=False, default=str))
        else:
            print(json.dumps(run_local(args.mode, Path(args.input), Path(args.state), args.limit), ensure_ascii=False))
    elif args.command == "preflight":
        try:
            print(json.dumps(preflight(artifact_path=Path(args.model)), ensure_ascii=False, default=str))
        except Exception as error:
            print(json.dumps({"status": "BLOCKED", "error_code": getattr(error, "code", "PREFLIGHT_FAILED"), "message": str(error)}, ensure_ascii=False))
            raise SystemExit(2)


if __name__ == "__main__":
    main()
