#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/run/btc_bot.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "BTC bot PID file not found"
  exit 0
fi

PID="$(cat "$PID_FILE")"

if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "BTC bot stopped. PID=$PID"
else
  echo "BTC bot is not running. Removing stale PID file."
fi

rm -f "$PID_FILE"