from pathlib import Path

import cv2
import numpy as np
import pytest

from app import processor
from app.processor import (
    AudioPreservationError,
    create_job,
    ffmpeg_command,
    finalize_output,
    process_video,
)
from app.storage import prepare_job_output, resolve_output
from app.tracker import Track


VALID_VIDEO_ID = "0123456789abcdef" * 2


def test_remove_audio_command_never_reads_or_maps_the_source_audio(tmp_path):
    temporary = tmp_path / "silent.mp4"
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"

    command = ffmpeg_command(
        temporary,
        source,
        output,
        "libx264",
        "remove",
    )

    assert command.count("-i") == 1
    assert str(source) not in command
    assert command[command.index("-map") + 1] == "0:v:0"
    assert "-an" in command
    assert "-c:a" not in command


def test_preserve_audio_command_requires_the_source_audio_stream(tmp_path):
    temporary = tmp_path / "silent.mp4"
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"

    command = ffmpeg_command(
        temporary,
        source,
        output,
        "libx264",
        "preserve",
    )

    assert command.count("-i") == 2
    assert str(source) in command
    assert "1:a:0" in command
    assert "1:a:0?" not in command
    assert command[command.index("-c:a") + 1] == "aac"
    assert "-an" not in command


def test_remove_policy_stays_silent_when_ffmpeg_is_unavailable(tmp_path, monkeypatch):
    temporary = tmp_path / "silent.mp4"
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    temporary.write_bytes(b"silent video")
    source.write_bytes(b"source video")
    monkeypatch.setattr(processor.shutil, "which", lambda _: None)

    status = finalize_output(temporary, source, output, "libx264", "remove")

    assert status == "removed"
    assert output.read_bytes() == b"silent video"
    assert not temporary.exists()


def test_preserve_policy_fails_instead_of_silently_removing_audio(
    tmp_path, monkeypatch
):
    temporary = tmp_path / "silent.mp4"
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    temporary.write_bytes(b"silent video")
    source.write_bytes(b"source video")
    monkeypatch.setattr(processor.shutil, "which", lambda _: None)

    with pytest.raises(AudioPreservationError, match="FFmpeg is unavailable"):
        finalize_output(temporary, source, output, "libx264", "preserve")

    assert temporary.exists()
    assert not output.exists()


def test_output_directories_isolate_jobs():
    job_a = "a" * 32
    job_b = "b" * 32

    directory_a = prepare_job_output(VALID_VIDEO_ID, job_a)
    directory_b = prepare_job_output(VALID_VIDEO_ID, job_b)

    assert directory_a != directory_b
    assert directory_a.name == job_a
    assert directory_b.name == job_b
    assert directory_a.parent == directory_b.parent


class FakeCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def isOpened(self):
        return True

    def get(self, prop):
        values = {
            cv2.CAP_PROP_FPS: 30.0,
            cv2.CAP_PROP_FRAME_WIDTH: 160,
            cv2.CAP_PROP_FRAME_HEIGHT: 120,
            cv2.CAP_PROP_FRAME_COUNT: len(self.frames),
        }
        return values[prop]

    def read(self):
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index].copy()
        self.index += 1
        return True, frame

    def release(self):
        pass


class FakeWriter:
    def __init__(self, path):
        self.path = Path(path)
        self.frames = []

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.path.write_bytes(b"silent rendered video")


class SequenceDetector:
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def reset_tracking(self):
        self.calls = 0

    def track(self, frame):  # noqa: ARG002
        self.calls += 1
        if self.calls == 1:
            return [Track(1, (10, 10, 50, 100), 0.95)]
        return [
            Track(2, (20, 10, 60, 100), 0.95),
            Track(3, (90, 10, 130, 100), 0.95),
        ]


