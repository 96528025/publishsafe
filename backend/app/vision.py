import logging
import os
from pathlib import Path

import cv2
import numpy as np

from .config import AVATAR_DIR, BYTETRACK_CONFIG
from .tracker import Track

logger = logging.getLogger(__name__)


class PersonDetector:
    def __init__(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "ultralytics is not installed. Run: pip install -r backend/requirements.txt"
            ) from exc
        model_path = os.getenv("YOLO_MODEL_PATH", "yolov8n-seg.pt")
        logger.info("Loading YOLOv8 nano person segmentation model: %s", model_path)
        self.model = YOLO(model_path)

    def detect(self, frame: np.ndarray) -> list[tuple[tuple[int, int, int, int], float]]:
        results = self.model.predict(
            frame, classes=[0], conf=0.3, imgsz=640, verbose=False
        )
        detections = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = (int(value) for value in box.xyxy[0].tolist())
            detections.append(((x1, y1, x2, y2), float(box.conf[0])))
        return detections

    def reset_tracking(self) -> None:
        # Ultralytics keeps tracker state on the predictor between calls.
        self.model.predictor = None

    def track(self, frame: np.ndarray) -> list[Track]:
        results = self.model.track(
            frame,
            persist=True,
            tracker=str(BYTETRACK_CONFIG),
            classes=[0],
            conf=0.3,
            imgsz=640,
            verbose=False,
        )
        boxes = results[0].boxes
        if boxes.id is None:
            return []

        track_ids = boxes.id.int().tolist()
        coordinates = boxes.xyxy.int().tolist()
        confidences = boxes.conf.tolist()
        masks = results[0].masks
        mask_data = (
            (masks.data.cpu().numpy() > 0.5).astype(np.uint8)
            if masks is not None
            else None
        )
        return [
            Track(
                track_id=track_id,
                bbox=tuple(coordinates[index]),
                confidence=float(confidences[index]),
                mask=mask_data[index] if mask_data is not None else None,
            )
            for index, track_id in enumerate(track_ids)
        ]


def appearance_histogram(
    frame: np.ndarray, bbox: tuple[int, int, int, int]
) -> np.ndarray | None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    box_width, box_height = x2 - x1, y2 - y1
    original_y1 = y1
    # Focus on the torso, where clothing color is more stable than limbs/background.
    x1 = max(0, int(x1 + box_width * 0.18))
    x2 = min(width, int(x2 - box_width * 0.18))
    y1 = max(0, int(original_y1 + box_height * 0.12))
    y2 = min(height, int(original_y1 + box_height * 0.70))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
    return cv2.normalize(histogram, histogram).flatten()


def appearance_distance(reference: np.ndarray, candidate: np.ndarray | None) -> float:
    if candidate is None:
        return 1.0
    return float(
        cv2.compareHist(
            reference.astype(np.float32),
            candidate.astype(np.float32),
            cv2.HISTCMP_BHATTACHARYYA,
        )
    )


def ensure_avatar_assets() -> None:
    palettes = {
        "sunny": ((35, 185, 255), (255, 245, 210)),
        "cosmo": ((215, 105, 110), (245, 225, 255)),
        "bloom": ((120, 200, 105), (230, 255, 235)),
    }
    for name, (body_color, face_color) in palettes.items():
        path = AVATAR_DIR / f"{name}.png"
        if path.exists():
            continue
        image = np.zeros((480, 320, 4), dtype=np.uint8)
        cv2.ellipse(image, (160, 310), (135, 150), 0, 0, 360, (*body_color, 245), -1)
        cv2.circle(image, (160, 130), 105, (*face_color, 255), -1)
        cv2.circle(image, (123, 120), 12, (50, 50, 70, 255), -1)
        cv2.circle(image, (197, 120), 12, (50, 50, 70, 255), -1)
        cv2.ellipse(image, (160, 160), (38, 23), 0, 0, 180, (50, 50, 70, 255), 7)
        cv2.circle(image, (75, 40), 28, (*body_color, 255), -1)
        cv2.circle(image, (245, 40), 28, (*body_color, 255), -1)
        cv2.imwrite(str(path), image)


