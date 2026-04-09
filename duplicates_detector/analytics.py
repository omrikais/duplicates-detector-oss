"""Analytics & insights — computation over scored pairs and groups."""

from __future__ import annotations

import dataclasses
import os
from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duplicates_detector.grouper import DuplicateGroup
    from duplicates_detector.metadata import VideoMetadata
    from duplicates_detector.scorer import ScoredPair


@dataclass(frozen=True, slots=True)
class DirectoryStats:
    path: str
    total_files: int
    duplicate_files: int
    total_size: int  # bytes
    recoverable_size: int  # bytes
    duplicate_density: float  # 0.0–1.0


@dataclass(frozen=True, slots=True)
class ScoreBucket:
    range: str  # e.g. "50-55"
    min: int
    max: int
    count: int


@dataclass(frozen=True, slots=True)
class FiletypeEntry:
    extension: str  # lowercase, e.g. ".mp4"
    count: int
    size: int  # bytes


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    date: str  # ISO 8601, e.g. "2024-01-15"
    total_files: int
    duplicate_files: int


@dataclass(frozen=True, slots=True)
class AnalyticsResult:
    directory_stats: tuple[DirectoryStats, ...]
    score_distribution: tuple[ScoreBucket, ...]
    filetype_breakdown: tuple[FiletypeEntry, ...]
    creation_timeline: tuple[TimelineEntry, ...]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_files_from_pairs(pairs: Sequence[ScoredPair]) -> dict[str, VideoMetadata]:
    """Deduplicate files across all scored pairs, keyed by ``str(path)``."""
    files: dict[str, VideoMetadata] = {}
    for p in pairs:
        files[str(p.file_a.path)] = p.file_a
        files[str(p.file_b.path)] = p.file_b
    return files


# ---------------------------------------------------------------------------
# Compute functions
# ---------------------------------------------------------------------------


def compute_directory_stats(
    pairs: Sequence[ScoredPair],
    all_paths: set[Path] | None = None,
    groups: Sequence[DuplicateGroup] | None = None,
    keep_strategy: str | None = None,
) -> tuple[DirectoryStats, ...]:
    """Per-directory statistics from scored pairs.

    When *groups* and *keep_strategy* are provided, recoverable bytes are
    computed from group keepers (all non-keeper members are recoverable).
    Otherwise a pair-level heuristic is used (smaller endpoint per pair).

    When *all_paths* is provided, ``total_files`` reflects the full directory
    population and ``duplicate_density`` is ``duplicate_files / total_files``.
    When absent, ``total_files == duplicate_files`` and ``density == 1.0``.
    """
    if not pairs:
        return ()

    files = _unique_files_from_pairs(pairs)
    recoverable_paths: set[str] = set()

    if groups and keep_strategy:
        # Group-aware: all non-keeper members are recoverable.
        from duplicates_detector.keeper import pick_keep_from_group

        for g in groups:
            # Skip groups where all members are references.
            non_ref = [m for m in g.members if not m.is_reference]
            if not non_ref:
                continue
            keeper = pick_keep_from_group(non_ref, keep_strategy)
            for m in g.members:
                if m.is_reference:
                    continue
                if keeper is not None and m.path == keeper.path:
                    continue
                recoverable_paths.add(str(m.path))
    else:
        # Pair-level heuristic — reference-aware, smaller endpoint as deletion
        # candidate (mirrors _compute_space_recoverable).
        for p in pairs:
            a, b = p.file_a, p.file_b
            if a.is_reference and b.is_reference:
                continue
            if a.is_reference:
                recoverable_paths.add(str(b.path))
            elif b.is_reference or a.file_size <= b.file_size:
                recoverable_paths.add(str(a.path))
            else:
                recoverable_paths.add(str(b.path))

    # Group by parent directory.
    dir_files: dict[str, list[VideoMetadata]] = defaultdict(list)
    for path_str, meta in files.items():
        dir_key = str(Path(path_str).parent)
        dir_files[dir_key].append(meta)

    # If all_paths provided, group them by directory too.
    all_paths_by_dir: dict[str, int] = {}
    if all_paths is not None:
        for ap in all_paths:
            dir_key = str(ap.parent)
            all_paths_by_dir[dir_key] = all_paths_by_dir.get(dir_key, 0) + 1

    results: list[DirectoryStats] = []
    for dir_path, metas in dir_files.items():
        duplicate_files = len(metas)
        total_size = sum(m.file_size for m in metas)
        recoverable_size = sum(m.file_size for m in metas if str(m.path) in recoverable_paths)

        if all_paths is not None:
            total_files = all_paths_by_dir.get(dir_path, duplicate_files)
            density = duplicate_files / total_files if total_files > 0 else 1.0
        else:
            total_files = duplicate_files
            density = 1.0

        results.append(
            DirectoryStats(
                path=dir_path,
                total_files=total_files,
                duplicate_files=duplicate_files,
                total_size=total_size,
                recoverable_size=recoverable_size,
                duplicate_density=density,
            )
        )

    # Sort by recoverable_size descending.
    results.sort(key=lambda d: d.recoverable_size, reverse=True)
    return tuple(results)


