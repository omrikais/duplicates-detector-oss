from __future__ import annotations

import re
import sys
import time
import warnings
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

if TYPE_CHECKING:
    from duplicates_detector.progress import ProgressEmitter

DEFAULT_VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".mpg",
        ".mpeg",
        ".ts",
        ".vob",
        ".3gp",
        ".ogv",
    }
)

DEFAULT_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".tiff",
        ".tif",
        ".heic",
        ".heif",
        ".avif",
        ".svg",
        ".ico",
    }
)

DEFAULT_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".flac",
        ".aac",
        ".m4a",
        ".wav",
        ".ogg",
        ".opus",
        ".wma",
        ".ape",
        ".alac",
        ".aiff",
        ".aif",
        ".wv",
        ".dsf",
        ".dff",
    }
)

DEFAULT_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".txt", ".md"})


class MediaFile(NamedTuple):
    """A discovered media file with its classified type."""

    path: Path
    media_type: Literal["video", "image"]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob pattern with ``**`` support into a compiled regex.

    Polyfill for ``PurePath.full_match()`` on Python < 3.13 where
    ``match()`` treats ``**`` as a single-component wildcard (``*``).

    Semantics:
    - ``**``  → zero or more path segments (including separators)
    - ``*``   → anything except a path separator
    - ``?``   → single non-separator character
    """
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # ** — zero or more path segments.
                i += 2
                if i < len(pattern) and pattern[i] in ("/", "\\"):
                    # **/  — match zero or more directory prefixes
                    i += 1
                    parts.append("(?:.+/)?")
                else:
                    # ** at end of pattern — match anything remaining
                    parts.append(".*")
            else:
                parts.append("[^/]*")
                i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c in ("\\", "/"):
            parts.append("/")
            i += 1
        else:
            parts.append(re.escape(c))
            i += 1
    return re.compile(f"^{''.join(parts)}$")


def _safe_iterdir(gen):
    """Yield items from a path generator, skipping PermissionError.

    Python's rglob()/iterdir() return generators that raise PermissionError
    when they encounter unreadable directories.  A bare try/except around a
    for-loop catches only the first error and terminates iteration.  This
    wrapper uses explicit next() calls so that each error is caught and
    skipped individually, allowing the rest of the tree to be traversed.
    """
    it = iter(gen)
    while True:
        try:
            yield next(it)
        except StopIteration:
            return
        except PermissionError as exc:
            warnings.warn(f"Permission denied, skipping: {exc}", stacklevel=2)


def _scan_files_iter(
    directories: str | Path | Sequence[str | Path],
    *,
    recursive: bool = True,
    extensions: frozenset[str],
    exclude: Sequence[str] | None = None,
    pause_waiter: Callable[[], None] | None = None,
) -> Iterator[Path]:
    """Yield discovered file paths one at a time (generator form).

    This is the core scanning logic extracted as a generator so that async
    callers (e.g. ``scan_stage`` in ``pipeline.py``) can consume items
    incrementally.  The existing :func:`_scan_files` wrapper collects
    results into a sorted, deduplicated list for backward compatibility.

    Yields:
        Each matching :class:`~pathlib.Path` (deduplicated by resolved path).

    Raises:
        FileNotFoundError: If any directory does not exist.
        NotADirectoryError: If any path is not a directory.
    """
    # Normalize to a list of Paths
    if isinstance(directories, (str, Path)):
        roots = [Path(directories)]
    else:
        roots = [Path(d) for d in directories]

    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"Directory not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

    seen: set[Path] = set()

    # Pre-compile exclude patterns once (avoids re-compiling regexes per file).
    _compiled_excludes: list[re.Pattern[str]] | None = None
    if exclude and sys.version_info < (3, 13):
        _compiled_excludes = [_glob_to_regex(pat) for pat in exclude]

    # Resolve the exclude-matching strategy once, outside the hot loop.
    _use_full_match = exclude and sys.version_info >= (3, 13)

    for root in roots:
        raw_entries = root.rglob("*") if recursive else root.iterdir()

        for entry in _safe_iterdir(raw_entries):
            try:
                if pause_waiter is not None:
                    pause_waiter()
                if not entry.is_file():
                    continue
                if exclude:
                    if _use_full_match:
                        _match = entry.relative_to(root).full_match
                        excluded = any(_match(pat) for pat in exclude)
                    else:
                        rel_str = entry.relative_to(root).as_posix()
                        excluded = any(rx.search(rel_str) is not None for rx in _compiled_excludes)  # type: ignore[union-attr]
                    if excluded:
                        continue
                if entry.suffix.lower() not in extensions:
                    continue

                resolved = entry.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield entry
            except PermissionError:
                warnings.warn(
                    f"Permission denied, skipping: {entry}",
                    stacklevel=2,
                )
                continue


def _scan_files(
    directories: str | Path | Sequence[str | Path],
    *,
    recursive: bool = True,
    extensions: frozenset[str],
    exclude: Sequence[str] | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
    pause_waiter: Callable[[], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> list[Path]:
    """Core scanning loop shared by :func:`find_video_files` and :func:`find_media_files`.

    Returns a sorted list of matching file paths (deduplicated by resolved path).
    Wraps :func:`_scan_files_iter` with progress tracking and sorting.

    Raises:
        FileNotFoundError: If any directory does not exist.
        NotADirectoryError: If any path is not a directory.
    """
    if progress_emitter is not None:
        progress_emitter.stage_start("scan")
    scan_start = time.monotonic()

    results: list[Path] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed:,} found"),
        TimeElapsedColumn(),
        console=Console(stderr=True),
        transient=True,
        disable=quiet or progress_emitter is not None,
    ) as progress:
        task = progress.add_task("Scanning", total=None)

        for entry in _scan_files_iter(
            directories,
            recursive=recursive,
            extensions=extensions,
            exclude=exclude,
            pause_waiter=pause_waiter,
        ):
            results.append(entry)
            progress.update(task, completed=len(results))
            if on_progress is not None:
                on_progress(len(results))
            if progress_emitter is not None:
                progress_emitter.progress("scan", current=len(results))

    if progress_emitter is not None:
        progress_emitter.progress("scan", current=len(results), force=True)
        progress_emitter.stage_end("scan", total=len(results), elapsed=time.monotonic() - scan_start)

    results.sort(key=lambda p: p.name.lower())
    return results


def find_video_files(
    directories: str | Path | Sequence[str | Path],
    *,
    recursive: bool = True,
    extensions: frozenset[str] | None = None,
    exclude: Sequence[str] | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
    pause_waiter: Callable[[], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> list[Path]:
    """Find video files in the given directory or directories.

    Args:
        directories: One or more directories to scan.  Accepts a single path
                     (str/Path) or a sequence of paths.
        recursive: If True, scan subdirectories as well.
        extensions: Set of file extensions to match (with leading dot, lowercase).
                    Defaults to DEFAULT_VIDEO_EXTENSIONS.
        exclude: Glob patterns to exclude.  Each pattern is matched against the
                 path relative to the scan root using PurePath.full_match()
                 (Python 3.13+) with a glob-to-regex polyfill for older versions.

    Returns:
        Sorted list of resolved video file paths (no symlink duplicates).

    Raises:
        FileNotFoundError: If any directory does not exist.
        NotADirectoryError: If any path is not a directory.
    """
    exts = extensions if extensions is not None else DEFAULT_VIDEO_EXTENSIONS
    return _scan_files(
        directories,
        recursive=recursive,
        extensions=exts,
        exclude=exclude,
        quiet=quiet,
        progress_emitter=progress_emitter,
        pause_waiter=pause_waiter,
        on_progress=on_progress,
    )


def find_media_files(
    directories: str | Path | Sequence[str | Path],
    *,
    recursive: bool = True,
    exclude: Sequence[str] | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
    pause_waiter: Callable[[], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> list[MediaFile]:
    """Find video and image files, classifying each by media type.

    Uses the union of :data:`DEFAULT_VIDEO_EXTENSIONS` and
    :data:`DEFAULT_IMAGE_EXTENSIONS`.  Each returned :class:`MediaFile`
    carries the original path and its ``"video"`` or ``"image"``
    classification.

    Returns:
        Sorted list of :class:`MediaFile` (sorted by filename, no symlink
        duplicates).

    Raises:
        FileNotFoundError: If any directory does not exist.
        NotADirectoryError: If any path is not a directory.
    """
    combined = DEFAULT_VIDEO_EXTENSIONS | DEFAULT_IMAGE_EXTENSIONS
    paths = _scan_files(
        directories,
        recursive=recursive,
        extensions=combined,
        exclude=exclude,
        quiet=quiet,
        progress_emitter=progress_emitter,
        pause_waiter=pause_waiter,
        on_progress=on_progress,
    )
    result: list[MediaFile] = []
    for p in paths:
        suffix = p.suffix.lower()
        if suffix in DEFAULT_VIDEO_EXTENSIONS:
            result.append(MediaFile(path=p, media_type="video"))
        else:
            result.append(MediaFile(path=p, media_type="image"))
    return result
