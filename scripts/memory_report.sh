#!/usr/bin/env bash
set -euo pipefail

run_optional() {
  local label="$1"
  shift
  echo
  echo "## ${label}"
  if ! "$@"; then
    echo "(command failed: $*)"
  fi
}

echo "# EdgeAI Memory Report"
date --iso-8601=seconds
hostnamectl 2>/dev/null | sed -n '1,8p' || hostname
uname -a

run_optional "Memory" free -h
run_optional "Disk" df -h / /home/pi3

run_optional "Top Processes By RSS" sh -c \
  "ps -eo pid,ppid,user,stat,%mem,%cpu,rss,comm,args --sort=-rss | head -n 25"

run_optional "Process RSS Aggregated" sh -c \
  "ps -eo comm,rss --no-headers | awk '{a[\$1]+=\$2} END {for (k in a) printf \"%8.1f MiB  %s\\n\", a[k]/1024, k}' | sort -nr | head -n 25"

run_optional "User Services" systemctl --user --no-pager --type=service --state=running
run_optional "System Services" sh -c \
  "systemctl --no-pager --type=service --state=running | sed -n '1,80p'"

run_optional "Edge Services Status" sh -c \
  "systemctl --user --no-pager status edge-task-hub.service openclaw-gateway.service pi-automation-scheduler.service 2>/dev/null | sed -n '1,180p'"

run_optional "Ollama Status" sh -c \
  "systemctl --no-pager status ollama.service 2>/dev/null | sed -n '1,80p'"

run_optional "Listening TCP Ports" sh -c \
  "ss -ltnp 2>/dev/null | sed -n '1,100p'"

run_optional "Ollama Loaded Models" sh -c \
  "timeout 8s ollama ps 2>/dev/null || true"
