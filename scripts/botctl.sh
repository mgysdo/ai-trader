#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

START_BTC="$ROOT_DIR/scripts/start_btc_bot.sh"
STOP_BTC="$ROOT_DIR/scripts/stop_btc_bot.sh"
START_EURUSD="$ROOT_DIR/scripts/start_eurusd_bot.sh"
STOP_EURUSD="$ROOT_DIR/scripts/stop_eurusd_bot.sh"

BTC_PID_FILE="$ROOT_DIR/run/btc_bot.pid"
EURUSD_PID_FILE="$ROOT_DIR/run/eurusd_bot.pid"
BTC_LOG_FILE="$ROOT_DIR/logs/btc_bot.log"
EURUSD_LOG_FILE="$ROOT_DIR/logs/eurusd_bot.log"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/botctl.sh <action> <target>

Actions:
  start | stop | restart | status | logs

Targets:
  btc | eurusd | all

Examples:
  ./scripts/botctl.sh start btc
  ./scripts/botctl.sh stop all
  ./scripts/botctl.sh status all
  ./scripts/botctl.sh logs eurusd
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

if [[ $# -ne 2 ]]; then
  usage
  exit 1
fi

ACTION="$1"
TARGET="$2"

case "$ACTION" in
  start)
    case "$TARGET" in
      btc) "$START_BTC" ;;
      eurusd) "$START_EURUSD" ;;
      all) "$START_BTC" && "$START_EURUSD" ;;
      *) usage; exit 1 ;;
    esac
    ;;
  stop)
    case "$TARGET" in
      btc) "$STOP_BTC" ;;
      eurusd) "$STOP_EURUSD" ;;
      all) "$STOP_BTC" && "$STOP_EURUSD" ;;
      *) usage; exit 1 ;;
    esac
    ;;
  restart)
    case "$TARGET" in
      btc) "$STOP_BTC" && "$START_BTC" ;;
      eurusd) "$STOP_EURUSD" && "$START_EURUSD" ;;
      all) "$STOP_BTC" && "$STOP_EURUSD" && "$START_BTC" && "$START_EURUSD" ;;
      *) usage; exit 1 ;;
    esac
    ;;
  status)
    case "$TARGET" in
      btc) status_one "BTC" "$BTC_PID_FILE" "$BTC_LOG_FILE" ;;
      eurusd) status_one "EURUSD" "$EURUSD_PID_FILE" "$EURUSD_LOG_FILE" ;;
      all)
        status_one "BTC" "$BTC_PID_FILE" "$BTC_LOG_FILE"
        status_one "EURUSD" "$EURUSD_PID_FILE" "$EURUSD_LOG_FILE"
        ;;
      *) usage; exit 1 ;;
    esac
    ;;
  logs)
    case "$TARGET" in
      btc) logs_one "$BTC_LOG_FILE" ;;
      eurusd) logs_one "$EURUSD_LOG_FILE" ;;
      all)
        echo "===== BTC ====="
        logs_one "$BTC_LOG_FILE"
        echo "===== EURUSD ====="
        logs_one "$EURUSD_LOG_FILE"
        ;;
      *) usage; exit 1 ;;
    esac
    ;;
  *)
    usage
    exit 1
    ;;
esac