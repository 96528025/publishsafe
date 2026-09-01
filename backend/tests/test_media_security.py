"""Security boundaries for private uploads, derived media, and retention."""

import logging
import stat
import time

import pytest

from app.capabilities import issue_media_capability, issue_session_capability
from app.config import MEDIA_CAPABILITY_TTL_SECONDS
from app.storage import (
    cleanup_expired_media,
    create_upload_session,
    find_video,
    prepare_job_output,
)

VIDEO_A = "a" * 32
VIDEO_B = "b" * 32
JOB_ID = "c" * 32


def authorized(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_video_specific_api_operations_reject_a_bare_uuid(
    api, stub_detector, video_session
):
    video_session(VIDEO_A)

    process = api.post(
        "/api/process",
        json={"video_id": VIDEO_A, "selected_track_id": 1},
    )
    frame = api.post(
        "/api/frame-preview",
        json={
            "video_id": VIDEO_A,
            "selected_track_id": 1,
        },
    )
    job = api.get(f"/api/jobs/{JOB_ID}")
    delete = api.delete(f"/api/videos/{VIDEO_A}")

    assert (process.status_code, frame.status_code) == (401, 401)
    assert (job.status_code, delete.status_code) == (401, 401)


def test_session_capability_is_scoped_to_one_video(api, video_session):
    _directory_a, token_a = video_session(VIDEO_A)
    video_session(VIDEO_B)

    response = api.delete(
        f"/api/videos/{VIDEO_B}", headers=authorized(token_a)
    )

    assert response.status_code == 403


def test_expired_session_capability_is_rejected(
    api, stub_detector, video_session
):
    video_session(VIDEO_A)
    expired = issue_session_capability(
        VIDEO_A,
        1,
        now=time.time() - 10,
    )

    response = api.post(
        "/api/process",
        json={"video_id": VIDEO_A, "selected_track_id": 1},
        headers=authorized(expired),
    )

    assert response.status_code == 401


def test_short_lived_media_capability_controls_preview_and_disables_caching(
    api, video_session
):
    directory, _token = video_session(VIDEO_A)
    preview = directory / "detected_preview.jpg"
    preview.write_bytes(b"private preview")
    preview.chmod(0o600)
    capability = issue_media_capability(
        VIDEO_A, "detected-preview", MEDIA_CAPABILITY_TTL_SECONDS
    )

    response = api.get(f"/api/media/{capability}")

    assert response.status_code == 200
    assert response.content == b"private preview"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_preview_capability_can_be_refreshed_only_with_the_session_capability(
    api, video_session
):
    directory, token = video_session(VIDEO_A)
    preview = directory / "detected_preview.jpg"
    preview.write_bytes(b"preview")
    preview.chmod(0o600)

    unauthenticated = api.get(
        f"/api/videos/{VIDEO_A}/preview-capability?variant=detected"
    )
    invalid_variant = api.get(
        f"/api/videos/{VIDEO_A}/preview-capability?variant=source",
        headers=authorized(token),
    )
    refreshed = api.get(
        f"/api/videos/{VIDEO_A}/preview-capability?variant=detected",
        headers=authorized(token),
    )

    assert unauthenticated.status_code == 401
    assert invalid_variant.status_code == 422
    assert refreshed.status_code == 200
    refreshed_url = refreshed.json()["preview_url"]
    assert refreshed_url.startswith("/api/media/")
    assert api.get(refreshed_url).content == b"preview"


def test_expired_media_capability_is_rejected(api, video_session):
    directory, _token = video_session(VIDEO_A)
    (directory / "detected_preview.jpg").write_bytes(b"private preview")
    expired = issue_media_capability(
        VIDEO_A,
        "detected-preview",
        1,
        now=time.time() - 10,
    )

    response = api.get(f"/api/media/{expired}")

    assert response.status_code == 401


def test_raw_original_and_legacy_static_paths_are_never_served(api, video_session):
    directory, _token = video_session(VIDEO_A)
    source = directory / "source.mp4"

    assert source.exists()
    assert api.get(f"/uploads/{VIDEO_A}/source.mp4").status_code == 404
    assert api.get(f"/outputs/{VIDEO_A}/{JOB_ID}/output.mp4").status_code == 404
    with pytest.raises(ValueError):
        issue_media_capability(
            VIDEO_A,
            "source",  # type: ignore[arg-type]
            MEDIA_CAPABILITY_TTL_SECONDS,
        )


def test_find_video_accepts_only_the_exact_private_source_name(video_session):
    directory, _token = video_session(VIDEO_A, with_source=False)
    (directory / "detected_preview.mp4").write_bytes(b"not an original")

    with pytest.raises(FileNotFoundError):
        find_video(VIDEO_A)


def test_delete_now_removes_all_media_and_revokes_derived_urls(
    api, video_session
):
    directory, token = video_session(VIDEO_A)
    preview = directory / "detected_preview.jpg"
    preview.write_bytes(b"preview")
    preview.chmod(0o600)
    output_directory = prepare_job_output(VIDEO_A, JOB_ID)
    output = output_directory / "output.mp4"
    output.write_bytes(b"processed")
    output.chmod(0o600)
    preview_capability = issue_media_capability(
        VIDEO_A, "detected-preview", MEDIA_CAPABILITY_TTL_SECONDS
    )
    output_capability = issue_media_capability(
        VIDEO_A,
        "output",
        MEDIA_CAPABILITY_TTL_SECONDS,
        job_id=JOB_ID,
    )

    deleted = api.delete(
        f"/api/videos/{VIDEO_A}", headers=authorized(token)
    )

    assert deleted.status_code == 204
    assert not directory.exists()
    assert not output_directory.exists()
    assert api.get(f"/api/media/{preview_capability}").status_code == 404
    assert api.get(f"/api/media/{output_capability}").status_code == 404


def test_ttl_cleanup_removes_expired_uploads_and_outputs_but_keeps_fresh_media(
    upload_dir, output_dir
):
    expired_directory = create_upload_session(VIDEO_A, expires_at=100)
    (expired_directory / "source.mp4").write_bytes(b"expired")
    expired_output = prepare_job_output(VIDEO_A, JOB_ID)
    (expired_output / "output.mp4").write_bytes(b"expired")

    fresh_directory = create_upload_session(VIDEO_B, expires_at=1_000)
    (fresh_directory / "source.mp4").write_bytes(b"fresh")

    removed = cleanup_expired_media(now=200, default_ttl_seconds=10)

    assert removed == {VIDEO_A}
    assert not (upload_dir / VIDEO_A).exists()
    assert not (output_dir / VIDEO_A).exists()
    assert (upload_dir / VIDEO_B / "source.mp4").exists()


def test_media_resolver_rejects_symlink_and_path_traversal_attempts(
    api, video_session, tmp_path
):
    directory, _token = video_session(VIDEO_A)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"must not leak")
    (directory / "detected_preview.jpg").symlink_to(outside)
    capability = issue_media_capability(
        VIDEO_A, "detected-preview", MEDIA_CAPABILITY_TTL_SECONDS
    )

    symlink_response = api.get(f"/api/media/{capability}")
    traversal_response = api.get("/api/media/..%2F..%2Fetc%2Fpasswd")

    assert symlink_response.status_code == 404
    assert traversal_response.status_code in {401, 404}
    assert b"must not leak" not in symlink_response.content


