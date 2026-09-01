"""API behaviour that does not require a model, real video, or FFmpeg.

The detector is replaced at the module boundary, so these tests cover
PublishSafe's own validation, dispatch, and error handling — not inference.
"""

VALID_VIDEO_ID = "0123456789abcdef" * 2


def authorized(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_reports_loading_until_the_detector_is_constructed(api):
    response = api.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model"] == "yolov8n-seg"
    assert body["device"] == "loading"


def test_health_reports_the_detector_device_once_available(api, stub_detector):
    assert api.get("/api/health").json()["device"] == stub_detector.device


def test_upload_rejects_an_unsupported_extension_without_writing_anything(api, upload_dir):
    response = api.post(
        "/api/upload",
        files={"file": ("notes.txt", b"not a video", "text/plain")},
    )

    assert response.status_code == 415
    assert ".mp4" in response.json()["detail"]
    assert list(upload_dir.iterdir()) == []


def test_upload_rejects_a_video_extension_that_is_not_allowed(api, upload_dir):
    response = api.post(
        "/api/upload",
        files={"file": ("clip.wmv", b"not a video", "video/x-ms-wmv")},
    )

    assert response.status_code == 415
    assert list(upload_dir.iterdir()) == []


def test_process_returns_404_when_the_video_id_has_no_uploaded_file(
    api, stub_detector, video_session
):
    _directory, token = video_session(VALID_VIDEO_ID, with_source=False)
    response = api.post(
        "/api/process",
        json={"video_id": VALID_VIDEO_ID, "selected_track_id": 1},
        headers=authorized(token),
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_process_rejects_a_malformed_request_before_touching_storage(api, stub_detector):
    response = api.post(
        "/api/process",
        json={"video_id": "nope", "selected_track_id": 1, "blur_strength": 999},
    )

    assert response.status_code == 422


def test_process_queues_a_job_and_dispatches_the_background_worker(
    api, stub_detector, video_session, monkeypatch
):
    from app import main

    _directory, token = video_session(VALID_VIDEO_ID)
    calls = []
    monkeypatch.setattr(main, "process_video", lambda *args: calls.append(args))

    response = api.post(
        "/api/process",
        json={
            "video_id": VALID_VIDEO_ID,
            "selected_track_id": 3,
            "mode": "blur",
            "blur_strength": 75,
            "process_scope": "preview",
            "audio_policy": "preserve",
        },
        headers=authorized(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["progress"] == 0
    assert body["output_url"] is None
    assert body["process_scope"] == "preview"
    assert body["audio_policy"] == "preserve"
    assert body["audio_status"] == "pending"
    assert body["conservative_fallback_frames"] == 0

    # The background task ran with the request's parameters, not defaults.
    assert len(calls) == 1
    (
        job_id,
        video_id,
        track_id,
        mode,
        _style,
        strength,
        scope,
        detector,
        policy,
    ) = calls[0]
    assert job_id == body["job_id"]
    assert (video_id, track_id, mode, strength, scope) == (
        VALID_VIDEO_ID,
        3,
        "blur",
        75,
        "preview",
    )
    assert detector is stub_detector
    assert policy == "preserve"


def test_job_status_is_retrievable_after_the_job_is_queued(
    api, stub_detector, video_session, monkeypatch
):
    from app import main

    _directory, token = video_session(VALID_VIDEO_ID)
    monkeypatch.setattr(main, "process_video", lambda *args: None)

    job_id = api.post(
        "/api/process",
        json={"video_id": VALID_VIDEO_ID, "selected_track_id": 1},
        headers=authorized(token),
    ).json()["job_id"]

    status = api.get(f"/api/jobs/{job_id}", headers=authorized(token))
    assert status.status_code == 200
    assert status.json()["job_id"] == job_id


def test_job_status_returns_404_for_an_unknown_job(api, video_session):
    _directory, token = video_session(VALID_VIDEO_ID)
    response = api.get("/api/jobs/does-not-exist", headers=authorized(token))

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_frame_preview_returns_404_when_the_source_video_is_missing(
    api, video_session
):
    _directory, token = video_session(VALID_VIDEO_ID, with_source=False)
    response = api.post(
        "/api/frame-preview",
        json={
            "video_id": VALID_VIDEO_ID,
            "selected_track_id": 1,
            "blur_strength": 40,
            "people": [],
        },
        headers=authorized(token),
    )

    assert response.status_code == 404