def compute_score_distribution(
    pairs: Sequence[ScoredPair],
    bucket_size: int = 5,
) -> tuple[ScoreBucket, ...]:
    """Histogram of pair scores bucketed by *bucket_size* points.

    Score 100.0 is placed in the last bucket. Empty input returns ``()``.
    """
    if not pairs:
        return ()

    # Find the range of scores.
    scores = [p.total_score for p in pairs]
    ceil_max = 100
    last_bucket_start = ceil_max - bucket_size

    counts: dict[int, int] = defaultdict(int)
    for s in scores:
        bucket_start = int(s) // bucket_size * bucket_size
        # Score 100.0 goes into the last bucket.
        if bucket_start >= ceil_max:
            bucket_start = last_bucket_start
        counts[bucket_start] += 1

    # Floor of the minimum score, but cap at last_bucket_start for score==100 edge case.
    floor_min = min(int(min(scores)) // bucket_size * bucket_size, last_bucket_start)

    buckets: list[ScoreBucket] = []
    for start in range(floor_min, ceil_max, bucket_size):
        end = start + bucket_size
        buckets.append(
            ScoreBucket(
                range=f"{start}-{end}",
                min=start,
                max=end,
                count=counts.get(start, 0),
            )
        )

    return tuple(buckets)


def compute_filetype_breakdown(
    pairs: Sequence[ScoredPair],
) -> tuple[FiletypeEntry, ...]:
    """File-type breakdown by extension, deduplicated by path.

    Sorted by count descending.
    """
    if not pairs:
        return ()

    files = _unique_files_from_pairs(pairs)

    ext_count: dict[str, int] = defaultdict(int)
    ext_size: dict[str, int] = defaultdict(int)
    for path_str, meta in files.items():
        ext = Path(path_str).suffix.lower()
        ext_count[ext] += 1
        ext_size[ext] += meta.file_size

    entries = [FiletypeEntry(extension=ext, count=ext_count[ext], size=ext_size[ext]) for ext in ext_count]
    entries.sort(key=lambda e: e.count, reverse=True)
    return tuple(entries)


def compute_creation_timeline(
    pairs: Sequence[ScoredPair],
    all_paths: set[Path] | None = None,
) -> tuple[TimelineEntry, ...]:
    """Daily timeline of files grouped by mtime date (UTC).

    When *all_paths* is provided, ``total_files`` reflects the full scanned
    population per day and ``duplicate_files`` counts only those that appear
    in scored pairs.  Without *all_paths*, the two fields are equal (all
    files come from pairs).

    Files without ``mtime`` are excluded. Sorted chronologically.
    """
    if not pairs:
        return ()

    # Collect pair-sourced files (all are "duplicate" files).
    dup_files = _unique_files_from_pairs(pairs)

    date_total: dict[str, int] = defaultdict(int)
    date_dup: dict[str, int] = defaultdict(int)

    # Count duplicate files by date.
    for _path_str, meta in dup_files.items():
        if meta.mtime is None:
            continue
        day = datetime.fromtimestamp(meta.mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        date_dup[day] += 1

    if all_paths is not None:
        # Stat all discovered paths to get mtime — covers non-duplicate files.
        for p in all_paths:
            try:
                mtime = os.stat(p).st_mtime
            except OSError:
                continue
            day = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
            date_total[day] += 1
    else:
        # Without all_paths, total == duplicate counts.
        date_total = dict(date_dup)

    # Merge keys — all_paths may have dates with no duplicates and vice versa.
    all_dates = set(date_total.keys()) | set(date_dup.keys())
    if not all_dates:
        return ()

    entries = [
        TimelineEntry(date=day, total_files=date_total.get(day, 0), duplicate_files=date_dup.get(day, 0))
        for day in all_dates
    ]
    entries.sort(key=lambda e: e.date)
    return tuple(entries)


def compute_analytics(
    pairs: Sequence[ScoredPair],
    all_paths: set[Path] | None = None,
    groups: Sequence[DuplicateGroup] | None = None,
    keep_strategy: str | None = None,
) -> AnalyticsResult:
    """Run all analytics computations over *pairs*."""
    return AnalyticsResult(
        directory_stats=compute_directory_stats(pairs, all_paths=all_paths, groups=groups, keep_strategy=keep_strategy),
        score_distribution=compute_score_distribution(pairs),
        filetype_breakdown=compute_filetype_breakdown(pairs),
        creation_timeline=compute_creation_timeline(pairs, all_paths=all_paths),
    )


def analytics_to_dict(result: AnalyticsResult) -> dict:
    """Convert an *AnalyticsResult* to a plain dict (JSON-serializable)."""
    return {
        "directory_stats": [dataclasses.asdict(d) for d in result.directory_stats],
        "score_distribution": [dataclasses.asdict(b) for b in result.score_distribution],
        "filetype_breakdown": [dataclasses.asdict(e) for e in result.filetype_breakdown],
        "creation_timeline": [dataclasses.asdict(e) for e in result.creation_timeline],
    }
