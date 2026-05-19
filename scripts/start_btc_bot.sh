#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/venv/bin/python"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"
LOG_FILE="$LOG_DIR/btc_bot.log"
PID_FILE="$PID_DIR/btc_bot.pid"

mkdir -p "$LOG_DIR" "$PID_DIR"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "BTC bot is already running with PID $(cat "$PID_FILE")"
  exit 0
fi

cd "$ROOT_DIR"
nohup "$VENV_PYTHON" main.py >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

echo "BTC bot started. PID=$(cat "$PID_FILE")"
echo "Log: $LOG_FILE"