def draw_preview(
    frame: np.ndarray, people: list[tuple[int, tuple[int, int, int, int], float]]
) -> np.ndarray:
    preview = frame.copy()
    for track_id, (x1, y1, x2, y2), _ in people:
        color = (54, 230, 196)
        cv2.rectangle(preview, (x1, y1), (x2, y2), color, 3)
        label = f"Person {track_id}"
        cv2.rectangle(preview, (x1, max(0, y1 - 34)), (x1 + 145, y1), color, -1)
        cv2.putText(
            preview,
            label,
            (x1 + 8, max(22, y1 - 9)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (20, 25, 35),
            2,
            cv2.LINE_AA,
        )
    return preview


def overlay_avatar(frame: np.ndarray, bbox: tuple[int, int, int, int], avatar: np.ndarray) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    padding_x = int((x2 - x1) * 0.08)
    padding_y = int((y2 - y1) * 0.05)
    x1, x2 = max(0, x1 - padding_x), min(width, x2 + padding_x)
    y1, y2 = max(0, y1 - padding_y), min(height, y2 + padding_y)
    if x2 <= x1 or y2 <= y1:
        return

    sticker = cv2.resize(avatar, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    alpha = sticker[:, :, 3:4].astype(np.float32) / 255.0
    frame[y1:y2, x1:x2] = (
        alpha * sticker[:, :, :3] + (1 - alpha) * frame[y1:y2, x1:x2]
    ).astype(np.uint8)


def blur_person(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int],
    strength: int = 40,
    mask: np.ndarray | None = None,
) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    padding_x = int((x2 - x1) * 0.08)
    padding_y = int((y2 - y1) * 0.05)
    x1, x2 = x1 - padding_x, x2 + padding_x
    y1, y2 = y1 - padding_y, y2 + padding_y
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return

    region_height, region_width = region.shape[:2]
    normalized = max(10, min(100, strength)) / 100.0
    anonymized = region

    # Pixelation fades in above the midpoint instead of appearing abruptly.
    if strength > 50:
        divisor = 8 + int((strength - 50) / 50 * 14)
        reduced_width = max(8, region_width // divisor)
        reduced_height = max(8, region_height // divisor)
        anonymized = cv2.resize(
            region,
            (reduced_width, reduced_height),
            interpolation=cv2.INTER_AREA,
        )
        anonymized = cv2.resize(
            anonymized,
            (region_width, region_height),
            interpolation=cv2.INTER_LINEAR,
        )

    kernel = int(11 + min(region.shape[:2]) * (0.08 + 0.34 * normalized))
    kernel = min(151, max(15, kernel | 1))
    anonymized = cv2.GaussianBlur(anonymized, (kernel, kernel), 0)

    if mask is None:
        frame[y1:y2, x1:x2] = anonymized
        return

    full_mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    mask_region = full_mask[y1:y2, x1:x2]
    dilation = max(3, int(min(region.shape[:2]) * 0.025)) | 1
    mask_region = cv2.dilate(
        mask_region,
        np.ones((dilation, dilation), dtype=np.uint8),
        iterations=1,
    )
    feather = max(5, int(min(region.shape[:2]) * 0.018)) | 1
    alpha = cv2.GaussianBlur(
        mask_region.astype(np.float32),
        (feather, feather),
        0,
    )[..., None]
    alpha = np.clip(alpha, 0.0, 1.0)
    frame[y1:y2, x1:x2] = (
        alpha * anonymized + (1.0 - alpha) * region
    ).astype(np.uint8)


def load_avatar(name: str) -> np.ndarray:
    avatar = cv2.imread(str(Path(AVATAR_DIR) / f"{name}.png"), cv2.IMREAD_UNCHANGED)
    if avatar is None or avatar.shape[2] != 4:
        raise RuntimeError(f"Avatar asset '{name}' could not be loaded")
    return avatar
