from dataclasses import dataclass


Box = tuple[int, int, int, int]


def iou(a: Box, b: Box) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if intersection == 0:
        return 0.0
    area_a = max(1, a[2] - a[0]) * max(1, a[3] - a[1])
    area_b = max(1, b[2] - b[0]) * max(1, b[3] - b[1])
    return intersection / float(area_a + area_b - intersection)


@dataclass
class Track:
    track_id: int
    bbox: Box
    confidence: float
    missed: int = 0


class IoUTracker:
    """Small, dependency-free tracker suitable for an MVP demo."""

    def __init__(self, iou_threshold: float = 0.25, max_missed: int = 20):
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self.tracks: dict[int, Track] = {}
        self.next_id = 1

    def update(self, detections: list[tuple[Box, float]]) -> list[Track]:
        unmatched_tracks = set(self.tracks)
        unmatched_detections = set(range(len(detections)))
        candidates: list[tuple[float, int, int]] = []

        for track_id, track in self.tracks.items():
            for detection_index, (bbox, _) in enumerate(detections):
                score = iou(track.bbox, bbox)
                if score >= self.iou_threshold:
                    candidates.append((score, track_id, detection_index))

        for _, track_id, detection_index in sorted(candidates, reverse=True):
            if track_id not in unmatched_tracks or detection_index not in unmatched_detections:
                continue
            bbox, confidence = detections[detection_index]
            self.tracks[track_id] = Track(track_id, bbox, confidence)
            unmatched_tracks.remove(track_id)
            unmatched_detections.remove(detection_index)

        for track_id in unmatched_tracks:
            self.tracks[track_id].missed += 1

        for detection_index in unmatched_detections:
            bbox, confidence = detections[detection_index]
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = Track(track_id, bbox, confidence)

        self.tracks = {
            track_id: track
            for track_id, track in self.tracks.items()
            if track.missed <= self.max_missed
        }
        return [track for track in self.tracks.values() if track.missed == 0]
