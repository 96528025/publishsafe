"""Deterministic, model-independent metrics for person-redaction coverage.

The evaluator intentionally operates on JSON annotations and predictions. It
does not import PublishSafe's runtime, download model weights, or inspect media.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STANDARD_SCENE_TAGS = ("occlusion", "low_light", "crowd", "profile")


class EvaluationInputError(ValueError):
    """Raised when an evaluation input cannot support trustworthy metrics."""


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise EvaluationInputError(f"{path}: top-level JSON value must be an object")
    return payload


def validate_ground_truth(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and index dense annotations without running an evaluation."""

    return _validate_ground_truth(payload)


def bbox_iou(left: list[float], right: list[float]) -> float:
    """Return intersection-over-union for two ``[x1, y1, x2, y2]`` boxes."""

    left_box = _validate_bbox(left, "left bbox")
    right_box = _validate_bbox(right, "right bbox")
    intersection_width = max(0.0, min(left_box[2], right_box[2]) - max(left_box[0], right_box[0]))
    intersection_height = max(0.0, min(left_box[3], right_box[3]) - max(left_box[1], right_box[1]))
    intersection = intersection_width * intersection_height
    left_area = (left_box[2] - left_box[0]) * (left_box[3] - left_box[1])
    right_area = (right_box[2] - right_box[0]) * (right_box[3] - right_box[1])
    return intersection / (left_area + right_area - intersection)


@dataclass
class _Counts:
    eligible: int = 0
    matched: int = 0

    def add(self, matched: bool) -> None:
        self.eligible += 1
        self.matched += int(matched)


@dataclass(frozen=True)
class _Run:
    frames: int
    video_id: str | None = None
    person_id: str | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    duration_seconds: float = 0.0


class _RunTracker:
    """Track consecutive missed redactions for visible annotated people."""

    def __init__(self, video_id: str, fps: float) -> None:
        self.video_id = video_id
        self.fps = fps
        self._active: dict[str, tuple[int, int, int]] = {}
        self.best = _Run(frames=0)

    def update(self, frame_index: int, missed_person_ids: set[str]) -> None:
        for person_id in list(self._active):
            if person_id not in missed_person_ids:
                self._active.pop(person_id)

        for person_id in missed_person_ids:
            previous = self._active.get(person_id)
            if previous is not None and previous[1] == frame_index - 1:
                start_frame, _, frames = previous
                current = (start_frame, frame_index, frames + 1)
            else:
                current = (frame_index, frame_index, 1)
            self._active[person_id] = current
            self._consider(person_id, current)

    def _consider(self, person_id: str, run: tuple[int, int, int]) -> None:
        start_frame, end_frame, frames = run
        candidate = _Run(
            frames=frames,
            video_id=self.video_id,
            person_id=person_id,
            start_frame=start_frame,
            end_frame=end_frame,
            duration_seconds=frames / self.fps,
        )
        candidate_key = (
            candidate.frames,
            -(candidate.start_frame or 0),
            candidate.person_id or "",
        )
        best_key = (
            self.best.frames,
            -(self.best.start_frame or 0),
            self.best.person_id or "",
        )
        if candidate_key > best_key:
            self.best = candidate


