from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import run_local


def main() -> None:
    parser = argparse.ArgumentParser(prog="quant_bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--mode", choices=("shadow", "paper"), required=True)
    run.add_argument("--input", default="quant/outputs/model_dataset.csv")
    run.add_argument("--state", default="quant/outputs/runtime_state.json")
    run.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.command == "run":
        print(json.dumps(run_local(args.mode, Path(args.input), Path(args.state), args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
