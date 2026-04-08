"""Tests for the four bug fixes on the feat/four-features branch.

Fix 1: Collision-safe MoveDeleter sidecar directory move
Fix 2: _remove_sidecar returns False for skipped directory sidecars
Fix 3: Fallback sidecar rediscovery for replay pairs (sidecars=None)
Fix 4: --no-pre-hash forwarded to auto-mode common_kwargs
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from duplicates_detector.advisor import _DeletionOutcome, _execute_deletion, _remove_sidecar
from duplicates_detector.deleter import (
    HardlinkDeleter,
    MoveDeleter,
    PermanentDeleter,
    ReflinkDeleter,
    SymlinkDeleter,
)
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.pipeline import PipelineResult
from duplicates_detector.scorer import ScoredPair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quiet_console() -> Console:
    """Console that writes to a StringIO buffer (suppresses terminal output)."""
    return Console(file=StringIO(), highlight=False, width=200)


def _make_pair_on_disk(
    tmp_path: Path,
    *,
    target_name: str = "photo_a.jpg",
    kept_name: str = "photo_b.jpg",
    target_size: int = 500,
    kept_size: int = 2000,
    sidecars: tuple[Path, ...] | None = None,
) -> tuple[ScoredPair, Path, Path]:
    """Create a scored pair backed by real files on disk."""
    target = tmp_path / target_name
    target.write_bytes(b"A" * target_size)
    kept = tmp_path / kept_name
    kept.write_bytes(b"B" * kept_size)

    meta_target = VideoMetadata(
        path=target,
        filename=Path(target_name).stem,
        duration=None,
        width=1920,
        height=1080,
        file_size=target_size,
        sidecars=sidecars,
    )
    meta_kept = VideoMetadata(
        path=kept,
        filename=Path(kept_name).stem,
        duration=None,
        width=1920,
        height=1080,
        file_size=kept_size,
    )
    pair = ScoredPair(
        file_a=meta_target,
        file_b=meta_kept,
        total_score=85.0,
        breakdown={"filename": 40.0},
        detail={},
    )
    return pair, target, kept


# ===========================================================================
# Fix 1: Collision-safe MoveDeleter sidecar directory move
# ===========================================================================


class TestMoveDeleterSidecarCollisionSafety:
    """When two .lrdata sidecar directories share the same name and are moved
    to the same staging directory, they must get unique target names instead
    of being silently merged by shutil.move."""

    def test_two_lrdata_dirs_get_unique_names_in_staging(self, tmp_path: Path):
        """Move two identically-named .lrdata dirs to the same destination:
        second one gets _1 suffix, contents don't merge."""
        staging = tmp_path / "staging"
        staging.mkdir()
        deleter = MoveDeleter(staging)
        console = _quiet_console()

        # First .lrdata directory (under dir_a/)
        dir_a = tmp_path / "dir_a"
        dir_a.mkdir()
        lrdata_a = dir_a / "photo.lrdata"
        lrdata_a.mkdir()
        (lrdata_a / "file_a.dat").write_bytes(b"data-from-a")

        # Second .lrdata directory (under dir_b/) — same basename
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()
        lrdata_b = dir_b / "photo.lrdata"
        lrdata_b.mkdir()
        (lrdata_b / "file_b.dat").write_bytes(b"data-from-b")

        # Move first
        removed_1, dest_1 = _remove_sidecar(lrdata_a, deleter, console)
        assert removed_1 is True
        assert dest_1 is not None
        assert not lrdata_a.exists()

        # Move second (same name) — should NOT merge
        removed_2, dest_2 = _remove_sidecar(lrdata_b, deleter, console)
        assert removed_2 is True
        assert dest_2 is not None
        assert not lrdata_b.exists()

        # Verify both are present under staging with unique names
        moved = sorted(p for p in staging.iterdir() if p.is_dir())
        assert len(moved) == 2

        # Original should be photo.lrdata, collision should be photo_1.lrdata
        names = sorted(d.name for d in moved)
        assert "photo.lrdata" in names
        assert "photo_1.lrdata" in names

        # Verify contents are NOT merged — each dir has only its own file
        original_dir = staging / "photo.lrdata"
        collision_dir = staging / "photo_1.lrdata"
        original_files = list(original_dir.iterdir())
        collision_files = list(collision_dir.iterdir())
        assert len(original_files) == 1
        assert len(collision_files) == 1
        assert original_files[0].name != collision_files[0].name

    def test_three_collisions_increment_counter(self, tmp_path: Path):
        """Three identically-named .lrdata dirs get _1, _2 suffixes."""
        staging = tmp_path / "staging"
        staging.mkdir()
        deleter = MoveDeleter(staging)
        console = _quiet_console()

        for i in range(3):
            parent = tmp_path / f"dir_{i}"
            parent.mkdir()
            lrdata = parent / "data.lrdata"
            lrdata.mkdir()
            (lrdata / f"content_{i}.txt").write_bytes(f"content-{i}".encode())
            _remove_sidecar(lrdata, deleter, console)

        moved = sorted(d.name for d in staging.iterdir() if d.is_dir())
        assert moved == ["data.lrdata", "data_1.lrdata", "data_2.lrdata"]

    def test_non_directory_sidecar_uses_deleter_remove(self, tmp_path: Path):
        """Non-directory sidecars still use the deleter's remove method (no regression)."""
        staging = tmp_path / "staging"
        staging.mkdir()
        deleter = MoveDeleter(staging)
        console = _quiet_console()

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp/>")

        removed, dest = _remove_sidecar(xmp, deleter, console)
        assert removed is True
        assert dest == staging / "photo.xmp"
        assert not xmp.exists()
        assert (staging / "photo.xmp").exists()


