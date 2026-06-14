#!/usr/bin/env bash
set -euo pipefail

stopped=0
for port in 5173 8000; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill $pids
    stopped=1
  fi
done

if [[ "$stopped" -eq 1 ]]; then
  echo "PublishSafe Owner services stopped."
else
  echo "No PublishSafe Owner services were running."
fi
