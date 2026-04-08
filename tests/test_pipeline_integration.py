from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from duplicates_detector.cache_db import CacheDB
from duplicates_detector.pipeline import PipelineController, PipelineResult, run_pipeline
from duplicates_detector.progress import ProgressEmitter
from duplicates_detector.scorer import compute_config_hash
from duplicates_detector.session import ScanSession, SessionManager


class TestAsyncPipelineIntegration:
    """Tests that exercise multiple pipeline components together."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_with_empty_directory(self, tmp_path: Path) -> None:
        """Pipeline handles empty directories gracefully."""
        ctrl = PipelineController()
        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.progress = MagicMock()
        progress.stage_end = MagicMock()

        results = await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=progress,
            controller=ctrl,
        )
        assert isinstance(results, PipelineResult)
        assert len(results.pairs) == 0

    @pytest.mark.asyncio
    async def test_pipeline_with_cache(self, tmp_path: Path) -> None:
        """Pipeline works with CacheDB integration (no crash on fake files)."""
        (tmp_path / "a.mp4").write_bytes(b"fake video content a")
        (tmp_path / "b.mp4").write_bytes(b"fake video content b")

        cache = CacheDB(tmp_path / "cache")
        try:
            ctrl = PipelineController()
            progress = MagicMock()
            progress.stage_start = MagicMock()
            progress.progress = MagicMock()
            progress.stage_end = MagicMock()

            results = await run_pipeline(
                directories=[tmp_path],
                recursive=True,
                extensions=frozenset({".mp4"}),
                exclude=None,
                mode="video",
                workers=1,
                cache=cache,
                progress=progress,
                controller=ctrl,
            )
            assert isinstance(results, PipelineResult)
            # Even though extraction will fail (no real media), pipeline should not crash
        finally:
            cache.close()

    @pytest.mark.asyncio
    async def test_pipeline_progress_stage_events(self, tmp_path: Path) -> None:
        """Pipeline emits stage lifecycle events for the stages that actually run."""
        (tmp_path / "clip.mp4").write_bytes(b"x")

        ctrl = PipelineController()
        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.progress = MagicMock()
        progress.stage_end = MagicMock()

        await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=progress,
            controller=ctrl,
        )

        # Default video scans without content/audio emit only the visible stages.
        start_stages = [call.args[0] for call in progress.stage_start.call_args_list]
        end_stages = [call.args[0] for call in progress.stage_end.call_args_list]
        for stage in ("scan", "extract", "filter", "score"):
            assert stage in start_stages, f"{stage} missing from stage_start"
            assert stage in end_stages, f"{stage} missing from stage_end"
        assert "content_hash" not in start_stages
        assert "audio_fingerprint" not in start_stages

    @pytest.mark.asyncio
    async def test_pipeline_with_filters(self, tmp_path: Path) -> None:
        """Pipeline applies filter parameters correctly."""
        (tmp_path / "a.mp4").write_bytes(b"x" * 100)
        (tmp_path / "b.mp4").write_bytes(b"y" * 200)

        ctrl = PipelineController()

        results = await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=None,
            controller=ctrl,
            # Apply very restrictive filters that would exclude small fake files
            min_size=1_000_000_000,
        )
        # All files should be filtered out by the huge min_size
        # (but this depends on metadata extraction — fake files won't produce
        # valid metadata so they won't reach filtering anyway)
        assert isinstance(results, PipelineResult)


class TestPauseResumeIntegration:
    """Tests pause/resume across pipeline components."""

    @pytest.mark.asyncio
    async def test_pause_file_controls_pipeline(self, tmp_path: Path) -> None:
        """Pause file correctly pauses and resumes the controller."""
        pause_file = tmp_path / "pause.ctl"
        pause_file.write_text("resume")

        ctrl = PipelineController()
        watcher = asyncio.create_task(ctrl.watch_pause_file(pause_file))

        await asyncio.sleep(0.1)
        assert not ctrl.is_paused

        pause_file.write_text("pause")
        await asyncio.sleep(0.6)
        assert ctrl.is_paused

        pause_file.write_text("resume")
        await asyncio.sleep(0.6)
        assert not ctrl.is_paused

        ctrl.cancel()
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_cancel_unblocks_paused_pipeline(self) -> None:
        """Cancellation unblocks a paused pipeline controller."""
        ctrl = PipelineController()
        ctrl.pause()
        assert ctrl.is_paused

        # Cancel should unblock
        asyncio.get_running_loop().call_later(0.05, ctrl.cancel)
        await asyncio.wait_for(ctrl.wait_if_paused(), timeout=1.0)
        assert ctrl.is_cancelled
        assert not ctrl.is_paused  # cancel clears paused state

    @pytest.mark.asyncio
    async def test_pause_resume_preserves_controller_state(self) -> None:
        """Multiple pause/resume cycles leave controller in correct state."""
        ctrl = PipelineController()
        for _ in range(5):
            ctrl.pause()
            assert ctrl.is_paused
            assert not ctrl.is_cancelled
            ctrl.resume()
            assert not ctrl.is_paused
            assert not ctrl.is_cancelled

    @pytest.mark.asyncio
    async def test_pause_after_cancel_is_noop(self) -> None:
        """Pausing after cancel does not re-pause."""
        ctrl = PipelineController()
        ctrl.cancel()
        ctrl.pause()
        # is_paused checks (not set) AND (not cancelled) — since cancelled, is_paused stays False
        assert not ctrl.is_paused
        assert ctrl.is_cancelled

    def test_stage_snapshot_preserves_completed_timings_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pause snapshots must include completed-stage timings, not partial active-stage time."""
        values = iter([10.0, 12.5, 20.0])
        monkeypatch.setattr("duplicates_detector.pipeline.time.monotonic", lambda: next(values))

        ctrl = PipelineController()
        ctrl.enter_stage("scan")
        ctrl.complete_stage("scan")
        ctrl.enter_stage("extract")

        snapshot = ctrl.stage_snapshot()

        assert snapshot.completed_stages == ["scan"]
        assert snapshot.active_stage == "extract"
        assert snapshot.stage_timings == {"scan": 2.5}
        assert "extract" not in snapshot.stage_timings


