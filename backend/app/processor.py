import logging
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

from .config import VIDEO_ENCODER
from .privacy import CreatorCandidate, select_creator_exemption
from .storage import (
    delete_output_job,
    find_video,
    prepare_job_output,
    secure_file,
)
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

AudioPolicy = Literal["remove", "preserve"]
AudioStatus = Literal["removed", "preserved"]


class AudioPreservationError(RuntimeError):
    pass


def ffmpeg_command(
    temporary: Path,
    source: Path,
    output: Path,
    encoder: str,
    audio_policy: AudioPolicy = "remove",
) -> list[str]:
    if audio_policy not in {"remove", "preserve"}:
        raise ValueError(f"Unsupported audio policy: {audio_policy}")

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(temporary),
    ]
    if audio_policy == "preserve":
        command.extend(["-i", str(source)])
    command.extend(["-map", "0:v:0"])
    if encoder == "h264_videotoolbox":
        command.extend(
            [
                "-c:v",
                "h264_videotoolbox",
                "-q:v",
                "65",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
            ]
        )
    else:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
            ]
        )
    if audio_policy == "preserve":
        # Do not use the optional-map suffix here: a preserve request must fail
        # rather than silently return a video without the requested audio.
        command.extend(["-map", "1:a:0", "-c:a", "aac", "-shortest"])
    else:
        command.append("-an")
    command.extend(["-movflags", "+faststart", str(output)])
    return command