def evaluate_privacy(
    ground_truth: dict[str, Any],
    predictions: dict[str, Any],
    *,
    iou_threshold: float = 0.5,
) -> dict[str, Any]:
    """Evaluate box-level redaction coverage for densely annotated videos.

    ``person_recall`` is the fraction of ground-truth person instances marked
    ``should_redact=true`` that receive a one-to-one predicted redaction match.
    A miss is treated as an unredacted frame for that person. This is a coverage
    proxy, not proof that pixels, identity, audio, text, or reflections are safe.
    """

    if not isinstance(iou_threshold, (int, float)) or isinstance(iou_threshold, bool):
        raise EvaluationInputError("iou_threshold must be numeric")
    if not 0.0 < float(iou_threshold) <= 1.0:
        raise EvaluationInputError("iou_threshold must be in (0, 1]")

    truth_videos = _validate_ground_truth(ground_truth)
    prediction_videos = _validate_predictions(predictions, truth_videos)

    overall_counts = _Counts()
    overall_best = _Run(frames=0)
    tag_counts: dict[str, _Counts] = {}
    tag_best: dict[str, _Run] = {}
    per_video: dict[str, dict[str, Any]] = {}

    for video_id, video in truth_videos.items():
        fps = float(video["fps"])
        video_counts = _Counts()
        overall_run_tracker = _RunTracker(video_id, fps)
        tag_run_trackers: dict[str, _RunTracker] = {}
        predicted_frames = prediction_videos.get(video_id, {})

        for frame in video["frames"]:
            frame_index = frame["frame_index"]
            redactions = predicted_frames.get(frame_index, [])
            target_people = [person for person in frame["people"] if person["should_redact"]]
            matched_ids = _match_targets(target_people, redactions, float(iou_threshold))
            missed_ids = {person["person_id"] for person in target_people if person["person_id"] not in matched_ids}
            overall_run_tracker.update(frame_index, missed_ids)

            active_misses_by_tag: dict[str, set[str]] = {}
            all_tags_this_frame: set[str] = set(video["scene_tags"]) | set(frame["scene_tags"])
            for person in target_people:
                person_id = person["person_id"]
                matched = person_id in matched_ids
                overall_counts.add(matched)
                video_counts.add(matched)
                person_tags = all_tags_this_frame | set(person["scene_tags"])
                for tag in person_tags:
                    tag_counts.setdefault(tag, _Counts()).add(matched)
                    active_misses_by_tag.setdefault(tag, set())
                    if not matched:
                        active_misses_by_tag[tag].add(person_id)

            known_tags = set(tag_run_trackers) | set(active_misses_by_tag)
            for tag in known_tags:
                tracker = tag_run_trackers.setdefault(tag, _RunTracker(video_id, fps))
                tracker.update(frame_index, active_misses_by_tag.get(tag, set()))

        video_best = overall_run_tracker.best
        overall_best = _pick_longer_run(overall_best, video_best)
        for tag, tracker in tag_run_trackers.items():
            tag_best[tag] = _pick_longer_run(tag_best.get(tag, _Run(frames=0)), tracker.best)
        per_video[video_id] = _stats(video_counts, video_best)

    # Always render the four documented privacy slices. An absent slice reports
    # zero eligible instances and ``person_recall: null``; it is never silently
    # presented as a successful result. Dataset-specific tags remain available
    # alongside the standard ones.
    by_tag = {
        tag: _stats(counts, tag_best.get(tag, _Run(frames=0)))
        for tag, counts in sorted(
            {
                **{tag: _Counts() for tag in STANDARD_SCENE_TAGS},
                **tag_counts,
            }.items()
        )
    }
    return {
        "schema_version": "1.0",
        "evaluation": {
            "iou_threshold": float(iou_threshold),
            "ground_truth_dataset": ground_truth["dataset"],
            "prediction_model": predictions["model"],
            "metric_scope": "box-level redaction-candidate coverage",
        },
        "overall": _stats(overall_counts, overall_best),
        "by_scene_tag": by_tag,
        "per_video": per_video,
    }


def _pick_longer_run(left: _Run, right: _Run) -> _Run:
    left_key = (left.frames, left.video_id or "", left.person_id or "")
    right_key = (right.frames, right.video_id or "", right.person_id or "")
    return right if right_key > left_key else left


def _stats(counts: _Counts, longest_run: _Run) -> dict[str, Any]:
    recall = counts.matched / counts.eligible if counts.eligible else None
    return {
        "eligible_person_instances": counts.eligible,
        "matched_redaction_instances": counts.matched,
        "person_recall": recall,
        "longest_consecutive_unredacted_frames": longest_run.frames,
        "worst_unredacted_run": {
            "video_id": longest_run.video_id,
            "person_id": longest_run.person_id,
            "start_frame": longest_run.start_frame,
            "end_frame": longest_run.end_frame,
            "frames": longest_run.frames,
            "duration_seconds": longest_run.duration_seconds,
        },
    }


