"""Validation rules PublishSafe defines on top of Pydantic."""

import pytest
from pydantic import ValidationError

from app.schemas import ProcessRequest

VALID_VIDEO_ID = "0123456789abcdef" * 2


def build_request(**overrides):
    payload = {"video_id": VALID_VIDEO_ID, "selected_track_id": 1}
    payload.update(overrides)
    return ProcessRequest(**payload)


@pytest.mark.parametrize(
    "video_id",
    [
        "",
        "not-a-video-id",
        VALID_VIDEO_ID[:31],
        VALID_VIDEO_ID + "a",
        VALID_VIDEO_ID.upper(),
        "../../etc/passwd",
    ],
)
def test_process_request_rejects_video_ids_that_are_not_32_char_lowercase_hex(video_id):
    """video_id is interpolated into filesystem paths, so the shape is enforced."""
    with pytest.raises(ValidationError):
        build_request(video_id=video_id)


def test_process_request_accepts_a_well_formed_video_id():
    assert build_request().video_id == VALID_VIDEO_ID


@pytest.mark.parametrize("blur_strength", [10, 40, 100])
def test_process_request_accepts_blur_strength_inside_the_supported_range(blur_strength):
    assert build_request(blur_strength=blur_strength).blur_strength == blur_strength


@pytest.mark.parametrize("blur_strength", [9, 0, -1, 101, 1000])
def test_process_request_rejects_blur_strength_outside_10_to_100(blur_strength):
    """blur_person clamps internally; the API refuses rather than silently clamping."""
    with pytest.raises(ValidationError):
        build_request(blur_strength=blur_strength)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "cartoon"},
        {"avatar_style": "neon"},
        {"process_scope": "half"},
        {"audio_policy": "copy-if-possible"},
        {"selected_track_id": 0},
        {"selected_track_id": -3},
    ],
)
def test_process_request_rejects_values_outside_the_supported_vocabulary(overrides):
    with pytest.raises(ValidationError):
        build_request(**overrides)


def test_process_request_defaults_match_the_documented_behaviour():
    request = build_request()
    assert (request.mode, request.avatar_style) == ("avatar", "sunny")
    assert (request.blur_strength, request.process_scope) == (40, "full")
    assert request.audio_policy == "remove"


def test_process_request_requires_an_explicit_preserve_policy():
    assert build_request(audio_policy="preserve").audio_policy == "preserve"
