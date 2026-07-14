#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

START_BTC="$ROOT_DIR/scripts/start_btc_bot.sh"
STOP_BTC="$ROOT_DIR/scripts/stop_btc_bot.sh"

BTC_PID_FILE="$ROOT_DIR/run/btc_bot.pid"
BTC_LOG_FILE="$ROOT_DIR/logs/btc_bot.log"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/botctl.sh <action>

Actions:
  start | stop | restart | status | logs

Examples:
  ./scripts/botctl.sh start
  ./scripts/botctl.sh status
  ./scripts/botctl.sh logs
EOF
}

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

status_one() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"

  if is_running "$pid_file"; then
    echo "$name: RUNNING (PID $(cat "$pid_file"))"
  else
    echo "$name: STOPPED"
  fi

  if [[ -f "$log_file" ]]; then
    echo "  log: $log_file"
  fi
}

logs_one() {
  local log_file="$1"
  if [[ -f "$log_file" ]]; then
    tail -n 50 "$log_file"
  else
    echo "Log file not found: $log_file"
  fi
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

ACTION="$1"

case "$ACTION" in
  start)   "$START_BTC" ;;
  stop)    "$STOP_BTC" ;;
  restart) "$STOP_BTC" && "$START_BTC" ;;
  status)  status_one "BTC" "$BTC_PID_FILE" "$BTC_LOG_FILE" ;;
  logs)    logs_one "$BTC_LOG_FILE" ;;
  *)
    usage
    exit 1
    ;;
esac
