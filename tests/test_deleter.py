from __future__ import annotations

import errno
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.deleter import (
    DeletionResult,
    HardlinkDeleter,
    MoveDeleter,
    PermanentDeleter,
    ReflinkDeleter,
    SymlinkDeleter,
    TrashDeleter,
    make_deleter,
)


# ---------------------------------------------------------------------------
# PermanentDeleter
# ---------------------------------------------------------------------------


class TestPermanentDeleter:
    def test_removes_file(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 100)
        deleter = PermanentDeleter()
        deleter.remove(f)
        assert not f.exists()

    def test_returns_correct_size(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 256)
        result = PermanentDeleter().remove(f)
        assert result.bytes_freed == 256

    def test_returns_path(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        result = PermanentDeleter().remove(f)
        assert result.path == f

    def test_destination_is_none(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        result = PermanentDeleter().remove(f)
        assert result.destination is None

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.mp4"
        with pytest.raises(FileNotFoundError):
            PermanentDeleter().remove(f)

    def test_permission_error(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        with patch.object(Path, "unlink", side_effect=PermissionError("nope")):
            with pytest.raises(PermissionError):
                PermanentDeleter().remove(f)

    def test_verb_properties(self) -> None:
        d = PermanentDeleter()
        assert d.verb == "Deleted"
        assert d.dry_verb == "Would delete"
        assert d.prompt_verb == "Delete"

    def test_gerund(self) -> None:
        assert PermanentDeleter().gerund == "Deleting"


# ---------------------------------------------------------------------------
# TrashDeleter
# ---------------------------------------------------------------------------


class TestTrashDeleter:
    def test_calls_send2trash(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 200)
        mock_s2t_fn = MagicMock()
        mock_module = MagicMock()
        mock_module.send2trash = mock_s2t_fn
        with patch.dict("sys.modules", {"send2trash": mock_module}):
            result = TrashDeleter().remove(f)
        mock_s2t_fn.assert_called_once_with(str(f))
        assert result.bytes_freed == 200

    def test_returns_correct_result(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 50)
        mock_module = MagicMock()
        with patch.dict("sys.modules", {"send2trash": mock_module}):
            result = TrashDeleter().remove(f)
        assert result.path == f
        assert result.destination is None

    def test_verb_properties(self) -> None:
        d = TrashDeleter()
        assert d.verb == "Trashed"
        assert d.dry_verb == "Would trash"
        assert d.prompt_verb == "Trash"

    def test_gerund(self) -> None:
        assert TrashDeleter().gerund == "Trashing"

    def test_import_error_propagates(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        with patch.dict("sys.modules", {"send2trash": None}):
            with pytest.raises((ImportError, TypeError)):
                TrashDeleter().remove(f)


# ---------------------------------------------------------------------------
# MoveDeleter
# ---------------------------------------------------------------------------


class TestMoveDeleter:
    def test_moves_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        f = src / "video.mp4"
        f.write_bytes(b"x" * 300)
        deleter = MoveDeleter(dst)
        deleter.remove(f)
        assert not f.exists()
        assert (dst / "video.mp4").exists()

    def test_returns_destination_path(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        f = src / "video.mp4"
        f.write_bytes(b"x" * 10)
        result = MoveDeleter(dst).remove(f)
        assert result.destination == dst / "video.mp4"

    def test_returns_correct_size(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        f = src / "video.mp4"
        f.write_bytes(b"x" * 512)
        result = MoveDeleter(dst).remove(f)
        assert result.bytes_freed == 512

    def test_collision_appends_counter(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        # Pre-existing file in destination
        (dst / "video.mp4").write_bytes(b"existing")
        f = src / "video.mp4"
        f.write_bytes(b"x" * 10)
        result = MoveDeleter(dst).remove(f)
        assert result.destination == dst / "video_1.mp4"
        assert (dst / "video_1.mp4").exists()

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (dst / "video.mp4").write_bytes(b"a")
        (dst / "video_1.mp4").write_bytes(b"b")
        f = src / "video.mp4"
        f.write_bytes(b"x" * 10)
        result = MoveDeleter(dst).remove(f)
        assert result.destination == dst / "video_2.mp4"

    def test_preserves_extension(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (dst / "clip.mkv").write_bytes(b"a")
        f = src / "clip.mkv"
        f.write_bytes(b"x" * 10)
        result = MoveDeleter(dst).remove(f)
        assert result.destination is not None
        assert result.destination.name == "clip_1.mkv"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        dst = tmp_path / "dst"
        dst.mkdir()
        f = tmp_path / "nonexistent.mp4"
        with pytest.raises(FileNotFoundError):
            MoveDeleter(dst).remove(f)

    def test_verb_properties(self) -> None:
        d = MoveDeleter(Path("/tmp"))
        assert d.verb == "Moved"
        assert d.dry_verb == "Would move"
        assert d.prompt_verb == "Move"

    def test_gerund(self) -> None:
        assert MoveDeleter(Path("/tmp")).gerund == "Moving"


# ---------------------------------------------------------------------------
# make_deleter factory
# ---------------------------------------------------------------------------


class TestMakeDeleter:
    def test_delete_returns_permanent(self) -> None:
        assert isinstance(make_deleter("delete"), PermanentDeleter)

    def test_trash_returns_trash(self) -> None:
        assert isinstance(make_deleter("trash"), TrashDeleter)

    def test_move_to_returns_move(self, tmp_path: Path) -> None:
        d = make_deleter("move-to", move_to_dir=tmp_path)
        assert isinstance(d, MoveDeleter)

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown action"):
            make_deleter("nuke")

    def test_move_to_without_dir_raises(self) -> None:
        with pytest.raises(ValueError, match="move_to_dir is required"):
            make_deleter("move-to")


# ---------------------------------------------------------------------------
# DeletionResult
# ---------------------------------------------------------------------------


class TestHardlinkDeleter:
    def test_creates_hardlink(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        result = HardlinkDeleter().remove(src, link_target=target)
        assert src.exists()
        # Same inode → hardlink
        assert src.stat().st_ino == target.stat().st_ino
        assert result.bytes_freed == 100
        assert result.destination == target

    def test_preserves_content(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 50)
        target.write_bytes(b"original content")
        HardlinkDeleter().remove(src, link_target=target)
        assert src.read_bytes() == b"original content"

    def test_missing_link_target_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        with pytest.raises(ValueError, match="link_target is required"):
            HardlinkDeleter().remove(f)

    def test_verb_properties(self) -> None:
        d = HardlinkDeleter()
        assert d.verb == "Hardlinked"
        assert d.dry_verb == "Would hardlink"
        assert d.prompt_verb == "Hardlink"

    def test_gerund(self) -> None:
        assert HardlinkDeleter().gerund == "Hardlinking"

    def test_preserves_original_on_link_failure(self, tmp_path: Path) -> None:
        """If os.link fails (e.g. EXDEV), original file must remain intact."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"precious data")
        target.write_bytes(b"y" * 200)
        with patch("duplicates_detector.deleter.os.link", side_effect=OSError(errno.EXDEV, "Cross-device link")):
            with pytest.raises(OSError, match="Cross-device link"):
                HardlinkDeleter().remove(src, link_target=target)
        assert src.exists()
        assert src.read_bytes() == b"precious data"

    def test_long_filename(self, tmp_path: Path) -> None:
        """Filenames near NAME_MAX don't fail due to temp name overflow."""
        long_name = "x" * 240 + ".mp4"  # 244 chars, near NAME_MAX of 255
        src = tmp_path / long_name
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        result = HardlinkDeleter().remove(src, link_target=target)
        assert src.exists()
        assert src.stat().st_ino == target.stat().st_ino
        assert result.bytes_freed == 100

    def test_no_temp_files_after_failure(self, tmp_path: Path) -> None:
        """No .tmp files left behind after a failed hardlink attempt."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        with patch("duplicates_detector.deleter.os.link", side_effect=OSError(errno.EXDEV, "Cross-device link")):
            with pytest.raises(OSError):
                HardlinkDeleter().remove(src, link_target=target)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


class TestSymlinkDeleter:
    def test_creates_symlink(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        result = SymlinkDeleter().remove(src, link_target=target)
        assert src.is_symlink()
        assert src.resolve() == target.resolve()
        assert result.bytes_freed == 100
        assert result.destination == target

    def test_preserves_content(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 50)
        target.write_bytes(b"original content")
        SymlinkDeleter().remove(src, link_target=target)
        assert src.read_bytes() == b"original content"

    def test_missing_link_target_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        with pytest.raises(ValueError, match="link_target is required"):
            SymlinkDeleter().remove(f)

    def test_verb_properties(self) -> None:
        d = SymlinkDeleter()
        assert d.verb == "Symlinked"
        assert d.dry_verb == "Would symlink"
        assert d.prompt_verb == "Symlink"

    def test_gerund(self) -> None:
        assert SymlinkDeleter().gerund == "Symlinking"

    def test_preserves_original_on_link_failure(self, tmp_path: Path) -> None:
        """If symlink_to fails, original file must remain intact."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"precious data")
        target.write_bytes(b"y" * 200)
        with patch("duplicates_detector.deleter.Path.symlink_to", side_effect=PermissionError("nope")):
            with pytest.raises(PermissionError):
                SymlinkDeleter().remove(src, link_target=target)
        assert src.exists()
        assert src.read_bytes() == b"precious data"

    def test_no_temp_files_after_failure(self, tmp_path: Path) -> None:
        """No .tmp files left behind after a failed symlink attempt."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        with patch("duplicates_detector.deleter.Path.symlink_to", side_effect=PermissionError("nope")):
            with pytest.raises(PermissionError):
                SymlinkDeleter().remove(src, link_target=target)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# ReflinkDeleter
# ---------------------------------------------------------------------------


class TestReflinkDeleter:
    @staticmethod
    def _fake_reflink(_src: Path, dst: Path) -> None:
        """Simulate a reflink by writing dummy content at the destination."""
        dst.write_bytes(b"reflinked")

    def test_creates_reflink(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"original content")
        with patch("duplicates_detector.deleter._create_reflink", side_effect=self._fake_reflink) as mock_reflink:
            result = ReflinkDeleter().remove(src, link_target=target)
        mock_reflink.assert_called_once()
        assert result.bytes_freed == 100
        assert result.destination == target

    def test_missing_link_target_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"x" * 10)
        with pytest.raises(ValueError, match="link_target is required"):
            ReflinkDeleter().remove(f)

    def test_reports_bytes_freed(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 512)
        target.write_bytes(b"y" * 200)
        with patch("duplicates_detector.deleter._create_reflink", side_effect=self._fake_reflink):
            result = ReflinkDeleter().remove(src, link_target=target)
        assert result.bytes_freed == 512

    def test_destination_is_link_target(self, tmp_path: Path) -> None:
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 10)
        target.write_bytes(b"y" * 10)
        with patch("duplicates_detector.deleter._create_reflink", side_effect=self._fake_reflink):
            result = ReflinkDeleter().remove(src, link_target=target)
        assert result.destination == target

    def test_verb_properties(self) -> None:
        d = ReflinkDeleter()
        assert d.verb == "Reflinked"
        assert d.dry_verb == "Would reflink"
        assert d.prompt_verb == "Reflink"

    def test_gerund(self) -> None:
        assert ReflinkDeleter().gerund == "Reflinking"

    def test_preserves_original_on_reflink_failure(self, tmp_path: Path) -> None:
        """If _create_reflink fails, original file must remain intact."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"precious data")
        target.write_bytes(b"y" * 200)
        with patch(
            "duplicates_detector.deleter._create_reflink",
            side_effect=OSError("Reflink not supported"),
        ):
            with pytest.raises(OSError, match="Reflink not supported"):
                ReflinkDeleter().remove(src, link_target=target)
        assert src.exists()
        assert src.read_bytes() == b"precious data"

    def test_no_temp_files_after_failure(self, tmp_path: Path) -> None:
        """No .tmp files left behind after a failed reflink attempt."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        with patch(
            "duplicates_detector.deleter._create_reflink",
            side_effect=OSError("Reflink not supported"),
        ):
            with pytest.raises(OSError):
                ReflinkDeleter().remove(src, link_target=target)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_non_cow_filesystem_error(self, tmp_path: Path) -> None:
        """OSError from non-CoW filesystem is propagated with clear message."""
        src = tmp_path / "dup.mp4"
        target = tmp_path / "original.mp4"
        src.write_bytes(b"x" * 100)
        target.write_bytes(b"y" * 200)
        with patch(
            "duplicates_detector.deleter._create_reflink",
            side_effect=OSError(errno.EOPNOTSUPP, "Operation not supported"),
        ):
            with pytest.raises(OSError):
                ReflinkDeleter().remove(src, link_target=target)


class TestReflinkCreation:
    def test_dispatches_to_cp_macos(self, tmp_path: Path) -> None:
        """macOS uses cp -c."""
        src = tmp_path / "src.mp4"
        dst = tmp_path / "dst.mp4"
        src.write_bytes(b"reflink content")
        with (
            patch("duplicates_detector.deleter.sys.platform", "darwin"),
            patch("duplicates_detector.deleter._reflink_via_cp_macos") as mock_cp,
        ):
            from duplicates_detector.deleter import _create_reflink

            _create_reflink(src, dst)
        mock_cp.assert_called_once_with(src, dst)

    def test_dispatches_to_cp_linux(self, tmp_path: Path) -> None:
        """Linux uses cp --reflink=always."""
        src = tmp_path / "src.mp4"
        dst = tmp_path / "dst.mp4"
        src.write_bytes(b"reflink content")
        with (
            patch("duplicates_detector.deleter.sys.platform", "linux"),
            patch("duplicates_detector.deleter._reflink_via_cp_linux") as mock_cp,
        ):
            from duplicates_detector.deleter import _create_reflink

            _create_reflink(src, dst)
        mock_cp.assert_called_once_with(src, dst)

    def test_cp_macos_failure_raises_oserror(self) -> None:
        """Non-zero cp -c exit raises OSError with descriptive message."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"not supported"
        with patch("duplicates_detector.deleter.subprocess.run", return_value=mock_result):
            from duplicates_detector.deleter import _reflink_via_cp_macos

            with pytest.raises(OSError, match="Reflink failed"):
                _reflink_via_cp_macos(Path("/a"), Path("/b"))

    def test_cp_linux_failure_raises_oserror(self) -> None:
        """Non-zero cp --reflink=always exit raises OSError with descriptive message."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"not supported"
        with patch("duplicates_detector.deleter.subprocess.run", return_value=mock_result):
            from duplicates_detector.deleter import _reflink_via_cp_linux

            with pytest.raises(OSError, match="Reflink failed"):
                _reflink_via_cp_linux(Path("/a"), Path("/b"))

    def test_cp_macos_timeout_raises_oserror(self) -> None:
        """Subprocess timeout is converted to OSError."""
        import subprocess as sp

        with patch("duplicates_detector.deleter.subprocess.run", side_effect=sp.TimeoutExpired("cp", 60)):
            from duplicates_detector.deleter import _reflink_via_cp_macos

            with pytest.raises(OSError, match="timed out"):
                _reflink_via_cp_macos(Path("/a"), Path("/b"))

    def test_cp_linux_timeout_raises_oserror(self) -> None:
        """Subprocess timeout is converted to OSError."""
        import subprocess as sp

        with patch("duplicates_detector.deleter.subprocess.run", side_effect=sp.TimeoutExpired("cp", 60)):
            from duplicates_detector.deleter import _reflink_via_cp_linux

            with pytest.raises(OSError, match="timed out"):
                _reflink_via_cp_linux(Path("/a"), Path("/b"))

    def test_cp_macos_missing_raises_oserror(self) -> None:
        """Missing cp command is converted to OSError, not FileNotFoundError."""
        with patch("duplicates_detector.deleter.subprocess.run", side_effect=FileNotFoundError("cp")):
            from duplicates_detector.deleter import _reflink_via_cp_macos

            with pytest.raises(OSError, match="cp command not found"):
                _reflink_via_cp_macos(Path("/a"), Path("/b"))

    def test_cp_linux_missing_raises_oserror(self) -> None:
        """Missing cp command is converted to OSError, not FileNotFoundError."""
        with patch("duplicates_detector.deleter.subprocess.run", side_effect=FileNotFoundError("cp")):
            from duplicates_detector.deleter import _reflink_via_cp_linux

            with pytest.raises(OSError, match="cp command not found"):
                _reflink_via_cp_linux(Path("/a"), Path("/b"))


# ---------------------------------------------------------------------------
# make_deleter factory (extended)
# ---------------------------------------------------------------------------


class TestMakeDeleterExtended:
    def test_hardlink_returns_hardlink(self) -> None:
        assert isinstance(make_deleter("hardlink"), HardlinkDeleter)

    def test_symlink_returns_symlink(self) -> None:
        assert isinstance(make_deleter("symlink"), SymlinkDeleter)

    def test_reflink_returns_reflink(self) -> None:
        assert isinstance(make_deleter("reflink"), ReflinkDeleter)


# ---------------------------------------------------------------------------
# DeletionResult
# ---------------------------------------------------------------------------


class TestDeletionResult:
    def test_frozen(self) -> None:
        r = DeletionResult(path=Path("/a"), bytes_freed=10)
        with pytest.raises(AttributeError):
            r.bytes_freed = 99  # type: ignore[misc]

    def test_destination_default(self) -> None:
        r = DeletionResult(path=Path("/a"), bytes_freed=0)
        assert r.destination is None