def test_ambiguous_reid_blurs_everyone_and_records_the_fallback(
    video_session, monkeypatch
):
    video_session(VALID_VIDEO_ID)
    frames = [
        np.zeros((120, 160, 3), dtype=np.uint8),
        np.ones((120, 160, 3), dtype=np.uint8),
    ]
    monkeypatch.setattr(
        processor.cv2,
        "VideoCapture",
        lambda _: FakeCapture(frames),
    )
    writers = []

    def make_writer(path, *args):  # noqa: ARG001
        writer = FakeWriter(path)
        writers.append(writer)
        return writer

    monkeypatch.setattr(processor.cv2, "VideoWriter", make_writer)
    monkeypatch.setattr(processor.cv2, "VideoWriter_fourcc", lambda *args: 0)
    monkeypatch.setattr(processor.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        processor,
        "appearance_histogram",
        lambda frame, bbox: np.array([bbox[0]], dtype=np.float32),
    )

    def appearance_distance(reference, candidate):
        assert reference[0] == 10
        return {10: 0.0, 20: 0.10, 90: 0.16}[int(candidate[0])]

    monkeypatch.setattr(processor, "appearance_distance", appearance_distance)
    monkeypatch.setattr(
        processor,
        "load_avatar",
        lambda _: np.zeros((8, 8, 4), dtype=np.uint8),
    )
    blurred = []
    overlaid = []
    monkeypatch.setattr(
        processor,
        "blur_person",
        lambda frame, bbox, strength, mask: blurred.append(bbox),
    )
    monkeypatch.setattr(
        processor,
        "overlay_avatar",
        lambda frame, bbox, avatar: overlaid.append(bbox),
    )
    processor.jobs.clear()
    job_id = create_job(VALID_VIDEO_ID, audio_policy="remove")

    process_video(
        job_id,
        VALID_VIDEO_ID,
        selected_track_id=1,
        mode="avatar",
        avatar_style="sunny",
        blur_strength=60,
        process_scope="full",
        detector=SequenceDetector(),
        audio_policy="remove",
    )

    job = processor.jobs[job_id]
    assert job["status"] == "complete"
    assert job["audio_policy"] == "remove"
    assert job["audio_status"] == "removed"
    assert job["conservative_fallback_frames"] == 1
    assert blurred == [(20, 10, 60, 100), (90, 10, 130, 100)]
    assert overlaid == []
    assert job["output_ready"] is True
    assert resolve_output(VALID_VIDEO_ID, job_id).read_bytes() == b"silent rendered video"
    assert len(writers) == 1 and len(writers[0].frames) == 2


def test_preserve_failure_is_reported_in_job_state(
    video_session, output_dir, monkeypatch
):
    video_session(VALID_VIDEO_ID)
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    monkeypatch.setattr(
        processor.cv2,
        "VideoCapture",
        lambda _: FakeCapture([frame]),
    )
    monkeypatch.setattr(
        processor.cv2,
        "VideoWriter",
        lambda path, *args: FakeWriter(path),
    )
    monkeypatch.setattr(processor.cv2, "VideoWriter_fourcc", lambda *args: 0)
    monkeypatch.setattr(
        processor,
        "appearance_histogram",
        lambda frame, bbox: np.array([bbox[0]], dtype=np.float32),
    )
    monkeypatch.setattr(processor, "appearance_distance", lambda ref, value: 0.0)

    def fail_preservation(*args, **kwargs):  # noqa: ARG001
        raise AudioPreservationError("Audio preservation failed safely")

    monkeypatch.setattr(processor, "finalize_output", fail_preservation)
    processor.jobs.clear()
    job_id = create_job(VALID_VIDEO_ID, audio_policy="preserve")

    process_video(
        job_id,
        VALID_VIDEO_ID,
        selected_track_id=1,
        mode="blur",
        avatar_style="sunny",
        blur_strength=60,
        process_scope="full",
        detector=SequenceDetector(),
        audio_policy="preserve",
    )

    job = processor.jobs[job_id]
    assert job["status"] == "failed"
    assert job["audio_policy"] == "preserve"
    assert job["audio_status"] == "preserve_failed"
    assert job["output_url"] is None
    assert job["message"] == "Audio preservation failed safely"
    assert not (output_dir / VALID_VIDEO_ID).exists()
