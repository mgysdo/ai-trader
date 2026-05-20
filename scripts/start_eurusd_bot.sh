#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/venv/bin/python"
LOG_DIR="$ROOT_DIR/logs"
PID_DIR="$ROOT_DIR/run"
LOG_FILE="$LOG_DIR/eurusd_bot.log"
PID_FILE="$PID_DIR/eurusd_bot.pid"
SCRIPT_PATH="$ROOT_DIR/eurusd_paper_bot.py"
PROC_PATTERN="$VENV_PYTHON $SCRIPT_PATH"

mkdir -p "$LOG_DIR" "$PID_DIR"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "EUR/USD bot is already running with PID $(cat "$PID_FILE")"
  exit 0
fi

if pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; then
  echo "EUR/USD bot process already exists outside PID tracking:"
  pgrep -af "$PROC_PATTERN"
  echo "Refusing to start a duplicate instance."
  exit 1
fi

cd "$ROOT_DIR"
nohup "$VENV_PYTHON" eurusd_paper_bot.py >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

echo "EUR/USD bot started. PID=$(cat "$PID_FILE")"
echo "Log: $LOG_FILE"