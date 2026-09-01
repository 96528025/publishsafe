import os
import secrets
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _storage_dir(env_var: str, default: Path) -> Path:
    # Overridable so tests can redirect writes away from the real media folders.
    override = os.getenv(env_var)
    return Path(override).expanduser().resolve() if override else default


def _positive_int(env_var: str, default: int) -> int:
    raw_value = os.getenv(env_var)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{env_var} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{env_var} must be positive")
    return value


UPLOAD_DIR = _storage_dir("PUBLISHSAFE_UPLOAD_DIR", PROJECT_ROOT / "uploads")
OUTPUT_DIR = _storage_dir("PUBLISHSAFE_OUTPUT_DIR", PROJECT_ROOT / "outputs")
AVATAR_DIR = _storage_dir("PUBLISHSAFE_AVATAR_DIR", PROJECT_ROOT / "assets" / "avatars")
BYTETRACK_CONFIG = PROJECT_ROOT / "backend" / "bytetrack.yaml"

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
RUNTIME_PROFILE = os.getenv("PUBLISHSAFE_PROFILE", "portable")
INFERENCE_DEVICE = os.getenv("PUBLISHSAFE_DEVICE", "cpu")
VIDEO_ENCODER = os.getenv("PUBLISHSAFE_VIDEO_ENCODER", "libx264")
MEDIA_TTL_SECONDS = _positive_int("PUBLISHSAFE_MEDIA_TTL_SECONDS", 24 * 60 * 60)
MEDIA_CAPABILITY_TTL_SECONDS = _positive_int(
    "PUBLISHSAFE_MEDIA_CAPABILITY_TTL_SECONDS", 5 * 60
)
CLEANUP_INTERVAL_SECONDS = _positive_int(
    "PUBLISHSAFE_CLEANUP_INTERVAL_SECONDS", 5 * 60
)

# A configured secret keeps capabilities valid across a process restart. The
# local default is deliberately ephemeral: restarting the backend revokes every
# previously issued URL instead of shipping a shared development secret.
_configured_secret = os.getenv("PUBLISHSAFE_CAPABILITY_SECRET")
if _configured_secret is not None and len(_configured_secret.encode("utf-8")) < 32:
    raise RuntimeError("PUBLISHSAFE_CAPABILITY_SECRET must be at least 32 bytes")
CAPABILITY_SECRET = (
    _configured_secret.encode("utf-8")
    if _configured_secret
    else secrets.token_bytes(32)
)

for directory in (UPLOAD_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)

AVATAR_DIR.mkdir(parents=True, exist_ok=True)
