from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path

from rapidfuzz import fuzz
from rapidfuzz.process import extract
from rich.console import Console

from duplicates_detector.comparators import (
    Comparator,
    FileNameComparator,
    get_default_comparators,
    get_image_comparators,
    normalize_filename,
)
from duplicates_detector.config import Mode
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.progress import make_progress

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from duplicates_detector.cache_db import CacheDB
    from duplicates_detector.progress import ProgressEmitter

# ---------------------------------------------------------------------------
# Shared counter for per-pair progress reporting (ProcessPoolExecutor)
# ---------------------------------------------------------------------------

_shared_pair_counter: Any = None


def _init_score_worker(counter: Any) -> None:
    """ProcessPoolExecutor initializer -- stores shared counter in module global."""
    global _shared_pair_counter  # noqa: PLW0603
    _shared_pair_counter = counter


# ---------------------------------------------------------------------------
# Config hash for scoring cache keys
# ---------------------------------------------------------------------------


def compute_config_hash(
    weights: Mapping[str, float],
    *,
    has_content: bool = False,
    has_audio: bool = False,
    content_method: str | None = None,
    mode: str = Mode.VIDEO,
) -> str:
    """Compute MD5 hex digest of scoring configuration for cache key.

    The hash captures all parameters that affect pair scores so that
    cached scores are automatically invalidated when the configuration
    changes.
    """
    config = {
        "weights": dict(weights),
        "has_content": has_content,
        "has_audio": has_audio,
        "content_method": content_method,
        "mode": mode,
    }
    return hashlib.md5(json.dumps(config, sort_keys=True).encode()).hexdigest()


# Minimum raw filename similarity (0.0–1.0) to consider a pair.
# Prevents coincidental metadata matches (duration, resolution, file size)
# from making unrelated files appear as duplicates.
_MIN_FILENAME_RATIO = 0.6


