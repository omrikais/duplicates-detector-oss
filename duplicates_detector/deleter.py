from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DeletionResult:
    """Outcome of a single file deletion/move."""

    path: Path
    bytes_freed: int
    destination: Path | None = None


class Deleter:
    """Strategy for removing duplicate files."""

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        """Remove/move a file. Raises OSError on failure."""
        raise NotImplementedError

    @property
    def verb(self) -> str:
        """Human-readable past-tense verb: 'Deleted', 'Trashed', 'Moved'."""
        raise NotImplementedError

    @property
    def dry_verb(self) -> str:
        """Dry-run verb: 'Would delete', 'Would trash', 'Would move'."""
        raise NotImplementedError

    @property
    def prompt_verb(self) -> str:
        """Interactive prompt verb: 'Delete', 'Trash', 'Move'."""
        raise NotImplementedError

    @property
    def gerund(self) -> str:
        """Present-participle form: 'Deleting', 'Trashing', 'Moving'."""
        pv = self.prompt_verb
        return (pv[:-1] if pv.endswith("e") else pv) + "ing"


class PermanentDeleter(Deleter):
    """Current behavior — Path.unlink()."""

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        size = path.stat().st_size
        path.unlink()
        return DeletionResult(path=path, bytes_freed=size)

    @property
    def verb(self) -> str:
        return "Deleted"

    @property
    def dry_verb(self) -> str:
        return "Would delete"

    @property
    def prompt_verb(self) -> str:
        return "Delete"


class TrashDeleter(Deleter):
    """Move to OS trash via send2trash."""

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        size = path.stat().st_size
        from send2trash import send2trash

        send2trash(str(path))
        return DeletionResult(path=path, bytes_freed=size)

    @property
    def verb(self) -> str:
        return "Trashed"

    @property
    def dry_verb(self) -> str:
        return "Would trash"

    @property
    def prompt_verb(self) -> str:
        return "Trash"


class MoveDeleter(Deleter):
    """Move to a staging directory."""

    def __init__(self, destination: Path) -> None:
        self._destination = destination

    @property
    def destination(self) -> Path:
        """The staging directory files are moved to."""
        return self._destination

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        size = path.stat().st_size
        target = self._resolve_target(path)
        shutil.move(str(path), str(target))
        return DeletionResult(path=path, bytes_freed=size, destination=target)

    @property
    def verb(self) -> str:
        return "Moved"

    @property
    def dry_verb(self) -> str:
        return "Would move"

    @property
    def prompt_verb(self) -> str:
        return "Move"

    def _resolve_target(self, path: Path) -> Path:
        """Compute target path, handling name collisions."""
        target = self._destination / path.name
        if not target.exists():
            return target
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while target.exists():
            target = self._destination / f"{stem}_{counter}{suffix}"
            counter += 1
        return target


def _tmp_link_path(path: Path) -> Path:
    """Return a unique temp path in the same directory for atomic link creation."""
    # Truncate prefix to avoid exceeding NAME_MAX (255) on long filenames.
    prefix = f".{path.name}."[:128]
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_str)
    tmp.unlink()  # Remove placeholder so link/symlink creation succeeds
    return tmp


class HardlinkDeleter(Deleter):
    """Replace duplicate with a hardlink to the kept file."""

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        if link_target is None:
            raise ValueError("link_target is required for HardlinkDeleter")
        size = path.stat().st_size
        tmp = _tmp_link_path(path)
        try:
            os.link(link_target, tmp)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return DeletionResult(path=path, bytes_freed=size, destination=link_target)

    @property
    def verb(self) -> str:
        return "Hardlinked"

    @property
    def dry_verb(self) -> str:
        return "Would hardlink"

    @property
    def prompt_verb(self) -> str:
        return "Hardlink"


class SymlinkDeleter(Deleter):
    """Replace duplicate with a symlink to the kept file."""

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        if link_target is None:
            raise ValueError("link_target is required for SymlinkDeleter")
        size = path.stat().st_size
        tmp = _tmp_link_path(path)
        try:
            tmp.symlink_to(link_target.resolve())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return DeletionResult(path=path, bytes_freed=size, destination=link_target)

    @property
    def verb(self) -> str:
        return "Symlinked"

    @property
    def dry_verb(self) -> str:
        return "Would symlink"

    @property
    def prompt_verb(self) -> str:
        return "Symlink"


def _reflink_via_cp_macos(src: Path, dst: Path) -> None:
    """Use cp -c (APFS clone) on macOS — guarantees CoW or failure."""
    try:
        result = subprocess.run(
            ["cp", "-c", str(src), str(dst)],
            capture_output=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise OSError("Reflink failed: cp command not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise OSError(f"Reflink timed out (cp -c): {src} → {dst}") from e
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise OSError(f"Reflink failed (cp -c): {stderr}. Ensure the filesystem supports copy-on-write (APFS).")


def _reflink_via_cp_linux(src: Path, dst: Path) -> None:
    """Use cp --reflink=always on Linux — guarantees CoW or failure."""
    try:
        result = subprocess.run(
            ["cp", "--reflink=always", str(src), str(dst)],
            capture_output=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise OSError("Reflink failed: cp command not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise OSError(f"Reflink timed out (cp --reflink=always): {src} → {dst}") from e
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise OSError(
            f"Reflink failed (cp --reflink=always): {stderr}. "
            "Ensure the filesystem supports copy-on-write (Btrfs, XFS with reflink)."
        )


def _create_reflink(src: Path, dst: Path) -> None:
    """Create a CoW reflink copy of src at dst.

    Uses cp -c (macOS/APFS) or cp --reflink=always (Linux/Btrfs/XFS).
    Both commands guarantee CoW semantics — they fail rather than
    silently falling back to a regular copy on non-CoW filesystems.
    Raises OSError if the filesystem does not support reflinks.
    """
    if sys.platform == "darwin":
        _reflink_via_cp_macos(src, dst)
    else:
        _reflink_via_cp_linux(src, dst)


class ReflinkDeleter(Deleter):
    """Replace duplicate with a CoW reflink to the kept file.

    Uses cp -c (macOS/APFS) or cp --reflink=always (Linux/Btrfs/XFS).
    Both guarantee CoW-or-fail semantics on supported filesystems.
    """

    def remove(self, path: Path, *, link_target: Path | None = None) -> DeletionResult:
        if link_target is None:
            raise ValueError("link_target is required for ReflinkDeleter")
        size = path.stat().st_size
        tmp = _tmp_link_path(path)
        try:
            _create_reflink(link_target, tmp)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return DeletionResult(path=path, bytes_freed=size, destination=link_target)

    @property
    def verb(self) -> str:
        return "Reflinked"

    @property
    def dry_verb(self) -> str:
        return "Would reflink"

    @property
    def prompt_verb(self) -> str:
        return "Reflink"


def make_deleter(action: str, move_to_dir: Path | None = None) -> Deleter:
    """Factory: create the appropriate Deleter from CLI args."""
    match action:
        case "delete":
            return PermanentDeleter()
        case "trash":
            return TrashDeleter()
        case "move-to":
            if move_to_dir is None:
                raise ValueError("move_to_dir is required for 'move-to' action")
            return MoveDeleter(move_to_dir)
        case "hardlink":
            return HardlinkDeleter()
        case "symlink":
            return SymlinkDeleter()
        case "reflink":
            return ReflinkDeleter()
        case _:
            raise ValueError(f"Unknown action: {action}")
