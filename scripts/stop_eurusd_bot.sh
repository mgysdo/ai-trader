#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/run/eurusd_bot.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "EUR/USD bot PID file not found"
  exit 0
fi

PID="$(cat "$PID_FILE")"

if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "EUR/USD bot stopped. PID=$PID"
else
  echo "EUR/USD bot is not running. Removing stale PID file."
fi

rm -f "$PID_FILE"