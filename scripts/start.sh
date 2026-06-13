#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi

echo "Starting PublishSafe..."
docker compose up --build -d

echo
echo "PublishSafe is starting at http://localhost:5173"
echo "The first start can take several minutes while dependencies and model weights download."
echo
echo "View logs:  docker compose logs -f"
echo "Stop:       ./scripts/stop.sh"
