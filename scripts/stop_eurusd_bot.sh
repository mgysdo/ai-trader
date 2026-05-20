#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/run/eurusd_bot.pid"
VENV_PYTHON="$ROOT_DIR/venv/bin/python"
SCRIPT_PATH="$ROOT_DIR/eurusd_paper_bot.py"
PROC_PATTERN="$VENV_PYTHON $SCRIPT_PATH"

stopped_any=false

if [[ ! -f "$PID_FILE" ]]; then
  echo "EUR/USD bot PID file not found; checking running processes by pattern."
else
  PID="$(cat "$PID_FILE")"

  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "EUR/USD bot stopped. PID=$PID"
    stopped_any=true
  else
    echo "EUR/USD bot is not running for PID file entry. Removing stale PID file."
  fi
fi

rm -f "$PID_FILE"

mapfile -t EXTRA_PIDS < <(pgrep -f "$PROC_PATTERN" || true)
for extra_pid in "${EXTRA_PIDS[@]}"; do
  if kill -0 "$extra_pid" 2>/dev/null; then
    kill "$extra_pid"
    echo "EUR/USD bot stopped (pattern match). PID=$extra_pid"
    stopped_any=true
  fi
done

if [[ "$stopped_any" = false ]]; then
  echo "No running EUR/USD bot process found."
fi