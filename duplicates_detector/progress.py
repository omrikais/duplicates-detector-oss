from __future__ import annotations

import json
import queue
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task as ProgressTask,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text


class ThroughputColumn(ProgressColumn):
    """Show processing speed as 'X.Y <unit>/s'."""

    def __init__(self, unit: str = "files") -> None:
        self._unit = unit
        super().__init__()

    def render(self, task: ProgressTask) -> Text:
        speed = task.finished_speed or task.speed
        if speed is None:
            return Text("")
        return Text(f"{speed:.1f} {self._unit}/s", style="progress.data.speed")


def make_progress(
    *,
    console: Console | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
    unit: str = "files",
) -> Progress:
    """Create the standard 7-column progress bar used across extract/score stages."""
    if console is None:
        console = Console(stderr=True)
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        ThroughputColumn(unit),
        console=console,
        transient=True,
        disable=quiet or progress_emitter is not None,
    )


class ProgressEmitter:
    """Emit structured JSON-lines progress events to stderr.

    Designed for GUI frontends that need machine-parseable real-time
    progress information.  Each event is a single JSON object followed
    by a newline, flushed immediately.

    Throttling: ``progress()`` events are rate-limited to at most one
    every ``_THROTTLE_INTERVAL`` seconds per stage.  The final event
    (when *current* equals the previously emitted *total*) is always
    emitted.  Pass ``force=True`` to bypass throttling.

    When ``threaded=True``, writes are dispatched to a background daemon
    thread so that ``sys.stderr.flush()`` never blocks the asyncio event
    loop.  Without this, a full stderr pipe buffer (GUI subprocess) can
    freeze the entire pipeline.
    """

    _THROTTLE_INTERVAL = 0.1  # 100ms
    _EMA_ALPHA = 0.3

    def __init__(self, *, threaded: bool = False) -> None:
        self._last_emit: dict[str, float] = {}
        self._stage_starts: dict[str, float] = {}
        self._ema_rates: dict[str, float] = {}
        self._prev_counts: dict[str, int] = {}
        self._prev_times: dict[str, float] = {}
        self._threaded = threaded
        if threaded:
            self._write_q: queue.Queue[str | None] = queue.Queue()
            self._writer = threading.Thread(target=self._writer_loop, daemon=True, name="progress-writer")
            self._writer.start()

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    # -- Background writer thread ------------------------------------------

    def _writer_loop(self) -> None:
        """Drain the write queue, writing each line to stderr.

        Runs in a daemon thread.  Terminates on ``None`` sentinel.
        """
        while True:
            line = self._write_q.get()
            if line is None:
                break
            sys.stderr.write(line)
            sys.stderr.flush()

    def _write(self, event: dict) -> None:
        line = json.dumps(event, separators=(",", ":")) + "\n"
        if self._threaded:
            self._write_q.put(line)
        else:
            sys.stderr.write(line)
            sys.stderr.flush()

    def close(self) -> None:
        """Flush remaining events and stop the writer thread (if threaded)."""
        if self._threaded:
            self._write_q.put(None)
            self._writer.join(timeout=5)

    # ------------------------------------------------------------------
    # Session lifecycle events
    # ------------------------------------------------------------------

    def session_start(
        self,
        session_id: str,
        total_files: int,
        stages: list[str],
        resumed_from: str | None = None,
        prior_elapsed_seconds: float = 0.0,
    ) -> None:
        """Emit a session_start event at the beginning of a pipeline run."""
        event: dict = {
            "type": "session_start",
            "session_id": session_id,
            "total_files": total_files,
            "stages": stages,
            "wall_start": self._iso_now(),
            "resumed_from": resumed_from,
            "prior_elapsed_seconds": prior_elapsed_seconds,
        }
        self._write(event)

    def session_end(
        self,
        session_id: str,
        total_elapsed: float,
        cache_time_saved: float,
    ) -> None:
        """Emit a session_end event at the end of a pipeline run."""
        event: dict = {
            "type": "session_end",
            "session_id": session_id,
            "total_elapsed": total_elapsed,
            "cache_time_saved": cache_time_saved,
            "timestamp": self._iso_now(),
        }
        self._write(event)

    def pause(self, session_id: str, session_file: str) -> None:
        """Emit a pause event when the pipeline is paused."""
        event: dict = {
            "type": "pause",
            "session_id": session_id,
            "session_file": session_file,
            "timestamp": self._iso_now(),
        }
        self._write(event)

    def resume(self, session_id: str) -> None:
        """Emit a resume event when the pipeline is resumed."""
        event: dict = {
            "type": "resume",
            "session_id": session_id,
            "timestamp": self._iso_now(),
        }
        self._write(event)

    # ------------------------------------------------------------------
    # Stage lifecycle events
    # ------------------------------------------------------------------

    def stage_start(self, stage: str, *, total: int | None = None) -> None:
        event: dict = {
            "type": "stage_start",
            "stage": stage,
            "timestamp": self._iso_now(),
        }
        if total is not None:
            event["total"] = total
        self._stage_starts[stage] = time.monotonic()
        self._prev_counts[stage] = 0
        self._prev_times[stage] = self._stage_starts[stage]
        self._write(event)

    def progress(
        self,
        stage: str,
        *,
        current: int,
        total: int | None = None,
        file: str | None = None,
        cache_hits: int | None = None,
        cache_misses: int | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        last = self._last_emit.get(stage, 0.0)
        if not force and (now - last) < self._THROTTLE_INTERVAL:
            return
        self._last_emit[stage] = now
        event: dict = {
            "type": "progress",
            "stage": stage,
            "current": current,
            "timestamp": self._iso_now(),
        }
        if total is not None:
            event["total"] = total
        if file is not None:
            event["file"] = file
        if cache_hits is not None:
            event["cache_hits"] = cache_hits
        if cache_misses is not None:
            event["cache_misses"] = cache_misses

        # EMA rate calculation
        prev_count = self._prev_counts.get(stage, 0)
        prev_time = self._prev_times.get(stage, now)
        time_delta = now - prev_time
        if time_delta > 0 and current > prev_count:
            instant_rate = (current - prev_count) / time_delta
            prev_ema = self._ema_rates.get(stage)
            if prev_ema is None:
                ema = instant_rate
            else:
                ema = self._EMA_ALPHA * instant_rate + (1 - self._EMA_ALPHA) * prev_ema
            self._ema_rates[stage] = ema
            event["rate"] = round(ema, 2)
            if total is not None and ema > 0:
                remaining = total - current
                event["eta_seconds"] = round(remaining / ema, 1)
        self._prev_counts[stage] = current
        self._prev_times[stage] = now

        self._write(event)

    def stage_end(self, stage: str, *, total: int, elapsed: float, **extra: object) -> None:
        event: dict = {
            "type": "stage_end",
            "stage": stage,
            "total": total,
            "elapsed": round(elapsed, 3),
            "timestamp": self._iso_now(),
        }
        event.update(extra)
        self._write(event)
        # Clear all per-stage tracking state
        self._last_emit.pop(stage, None)
        self._stage_starts.pop(stage, None)
        self._ema_rates.pop(stage, None)
        self._prev_counts.pop(stage, None)
        self._prev_times.pop(stage, None)


# ---------------------------------------------------------------------------
# Aggregating progress for concurrent auto-mode sub-pipelines
# ---------------------------------------------------------------------------


class _SubEmitter:
    """Per-sub-pipeline emitter that routes events to an :class:`AggregatingProgressEmitter`.

    Implements the same method signatures as :class:`ProgressEmitter` so it
    can be passed to ``run_pipeline(progress=...)``.  Duck-typed — no
    ``isinstance`` checks exist in the codebase.
    """

    def __init__(self, parent: AggregatingProgressEmitter, sub_id: int) -> None:
        self._parent = parent
        self._sub_id = sub_id

    def stage_start(self, stage: str, *, total: int | None = None) -> None:
        self._parent._on_stage_start(self._sub_id, stage, total)

    def progress(
        self,
        stage: str,
        *,
        current: int,
        total: int | None = None,
        file: str | None = None,
        cache_hits: int | None = None,
        cache_misses: int | None = None,
        force: bool = False,
    ) -> None:
        self._parent._on_progress(
            self._sub_id,
            stage,
            current,
            total=total,
            file=file,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            force=force,
        )

    def stage_end(self, stage: str, *, total: int, elapsed: float, **extra: object) -> None:
        self._parent._on_stage_end(self._sub_id, stage, total, elapsed, **extra)


class AggregatingProgressEmitter:
    """Merge progress from N concurrent sub-pipelines into unified events.

    - ``stage_start``: emitted when the FIRST sub-pipeline enters a stage.
    - ``progress``: aggregates current/total/cache counts from all sub-pipelines,
      then delegates to the real :class:`ProgressEmitter` (which handles throttling).
    - ``stage_end``: emitted when all N expected sub-pipelines
      (``self._sub_count``) have completed a stage — NOT when all *entered*
      sub-pipelines have, to prevent early firing when one branch completes
      before the other enters.

    Thread-safe: ``score_stage`` runs ``find_duplicates`` in an executor thread
    that calls ``progress()`` directly, so the lock protects concurrent access.
    """

    def __init__(
        self,
        delegate: ProgressEmitter,
        sub_count: int,
        expected_stage_counts: dict[str, int] | None = None,
    ) -> None:
        self._delegate = delegate
        self._sub_count = sub_count
        self._expected_stage_counts = dict(expected_stage_counts or {})
        self._lock = threading.Lock()
        self._stage_entered: dict[str, set[int]] = defaultdict(set)
        self._stage_completed: dict[str, set[int]] = defaultdict(set)
        self._currents: dict[str, dict[int, int]] = defaultdict(dict)
        self._totals: dict[str, dict[int, int]] = defaultdict(dict)
        self._elapsed: dict[str, dict[int, float]] = defaultdict(dict)
        self._cache_hits: dict[str, dict[int, int]] = defaultdict(dict)
        self._cache_misses: dict[str, dict[int, int]] = defaultdict(dict)
        self._end_extras: dict[str, dict[int, dict]] = defaultdict(dict)

    def _expected_count(self, stage: str) -> int:
        return self._expected_stage_counts.get(stage, self._sub_count)

    def create_sub_emitter(self, sub_id: int) -> _SubEmitter:
        """Create a per-sub-pipeline emitter that routes events to this aggregator."""
        return _SubEmitter(self, sub_id)

    def _on_stage_start(self, sub_id: int, stage: str, total: int | None) -> None:
        if self._expected_count(stage) <= 0:
            return
        with self._lock:
            self._stage_entered[stage].add(sub_id)
            if total is not None:
                self._totals[stage][sub_id] = total
            # Emit unified stage_start on FIRST entry
            if len(self._stage_entered[stage]) == 1:
                combined = sum(self._totals[stage].values()) if self._totals[stage] else None
                self._delegate.stage_start(stage, total=combined)

    def _on_progress(
        self,
        sub_id: int,
        stage: str,
        current: int,
        *,
        total: int | None = None,
        file: str | None = None,
        cache_hits: int | None = None,
        cache_misses: int | None = None,
        force: bool = False,
    ) -> None:
        if self._expected_count(stage) <= 0:
            return
        with self._lock:
            self._currents[stage][sub_id] = current
            if total is not None:
                self._totals[stage][sub_id] = total
            if cache_hits is not None:
                self._cache_hits[stage][sub_id] = cache_hits
            if cache_misses is not None:
                self._cache_misses[stage][sub_id] = cache_misses
            combined_current = sum(self._currents[stage].values())
            combined_total = sum(self._totals[stage].values()) if self._totals[stage] else None
            combined_hits = sum(self._cache_hits[stage].values()) if self._cache_hits[stage] else None
            combined_misses = sum(self._cache_misses[stage].values()) if self._cache_misses[stage] else None
        # Delegate to real emitter outside lock (it handles throttling)
        self._delegate.progress(
            stage,
            current=combined_current,
            total=combined_total,
            cache_hits=combined_hits,
            cache_misses=combined_misses,
            force=force,
        )

    def _on_stage_end(self, sub_id: int, stage: str, total: int, elapsed: float, **extra: object) -> None:
        expected = self._expected_count(stage)
        if expected <= 0:
            return
        with self._lock:
            self._stage_completed[stage].add(sub_id)
            self._elapsed[stage][sub_id] = elapsed
            self._totals[stage][sub_id] = total
            self._end_extras[stage][sub_id] = dict(extra)
            completed = len(self._stage_completed[stage])
            if completed < expected:
                return  # Still waiting for other sub-pipelines
            # All N expected sub-pipelines have completed — emit unified stage_end.
            combined_total = sum(self._totals[stage].values())
            max_elapsed = max(self._elapsed[stage].values())
            merged_extra: dict[str, object] = {}
            for ex in self._end_extras[stage].values():
                for k, v in ex.items():
                    if isinstance(v, (int, float)):
                        merged_extra[k] = (merged_extra.get(k) or 0) + v  # type: ignore[operator]
                    else:
                        merged_extra[k] = v
        self._delegate.stage_end(stage, total=combined_total, elapsed=max_elapsed, **merged_extra)

    def unified_stage_state(self) -> tuple[list[str], str | None]:
        """Return ``(completed_stages, active_stage)`` from the unified perspective.

        A stage is 'completed' when all N expected sub-pipelines
        (``self._sub_count``) have completed it.  A stage is 'active' if at
        least one sub-pipeline has entered it but fewer than ``sub_count``
        have completed.

        Only covers the 6 canonical async stages.  Thumbnail and report are
        post-pipeline stages managed by ``cli.py`` outside the aggregator scope.
        """
        snapshot = self.unified_stage_snapshot()
        return snapshot.completed_stages, snapshot.active_stage

    def unified_stage_snapshot(self):
        """Return a pause-checkpoint snapshot for concurrent auto-mode pipelines."""
        from duplicates_detector.pipeline import _CANONICAL_STAGES
        from duplicates_detector.pipeline import PipelineStageSnapshot

        with self._lock:
            completed: list[str] = []
            active: str | None = None
            stage_timings: dict[str, float] = {}
            for stage in _CANONICAL_STAGES:
                expected = self._expected_count(stage)
                if expected <= 0:
                    continue
                done = self._stage_completed.get(stage, set())
                entered = self._stage_entered.get(stage, set())
                if len(done) >= expected:
                    completed.append(stage)
                    elapsed = self._elapsed.get(stage, {})
                    if elapsed:
                        stage_timings[stage] = max(elapsed.values())
                elif entered and active is None:
                    active = stage
            return PipelineStageSnapshot(
                completed_stages=completed,
                active_stage=active,
                stage_timings=stage_timings,
            )
