"""Private media layout, retention, and safe path resolution."""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from .config import ALLOWED_EXTENSIONS, MEDIA_TTL_SECONDS, OUTPUT_DIR, UPLOAD_DIR

VIDEO_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
EXPIRY_FILENAME = ".expires_at"


def _validated_id(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def upload_session_dir(video_id: str) -> Path:
    return UPLOAD_DIR / _validated_id(video_id, VIDEO_ID_PATTERN, "video id")


def output_session_dir(video_id: str) -> Path:
    return OUTPUT_DIR / _validated_id(video_id, VIDEO_ID_PATTERN, "video id")


def output_job_dir(video_id: str, job_id: str) -> Path:
    return output_session_dir(video_id) / _validated_id(
        job_id, JOB_ID_PATTERN, "job id"
    )


def secure_file(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        path.chmod(0o600)


def _secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError("private storage directory cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def create_upload_session(video_id: str, expires_at: float) -> Path:
    directory = upload_session_dir(video_id)
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    marker = directory / EXPIRY_FILENAME
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        output.write(str(int(expires_at)))
    return directory


def open_private_binary(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def prepare_job_output(video_id: str, job_id: str) -> Path:
    video_directory = output_session_dir(video_id)
    _secure_directory(video_directory)
    job_directory = output_job_dir(video_id, job_id)
    job_directory.mkdir(mode=0o700)
    job_directory.chmod(0o700)
    return job_directory


def find_video(video_id: str) -> Path:
    directory = upload_session_dir(video_id)
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError("Uploaded video was not found")
    matches = [
        directory / f"source{suffix}"
        for suffix in ALLOWED_EXTENSIONS
        if (directory / f"source{suffix}").is_file()
        and not (directory / f"source{suffix}").is_symlink()
    ]
    if len(matches) != 1:
        raise FileNotFoundError("Uploaded video was not found")
    return matches[0]


def session_exists(video_id: str, *, now: float | None = None) -> bool:
    try:
        find_video(video_id)
    except (FileNotFoundError, ValueError):
        return False
    directory = upload_session_dir(video_id)
    return _expiry_for(directory, MEDIA_TTL_SECONDS) > (
        time.time() if now is None else now
    )


def resolve_preview(video_id: str, filename: str) -> Path:
    if filename not in {"detected_preview.jpg", "frame_preview.jpg"}:
        raise FileNotFoundError("Media was not found")
    candidate = upload_session_dir(video_id) / filename
    return _resolved_private_file(candidate, UPLOAD_DIR)


def resolve_output(video_id: str, job_id: str) -> Path:
    candidate = output_job_dir(video_id, job_id) / "output.mp4"
    return _resolved_private_file(candidate, OUTPUT_DIR)


def _resolved_private_file(candidate: Path, root: Path) -> Path:
    if candidate.is_symlink() or not candidate.is_file():
        raise FileNotFoundError("Media was not found")
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise FileNotFoundError("Media was not found")
    return resolved_candidate


def delete_output_job(video_id: str, job_id: str) -> None:
    _remove_path(output_job_dir(video_id, job_id))
    video_directory = output_session_dir(video_id)
    try:
        video_directory.rmdir()
    except (FileNotFoundError, OSError):
        pass


def delete_video_media(video_id: str) -> None:
    _remove_path(upload_session_dir(video_id))
    _remove_path(output_session_dir(video_id))


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _expiry_for(directory: Path, default_ttl_seconds: int) -> float:
    marker = directory / EXPIRY_FILENAME
    if not marker.exists():
        return directory.stat().st_mtime + default_ttl_seconds
    try:
        return float(marker.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        # A corrupt marker never extends the lifetime of private media.
        return 0


def tighten_existing_permissions() -> None:
    for root in (UPLOAD_DIR, OUTPUT_DIR):
        _secure_directory(root)
        for path in root.rglob("*"):
            if path.is_symlink():
                continue
            try:
                path.chmod(0o700 if path.is_dir() else 0o600)
            except FileNotFoundError:
                continue


def cleanup_expired_media(
    *,
    now: float | None = None,
    default_ttl_seconds: int = MEDIA_TTL_SECONDS,
    preserve_video_ids: set[str] | None = None,
) -> set[str]:
    """Delete expired sessions and inaccessible orphan outputs.

    Returns the video IDs removed so the in-memory job registry can be pruned.
    Legacy flat files are also aged out; they are never exposed by the API.
    """

    current_time = time.time() if now is None else now
    preserve = preserve_video_ids or set()
    removed: set[str] = set()

    for entry in list(UPLOAD_DIR.iterdir()):
        if entry.name == ".gitkeep":
            continue
        if entry.is_dir() and VIDEO_ID_PATTERN.fullmatch(entry.name):
            if entry.name in preserve:
                continue
            if _expiry_for(entry, default_ttl_seconds) <= current_time:
                delete_video_media(entry.name)
                removed.add(entry.name)
        elif entry.stat().st_mtime + default_ttl_seconds <= current_time:
            _remove_path(entry)

    active_sessions = {
        entry.name
        for entry in UPLOAD_DIR.iterdir()
        if entry.is_dir() and VIDEO_ID_PATTERN.fullmatch(entry.name)
    }
    for entry in list(OUTPUT_DIR.iterdir()):
        if entry.name == ".gitkeep":
            continue
        if entry.is_dir() and VIDEO_ID_PATTERN.fullmatch(entry.name):
            if entry.name in preserve:
                continue
            if entry.name not in active_sessions:
                _remove_path(entry)
                removed.add(entry.name)
        elif entry.stat().st_mtime + default_ttl_seconds <= current_time:
            _remove_path(entry)

    return removed
