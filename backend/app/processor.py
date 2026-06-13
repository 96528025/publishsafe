import logging
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import OUTPUT_DIR, UPLOAD_DIR
from .vision import (
    PersonDetector,
    appearance_distance,
    appearance_histogram,
    blur_person,
    load_avatar,
    overlay_avatar,
)

logger = logging.getLogger(__name__)

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


def find_video(video_id: str) -> Path:
    matches = list(UPLOAD_DIR.glob(f"{video_id}.*"))
    if not matches:
        raise FileNotFoundError("Uploaded video was not found")
    return matches[0]


def set_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        jobs[job_id].update(changes)


def process_video(
    job_id: str,
    video_id: str,
    selected_track_id: int,
    mode: str,
    avatar_style: str,
    detector: PersonDetector,
) -> None:
    capture = None
    writer = None
    try:
        set_job(job_id, status="processing", message="Loading video")
        source = find_video(video_id)
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise RuntimeError("OpenCV could not open the uploaded video")

        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        temporary = OUTPUT_DIR / f"{video_id}_silent.mp4"
        output = OUTPUT_DIR / f"{video_id}_protected.mp4"
        writer = cv2.VideoWriter(
            str(temporary),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError("Could not create the output video")

        detector.reset_tracking()
        avatar = load_avatar(avatar_style) if mode == "avatar" else None
        frame_number = 0
        creator_track_id = selected_track_id
        creator_appearance: np.ndarray | None = None

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            tracks = detector.track(frame)

            if creator_appearance is None:
                selected = next(
                    (track for track in tracks if track.track_id == selected_track_id),
                    None,
                )
                if selected is not None:
                    creator_appearance = appearance_histogram(frame, selected.bbox)
            else:
                candidates = [
                    (
                        appearance_distance(
                            creator_appearance,
                            appearance_histogram(frame, track.bbox),
                        ),
                        track,
                    )
                    for track in tracks
                ]
                current = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate[1].track_id == creator_track_id
                    ),
                    None,
                )
                best = min(candidates, key=lambda candidate: candidate[0], default=None)

                # If ByteTrack swaps IDs during a crossing, clothing appearance
                # provides a second signal to recover the selected creator.
                if best is not None and best[0] < 0.48:
                    if current is None or current[0] > best[0] + 0.12:
                        if creator_track_id != best[1].track_id:
                            logger.info(
                                "[%s] Creator track recovered: %s -> %s",
                                job_id,
                                creator_track_id,
                                best[1].track_id,
                            )
                        creator_track_id = best[1].track_id

            for track in tracks:
                if track.track_id == creator_track_id:
                    continue
                if mode == "blur":
                    blur_person(frame, track.bbox)
                else:
                    overlay_avatar(frame, track.bbox, avatar)
            writer.write(frame)
            frame_number += 1

            if frame_number == 1 or frame_number % 10 == 0:
                progress = min(99, int(frame_number / frame_count * 100))
                message = f"Protecting frame {frame_number} of {frame_count}"
                set_job(job_id, progress=progress, message=message)
                logger.info("[%s] %s (%d%%)", job_id, message, progress)

        if frame_number == 0:
            raise RuntimeError("The uploaded file did not contain readable video frames")
        writer.release()
        writer = None
        capture.release()
        capture = None

        # OpenCV does not preserve audio. Reattach it when ffmpeg is available.
        if shutil.which("ffmpeg"):
            command = [
                "ffmpeg", "-y", "-i", str(temporary), "-i", str(source),
                "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264",
                "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", "-shortest", str(output),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("ffmpeg audio merge failed: %s", result.stderr[-500:])
                temporary.replace(output)
            else:
                temporary.unlink(missing_ok=True)
        else:
            temporary.replace(output)

        set_job(
            job_id,
            status="complete",
            progress=100,
            message="Your privacy-safe video is ready",
            output_url=f"/outputs/{output.name}",
        )
    except Exception as exc:
        logger.exception("Video processing failed for job %s", job_id)
        set_job(job_id, status="failed", message=str(exc))
    finally:
        if writer is not None:
            writer.release()
        if capture is not None:
            capture.release()


def create_job() -> str:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Waiting to process",
            "output_url": None,
        }
    return job_id
