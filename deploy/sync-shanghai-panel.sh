#!/usr/bin/env bash
set -euo pipefail

# Upload only the loopback dashboard/control files to the named Linux node.
# The SSH client prompts for the operator's password; this script never stores
# or forwards exchange credentials. It verifies hashes before replacement.

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
remote_user="${REMOTE_USER:-ubuntu}"
remote_host="${REMOTE_HOST:-111.231.25.250}"
remote_root="${REMOTE_ROOT:-/home/ubuntu/apps/btc-current}"
remote_target="${remote_user}@${remote_host}"
ssh_options=("-o" "ConnectTimeout=10" "-o" "ServerAliveInterval=15" "-o" "ServerAliveCountMax=3")
files=("server.py" "app.js" "index.html" "styles.css")
local_frontend="$repo_root/frontend"
remote_tmp="/tmp/quant-panel-sync-$(date +%s)-$$"

cleanup() {
  ssh "${ssh_options[@]}" "$remote_target" "case \"$remote_tmp\" in /tmp/quant-panel-sync-*) rm -rf -- \"$remote_tmp\" ;; esac" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for file in "${files[@]}"; do
  test -f "$local_frontend/$file" || { echo "missing local file: $file" >&2; exit 2; }
done

echo "[quant] preparing $remote_target:$remote_root"
ssh "${ssh_options[@]}" "$remote_target" "mkdir -m 700 -- \"$remote_tmp\""

for file in "${files[@]}"; do
  scp "${ssh_options[@]}" "$local_frontend/$file" "$remote_target:$remote_tmp/$file"
done

manifest_local="$(mktemp)"
trap 'rm -f -- "$manifest_local"; cleanup' EXIT
for file in "${files[@]}"; do
  (cd "$local_frontend" && sha256sum "$file") >> "$manifest_local"
done
scp "${ssh_options[@]}" "$manifest_local" "$remote_target:$remote_tmp/manifest.sha256"
rm -f -- "$manifest_local"

ssh "${ssh_options[@]}" "$remote_target" "
  set -eu
  cd \"$remote_tmp\"
  sha256sum -c manifest.sha256
  \"$remote_root/.venv/bin/python\" -m py_compile server.py
  install -m 0644 server.py \"$remote_root/frontend/server.py\"
  install -m 0644 app.js \"$remote_root/frontend/app.js\"
  install -m 0644 index.html \"$remote_root/frontend/index.html\"
  install -m 0644 styles.css \"$remote_root/frontend/styles.css\"
  case \"$remote_tmp\" in /tmp/quant-panel-sync-*) rm -rf -- \"$remote_tmp\" ;; esac
  sudo -n systemctl restart quant-local-control-panel.service
  test \"\$(systemctl is-active quant-local-control-panel.service)\" = active
"

echo "[quant] Shanghai panel files verified, installed, and service active"
