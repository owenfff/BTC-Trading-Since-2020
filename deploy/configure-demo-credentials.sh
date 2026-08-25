#!/usr/bin/env bash
set -euo pipefail

# Configure exactly one non-production venue locally. Credentials never pass
# through the dashboard, repository, Git, or command-line arguments.
umask 077

venue="${1:-}"
case "$venue" in
  okx-demo|binance-spot-testnet|binance-futures-testnet) ;;
  *)
    echo "usage: $0 okx-demo|binance-spot-testnet|binance-futures-testnet" >&2
    exit 2
    ;;
esac

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/quant-bot"
env_file="$config_dir/credentials.env"
mkdir -p "$config_dir"
chmod 700 "$config_dir"

read_secret() {
  local prompt="$1"
  local value
  read -r -s -p "$prompt" value
  printf '\n' >&2
  printf '%s' "$value"
}

api_key=""
api_secret=""
passphrase=""
case "$venue" in
  okx-demo)
    read -r -p "OKX Demo API key: " api_key
    printf '\n' >&2
    api_secret="$(read_secret 'OKX Demo API secret: ')"
    passphrase="$(read_secret 'OKX Demo passphrase: ')"
    ;;
  binance-spot-testnet)
    read -r -p "Binance Spot Testnet API key: " api_key
    printf '\n' >&2
    api_secret="$(read_secret 'Binance Spot Testnet API secret: ')"
    ;;
  binance-futures-testnet)
    read -r -p "Binance Futures Testnet API key: " api_key
    printf '\n' >&2
    api_secret="$(read_secret 'Binance Futures Testnet API secret: ')"
    ;;
esac

tmp_file="$(mktemp "$config_dir/credentials.env.tmp.XXXXXX")"
trap 'rm -f "$tmp_file"' EXIT
{
  printf '%s\n' '# Local Demo/Testnet credentials. This file must remain mode 600.'
  case "$venue" in
    okx-demo)
      printf 'OKX_DEMO_API_KEY=%q\n' "$api_key"
      printf 'OKX_DEMO_API_SECRET=%q\n' "$api_secret"
      printf 'OKX_DEMO_API_PASSPHRASE=%q\n' "$passphrase"
      ;;
    binance-spot-testnet)
      printf 'BINANCE_TESTNET_API_KEY=%q\n' "$api_key"
      printf 'BINANCE_TESTNET_API_SECRET=%q\n' "$api_secret"
      ;;
    binance-futures-testnet)
      printf 'BINANCE_FUTURES_TESTNET_API_KEY=%q\n' "$api_key"
      printf 'BINANCE_FUTURES_TESTNET_API_SECRET=%q\n' "$api_secret"
      ;;
  esac
} > "$tmp_file"
chmod 600 "$tmp_file"
mv -f "$tmp_file" "$env_file"
trap - EXIT

echo "Saved one local $venue credential set to $env_file (mode 600)."
echo "Restart the local control panel service before starting the venue:"
echo "  sudo systemctl restart quant-local-control-panel.service"