def _match_targets(
    targets: list[dict[str, Any]],
    redactions: list[dict[str, Any]],
    iou_threshold: float,
) -> set[str]:
    """Return a deterministic maximum-cardinality one-to-one matching.

    Maximizing cardinality is important for recall: consuming the highest-IoU
    edge first can block two otherwise valid threshold matches. IoU is therefore
    used to define and deterministically order valid edges, while augmenting
    paths maximize the number of matched ground-truth people.
    """

    adjacency: dict[str, list[tuple[float, int]]] = {}
    for target in targets:
        person_id = target["person_id"]
        adjacency[person_id] = []
        for redaction_index, redaction in enumerate(redactions):
            overlap = bbox_iou(target["bbox"], redaction["bbox"])
            if overlap >= iou_threshold:
                adjacency[person_id].append((overlap, redaction_index))
        adjacency[person_id].sort(key=lambda item: (-item[0], item[1]))

    redaction_owner: dict[int, str] = {}

    def augment(person_id: str, visited_redactions: set[int]) -> bool:
        for _, redaction_index in adjacency[person_id]:
            if redaction_index in visited_redactions:
                continue
            visited_redactions.add(redaction_index)
            previous_owner = redaction_owner.get(redaction_index)
            if previous_owner is None or augment(previous_owner, visited_redactions):
                redaction_owner[redaction_index] = person_id
                return True
        return False

    for person_id in sorted(adjacency):
        augment(person_id, set())
    return set(redaction_owner.values())