def _get_or_compute_sha256(meta: VideoMetadata, sha256_lookup: dict[Path, str] | None = None) -> str:
    """Return SHA-256 hex digest, checking lookup dict first then reading file.

    Top-level function for pickling compatibility with ProcessPoolExecutor.
    Reads the file in 64KB chunks.
    """
    if sha256_lookup is not None:
        cached = sha256_lookup.get(meta.path)
        if cached is not None:
            return cached

    h = hashlib.sha256()
    with open(meta.path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class ScoredPair:
    file_a: VideoMetadata
    file_b: VideoMetadata
    total_score: float  # 0.0 - 100.0
    breakdown: dict[str, float | None]  # comparator name -> weighted contribution (None = no data)
    detail: dict[str, tuple[float, float]]  # comparator name -> (raw_score, weight)


def _bucket_by_duration(
    items: list[VideoMetadata],
    tolerance: float = 2.0,
) -> list[list[VideoMetadata]]:
    """Group videos into duration buckets where members are within ±tolerance seconds.

    Videos with unknown duration go into a catch-all bucket.
    """
    known = sorted(
        [v for v in items if v.duration is not None],
        key=lambda v: v.duration,  # type: ignore[arg-type]
    )
    unknown = [v for v in items if v.duration is None]

    buckets: list[list[VideoMetadata]] = []

    if known:
        current_bucket: list[VideoMetadata] = [known[0]]
        bucket_start = known[0].duration  # type: ignore[assignment]

        for item in known[1:]:
            if item.duration is None:
                raise ValueError(f"item.duration must not be None (filtered to known durations): {item.path}")
            if item.duration - bucket_start <= tolerance * 2:
                current_bucket.append(item)
            else:
                if len(current_bucket) >= 2:
                    buckets.append(current_bucket)
                current_bucket = [item]
                bucket_start = item.duration

        if len(current_bucket) >= 2:
            buckets.append(current_bucket)

    if unknown:
        buckets.append(unknown)

    return buckets


def _bucket_by_page_count(
    items: list[VideoMetadata],
    tolerance: int = 2,
) -> list[list[VideoMetadata]]:
    """Group documents into page-count buckets where members are within ±tolerance pages.

    Documents with unknown page count go into a catch-all bucket.
    """
    known: list[VideoMetadata] = []
    unknown: list[VideoMetadata] = []
    for v in items:
        if v.page_count is not None:
            known.append(v)
        else:
            unknown.append(v)
    known.sort(key=lambda v: v.page_count)  # type: ignore[arg-type]

    buckets: list[list[VideoMetadata]] = []
    current: list[VideoMetadata] = []
    bucket_start: int = 0
    for v in known:
        pc: int = v.page_count  # type: ignore[assignment]  # pre-filtered to non-None
        if current and pc - bucket_start > tolerance * 2:
            if len(current) >= 2:
                buckets.append(current)
            current = []
            bucket_start = pc
        if not current:
            bucket_start = pc
        current.append(v)
    if len(current) >= 2:
        buckets.append(current)

    if len(unknown) >= 2:
        buckets.append(unknown)
    return buckets


def _pair_key(a: VideoMetadata, b: VideoMetadata) -> tuple[Path, Path]:
    """Canonical key for a pair (smaller path first)."""
    if str(a.path) <= str(b.path):
        return (a.path, b.path)
    return (b.path, a.path)


def _pair_has_tfidf(a: VideoMetadata, b: VideoMetadata, comparators: list[Comparator]) -> bool:
    """Return True when a TF-IDF matrix is attached and both items are indexed."""
    from duplicates_detector.comparators import ContentComparator as _CC

    for c in comparators:
        if isinstance(c, _CC) and c._tfidf_index_map is not None:
            return a.path in c._tfidf_index_map and b.path in c._tfidf_index_map
    return False


def _score_pair(
    a: VideoMetadata,
    b: VideoMetadata,
    comparators: list[Comparator],
    *,
    threshold: float = 0.0,
    has_content: bool = False,
    sha256_lookup: dict[Path, str] | None = None,
) -> ScoredPair | None:
    """Compute the similarity score for a pair of videos.

    Returns None if the pair scores below threshold.
    Comparators return None for missing metadata — these contribute 0 to the
    total but are tracked separately in the breakdown (displayed as "n/a").

    Heuristic: identical filename + identical file size (>0) → score 100.
    Byte-identical: same file_size + same pre_hash → verify via SHA-256 → score 100.
    Filename gate: pairs with raw filename similarity < _MIN_FILENAME_RATIO
    are rejected — coincidental metadata similarity alone is not enough.
    The gate is disabled when *has_content* is True, since the content
    comparator can identify duplicates regardless of filename similarity.
    """
    # Identical name + size means identical file regardless of missing metadata.
    # Compare normalized filenames so differences in case/separators
    # (e.g. "My.Movie" vs "My Movie") don't defeat the heuristic.
    identical = (
        normalize_filename(a.filename) == normalize_filename(b.filename)
        and a.file_size == b.file_size
        and a.file_size > 0
    )

    # Byte-identical fast path: files with same size and pre-hash (MD5 of first 4KB)
    # are verified via full SHA-256.  If they match, short-circuit to score 100.
    # Skip when `identical` already guarantees 100 — avoids unnecessary file reads.
    if not identical and a.file_size == b.file_size > 0 and a.pre_hash is not None and a.pre_hash == b.pre_hash:
        try:
            sha_a = _get_or_compute_sha256(a, sha256_lookup)
            sha_b = _get_or_compute_sha256(b, sha256_lookup)
            if sha_a == sha_b:
                # Store computed hashes back so post-scoring cache loop can reuse them
                if sha256_lookup is not None:
                    sha256_lookup[a.path] = sha_a
                    sha256_lookup[b.path] = sha_b
                return ScoredPair(
                    file_a=a,
                    file_b=b,
                    total_score=100.0,
                    breakdown={"byte_identical": 100.0},
                    detail={"byte_identical": (1.0, 100.0)},
                )
        except OSError:
            pass  # Fall through to normal scoring on I/O errors

    total = 0.0
    breakdown: dict[str, float | None] = {}
    detail: dict[str, tuple[float, float]] = {}
    remaining_weight = sum(c.weight for c in comparators)

    for comp in comparators:
        remaining_weight -= comp.weight
        raw = comp.score(a, b)

        if raw is None:
            breakdown[comp.name] = None
        else:
            weighted = raw * comp.weight
            breakdown[comp.name] = round(weighted, 1)
            detail[comp.name] = (raw, comp.weight)
            total += weighted

        # Filename gate: low filename similarity means the files are unrelated,
        # regardless of how similar their metadata happens to be.
        # Disabled in content mode when both files have usable content hashes,
        # since the content comparator can identify duplicates (re-encodes,
        # renamed copies) even with dissimilar names.  When either hash is
        # missing the gate stays active to prevent metadata-only false positives.
        pair_has_content = has_content and (
            (a.clip_embedding is not None and b.clip_embedding is not None)
            or (a.content_hash is not None and b.content_hash is not None)
            or (a.content_frames is not None and b.content_frames is not None)
            or (a.audio_fingerprint is not None and b.audio_fingerprint is not None)
            or _pair_has_tfidf(a, b, comparators)
        )
        if (
            not pair_has_content
            and comp.name == "filename"
            and comp.weight > 0
            and not identical
            and raw is not None
            and raw < _MIN_FILENAME_RATIO
        ):
            return None

        # Early exit: even perfect scores on remaining comparators can't reach threshold
        # (skip when identical-file heuristic will override the total anyway)
        if not identical and total + remaining_weight < threshold:
            return None

    if identical:
        total = 100.0

    return ScoredPair(
        file_a=a,
        file_b=b,
        total_score=round(total, 1),
        breakdown=breakdown,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Worker functions for ProcessPoolExecutor (must be top-level for pickling)
# ---------------------------------------------------------------------------


def _score_bucket_chunk_worker(
    args: tuple[
        list[list[VideoMetadata]],
        float,
        list[Comparator],
        bool,
        dict[tuple[str, str], dict],
        dict[Path, str] | None,
    ],
) -> tuple[list[ScoredPair], set[tuple[Path, Path]], int]:
    """Score all pairs within a chunk of duration buckets."""
    bucket_chunk, threshold, comparators, has_content, cached_pairs_lookup, sha256_lookup = args
    results: list[ScoredPair] = []
    seen: set[tuple[Path, Path]] = set()
    cached_count = 0

    for bucket in bucket_chunk:
        for i, a in enumerate(bucket):
            for j in range(i + 1, len(bucket)):
                b = bucket[j]
                key = _pair_key(a, b)
                seen.add(key)

                # Check scoring cache before computing
                if cached_pairs_lookup:
                    cache_key = _cache_lookup_key(a, b)
                    cached_entry = cached_pairs_lookup.get(cache_key)
                    if cached_entry is not None:
                        scored = _scored_pair_from_cache(a, b, cached_entry, threshold=threshold)
                        if scored is not None:
                            results.append(scored)
                        cached_count += 1
                        if _shared_pair_counter is not None:
                            with _shared_pair_counter.get_lock():
                                _shared_pair_counter.value += 1
                        continue

                scored = _score_pair(
                    a, b, comparators, threshold=threshold, has_content=has_content, sha256_lookup=sha256_lookup
                )
                if scored is not None:
                    results.append(scored)
                if _shared_pair_counter is not None:
                    with _shared_pair_counter.get_lock():
                        _shared_pair_counter.value += 1

    return results, seen, cached_count


def _filename_chunk_worker(
    args: tuple[
        int,
        int,
        list[VideoMetadata],
        list[str],
        set[tuple[Path, Path]],
        float,
        float,
        list[Comparator],
        bool,
        dict[tuple[str, str], dict],
        dict[Path, str] | None,
    ],
) -> tuple[list[ScoredPair], set[tuple[Path, Path]], int]:
    """Score filename-similar cross-bucket pairs for a slice of items.

    Uses rapidfuzz.process.extract for efficient batch matching.
    Returns (scored_pairs, evaluated_keys, cached_count) where evaluated_keys
    contains the pair keys of all pairs evaluated (regardless of whether they
    passed threshold), and cached_count is how many came from the scoring cache.
    """
    (
        start,
        end,
        items,
        normalized,
        bucketed_pairs,
        threshold,
        name_threshold,
        comparators,
        has_content,
        cached_pairs_lookup,
        sha256_lookup,
    ) = args
    results: list[ScoredPair] = []
    evaluated_keys: set[tuple[Path, Path]] = set()
    cached_count = 0

    for i in range(start, end):
        candidates = normalized[i + 1 :]
        if not candidates:
            break

        matches = extract(
            normalized[i],
            candidates,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=name_threshold,
            limit=None,
        )

        for _, _score, idx in matches:
            j = i + 1 + idx
            a, b = items[i], items[j]

            key = _pair_key(a, b)
            if key in bucketed_pairs:
                continue

            evaluated_keys.add(key)

            # Check scoring cache before computing
            if cached_pairs_lookup:
                cache_key = _cache_lookup_key(a, b)
                cached_entry = cached_pairs_lookup.get(cache_key)
                if cached_entry is not None:
                    scored = _scored_pair_from_cache(a, b, cached_entry, threshold=threshold)
                    if scored is not None:
                        results.append(scored)
                    cached_count += 1
                    if _shared_pair_counter is not None:
                        with _shared_pair_counter.get_lock():
                            _shared_pair_counter.value += 1
                    continue

            scored = _score_pair(
                a, b, comparators, threshold=threshold, has_content=has_content, sha256_lookup=sha256_lookup
            )
            if scored is not None:
                results.append(scored)
            if _shared_pair_counter is not None:
                with _shared_pair_counter.get_lock():
                    _shared_pair_counter.value += 1

    return results, evaluated_keys, cached_count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _count_bucket_pairs(buckets: list[list[VideoMetadata]]) -> int:
    """Count total pairwise comparisons across all buckets."""
    return sum(len(b) * (len(b) - 1) // 2 for b in buckets)


# ---------------------------------------------------------------------------
# Multi-level sub-bucketing for large duration buckets
# ---------------------------------------------------------------------------

_MAX_BUCKET_PAIRS = 50_000  # Threshold before applying sub-bucketing


def _resolution_tier(v: VideoMetadata) -> str:
    """Classify video into a resolution tier for sub-bucketing."""
    if v.width is None or v.height is None:
        return "unknown"
    pixels = v.width * v.height
    if pixels <= 153_600:
        return "ld"  # ≤ ~360p
    if pixels <= 409_920:
        return "sd"  # ≤ ~480p
    if pixels <= 921_600:
        return "hd"  # ≤ ~720p
    if pixels <= 2_073_600:
        return "fhd"  # ≤ ~1080p
    if pixels <= 3_686_400:
        return "qhd"  # ≤ ~1440p
    return "uhd"


def _filesize_tier(v: VideoMetadata) -> int:
    """Log-scale file size tier (each tier is ~2x the previous)."""
    if v.file_size <= 0:
        return -1
    mb = v.file_size / (1024 * 1024)
    return int(math.log2(max(mb, 0.1)))


def _refine_large_buckets(
    buckets: list[list[VideoMetadata]],
    max_pairs: int = _MAX_BUCKET_PAIRS,
) -> list[list[VideoMetadata]]:
    """Split large buckets using resolution and file-size sub-bucketing.

    Preserves small buckets as-is.  Large ones are split first by resolution
    tier, then by file-size tier if still too large.  The filename pass
    catches cross-tier duplicates that sub-bucketing might separate.
    """
    refined: list[list[VideoMetadata]] = []

    for bucket in buckets:
        n = len(bucket)
        if n * (n - 1) // 2 <= max_pairs:
            refined.append(bucket)
            continue

        # Level 1: sub-bucket by resolution
        by_res: dict[str, list[VideoMetadata]] = {}
        for v in bucket:
            by_res.setdefault(_resolution_tier(v), []).append(v)

        for sub in by_res.values():
            m = len(sub)
            if m < 2:
                continue
            if m * (m - 1) // 2 <= max_pairs:
                refined.append(sub)
                continue

            # Level 2: sub-bucket by file size
            by_size: dict[int, list[VideoMetadata]] = {}
            for v in sub:
                by_size.setdefault(_filesize_tier(v), []).append(v)

            for sub2 in by_size.values():
                if len(sub2) >= 2:
                    refined.append(sub2)

    return refined


def _bucket_by_resolution_tier(
    items: list[VideoMetadata],
) -> list[list[VideoMetadata]]:
    """Group items by resolution tier for image mode pre-filtering.

    Uses the existing _resolution_tier() classifier. Drops buckets
    with fewer than 2 items.
    """
    by_tier: dict[str, list[VideoMetadata]] = {}
    for v in items:
        by_tier.setdefault(_resolution_tier(v), []).append(v)
    return [bucket for bucket in by_tier.values() if len(bucket) >= 2]


def find_duplicates(
    items: list[VideoMetadata],
    *,
    threshold: float = 50.0,
    comparators: list[Comparator] | None = None,
    workers: int = 0,
    verbose: bool = False,
    stats: dict[str, int] | None = None,
    quiet: bool = False,
    mode: str = Mode.VIDEO,
    progress_emitter: ProgressEmitter | None = None,
    cache_db: CacheDB | None = None,
    config_hash: str | None = None,
    content_method: str | None = None,
    pause_waiter: Callable[[], None] | None = None,
    _emit_score_stage: bool = True,
    _progress_offset: int = 0,
    _total_offset: int = 0,
) -> list[ScoredPair]:
    """Find potential duplicate video pairs above the similarity threshold.

    Uses duration bucketing as primary pre-filter, with a secondary
    filename-based pass for cross-bucket matches. Both passes are
    parallelized across CPU cores using ProcessPoolExecutor.

    Args:
        workers: Number of CPU workers for scoring. 0 = auto (cpu_count).
        verbose: Show supplementary text (bucket stats, pair counts).
        stats: Optional mutable dict populated with ``total_pairs_scored``.
        cache_db: Optional CacheDB instance for scoring cache lookups/writes.
        config_hash: Scoring configuration hash (from ``compute_config_hash``).
            Required when *cache_db* is provided.
        pause_waiter: Optional blocking callback used to pause scorer work
            from executor threads until the pipeline resumes.
        _emit_score_stage: When False, suppress stage_start/stage_end
            emissions while still emitting granular progress events.
            Used by auto-mode wrapper to avoid duplicate stage lifecycle.
        _progress_offset: Base value added to ``current`` in progress
            events. Used by auto-mode to keep cumulative progress across
            sequential video/image scoring invocations.
        _total_offset: Base value added to ``total`` in progress events.
    """
    _console = Console(stderr=True)

    if len(items) < 2:
        if stats is not None:
            stats["total_pairs_scored"] = 0
        return []

    if workers <= 0:
        workers = os.cpu_count() or 4

    # SSIM mode stores large PNG frame blobs on each VideoMetadata.
    # Force serial scoring to avoid pickling those blobs across
    # ProcessPoolExecutor worker boundaries (IPC fan-out).
    has_ssim_frames = any(v.content_frames is not None for v in items)
    if has_ssim_frames:
        workers = 1

    # TF-IDF mode: build matrix from text_content, attach to ContentComparator,
    # and force serial scoring (scipy sparse matrix can't be pickled across
    # ProcessPoolExecutor boundaries).
    if content_method == "tfidf" and comparators is not None:
        from duplicates_detector.comparators import ContentComparator as _ContentComparator

        content_comp = next((c for c in comparators if isinstance(c, _ContentComparator)), None)
        if content_comp is not None and content_comp._is_document:
            from duplicates_detector.tfidf import build_tfidf_matrix

            tfidf_items = [v for v in items if v.text_content is not None]
            if len(tfidf_items) >= 2:
                matrix = build_tfidf_matrix(tfidf_items)
                if matrix is not None:
                    index_map = {v.path: idx for idx, v in enumerate(tfidf_items)}
                    content_comp.set_tfidf_data(matrix, index_map)
                    workers = 1

    if comparators is None:
        if mode == Mode.IMAGE:
            comparators = get_image_comparators()
        elif mode == Mode.AUDIO:
            from duplicates_detector.comparators import get_audio_mode_comparators

            comparators = get_audio_mode_comparators()
        elif mode == Mode.DOCUMENT:
            from duplicates_detector.comparators import get_document_comparators

            comparators = get_document_comparators()
        else:
            comparators = get_default_comparators()

    has_content = any(c.name in ("content", "audio") for c in comparators)

    # --- Scoring cache: bulk lookup ---
    cached_pairs_lookup: dict[tuple[str, str], dict] = {}
    if cache_db is not None and config_hash is not None:
        mtimes: dict[Path, float] = {}
        for item in items:
            try:
                mtimes[item.path] = item.path.stat().st_mtime
            except OSError:
                pass
        cached = cache_db.get_scored_pairs_bulk(
            {item.path for item in items},
            config_hash=config_hash,
            mtimes=mtimes,
        )
        for entry in cached:
            cached_pairs_lookup[(entry["path_a"], entry["path_b"])] = entry

    # --- SHA-256 cache: pre-load known hashes ---
    sha256_lookup: dict[Path, str] = {}
    if cache_db is not None:
        for item in items:
            try:
                st = item.path.stat()
                cached_sha = cache_db.get_sha256(item.path, file_size=st.st_size, mtime=st.st_mtime)
                if cached_sha is not None:
                    sha256_lookup[item.path] = cached_sha
            except OSError:
                pass
    preloaded_sha256_paths = frozenset(sha256_lookup)

    # Pre-compute normalized filenames once (avoids redundant regex per comparison)
    normalized = [normalize_filename(v.filename) for v in items]
    normalized_lookup = {v.filename: n for v, n in zip(items, normalized)}

    # Pre-populate filename comparator cache to avoid per-pair recomputation
    for comp in comparators:
        if isinstance(comp, FileNameComparator):
            comp.set_normalized_cache(normalized_lookup)

    # --- Pass 1: Bucketed pairwise comparison ---
    if mode == Mode.IMAGE:
        buckets = _bucket_by_resolution_tier(items)
    elif mode == Mode.DOCUMENT:
        buckets = _bucket_by_page_count(items)
    else:
        buckets = _bucket_by_duration(items)
    raw_pairs = _count_bucket_pairs(buckets)
    buckets = _refine_large_buckets(buckets)
    total_pairs = _count_bucket_pairs(buckets)

    if verbose:
        largest = max(len(b) for b in buckets) if buckets else 0
        _console.print(
            f"  [dim]{len(buckets):,} comparison groups "
            f"(largest {largest:,} items), "
            f"{total_pairs:,} pairs to score"
            f"{f' (reduced from {raw_pairs:,})' if total_pairs < raw_pairs else ''}[/dim]"
        )

    total_scored = total_pairs + _total_offset  # Pass 1 always evaluates this many pairs
    actual_pairs_evaluated = total_pairs  # Accurate count for stats (no offsets/inflation)

    if mode == Mode.IMAGE:
        pass1_label = "Scoring resolution groups"
    elif mode == Mode.DOCUMENT:
        pass1_label = "Scoring page-count groups"
    else:
        pass1_label = "Scoring duration buckets"

    if progress_emitter is not None and _emit_score_stage:
        progress_emitter.stage_start("score", total=total_pairs)
    score_start = time.monotonic()
    score_progress_count = _progress_offset

    def _score_cache_stats() -> tuple[int | None, int | None]:
        if cache_db is not None:
            s = cache_db.stats()
            return s.get("score_hits", 0), s.get("score_misses", 0)
        return None, None

    def _pause_if_needed() -> None:
        if pause_waiter is not None:
            pause_waiter()

    with make_progress(console=_console, quiet=quiet, progress_emitter=progress_emitter, unit="pairs") as progress:
        # --- Pass 1: Bucketed scoring ---
        task1 = progress.add_task(pass1_label, total=total_pairs)

        def _advance_pair() -> None:
            nonlocal score_progress_count
            _pause_if_needed()
            progress.advance(task1)
            score_progress_count += 1
            if progress_emitter is not None:
                progress_emitter.progress("score", current=score_progress_count, total=total_scored)

        if workers > 1 and len(buckets) > 1:
            pairs, seen_pairs, pass1_cached = _score_buckets_parallel(
                buckets,
                threshold,
                workers,
                comparators,
                has_content=has_content,
                on_pair=_advance_pair,
                wait_if_paused=_pause_if_needed if pause_waiter is not None else None,
                cached_pairs_lookup=cached_pairs_lookup,
                sha256_lookup=sha256_lookup or None,
            )
        else:
            pairs, seen_pairs, pass1_cached = _score_buckets_serial(
                buckets,
                threshold,
                comparators,
                has_content=has_content,
                on_pair=_advance_pair,
                cached_pairs_lookup=cached_pairs_lookup,
                wait_if_paused=_pause_if_needed if pause_waiter is not None else None,
                sha256_lookup=sha256_lookup or None,
            )
        actual_pairs_evaluated -= pass1_cached

        # --- Pass 2: Cross-bucket filename matching ---
        task2 = progress.add_task("Checking filename matches", total=len(items))

        # Pre-estimate pass 2 contribution for machine progress total.
        # Actual pair count is unknown upfront; use item count as proxy.
        pass2_estimate = len(items)
        total_scored += pass2_estimate
        pass2_progress = 0

        def _advance_item() -> None:
            nonlocal score_progress_count, pass2_progress
            _pause_if_needed()
            progress.advance(task2)
            pass2_progress += 1
            score_progress_count += 1
            if progress_emitter is not None:
                progress_emitter.progress("score", current=score_progress_count, total=total_scored)

        if workers > 1 and len(items) > 100:
            extra, filename_keys, pass2_cached = _filename_pass_parallel(
                items,
                normalized,
                seen_pairs,
                threshold,
                workers,
                comparators,
                has_content=has_content,
                on_item=_advance_item,
                wait_if_paused=_pause_if_needed if pause_waiter is not None else None,
                cached_pairs_lookup=cached_pairs_lookup,
                sha256_lookup=sha256_lookup or None,
            )
        else:
            extra, filename_keys, pass2_cached = _filename_pass_serial(
                items,
                normalized,
                seen_pairs,
                comparators,
                threshold,
                has_content=has_content,
                on_item=_advance_item,
                cached_pairs_lookup=cached_pairs_lookup,
                wait_if_paused=_pause_if_needed if pause_waiter is not None else None,
                sha256_lookup=sha256_lookup or None,
            )
        # Correct the progress estimate with actual pair count.
        # During pass 2, _advance_item incremented score_progress_count
        # once per *item* (for the Rich progress bar), but total_scored
        # tracks *pairs*.  Reconcile so totals are consistent without
        # ever moving current backward (monotonicity for consumers).
        actual_pairs_evaluated += len(filename_keys) - pass2_cached
        pass2_actual_pairs = len(filename_keys)
        if pass2_actual_pairs >= pass2_progress:
            # More pairs than items — bump current to match actual work.
            score_progress_count += pass2_actual_pairs - pass2_progress
        # Replace the item-count estimate with whichever is larger:
        # the actual pair count or the already-emitted item increments.
        # This keeps current monotonic while aligning total with reality.
        total_scored += max(pass2_actual_pairs, pass2_progress) - pass2_estimate
        # Ensure total never drops below current.
        total_scored = max(total_scored, score_progress_count)
        if progress_emitter is not None:
            _sh, _sm = _score_cache_stats()
            progress_emitter.progress(
                "score", current=score_progress_count, total=total_scored, force=True, cache_hits=_sh, cache_misses=_sm
            )

        pairs.extend(extra)
        # Add ALL evaluated pairs to seen_pairs (not just above-threshold)
        # so pass 3 doesn't redundantly re-score them.
        seen_pairs.update(filename_keys)

        # --- Pass 3: Content-hash all-pairs (content mode only) ---
        # When --content is active, renamed re-encodes with different
        # durations land in different buckets and may fail the 80%
        # filename cutoff.  Compare all cross-bucket pairs where BOTH
        # files have a content hash.  This pass only touches the
        # successfully-hashed subset, so its cost scales with the
        # number of usable hashes, not the total file count.
        if has_content:
            hashed = [
                v
                for v in items
                if v.clip_embedding is not None
                or v.content_hash is not None
                or v.content_frames is not None
                or v.audio_fingerprint is not None
                or v.text_content is not None
            ]
            if len(hashed) >= 2:
                # Count only pairs not already evaluated in earlier passes.
                # Use raw paths (not resolved) to match _pair_key's format.
                hashed_paths = {v.path for v in hashed}
                already_seen = sum(1 for a, b in seen_pairs if a in hashed_paths and b in hashed_paths)
                nh = len(hashed)
                content_new_pairs = nh * (nh - 1) // 2 - already_seen
                actual_pairs_evaluated += max(content_new_pairs, 0)
                total_scored += max(content_new_pairs, 0)

                def _advance_content_pair() -> None:
                    nonlocal score_progress_count
                    _pause_if_needed()
                    score_progress_count += 1
                    if progress_emitter is not None:
                        progress_emitter.progress("score", current=score_progress_count, total=total_scored)

                def _advance_content_chunk(count: int) -> None:
                    nonlocal score_progress_count
                    _pause_if_needed()
                    score_progress_count += count
                    if progress_emitter is not None:
                        progress_emitter.progress("score", current=score_progress_count, total=total_scored)

                if workers > 1 and len(hashed) > 100:
                    content_extra, pass3_cached = _content_pass_parallel(
                        hashed,
                        seen_pairs,
                        comparators,
                        threshold,
                        workers,
                        on_chunk=_advance_content_chunk,
                        wait_if_paused=_pause_if_needed if pause_waiter is not None else None,
                        cached_pairs_lookup=cached_pairs_lookup,
                        sha256_lookup=sha256_lookup or None,
                    )
                else:
                    content_extra, pass3_cached = _content_pass_serial(
                        hashed,
                        seen_pairs,
                        comparators,
                        threshold,
                        on_pair=_advance_content_pair,
                        cached_pairs_lookup=cached_pairs_lookup,
                        wait_if_paused=_pause_if_needed if pause_waiter is not None else None,
                        sha256_lookup=sha256_lookup or None,
                    )
                actual_pairs_evaluated -= pass3_cached
                if progress_emitter is not None:
                    _sh, _sm = _score_cache_stats()
                    progress_emitter.progress(
                        "score",
                        current=score_progress_count,
                        total=total_scored,
                        force=True,
                        cache_hits=_sh,
                        cache_misses=_sm,
                    )
                pairs.extend(content_extra)

    if progress_emitter is not None:
        _sh, _sm = _score_cache_stats()
        progress_emitter.progress(
            "score", current=score_progress_count, total=total_scored, force=True, cache_hits=_sh, cache_misses=_sm
        )
        if _emit_score_stage:
            progress_emitter.stage_end(
                "score",
                total=actual_pairs_evaluated,
                elapsed=time.monotonic() - score_start,
                pairs_found=len(pairs),
                cache_hits=_sh if _sh else 0,
                cache_misses=_sm if _sm else 0,
            )

    # --- Scoring cache: bulk write newly scored pairs ---
    if cache_db is not None and config_hash is not None:
        new_rows: list[tuple[str, str, float, float, str, float, str]] = []
        for pair in pairs:
            try:
                ka = str(pair.file_a.path.resolve())
                kb = str(pair.file_b.path.resolve())
                if ka > kb:
                    ka, kb = kb, ka
                    ma = pair.file_b.path.stat().st_mtime
                    mb = pair.file_a.path.stat().st_mtime
                else:
                    ma = pair.file_a.path.stat().st_mtime
                    mb = pair.file_b.path.stat().st_mtime
                # Skip pairs already in cache (came from cache hits)
                if (ka, kb) in cached_pairs_lookup:
                    continue
                detail_json = json.dumps({k: list(v) for k, v in pair.detail.items()}, separators=(",", ":"))
                new_rows.append((ka, kb, ma, mb, config_hash, pair.total_score, detail_json))
            except OSError:
                pass
        if new_rows:
            cache_db.put_scored_pairs_bulk(new_rows)

    # --- SHA-256 cache: store newly computed hashes from byte-identical pairs ---
    if cache_db is not None:
        for pair in pairs:
            if "byte_identical" in pair.detail:
                for meta in (pair.file_a, pair.file_b):
                    if meta.path not in preloaded_sha256_paths:
                        try:
                            sha = _get_or_compute_sha256(meta)
                            st = meta.path.stat()
                            cache_db.put_sha256(meta.path, file_size=st.st_size, mtime=st.st_mtime, sha256=sha)
                            sha256_lookup[meta.path] = sha
                        except OSError:
                            pass

    if stats is not None:
        # total_pairs_scored: exact number of pairs evaluated (for summary).
        # _progress_current/_progress_total: monotonic progress-bar units
        # (may exceed total_pairs_scored because pass 2 emits per-item
        # increments for responsiveness, and monotonicity prevents rollback
        # when fewer pairs than items are found).
        stats["total_pairs_scored"] = actual_pairs_evaluated
        stats["_progress_current"] = score_progress_count
        stats["_progress_total"] = total_scored

    # Strip SSIM frame data from results — no longer needed after scoring.
    # Prevents large PNG blobs from persisting through sort/group/report.
    if has_ssim_frames:
        pairs = [
            ScoredPair(
                file_a=replace(p.file_a, content_frames=None),
                file_b=replace(p.file_b, content_frames=None),
                total_score=p.total_score,
                breakdown=p.breakdown,
                detail=p.detail,
            )
            for p in pairs
        ]

    # Strip CLIP embeddings from results — no longer needed after scoring.
    # Prevents large float32 vectors from persisting through sort/group/report.
    if any(p.file_a.clip_embedding is not None for p in pairs):
        pairs = [
            ScoredPair(
                file_a=replace(p.file_a, clip_embedding=None),
                file_b=replace(p.file_b, clip_embedding=None),
                total_score=p.total_score,
                breakdown=p.breakdown,
                detail=p.detail,
            )
            for p in pairs
        ]

    # Strip text_content from results — no longer needed after scoring.
    # Prevents large extracted text from persisting through sort/group/report.
    if any(p.file_a.text_content is not None or p.file_b.text_content is not None for p in pairs):
        pairs = [
            ScoredPair(
                file_a=replace(p.file_a, text_content=None),
                file_b=replace(p.file_b, text_content=None),
                total_score=p.total_score,
                breakdown=p.breakdown,
                detail=p.detail,
            )
            for p in pairs
        ]

    pairs.sort(key=lambda p: p.total_score, reverse=True)
    return pairs


def _score_buckets_parallel(
    buckets: list[list[VideoMetadata]],
    threshold: float,
    workers: int,
    comparators: list[Comparator],
    *,
    has_content: bool = False,
    on_pair: Callable[[], None] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    cached_pairs_lookup: dict[tuple[str, str], dict] | None = None,
    sha256_lookup: dict[Path, str] | None = None,
) -> tuple[list[ScoredPair], set[tuple[Path, Path]], int]:
    """Score duration buckets in parallel using ProcessPoolExecutor."""
    import multiprocessing

    cache_arg = cached_pairs_lookup or {}

    chunk_count = min(workers, len(buckets))
    chunk_size = math.ceil(len(buckets) / chunk_count)
    chunks = [buckets[i : i + chunk_size] for i in range(0, len(buckets), chunk_size)]

    pairs: list[ScoredPair] = []
    seen_pairs: set[tuple[Path, Path]] = set()
    total_cached = 0
    reported = 0

    pair_counter: multiprocessing.Value = multiprocessing.Value("i", 0)  # type: ignore[assignment]
    with ProcessPoolExecutor(
        max_workers=chunk_count,
        initializer=_init_score_worker,
        initargs=(pair_counter,),
    ) as executor:
        futures = {
            executor.submit(
                _score_bucket_chunk_worker, (chunk, threshold, comparators, has_content, cache_arg, sha256_lookup)
            ): idx
            for idx, chunk in enumerate(chunks)
        }
        remaining = set(futures)
        while remaining:
            if wait_if_paused is not None:
                wait_if_paused()
            done, remaining = wait(remaining, timeout=0.1)
            for future in done:
                chunk_pairs, chunk_seen, chunk_cached = future.result()
                pairs.extend(chunk_pairs)
                seen_pairs.update(chunk_seen)
                total_cached += chunk_cached
            if on_pair:
                with pair_counter.get_lock():
                    current = pair_counter.value
                for _ in range(current - reported):
                    on_pair()
                reported = current

    return pairs, seen_pairs, total_cached


def _cache_lookup_key(a: VideoMetadata, b: VideoMetadata) -> tuple[str, str]:
    """Return a canonical (resolved, sorted) string pair for cache lookup."""
    ka = str(a.path.resolve())
    kb = str(b.path.resolve())
    if ka > kb:
        ka, kb = kb, ka
    return ka, kb


def _scored_pair_from_cache(
    a: VideoMetadata,
    b: VideoMetadata,
    entry: dict,
    *,
    threshold: float = 0.0,
) -> ScoredPair | None:
    """Reconstruct a ScoredPair from a cache entry dict.

    Returns None if the cached score is below *threshold*.
    """
    score = entry["score"]
    if score < threshold:
        return None
    detail_raw: dict[str, list] = entry["detail"]
    detail = {k: (v[0], v[1]) for k, v in detail_raw.items()}
    breakdown: dict[str, float | None] = {k: round(v[0] * v[1], 1) for k, v in detail.items()}
    return ScoredPair(
        file_a=a,
        file_b=b,
        total_score=round(score, 1),
        breakdown=breakdown,
        detail=detail,
    )


def _score_buckets_serial(
    buckets: list[list[VideoMetadata]],
    threshold: float,
    comparators: list[Comparator],
    *,
    has_content: bool = False,
    on_pair: Callable[[], None] | None = None,
    cached_pairs_lookup: dict[tuple[str, str], dict] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    sha256_lookup: dict[Path, str] | None = None,
) -> tuple[list[ScoredPair], set[tuple[Path, Path]], int]:
    """Score duration buckets on a single process."""
    pairs: list[ScoredPair] = []
    seen_pairs: set[tuple[Path, Path]] = set()
    cached_count = 0

    for bucket in buckets:
        for i, a in enumerate(bucket):
            for j in range(i + 1, len(bucket)):
                if wait_if_paused is not None:
                    wait_if_paused()
                b = bucket[j]
                key = _pair_key(a, b)
                seen_pairs.add(key)

                # Check scoring cache before computing
                if cached_pairs_lookup:
                    cache_key = _cache_lookup_key(a, b)
                    cached_entry = cached_pairs_lookup.get(cache_key)
                    if cached_entry is not None:
                        scored = _scored_pair_from_cache(a, b, cached_entry, threshold=threshold)
                        if scored is not None:
                            pairs.append(scored)
                        cached_count += 1
                        if on_pair:
                            on_pair()
                        continue

                scored = _score_pair(
                    a, b, comparators, threshold=threshold, has_content=has_content, sha256_lookup=sha256_lookup
                )
                if scored is not None:
                    pairs.append(scored)
                if on_pair:
                    on_pair()

    return pairs, seen_pairs, cached_count


def _filename_pass_parallel(
    items: list[VideoMetadata],
    normalized: list[str],
    bucketed_pairs: set[tuple[Path, Path]],
    threshold: float,
    workers: int,
    comparators: list[Comparator],
    name_threshold: float = 80.0,
    *,
    has_content: bool = False,
    on_item: Callable[[], None] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    cached_pairs_lookup: dict[tuple[str, str], dict] | None = None,
    sha256_lookup: dict[Path, str] | None = None,
) -> tuple[list[ScoredPair], set[tuple[Path, Path]], int]:
    """Run the filename cross-bucket pass in parallel.

    Returns (scored_pairs, evaluated_keys, cached_count).
    """
    cache_arg = cached_pairs_lookup or {}

    n = len(items)
    chunk_count = min(workers, n)
    chunk_size = math.ceil(n / chunk_count)

    work = [
        (
            start,
            min(start + chunk_size, n),
            items,
            normalized,
            bucketed_pairs,
            threshold,
            name_threshold,
            comparators,
            has_content,
            cache_arg,
            sha256_lookup,
        )
        for start in range(0, n, chunk_size)
    ]

    import multiprocessing

    pairs: list[ScoredPair] = []
    all_evaluated: set[tuple[Path, Path]] = set()
    total_cached = 0
    reported = 0

    pair_counter: multiprocessing.Value = multiprocessing.Value("i", 0)  # type: ignore[assignment]
    with ProcessPoolExecutor(
        max_workers=chunk_count,
        initializer=_init_score_worker,
        initargs=(pair_counter,),
    ) as executor:
        futures = {executor.submit(_filename_chunk_worker, w): w[1] - w[0] for w in work}
        remaining = set(futures)
        while remaining:
            if wait_if_paused is not None:
                wait_if_paused()
            done, remaining = wait(remaining, timeout=0.1)
            for future in done:
                chunk_pairs, chunk_keys, chunk_cached = future.result()
                pairs.extend(chunk_pairs)
                all_evaluated.update(chunk_keys)
                total_cached += chunk_cached
            if on_item:
                with pair_counter.get_lock():
                    current = pair_counter.value
                for _ in range(current - reported):
                    on_item()
                reported = current

    # Defensive dedup: guard against any cross-chunk overlap.
    seen: set[tuple[Path, Path]] = set()
    unique: list[ScoredPair] = []
    for sp in pairs:
        key = _pair_key(sp.file_a, sp.file_b)
        if key not in seen:
            seen.add(key)
            unique.append(sp)
    return unique, all_evaluated, total_cached


def _filename_pass_serial(
    items: list[VideoMetadata],
    normalized: list[str],
    bucketed_pairs: set[tuple[Path, Path]],
    comparators: list[Comparator],
    threshold: float,
    name_threshold: float = 80.0,
    *,
    has_content: bool = False,
    on_item: Callable[[], None] | None = None,
    cached_pairs_lookup: dict[tuple[str, str], dict] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    sha256_lookup: dict[Path, str] | None = None,
) -> tuple[list[ScoredPair], set[tuple[Path, Path]], int]:
    """Run the filename cross-bucket pass on a single process.

    Returns (scored_pairs, evaluated_keys, cached_count) where evaluated_keys
    contains the pair keys of all pairs evaluated (regardless of whether they
    passed threshold), and cached_count is how many came from the scoring cache.
    """
    extra_pairs: list[ScoredPair] = []
    evaluated_keys: set[tuple[Path, Path]] = set()
    cached_count = 0

    for i in range(len(items)):
        if wait_if_paused is not None:
            wait_if_paused()
        candidates = normalized[i + 1 :]
        if not candidates:
            if on_item:
                on_item()
            break

        matches = extract(
            normalized[i],
            candidates,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=name_threshold,
            limit=None,
        )

        for _, _score, idx in matches:
            if wait_if_paused is not None:
                wait_if_paused()
            j = i + 1 + idx
            a, b = items[i], items[j]

            key = _pair_key(a, b)
            if key in bucketed_pairs:
                continue

            evaluated_keys.add(key)

            # Check scoring cache before computing
            if cached_pairs_lookup:
                cache_key = _cache_lookup_key(a, b)
                cached_entry = cached_pairs_lookup.get(cache_key)
                if cached_entry is not None:
                    scored = _scored_pair_from_cache(a, b, cached_entry, threshold=threshold)
                    if scored is not None:
                        extra_pairs.append(scored)
                    cached_count += 1
                    continue

            scored = _score_pair(
                a, b, comparators, threshold=threshold, has_content=has_content, sha256_lookup=sha256_lookup
            )
            if scored is not None:
                extra_pairs.append(scored)

        if on_item:
            on_item()

    return extra_pairs, evaluated_keys, cached_count


def _content_chunk_worker(
    args: tuple[
        int,
        int,
        list[VideoMetadata],
        set[tuple[Path, Path]],
        list[Comparator],
        float,
        dict[tuple[str, str], dict],
        dict[Path, str] | None,
    ],
) -> tuple[list[ScoredPair], int, int]:
    """Score content-hash all-pairs for a slice of outer-loop indices.

    Returns (scored_pairs, evaluated_count, cached_count) where evaluated_count
    is the number of unseen pairs processed (scored or cache-hit, not skipped),
    and cached_count is how many came from the scoring cache.
    """
    start, end, hashed_items, seen_pairs, comparators, threshold, cached_pairs_lookup, sha256_lookup = args
    results: list[ScoredPair] = []
    evaluated = 0
    cached_count = 0
    n = len(hashed_items)
    for i in range(start, end):
        a = hashed_items[i]
        for j in range(i + 1, n):
            b = hashed_items[j]
            key = _pair_key(a, b)
            if key in seen_pairs:
                continue
            evaluated += 1

            # Check scoring cache before computing
            if cached_pairs_lookup:
                cache_key = _cache_lookup_key(a, b)
                cached_entry = cached_pairs_lookup.get(cache_key)
                if cached_entry is not None:
                    scored = _scored_pair_from_cache(a, b, cached_entry, threshold=threshold)
                    if scored is not None:
                        results.append(scored)
                    cached_count += 1
                    if _shared_pair_counter is not None:
                        with _shared_pair_counter.get_lock():
                            _shared_pair_counter.value += 1
                    continue

            scored = _score_pair(a, b, comparators, threshold=threshold, has_content=True, sha256_lookup=sha256_lookup)
            if scored is not None:
                results.append(scored)
            if _shared_pair_counter is not None:
                with _shared_pair_counter.get_lock():
                    _shared_pair_counter.value += 1
    return results, evaluated, cached_count


def _content_pass_serial(
    hashed_items: list[VideoMetadata],
    seen_pairs: set[tuple[Path, Path]],
    comparators: list[Comparator],
    threshold: float,
    *,
    on_pair: Callable[[], None] | None = None,
    cached_pairs_lookup: dict[tuple[str, str], dict] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    sha256_lookup: dict[Path, str] | None = None,
) -> tuple[list[ScoredPair], int]:
    """All-pairs comparison for files with content hashes.

    Only called in content mode.  Compares every unseen pair in
    *hashed_items* (the subset with non-None content_hash) so that
    renamed re-encodes with different durations are not missed by the
    duration-bucketing and filename passes.

    Returns (scored_pairs, cached_count).
    """
    if on_pair is None and not cached_pairs_lookup:
        results, _, cached = _content_chunk_worker(
            (0, len(hashed_items), hashed_items, seen_pairs, comparators, threshold, {}, sha256_lookup)
        )
        return results, cached
    # Inline the loop so we can fire on_pair per evaluated pair and check cache.
    results: list[ScoredPair] = []
    cached_count = 0
    n = len(hashed_items)
    for i in range(n):
        a = hashed_items[i]
        for j in range(i + 1, n):
            if wait_if_paused is not None:
                wait_if_paused()
            b = hashed_items[j]
            key = _pair_key(a, b)
            if key in seen_pairs:
                continue
            if on_pair:
                on_pair()

            # Check scoring cache before computing
            if cached_pairs_lookup:
                cache_key = _cache_lookup_key(a, b)
                cached_entry = cached_pairs_lookup.get(cache_key)
                if cached_entry is not None:
                    scored = _scored_pair_from_cache(a, b, cached_entry, threshold=threshold)
                    if scored is not None:
                        results.append(scored)
                    cached_count += 1
                    continue

            scored = _score_pair(a, b, comparators, threshold=threshold, has_content=True, sha256_lookup=sha256_lookup)
            if scored is not None:
                results.append(scored)
    return results, cached_count


def _content_pass_parallel(
    hashed_items: list[VideoMetadata],
    seen_pairs: set[tuple[Path, Path]],
    comparators: list[Comparator],
    threshold: float,
    workers: int,
    *,
    on_chunk: Callable[[int], None] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    cached_pairs_lookup: dict[tuple[str, str], dict] | None = None,
    sha256_lookup: dict[Path, str] | None = None,
) -> tuple[list[ScoredPair], int]:
    """All-pairs comparison for files with content hashes, parallelized.

    Returns (scored_pairs, cached_count).
    """
    import multiprocessing

    cache_arg = cached_pairs_lookup or {}

    n = len(hashed_items)
    chunk_count = min(workers, n)
    chunk_size = max(1, n // chunk_count)

    work = [
        (start, min(start + chunk_size, n), hashed_items, seen_pairs, comparators, threshold, cache_arg, sha256_lookup)
        for start in range(0, n, chunk_size)
    ]

    results: list[ScoredPair] = []
    total_cached = 0
    reported = 0

    pair_counter: multiprocessing.Value = multiprocessing.Value("i", 0)  # type: ignore[assignment]
    with ProcessPoolExecutor(
        max_workers=min(len(work), workers),
        initializer=_init_score_worker,
        initargs=(pair_counter,),
    ) as executor:
        futures = {executor.submit(_content_chunk_worker, w): idx for idx, w in enumerate(work)}
        remaining = set(futures)
        while remaining:
            if wait_if_paused is not None:
                wait_if_paused()
            done, remaining = wait(remaining, timeout=0.1)
            for future in done:
                chunk_results, _evaluated, chunk_cached = future.result()
                results.extend(chunk_results)
                total_cached += chunk_cached
            if on_chunk is not None:
                with pair_counter.get_lock():
                    current = pair_counter.value
                delta = current - reported
                if delta > 0:
                    on_chunk(delta)
                reported = current

    # Defensive dedup: guard against any cross-chunk overlap.
    seen: set[tuple[Path, Path]] = set()
    unique: list[ScoredPair] = []
    for sp in results:
        key = _pair_key(sp.file_a, sp.file_b)
        if key not in seen:
            seen.add(key)
            unique.append(sp)
    return unique, total_cached