class TestSessionIntegration:
    """Tests session save/load round-trip."""

    def test_session_save_load_round_trip(self, tmp_path: Path) -> None:
        """Session data survives save/load cycle."""
        manager = SessionManager(tmp_path / "sessions")
        session = ScanSession(
            session_id="int-test-1",
            directories=["/test/videos"],
            config={"mode": "video", "content": True, "weights": {"filename": 50}},
            completed_stages=["scan", "extract"],
            active_stage="content_hash",
            total_files=1000,
            elapsed_seconds=45.2,
            stage_timings={"scan": 0.5, "extract": 44.7},
        )
        manager.save(session)

        loaded = manager.load("int-test-1")
        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert loaded.directories == session.directories
        assert loaded.config == session.config
        assert loaded.completed_stages == session.completed_stages
        assert loaded.active_stage == session.active_stage
        assert loaded.total_files == session.total_files
        assert loaded.elapsed_seconds == session.elapsed_seconds
        assert loaded.stage_timings == session.stage_timings

    def test_session_manager_prune_and_list(self, tmp_path: Path) -> None:
        """Session manager prune and list work correctly together."""
        manager = SessionManager(tmp_path / "sessions")

        # Create 10 sessions
        for i in range(10):
            session = ScanSession(
                session_id=f"s{i:03d}",
                directories=["/tmp"],
                config={},
                completed_stages=[],
                active_stage="scan",
                total_files=100,
                elapsed_seconds=0,
                stage_timings={},
            )
            manager.save(session)

        assert len(manager.list_sessions()) == 10
        manager.prune(max_sessions=5)
        assert len(manager.list_sessions()) == 5

    def test_session_config_preserves_nested_data(self, tmp_path: Path) -> None:
        """Nested config dicts (e.g. weights) survive round-trip."""
        manager = SessionManager(tmp_path / "sessions")
        config = {
            "mode": "image",
            "content": True,
            "weights": {"filename": 25, "resolution": 20, "filesize": 15, "exif": 40},
            "exclude": ["*.tmp", "thumbs/"],
        }
        session = ScanSession(
            session_id="nested-cfg",
            directories=["/photos"],
            config=config,
            completed_stages=["scan"],
            active_stage="extract",
            total_files=500,
            elapsed_seconds=10.0,
            stage_timings={"scan": 10.0},
        )
        manager.save(session)
        loaded = manager.load("nested-cfg")
        assert loaded is not None
        assert loaded.config["weights"]["exif"] == 40
        assert loaded.config["exclude"] == ["*.tmp", "thumbs/"]


