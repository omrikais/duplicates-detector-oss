"""Async pipeline stages for the duplicate-detection workflow.

Each stage is an async coroutine that reads from an input queue, processes
items, and writes results to an output queue.  A ``None`` sentinel on a
queue signals "no more items".

Stages respect a shared :class:`PipelineController` for pause/resume and
cooperative cancellation.

The :func:`run_pipeline` function wires scan -> extract -> filter -> hash ->
audio -> score into a single ``asyncio.TaskGroup``, returning scored pairs.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from duplicates_detector.config import Mode

if TYPE_CHECKING:
    from duplicates_detector.metadata import VideoMetadata
    from duplicates_detector.progress import ProgressEmitter
    from duplicates_detector.scorer import ScoredPair

# ---------------------------------------------------------------------------
# Canonical stage names — single source of truth
# ---------------------------------------------------------------------------

_CANONICAL_STAGES = ("scan", "extract", "filter", "content_hash", "audio_fingerprint", "score")


def _get_cache_stats(cache: Any) -> dict[str, int]:
    """Return cache hit/miss stats, or ``{}`` if *cache* is ``None``."""
    if cache is not None:
        return cache.stats()
    return {}


def _effective_workers(config: Any) -> int:
    """Resolve the worker count from *config*, falling back to CPU count."""
    return getattr(config, "workers", 0) or (os.cpu_count() or 4)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PipelineResult:
    """Result from :func:`run_pipeline` with real stats from each stage."""

    pairs: list[ScoredPair]
    files_scanned: int = 0
    files_after_filter: int = 0
    total_pairs_scored: int = 0
    pairs_found: int = 0
    scan_time: float = 0.0
    extract_time: float = 0.0
    filter_time: float = 0.0
    content_hash_time: float = 0.0
    audio_fingerprint_time: float = 0.0
    scoring_time: float = 0.0
    stage_timings: dict[str, float] = dataclasses.field(default_factory=dict)
    stage_counts: dict[str, int] = dataclasses.field(default_factory=dict)
    discovered_paths: set[Path] = dataclasses.field(default_factory=set)


@dataclasses.dataclass(frozen=True, slots=True)
class PipelineStageSnapshot:
    """Read-only snapshot of stage lifecycle state for pause checkpoints."""

    completed_stages: list[str]
    active_stage: str | None
    stage_timings: dict[str, float]


# ---------------------------------------------------------------------------
# TaskGroup polyfill for Python 3.10 compatibility
# ---------------------------------------------------------------------------

if sys.version_info >= (3, 11):
    _TaskGroup = asyncio.TaskGroup
else:

    class _TaskGroup:
        """Minimal ``asyncio.TaskGroup`` polyfill for Python 3.10.

        Uses ``asyncio.gather()`` under the hood.  On error the first
        exception is re-raised (no ``ExceptionGroup`` wrapping, which is
        unavailable on 3.10).
        """

        def __init__(self) -> None:
            self._tasks: list[asyncio.Task[Any]] = []

        def create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
            task = asyncio.ensure_future(coro)
            self._tasks.append(task)
            return task

        async def __aenter__(self) -> _TaskGroup:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: Any,
        ) -> None:
            if exc_val is not None:
                # Context body raised -- cancel all tasks and suppress their
                # CancelledError so the original exception propagates.
                for t in self._tasks:
                    t.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
                return

            if not self._tasks:
                return

            try:
                await asyncio.gather(*self._tasks)
            except BaseException:
                # One task failed -- cancel the rest, await them, re-raise.
                for t in self._tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
                # Re-raise the first real (non-cancellation) error.
                for t in self._tasks:
                    if t.done() and not t.cancelled():
                        exc = t.exception()
                        if exc is not None:
                            raise exc
                raise  # fallback: re-raise the original


# ---------------------------------------------------------------------------
# Helper: async queue iterator
# ---------------------------------------------------------------------------


async def queue_iter(q: asyncio.Queue[Any]) -> AsyncIterator[Any]:
    """Yield items from *q* until a ``None`` sentinel is received."""
    while True:
        item = await q.get()
        if item is None:
            break
        yield item


# ---------------------------------------------------------------------------
# Pipeline controller
# ---------------------------------------------------------------------------


class PipelineController:
    """Coordinate pause/resume/cancel across all pipeline stages.

    Internally uses a :class:`_SharedControl` object for pause/cancel state
    and callbacks.  Stage tracking (``enter_stage``/``complete_stage``) is
    per-instance, enabling concurrent sub-pipelines (via :meth:`linked`) to
    share pause/cancel signals while maintaining independent stage state.

    Uses a single ``threading.Event`` for all pause/resume coordination.
    This is thread-safe and signal-handler-safe, allowing ``pause()``
    and ``resume()`` to be called from any context (signal handlers,
    background threads, async coroutines).

    * **Event SET** -> pipeline runs freely.
    * **Event CLEARED** -> ``wait_if_paused()`` blocks the caller.
    * **Cancel** -> sets a flag *and* sets the event (unblocks paused waiters).
    """

    class _SharedControl:
        """Shared pause/cancel/callback state for one or more linked controllers."""

        __slots__ = ("thread_event", "cancelled", "on_pause", "on_resume")

        def __init__(self) -> None:
            self.thread_event = threading.Event()
            self.thread_event.set()  # start running
            self.cancelled = False
            self.on_pause: Callable[[], None] | None = None
            self.on_resume: Callable[[], None] | None = None

    def __init__(self, *, _shared: _SharedControl | None = None) -> None:
        self._shared = _shared or self._SharedControl()
        self._lock = threading.Lock()
        self._completed_stages: list[str] = []
        self._active_stage: str | None = None
        self._stage_starts: dict[str, float] = {}
        self._stage_timings: dict[str, float] = {}
        self.files_discovered: int = 0

    # -- Linked controller -------------------------------------------------

    def linked(self) -> PipelineController:
        """Create a controller sharing pause/cancel state but with independent stage tracking.

        Used for concurrent sub-pipelines (auto mode) where both must respond
        to the same pause/cancel signals but track their own stage progress.
        """
        return PipelineController(_shared=self._shared)

    # -- Pause / Resume ---------------------------------------------------

    def pause(self) -> None:
        """Pause the pipeline.  Stages will block on ``wait_if_paused()``."""
        if not self._shared.cancelled:
            self._shared.thread_event.clear()
            if self._shared.on_pause is not None:
                self._shared.on_pause()

    def resume(self) -> None:
        """Resume the pipeline.  Unblocks all stages waiting in ``wait_if_paused()``."""
        self._shared.thread_event.set()
        if self._shared.on_resume is not None and not self._shared.cancelled:
            self._shared.on_resume()

    # -- Cancel ------------------------------------------------------------

    def cancel(self) -> None:
        """Cancel the pipeline.  Also unblocks any paused stages."""
        self._shared.cancelled = True
        self._shared.thread_event.set()  # unblock anyone waiting

    # -- Properties --------------------------------------------------------

    @property
    def is_paused(self) -> bool:
        """``True`` when the pipeline is paused (and not cancelled)."""
        return not self._shared.thread_event.is_set() and not self._shared.cancelled

    @property
    def is_cancelled(self) -> bool:
        """``True`` when cancel has been called."""
        return self._shared.cancelled

    # -- on_pause / on_resume properties -----------------------------------

    @property
    def on_pause(self) -> Callable[[], None] | None:
        return self._shared.on_pause

    @on_pause.setter
    def on_pause(self, value: Callable[[], None] | None) -> None:
        self._shared.on_pause = value

    @property
    def on_resume(self) -> Callable[[], None] | None:
        return self._shared.on_resume

    @on_resume.setter
    def on_resume(self, value: Callable[[], None] | None) -> None:
        self._shared.on_resume = value

    # -- Stage tracking (per-instance, not shared) -------------------------

    def enter_stage(self, name: str) -> None:
        """Record that stage *name* is now active."""
        with self._lock:
            self._active_stage = name
            self._stage_starts[name] = time.monotonic()

    def complete_stage(self, name: str) -> None:
        """Record that stage *name* has finished."""
        with self._lock:
            start = self._stage_starts.pop(name, None)
            if start is not None:
                self._stage_timings[name] = max(0.0, time.monotonic() - start)
            if name not in self._completed_stages:
                self._completed_stages.append(name)
            if self._active_stage == name:
                self._active_stage = None

    @property
    def completed_stages(self) -> list[str]:
        """Return a copy of the completed stage names."""
        with self._lock:
            return list(self._completed_stages)

    @property
    def active_stage(self) -> str | None:
        """Return the currently active stage name, or ``None``."""
        with self._lock:
            return self._active_stage

    def stage_snapshot(self) -> PipelineStageSnapshot:
        """Return completed stage/timing state for pause checkpoints.

        Only fully completed stages are included in ``stage_timings``.
        The active stage is intentionally excluded until completion.
        """
        with self._lock:
            return PipelineStageSnapshot(
                completed_stages=list(self._completed_stages),
                active_stage=self._active_stage,
                stage_timings=dict(self._stage_timings),
            )

    # -- Pause-file watcher ------------------------------------------------

    async def watch_pause_file(self, path: Path) -> None:
        """Poll a control file at 500ms intervals.

        When file content is ``"pause"``, calls :meth:`pause`.
        When file content is ``"resume"``, calls :meth:`resume`.
        Stops when controller is cancelled.
        """
        while not self.is_cancelled:
            try:
                content = path.read_text().strip().lower()
                if content == "pause" and not self.is_paused:
                    self.pause()
                elif content == "resume" and self.is_paused:
                    self.resume()
            except (OSError, ValueError):
                pass  # File missing or unreadable — skip
            await asyncio.sleep(0.5)

    # -- Wait helper -------------------------------------------------------

    async def wait_if_paused(self) -> None:
        """Block until the pipeline is resumed (or cancelled).

        Polls the thread-safe ``threading.Event`` rather than awaiting
        an ``asyncio.Event`` so that ``pause()``/``resume()`` can be
        called safely from signal handlers and background threads
        (e.g., the pause-file watcher).
        """
        if self._shared.thread_event.is_set():
            return  # fast path: not paused
        while not self._shared.thread_event.is_set() and not self._shared.cancelled:
            await asyncio.sleep(0.05)

    def wait_if_paused_blocking(self) -> None:
        """Thread-safe pause wait for executor-driven scoring work."""
        self._shared.thread_event.wait()


# ---------------------------------------------------------------------------
# Stage 1: Scan (streaming via _scan_files_iter)
# ---------------------------------------------------------------------------


async def scan_stage(
    config: Any,
    out_q: asyncio.Queue[Path | None],
    progress: ProgressEmitter | None,
    controller: PipelineController,
    *,
    _stats: dict[str, Any] | None = None,
) -> None:
    """Discover files on disk and stream them into *out_q*.

    Uses :func:`scanner._scan_files_iter` (generator) bridged to the async
    event loop via a thread so items flow one-at-a-time rather than
    materializing the full file list first.

    Emits progress events via *progress* (if provided).
    Puts a ``None`` sentinel at the end to signal downstream stages.
    """
    from duplicates_detector.scanner import _scan_files_iter

    controller.enter_stage("scan")
    if progress is not None:
        progress.stage_start("scan")
    scan_start = time.monotonic()
    count = 0
    paths_seen: set[Path] = set()

    # Bridge sync generator -> async queue via a background thread.
    bridge_q: asyncio.Queue[Path | None] = asyncio.Queue(maxsize=200)
    loop = asyncio.get_running_loop()

    class _ScanCancelled(Exception):
        """Internal sentinel exception used to stop scanner iteration cleanly."""

    def _pause_waiter() -> None:
        controller.wait_if_paused_blocking()
        if controller.is_cancelled:
            raise _ScanCancelled

    def _scan_thread() -> None:
        try:
            for path in _scan_files_iter(
                config.directories,
                recursive=config.recursive,
                extensions=config.extensions,
                exclude=config.exclude,
                pause_waiter=_pause_waiter,
            ):
                if controller.is_cancelled:
                    break
                asyncio.run_coroutine_threadsafe(bridge_q.put(path), loop).result()
        except _ScanCancelled:
            pass
        finally:
            # Always send sentinel so queue_iter unblocks even on error.
            # The actual exception propagates via scan_future.
            asyncio.run_coroutine_threadsafe(bridge_q.put(None), loop).result()

    scan_future = loop.run_in_executor(None, _scan_thread)

    async for path in queue_iter(bridge_q):
        await controller.wait_if_paused()
        if controller.is_cancelled:
            break
        await out_q.put(path)
        paths_seen.add(path)
        count += 1
        controller.files_discovered = count
        if progress is not None:
            progress.progress("scan", current=count)

    await scan_future  # ensure thread completes

    if progress is not None:
        progress.progress("scan", current=count, total=count, force=True)
        progress.stage_end("scan", total=count, elapsed=time.monotonic() - scan_start)

    if _stats is not None:
        _stats["scan_count"] = count
        _stats["scan_time"] = time.monotonic() - scan_start
        _stats["discovered_paths"] = paths_seen

    controller.complete_stage("scan")
    await out_q.put(None)  # sentinel


async def seeded_scan_stage(
    paths: list[Path],
    out_q: asyncio.Queue[Path | None],
    controller: PipelineController,
    *,
    _stats: dict[str, Any] | None = None,
) -> None:
    """Feed an already-discovered path list into the pipeline.

    The CLI performs an outer discovery pass so it can surface live progress
    and support pause/resume before the async pipeline starts. When those
    paths are already known, seed the downstream queues directly instead of
    rescanning the filesystem here.
    """
    count = 0
    for path in paths:
        await controller.wait_if_paused()
        if controller.is_cancelled:
            break
        await out_q.put(path)
        count += 1

    if _stats is not None:
        _stats["scan_count"] = count
        _stats["discovered_paths"] = set(paths)

    await out_q.put(None)


# ---------------------------------------------------------------------------
# Stage 2: Extract metadata (concurrent fan-out)
# ---------------------------------------------------------------------------


async def extract_stage(
    in_q: asyncio.Queue[Path | None],
    out_q: asyncio.Queue[VideoMetadata | None],
    cache: Any,
    config: Any,
    progress: ProgressEmitter | None,
    controller: PipelineController,
    *,
    reference_dirs: list[Path] | None = None,
    expected_total: int | None = None,
    _stats: dict[str, Any] | None = None,
) -> None:
    """Read paths from *in_q*, extract metadata concurrently, write to *out_q*.

    Uses :func:`metadata._extract_one_with_cache` with a bounded
    ``ThreadPoolExecutor`` and ``asyncio.wait(FIRST_COMPLETED)`` fan-out
    to process multiple files in parallel.

    When *reference_dirs* is provided, tags metadata with
    ``is_reference=True`` for files inside any reference directory.

    When *expected_total* is provided (from the outer scan count), it is
    used as the ``total`` in progress events from the start so the GUI
    can show accurate percentages instead of the growing queue-pull count.
    """
    from dataclasses import replace

    from duplicates_detector.metadata import _extract_one_with_cache

    controller.enter_stage("extract")
    if progress is not None:
        progress.stage_start("extract", total=expected_total)
    extract_start = time.monotonic()

    raw_workers = _effective_workers(config)
    # Metadata extraction is I/O-bound (stat + read), not CPU-bound.
    # Scale workers above CPU count to keep the disk busy.
    max_concurrent = min(raw_workers * 8, 128)
    mode = getattr(config, "mode", Mode.VIDEO)
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=max_concurrent)
    count = 0
    items_received = 0
    pending: set[asyncio.Future[VideoMetadata | None]] = set()

    def _best_total() -> int:
        """Return the best available total for progress reporting."""
        if expected_total is not None:
            return expected_total
        return items_received

    def _tag_reference(meta: VideoMetadata) -> VideoMetadata:
        """Tag metadata as reference if path is inside any reference dir."""
        if reference_dirs:
            resolved = meta.path.resolve()
            if any(resolved.is_relative_to(ref) or meta.path.is_relative_to(ref) for ref in reference_dirs):
                return replace(meta, is_reference=True)
        return meta

    # Sidecar discovery config (resolved once)
    _do_sidecars = not getattr(config, "no_sidecars", False)
    _sidecar_exts_raw = getattr(config, "sidecar_extensions", None)
    _sidecar_exts: frozenset[str] | None = None
    if _sidecar_exts_raw:
        from duplicates_detector.sidecar import parse_sidecar_extensions

        _sidecar_exts = parse_sidecar_extensions(_sidecar_exts_raw)

    def _attach_sidecars(meta: VideoMetadata) -> VideoMetadata:
        """Discover and attach sidecar files to metadata.

        Sets ``sidecars`` to an empty tuple when disabled or when no sidecars
        are found, so that ``None`` unambiguously means "unknown" (e.g. replay).
        """
        import dataclasses as _dc

        if not _dc.is_dataclass(meta) or isinstance(meta, type):
            return meta  # non-dataclass (e.g. test mock) — pass through
        if not _do_sidecars:
            return replace(meta, sidecars=())
        from duplicates_detector.sidecar import find_sidecars

        kwargs: dict[str, object] = {}
        if _sidecar_exts is not None:
            kwargs["extensions"] = _sidecar_exts
        found = find_sidecars(meta.path, **kwargs)  # type: ignore[arg-type]
        return replace(meta, sidecars=tuple(found))

    # Defer individual cache writes — batch them for throughput.
    _use_deferred = cache is not None and hasattr(cache, "put_metadata_batch")

    def _extract_and_enrich(path: Path) -> VideoMetadata | None:
        """Extract metadata, tag references, and discover sidecars in one executor call."""
        meta = _extract_one_with_cache(path, cache, mode, defer_cache_write=_use_deferred)
        if meta is None:
            return None
        meta = _tag_reference(meta)
        meta = _attach_sidecars(meta)
        return meta

    # Pending cache writes: (path, data_dict, file_size, mtime)
    _cache_pending: list[tuple[Path, dict, int, float]] = []

    def _count_and_collect(done_set: set[asyncio.Future[VideoMetadata | None]]) -> tuple[int, list[VideoMetadata]]:
        """Count completed futures and collect successful results.

        Returns ``(total_processed, results_to_enqueue)`` without touching
        the output queue — so the caller can emit progress *before* the
        potentially-blocking ``out_q.put()`` calls.

        When deferred caching is active, accumulates cache-miss results and
        flushes them in batches to avoid per-file write-lock contention.
        """
        from duplicates_detector.metadata import _metadata_to_cache_dict

        n = 0
        results: list[VideoMetadata] = []
        for f in done_set:
            n += 1
            if f.exception() is not None:
                continue
            meta = f.result()
            if meta is not None:
                # Queue deferred cache writes for cache-miss results
                if _use_deferred and meta.mtime is not None:
                    _cache_pending.append((meta.path, _metadata_to_cache_dict(meta), meta.file_size, meta.mtime))
                results.append(meta)
        # Flush cache batch when large enough
        if _use_deferred and len(_cache_pending) >= 100:
            cache.put_metadata_batch(_cache_pending[:])
            _cache_pending.clear()
        return n, results

    def _emit_progress() -> None:
        if progress is not None:
            stats = _get_cache_stats(cache)
            progress.progress(
                "extract",
                current=count,
                total=_best_total(),
                cache_hits=stats.get("metadata_hits"),
                cache_misses=stats.get("metadata_misses"),
            )

    async for path in queue_iter(in_q):
        await controller.wait_if_paused()
        if controller.is_cancelled:
            break
        items_received += 1
        fut = asyncio.ensure_future(loop.run_in_executor(executor, _extract_and_enrich, path))
        pending.add(fut)
        # Non-blocking harvest of completed futures — ensures intermediate
        # progress events fire even when pending < max_concurrent.
        newly_done = {f for f in pending if f.done()}
        if newly_done:
            pending -= newly_done
            batch_n, batch_results = _count_and_collect(newly_done)
            count += batch_n
            # Emit progress BEFORE blocking on out_q.put() so that the
            # GUI sees forward movement even under queue back-pressure.
            _emit_progress()
            for meta in batch_results:
                await out_q.put(meta)
        if len(pending) >= max_concurrent:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            batch_n, batch_results = _count_and_collect(done)
            count += batch_n
            _emit_progress()
            for meta in batch_results:
                await out_q.put(meta)

    # After sentinel: items_received is the definitive total.
    if pending:
        done, _ = await asyncio.wait(pending)
        batch_n, batch_results = _count_and_collect(done)
        count += batch_n
        if progress is not None:
            stats = _get_cache_stats(cache)
            progress.progress(
                "extract",
                current=count,
                total=expected_total or items_received,
                cache_hits=stats.get("metadata_hits"),
                cache_misses=stats.get("metadata_misses"),
            )
        for meta in batch_results:
            await out_q.put(meta)

    if progress is not None:
        stats = _get_cache_stats(cache)
        progress.progress(
            "extract",
            current=count,
            force=True,
            cache_hits=stats.get("metadata_hits"),
            cache_misses=stats.get("metadata_misses"),
        )
        progress.stage_end(
            "extract",
            total=count,
            elapsed=time.monotonic() - extract_start,
            cache_hits=stats.get("metadata_hits", 0),
            cache_misses=stats.get("metadata_misses", 0),
        )

    executor.shutdown(wait=False)
    # Flush remaining deferred cache writes
    if _use_deferred and _cache_pending:
        cache.put_metadata_batch(_cache_pending[:])
        _cache_pending.clear()
    if _stats is not None:
        _stats["extract_count"] = count
        _stats["extract_time"] = time.monotonic() - extract_start

    controller.complete_stage("extract")
    await out_q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# Stage 3: Filter metadata
# ---------------------------------------------------------------------------


async def filter_stage(
    in_q: asyncio.Queue[VideoMetadata | None],
    out_q: asyncio.Queue[VideoMetadata | None],
    config: Any,
    progress: ProgressEmitter | None,
    controller: PipelineController,
    *,
    _stats: dict[str, Any] | None = None,
) -> None:
    """Read metadata from *in_q*, apply filters, write survivors to *out_q*.

    Delegates to :func:`filters.filter_metadata` for individual items.
    Puts a ``None`` sentinel at the end.
    """
    from duplicates_detector.filters import filter_metadata

    controller.enter_stage("filter")
    if progress is not None:
        progress.stage_start("filter")
    filter_start = time.monotonic()

    count = 0
    passed = 0

    async for meta in queue_iter(in_q):
        await controller.wait_if_paused()
        if controller.is_cancelled:
            break

        # filter_metadata works on a list; wrap the single item.
        surviving = filter_metadata(
            [meta],
            min_size=config.min_size,
            max_size=config.max_size,
            min_duration=config.min_duration,
            max_duration=config.max_duration,
            min_resolution=config.min_resolution,
            max_resolution=config.max_resolution,
            min_bitrate=config.min_bitrate,
            max_bitrate=config.max_bitrate,
            codecs=getattr(config, "codecs", None),
        )
        if surviving:
            await out_q.put(surviving[0])
            passed += 1
        count += 1

    if progress is not None:
        progress.stage_end("filter", total=passed, elapsed=time.monotonic() - filter_start)

    if _stats is not None:
        _stats["filter_count"] = passed
        _stats["filter_time"] = time.monotonic() - filter_start

    controller.complete_stage("filter")
    await out_q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# Stage 4: Content hashing (concurrent fan-out)
# ---------------------------------------------------------------------------


async def hash_stage(
    in_q: asyncio.Queue[VideoMetadata | None],
    out_q: asyncio.Queue[VideoMetadata | None],
    cache: Any,
    config: Any,
    progress: ProgressEmitter | None,
    controller: PipelineController,
    *,
    expected_total: int | None = None,
    _stats: dict[str, Any] | None = None,
) -> None:
    """Read metadata from *in_q*, compute content hashes, write to *out_q*.

    Uses :func:`content._hash_one_with_cache` with concurrent fan-out
    when ``config.content`` is truthy.  Passes items through unchanged
    when content hashing is not requested.
    """
    from duplicates_detector.content import _hash_one_with_cache, _pre_hash_one_with_cache
    from duplicates_detector.metadata import _extract_text_only

    count = 0
    do_hash = getattr(config, "content", False)
    is_document = getattr(config, "mode", Mode.VIDEO) == Mode.DOCUMENT
    content_method = getattr(config, "content_method", "phash")

    # TF-IDF is pairwise at score time (like SSIM) — no per-file hashing.
    # Items pass through the stage without content hashing, but text_content
    # must be rehydrated for cache-hit documents (text is transient, not cached).
    needs_text_rehydration = do_hash and is_document and content_method == "tfidf"
    if needs_text_rehydration:
        do_hash = False

    stage_visible = _stage_is_visible(config, "content_hash")
    hash_start = time.monotonic() if stage_visible else 0.0
    loop = asyncio.get_running_loop()

    if stage_visible:
        controller.enter_stage("content_hash")
        if progress is not None:
            progress.stage_start("content_hash", total=expected_total)

    if do_hash:
        workers = _effective_workers(config)
        max_concurrent = min(workers, 128)
        executor = ThreadPoolExecutor(max_workers=max_concurrent)
        items_received = 0

        rotation_invariant = getattr(config, "rotation_invariant", False)
        is_image = getattr(config, "mode", Mode.VIDEO) == Mode.IMAGE

        # SSIM uses a separate pairwise code path — skip pre-hash entirely.
        # CLIP is cached like PDQ so it benefits from pre-hash short-circuit.
        # Also respect explicit --no-pre-hash flag.
        skip_pre_hash = content_method == "ssim" or config.no_pre_hash

        if content_method == "clip":
            from duplicates_detector.clip import _clip_one_with_cache

            # Suppress Rich download output when machine-progress is active
            # (stderr must stay JSONL-clean). Require successful init since
            # the user explicitly requested CLIP.
            _clip_quiet = progress is not None

            def _hash_one(m: VideoMetadata) -> VideoMetadata:
                return _clip_one_with_cache(
                    m,
                    cache,
                    is_image=is_image,
                    quiet=_clip_quiet,
                    required=True,
                )
        else:

            def _hash_one(m: VideoMetadata) -> VideoMetadata:
                return _hash_one_with_cache(
                    m,
                    cache,
                    rotation_invariant=rotation_invariant,
                    is_image=is_image,
                    is_document=is_document,
                )

        # --- Pass 1: Collect items and compute pre-hashes ---
        all_items: list[VideoMetadata] = []
        async for meta in queue_iter(in_q):
            await controller.wait_if_paused()
            if controller.is_cancelled:
                break
            items_received += 1
            if not skip_pre_hash:
                meta = await loop.run_in_executor(executor, _pre_hash_one_with_cache, meta, cache)
            all_items.append(meta)

        # Pre-hashes feed the scorer's byte-identical fast path (SHA-256
        # verified); all items still need real PDQ/CLIP hashes for content
        # comparison — synthetic content hashes would cause false positives
        # when files share the first 4KB but differ afterwards.
        pdq_items = all_items

        # --- PDQ fan-out for singletons ---
        pending: set[asyncio.Future[VideoMetadata]] = set()
        for item in pdq_items:
            await controller.wait_if_paused()
            if controller.is_cancelled:
                break
            fut = asyncio.ensure_future(loop.run_in_executor(executor, _hash_one, item))
            pending.add(fut)
            # Non-blocking harvest of completed futures
            newly_done = {f for f in pending if f.done()}
            if newly_done:
                pending -= newly_done
                for f in newly_done:
                    await out_q.put(f.result())
                    count += 1
                if stage_visible and progress is not None:
                    stats = _get_cache_stats(cache)
                    progress.progress(
                        "content_hash",
                        current=count,
                        total=items_received,
                        cache_hits=stats.get("content_hits"),
                        cache_misses=stats.get("content_misses"),
                    )
            if len(pending) >= max_concurrent:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for f in done:
                    await out_q.put(f.result())
                    count += 1
                if stage_visible and progress is not None:
                    stats = _get_cache_stats(cache)
                    progress.progress(
                        "content_hash",
                        current=count,
                        total=items_received,
                        cache_hits=stats.get("content_hits"),
                        cache_misses=stats.get("content_misses"),
                    )

        # Drain remaining futures
        if pending:
            done, _ = await asyncio.wait(pending)
            for f in done:
                await out_q.put(f.result())
                count += 1
            if stage_visible and progress is not None:
                stats = _get_cache_stats(cache)
                progress.progress(
                    "content_hash",
                    current=count,
                    total=items_received,
                    cache_hits=stats.get("content_hits"),
                    cache_misses=stats.get("content_misses"),
                )

        executor.shutdown(wait=False)
    else:
        # Pass-through: no hashing requested, but compute pre-hashes
        # for byte-identical detection unless explicitly disabled.
        compute_pre_hash = not config.no_pre_hash
        if compute_pre_hash:
            workers_count = _effective_workers(config)
            pre_hash_executor = ThreadPoolExecutor(max_workers=min(workers_count, 128))
        else:
            pre_hash_executor = None

        async for meta in queue_iter(in_q):
            await controller.wait_if_paused()
            if controller.is_cancelled:
                break
            if compute_pre_hash and pre_hash_executor is not None:
                meta = await loop.run_in_executor(pre_hash_executor, _pre_hash_one_with_cache, meta, cache)
            if needs_text_rehydration and meta.text_content is None:
                text = await loop.run_in_executor(None, _extract_text_only, meta.path)
                if text is not None:
                    meta = dataclasses.replace(meta, text_content=text)
            await out_q.put(meta)
            count += 1
            if stage_visible and progress is not None:
                progress.progress("content_hash", current=count)
        if pre_hash_executor is not None:
            pre_hash_executor.shutdown(wait=False)

    if stage_visible and progress is not None:
        stats = _get_cache_stats(cache)
        progress.progress(
            "content_hash",
            current=count,
            total=count,
            force=True,
            cache_hits=stats.get("content_hits"),
            cache_misses=stats.get("content_misses"),
        )
        progress.stage_end(
            "content_hash",
            total=count,
            elapsed=time.monotonic() - hash_start,
            cache_hits=stats.get("content_hits", 0),
            cache_misses=stats.get("content_misses", 0),
            hashed=count,
        )

    if cache is not None and hasattr(cache, "flush"):
        cache.flush()

    if stage_visible and _stats is not None:
        _stats["content_hash_count"] = count
        _stats["content_hash_time"] = time.monotonic() - hash_start

    if stage_visible:
        controller.complete_stage("content_hash")
    await out_q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# Stage 5: Audio fingerprinting (concurrent fan-out)
# ---------------------------------------------------------------------------


async def audio_stage(
    in_q: asyncio.Queue[VideoMetadata | None],
    out_q: asyncio.Queue[VideoMetadata | None],
    cache: Any,
    config: Any,
    progress: ProgressEmitter | None,
    controller: PipelineController,
    *,
    expected_total: int | None = None,
    _stats: dict[str, Any] | None = None,
) -> None:
    """Read metadata from *in_q*, compute audio fingerprints, write to *out_q*.

    Uses :func:`audio._fingerprint_one_with_cache` with concurrent fan-out
    when ``config.audio`` is truthy.  Passes items through unchanged when
    audio fingerprinting is not requested.

    Emits ``audio_fingerprint`` stage events.
    """
    do_audio = getattr(config, "audio", False)
    count = 0
    stage_visible = _stage_is_visible(config, "audio_fingerprint")
    audio_start = time.monotonic() if stage_visible else 0.0

    if stage_visible:
        controller.enter_stage("audio_fingerprint")
        if progress is not None:
            progress.stage_start("audio_fingerprint", total=expected_total)

    def _best_audio_total() -> int | None:
        if expected_total is not None:
            return expected_total
        return items_received if items_received > 0 else None

    if do_audio:
        from duplicates_detector.audio import _fingerprint_one_with_cache

        workers = _effective_workers(config)
        max_concurrent = min(workers, 128)
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=max_concurrent)
        pending: set[asyncio.Future[VideoMetadata]] = set()
        items_received = 0

        async for meta in queue_iter(in_q):
            await controller.wait_if_paused()
            if controller.is_cancelled:
                break
            items_received += 1
            fut = asyncio.ensure_future(loop.run_in_executor(executor, _fingerprint_one_with_cache, meta, cache))
            pending.add(fut)
            # Non-blocking harvest of completed futures
            newly_done = {f for f in pending if f.done()}
            if newly_done:
                pending -= newly_done
                for f in newly_done:
                    await out_q.put(f.result())
                    count += 1
                if stage_visible and progress is not None:
                    stats = _get_cache_stats(cache)
                    progress.progress(
                        "audio_fingerprint",
                        current=count,
                        total=_best_audio_total(),
                        cache_hits=stats.get("audio_hits"),
                        cache_misses=stats.get("audio_misses"),
                    )
            if len(pending) >= max_concurrent:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for f in done:
                    await out_q.put(f.result())
                    count += 1
                if stage_visible and progress is not None:
                    stats = _get_cache_stats(cache)
                    progress.progress(
                        "audio_fingerprint",
                        current=count,
                        total=_best_audio_total(),
                        cache_hits=stats.get("audio_hits"),
                        cache_misses=stats.get("audio_misses"),
                    )

        # After sentinel: items_received is the definitive total.
        if pending:
            done, _ = await asyncio.wait(pending)
            for f in done:
                await out_q.put(f.result())
                count += 1
            if stage_visible and progress is not None:
                stats = _get_cache_stats(cache)
                progress.progress(
                    "audio_fingerprint",
                    current=count,
                    total=_best_audio_total(),
                    cache_hits=stats.get("audio_hits"),
                    cache_misses=stats.get("audio_misses"),
                )

        executor.shutdown(wait=False)
    else:
        # Pass-through: no audio fingerprinting requested
        async for meta in queue_iter(in_q):
            await controller.wait_if_paused()
            if controller.is_cancelled:
                break
            await out_q.put(meta)
            count += 1
            if stage_visible and progress is not None:
                progress.progress("audio_fingerprint", current=count)

    if stage_visible and progress is not None:
        stats = _get_cache_stats(cache)
        progress.progress(
            "audio_fingerprint",
            current=count,
            total=count,
            force=True,
            cache_hits=stats.get("audio_hits"),
            cache_misses=stats.get("audio_misses"),
        )
        progress.stage_end(
            "audio_fingerprint",
            total=count,
            elapsed=time.monotonic() - audio_start,
            cache_hits=stats.get("audio_hits", 0),
            cache_misses=stats.get("audio_misses", 0),
            fingerprinted=count,
        )

    if cache is not None and hasattr(cache, "flush"):
        cache.flush()

    if stage_visible and _stats is not None:
        _stats["audio_fingerprint_count"] = count
        _stats["audio_fingerprint_time"] = time.monotonic() - audio_start

    if stage_visible:
        controller.complete_stage("audio_fingerprint")
    await out_q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# Stage 6: Score (queue-based accumulate then score)
# ---------------------------------------------------------------------------


async def score_stage(
    in_q: asyncio.Queue[VideoMetadata | None],
    cache: Any | None,
    config: Any,
    progress: ProgressEmitter | None,
    controller: PipelineController,
    *,
    config_hash: str | None = None,
    _stats: dict[str, Any] | None = None,
) -> list[ScoredPair]:
    """Accumulate metadata from *in_q*, then score all pairs.

    Scoring needs the full metadata list (for O(n^2) pair comparison).
    Delegates to :func:`scorer.find_duplicates` which handles bucketing,
    parallelism, the multi-pass scoring pipeline, and bulk cache writes.

    Returns a list of :class:`~duplicates_detector.scorer.ScoredPair`.
    """
    controller.enter_stage("score")
    if progress is not None:
        progress.stage_start("score")
    score_start = time.monotonic()

    # Accumulate all metadata from the upstream queue
    metadata_list: list[VideoMetadata] = []
    async for meta in queue_iter(in_q):
        await controller.wait_if_paused()
        if controller.is_cancelled:
            break
        metadata_list.append(meta)

    if len(metadata_list) < 2:
        if progress is not None:
            progress.stage_end("score", total=0, elapsed=time.monotonic() - score_start, cache_hits=0, cache_misses=0)
        controller.complete_stage("score")
        return []

    from duplicates_detector.scorer import find_duplicates

    comparators = getattr(config, "comparators", None)
    workers = getattr(config, "workers", 0)
    mode = getattr(config, "mode", Mode.VIDEO)
    threshold = getattr(config, "threshold", 50.0)
    content_method = getattr(config, "content_method", None)

    # Collect actual scoring stats (total comparisons evaluated)
    scoring_stats: dict[str, int] = {}

    # Run scoring in the default executor to avoid blocking the event loop.
    loop = asyncio.get_running_loop()
    scored = await loop.run_in_executor(
        None,
        lambda: find_duplicates(
            metadata_list,
            workers=workers,
            comparators=comparators,
            quiet=True,  # suppress Rich output in async context
            mode=mode,
            progress_emitter=progress,
            _emit_score_stage=False,  # we emit our own stage lifecycle
            cache_db=cache,
            config_hash=config_hash,
            content_method=content_method,
            pause_waiter=controller.wait_if_paused_blocking,
            threshold=threshold,
            stats=scoring_stats,
        ),
    )

    elapsed = time.monotonic() - score_start
    total_evaluated = scoring_stats.get("total_pairs_scored", len(scored))
    if progress is not None:
        _cstats = _get_cache_stats(cache)
        progress.stage_end(
            "score",
            total=total_evaluated,
            elapsed=elapsed,
            pairs_found=len(scored),
            cache_hits=_cstats.get("score_hits", 0),
            cache_misses=_cstats.get("score_misses", 0),
        )

    if _stats is not None:
        _stats["score_count"] = total_evaluated
        _stats["score_time"] = elapsed
        _stats["pairs_found"] = len(scored)

    controller.complete_stage("score")
    return scored


# ---------------------------------------------------------------------------
# Config dataclasses for stage adapters
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ScanConfig:
    """Configuration consumed by :func:`scan_stage`."""

    directories: list[Path]
    recursive: bool
    extensions: frozenset[str]
    exclude: list[str] | None


@dataclasses.dataclass(frozen=True, slots=True)
class ExtractConfig:
    """Configuration consumed by :func:`extract_stage`."""

    mode: str
    workers: int
    no_sidecars: bool = False
    sidecar_extensions: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class FilterConfig:
    """Configuration consumed by :func:`filter_stage`."""

    min_size: int | None = None
    max_size: int | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    min_resolution: tuple[int, int] | None = None
    max_resolution: tuple[int, int] | None = None
    min_bitrate: int | None = None
    max_bitrate: int | None = None
    codecs: frozenset[str] | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Full configuration for the async pipeline."""

    # Scan
    directories: list[Path]
    recursive: bool
    extensions: frozenset[str]
    exclude: list[str] | None
    # Mode & workers
    mode: str
    workers: int
    # Filter
    min_size: int | None = None
    max_size: int | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    min_resolution: tuple[int, int] | None = None
    max_resolution: tuple[int, int] | None = None
    min_bitrate: int | None = None
    max_bitrate: int | None = None
    codecs: frozenset[str] | None = None
    # Content hashing
    content: bool = False
    rotation_invariant: bool = False
    content_method: str = "phash"
    # Pre-hash control
    no_pre_hash: bool = False
    # Audio
    audio: bool = False
    # Scoring
    comparators: list[Any] | None = None
    threshold: float = 50.0
    config_hash: str | None = None
    # Reference
    reference_dirs: list[Path] | None = None
    # Sidecar
    no_sidecars: bool = False
    sidecar_extensions: str | None = None
    # Pause
    pause_file: Path | None = None
    # Authoritative externally visible stages for this invocation
    visible_stages: frozenset[str] = dataclasses.field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Authoritative stage list