# ===========================================================================
# Fix 2: _remove_sidecar returns False for skipped directory sidecars
# ===========================================================================


class TestRemoveSidecarSkipForLinkDeleters:
    """Link-based deleters (hardlink, symlink, reflink) cannot meaningfully
    operate on directories. _remove_sidecar returns False and the caller
    skips counting them."""

    @pytest.mark.parametrize(
        "deleter_cls",
        [HardlinkDeleter, SymlinkDeleter, ReflinkDeleter],
        ids=["hardlink", "symlink", "reflink"],
    )
    def test_remove_sidecar_returns_false_for_directory(self, tmp_path: Path, deleter_cls):
        """_remove_sidecar returns False for directory sidecars with link-based deleters."""
        lrdata = tmp_path / "photo.lrdata"
        lrdata.mkdir()
        (lrdata / "data.dat").write_bytes(b"lr-data")

        console = _quiet_console()
        deleter = deleter_cls()
        removed, dest = _remove_sidecar(lrdata, deleter, console)
        assert removed is False
        assert dest is None
        # Directory should still exist (not deleted)
        assert lrdata.exists()

    @pytest.mark.parametrize(
        "deleter_cls",
        [HardlinkDeleter, SymlinkDeleter, ReflinkDeleter],
        ids=["hardlink", "symlink", "reflink"],
    )
    def test_execute_deletion_does_not_count_skipped_directory_sidecar(self, tmp_path: Path, deleter_cls):
        """_execute_deletion with a link-based deleter and a directory sidecar:
        sidecars_deleted == 0, no action log entry for the sidecar.
        Uses dry_run=True to avoid requiring filesystem support (e.g. reflink)."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        lrdata = tmp_path / "photo.lrdata"
        lrdata.mkdir()
        (lrdata / "data.dat").write_bytes(b"lr-data")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=deleter_cls(),
            dry_run=True,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(lrdata,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 0
        assert outcome.sidecar_bytes_freed == 0
        # Action log should have ONE entry for the main file but NONE for the sidecar
        assert mock_log.log.call_count == 1
        assert mock_log.log.call_args.kwargs.get("sidecar_of") is None

    def test_file_sidecar_works_with_permanent_deleter(self, tmp_path: Path):
        """File sidecars (not directories) are handled normally by PermanentDeleter."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp/>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(xmp,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1
        assert not xmp.exists()
        # Action log: 1 for main file + 1 for sidecar
        assert mock_log.log.call_count == 2

    def test_permanent_deleter_removes_directory_sidecar(self, tmp_path: Path):
        """PermanentDeleter does remove directory sidecars (not skipped)."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        lrdata = tmp_path / "photo.lrdata"
        lrdata.mkdir()
        (lrdata / "data.dat").write_bytes(b"lr-data")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(lrdata,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1
        assert not lrdata.exists()


# ===========================================================================
# Fix 3: Fallback sidecar rediscovery for replay pairs (sidecars=None)
# ===========================================================================


class TestSidecarRediscoveryForReplay:
    """When sidecars=None (replay-reconstructed pairs), _execute_deletion
    calls find_sidecars() to discover sidecars from the filesystem."""

    def test_xmp_sidecar_discovered_and_deleted_when_sidecars_none(self, tmp_path: Path):
        """A .xmp sidecar next to the target is discovered and deleted when sidecars=None."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,  # key: sidecars not provided
        )

        assert outcome.success is True
        assert not target.exists()
        assert not xmp.exists()
        assert outcome.sidecars_deleted == 1
        assert outcome.sidecar_bytes_freed > 0

    def test_lrdata_directory_discovered_when_sidecars_none(self, tmp_path: Path):
        """A .lrdata directory next to the target is discovered and deleted."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        lrdata = tmp_path / "photo.lrdata"
        lrdata.mkdir()
        (lrdata / "preview.dat").write_bytes(b"preview-data")

        console = _quiet_console()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=None,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
        )

        assert outcome.success is True
        assert not lrdata.exists()
        assert outcome.sidecars_deleted == 1

    def test_no_sidecar_files_present_sidecars_none(self, tmp_path: Path):
        """When no sidecar files exist and sidecars=None, deletion still succeeds."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        console = _quiet_console()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=None,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
        )

        assert outcome.success is True
        assert not target.exists()
        assert outcome.sidecars_deleted == 0

    def test_explicit_empty_tuple_no_rediscovery(self, tmp_path: Path):
        """When sidecars=() (empty tuple, not None), no rediscovery happens."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        # Even though an xmp exists, it shouldn't be found because sidecars=()
        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=None,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(),  # explicit empty, NOT None
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 0
        # The xmp sidecar should still exist since we explicitly said no sidecars
        assert xmp.exists()

    def test_multiple_sidecars_discovered_when_none(self, tmp_path: Path):
        """Multiple sidecar types are all discovered and deleted."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp/>")
        aae = tmp_path / "photo.aae"
        aae.write_bytes(b"aae-data")

        console = _quiet_console()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=None,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
        )

        assert outcome.success is True
        assert not xmp.exists()
        assert not aae.exists()
        assert outcome.sidecars_deleted == 2


