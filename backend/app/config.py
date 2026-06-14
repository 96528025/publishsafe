import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = PROJECT_ROOT / "uploads"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
AVATAR_DIR = PROJECT_ROOT / "assets" / "avatars"
BYTETRACK_CONFIG = PROJECT_ROOT / "backend" / "bytetrack.yaml"

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
RUNTIME_PROFILE = os.getenv("PUBLISHSAFE_PROFILE", "portable")
INFERENCE_DEVICE = os.getenv("PUBLISHSAFE_DEVICE", "cpu")
VIDEO_ENCODER = os.getenv("PUBLISHSAFE_VIDEO_ENCODER", "libx264")

for directory in (UPLOAD_DIR, OUTPUT_DIR, AVATAR_DIR):
    directory.mkdir(parents=True, exist_ok=True)
