"""Optional real-YOLO runner for annotated media.

This runner emits person boxes in the evaluator's prediction format. It does
not apply PublishSafe's selected-creator exclusion, tracking recovery, blur, or
export pipeline, so its output measures detector coverage only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evaluation.privacy_metrics import (
    EvaluationInputError,
    load_json,
    validate_ground_truth,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate YOLO person-box predictions for dense annotations.")
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="yolov8n-seg.pt")
    parser.add_argument("--confidence", type=float, default=0.3)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="cpu")
    return parser


def _media_path(video: dict, annotation_path: Path) -> Path:
    value = video.get("media_path")
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(
            f"video {video.get('video_id')!r} needs media_path for the YOLO runner"
        )
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (annotation_path.parent / candidate).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not 0.0 < args.confidence <= 1.0:
        parser.error("--confidence must be in (0, 1]")
    if args.imgsz <= 0:
        parser.error("--imgsz must be positive")

    try:
        ground_truth = load_json(args.ground_truth)
        videos = list(validate_ground_truth(ground_truth).values())
    except (EvaluationInputError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    try:
        import cv2
        from ultralytics import YOLO, __version__ as ultralytics_version
    except ImportError:
        parser.error(
            "the optional runner needs backend/requirements.txt (OpenCV, Ultralytics, and PyTorch)"
        )

    model = YOLO(args.model)
    loaded_weight_path = Path(str(getattr(model, "ckpt_path", args.model)))
    prediction_videos = []
    try:
        for video in videos:
            if not isinstance(video, dict):
                raise EvaluationInputError("each ground-truth video must be an object")
            path = _media_path(video, args.ground_truth)
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise EvaluationInputError(f"could not open media for {video.get('video_id')!r}: {path}")
            frames = []
            try:
                for frame_index in range(int(video.get("frame_count", 0))):
                    ok, frame = capture.read()
                    if not ok:
                        raise EvaluationInputError(
                            f"{path} ended before annotated frame {frame_index}"
                        )
                    result = model.predict(
                        frame,
                        classes=[0],
                        conf=args.confidence,
                        imgsz=args.imgsz,
                        device=args.device,
                        verbose=False,
                    )[0]
                    redactions = []
                    for box, confidence in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()):
                        redactions.append(
                            {
                                "bbox": [float(value) for value in box],
                                "confidence": float(confidence),
                            }
                        )
                    frames.append({"frame_index": frame_index, "redactions": redactions})
            finally:
                capture.release()
            prediction_videos.append({"video_id": video["video_id"], "frames": frames})
    except EvaluationInputError as exc:
        parser.error(str(exc))

    output = {
        "schema_version": "1.0",
        "model": {
            "name": Path(args.model).name,
            "version": f"ultralytics-{ultralytics_version}",
            "runner": "evaluation.runners.yolo_seg",
            "weights": str(args.model),
            "weights_sha256": (
                _sha256(loaded_weight_path) if loaded_weight_path.is_file() else None
            ),
            "parameters": {
                "confidence": args.confidence,
                "imgsz": args.imgsz,
                "device": args.device,
                "classes": [0],
            },
        },
        "videos": prediction_videos,
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