# ---------------------------------------------------------------------------


def compute_stage_list(
    *,
    is_replay: bool = False,
    is_ssim: bool = False,
    embed_thumbnails: bool = False,
    has_content: bool = False,
    has_audio: bool = False,
) -> list[str]:
    """Compute the authoritative stage list for a pipeline run.

    Single source of truth for which stages emit ``stage_start``/``stage_end``
    events.  Used by ``session_start.stages``.

    Only stages that perform real work are included.  Pass-through stages
    (content_hash when ``has_content`` is False, audio_fingerprint when
    ``has_audio`` is False) still run internally but are excluded from
    the authoritative list so GUI progress weights are not diluted.

    SSIM falls back to a legacy sequential path with different stages.
    Replay substitutes ``replay`` for the pre-report pipeline stages while
    preserving shared post-processing stages such as ``thumbnail`` and ``report``.
    """
    if is_replay:
        stages: list[str] = ["replay", "filter"]
    elif is_ssim:
        stages: list[str] = ["scan", "extract", "filter", "ssim_extract", "score"]
    else:
        stages: list[str] = ["scan", "extract", "filter"]
        if has_content:
            stages.append("content_hash")
        if has_audio:
            stages.append("audio_fingerprint")
        stages.append("score")

    if embed_thumbnails:
        stages.append("thumbnail")
    stages.append("report")
    return stages


