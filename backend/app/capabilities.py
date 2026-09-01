"""Small, dependency-free HMAC capabilities for private local media.

Session capabilities authorize API operations for exactly one uploaded video.
Media capabilities authorize one short-lived preview or processed output. Raw
uploads are intentionally not part of the media artifact vocabulary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any, Literal

from .config import CAPABILITY_SECRET

VIDEO_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MEDIA_ARTIFACTS = frozenset({"detected-preview", "frame-preview", "output"})
MAX_TOKEN_LENGTH = 4096


class CapabilityError(ValueError):
    """Raised when a capability is missing, invalid, expired, or mis-scoped."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _encode(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    body = _b64encode(serialized)
    signature = _b64encode(
        hmac.new(CAPABILITY_SECRET, body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _issue(
    capability_type: Literal["session", "media"],
    video_id: str,
    ttl_seconds: int,
    *,
    now: float | None = None,
    artifact: str | None = None,
    job_id: str | None = None,
) -> str:
    if not VIDEO_ID_PATTERN.fullmatch(video_id):
        raise ValueError("invalid video id")
    if ttl_seconds < 1:
        raise ValueError("capability TTL must be positive")
    if capability_type == "media" and artifact not in MEDIA_ARTIFACTS:
        raise ValueError("invalid media artifact")
    if artifact == "output" and not (job_id and JOB_ID_PATTERN.fullmatch(job_id)):
        raise ValueError("output capabilities require a valid job id")
    if artifact != "output" and job_id is not None:
        raise ValueError("job id is only valid for output capabilities")

    issued_at = int(time.time() if now is None else now)
    payload: dict[str, Any] = {
        "v": 1,
        "type": capability_type,
        "video_id": video_id,
        "exp": issued_at + ttl_seconds,
        "nonce": secrets.token_urlsafe(8),
    }
    if artifact is not None:
        payload["artifact"] = artifact
    if job_id is not None:
        payload["job_id"] = job_id
    return _encode(payload)


def issue_session_capability(
    video_id: str, ttl_seconds: int, *, now: float | None = None
) -> str:
    return _issue("session", video_id, ttl_seconds, now=now)


def issue_media_capability(
    video_id: str,
    artifact: Literal["detected-preview", "frame-preview", "output"],
    ttl_seconds: int,
    *,
    job_id: str | None = None,
    now: float | None = None,
) -> str:
    return _issue(
        "media",
        video_id,
        ttl_seconds,
        now=now,
        artifact=artifact,
        job_id=job_id,
    )


def verify_capability(
    token: str,
    expected_type: Literal["session", "media"],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    if not token or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 1:
        raise CapabilityError("invalid capability")
    body, encoded_signature = token.split(".", 1)
    try:
        supplied_signature = _b64decode(encoded_signature)
        expected_signature = hmac.new(
            CAPABILITY_SECRET, body.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise CapabilityError("invalid capability")
        payload = json.loads(_b64decode(body))
    except (CapabilityError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise CapabilityError("invalid capability") from exc

    if not isinstance(payload, dict):
        raise CapabilityError("invalid capability")
    if payload.get("v") != 1 or payload.get("type") != expected_type:
        raise CapabilityError("invalid capability")
    video_id = payload.get("video_id")
    expires_at = payload.get("exp")
    if not isinstance(video_id, str) or not VIDEO_ID_PATTERN.fullmatch(video_id):
        raise CapabilityError("invalid capability")
    if type(expires_at) is not int:
        raise CapabilityError("invalid capability")
    current_time = int(time.time() if now is None else now)
    if current_time >= expires_at:
        raise CapabilityError("expired capability")

    if expected_type == "media":
        artifact = payload.get("artifact")
        if artifact not in MEDIA_ARTIFACTS:
            raise CapabilityError("invalid capability")
        job_id = payload.get("job_id")
        if artifact == "output":
            if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
                raise CapabilityError("invalid capability")
        elif job_id is not None:
            raise CapabilityError("invalid capability")
    return payload
