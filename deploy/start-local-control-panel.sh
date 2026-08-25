#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
export PYTHONPATH="${repo_dir}:${repo_dir}/quant/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${python_bin}" "${repo_dir}/frontend/server.py" --host 127.0.0.1 --port "${PORT:-8080}" --control