def compute_visible_stage_set(
    *,
    mode: str,
    has_content: bool = False,
    has_audio: bool = False,
    content_method: str = "phash",
) -> frozenset[str]:
    """Return externally visible stages for one concrete pipeline configuration."""
    return frozenset(
        compute_stage_list(
            has_content=has_content and content_method != "ssim",
            has_audio=has_audio and mode != Mode.IMAGE,
        )
    )


def _stage_is_visible(config: Any, stage: str) -> bool:
    """Return True when *stage* is part of the advertised contract for *config*."""
    visible_stages = getattr(config, "visible_stages", None)
    if not isinstance(visible_stages, (set, frozenset, list, tuple)):
        visible_stages = compute_visible_stage_set(
            mode=getattr(config, "mode", Mode.VIDEO),
            has_content=bool(getattr(config, "content", False)),
            has_audio=bool(getattr(config, "audio", False)),
            content_method=getattr(config, "content_method", "phash"),
        )
    return stage in visible_stages


# ---------------------------------------------------------------------------
# run_pipeline — wire all stages together
# ---------------------------------------------------------------------------


async def run_pipeline(
    *,
    directories: list[Path],
    recursive: bool,
    extensions: frozenset[str],
    exclude: list[str] | None,
    mode: str,
    workers: int,
    cache: Any | None,
    progress: ProgressEmitter | None,
    controller: PipelineController,
    # Filter params
    min_size: int | None = None,
    max_size: int | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    min_resolution: tuple[int, int] | None = None,
    max_resolution: tuple[int, int] | None = None,
    min_bitrate: int | None = None,
    max_bitrate: int | None = None,
    codecs: frozenset[str] | None = None,
    # Content hashing
    content: bool = False,
    rotation_invariant: bool = False,
    content_method: str = "phash",
    # Pre-hash control
    no_pre_hash: bool = False,
    # Audio
    audio: bool = False,
    # Scoring
    comparators: list[Any] | None = None,
    threshold: float = 50.0,
    config_hash: str | None = None,
    # Reference
    reference_dirs: list[Path] | None = None,
    # Sidecar
    no_sidecars: bool = False,
    sidecar_extensions: str | None = None,
    # Pause
    pause_file: Path | None = None,
    # Optional pre-scanned seed input
    pre_scanned_paths: list[Path] | None = None,
    seeded_scan_time: float | None = None,
    seeded_discovered_paths: set[Path] | None = None,
    # Fast pre-count for stable progress totals
    expected_file_count: int | None = None,
) -> PipelineResult:
    """Run the full async streaming pipeline: scan -> extract -> filter -> hash -> audio -> score.

    Returns a list of :class:`~duplicates_detector.scorer.ScoredPair` objects.

    All six stages run concurrently inside a ``TaskGroup``, connected by
    unbounded queues. Scan streams files one-at-a-time via the sync
    generator bridge unless ``pre_scanned_paths`` is supplied, in which
    case the pipeline is seeded directly from that list. Extract, hash,
    and audio stages use concurrent fan-out with ``asyncio.wait(FIRST_COMPLETED)``.
    Score accumulates all metadata then runs ``find_duplicates`` in an executor.
    """
    scan_cfg = ScanConfig(
        directories=directories,
        recursive=recursive,
        extensions=extensions,
        exclude=exclude,
    )
    extract_cfg = ExtractConfig(
        mode=mode,
        workers=workers,
        no_sidecars=no_sidecars,
        sidecar_extensions=sidecar_extensions,
    )
    filter_cfg = FilterConfig(
        min_size=min_size,
        max_size=max_size,
        min_duration=min_duration,
        max_duration=max_duration,
        min_resolution=min_resolution,
        max_resolution=max_resolution,
        min_bitrate=min_bitrate,
        max_bitrate=max_bitrate,
        codecs=codecs,
    )

    # Build a config object for stages that need multiple fields
    visible_stages = compute_visible_stage_set(
        mode=mode,
        has_content=content,
        has_audio=audio,
        content_method=content_method,
    )
    pipeline_cfg = PipelineConfig(
        directories=directories,
        recursive=recursive,
        extensions=extensions,
        exclude=exclude,
        mode=mode,
        workers=workers,
        min_size=min_size,
        max_size=max_size,
        min_duration=min_duration,
        max_duration=max_duration,
        min_resolution=min_resolution,
        max_resolution=max_resolution,
        min_bitrate=min_bitrate,
        max_bitrate=max_bitrate,
        codecs=codecs,
        content=content,
        rotation_invariant=rotation_invariant,
        content_method=content_method,
        no_pre_hash=no_pre_hash,
        audio=audio,
        comparators=comparators,
        threshold=threshold,
        config_hash=config_hash,
        reference_dirs=reference_dirs,
        no_sidecars=no_sidecars,
        sidecar_extensions=sidecar_extensions,
        pause_file=pause_file,
        visible_stages=visible_stages,
    )

    # Unbounded queues: back-pressure from bounded queues caused the extract
    # stage to block on out_q.put() when downstream stages (content_hash,
    # audio) were slow on external drives.  With maxsize=500+200+200+100,
    # extract stalled at ~715 items for 1095-file scans.  Memory is trivial
    # (~1KB per VideoMetadata before content hashing adds frame data).
    scan_q: asyncio.Queue[Path | None] = asyncio.Queue()
    metadata_q: asyncio.Queue[VideoMetadata | None] = asyncio.Queue()
    filter_q: asyncio.Queue[VideoMetadata | None] = asyncio.Queue()
    hash_q: asyncio.Queue[VideoMetadata | None] = asyncio.Queue()
    audio_q: asyncio.Queue[VideoMetadata | None] = asyncio.Queue()

    # Shared stats accumulator — stages write their metrics here.
    # Each stage writes unique keys, so no concurrent-write conflicts.
    _stats: dict[str, Any] = {}
    if pre_scanned_paths is not None:
        _stats["scan_count"] = len(pre_scanned_paths)
        _stats["scan_time"] = seeded_scan_time or 0.0
        _stats["discovered_paths"] = seeded_discovered_paths or set(pre_scanned_paths)

    scored: list[ScoredPair] = []

    async def _collect() -> None:
        nonlocal scored
        scored = await score_stage(
            audio_q,
            cache,
            pipeline_cfg,
            progress,
            controller,
            config_hash=config_hash,
            _stats=_stats,
        )

    pause_watcher: asyncio.Task[None] | None = None
    try:
        if pause_file is not None:
            pause_watcher = asyncio.create_task(controller.watch_pause_file(pause_file))

        async with _TaskGroup() as tg:
            if pre_scanned_paths is None:
                tg.create_task(scan_stage(scan_cfg, scan_q, progress, controller, _stats=_stats))
            else:
                tg.create_task(seeded_scan_stage(pre_scanned_paths, scan_q, controller, _stats=_stats))
            tg.create_task(
                extract_stage(
                    scan_q,
                    metadata_q,
                    cache,
                    extract_cfg,
                    progress,
                    controller,
                    reference_dirs=reference_dirs,
                    expected_total=len(pre_scanned_paths) if pre_scanned_paths is not None else expected_file_count,
                    _stats=_stats,
                )
            )
            # When filters are active, pass None so downstream stages use
            # items_received (post-filter count) instead of the inflated
            # pre-filter total which makes progress/ETA artificially low.
            _has_filters = any(getattr(filter_cfg, f.name) is not None for f in dataclasses.fields(filter_cfg))
            _downstream_total = (
                None
                if _has_filters
                else (len(pre_scanned_paths) if pre_scanned_paths is not None else expected_file_count)
            )
            tg.create_task(filter_stage(metadata_q, filter_q, filter_cfg, progress, controller, _stats=_stats))
            tg.create_task(
                hash_stage(
                    filter_q,
                    hash_q,
                    cache,
                    pipeline_cfg,
                    progress,
                    controller,
                    expected_total=_downstream_total,
                    _stats=_stats,
                )
            )
            tg.create_task(
                audio_stage(
                    hash_q,
                    audio_q,
                    cache,
                    pipeline_cfg,
                    progress,
                    controller,
                    expected_total=_downstream_total,
                    _stats=_stats,
                )
            )
            tg.create_task(_collect())
    finally:
        if pause_watcher is not None:
            pause_watcher.cancel()
            with suppress(asyncio.CancelledError):
                await pause_watcher

    return PipelineResult(
        pairs=scored,
        files_scanned=_stats.get("scan_count", 0),
        files_after_filter=_stats.get("filter_count", 0),
        total_pairs_scored=_stats.get("score_count", len(scored)),
        pairs_found=_stats.get("pairs_found", len(scored)),
        scan_time=_stats.get("scan_time", 0.0),
        extract_time=_stats.get("extract_time", 0.0),
        filter_time=_stats.get("filter_time", 0.0),
        content_hash_time=_stats.get("content_hash_time", 0.0),
        audio_fingerprint_time=_stats.get("audio_fingerprint_time", 0.0),
        scoring_time=_stats.get("score_time", 0.0),
        stage_timings={s: _stats.get(f"{s}_time", 0.0) for s in _CANONICAL_STAGES},
        stage_counts={s: _stats.get(f"{s}_count", 0) for s in _CANONICAL_STAGES},
        discovered_paths=_stats.get("discovered_paths", set()),
    )