def test_private_storage_permissions_are_owner_only(video_session):
    directory, _token = video_session(VIDEO_A)
    source = directory / "source.mp4"

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(source.stat().st_mode) == 0o600


def test_job_status_returns_a_controlled_output_capability(
    api, video_session
):
    from app.processor import create_job, jobs, jobs_lock

    _directory, token = video_session(VIDEO_A)
    job_id = create_job(VIDEO_A, "full")
    output_directory = prepare_job_output(VIDEO_A, job_id)
    output = output_directory / "output.mp4"
    output.write_bytes(b"finished video")
    output.chmod(0o600)
    with jobs_lock:
        jobs[job_id].update(
            status="complete",
            progress=100,
            message="ready",
            output_ready=True,
        )

    status_response = api.get(
        f"/api/jobs/{job_id}", headers=authorized(token)
    )
    output_url = status_response.json()["output_url"]
    media_response = api.get(output_url)
    download_response = api.get(f"{output_url}?download=1")

    assert status_response.status_code == 200
    assert output_url.startswith("/api/media/")
    assert "/outputs/" not in output_url
    assert media_response.status_code == 200
    assert media_response.content == b"finished video"
    assert media_response.headers["cache-control"].startswith("private, no-store")
    assert "content-disposition" not in media_response.headers
    disposition = download_response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "publishsafe-output.mp4" in disposition
    assert output_url.rsplit("/", 1)[-1] not in disposition


def test_media_url_is_revoked_when_session_ttl_elapses(
    api, video_session, monkeypatch
):
    from app import storage

    directory, _token = video_session(VIDEO_A)
    (directory / "detected_preview.jpg").write_bytes(b"preview")
    capability = issue_media_capability(
        VIDEO_A, "detected-preview", MEDIA_CAPABILITY_TTL_SECONDS
    )
    monkeypatch.setattr(storage, "_expiry_for", lambda *_args: time.time() - 1)

    response = api.get(f"/api/media/{capability}")

    assert response.status_code == 404


def test_failed_upload_analysis_removes_the_entire_private_session(
    api, upload_dir, monkeypatch
):
    from app import main

    class UnreadableCapture:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(main.cv2, "VideoCapture", lambda _path: UnreadableCapture())

    response = api.post(
        "/api/upload",
        files={"file": ("clip.mp4", b"not really a video", "video/mp4")},
    )

    assert response.status_code == 422
    assert list(upload_dir.iterdir()) == []


def test_failed_processing_removes_partial_job_output(
    video_session, output_dir, stub_detector, monkeypatch
):
    from app import processor

    class OpenCapture:
        def isOpened(self):
            return True

        def get(self, property_id):
            values = {
                processor.cv2.CAP_PROP_FPS: 30,
                processor.cv2.CAP_PROP_FRAME_WIDTH: 640,
                processor.cv2.CAP_PROP_FRAME_HEIGHT: 480,
                processor.cv2.CAP_PROP_FRAME_COUNT: 30,
            }
            return values.get(property_id, 0)

        def release(self):
            pass

    class FailedWriter:
        def isOpened(self):
            return False

        def release(self):
            pass

    video_session(VIDEO_A)
    job_id = processor.create_job(VIDEO_A)
    monkeypatch.setattr(processor.cv2, "VideoCapture", lambda _path: OpenCapture())
    monkeypatch.setattr(processor.cv2, "VideoWriter", lambda *_args: FailedWriter())

    processor.process_video(
        job_id,
        VIDEO_A,
        1,
        "blur",
        "sunny",
        40,
        "full",
        stub_detector,
    )

    assert processor.jobs[job_id]["status"] == "failed"
    assert not (output_dir / VIDEO_A).exists()


def test_access_log_filter_redacts_media_capabilities():
    from app.main import CapabilityAccessLogFilter

    secret = "signed.payload"
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", f"/api/media/{secret}", "1.1", 200),
        None,
    )

    assert CapabilityAccessLogFilter().filter(record)
    assert secret not in record.getMessage()
    assert "/api/media/[REDACTED]" in record.getMessage()
