from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import MagicMock

import pytest

from duplicates_detector.progress import ProgressEmitter


def _make_emitter(monkeypatch: pytest.MonkeyPatch) -> tuple[ProgressEmitter, StringIO]:
    buf = StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    e = ProgressEmitter()
    return e, buf


def _parse_events(buf: StringIO) -> list[dict]:
    buf.seek(0)
    return [json.loads(line) for line in buf if line.strip()]


class TestSessionEvents:
    def test_session_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.session_start(
            session_id="abc123",
            total_files=30000,
            stages=["scan", "extract", "score"],
        )
        events = _parse_events(buf)
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "session_start"
        assert ev["session_id"] == "abc123"
        assert ev["total_files"] == 30000
        assert ev["stages"] == ["scan", "extract", "score"]
        assert "wall_start" in ev
        assert ev["resumed_from"] is None

    def test_session_start_with_resumed_from(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.session_start(
            session_id="abc123",
            total_files=100,
            stages=["extract"],
            resumed_from="/tmp/checkpoint.json",
        )
        events = _parse_events(buf)
        assert events[0]["resumed_from"] == "/tmp/checkpoint.json"

    def test_session_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.session_end(session_id="abc123", total_elapsed=380.5, cache_time_saved=120.0)
        events = _parse_events(buf)
        assert events[0]["type"] == "session_end"
        assert events[0]["session_id"] == "abc123"
        assert events[0]["total_elapsed"] == 380.5
        assert events[0]["cache_time_saved"] == 120.0
        assert "timestamp" in events[0]

    def test_pause_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.pause(session_id="abc123", session_file="/tmp/session.json")
        events = _parse_events(buf)
        assert events[0]["type"] == "pause"
        assert events[0]["session_id"] == "abc123"
        assert events[0]["session_file"] == "/tmp/session.json"
        assert "timestamp" in events[0]

    def test_resume_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.resume(session_id="abc123")
        events = _parse_events(buf)
        assert events[0]["type"] == "resume"
        assert events[0]["session_id"] == "abc123"
        assert "timestamp" in events[0]


class TestEMARate:
    def test_rate_in_progress_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        # Simulate time passing by backdating the stage start and prev time
        e._stage_starts["extract"] = e._stage_starts["extract"] - 2.0
        e._prev_times["extract"] = e._prev_times["extract"] - 2.0
        e._last_emit.pop("extract", None)  # clear throttle
        e.progress("extract", current=50, total=100, force=True)
        events = _parse_events(buf)
        progress_events = [ev for ev in events if ev["type"] == "progress"]
        assert len(progress_events) >= 1
        assert "rate" in progress_events[-1]
        assert progress_events[-1]["rate"] > 0
        assert "eta_seconds" in progress_events[-1]
        assert progress_events[-1]["eta_seconds"] >= 0

    def test_ema_smoothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EMA rate should smooth out fluctuations across multiple emissions."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        # First progress: 10 items in 1 second
        e._prev_times["extract"] = e._prev_times["extract"] - 1.0
        e._last_emit.pop("extract", None)
        e.progress("extract", current=10, total=100, force=True)
        # Second progress: 20 more items in 1 second (faster)
        e._prev_times["extract"] = e._prev_times["extract"] - 1.0
        e._last_emit.pop("extract", None)
        e.progress("extract", current=30, total=100, force=True)
        events = _parse_events(buf)
        progress_events = [ev for ev in events if ev["type"] == "progress"]
        assert len(progress_events) == 2
        # Second rate should be smoothed (not purely the instantaneous 20/s)
        rate1 = progress_events[0]["rate"]
        rate2 = progress_events[1]["rate"]
        assert rate1 > 0
        assert rate2 > 0

    def test_no_rate_when_no_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rate should not appear when current hasn't advanced."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        e._prev_times["extract"] = e._prev_times["extract"] - 1.0
        e._last_emit.pop("extract", None)
        # current=0, same as prev_count=0 — no progress
        e.progress("extract", current=0, total=100, force=True)
        events = _parse_events(buf)
        progress_events = [ev for ev in events if ev["type"] == "progress"]
        assert "rate" not in progress_events[-1]

    def test_cache_stats_in_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        e._last_emit.pop("extract", None)
        e.progress("extract", current=10, total=100, cache_hits=8, cache_misses=2, force=True)
        events = _parse_events(buf)
        progress_events = [ev for ev in events if ev["type"] == "progress"]
        assert progress_events[-1]["cache_hits"] == 8
        assert progress_events[-1]["cache_misses"] == 2

    def test_cache_stats_omitted_when_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        e._last_emit.pop("extract", None)
        e.progress("extract", current=10, total=100, force=True)
        events = _parse_events(buf)
        progress_events = [ev for ev in events if ev["type"] == "progress"]
        assert "cache_hits" not in progress_events[-1]
        assert "cache_misses" not in progress_events[-1]


class TestCacheStatsInStageEnd:
    def test_stage_end_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        e.stage_end("extract", total=100, elapsed=5.0, cache_hits=80, cache_misses=20)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert end_events[0]["cache_hits"] == 80
        assert end_events[0]["cache_misses"] == 20

    def test_score_stage_end_includes_cache_stats_and_pairs_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Score stage_end event carries cache_hits, cache_misses, and pairs_found via **extra kwargs."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("score")
        e.stage_end("score", total=100, elapsed=1.0, pairs_found=5, cache_hits=42, cache_misses=8)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        ev = end_events[0]
        assert ev["stage"] == "score"
        assert ev["total"] == 100
        assert ev["pairs_found"] == 5
        assert ev["cache_hits"] == 42
        assert ev["cache_misses"] == 8

    def test_score_stage_end_zero_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Score stage_end with zero cache hits/misses still includes the fields."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("score")
        e.stage_end("score", total=50, elapsed=0.5, pairs_found=0, cache_hits=0, cache_misses=0)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        ev = end_events[0]
        assert ev["cache_hits"] == 0
        assert ev["cache_misses"] == 0
        assert ev["pairs_found"] == 0


class TestHashedAndFingerprintedExtras:
    """Verify that stage_end events for content_hash and audio_fingerprint include
    the ``hashed`` and ``fingerprinted`` extras respectively."""

    def test_content_hash_stage_end_includes_hashed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """content_hash stage_end should carry a ``hashed`` count."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("content_hash", total=12)
        e.stage_end("content_hash", total=12, elapsed=3.5, hashed=12)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["stage"] == "content_hash"
        assert end_events[0]["hashed"] == 12

    def test_audio_fingerprint_stage_end_includes_fingerprinted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """audio_fingerprint stage_end should carry a ``fingerprinted`` count."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("audio_fingerprint", total=7)
        e.stage_end("audio_fingerprint", total=7, elapsed=2.1, fingerprinted=7)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["stage"] == "audio_fingerprint"
        assert end_events[0]["fingerprinted"] == 7

    def test_hashed_zero_still_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A zero ``hashed`` count should still appear in the event (not omitted)."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("content_hash")
        e.stage_end("content_hash", total=0, elapsed=0.0, hashed=0)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert end_events[0]["hashed"] == 0

    def test_fingerprinted_zero_still_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A zero ``fingerprinted`` count should still appear in the event (not omitted)."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("audio_fingerprint")
        e.stage_end("audio_fingerprint", total=0, elapsed=0.0, fingerprinted=0)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert end_events[0]["fingerprinted"] == 0

    def test_hashed_coexists_with_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """content_hash stage_end can carry both ``hashed`` and cache stats."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("content_hash", total=20)
        e.stage_end("content_hash", total=20, elapsed=4.0, cache_hits=15, cache_misses=5, hashed=20)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        ev = end_events[0]
        assert ev["hashed"] == 20
        assert ev["cache_hits"] == 15
        assert ev["cache_misses"] == 5

    def test_fingerprinted_coexists_with_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """audio_fingerprint stage_end can carry both ``fingerprinted`` and cache stats."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("audio_fingerprint", total=10)
        e.stage_end("audio_fingerprint", total=10, elapsed=1.5, cache_hits=6, cache_misses=4, fingerprinted=10)
        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        ev = end_events[0]
        assert ev["fingerprinted"] == 10
        assert ev["cache_hits"] == 6
        assert ev["cache_misses"] == 4


class TestStageStateCleanup:
    def test_stage_end_clears_ema_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stage_end clears all per-stage tracking state."""
        e, buf = _make_emitter(monkeypatch)
        e.stage_start("extract", total=100)
        e.progress("extract", current=10, total=100, force=True)
        e.stage_end("extract", total=100, elapsed=5.0)
        assert "extract" not in e._stage_starts
        assert "extract" not in e._ema_rates
        assert "extract" not in e._prev_counts
        assert "extract" not in e._prev_times
        assert "extract" not in e._last_emit


# ---------------------------------------------------------------------------
# AggregatingProgressEmitter + _SubEmitter
# ---------------------------------------------------------------------------


class TestAggregatingProgressEmitter:
    """Tests for aggregating progress from concurrent sub-pipelines."""

    def test_stage_start_emitted_on_first_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unified stage_start fires when the first sub-pipeline enters a stage."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("extract", total=50)
        events = _parse_events(buf)
        starts = [e for e in events if e["type"] == "stage_start"]
        assert len(starts) == 1
        assert starts[0]["stage"] == "extract"
        assert starts[0]["total"] == 50

        # Second sub-pipeline entering same stage should NOT emit another stage_start
        sub1.stage_start("extract", total=30)
        events = _parse_events(buf)
        starts = [e for e in events if e["type"] == "stage_start"]
        assert len(starts) == 1  # still only 1

    def test_stage_start_combines_totals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both sub-pipelines provide totals before first emit, combined total is emitted.

        Note: only the first sub-pipeline's total is known at stage_start time.
        The combined total only appears in later progress events.
        """
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)

        sub0.stage_start("extract", total=50)
        events = _parse_events(buf)
        starts = [e for e in events if e["type"] == "stage_start"]
        assert starts[0]["total"] == 50  # only first sub's total at this point

    def test_progress_aggregates_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Progress events combine current/total from all sub-pipelines."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("extract", total=50)
        sub1.stage_start("extract", total=30)

        sub0.progress("extract", current=10, total=50, force=True)
        sub1.progress("extract", current=5, total=30, force=True)

        events = _parse_events(buf)
        progress_events = [e for e in events if e["type"] == "progress"]
        # The last progress event should have combined totals
        last = progress_events[-1]
        assert last["current"] == 15  # 10 + 5
        assert last["total"] == 80  # 50 + 30

    def test_progress_aggregates_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache hits/misses are summed across sub-pipelines."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("extract", total=10)
        sub1.stage_start("extract", total=10)
        sub0.progress("extract", current=5, cache_hits=3, cache_misses=2, force=True)
        sub1.progress("extract", current=3, cache_hits=1, cache_misses=2, force=True)

        events = _parse_events(buf)
        progress_events = [e for e in events if e["type"] == "progress"]
        last = progress_events[-1]
        assert last["cache_hits"] == 4  # 3 + 1
        assert last["cache_misses"] == 4  # 2 + 2

    def test_stage_end_waits_for_all_sub_pipelines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stage_end is only emitted when all sub_count sub-pipelines complete."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("extract", total=50)
        sub1.stage_start("extract", total=30)

        # First sub-pipeline completes
        sub0.stage_end("extract", total=50, elapsed=2.0)
        events = _parse_events(buf)
        end_events = [e for e in events if e["type"] == "stage_end"]
        assert len(end_events) == 0  # NOT yet emitted

        # Second sub-pipeline completes
        sub1.stage_end("extract", total=30, elapsed=3.0)
        events = _parse_events(buf)
        end_events = [e for e in events if e["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["total"] == 80  # 50 + 30
        assert end_events[0]["elapsed"] == 3.0  # max of 2.0, 3.0

    def test_stage_end_merges_numeric_extras(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Extra kwargs in stage_end are summed if numeric."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("extract")
        sub1.stage_start("extract")
        sub0.stage_end("extract", total=10, elapsed=1.0, cache_hits=5, cache_misses=3)
        sub1.stage_end("extract", total=20, elapsed=2.0, cache_hits=8, cache_misses=2)

        events = _parse_events(buf)
        end_events = [e for e in events if e["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["cache_hits"] == 13  # 5 + 8
        assert end_events[0]["cache_misses"] == 5  # 3 + 2

    def test_stage_end_no_early_fire_before_all_enter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stage_end must not fire when one sub completes before the other enters.

        This tests the critical sub_count-based gating: even if sub0 has both
        entered AND completed a stage, stage_end waits for sub_count=2
        completions, not just 'all entered have completed'.
        """
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        # Only sub0 enters and completes
        sub0.stage_start("extract", total=10)
        sub0.stage_end("extract", total=10, elapsed=1.0)

        events = _parse_events(buf)
        end_events = [e for e in events if e["type"] == "stage_end"]
        assert len(end_events) == 0  # Must NOT fire yet

        # Now sub1 enters and completes
        sub1.stage_start("extract", total=5)
        sub1.stage_end("extract", total=5, elapsed=0.5)

        events = _parse_events(buf)
        end_events = [e for e in events if e["type"] == "stage_end"]
        assert len(end_events) == 1


class TestSubEmitter:
    """Tests for _SubEmitter duck-typed interface."""

    def test_sub_emitter_has_stage_start(self) -> None:
        """_SubEmitter implements stage_start method."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=1)
        sub = agg.create_sub_emitter(0)
        assert hasattr(sub, "stage_start")
        assert callable(sub.stage_start)

    def test_sub_emitter_has_progress(self) -> None:
        """_SubEmitter implements progress method."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=1)
        sub = agg.create_sub_emitter(0)
        assert hasattr(sub, "progress")
        assert callable(sub.progress)

    def test_sub_emitter_has_stage_end(self) -> None:
        """_SubEmitter implements stage_end method."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=1)
        sub = agg.create_sub_emitter(0)
        assert hasattr(sub, "stage_end")
        assert callable(sub.stage_end)

    def test_sub_emitter_routes_to_aggregator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_SubEmitter routes all events through the aggregator to the delegate."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=1)
        sub = agg.create_sub_emitter(0)

        sub.stage_start("scan", total=10)
        sub.progress("scan", current=5, total=10, force=True)
        sub.stage_end("scan", total=10, elapsed=1.0)

        events = _parse_events(buf)
        types = [e["type"] for e in events]
        assert "stage_start" in types
        assert "progress" in types
        assert "stage_end" in types


class TestUnifiedStageState:
    """Tests for AggregatingProgressEmitter.unified_stage_state()."""

    def test_no_stages_entered(self) -> None:
        """No stages entered: empty completed, no active."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        completed, active = agg.unified_stage_state()
        assert completed == []
        assert active is None

    def test_one_sub_entered(self) -> None:
        """One sub entered: stage is active but not completed."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub0.stage_start("scan")
        completed, active = agg.unified_stage_state()
        assert completed == []
        assert active == "scan"

    def test_both_completed(self) -> None:
        """Both subs completed: stage is completed, no active."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("scan")
        sub0.stage_end("scan", total=10, elapsed=1.0)
        sub1.stage_start("scan")
        sub1.stage_end("scan", total=5, elapsed=0.5)

        completed, active = agg.unified_stage_state()
        assert completed == ["scan"]
        assert active is None

    def test_mixed_completed_and_active(self) -> None:
        """One stage completed, another active."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        # Both complete scan
        sub0.stage_start("scan")
        sub0.stage_end("scan", total=10, elapsed=1.0)
        sub1.stage_start("scan")
        sub1.stage_end("scan", total=5, elapsed=0.5)

        # Only sub0 enters extract
        sub0.stage_start("extract")

        completed, active = agg.unified_stage_state()
        assert completed == ["scan"]
        assert active == "extract"

    def test_uses_sub_count_not_entered_count(self) -> None:
        """Completion is based on sub_count, not how many have entered.

        If sub_count=2 but only one sub has entered and completed a stage,
        the stage is NOT considered completed.
        """
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)

        sub0.stage_start("scan")
        sub0.stage_end("scan", total=10, elapsed=1.0)

        completed, active = agg.unified_stage_state()
        # scan is NOT completed (only 1 of 2 subs finished)
        assert "scan" not in completed
        # scan is active (entered but not fully completed)
        assert active == "scan"

    def test_only_tracks_canonical_stages(self) -> None:
        """unified_stage_state only reports on _CANONICAL_STAGES."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=1)
        sub = agg.create_sub_emitter(0)

        # Enter and complete a non-canonical stage
        sub.stage_start("thumbnail")
        sub.stage_end("thumbnail", total=5, elapsed=0.1)

        completed, active = agg.unified_stage_state()
        # thumbnail is not a canonical stage, so it's not reported
        assert "thumbnail" not in completed
        assert active is None

    def test_stage_with_single_expected_participant_completes(self) -> None:
        """Per-stage expected counts let auto-mode audio complete with one participating sub-pipeline."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = ProgressEmitter()
        agg = AggregatingProgressEmitter(delegate, sub_count=2, expected_stage_counts={"audio_fingerprint": 1})
        sub0 = agg.create_sub_emitter(0)

        sub0.stage_start("audio_fingerprint")
        sub0.stage_end("audio_fingerprint", total=2, elapsed=0.5)

        completed, active = agg.unified_stage_state()
        assert "audio_fingerprint" in completed
        assert active is None

    def test_zero_expected_stage_is_ignored(self) -> None:
        """Stages with zero expected participants are ignored entirely."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate = MagicMock()
        agg = AggregatingProgressEmitter(delegate, sub_count=2, expected_stage_counts={"audio_fingerprint": 0})
        sub0 = agg.create_sub_emitter(0)

        sub0.stage_start("audio_fingerprint")
        sub0.progress("audio_fingerprint", current=1, total=1)
        sub0.stage_end("audio_fingerprint", total=1, elapsed=0.1)

        completed, active = agg.unified_stage_state()
        assert "audio_fingerprint" not in completed
        assert active is None
        delegate.stage_start.assert_not_called()
        delegate.progress.assert_not_called()
        delegate.stage_end.assert_not_called()


class TestAggregatedHashedAndFingerprinted:
    """Verify that hashed/fingerprinted extras are correctly merged when
    aggregating stage_end events from concurrent sub-pipelines."""

    def test_aggregator_sums_hashed_across_sub_pipelines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two sub-pipelines completing content_hash should sum their ``hashed`` counts."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("content_hash", total=8)
        sub1.stage_start("content_hash", total=5)

        sub0.stage_end("content_hash", total=8, elapsed=2.0, hashed=8)
        sub1.stage_end("content_hash", total=5, elapsed=1.5, hashed=5)

        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["hashed"] == 13  # 8 + 5

    def test_aggregator_sums_fingerprinted_across_sub_pipelines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two sub-pipelines completing audio_fingerprint should sum their ``fingerprinted`` counts."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("audio_fingerprint", total=4)
        sub1.stage_start("audio_fingerprint", total=6)

        sub0.stage_end("audio_fingerprint", total=4, elapsed=1.0, fingerprinted=4)
        sub1.stage_end("audio_fingerprint", total=6, elapsed=2.0, fingerprinted=6)

        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["fingerprinted"] == 10  # 4 + 6

    def test_aggregator_merges_hashed_with_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Aggregated content_hash stage_end should carry both merged hashed and cache stats."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=2)
        sub0 = agg.create_sub_emitter(0)
        sub1 = agg.create_sub_emitter(1)

        sub0.stage_start("content_hash")
        sub1.stage_start("content_hash")

        sub0.stage_end("content_hash", total=10, elapsed=1.0, hashed=10, cache_hits=7, cache_misses=3)
        sub1.stage_end("content_hash", total=5, elapsed=2.0, hashed=5, cache_hits=2, cache_misses=3)

        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        ev = end_events[0]
        assert ev["hashed"] == 15  # 10 + 5
        assert ev["cache_hits"] == 9  # 7 + 2
        assert ev["cache_misses"] == 6  # 3 + 3

    def test_single_sub_pipeline_hashed_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With sub_count=1, hashed extra passes through directly."""
        from duplicates_detector.progress import AggregatingProgressEmitter

        delegate, buf = _make_emitter(monkeypatch)
        agg = AggregatingProgressEmitter(delegate, sub_count=1)
        sub = agg.create_sub_emitter(0)

        sub.stage_start("content_hash", total=3)
        sub.stage_end("content_hash", total=3, elapsed=0.5, hashed=3)

        events = _parse_events(buf)
        end_events = [ev for ev in events if ev["type"] == "stage_end"]
        assert len(end_events) == 1
        assert end_events[0]["hashed"] == 3