def _validate_ground_truth(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _require_schema_version(payload, "ground truth")
    dataset = _require_mapping(payload, "dataset", "ground truth")
    for field in ("name", "version", "license", "source"):
        _require_nonempty_string(dataset, field, "ground truth.dataset")
    videos = _require_list(payload, "videos", "ground truth")
    if not videos:
        raise EvaluationInputError("ground truth.videos must not be empty")

    indexed: dict[str, dict[str, Any]] = {}
    for video_number, video_value in enumerate(videos):
        context = f"ground truth.videos[{video_number}]"
        video = _as_mapping(video_value, context)
        video_id = _require_nonempty_string(video, "video_id", context)
        if video_id in indexed:
            raise EvaluationInputError(f"duplicate ground-truth video_id: {video_id}")
        frame_count = _require_nonnegative_int(video, "frame_count", context)
        if frame_count == 0:
            raise EvaluationInputError(f"{context}.frame_count must be greater than zero")
        fps = video.get("fps")
        if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
            raise EvaluationInputError(f"{context}.fps must be a positive finite number")
        video["scene_tags"] = _validate_tags(video.get("scene_tags", []), f"{context}.scene_tags")
        frames = _require_list(video, "frames", context)
        if len(frames) != frame_count:
            raise EvaluationInputError(
                f"{context} must contain dense annotations for all {frame_count} frames; found {len(frames)}"
            )

        validated_frames: list[dict[str, Any]] = []
        seen_indices: set[int] = set()
        for frame_number, frame_value in enumerate(frames):
            frame_context = f"{context}.frames[{frame_number}]"
            frame = _as_mapping(frame_value, frame_context)
            frame_index = _require_nonnegative_int(frame, "frame_index", frame_context)
            if frame_index >= frame_count or frame_index in seen_indices:
                raise EvaluationInputError(f"{frame_context}.frame_index is duplicate or outside frame_count")
            seen_indices.add(frame_index)
            frame["scene_tags"] = _validate_tags(frame.get("scene_tags", []), f"{frame_context}.scene_tags")
            people = _require_list(frame, "people", frame_context)
            seen_people: set[str] = set()
            validated_people: list[dict[str, Any]] = []
            for person_number, person_value in enumerate(people):
                person_context = f"{frame_context}.people[{person_number}]"
                person = _as_mapping(person_value, person_context)
                person_id = _require_nonempty_string(person, "person_id", person_context)
                if person_id in seen_people:
                    raise EvaluationInputError(f"duplicate person_id {person_id!r} in frame {frame_index}")
                seen_people.add(person_id)
                person["bbox"] = list(_validate_bbox(person.get("bbox"), f"{person_context}.bbox"))
                if not isinstance(person.get("should_redact"), bool):
                    raise EvaluationInputError(f"{person_context}.should_redact must be boolean")
                person["scene_tags"] = _validate_tags(
                    person.get("scene_tags", []), f"{person_context}.scene_tags"
                )
                validated_people.append(person)
            frame["people"] = validated_people
            validated_frames.append(frame)
        if seen_indices != set(range(frame_count)):
            raise EvaluationInputError(f"{context}.frames must cover every index from 0 to {frame_count - 1}")
        video["frames"] = sorted(validated_frames, key=lambda item: item["frame_index"])
        indexed[video_id] = video
    return indexed


def _validate_predictions(
    payload: dict[str, Any],
    truth_videos: dict[str, dict[str, Any]],
) -> dict[str, dict[int, list[dict[str, Any]]]]:
    _require_schema_version(payload, "predictions")
    model = _require_mapping(payload, "model", "predictions")
    for field in ("name", "version", "runner"):
        _require_nonempty_string(model, field, "predictions.model")
    videos = _require_list(payload, "videos", "predictions")
    indexed: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for video_number, video_value in enumerate(videos):
        context = f"predictions.videos[{video_number}]"
        video = _as_mapping(video_value, context)
        video_id = _require_nonempty_string(video, "video_id", context)
        if video_id not in truth_videos:
            raise EvaluationInputError(f"predictions contain unknown video_id: {video_id}")
        if video_id in indexed:
            raise EvaluationInputError(f"duplicate prediction video_id: {video_id}")
        frame_count = truth_videos[video_id]["frame_count"]
        frames = _require_list(video, "frames", context)
        frame_map: dict[int, list[dict[str, Any]]] = {}
        for frame_number, frame_value in enumerate(frames):
            frame_context = f"{context}.frames[{frame_number}]"
            frame = _as_mapping(frame_value, frame_context)
            frame_index = _require_nonnegative_int(frame, "frame_index", frame_context)
            if frame_index >= frame_count or frame_index in frame_map:
                raise EvaluationInputError(f"{frame_context}.frame_index is duplicate or outside ground truth")
            redactions = _require_list(frame, "redactions", frame_context)
            validated_redactions: list[dict[str, Any]] = []
            for redaction_number, redaction_value in enumerate(redactions):
                redaction_context = f"{frame_context}.redactions[{redaction_number}]"
                redaction = _as_mapping(redaction_value, redaction_context)
                redaction["bbox"] = list(_validate_bbox(redaction.get("bbox"), f"{redaction_context}.bbox"))
                confidence = redaction.get("confidence")
                if confidence is not None and (
                    not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or not math.isfinite(confidence)
                    or not 0.0 <= confidence <= 1.0
                ):
                    raise EvaluationInputError(f"{redaction_context}.confidence must be in [0, 1]")
                validated_redactions.append(redaction)
            frame_map[frame_index] = validated_redactions
        indexed[video_id] = frame_map
    return indexed


def _validate_bbox(value: Any, context: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise EvaluationInputError(f"{context} must be [x1, y1, x2, y2]")
    if any(
        not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item)
        for item in value
    ):
        raise EvaluationInputError(f"{context} coordinates must be finite numbers")
    x1, y1, x2, y2 = (float(item) for item in value)
    if x2 <= x1 or y2 <= y1:
        raise EvaluationInputError(f"{context} must have x2 > x1 and y2 > y1")
    return x1, y1, x2, y2


def _validate_tags(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvaluationInputError(f"{context} must be a list of non-empty strings")
    return sorted(set(item.strip() for item in value))


def _require_schema_version(payload: dict[str, Any], context: str) -> None:
    if payload.get("schema_version") != "1.0":
        raise EvaluationInputError(f"{context}.schema_version must be '1.0'")


def _as_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationInputError(f"{context} must be an object")
    return dict(value)


def _require_mapping(payload: dict[str, Any], field: str, context: str) -> dict[str, Any]:
    return _as_mapping(payload.get(field), f"{context}.{field}")


def _require_list(payload: dict[str, Any], field: str, context: str) -> list[Any]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise EvaluationInputError(f"{context}.{field} must be a list")
    return value


def _require_nonempty_string(payload: dict[str, Any], field: str, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"{context}.{field} must be a non-empty string")
    return value.strip()


def _require_nonnegative_int(payload: dict[str, Any], field: str, context: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvaluationInputError(f"{context}.{field} must be a non-negative integer")
    return value
