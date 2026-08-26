"""Shared test setup.

Two things must happen before ``app.config`` is imported anywhere, so they run
at module import time rather than inside a fixture:

1. The upload/output/avatar directories are redirected into a throwaway
   temporary tree. ``app.main`` mounts these paths as static directories at
   import time, so redirecting them later would be too late.
2. Nothing in the suite may reach the network or load a YOLO model.
"""

import os
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

# Resolved because config.py resolves its overrides, and on macOS the temp dir
# is reached through a /var -> /private/var symlink.
TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="publishsafe-tests-")).resolve()

os.environ["PUBLISHSAFE_UPLOAD_DIR"] = str(TEST_MEDIA_ROOT / "uploads")
os.environ["PUBLISHSAFE_OUTPUT_DIR"] = str(TEST_MEDIA_ROOT / "outputs")
os.environ["PUBLISHSAFE_AVATAR_DIR"] = str(TEST_MEDIA_ROOT / "avatars")

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_MEDIA_DIRS = (REPO_ROOT / "uploads", REPO_ROOT / "outputs")


def real_media_contents() -> dict[str, set[str]]:
    """What the developer's real media folders hold right now.

    These are gitignored working folders, so they are rarely empty on a
    developer machine. The suite asserts it does not *add* to them rather than
    asserting they are empty.
    """
    return {
        directory.name: {entry.name for entry in directory.iterdir()}
        if directory.exists()
        else set()
        for directory in REAL_MEDIA_DIRS
    }


# Captured at import time, before any test has had a chance to write.
REAL_MEDIA_SNAPSHOT = real_media_contents()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)


def _model_weight_snapshot() -> set[Path]:
    """Every ``*.pt`` file in the places a YOLO download would land."""
    roots = [
        REPO_ROOT,
        Path.home() / ".cache" / "torch",
        Path.home() / ".config" / "Ultralytics",
        Path.home() / "Library" / "Application Support" / "Ultralytics",
    ]
    found: set[Path] = set()
    for root in roots:
        if root.exists():
            found.update(root.rglob("*.pt"))
    return found


@pytest.fixture(scope="session", autouse=True)
def guard_against_model_downloads():
    """Fail the run if a test pulls down model weights."""
    before = _model_weight_snapshot()
    yield
    new_weights = _model_weight_snapshot() - before
    assert not new_weights, f"tests downloaded model weights: {sorted(new_weights)}"


@pytest.fixture(scope="session", autouse=True)
def guard_real_media_dirs():
    """Fail the run if a test writes into the real uploads/outputs folders."""
    yield
    for name, before in REAL_MEDIA_SNAPSHOT.items():
        added = real_media_contents()[name] - before
        assert not added, f"tests wrote into the real {name}/ folder: {sorted(added)}"


@pytest.fixture(scope="session")
def real_media_snapshot():
    return REAL_MEDIA_SNAPSHOT


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch):
    """Make any outbound connection attempt an immediate, obvious failure.

    Only outbound connects are blocked; socket objects themselves still work so
    that the ASGI test transport is unaffected.
    """

    def refuse(*args, **kwargs):
        raise RuntimeError("network access is not allowed in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class StubDetector:
    """Stands in for PersonDetector so no model is ever constructed."""

    def __init__(self, device: str = "cpu", tracks: list | None = None):
        self.device = device
        self.tracks = tracks or []
        self.reset_calls = 0

    def reset_tracking(self) -> None:
        self.reset_calls += 1

    def track(self, frame):  # noqa: ARG002
        return list(self.tracks)


@pytest.fixture
def api():
    """A TestClient that never triggers the model-loading lifespan.

    Starlette only runs lifespan handlers when TestClient is used as a context
    manager, so constructing it directly keeps ``main.detector`` as ``None``.
    """
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app)


@pytest.fixture
def stub_detector(monkeypatch):
    from app import main

    detector = StubDetector()
    monkeypatch.setattr(main, "detector", detector)
    return detector


@pytest.fixture
def upload_dir():
    from app.config import UPLOAD_DIR

    return UPLOAD_DIR


@pytest.fixture(autouse=True)
def clean_media_dirs():
    """Keep every test's view of the media directories independent."""
    from app.config import OUTPUT_DIR, UPLOAD_DIR

    yield
    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        for entry in directory.iterdir():
            if entry.is_file():
                entry.unlink()
            else:
                shutil.rmtree(entry, ignore_errors=True)
