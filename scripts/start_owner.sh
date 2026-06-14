#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
owner_file="$project_root/.publishsafe-owner-machine"
cd "$project_root"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "Owner mode requires this project's Apple Silicon Mac."
  exit 1
fi

if [[ ! -f "$owner_file" ]]; then
  echo "Owner mode is not configured on this computer."
  echo "Use the portable version instead: ./scripts/start.sh"
  exit 1
fi

platform_uuid="$(ioreg -rd1 -c IOPlatformExpertDevice | awk -F\\\" '/IOPlatformUUID/{print $(NF-1)}')"
machine_fingerprint="$(
  printf '%s' "${platform_uuid}|$(sysctl -n hw.model)|$(sysctl -n hw.memsize)" \
    | shasum -a 256 \
    | awk '{print $1}'
)"
expected_fingerprint="$(tr -d '[:space:]' < "$owner_file")"

if [[ "$machine_fingerprint" != "$expected_fingerprint" ]]; then
  echo "Owner mode is configured for a different computer."
  echo "Use the portable version instead: ./scripts/start.sh"
  exit 1
fi

for command in ffmpeg npm; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Owner mode requires '$command'."
    exit 1
  fi
done

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Owner mode requires the local Python environment at .venv/."
  echo "Create it using the source-install instructions in README.md."
  exit 1
fi

if ! .venv/bin/python -c \
  "import torch; raise SystemExit(0 if torch.backends.mps.is_available() else 1)"
then
  echo "Apple GPU acceleration (MPS) is unavailable in the current Python environment."
  exit 1
fi

if ! ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_videotoolbox; then
  echo "FFmpeg does not provide h264_videotoolbox on this computer."
  exit 1
fi

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8000 is already in use. Stop the existing backend first."
  exit 1
fi
if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 5173 is already in use. Stop the existing frontend first."
  exit 1
fi

backend_pid=""
frontend_pid=""

cleanup() {
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true
  wait "$frontend_pid" "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

export PUBLISHSAFE_PROFILE="owner-m2"
export PUBLISHSAFE_DEVICE="mps"
export PUBLISHSAFE_VIDEO_ENCODER="h264_videotoolbox"

echo "Starting PublishSafe Owner mode..."
echo "Inference: Apple GPU (MPS)"
echo "Encoding:  Apple VideoToolbox"

.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

(
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 5173
) &
frontend_pid=$!

echo
echo "PublishSafe Owner mode is starting at http://localhost:5173"
echo "Press Ctrl+C to stop both services."

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done
