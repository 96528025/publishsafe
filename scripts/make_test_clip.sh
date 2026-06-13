#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "Usage: $0 INPUT_VIDEO [START_SECONDS] [DURATION_SECONDS]"
  exit 1
fi

input="$1"
start="${2:-0}"
duration="${3:-5}"

if [[ ! -f "$input" ]]; then
  echo "Input video not found: $input"
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$project_root/test-clips"
mkdir -p "$output_dir"

filename="$(basename "$input")"
stem="${filename%.*}"
output="$output_dir/${stem}_test_${start}s_${duration}s.mp4"

ffmpeg -y \
  -ss "$start" \
  -i "$input" \
  -t "$duration" \
  -vf "fps=15,scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2" \
  -an \
  -c:v libx264 \
  -preset veryfast \
  -crf 24 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  "$output"

echo "$output"
