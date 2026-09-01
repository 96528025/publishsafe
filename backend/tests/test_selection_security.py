"""Server-owned creator selection and preview fail-closed boundaries."""

from pathlib import Path

from app.storage import PREVIEW_MANIFEST_FILENAME


VIDEO_ID = "d" * 32


def authorized(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def preview_request(api, token: str, **overrides):
    payload = {
        "video_id": VIDEO_ID,
        "selected_track_id": 1,
        "blur_strength": 40,
    }
    payload.update(overrides)
    return api.post(
        "/api/frame-preview",
        json=payload,
        headers=authorized(token),
    )


def test_frame_preview_uses_server_manifest_not_client_geometry(
    api, video_session, monkeypatch
):
    from app import main

    people = [
        {"track_id": 1, "bbox": [10, 10, 50, 100], "confidence": 0.95},
        {"track_id": 2, "bbox": [80, 10, 130, 100], "confidence": 0.91},
    ]
    directory, token = video_session(VIDEO_ID, people=people)
    blurred = []
    monkeypatch.setattr(
        main,
        "blur_person",
        lambda frame, bbox, strength, mask: blurred.append((bbox, strength)),
    )

    response = preview_request(api, token)

    assert response.status_code == 200
    assert blurred == [((80, 10, 130, 100), 40)]
    assert (directory / "frame_preview.jpg").is_file()


def test_frame_preview_forbids_client_supplied_people_and_bbox_spoofing(
    api, video_session
):
    directory, token = video_session(VIDEO_ID)

    response = preview_request(
        api,
        token,
        people=[
            {
                "track_id": 1,
                "bbox": [0, 0, 1, 1],
                "confidence": 1.0,
            }
        ],
    )

    assert response.status_code == 422
    assert not (directory / "frame_preview.jpg").exists()


def test_frame_preview_rejects_missing_empty_or_corrupt_server_manifest(
    api, video_session
):
    cases: list[tuple[str, Path]] = []

    missing_directory, missing_token = video_session(VIDEO_ID, with_preview=False)
    missing = preview_request(api, missing_token)
    cases.append(("missing", missing_directory))

    # Each case uses the same ID only after removing the prior session through
    # the API, matching the fixture's one-session storage contract.
    api.delete(f"/api/videos/{VIDEO_ID}", headers=authorized(missing_token))
    empty_directory, empty_token = video_session(VIDEO_ID, people=[])
    empty = preview_request(api, empty_token)
    cases.append(("empty", empty_directory))

    api.delete(f"/api/videos/{VIDEO_ID}", headers=authorized(empty_token))
    corrupt_directory, corrupt_token = video_session(VIDEO_ID)
    (corrupt_directory / PREVIEW_MANIFEST_FILENAME).write_text(
        "not-json", encoding="utf-8"
    )
    corrupt = preview_request(api, corrupt_token)
    cases.append(("corrupt", corrupt_directory))

    assert [missing.status_code, empty.status_code, corrupt.status_code] == [409, 409, 409]
    assert all(not (directory / "frame_preview.jpg").exists() for _, directory in cases)


def test_frame_preview_rejects_track_not_in_server_manifest(api, video_session):
    directory, token = video_session(VIDEO_ID)

    response = preview_request(api, token, selected_track_id=999)

    assert response.status_code == 409
    assert "not present" in response.json()["detail"]
    assert not (directory / "frame_preview.jpg").exists()

