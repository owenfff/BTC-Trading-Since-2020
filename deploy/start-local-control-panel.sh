#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
export PYTHONPATH="${repo_dir}:${repo_dir}/quant/src${PYTHONPATH:+:${PYTHONPATH}}"

credentials_file="${QUANT_CREDENTIALS_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/quant-bot/credentials.env}"
if [[ -f "$credentials_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$credentials_file"
  set +a
fi

exec "${python_bin}" "${repo_dir}/frontend/server.py" --host 127.0.0.1 --port "${PORT:-8080}" --control
