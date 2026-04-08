"""Edge-case tests: permission errors during deletion and scan.

Validates that PermissionError, OSError(EACCES), and OSError(EROFS) raised
by Path.unlink(), shutil.move(), Path.symlink_to(), os.link(), and send2trash()
are caught and reported without aborting the session.
"""

from __future__ import annotations

import errno
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from duplicates_detector.advisor import (
    review_duplicates,
    review_groups,
)
from duplicates_detector.deleter import (
    HardlinkDeleter,
    MoveDeleter,
    PermanentDeleter,
    SymlinkDeleter,
    TrashDeleter,
)
from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(
    name: str = "a.mp4",
    file_size: int = 1_000_000,
    is_reference: bool = False,
    duration: float | None = 120.0,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/videos/{name}"),
        filename=Path(name).stem,
        duration=duration,
        width=1920,
        height=1080,
        file_size=file_size,
        is_reference=is_reference,
        sidecars=(),  # skip sidecar discovery on fake paths
    )


def _make_pair(
    a: str = "a.mp4",
    b: str = "b.mp4",
    score: float = 80.0,
    a_file_size: int = 1_000_000,
    b_file_size: int = 2_000_000,
) -> ScoredPair:
    return ScoredPair(
        file_a=_make_meta(a, file_size=a_file_size),
        file_b=_make_meta(b, file_size=b_file_size),
        total_score=score,
        breakdown={"filename": 30.0, "duration": 35.0},
        detail={},
    )


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, highlight=False, width=200), buf


# ---------------------------------------------------------------------------
# Permission errors during deletion
# ---------------------------------------------------------------------------


class TestPermissionErrorDuringDeletion:
    def test_permission_error_unlink_continues_session(self):
        """Path.unlink() raises PermissionError → error recorded, other pairs processed."""
        pairs = [_make_pair("a.mp4", "b.mp4"), _make_pair("c.mp4", "d.mp4")]
        con, buf = _console()

        call_count = 0

        def mock_remove(path, *, link_target=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("Permission denied")
            from duplicates_detector.deleter import DeletionResult

            return DeletionResult(path=path, bytes_freed=1_000_000)

        deleter = PermanentDeleter()
        with (
            patch.object(deleter, "remove", side_effect=mock_remove),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
        ):
            summary = review_duplicates(pairs, console=con, deleter=deleter)

        assert len(summary.errors) == 1
        assert "Permission denied" in summary.errors[0][1]
        assert len(summary.deleted) == 1  # second pair succeeded

    def test_readonly_fs_error_continues(self):
        """OSError(EROFS) on deletion → caught, session continues."""
        pairs = [_make_pair()]
        con, buf = _console()

        deleter = PermanentDeleter()
        with (
            patch.object(deleter, "remove", side_effect=OSError(errno.EROFS, "Read-only file system")),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
        ):
            summary = review_duplicates(pairs, console=con, deleter=deleter)

        assert len(summary.errors) == 1

    def test_eacces_on_stat_for_size_in_dry_run(self):
        """Path.stat() raises PermissionError during dry-run size calc → OSError caught."""
        pairs = [_make_pair()]
        con, buf = _console()

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", side_effect=OSError(errno.EACCES, "Permission denied")),
        ):
            summary = review_duplicates(pairs, console=con, dry_run=True)

        # The OSError is caught by the generic OSError handler
        assert len(summary.errors) == 1

    def test_permission_error_in_group_mode(self):
        """Group review with PermissionError on one file → other files still deletable."""
        meta_a = _make_meta("a.mp4", file_size=1_000_000)
        meta_b = _make_meta("b.mp4", file_size=2_000_000)
        meta_c = _make_meta("c.mp4", file_size=3_000_000)

        group = DuplicateGroup(
            group_id=0,
            members=(meta_a, meta_b, meta_c),
            pairs=(),
            min_score=80.0,
            max_score=90.0,
            avg_score=85.0,
        )

        con, buf = _console()

        call_count = 0

        def mock_remove(path, *, link_target=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("Permission denied")
            from duplicates_detector.deleter import DeletionResult

            return DeletionResult(path=path, bytes_freed=2_000_000)

        deleter = PermanentDeleter()
        with (
            patch.object(deleter, "remove", side_effect=mock_remove),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="1"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=2_000_000)),
        ):
            summary = review_groups([group], console=con, deleter=deleter)

        assert len(summary.errors) == 1
        assert len(summary.deleted) == 1  # second deletion succeeded

    def test_move_permission_error(self, tmp_path: Path):
        """shutil.move() raises PermissionError → error reported, file left in place."""
        pairs = [_make_pair()]
        con, buf = _console()

        deleter = MoveDeleter(tmp_path)
        with (
            patch.object(deleter, "remove", side_effect=PermissionError("Permission denied")),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
        ):
            summary = review_duplicates(pairs, console=con, deleter=deleter)

        assert len(summary.errors) == 1

    def test_hardlink_permission_error(self):
        """os.link() raises PermissionError → error reported."""
        pairs = [_make_pair()]
        con, buf = _console()

        deleter = HardlinkDeleter()
        with (
            patch.object(deleter, "remove", side_effect=PermissionError("Permission denied")),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
        ):
            summary = review_duplicates(pairs, console=con, deleter=deleter)

        assert len(summary.errors) == 1

    def test_symlink_permission_error(self):
        """Path.symlink_to() raises PermissionError → error reported."""
        pairs = [_make_pair()]
        con, buf = _console()

        deleter = SymlinkDeleter()
        with (
            patch.object(deleter, "remove", side_effect=PermissionError("Permission denied")),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
        ):
            summary = review_duplicates(pairs, console=con, deleter=deleter)

        assert len(summary.errors) == 1

    def test_trash_permission_error(self):
        """send2trash() raises OSError → caught, file left in place."""
        pairs = [_make_pair()]
        con, buf = _console()

        deleter = TrashDeleter()
        with (
            patch.object(deleter, "remove", side_effect=OSError("Trash failed")),
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
        ):
            summary = review_duplicates(pairs, console=con, deleter=deleter)

        assert len(summary.errors) == 1


# ---------------------------------------------------------------------------
# Permission errors during scan/extraction
# ---------------------------------------------------------------------------


class TestPermissionErrorDuringScan:
    def test_unreadable_file_in_metadata_extraction(self, tmp_path: Path):
        """ffprobe subprocess raises PermissionError → None metadata."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)

        with patch(
            "duplicates_detector.metadata.subprocess.run",
            side_effect=OSError(errno.EACCES, "Permission denied"),
        ):
            from duplicates_detector.metadata import extract_one

            meta = extract_one(f)

        # OSError during subprocess.run is caught, fields are None
        assert meta is not None
        assert meta.duration is None

    def test_unreadable_file_during_image_content_hash(self, tmp_path: Path):
        """PIL.Image.open raises PermissionError → returns None."""
        f = tmp_path / "image.jpg"
        f.write_bytes(b"\x00" * 100)

        with patch("duplicates_detector.content.Image.open", side_effect=PermissionError("denied")):
            from duplicates_detector.content import compute_image_content_hash

            result = compute_image_content_hash(f)

        assert result is None