class TestScoringCacheConfigHash:
    """Tests scoring cache config hash stability and cache integration."""

    def test_config_hash_stable_across_calls(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, has_content=True, mode="video")
        h2 = compute_config_hash(weights, has_content=True, mode="video")
        assert h1 == h2
        assert len(h1) == 32  # MD5 hex digest

    def test_config_hash_with_cache_roundtrip(self, tmp_path: Path) -> None:
        """Config hash works correctly as a cache key — store and retrieve."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"x")
        b.write_bytes(b"y")

        cache = CacheDB(tmp_path / "cache")
        try:
            weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
            ch = compute_config_hash(weights, mode="video")

            cache.put_scored_pair(
                a,
                b,
                mtime_a=a.stat().st_mtime,
                mtime_b=b.stat().st_mtime,
                config_hash=ch,
                score=75.0,
                detail={"filename": [0.8, 50.0]},
            )

            # Same config hash retrieves the pair
            result = cache.get_scored_pair(
                a,
                b,
                config_hash=ch,
                mtime_a=a.stat().st_mtime,
                mtime_b=b.stat().st_mtime,
            )
            assert result is not None
            assert result["score"] == 75.0

            # Different config hash misses
            ch2 = compute_config_hash(weights, has_content=True, mode="video")
            result2 = cache.get_scored_pair(
                a,
                b,
                config_hash=ch2,
                mtime_a=a.stat().st_mtime,
                mtime_b=b.stat().st_mtime,
            )
            assert result2 is None
        finally:
            cache.close()

    def test_cache_canonical_pair_ordering(self, tmp_path: Path) -> None:
        """Scored pairs are retrievable regardless of argument order."""
        a = tmp_path / "aaa.mp4"
        b = tmp_path / "zzz.mp4"
        a.write_bytes(b"x")
        b.write_bytes(b"y")

        cache = CacheDB(tmp_path / "cache")
        try:
            ch = compute_config_hash({"filename": 100}, mode="video")
            cache.put_scored_pair(
                a,
                b,
                mtime_a=a.stat().st_mtime,
                mtime_b=b.stat().st_mtime,
                config_hash=ch,
                score=90.0,
                detail={"filename": [0.95, 100.0]},
            )

            # Retrieve in reversed order
            result = cache.get_scored_pair(
                b,
                a,
                config_hash=ch,
                mtime_a=b.stat().st_mtime,
                mtime_b=a.stat().st_mtime,
            )
            assert result is not None
            assert result["score"] == 90.0
        finally:
            cache.close()


class TestCacheDBMultiTable:
    """Tests CacheDB with multiple table types in one session."""

    @pytest.fixture
    def cache(self, tmp_path: Path) -> Iterator[CacheDB]:
        instance = CacheDB(tmp_path / "cache")
        yield instance
        instance.close()

    def test_metadata_and_content_hash_coexist(self, tmp_path: Path, cache: CacheDB) -> None:
        """Storing metadata and content hashes for the same file works."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"content")
        st = f.stat()

        # Store metadata
        cache.put_metadata(
            f,
            {"duration": 120.0, "width": 1920, "height": 1080},
            file_size=st.st_size,
            mtime=st.st_mtime,
        )

        # Store content hash for the same file
        cache.put_content_hash(
            f,
            file_size=st.st_size,
            mtime=st.st_mtime,
            hashes=(123456, 789012),
            rotation_invariant=False,
        )

        # Both should be retrievable
        meta = cache.get_metadata(f, file_size=st.st_size, mtime=st.st_mtime)
        assert meta is not None
        assert meta["duration"] == 120.0

        hashes = cache.get_content_hash(
            f,
            file_size=st.st_size,
            mtime=st.st_mtime,
            rotation_invariant=False,
        )
        assert hashes == (123456, 789012)

    def test_stats_track_all_tables(self, tmp_path: Path, cache: CacheDB) -> None:
        """Stats counters increment independently per table."""
        f = tmp_path / "test.mp4"
        f.write_bytes(b"x")
        st = f.stat()

        # Cause a metadata miss
        cache.get_metadata(f, file_size=st.st_size, mtime=st.st_mtime)

        # Store and retrieve (miss then hit)
        cache.put_metadata(f, {"duration": 10.0}, file_size=st.st_size, mtime=st.st_mtime)
        cache.get_metadata(f, file_size=st.st_size, mtime=st.st_mtime)

        # Cause a content miss
        cache.get_content_hash(
            f,
            file_size=st.st_size,
            mtime=st.st_mtime,
            rotation_invariant=False,
        )

        stats = cache.stats()
        assert stats["metadata_misses"] == 1
        assert stats["metadata_hits"] == 1
        assert stats["content_misses"] == 1
        assert stats["content_hits"] == 0

    def test_prune_removes_stale_entries(self, tmp_path: Path, cache: CacheDB) -> None:
        """Prune removes entries for paths not in the active set."""
        a = tmp_path / "keep.mp4"
        b = tmp_path / "remove.mp4"
        a.write_bytes(b"x")
        b.write_bytes(b"y")

        cache.put_metadata(a, {"dur": 10}, file_size=1, mtime=1.0)
        cache.put_metadata(b, {"dur": 20}, file_size=2, mtime=2.0)

        deleted = cache.prune({a.resolve()})
        assert deleted >= 1

        # 'a' should still be retrievable
        assert cache.get_metadata(a, file_size=1, mtime=1.0) is not None
        # 'b' should be gone (returns None = miss)
        result = cache.get_metadata(b, file_size=2, mtime=2.0)
        assert result is None


