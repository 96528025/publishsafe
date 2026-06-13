#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$project_root/samples"
image="$output_dir/ultralytics-bus.jpg"
video="$output_dir/publishsafe-sample.mp4"

mkdir -p "$output_dir"

if [[ ! -f "$image" ]]; then
  echo "Downloading the Ultralytics public sample image..."
  curl -L --fail --show-error \
    https://ultralytics.com/images/bus.jpg \
    -o "$image"
fi

echo "Generating a 6-second sample video..."
ffmpeg -y -loglevel error \
  -loop 1 \
  -i "$image" \
  -t 6 \
  -vf "scale=960:-2,zoompan=z='min(zoom+0.0008,1.08)':d=180:s=960x540:fps=30" \
  -an \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  "$video"

echo "$video"
