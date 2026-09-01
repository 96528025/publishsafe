from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.privacy_metrics import (
    EvaluationInputError,
    bbox_iou,
    evaluate_privacy,
    load_json,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fixture_inputs():
    return (
        load_json(FIXTURES / "synthetic_ground_truth.json"),
        load_json(FIXTURES / "synthetic_predictions.json"),
    )


def test_synthetic_fixture_exercises_overall_and_scene_metrics():
    ground_truth, predictions = fixture_inputs()
    report = evaluate_privacy(ground_truth, predictions)

    assert report["overall"]["eligible_person_instances"] == 6
    assert report["overall"]["matched_redaction_instances"] == 3
    assert report["overall"]["person_recall"] == pytest.approx(0.5)
    assert report["overall"]["longest_consecutive_unredacted_frames"] == 2
    assert report["overall"]["worst_unredacted_run"] == {
        "video_id": "synthetic-four-frame-video",
        "person_id": "bystander-a",
        "start_frame": 1,
        "end_frame": 2,
        "frames": 2,
        "duration_seconds": 1.0,
    }

    assert report["by_scene_tag"]["crowd"]["person_recall"] == pytest.approx(0.5)
    assert report["by_scene_tag"]["occlusion"]["person_recall"] == pytest.approx(1 / 3)
    assert report["by_scene_tag"]["profile"]["longest_consecutive_unredacted_frames"] == 2
    assert report["by_scene_tag"]["low_light"]["longest_consecutive_unredacted_frames"] == 1
    assert {"profile", "occlusion", "low_light", "crowd"} <= set(report["by_scene_tag"])


def test_iou_handles_identical_partial_and_disjoint_boxes():
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert bbox_iou([0, 0, 10, 10], [5, 5, 15, 15]) == pytest.approx(25 / 175)
    assert bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_one_prediction_cannot_cover_two_people():
    ground_truth, predictions = fixture_inputs()
    first_frame = ground_truth["videos"][0]["frames"][0]
    first_frame["people"] = [
        {"person_id": "a", "bbox": [0, 0, 10, 10], "should_redact": True, "scene_tags": []},
        {"person_id": "b", "bbox": [1, 0, 11, 10], "should_redact": True, "scene_tags": []},
    ]
    for frame in ground_truth["videos"][0]["frames"][1:]:
        frame["people"] = []
    predictions["videos"][0]["frames"] = [
        {"frame_index": 0, "redactions": [{"bbox": [0, 0, 10, 10], "confidence": 0.9}]}
    ]

    report = evaluate_privacy(ground_truth, predictions)
    assert report["overall"]["eligible_person_instances"] == 2
    assert report["overall"]["matched_redaction_instances"] == 1


def test_matching_maximizes_recall_instead_of_greedily_taking_highest_iou():
    ground_truth, predictions = fixture_inputs()
    first_frame = ground_truth["videos"][0]["frames"][0]
    first_frame["people"] = [
        {"person_id": "a", "bbox": [0, 0, 10, 10], "should_redact": True, "scene_tags": []},
        {"person_id": "b", "bbox": [4, 0, 14, 10], "should_redact": True, "scene_tags": []},
    ]
    for frame in ground_truth["videos"][0]["frames"][1:]:
        frame["people"] = []
    predictions["videos"][0]["frames"] = [
        {
            "frame_index": 0,
            "redactions": [
                # a->0 has the highest IoU, but assigning it would strand b.
                {"bbox": [1, 0, 11, 10], "confidence": 0.9},
                {"bbox": [0, 0, 8, 10], "confidence": 0.9},
            ],
        }
    ]

    report = evaluate_privacy(ground_truth, predictions)
    assert report["overall"]["eligible_person_instances"] == 2
    assert report["overall"]["matched_redaction_instances"] == 2


def test_missing_prediction_frames_are_counted_as_missed_redactions():
    ground_truth, predictions = fixture_inputs()
    predictions["videos"][0]["frames"] = []

    report = evaluate_privacy(ground_truth, predictions)
    assert report["overall"]["matched_redaction_instances"] == 0
    assert report["overall"]["longest_consecutive_unredacted_frames"] == 4


def test_unredacted_run_is_per_person_track_and_resets_when_person_is_absent():
    ground_truth, predictions = fixture_inputs()
    ground_truth["videos"][0]["frames"][1]["people"] = []
    predictions["videos"][0]["frames"] = []

    report = evaluate_privacy(ground_truth, predictions)
    assert report["overall"]["longest_consecutive_unredacted_frames"] == 2
    assert report["overall"]["worst_unredacted_run"]["person_id"] == "bystander-a"
    assert report["overall"]["worst_unredacted_run"]["start_frame"] == 2
    assert report["overall"]["worst_unredacted_run"]["end_frame"] == 3


def test_unannotated_standard_scenario_is_reported_as_not_measured():
    ground_truth, predictions = fixture_inputs()
    for frame in ground_truth["videos"][0]["frames"]:
        frame["scene_tags"] = [tag for tag in frame["scene_tags"] if tag != "low_light"]

    report = evaluate_privacy(ground_truth, predictions)
    low_light = report["by_scene_tag"]["low_light"]
    assert low_light["eligible_person_instances"] == 0
    assert low_light["person_recall"] is None
    assert low_light["longest_consecutive_unredacted_frames"] == 0


def test_selected_creator_is_not_part_of_privacy_recall():
    ground_truth, predictions = fixture_inputs()
    ground_truth["videos"][0]["frames"][0]["people"] = [
        {"person_id": "creator", "bbox": [0, 0, 10, 10], "should_redact": False, "scene_tags": []}
    ]
    for frame in ground_truth["videos"][0]["frames"][1:]:
        frame["people"] = []
    predictions["videos"][0]["frames"] = []

    report = evaluate_privacy(ground_truth, predictions)
    assert report["overall"]["eligible_person_instances"] == 0
    assert report["overall"]["person_recall"] is None


def test_dense_ground_truth_is_required_for_consecutive_frame_claims():
    ground_truth, predictions = fixture_inputs()
    ground_truth["videos"][0]["frames"].pop()

    with pytest.raises(EvaluationInputError, match="dense annotations"):
        evaluate_privacy(ground_truth, predictions)


def test_unknown_prediction_video_is_rejected():
    ground_truth, predictions = fixture_inputs()
    invalid = deepcopy(predictions["videos"][0])
    invalid["video_id"] = "not-in-ground-truth"
    predictions["videos"].append(invalid)

    with pytest.raises(EvaluationInputError, match="unknown video_id"):
        evaluate_privacy(ground_truth, predictions)