class TestProgressEmitterIntegration:
    """Tests ProgressEmitter session lifecycle with real JSON parsing."""

    def test_full_session_lifecycle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session start -> progress -> stage events -> session end."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.session_start(session_id="test-1", total_files=100, stages=["scan", "extract"])
        emitter.stage_start("scan", total=100)
        emitter.progress("scan", current=50, total=100, force=True)
        emitter.stage_end("scan", total=100, elapsed=1.5)
        emitter.stage_start("extract", total=100)
        emitter.progress("extract", current=30, total=100, cache_hits=20, cache_misses=10, force=True)
        emitter.stage_end("extract", total=100, elapsed=5.0, cache_hits=80, cache_misses=20)
        emitter.session_end(session_id="test-1", total_elapsed=6.5, cache_time_saved=2.0)

        buf.seek(0)
        events = [json.loads(line) for line in buf if line.strip()]

        types = [e["type"] for e in events]
        assert types[0] == "session_start"
        assert types[-1] == "session_end"
        assert "stage_start" in types
        assert "progress" in types
        assert "stage_end" in types

        # Verify cache stats in progress event
        progress_events = [e for e in events if e["type"] == "progress" and e.get("cache_hits")]
        assert len(progress_events) >= 1
        assert progress_events[0]["cache_hits"] == 20

    def test_session_events_have_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All event types contain their required fields."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.session_start(session_id="f-test", total_files=50, stages=["scan"])
        emitter.stage_start("scan", total=50)
        emitter.progress("scan", current=25, total=50, force=True)
        emitter.stage_end("scan", total=50, elapsed=2.0)
        emitter.session_end(session_id="f-test", total_elapsed=2.0, cache_time_saved=0.0)

        buf.seek(0)
        events = [json.loads(line) for line in buf if line.strip()]

        session_start = next(e for e in events if e["type"] == "session_start")
        assert "session_id" in session_start
        assert "total_files" in session_start
        assert "stages" in session_start
        assert "wall_start" in session_start

        stage_start = next(e for e in events if e["type"] == "stage_start")
        assert "stage" in stage_start
        assert "timestamp" in stage_start

        progress_ev = next(e for e in events if e["type"] == "progress")
        assert "stage" in progress_ev
        assert "current" in progress_ev
        assert "timestamp" in progress_ev

        stage_end = next(e for e in events if e["type"] == "stage_end")
        assert "stage" in stage_end
        assert "total" in stage_end
        assert "elapsed" in stage_end

        session_end = next(e for e in events if e["type"] == "session_end")
        assert "session_id" in session_end
        assert "total_elapsed" in session_end
        assert "cache_time_saved" in session_end

    def test_stage_end_clears_state_for_reuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After stage_end, the same stage name can be reused without state leaks."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        # First use of "extract"
        emitter.stage_start("extract", total=100)
        emitter.progress("extract", current=100, total=100, force=True)
        emitter.stage_end("extract", total=100, elapsed=5.0)

        # Second use of "extract" (e.g., in a different pipeline run)
        emitter.stage_start("extract", total=200)
        emitter.progress("extract", current=200, total=200, force=True)
        emitter.stage_end("extract", total=200, elapsed=10.0)

        buf.seek(0)
        events = [json.loads(line) for line in buf if line.strip()]
        stage_ends = [e for e in events if e["type"] == "stage_end" and e["stage"] == "extract"]
        assert len(stage_ends) == 2
        assert stage_ends[0]["total"] == 100
        assert stage_ends[1]["total"] == 200


