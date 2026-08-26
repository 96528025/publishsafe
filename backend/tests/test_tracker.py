"""Pure tracking logic: no model, no frames, just boxes."""

import pytest

from app.tracker import IoUTracker, iou


def test_iou_is_one_for_identical_boxes_and_zero_when_disjoint():
    box = (0, 0, 10, 10)
    assert iou(box, box) == pytest.approx(1.0)
    assert iou(box, (50, 50, 60, 60)) == 0.0
    # Touching edges share no area.
    assert iou(box, (10, 0, 20, 10)) == 0.0


def test_iou_matches_the_hand_computed_overlap_ratio():
    # 25px intersection over a 175px union.
    assert iou((0, 0, 10, 10), (5, 5, 15, 15)) == pytest.approx(25 / 175)


def test_tracker_assigns_sequential_ids_to_previously_unseen_detections():
    tracker = IoUTracker()
    tracks = tracker.update([((0, 0, 10, 10), 0.9), ((50, 50, 60, 60), 0.8)])
    assert sorted(track.track_id for track in tracks) == [1, 2]


def test_tracker_keeps_the_same_id_when_a_person_moves_between_frames():
    """ID stability is what lets the UI keep the creator selected."""
    tracker = IoUTracker()
    first = tracker.update([((0, 0, 100, 100), 0.9)])
    second = tracker.update([((10, 10, 110, 110), 0.9)])
    assert first[0].track_id == second[0].track_id == 1
    assert second[0].bbox == (10, 10, 110, 110)


def test_tracker_starts_a_new_id_when_the_box_jumps_too_far():
    tracker = IoUTracker()
    tracker.update([((0, 0, 20, 20), 0.9)])
    moved = tracker.update([((500, 500, 520, 520), 0.9)])
    assert moved[0].track_id == 2


def test_tracker_returns_nothing_for_empty_detections_and_expires_stale_tracks():
    tracker = IoUTracker(max_missed=2)
    tracker.update([((0, 0, 10, 10), 0.9)])

    # A missed frame hides the track from the result but keeps it recoverable.
    assert tracker.update([]) == []
    assert 1 in tracker.tracks

    tracker.update([])
    tracker.update([])
    assert tracker.tracks == {}

    # After expiry the same location is treated as a new person.
    revived = tracker.update([((0, 0, 10, 10), 0.9)])
    assert revived[0].track_id == 2


def test_tracker_handles_empty_detections_on_a_fresh_tracker():
    assert IoUTracker().update([]) == []
