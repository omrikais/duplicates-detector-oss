from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from duplicates_detector.filters import format_size_human


@dataclass
class PipelineStats:
    """Accumulator for pipeline-wide statistics."""

    files_scanned: int = 0
    files_after_filter: int = 0
    extraction_failures: int = 0
    metadata_cache_hits: int = 0
    metadata_cache_misses: int = 0
    content_cache_hits: int = 0
    content_cache_misses: int = 0
    content_mode: bool = False
    metadata_cache_enabled: bool = True
    content_cache_enabled: bool = True
    total_pairs_scored: int = 0
    pairs_above_threshold: int = 0
    pairs_after_min_score: int | None = None
    groups_count: int | None = None
    display_limit: int | None = None
    total_result_count: int | None = None
    space_recoverable: int = 0
    sidecars_deleted: int = 0
    sidecar_bytes_freed: int = 0
    scan_time: float = 0.0
    extract_time: float = 0.0
    filter_time: float = 0.0
    content_hash_time: float = 0.0
    audio_fingerprint_time: float = 0.0
    scoring_time: float = 0.0
    total_time: float = 0.0
    replay_source: str | None = None
    discovered_paths: set[Path] = field(default_factory=set)


def _format_time(seconds: float) -> str:
    """Format seconds as a compact human-readable duration."""
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


def _cache_rate(hits: int, misses: int) -> str:
    """Format cache hit rate as 'hits/total (pct%)'."""
    total = hits + misses
    if total == 0:
        return "n/a"
    rate = hits / total
    return f"{rate:.0%}"


def print_summary(stats: PipelineStats, console: Console | None = None) -> None:
    """Render a compact post-run summary panel to stderr."""
    if console is None:
        console = Console(stderr=True)

    lines: list[str] = []

    if stats.replay_source is not None:
        # Replay mode: simplified summary
        lines.append(f"Replay source: {stats.replay_source}")
        lines.append(f"Pairs loaded: {stats.total_pairs_scored:,}")

        # Scoring results
        scoring = f"{stats.pairs_above_threshold:,} duplicates"
        if stats.pairs_after_min_score is not None and stats.pairs_after_min_score != stats.pairs_above_threshold:
            scoring += f" → {stats.pairs_after_min_score:,} above min-score"
        if stats.groups_count is not None:
            scoring += f" ({stats.groups_count:,} groups)"
        lines.append(scoring)

        if stats.space_recoverable > 0:
            lines.append(f"~{format_size_human(stats.space_recoverable)} recoverable")

        lines.append(f"Time: {_format_time(stats.total_time)}")
    else:
        # Normal scan mode
        # Line 1: files scanned with optional qualifiers
        parts: list[str] = [f"{stats.files_scanned:,} files scanned"]
        filtered = stats.files_scanned - stats.extraction_failures - stats.files_after_filter
        if filtered > 0:
            parts.append(f"{filtered:,} filtered")
        if stats.extraction_failures > 0:
            parts.append(f"{stats.extraction_failures:,} failed")
        lines.append(parts[0] if len(parts) == 1 else f"{parts[0]} ({', '.join(parts[1:])})")

        # Line 2: scoring results
        scoring = f"{stats.total_pairs_scored:,} pairs scored → {stats.pairs_above_threshold:,} duplicates"
        if stats.pairs_after_min_score is not None and stats.pairs_after_min_score != stats.pairs_above_threshold:
            scoring += f" → {stats.pairs_after_min_score:,} above min-score"
        if stats.groups_count is not None:
            scoring += f" ({stats.groups_count:,} groups)"
        if stats.pairs_after_min_score is not None:
            effective_count = stats.pairs_after_min_score
        else:
            effective_count = stats.pairs_above_threshold
        actual_count = stats.groups_count if stats.groups_count is not None else effective_count
        if stats.display_limit is not None and stats.display_limit < actual_count:
            if stats.total_result_count is not None:
                scoring += f" (showing {stats.display_limit:,} of {stats.total_result_count:,})"
            else:
                scoring += f" (showing {stats.display_limit:,})"
        lines.append(scoring)

        # Line 3: space recoverable (only if duplicates found)
        if stats.space_recoverable > 0:
            lines.append(f"~{format_size_human(stats.space_recoverable)} recoverable")

        # Line 3b: sidecar stats (only if sidecars were deleted)
        if stats.sidecars_deleted > 0:
            lines.append(
                f"{stats.sidecars_deleted:,} sidecar(s) deleted ({format_size_human(stats.sidecar_bytes_freed)} freed)"
            )

        # Line 4: cache stats (only if caching was used)
        cache_parts: list[str] = []
        if stats.metadata_cache_enabled:
            cache_parts.append(f"{_cache_rate(stats.metadata_cache_hits, stats.metadata_cache_misses)} metadata")
        if stats.content_mode and stats.content_cache_enabled:
            cache_parts.append(f"{_cache_rate(stats.content_cache_hits, stats.content_cache_misses)} content")
        if cache_parts:
            lines.append(f"Cache: {', '.join(cache_parts)}")

        # Line 5: timing
        timing_parts = [f"scan {_format_time(stats.scan_time)}"]
        timing_parts.append(f"metadata {_format_time(stats.extract_time)}")
        if stats.content_mode:
            timing_parts.append(f"content {_format_time(stats.content_hash_time)}")
        if stats.audio_fingerprint_time > 0:
            timing_parts.append(f"audio {_format_time(stats.audio_fingerprint_time)}")
        timing_parts.append(f"scoring {_format_time(stats.scoring_time)}")
        lines.append(f"Time: {', '.join(timing_parts)} ({_format_time(stats.total_time)} total)")

    panel = Panel(
        "\n".join(lines),
        title="Summary",
        border_style="dim",
        expand=False,
    )
    console.print(panel)
