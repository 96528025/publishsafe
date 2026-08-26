"""Guards for the constraints CI depends on.

If these fail, the suite has started pulling in the heavy ML stack or writing
into the real media folders — the two things CI is built to avoid.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_MEDIA_ROOT = Path(os.environ["PUBLISHSAFE_UPLOAD_DIR"]).parent


def test_importing_the_api_does_not_load_ultralytics_or_torch():
    import app.main  # noqa: F401

    assert "ultralytics" not in sys.modules
    assert "torch" not in sys.modules


def test_media_paths_are_redirected_out_of_the_repository():
    from app.config import OUTPUT_DIR, UPLOAD_DIR

    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        assert directory.is_relative_to(TEST_MEDIA_ROOT)
        assert not directory.is_relative_to(REPO_ROOT)


def test_the_suite_adds_nothing_to_the_real_media_folders(real_media_snapshot):
    """uploads/ and outputs/ are gitignored working folders, not necessarily
    empty — what matters is that the suite leaves them exactly as it found them."""
    for name, before in real_media_snapshot.items():
        current = {entry.name for entry in (REPO_ROOT / name).iterdir()}
        assert current - before == set()


def test_no_model_weights_are_written_during_the_test_run():
    assert list(TEST_MEDIA_ROOT.rglob("*.pt")) == []
