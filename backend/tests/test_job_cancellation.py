"""Cancellation makes DELETE and TTL cleanup stop active local work."""

from pathlib import Path

import cv2
import numpy as np

from app import processor
from app.processor import cancel_video_jobs, create_job, process_video
from app.tracker import Track


VIDEO_A = "a" * 32
VIDEO_B = "b" * 32


def authorized(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TrackingCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        return {
            cv2.CAP_PROP_FPS: 30.0,
            cv2.CAP_PROP_FRAME_WIDTH: 160,
            cv2.CAP_PROP_FRAME_HEIGHT: 120,
            cv2.CAP_PROP_FRAME_COUNT: len(self.frames),
        }[prop]

    def read(self):
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index].copy()
        self.index += 1
        return True, frame

    def release(self):
        self.released = True


class TrackingWriter:
    def __init__(self, path):
        self.path = Path(path)
        self.frames = []
        self.released = False

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.released = True
        self.path.write_bytes(b"partial")


class CancelOnSecondDetection:
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def reset_tracking(self):
        self.calls = 0

    def track(self, frame):  # noqa: ARG002
        self.calls += 1
        if self.calls == 2:
            cancel_video_jobs(VIDEO_A, drop_records=True)
        return [Track(1, (10, 10, 50, 100), 0.95)]


class ActiveProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def test_cancelled_render_stops_between_frames_and_removes_partial_output(
    video_session, output_dir, monkeypatch
):
    video_session(VIDEO_A)
    frames = [np.zeros((120, 160, 3), dtype=np.uint8) for _ in range(6)]
    capture = TrackingCapture(frames)
    writers = []
    monkeypatch.setattr(processor.cv2, "VideoCapture", lambda _: capture)

    def make_writer(path, *args):  # noqa: ARG001
        writer = TrackingWriter(path)
        writers.append(writer)
        return writer

    monkeypatch.setattr(processor.cv2, "VideoWriter", make_writer)
    monkeypatch.setattr(processor.cv2, "VideoWriter_fourcc", lambda *args: 0)
    monkeypatch.setattr(processor.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        processor,
        "appearance_histogram",
        lambda frame, bbox: np.array([10], dtype=np.float32),
    )
    monkeypatch.setattr(processor, "appearance_distance", lambda ref, value: 0.0)
    detector = CancelOnSecondDetection()
    job_id = create_job(VIDEO_A)

    process_video(
        job_id,
        VIDEO_A,
        selected_track_id=1,
        mode="blur",
        avatar_style="sunny",
        blur_strength=40,
        process_scope="full",
        detector=detector,
        creator_appearance=np.array([10], dtype=np.float32),
    )

    assert detector.calls == 2
    assert capture.released is True
    assert writers[0].released is True
    assert not (output_dir / VIDEO_A).exists()
    assert job_id not in processor.jobs
    assert job_id not in processor.job_runtimes


def test_cancel_video_jobs_only_targets_the_requested_video():
    job_a = create_job(VIDEO_A)
    job_b = create_job(VIDEO_B)

    cancelled = cancel_video_jobs(VIDEO_A, drop_records=True)

    assert cancelled == {job_a}
    assert job_a not in processor.jobs
    assert job_a not in processor.job_runtimes
    assert job_b in processor.jobs
    assert job_b in processor.job_runtimes


def test_delete_terminates_active_encoder_and_revokes_job_record(
    api, video_session
):
    directory, token = video_session(VIDEO_A)
    job_id = create_job(VIDEO_A)
    active_process = ActiveProcess()
    with processor.jobs_lock:
        processor.jobs[job_id]["status"] = "processing"
        processor.job_runtimes[job_id].active_process = active_process

    response = api.delete(
        f"/api/videos/{VIDEO_A}", headers=authorized(token)
    )

    assert response.status_code == 204
    assert active_process.terminated is True
    assert job_id not in processor.jobs
    assert job_id not in processor.job_runtimes
    assert not directory.exists()


def test_ttl_cleanup_cancels_expired_active_job_and_prunes_memory(
    video_session
):
    from app import main

    directory, _token = video_session(VIDEO_A)
    (directory / ".expires_at").write_text("100", encoding="ascii")
    job_id = create_job(VIDEO_A)
    with processor.jobs_lock:
        processor.jobs[job_id]["status"] = "processing"

    removed = main.cleanup_expired_media(now=200)

    assert removed == {VIDEO_A}
    assert not directory.exists()
    assert job_id not in processor.jobs
    assert job_id not in processor.job_runtimes