# ===========================================================================
# Fix 4: --no-pre-hash forwarded to auto-mode common_kwargs
# ===========================================================================


_SCAN_ITER_TARGET = "duplicates_detector.scanner._scan_files_iter"


def _mock_scan_iter_auto():
    """Context manager that mocks _scan_files_iter for auto-mode discovery."""
    return patch(_SCAN_ITER_TARGET, side_effect=lambda *a, **kw: iter([Path("a.mp4"), Path("b.jpg")]))


class TestNoPreHashAutoMode:
    """--no-pre-hash must be forwarded to both sub-pipelines in auto mode."""

    def test_no_pre_hash_forwarded_to_auto_mode_subpipelines(self, tmp_path: Path):
        """When --no-pre-hash is passed with --mode auto, both sub-pipelines receive it."""
        from duplicates_detector.cli import main
        from duplicates_detector.scanner import MediaFile

        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.jpg").touch()

        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.jpg", media_type="image"),
        ]

        with (
            _mock_scan_iter_auto(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=1),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--no-pre-hash"])

        assert mock_pipeline.call_count == 2
        for call_obj in mock_pipeline.call_args_list:
            assert call_obj.kwargs["no_pre_hash"] is True, (
                f"no_pre_hash not forwarded to {call_obj.kwargs.get('mode')} sub-pipeline"
            )

    def test_pre_hash_default_forwarded_to_auto_mode(self, tmp_path: Path):
        """Without --no-pre-hash, both sub-pipelines receive no_pre_hash=False."""
        from duplicates_detector.cli import main
        from duplicates_detector.scanner import MediaFile

        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.jpg").touch()

        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.jpg", media_type="image"),
        ]

        with (
            _mock_scan_iter_auto(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=1),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto"])

        assert mock_pipeline.call_count == 2
        for call_obj in mock_pipeline.call_args_list:
            assert call_obj.kwargs["no_pre_hash"] is False, (
                f"no_pre_hash should default to False for {call_obj.kwargs.get('mode')} sub-pipeline"
            )


# ===========================================================================
# Fix 5: --no-sidecars (empty tuple) no longer triggers fallback rediscovery
# ===========================================================================


class TestNoSidecarsDisablesRediscovery:
    """When --no-sidecars is set, pipeline sets sidecars=() on metadata.
    _execute_deletion must distinguish this from sidecars=None (replay)
    and NOT rediscover sidecars when the tuple is explicitly empty."""

    def test_empty_tuple_sidecars_skips_rediscovery_even_with_xmp_present(self, tmp_path: Path):
        """sidecars=() means user disabled sidecars — existing .xmp is NOT found or deleted."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        # A real .xmp sidecar exists on disk
        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(),  # explicitly disabled
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 0
        assert outcome.sidecar_bytes_freed == 0
        # XMP must still exist — it was NOT rediscovered
        assert xmp.exists()
        # Only one action log entry: the main file
        assert mock_log.log.call_count == 1

    def test_none_sidecars_triggers_rediscovery(self, tmp_path: Path):
        """sidecars=None (replay) triggers fallback rediscovery."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,  # unknown — triggers rediscovery
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1
        assert not xmp.exists()
        # Two log entries: main file + sidecar
        assert mock_log.log.call_count == 2

    def test_custom_sidecar_extensions_used_during_rediscovery(self, tmp_path: Path):
        """sidecar_extensions='.pp3' causes rediscovery to find .pp3 files only."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        # Create both .xmp and .pp3 sidecars
        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp/>")
        pp3 = tmp_path / "photo.pp3"
        pp3.write_bytes(b"pp3-data")

        console = _quiet_console()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=None,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
            sidecar_extensions=".pp3",
        )

        assert outcome.success is True
        # Only .pp3 should be found (custom extensions override defaults)
        assert not pp3.exists()
        # .xmp should still exist — it's not in the custom extension list
        assert xmp.exists()
        assert outcome.sidecars_deleted == 1


# ===========================================================================
# Fix 6: Link-based deleters skip FILE sidecars too (not just directories)
# ===========================================================================


class TestLinkDeletersSkipFileSidecars:
    """Previously, link-based deleters only skipped directory sidecars and
    crashed on file sidecars with ValueError('link_target is required').
    Now they skip ALL sidecars (files and directories)."""

    @pytest.mark.parametrize(
        "deleter_cls",
        [HardlinkDeleter, SymlinkDeleter, ReflinkDeleter],
        ids=["hardlink", "symlink", "reflink"],
    )
    def test_remove_sidecar_returns_false_for_file_sidecar(self, tmp_path: Path, deleter_cls):
        """_remove_sidecar returns (False, None) for a file sidecar with link-based deleters."""
        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        deleter = deleter_cls()
        removed, dest = _remove_sidecar(xmp, deleter, console)

        assert removed is False
        assert dest is None
        # File must still exist — it was skipped, not deleted
        assert xmp.exists()

    @pytest.mark.parametrize(
        "deleter_cls",
        [HardlinkDeleter, SymlinkDeleter, ReflinkDeleter],
        ids=["hardlink", "symlink", "reflink"],
    )
    def test_execute_deletion_skips_file_sidecar_with_link_deleter(self, tmp_path: Path, deleter_cls):
        """_execute_deletion with a link-based deleter and a file sidecar:
        sidecars_deleted == 0, file still exists, no sidecar action log entry.
        Uses dry_run=True to avoid requiring filesystem support (e.g. reflink)."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=deleter_cls(),
            dry_run=True,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(xmp,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 0
        assert outcome.sidecar_bytes_freed == 0
        # XMP file must still exist (dry_run doesn't touch anything)
        assert xmp.exists()
        # Only one action log entry: the main file, not the sidecar
        assert mock_log.log.call_count == 1
        assert mock_log.log.call_args.kwargs.get("sidecar_of") is None

    def test_permanent_deleter_still_handles_file_sidecar(self, tmp_path: Path):
        """PermanentDeleter handles file sidecars normally (regression guard)."""
        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        removed, dest = _remove_sidecar(xmp, PermanentDeleter(), console)

        assert removed is True
        assert dest is None  # PermanentDeleter has no destination
        assert not xmp.exists()


# ===========================================================================
# Fix 7: Moved sidecar destinations recorded in action log
# ===========================================================================


class TestMovedSidecarDestinationInActionLog:
    """When MoveDeleter moves a sidecar file, the destination path must
    appear in the action log entry so undo scripts can restore it."""

    def test_move_deleter_sidecar_destination_logged(self, tmp_path: Path):
        """MoveDeleter: action log entry for sidecar includes destination path."""
        staging = tmp_path / "staging"
        staging.mkdir()
        deleter = MoveDeleter(staging)

        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=deleter,
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(xmp,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1

        # Find the sidecar log entry (the one with sidecar_of set)
        sidecar_calls = [c for c in mock_log.log.call_args_list if c.kwargs.get("sidecar_of") is not None]
        assert len(sidecar_calls) == 1
        sc_call = sidecar_calls[0]
        # Destination must be set and point to the staging directory
        assert sc_call.kwargs["destination"] is not None
        assert sc_call.kwargs["destination"].parent == staging

    def test_permanent_deleter_sidecar_destination_is_none(self, tmp_path: Path):
        """PermanentDeleter: action log entry for sidecar has destination=None."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(xmp,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1

        # Find the sidecar log entry
        sidecar_calls = [c for c in mock_log.log.call_args_list if c.kwargs.get("sidecar_of") is not None]
        assert len(sidecar_calls) == 1
        # PermanentDeleter returns None for destination
        assert sidecar_calls[0].kwargs["destination"] is None

    def test_move_deleter_directory_sidecar_destination_logged(self, tmp_path: Path):
        """MoveDeleter: action log entry for a directory sidecar includes destination."""
        staging = tmp_path / "staging"
        staging.mkdir()
        deleter = MoveDeleter(staging)

        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        lrdata = tmp_path / "photo.lrdata"
        lrdata.mkdir()
        (lrdata / "preview.dat").write_bytes(b"preview-data")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=deleter,
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=(lrdata,),
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1

        sidecar_calls = [c for c in mock_log.log.call_args_list if c.kwargs.get("sidecar_of") is not None]
        assert len(sidecar_calls) == 1
        sc_dest = sidecar_calls[0].kwargs["destination"]
        assert sc_dest is not None
        assert sc_dest.parent == staging


# ===========================================================================
# Fix 8: directory weight accepted by _validate_weights
# ===========================================================================


class TestValidateWeightsDirectoryKey:
    """_validate_weights now accepts 'directory' as an optional weight key
    in any mode. When directory is present with weight > 0, the sum-to-100
    check is relaxed since _apply_weights renormalizes downstream."""

    def test_video_mode_with_directory_weight_succeeds(self):
        """directory=10 in video mode doesn't fail even though total > 100."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        result = _validate_weights(
            "filename=50,duration=30,resolution=10,filesize=10,directory=10",
            content=False,
            console=console,
            mode="video",
        )
        assert "directory" in result
        assert result["directory"] == 10.0

    def test_video_mode_without_directory_must_sum_to_100(self):
        """Without directory, weights that don't sum to 100 fail."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        with pytest.raises(SystemExit):
            _validate_weights(
                "filename=50,duration=30,resolution=10,filesize=5",
                content=False,
                console=console,
                mode="video",
            )

    def test_unknown_key_still_rejected(self):
        """Unknown keys like 'foobar' are still rejected."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        with pytest.raises(SystemExit):
            _validate_weights(
                "filename=50,duration=30,resolution=10,filesize=10,foobar=10",
                content=False,
                console=console,
                mode="video",
            )

    def test_image_mode_with_directory_weight_succeeds(self):
        """directory key works in image mode."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        result = _validate_weights(
            "filename=25,resolution=20,filesize=15,exif=40,directory=5",
            content=False,
            console=console,
            mode="image",
        )
        assert "directory" in result
        assert result["directory"] == 5.0

    def test_audio_mode_with_directory_weight_succeeds(self):
        """directory key works in audio mode."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        result = _validate_weights(
            "filename=30,duration=30,tags=40,directory=10",
            content=False,
            console=console,
            mode="audio",
        )
        assert "directory" in result
        assert result["directory"] == 10.0

    def test_directory_zero_weight_still_requires_sum_to_100(self):
        """directory=0 doesn't relax the sum-to-100 constraint."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        # Total base weights = 95, directory=0 → sum=95, should fail
        with pytest.raises(SystemExit):
            _validate_weights(
                "filename=50,duration=25,resolution=10,filesize=10,directory=0",
                content=False,
                console=console,
                mode="video",
            )

    def test_video_mode_standard_weights_still_work(self):
        """Existing standard weights without directory still pass."""
        from duplicates_detector.cli import _validate_weights

        console = _quiet_console()
        result = _validate_weights(
            "filename=50,duration=30,resolution=10,filesize=10",
            content=False,
            console=console,
            mode="video",
        )
        assert sum(result.values()) == 100.0
        assert "directory" not in result


# ===========================================================================
# Fix 9: no_sidecars threaded to advisor for replay mode
# ===========================================================================


class TestNoSidecarsThreadedToAdvisor:
    """When --replay --no-sidecars is used, _execute_deletion receives
    no_sidecars=True so that sidecar rediscovery is suppressed even though
    sidecars=None (replay mode lacks sidecar metadata)."""

    def test_no_sidecars_true_suppresses_rediscovery_with_sidecars_none(self, tmp_path: Path):
        """sidecars=None, no_sidecars=True: .xmp exists but is NOT found or deleted."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
            no_sidecars=True,
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 0
        assert outcome.sidecar_bytes_freed == 0
        # The XMP must still exist — rediscovery was suppressed
        assert xmp.exists()
        # Only one action log entry: the main file
        assert mock_log.log.call_count == 1

    def test_no_sidecars_false_allows_rediscovery_with_sidecars_none(self, tmp_path: Path):
        """sidecars=None, no_sidecars=False: .xmp IS found via rediscovery and deleted."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()
        mock_log = MagicMock()

        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=mock_log,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
            no_sidecars=False,
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1
        assert outcome.sidecar_bytes_freed > 0
        # The XMP should be deleted via rediscovery
        assert not xmp.exists()
        # Two action log entries: main file + sidecar
        assert mock_log.log.call_count == 2

    def test_no_sidecars_default_is_false(self, tmp_path: Path):
        """When no_sidecars is not passed (default), rediscovery works normally."""
        target = tmp_path / "photo.jpg"
        target.write_bytes(b"image-data" * 100)
        kept = tmp_path / "kept.jpg"
        kept.write_bytes(b"kept-data" * 200)

        xmp = tmp_path / "photo.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")

        console = _quiet_console()

        # Call without no_sidecars kwarg at all — should default to False
        outcome = _execute_deletion(
            target_path=target,
            kept_path=kept,
            deleter=PermanentDeleter(),
            dry_run=False,
            action_log=None,
            score=85.0,
            strategy="biggest",
            console=console,
            sidecars=None,
        )

        assert outcome.success is True
        assert outcome.sidecars_deleted == 1
        assert not xmp.exists()


# ===========================================================================
# Fix 10: --no-pre-hash respected in content-hash scans
# ===========================================================================


class TestNoPreHashContentHashScans:
    """When --no-pre-hash is passed with --content, hash_stage skips
    pre-hash grouping and sends ALL files through the full PDQ path."""

    @pytest.mark.asyncio
    async def test_no_pre_hash_true_skips_pre_hash_with_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """content=True, no_pre_hash=True: byte-identical files still go through PDQ."""
        import asyncio
        from dataclasses import replace as dreplace

        from duplicates_detector.config import Mode
        from duplicates_detector.pipeline import PipelineController, hash_stage

        data = b"x" * 8192
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(data)
        p2.write_bytes(data)

        st1 = p1.stat()
        st2 = p2.stat()
        meta1 = VideoMetadata(
            path=p1,
            filename="a",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st1.st_size,
            mtime=st1.st_mtime,
        )
        meta2 = VideoMetadata(
            path=p2,
            filename="b",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st2.st_size,
            mtime=st2.st_mtime,
        )

        hash_calls: list[Path] = []
        pre_hash_calls: list[Path] = []

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            hash_calls.append(m.path)
            return dreplace(m, content_hash=(1, 2, 3, 4))

        def _fake_pre_hash(m, cache):
            pre_hash_calls.append(m.path)
            return dreplace(m, pre_hash="fakehash")

        monkeypatch.setattr("duplicates_detector.content._hash_one_with_cache", _fake_hash)
        monkeypatch.setattr("duplicates_detector.content._pre_hash_one_with_cache", _fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = True
        config.content_method = "phash"
        config.workers = 1
        config.mode = Mode.VIDEO
        config.rotation_invariant = False
        config.visible_stages = frozenset()
        config.no_pre_hash = True  # <-- the fix: skip pre-hash

        await in_q.put(meta1)
        await in_q.put(meta2)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 2
        # Pre-hash should NOT have been called
        assert len(pre_hash_calls) == 0
        # Both files should go through the full PDQ hash path
        assert len(hash_calls) == 2

    @pytest.mark.asyncio
    async def test_no_pre_hash_false_computes_pre_hash_and_still_runs_pdq(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """content=True, no_pre_hash=False: pre-hash is computed but all files
        still go through PDQ.  Pre-hashes feed the scorer's byte-identical fast
        path only — they no longer produce synthetic content hashes."""
        import asyncio
        from dataclasses import replace as dreplace

        from duplicates_detector.config import Mode
        from duplicates_detector.pipeline import PipelineController, hash_stage

        data = b"x" * 8192
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(data)
        p2.write_bytes(data)

        st1 = p1.stat()
        st2 = p2.stat()
        meta1 = VideoMetadata(
            path=p1,
            filename="a",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st1.st_size,
            mtime=st1.st_mtime,
        )
        meta2 = VideoMetadata(
            path=p2,
            filename="b",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st2.st_size,
            mtime=st2.st_mtime,
        )

        hash_calls: list[Path] = []
        pre_hash_calls: list[Path] = []

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            hash_calls.append(m.path)
            return dreplace(m, content_hash=(1, 2, 3, 4))

        def _fake_pre_hash(m, cache):
            pre_hash_calls.append(m.path)
            return dreplace(m, pre_hash="fakehash")

        monkeypatch.setattr("duplicates_detector.content._hash_one_with_cache", _fake_hash)
        monkeypatch.setattr("duplicates_detector.content._pre_hash_one_with_cache", _fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = True
        config.content_method = "phash"
        config.workers = 1
        config.mode = Mode.VIDEO
        config.rotation_invariant = False
        config.visible_stages = frozenset()
        config.no_pre_hash = False  # pre-hash enabled

        await in_q.put(meta1)
        await in_q.put(meta2)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 2
        # Pre-hash WAS called for both files
        assert len(pre_hash_calls) == 2
        # Both files still went through PDQ (no synthetic short-circuit)
        assert len(hash_calls) == 2
        # Both should have content_hash set (from PDQ mock)
        assert items[0].content_hash is not None
        assert items[1].content_hash is not None


# ===========================================================================
# Fix 11: CLIP model SHA256 pinned
# ===========================================================================


class TestClipModelSha256Pinned:
    """The CLIP model SHA256 must be a real hash (not empty) so that
    downloaded model files are integrity-checked."""

    def test_model_sha256_is_valid_hex_digest(self):
        """_MODEL_SHA256 is a 64-character hex string (SHA-256 digest)."""
        from duplicates_detector.clip import _MODEL_SHA256

        assert isinstance(_MODEL_SHA256, str)
        assert len(_MODEL_SHA256) == 64
        # Must be valid hex
        int(_MODEL_SHA256, 16)

    def test_model_url_points_to_vision_model(self):
        """_MODEL_URL contains 'vision' indicating the correct vision-only model."""
        from duplicates_detector.clip import _MODEL_URL

        assert isinstance(_MODEL_URL, str)
        assert "vision" in _MODEL_URL.lower()

    def test_model_sha256_is_not_placeholder(self):
        """_MODEL_SHA256 is not an all-zeros or placeholder value."""
        from duplicates_detector.clip import _MODEL_SHA256

        assert _MODEL_SHA256 != ""
        assert _MODEL_SHA256 != "0" * 64


# ===========================================================================
# Fix 12: Sidecar counters populated in summary
# ===========================================================================


class TestSidecarCountersInSummary:
    """After advisor returns DeletionSummary, the CLI copies sidecar stats
    into PipelineStats. print_summary() should display them when non-zero."""

    def test_sidecar_stats_displayed_when_nonzero(self):
        """print_summary with sidecars_deleted > 0 includes sidecar line."""
        from duplicates_detector.summary import PipelineStats, print_summary

        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=5,
            pairs_above_threshold=3,
            sidecars_deleted=3,
            sidecar_bytes_freed=1024,
        )
        console = _quiet_console()
        print_summary(stats, console=console)

        output = console.file.getvalue()  # type: ignore[union-attr]
        assert "sidecar" in output.lower()
        assert "3" in output
        # Should mention freed space
        assert "freed" in output.lower()

    def test_no_sidecar_line_when_zero(self):
        """print_summary with sidecars_deleted == 0 does NOT include sidecar line."""
        from duplicates_detector.summary import PipelineStats, print_summary

        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=5,
            pairs_above_threshold=3,
            sidecars_deleted=0,
            sidecar_bytes_freed=0,
        )
        console = _quiet_console()
        print_summary(stats, console=console)

        output = console.file.getvalue()  # type: ignore[union-attr]
        assert "sidecar" not in output.lower()

    def test_sidecar_bytes_formatted_correctly(self):
        """Sidecar bytes are human-formatted (e.g. '1.0 KB')."""
        from duplicates_detector.summary import PipelineStats, print_summary

        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=5,
            pairs_above_threshold=3,
            sidecars_deleted=1,
            sidecar_bytes_freed=2048,
        )
        console = _quiet_console()
        print_summary(stats, console=console)

        output = console.file.getvalue()  # type: ignore[union-attr]
        # 2048 bytes should format as "2.0 KB" or similar
        assert "sidecar" in output.lower()
        assert "KB" in output or "kB" in output or "2" in output