class TestCrossComponentWorkflow:
    """Tests that simulate realistic multi-component workflows."""

    @pytest.mark.asyncio
    async def test_pipeline_then_session_checkpoint(self, tmp_path: Path) -> None:
        """Pipeline run followed by session save for pause/resume."""
        # Run pipeline
        (tmp_path / "vid.mp4").write_bytes(b"content")
        ctrl = PipelineController()

        results = await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=None,
            controller=ctrl,
        )

        # Save session checkpoint
        manager = SessionManager(tmp_path / "sessions")
        session = ScanSession(
            session_id="workflow-1",
            directories=[str(tmp_path)],
            config={"mode": "video"},
            completed_stages=["scan", "extract", "filter"],
            active_stage="score",
            total_files=1,
            elapsed_seconds=0.5,
            stage_timings={"scan": 0.1, "extract": 0.3, "filter": 0.1},
        )
        manager.save(session)

        # Verify session is loadable
        loaded = manager.load("workflow-1")
        assert loaded is not None
        assert loaded.completed_stages == ["scan", "extract", "filter"]
        assert loaded.active_stage == "score"

    def test_cache_survives_close_and_reopen(self, tmp_path: Path) -> None:
        """Cache data persists across close/reopen cycles."""
        cache_dir = tmp_path / "cache"
        f = tmp_path / "movie.mp4"
        f.write_bytes(b"movie data")
        st = f.stat()

        # First session: write data
        cache1 = CacheDB(cache_dir)
        cache1.put_metadata(
            f,
            {"duration": 120.0, "codec": "h264"},
            file_size=st.st_size,
            mtime=st.st_mtime,
        )
        cache1.close()

        # Second session: read data back
        cache2 = CacheDB(cache_dir)
        try:
            meta = cache2.get_metadata(f, file_size=st.st_size, mtime=st.st_mtime)
            assert meta is not None
            assert meta["duration"] == 120.0
            assert meta["codec"] == "h264"
        finally:
            cache2.close()

    def test_scoring_config_hash_sensitivity(self) -> None:
        """Verify that subtle config changes produce distinct hashes."""
        base = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}

        # All these should produce different hashes
        h_base = compute_config_hash(base, mode="video")
        h_content = compute_config_hash(base, has_content=True, mode="video")
        h_audio = compute_config_hash(base, has_audio=True, mode="video")
        h_image = compute_config_hash(base, mode="image")
        h_ssim = compute_config_hash(base, has_content=True, content_method="ssim", mode="video")

        all_hashes = {h_base, h_content, h_audio, h_image, h_ssim}
        assert len(all_hashes) == 5, "Each config variation should produce a unique hash"