def finalize_output(
    temporary: Path,
    source: Path,
    output: Path,
    encoder: str,
    audio_policy: AudioPolicy,
) -> AudioStatus:
    if audio_policy not in {"remove", "preserve"}:
        raise ValueError(f"Unsupported audio policy: {audio_policy}")
    if not shutil.which("ffmpeg"):
        if audio_policy == "preserve":
            raise AudioPreservationError(
                "Audio preservation was requested, but FFmpeg is unavailable"
            )
        temporary.replace(output)
        return "removed"

    result = subprocess.run(
        ffmpeg_command(temporary, source, output, encoder, audio_policy),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and encoder != "libx264":
        logger.warning(
            "%s encoding failed; retrying with libx264: %s",
            encoder,
            result.stderr[-500:],
        )
        result = subprocess.run(
            ffmpeg_command(temporary, source, output, "libx264", audio_policy),
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        output.unlink(missing_ok=True)
        if audio_policy == "preserve":
            logger.error("FFmpeg audio preservation failed: %s", result.stderr[-500:])
            raise AudioPreservationError("FFmpeg could not preserve the source audio")
        logger.warning("FFmpeg video encoding failed: %s", result.stderr[-500:])
        temporary.replace(output)
        return "removed"

    temporary.unlink(missing_ok=True)
    return "preserved" if audio_policy == "preserve" else "removed"


def completion_message(process_scope: str, audio_status: AudioStatus) -> str:
    subject = (
        "Your 10-second preview"
        if process_scope == "preview"
        else "Your processed video"
    )
    audio_result = (
        "source audio" if audio_status == "preserved" else "audio removed"
    )
    return f"{subject} is ready with {audio_result}"


def set_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is not None:
            job.update(changes)


def process_video(
    job_id: str,
    video_id: str,
    selected_track_id: int,
    mode: str,
    avatar_style: str,
    blur_strength: int,
    process_scope: str,
    detector: PersonDetector,
    audio_policy: AudioPolicy = "remove",
) -> None:
    capture = None
    writer = None
    temporary: Path | None = None
    output: Path | None = None
    conservative_fallback_frames = 0
    completed = False
    try:
        set_job(
            job_id,
            status="processing",
            message="Loading video",
            audio_policy=audio_policy,
            audio_status="pending",
        )
        source = find_video(video_id)
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise RuntimeError("OpenCV could not open the uploaded video")

        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        source_frame_count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        source_frame_limit = (
            min(source_frame_count, max(1, int(fps * 10)))
            if process_scope == "preview"
            else source_frame_count
        )
        frame_step = max(1, round(fps / 15)) if process_scope == "preview" else 1
        output_fps = fps / frame_step
        frame_count = (source_frame_limit + frame_step - 1) // frame_step
        job_directory = prepare_job_output(video_id, job_id)
        temporary = job_directory / "silent.mp4"
        output = job_directory / "output.mp4"
        output_width, output_height = width, height
        if process_scope == "preview" and width > 1280:
            scale = 1280 / width
            output_width = 1280
            output_height = int(height * scale) // 2 * 2
        writer = cv2.VideoWriter(
            str(temporary),
            cv2.VideoWriter_fourcc(*"mp4v"),
            output_fps,
            (output_width, output_height),
        )
        if not writer.isOpened():
            raise RuntimeError("Could not create the output video")
        secure_file(temporary)

        detector.reset_tracking()
        avatar = load_avatar(avatar_style) if mode == "avatar" else None
        frame_number = 0
        source_frame_number = 0
        creator_track_id = selected_track_id
        creator_appearance: np.ndarray | None = None
        last_fallback_detail: str | None = None

        while True:
            if source_frame_number >= source_frame_limit:
                break
            ok, frame = capture.read()
            if not ok:
                break
            should_process = source_frame_number % frame_step == 0
            source_frame_number += 1
            if not should_process:
                continue
            if (output_width, output_height) != (width, height):
                frame = cv2.resize(
                    frame,
                    (output_width, output_height),
                    interpolation=cv2.INTER_AREA,
                )
            tracks = detector.track(frame)

            track_appearances = {
                track.track_id: appearance_histogram(frame, track.bbox)
                for track in tracks
            }
            if creator_appearance is None:
                selected = next(
                    (track for track in tracks if track.track_id == selected_track_id),
                    None,
                )
                if selected is not None:
                    creator_appearance = track_appearances[selected.track_id]

            candidates = [
                CreatorCandidate(
                    track_id=track.track_id,
                    detection_confidence=track.confidence,
                    appearance_distance=(
                        appearance_distance(
                            creator_appearance,
                            track_appearances[track.track_id],
                        )
                        if creator_appearance is not None
                        else None
                    ),
                )
                for track in tracks
            ]
            decision = select_creator_exemption(creator_track_id, candidates)
            if decision.reason == "unique_appearance_recovery":
                logger.info(
                    "[%s] Creator track recovered with unique appearance "
                    "evidence: %s -> %s",
                    job_id,
                    creator_track_id,
                    decision.next_creator_track_id,
                )
            elif decision.reason == "conservative_fallback" and tracks:
                conservative_fallback_frames += 1
                if decision.fallback_detail != last_fallback_detail:
                    logger.warning(
                        "[%s] Conservative privacy fallback (%s); "
                        "blurring all detected people",
                        job_id,
                        decision.fallback_detail,
                    )
                last_fallback_detail = decision.fallback_detail
            else:
                last_fallback_detail = None
            creator_track_id = decision.next_creator_track_id

            for track in tracks:
                if track.track_id == decision.exempt_track_id:
                    continue
                if decision.exempt_track_id is None or mode == "blur":
                    blur_person(frame, track.bbox, blur_strength, track.mask)
                else:
                    overlay_avatar(frame, track.bbox, avatar)
            writer.write(frame)
            frame_number += 1

            if frame_number == 1 or frame_number % 10 == 0:
                progress = min(99, int(frame_number / frame_count * 100))
                message = f"Protecting frame {frame_number} of {frame_count}"
                set_job(
                    job_id,
                    progress=progress,
                    message=message,
                    conservative_fallback_frames=conservative_fallback_frames,
                )
                logger.info("[%s] %s (%d%%)", job_id, message, progress)

        if frame_number == 0:
            raise RuntimeError("The uploaded file did not contain readable video frames")
        writer.release()
        writer = None
        capture.release()
        capture = None

        set_job(
            job_id,
            progress=99,
            message=(
                "Finalizing with source audio"
                if audio_policy == "preserve"
                else "Finalizing with audio removed"
            ),
            conservative_fallback_frames=conservative_fallback_frames,
        )
        audio_status = finalize_output(
            temporary,
            source,
            output,
            VIDEO_ENCODER,
            audio_policy,
        )
        secure_file(output)

        set_job(
            job_id,
            status="complete",
            progress=100,
            message=completion_message(process_scope, audio_status),
            output_ready=True,
            process_scope=process_scope,
            audio_policy=audio_policy,
            audio_status=audio_status,
            conservative_fallback_frames=conservative_fallback_frames,
        )
        completed = True
    except AudioPreservationError as exc:
        logger.exception("Audio preservation failed for job %s", job_id)
        if writer is not None:
            writer.release()
            writer = None
        if capture is not None:
            capture.release()
            capture = None
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if output is not None:
            output.unlink(missing_ok=True)
        set_job(
            job_id,
            status="failed",
            message=str(exc),
            audio_policy=audio_policy,
            audio_status="preserve_failed",
            conservative_fallback_frames=conservative_fallback_frames,
        )
    except Exception as exc:
        logger.exception("Video processing failed for job %s", job_id)
        if writer is not None:
            writer.release()
            writer = None
        if capture is not None:
            capture.release()
            capture = None
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if output is not None:
            output.unlink(missing_ok=True)
        set_job(
            job_id,
            status="failed",
            message=str(exc),
            conservative_fallback_frames=conservative_fallback_frames,
        )
    finally:
        if writer is not None:
            writer.release()
        if capture is not None:
            capture.release()
        if not completed:
            delete_output_job(video_id, job_id)


def create_job(
    video_id: str,
    process_scope: str = "full",
    audio_policy: AudioPolicy = "remove",
) -> str:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Waiting to process",
            "output_url": None,
            "output_ready": False,
            "process_scope": process_scope,
            "audio_policy": audio_policy,
            "audio_status": "pending",
            "conservative_fallback_frames": 0,
            "video_id": video_id,
            "created_at": time.time(),
        }
    return job_id
