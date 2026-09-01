"""Frame-level privacy helpers, exercised with small NumPy arrays only."""

import cv2
import numpy as np
import pytest

from app.vision import appearance_distance, appearance_histogram, blur_person


def noisy_frame(height: int = 120, width: int = 160) -> np.ndarray:
    """Uniform frames survive blurring unchanged, so use deterministic noise."""
    rng = np.random.default_rng(seed=7)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def test_blur_person_clamps_a_bbox_that_extends_past_every_frame_edge():
    frame = noisy_frame()
    original = frame.copy()

    blur_person(frame, (-40, -30, 400, 300), strength=40)

    assert frame.shape == original.shape
    assert not np.array_equal(frame, original)


def test_blur_person_leaves_the_frame_untouched_for_a_degenerate_bbox():
    """A box clamped down to zero area must be a no-op, not a crash."""
    frame = noisy_frame()
    original = frame.copy()

    blur_person(frame, (500, 500, 520, 520), strength=40)

    assert np.array_equal(frame, original)


def test_blur_person_without_a_mask_uses_the_padded_bbox():
    frame = noisy_frame()
    original = frame.copy()

    blur_person(frame, (40, 30, 120, 90), strength=60, mask=None)

    assert not np.array_equal(frame[30:90, 40:120], original[30:90, 40:120])
    assert np.array_equal(frame[:20, :20], original[:20, :20])


def test_blur_person_with_an_empty_mask_falls_back_to_the_padded_bbox():
    frame = noisy_frame()
    original = frame.copy()
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)

    blur_person(frame, (40, 30, 120, 90), strength=60, mask=mask)

    assert not np.array_equal(frame[30:90, 40:120], original[30:90, 40:120])
    assert np.array_equal(frame[:20, :20], original[:20, :20])


def test_blur_person_with_a_too_small_mask_falls_back_to_the_padded_bbox():
    frame = noisy_frame()
    original = frame.copy()
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    mask[60, 80] = 1

    blur_person(frame, (40, 30, 120, 90), strength=60, mask=mask)

    assert not np.array_equal(frame[30:90, 40:120], original[30:90, 40:120])
    assert np.array_equal(frame[:20, :20], original[:20, :20])


def test_blur_person_with_a_malformed_mask_falls_back_to_the_padded_bbox():
    frame = noisy_frame()
    original = frame.copy()
    malformed_mask = np.ones((12, 12, 2), dtype=np.uint8)

    blur_person(frame, (40, 30, 120, 90), strength=40, mask=malformed_mask)

    assert not np.array_equal(frame[30:90, 40:120], original[30:90, 40:120])


def test_blur_person_fails_closed_when_mask_resizing_raises(monkeypatch):
    frame = noisy_frame()
    original = frame.copy()

    def fail_resize(*args, **kwargs):  # noqa: ARG001
        raise cv2.error("bad mask")

    monkeypatch.setattr(cv2, "resize", fail_resize)
    blur_person(
        frame,
        (40, 30, 120, 90),
        strength=40,
        mask=np.ones((12, 12), dtype=np.uint8),
    )

    assert not np.array_equal(frame[30:90, 40:120], original[30:90, 40:120])


def test_blur_person_with_a_full_mask_changes_only_the_padded_box_region():
    frame = noisy_frame()
    original = frame.copy()
    mask = np.ones(frame.shape[:2], dtype=np.uint8)

    blur_person(frame, (40, 30, 120, 90), strength=60, mask=mask)

    # Padding is 8% horizontally and 5% vertically around the box.
    assert not np.array_equal(frame[30:90, 40:120], original[30:90, 40:120])
    assert np.array_equal(frame[:20, :20], original[:20, :20])


@pytest.mark.parametrize("bbox", [(10, 10, 10, 10), (0, 0, 1, 1), (200, 200, 260, 260)])
def test_appearance_histogram_returns_none_when_the_torso_crop_is_empty(bbox):
    assert appearance_histogram(noisy_frame(), bbox) is None


def test_appearance_distance_treats_a_missing_candidate_as_maximally_different():
    reference = appearance_histogram(noisy_frame(), (20, 10, 100, 110))
    assert reference is not None
    assert appearance_distance(reference, None) == 1.0
    assert appearance_distance(reference, reference) == pytest.approx(0.0, abs=1e-3)
