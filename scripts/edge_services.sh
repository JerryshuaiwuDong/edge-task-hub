#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/edge_services.sh status [all|hub|openclaw|scheduler|ollama]
  scripts/edge_services.sh start  [all|hub|openclaw|scheduler|ollama]
  scripts/edge_services.sh stop   [all|hub|openclaw|scheduler|ollama]

Default target is all. OpenClaw and the Node scheduler are user services.
Ollama is a system service and may require sudo.
USAGE
}

action="${1:-status}"
target="${2:-all}"

user_service() {
  if [[ "$action" == "status" ]]; then
    systemctl --user --no-pager status "$1" || true
    return 0
  fi
  systemctl --user "$action" "$1"
}

system_service() {
  if [[ "$action" == "status" ]]; then
    systemctl --no-pager status "$1" || true
    return 0
  fi
  if systemctl "$action" "$1" 2>/dev/null; then
    return 0
  fi
  sudo -n systemctl "$action" "$1"
}

run_target() {
  case "$1" in
    hub)
      user_service edge-task-hub.service
      ;;
    openclaw)
      user_service openclaw-gateway.service
      ;;
    scheduler)
      user_service pi-automation-scheduler.service
      ;;
    ollama)
      system_service ollama.service
      ;;
    all)
      user_service edge-task-hub.service
      user_service openclaw-gateway.service
      user_service pi-automation-scheduler.service
      system_service ollama.service
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

case "$action" in
  start|stop|status|restart)
    run_target "$target"
    ;;
  *)
    usage
    exit 2
    ;;
esac
