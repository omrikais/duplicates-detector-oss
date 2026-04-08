from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import replace
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.pipeline import (
    PipelineController,
    PipelineResult,
    _CANONICAL_STAGES,
    _TaskGroup,
    audio_stage,
    compute_stage_list,
    extract_stage,
    filter_stage,
    hash_stage,
    queue_iter,
    run_pipeline,
    scan_stage,
    score_stage,
)
from duplicates_detector.config import Mode
from duplicates_detector.content import _synthetic_content_hash
from duplicates_detector.scorer import ScoredPair


class TestPipelineController:
    @pytest.mark.asyncio
    async def test_pause_blocks(self) -> None:
        ctrl = PipelineController()
        ctrl.pause()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ctrl.wait_if_paused(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_resume_unblocks(self) -> None:
        ctrl = PipelineController()
        ctrl.pause()
        asyncio.get_running_loop().call_later(0.05, ctrl.resume)
        await asyncio.wait_for(ctrl.wait_if_paused(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_cancel_unblocks_paused(self) -> None:
        ctrl = PipelineController()
        ctrl.pause()
        asyncio.get_running_loop().call_later(0.05, ctrl.cancel)
        await asyncio.wait_for(ctrl.wait_if_paused(), timeout=1.0)
        assert ctrl.is_cancelled

    def test_blocking_wait_unblocks_on_resume(self) -> None:
        ctrl = PipelineController()
        ctrl.pause()
        released = threading.Event()

        def _waiter() -> None:
            ctrl.wait_if_paused_blocking()
            released.set()

        thread = threading.Thread(target=_waiter)
        thread.start()
        time.sleep(0.05)
        assert not released.is_set()

        ctrl.resume()
        thread.join(timeout=1.0)
        assert released.is_set()


class TestPauseFileWatcher:
    @pytest.mark.asyncio
    async def test_pause_file_watcher(self, tmp_path: Path) -> None:
        pause_file = tmp_path / "pause_ctl"
        pause_file.write_text("resume")
        ctrl = PipelineController()

        watcher = asyncio.create_task(ctrl.watch_pause_file(pause_file))
        await asyncio.sleep(0.1)
        assert not ctrl.is_paused

        pause_file.write_text("pause")
        await asyncio.sleep(0.6)  # wait for poll
        assert ctrl.is_paused

        pause_file.write_text("resume")
        await asyncio.sleep(0.6)
        assert not ctrl.is_paused

        ctrl.cancel()  # stop watcher
        await asyncio.sleep(0.1)
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_pause_file_missing(self, tmp_path: Path) -> None:
        """Watcher handles missing file gracefully."""
        pause_file = tmp_path / "nonexistent"
        ctrl = PipelineController()

        watcher = asyncio.create_task(ctrl.watch_pause_file(pause_file))
        await asyncio.sleep(0.2)
        assert not ctrl.is_paused  # Should not crash

        ctrl.cancel()
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


class TestScanStage:
    @pytest.mark.asyncio
    async def test_scan_yields_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp4").write_bytes(b"x")
        (tmp_path / "b.mp4").write_bytes(b"x")
        out_q: asyncio.Queue[Path | None] = asyncio.Queue()
        ctrl = PipelineController()
        progress = MagicMock()
        config = MagicMock()
        config.directories = [tmp_path]
        config.recursive = True
        config.extensions = frozenset({".mp4"})
        config.exclude = None

        await scan_stage(config, out_q, progress, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is None:
                break
            items.append(item)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_scan_stage_streams(self, tmp_path: Path) -> None:
        """Verify scan_stage puts items into queue one at a time (streaming)."""
        for i in range(10):
            (tmp_path / f"file{i:02d}.mp4").write_bytes(b"x")

        out_q: asyncio.Queue[Path | None] = asyncio.Queue(maxsize=5)
        ctrl = PipelineController()
        config = MagicMock()
        config.directories = [tmp_path]
        config.recursive = True
        config.extensions = frozenset({".mp4"})
        config.exclude = None

        # Run scan in background; with maxsize=5, it will block after 5 items
        # if not consumed. We consume items one at a time to verify streaming.
        received: list[Path] = []

        async def _consume() -> None:
            async for item in queue_iter(out_q):
                received.append(item)
                await asyncio.sleep(0.01)  # simulate slow consumer

        async with _TaskGroup() as tg:
            tg.create_task(scan_stage(config, out_q, None, ctrl))
            tg.create_task(_consume())

        assert len(received) == 10

    @pytest.mark.asyncio
    async def test_scan_stage_passes_pause_waiter_to_scanner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """scan_stage should hand scanner a blocking pause waiter for discovery."""
        wait_points: list[str] = []

        def _fake_scan_files_iter(*_args, **kwargs):
            pause_waiter = kwargs.get("pause_waiter")
            assert pause_waiter is not None
            wait_points.append("before")
            pause_waiter()
            wait_points.append("after")
            yield Path("/tmp/fake-a.mp4")

        import duplicates_detector.scanner

        monkeypatch.setattr(duplicates_detector.scanner, "_scan_files_iter", _fake_scan_files_iter)

        out_q: asyncio.Queue[Path | None] = asyncio.Queue()
        ctrl = PipelineController()
        ctrl.pause()
        asyncio.get_running_loop().call_later(0.05, ctrl.resume)
        config = MagicMock()
        config.directories = [Path("/tmp")]
        config.recursive = True
        config.extensions = frozenset({".mp4"})
        config.exclude = None

        await asyncio.wait_for(scan_stage(config, out_q, None, ctrl), timeout=1.0)

        assert wait_points == ["before", "after"]


class TestSentinelPropagation:
    @pytest.mark.asyncio
    async def test_filter_propagates_sentinel(self) -> None:
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = MagicMock()
        config = MagicMock()
        config.min_size = None
        config.max_size = None
        config.min_resolution = None
        config.max_resolution = None
        config.min_duration = None
        config.max_duration = None
        config.min_bitrate = None
        config.max_bitrate = None
        config.codecs = None

        await in_q.put(None)  # sentinel immediately
        await filter_stage(in_q, out_q, config, progress, ctrl)

        sentinel = await out_q.get()
        assert sentinel is None


class TestExtractStageConcurrent:
    @pytest.mark.asyncio
    async def test_extract_stage_concurrent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify extract_stage achieves concurrency > 1."""
        peak_concurrent = 0
        active_count = 0
        lock = threading.Lock()

        def _slow_extract(path, cache, mode, **kwargs):
            nonlocal peak_concurrent, active_count
            with lock:
                active_count += 1
                if active_count > peak_concurrent:
                    peak_concurrent = active_count
            time.sleep(0.05)  # simulate I/O
            with lock:
                active_count -= 1
            # Return a mock metadata object
            meta = MagicMock()
            meta.path = path
            return meta

        monkeypatch.setattr("duplicates_detector.pipeline._extract_one_with_cache_import", None, raising=False)
        import duplicates_detector.metadata

        monkeypatch.setattr(duplicates_detector.metadata, "_extract_one_with_cache", _slow_extract)

        in_q: asyncio.Queue[Path | None] = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.mode = "video"
        config.workers = 4

        # Feed 8 paths
        for i in range(8):
            await in_q.put(Path(f"/fake/file{i}.mp4"))
        await in_q.put(None)

        await extract_stage(in_q, out_q, None, config, None, ctrl)

        # Collect results (excluding sentinel)
        results = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                results.append(item)

        assert len(results) == 8
        assert peak_concurrent > 1, f"Expected concurrent execution, but peak was {peak_concurrent}"


class TestScoreStageFromQueue:
    @pytest.mark.asyncio
    async def test_score_stage_from_queue(self, tmp_path: Path) -> None:
        """Put metadata items + sentinel into queue, verify score_stage returns scored pairs."""
        from duplicates_detector.metadata import VideoMetadata

        in_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.mode = "video"
        config.workers = 1
        config.comparators = None
        config.threshold = 50.0

        # Create files with same name pattern to trigger filename match
        a = tmp_path / "video_test.mp4"
        b = tmp_path / "video_test_copy.mp4"
        a.write_bytes(b"x" * 1000)
        b.write_bytes(b"y" * 1000)

        meta_a = VideoMetadata(
            path=a,
            filename="video_test",
            duration=60.0,
            width=1920,
            height=1080,
            file_size=a.stat().st_size,
        )
        meta_b = VideoMetadata(
            path=b,
            filename="video_test_copy",
            duration=60.0,
            width=1920,
            height=1080,
            file_size=b.stat().st_size,
        )

        await in_q.put(meta_a)
        await in_q.put(meta_b)
        await in_q.put(None)

        # score_stage should accumulate and score
        result = await score_stage(in_q, None, config, None, ctrl)
        assert isinstance(result, list)
        # With matching durations and similar filenames, we should get a scored pair
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_score_stage_blocks_while_paused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """score_stage should stop inside scorer work until the controller resumes."""
        in_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.mode = "video"
        config.workers = 1
        config.comparators = None
        config.threshold = 50.0

        scoring_started = threading.Event()
        scoring_resumed = threading.Event()

        def _fake_find_duplicates(items, *, stats=None, pause_waiter=None, **kwargs):
            if stats is not None:
                stats["total_pairs_scored"] = 0
            scoring_started.set()
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and not ctrl.is_paused:
                time.sleep(0.01)
            if pause_waiter is not None:
                pause_waiter()
            scoring_resumed.set()
            return []

        import duplicates_detector.scorer

        monkeypatch.setattr(duplicates_detector.scorer, "find_duplicates", _fake_find_duplicates)

        await in_q.put(MagicMock())
        await in_q.put(MagicMock())
        await in_q.put(None)

        task = asyncio.create_task(score_stage(in_q, None, config, None, ctrl))
        assert await asyncio.to_thread(scoring_started.wait, 1.0)

        ctrl.pause()
        await asyncio.sleep(0.2)
        assert not task.done()
        assert not scoring_resumed.is_set()

        ctrl.resume()
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result == []
        assert scoring_resumed.is_set()


class TestAudioStage:
    @pytest.mark.asyncio
    async def test_audio_stage_passthrough(self) -> None:
        """Audio stage passes items through when audio is disabled."""
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.audio = False

        meta = MagicMock()
        await in_q.put(meta)
        await in_q.put(None)

        await audio_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 1
        assert items[0] is meta

    @pytest.mark.asyncio
    async def test_audio_stage_disabled_stays_internal(self) -> None:
        """Disabled audio stage passes through without external stage events or tracking."""
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock()
        config.audio = False
        config.mode = "video"
        config.content = False
        config.content_method = "phash"
        stats: dict[str, object] = {}

        meta = MagicMock()
        await in_q.put(meta)
        await in_q.put(None)

        await audio_stage(in_q, out_q, None, config, progress, ctrl, _stats=stats)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert items == [meta]
        progress.stage_start.assert_not_called()
        progress.progress.assert_not_called()
        progress.stage_end.assert_not_called()
        assert ctrl.active_stage is None
        assert ctrl.completed_stages == []
        assert "audio_fingerprint_count" not in stats
        assert "audio_fingerprint_time" not in stats


class TestHashStagePassthrough:
    @pytest.mark.asyncio
    async def test_hash_stage_passthrough(self) -> None:
        """Hash stage passes items through when content is disabled."""
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = False

        meta = MagicMock()
        await in_q.put(meta)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 1
        assert items[0] is meta

    @pytest.mark.asyncio
    async def test_hash_stage_disabled_stays_internal(self) -> None:
        """Disabled content-hash stage passes through without external stage events or tracking."""
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock()
        config.content = False
        config.audio = False
        config.mode = "video"
        config.content_method = "phash"
        stats: dict[str, object] = {}

        meta = MagicMock()
        await in_q.put(meta)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, progress, ctrl, _stats=stats)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert items == [meta]
        progress.stage_start.assert_not_called()
        progress.progress.assert_not_called()
        progress.stage_end.assert_not_called()
        assert ctrl.active_stage is None
        assert ctrl.completed_stages == []
        assert "content_hash_count" not in stats
        assert "content_hash_time" not in stats

    @pytest.mark.asyncio
    async def test_passthrough_computes_pre_hash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When content=False, hash_stage still computes pre-hashes for byte-identical detection."""
        p = tmp_path / "a.mp4"
        p.write_bytes(b"test content for pre hash")
        st = p.stat()
        meta = VideoMetadata(
            path=p,
            filename="a",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st.st_size,
            mtime=st.st_mtime,
        )

        pre_hash_calls: list[Path] = []

        def fake_pre_hash(m, cache):
            pre_hash_calls.append(m.path)
            return replace(m, pre_hash="fakehash123")

        # hash_stage imports _pre_hash_one_with_cache inside the function body
        # from duplicates_detector.content, so we patch the source module.
        monkeypatch.setattr("duplicates_detector.content._pre_hash_one_with_cache", fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = False
        config.no_pre_hash = False
        config.workers = 1

        await in_q.put(meta)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 1
        assert items[0].pre_hash == "fakehash123"
        assert len(pre_hash_calls) == 1

    @pytest.mark.asyncio
    async def test_passthrough_skips_pre_hash_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When content=False and no_pre_hash=True, hash_stage is pure pass-through."""
        p = tmp_path / "a.mp4"
        p.write_bytes(b"test content")
        st = p.stat()
        meta = VideoMetadata(
            path=p,
            filename="a",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st.st_size,
            mtime=st.st_mtime,
        )

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = False
        config.no_pre_hash = True

        await in_q.put(meta)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 1
        assert items[0].pre_hash is None


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_basic_pipeline(self, tmp_path: Path) -> None:
        """run_pipeline returns PipelineResult with pairs list."""
        (tmp_path / "a.mp4").write_bytes(b"x")
        (tmp_path / "b.mp4").write_bytes(b"x")

        ctrl = PipelineController()
        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.progress = MagicMock()
        progress.stage_end = MagicMock()

        result = await run_pipeline(
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
        assert isinstance(result, PipelineResult)
        assert isinstance(result.pairs, list)

    @pytest.mark.asyncio
    async def test_pipeline_cancel(self, tmp_path: Path) -> None:
        """Cancelled pipeline returns PipelineResult with partial/empty pairs."""
        for i in range(100):
            (tmp_path / f"file{i}.mp4").write_bytes(b"x")

        ctrl = PipelineController()
        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.progress = MagicMock()
        progress.stage_end = MagicMock()

        # Cancel immediately
        ctrl.cancel()

        result = await run_pipeline(
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
        assert isinstance(result, PipelineResult)
        assert isinstance(result.pairs, list)

    @pytest.mark.asyncio
    async def test_pipeline_can_use_pre_scanned_paths(self, tmp_path: Path) -> None:
        """Providing pre_scanned_paths skips the pipeline's internal scan stage."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.write_bytes(b"x")

        ctrl = PipelineController()
        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.progress = MagicMock()
        progress.stage_end = MagicMock()

        result = await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=progress,
            controller=ctrl,
            pre_scanned_paths=files,
            seeded_scan_time=1.25,
            seeded_discovered_paths=set(files),
        )

        start_stages = [call.args[0] for call in progress.stage_start.call_args_list]
        assert "scan" not in start_stages
        assert result.files_scanned == len(files)
        assert result.scan_time == pytest.approx(1.25)
        assert result.discovered_paths == set(files)


class TestRunPipelineFull:
    @pytest.mark.asyncio
    async def test_run_pipeline_default_emits_only_advertised_stages(self, tmp_path: Path) -> None:
        """Default async pipeline keeps disabled pass-through stages out of lifecycle events."""
        # Create files
        (tmp_path / "a.mp4").write_bytes(b"content_a")
        (tmp_path / "b.mp4").write_bytes(b"content_b")

        ctrl = PipelineController()
        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.progress = MagicMock()
        progress.stage_end = MagicMock()

        result = await run_pipeline(
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
        assert isinstance(result, PipelineResult)
        assert isinstance(result.pairs, list)
        assert isinstance(result.stage_timings, dict)
        assert isinstance(result.stage_counts, dict)

        # Default pipeline emits only the authoritative stages.
        start_stages = [call.args[0] for call in progress.stage_start.call_args_list]
        end_stages = [call.args[0] for call in progress.stage_end.call_args_list]

        for stage_name in ("scan", "extract", "filter", "score"):
            assert stage_name in start_stages, f"{stage_name} missing from stage_start"
            assert stage_name in end_stages, f"{stage_name} missing from stage_end"
        assert "content_hash" not in start_stages
        assert "content_hash" not in end_stages
        assert "audio_fingerprint" not in start_stages
        assert "audio_fingerprint" not in end_stages

    @pytest.mark.asyncio
    async def test_run_pipeline_content_enabled_emits_content_hash(self, tmp_path: Path) -> None:
        """Enabling content hashing adds the content_hash lifecycle stage."""
        (tmp_path / "a.mp4").write_bytes(b"content_a")
        (tmp_path / "b.mp4").write_bytes(b"content_b")

        ctrl = PipelineController()
        progress = _make_progress_mock()

        result = await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=progress,
            controller=ctrl,
            content=True,
        )

        assert isinstance(result, PipelineResult)
        start_stages = [call.args[0] for call in progress.stage_start.call_args_list]
        end_stages = [call.args[0] for call in progress.stage_end.call_args_list]
        assert "content_hash" in start_stages
        assert "content_hash" in end_stages

    @pytest.mark.asyncio
    async def test_run_pipeline_audio_enabled_emits_audio_fingerprint(self, tmp_path: Path) -> None:
        """Enabling audio fingerprinting adds the audio_fingerprint lifecycle stage."""
        (tmp_path / "a.mp4").write_bytes(b"content_a")
        (tmp_path / "b.mp4").write_bytes(b"content_b")

        ctrl = PipelineController()
        progress = _make_progress_mock()

        result = await run_pipeline(
            directories=[tmp_path],
            recursive=True,
            extensions=frozenset({".mp4"}),
            exclude=None,
            mode="video",
            workers=1,
            cache=None,
            progress=progress,
            controller=ctrl,
            audio=True,
        )

        assert isinstance(result, PipelineResult)
        start_stages = [call.args[0] for call in progress.stage_start.call_args_list]
        end_stages = [call.args[0] for call in progress.stage_end.call_args_list]
        assert "audio_fingerprint" in start_stages
        assert "audio_fingerprint" in end_stages


class TestTaskGroupCompat:
    @pytest.mark.asyncio
    async def test_taskgroup_runs_concurrent_tasks(self) -> None:
        """All tasks created inside _TaskGroup run to completion."""
        results: list[int] = []

        async def worker(value: int) -> None:
            await asyncio.sleep(0.01)
            results.append(value)

        async with _TaskGroup() as tg:
            tg.create_task(worker(1))
            tg.create_task(worker(2))
            tg.create_task(worker(3))

        assert sorted(results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_taskgroup_propagates_exception(self) -> None:
        """An exception in one task propagates out and cancels siblings."""
        canary = asyncio.Event()

        async def good_task() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                canary.set()
                raise

        async def bad_task() -> None:
            raise ValueError("boom")

        # On 3.11+ asyncio.TaskGroup wraps in ExceptionGroup; our polyfill re-raises directly.
        _expected: tuple[type[BaseException], ...] = (ValueError,)
        if sys.version_info >= (3, 11):
            _expected = (ValueError, ExceptionGroup)  # type: ignore[assignment]  # noqa: F821

        with pytest.raises(_expected):
            async with _TaskGroup() as tg:
                tg.create_task(good_task())
                tg.create_task(bad_task())

        # The good task should have been cancelled
        assert canary.is_set()


# ---------------------------------------------------------------------------
# Cache stats in progress events
# ---------------------------------------------------------------------------


def _make_cache_mock(
    metadata_hits: int = 0,
    metadata_misses: int = 0,
    content_hits: int = 0,
    content_misses: int = 0,
    audio_hits: int = 0,
    audio_misses: int = 0,
) -> MagicMock:
    """Create a cache mock whose ``.stats()`` returns the given counters."""
    cache = MagicMock()
    cache.stats.return_value = {
        "metadata_hits": metadata_hits,
        "metadata_misses": metadata_misses,
        "content_hits": content_hits,
        "content_misses": content_misses,
        "audio_hits": audio_hits,
        "audio_misses": audio_misses,
    }
    return cache


def _make_progress_mock() -> MagicMock:
    progress = MagicMock()
    progress.stage_start = MagicMock()
    progress.progress = MagicMock()
    progress.stage_end = MagicMock()
    return progress


class TestExtractStageCacheStats:
    @pytest.mark.asyncio
    async def test_extract_stage_progress_has_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """extract_stage progress events should include cache_hits and cache_misses."""

        def _fake_extract(path, cache, mode, **kwargs):
            meta = MagicMock()
            meta.path = path
            return meta

        import duplicates_detector.metadata

        monkeypatch.setattr(duplicates_detector.metadata, "_extract_one_with_cache", _fake_extract)

        in_q: asyncio.Queue[Path | None] = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        cache = _make_cache_mock(metadata_hits=1, metadata_misses=1)
        config = MagicMock(workers=1, mode="video")

        await in_q.put(Path("/fake/a.mp4"))
        await in_q.put(Path("/fake/b.mp4"))
        await in_q.put(None)

        await extract_stage(in_q, out_q, cache, config, progress, ctrl)

        # Check progress() calls include cache_hits/cache_misses kwargs
        calls_with_cache = [
            c
            for c in progress.progress.call_args_list
            if c.kwargs.get("cache_hits") is not None or c.kwargs.get("cache_misses") is not None
        ]
        assert len(calls_with_cache) > 0, "No progress events with cache stats found"

    @pytest.mark.asyncio
    async def test_extract_stage_end_has_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """extract_stage stage_end event should include cache_hits and cache_misses."""

        def _fake_extract(path, cache, mode, **kwargs):
            meta = MagicMock()
            meta.path = path
            return meta

        import duplicates_detector.metadata

        monkeypatch.setattr(duplicates_detector.metadata, "_extract_one_with_cache", _fake_extract)

        in_q: asyncio.Queue[Path | None] = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        cache = _make_cache_mock(metadata_hits=3, metadata_misses=2)
        config = MagicMock(workers=1, mode="video")

        await in_q.put(Path("/fake/a.mp4"))
        await in_q.put(None)

        await extract_stage(in_q, out_q, cache, config, progress, ctrl)

        # stage_end should include cache_hits and cache_misses as extra kwargs
        assert progress.stage_end.call_count == 1
        end_kwargs = progress.stage_end.call_args.kwargs
        assert "cache_hits" in end_kwargs, f"cache_hits missing from stage_end kwargs: {end_kwargs}"
        assert "cache_misses" in end_kwargs, f"cache_misses missing from stage_end kwargs: {end_kwargs}"
        assert end_kwargs["cache_hits"] == 3
        assert end_kwargs["cache_misses"] == 2


class TestHashStageCacheStats:
    @pytest.mark.asyncio
    async def test_hash_stage_progress_has_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hash_stage progress events should include cache_hits and cache_misses when content=True."""

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            return m  # pass through unchanged

        def _fake_pre_hash(m, cache):
            return m  # pass through unchanged

        import duplicates_detector.content

        monkeypatch.setattr(duplicates_detector.content, "_hash_one_with_cache", _fake_hash)
        monkeypatch.setattr(duplicates_detector.content, "_pre_hash_one_with_cache", _fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        cache = _make_cache_mock(content_hits=2, content_misses=1)
        config = MagicMock(
            content=True,
            workers=1,
            mode="video",
            rotation_invariant=False,
        )

        await in_q.put(MagicMock())
        await in_q.put(MagicMock())
        await in_q.put(None)

        await hash_stage(in_q, out_q, cache, config, progress, ctrl)

        # Check progress() calls include cache_hits/cache_misses kwargs
        calls_with_cache = [
            c
            for c in progress.progress.call_args_list
            if c.kwargs.get("cache_hits") is not None or c.kwargs.get("cache_misses") is not None
        ]
        assert len(calls_with_cache) > 0, "No progress events with cache stats found"

    @pytest.mark.asyncio
    async def test_hash_stage_end_has_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hash_stage stage_end event should include cache_hits and cache_misses."""

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            return m

        def _fake_pre_hash(m, cache):
            return m

        import duplicates_detector.content

        monkeypatch.setattr(duplicates_detector.content, "_hash_one_with_cache", _fake_hash)
        monkeypatch.setattr(duplicates_detector.content, "_pre_hash_one_with_cache", _fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        cache = _make_cache_mock(content_hits=5, content_misses=3)
        config = MagicMock(
            content=True,
            workers=1,
            mode="video",
            rotation_invariant=False,
        )

        await in_q.put(MagicMock())
        await in_q.put(None)

        await hash_stage(in_q, out_q, cache, config, progress, ctrl)

        assert progress.stage_end.call_count == 1
        end_kwargs = progress.stage_end.call_args.kwargs
        assert "cache_hits" in end_kwargs, f"cache_hits missing from stage_end kwargs: {end_kwargs}"
        assert "cache_misses" in end_kwargs, f"cache_misses missing from stage_end kwargs: {end_kwargs}"
        assert end_kwargs["cache_hits"] == 5
        assert end_kwargs["cache_misses"] == 3

    @pytest.mark.asyncio
    async def test_hash_stage_final_progress_reports_definitive_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hash_stage should include the final item count in its forced progress event."""

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            return m

        def _fake_pre_hash(m, cache):
            return m

        import duplicates_detector.content

        monkeypatch.setattr(duplicates_detector.content, "_hash_one_with_cache", _fake_hash)
        monkeypatch.setattr(duplicates_detector.content, "_pre_hash_one_with_cache", _fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock(
            content=True,
            workers=1,
            mode="video",
            rotation_invariant=False,
        )

        await in_q.put(MagicMock())
        await in_q.put(MagicMock())
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, progress, ctrl)

        final_progress = progress.progress.call_args_list[-1]
        assert final_progress.kwargs["force"] is True
        assert final_progress.kwargs["total"] == 2

    @pytest.mark.asyncio
    async def test_hash_stage_passthrough_no_cache_stats(self) -> None:
        """hash_stage pass-through mode stays internal when content hashing is disabled."""
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock(content=False)

        await in_q.put(MagicMock())
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, progress, ctrl)

        progress.stage_start.assert_not_called()
        progress.progress.assert_not_called()
        progress.stage_end.assert_not_called()


class TestAudioStageCacheStats:
    @pytest.mark.asyncio
    async def test_audio_stage_progress_has_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """audio_stage progress events should include cache_hits and cache_misses when audio=True."""

        def _fake_fingerprint(meta, cache):
            return meta

        import duplicates_detector.audio

        monkeypatch.setattr(duplicates_detector.audio, "_fingerprint_one_with_cache", _fake_fingerprint)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        cache = _make_cache_mock(audio_hits=4, audio_misses=2)
        config = MagicMock(audio=True, workers=1)

        await in_q.put(MagicMock())
        await in_q.put(MagicMock())
        await in_q.put(None)

        await audio_stage(in_q, out_q, cache, config, progress, ctrl)

        calls_with_cache = [
            c
            for c in progress.progress.call_args_list
            if c.kwargs.get("cache_hits") is not None or c.kwargs.get("cache_misses") is not None
        ]
        assert len(calls_with_cache) > 0, "No progress events with cache stats found"

    @pytest.mark.asyncio
    async def test_audio_stage_end_has_cache_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """audio_stage stage_end event should include cache_hits and cache_misses."""

        def _fake_fingerprint(meta, cache):
            return meta

        import duplicates_detector.audio

        monkeypatch.setattr(duplicates_detector.audio, "_fingerprint_one_with_cache", _fake_fingerprint)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        cache = _make_cache_mock(audio_hits=7, audio_misses=1)
        config = MagicMock(audio=True, workers=1)

        await in_q.put(MagicMock())
        await in_q.put(None)

        await audio_stage(in_q, out_q, cache, config, progress, ctrl)

        assert progress.stage_end.call_count == 1
        end_kwargs = progress.stage_end.call_args.kwargs
        assert "cache_hits" in end_kwargs, f"cache_hits missing from stage_end kwargs: {end_kwargs}"
        assert "cache_misses" in end_kwargs, f"cache_misses missing from stage_end kwargs: {end_kwargs}"
        assert end_kwargs["cache_hits"] == 7
        assert end_kwargs["cache_misses"] == 1

    @pytest.mark.asyncio
    async def test_audio_stage_final_progress_reports_definitive_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """audio_stage should include the final item count in its forced progress event."""

        def _fake_fingerprint(meta, cache):
            return meta

        import duplicates_detector.audio

        monkeypatch.setattr(duplicates_detector.audio, "_fingerprint_one_with_cache", _fake_fingerprint)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock(audio=True, workers=1)

        await in_q.put(MagicMock())
        await in_q.put(MagicMock())
        await in_q.put(None)

        await audio_stage(in_q, out_q, None, config, progress, ctrl)

        final_progress = progress.progress.call_args_list[-1]
        assert final_progress.kwargs["force"] is True
        assert final_progress.kwargs["total"] == 2


# ---------------------------------------------------------------------------
# Stage tracking + on_pause / on_resume callbacks
# ---------------------------------------------------------------------------


class TestStageTracking:
    def test_enter_stage_sets_active(self) -> None:
        ctrl = PipelineController()
        ctrl.enter_stage("extract")
        assert ctrl.active_stage == "extract"

    def test_complete_stage_adds_to_completed(self) -> None:
        ctrl = PipelineController()
        ctrl.enter_stage("scan")
        ctrl.complete_stage("scan")
        assert "scan" in ctrl.completed_stages
        assert ctrl.active_stage is None

    def test_completed_stages_returns_copy(self) -> None:
        ctrl = PipelineController()
        ctrl.complete_stage("scan")
        stages = ctrl.completed_stages
        stages.append("bogus")
        assert "bogus" not in ctrl.completed_stages

    def test_complete_stage_does_not_clear_different_active(self) -> None:
        ctrl = PipelineController()
        ctrl.enter_stage("extract")
        ctrl.complete_stage("scan")
        assert ctrl.active_stage == "extract"


class TestOnPauseCallback:
    def test_on_pause_fires(self) -> None:
        ctrl = PipelineController()
        called = []
        ctrl.on_pause = lambda: called.append("paused")
        ctrl.pause()
        assert called == ["paused"]

    def test_on_pause_not_called_when_cancelled(self) -> None:
        ctrl = PipelineController()
        called = []
        ctrl.on_pause = lambda: called.append("paused")
        ctrl.cancel()
        ctrl.pause()
        # pause() is a no-op when cancelled, so callback should not fire
        assert called == []


class TestOnResumeCallback:
    def test_on_resume_fires(self) -> None:
        ctrl = PipelineController()
        called = []
        ctrl.on_resume = lambda: called.append("resumed")
        ctrl.pause()
        ctrl.resume()
        assert called == ["resumed"]

    def test_on_resume_not_called_when_cancelled(self) -> None:
        ctrl = PipelineController()
        called = []
        ctrl.on_resume = lambda: called.append("resumed")
        ctrl.cancel()
        ctrl.resume()
        assert called == []


# ---------------------------------------------------------------------------
# PipelineResult dataclass
# ---------------------------------------------------------------------------


class TestPipelineResult:
    def test_default_fields(self) -> None:
        """PipelineResult has sensible defaults for all stat fields."""
        result = PipelineResult(pairs=[])
        assert result.pairs == []
        assert result.files_scanned == 0
        assert result.files_after_filter == 0
        assert result.total_pairs_scored == 0
        assert result.pairs_found == 0
        assert result.scan_time == 0.0
        assert result.extract_time == 0.0
        assert result.filter_time == 0.0
        assert result.content_hash_time == 0.0
        assert result.audio_fingerprint_time == 0.0
        assert result.scoring_time == 0.0
        assert result.stage_timings == {}
        assert result.stage_counts == {}

    def test_stage_timings_keys_match_canonical(self) -> None:
        """stage_timings keys should match _CANONICAL_STAGES when fully populated."""
        timings = {s: 0.0 for s in _CANONICAL_STAGES}
        counts = {s: 0 for s in _CANONICAL_STAGES}
        result = PipelineResult(pairs=[], stage_timings=timings, stage_counts=counts)
        assert set(result.stage_timings.keys()) == set(_CANONICAL_STAGES)
        assert set(result.stage_counts.keys()) == set(_CANONICAL_STAGES)

    def test_pairs_field_holds_scored_pairs(self) -> None:
        """pairs field should hold the list passed in."""
        meta_a = VideoMetadata(path=Path("a.mp4"), filename="a", duration=60.0, width=1920, height=1080, file_size=100)
        meta_b = VideoMetadata(path=Path("b.mp4"), filename="b", duration=60.0, width=1920, height=1080, file_size=100)
        meta_c = VideoMetadata(path=Path("c.mp4"), filename="c", duration=60.0, width=1920, height=1080, file_size=100)
        fake_pairs = [
            ScoredPair(file_a=meta_a, file_b=meta_b, total_score=90.0, breakdown={}, detail={}),
            ScoredPair(file_a=meta_a, file_b=meta_c, total_score=85.0, breakdown={}, detail={}),
        ]
        result = PipelineResult(pairs=fake_pairs, files_scanned=10, pairs_found=2)
        assert result.pairs is fake_pairs
        assert result.files_scanned == 10
        assert result.pairs_found == 2

    def test_is_dataclass(self) -> None:
        """PipelineResult is a dataclass."""
        assert dataclasses.is_dataclass(PipelineResult)


# ---------------------------------------------------------------------------
# _CANONICAL_STAGES constant
# ---------------------------------------------------------------------------


class TestCanonicalStages:
    def test_canonical_stages_is_tuple(self) -> None:
        assert isinstance(_CANONICAL_STAGES, tuple)

    def test_canonical_stages_has_six_entries(self) -> None:
        assert len(_CANONICAL_STAGES) == 6

    def test_canonical_stages_order(self) -> None:
        """The 6 canonical stages must appear in pipeline execution order."""
        assert _CANONICAL_STAGES == (
            "scan",
            "extract",
            "filter",
            "content_hash",
            "audio_fingerprint",
            "score",
        )


# ---------------------------------------------------------------------------
# compute_stage_list
# ---------------------------------------------------------------------------


class TestComputeStageList:
    def test_async_default_stages(self) -> None:
        """Default async pipeline without content/audio: scan, extract, filter, score + report."""
        stages = compute_stage_list()
        assert stages == ["scan", "extract", "filter", "score", "report"]

    def test_async_with_thumbnails(self) -> None:
        """embed_thumbnails adds 'thumbnail' before 'report'."""
        stages = compute_stage_list(embed_thumbnails=True)
        assert stages == ["scan", "extract", "filter", "score", "thumbnail", "report"]

    def test_replay_stages(self) -> None:
        """Replay mode has only replay + filter + report."""
        stages = compute_stage_list(is_replay=True)
        assert stages == ["replay", "filter", "report"]

    def test_replay_ignores_ssim(self) -> None:
        """Replay takes precedence over SSIM -- result is replay path."""
        stages = compute_stage_list(is_replay=True, is_ssim=True)
        assert stages == ["replay", "filter", "report"]

    def test_replay_with_thumbnails_includes_thumbnail_stage(self) -> None:
        """Replay includes thumbnail before report when thumbnails are embedded."""
        stages = compute_stage_list(is_replay=True, embed_thumbnails=True)
        assert stages == ["replay", "filter", "thumbnail", "report"]

    def test_ssim_stages(self) -> None:
        """SSIM path uses ssim_extract instead of content_hash/audio_fingerprint."""
        stages = compute_stage_list(is_ssim=True)
        assert stages == ["scan", "extract", "filter", "ssim_extract", "score", "report"]

    def test_ssim_with_thumbnails(self) -> None:
        """SSIM + thumbnails includes thumbnail before report."""
        stages = compute_stage_list(is_ssim=True, embed_thumbnails=True)
        assert stages == ["scan", "extract", "filter", "ssim_extract", "score", "thumbnail", "report"]

    def test_report_always_last(self) -> None:
        """Report is always the last stage in any configuration."""
        for kwargs in [
            {},
            {"is_replay": True},
            {"is_replay": True, "embed_thumbnails": True},
            {"is_ssim": True},
            {"embed_thumbnails": True},
            {"is_ssim": True, "embed_thumbnails": True},
            {"has_content": True},
            {"has_audio": True},
            {"has_content": True, "has_audio": True},
            {"has_content": True, "embed_thumbnails": True},
        ]:
            stages = compute_stage_list(**kwargs)
            assert stages[-1] == "report", f"report not last for {kwargs}: {stages}"

    def test_has_content_includes_content_hash(self) -> None:
        """has_content=True includes content_hash between filter and score."""
        stages = compute_stage_list(has_content=True)
        assert stages == ["scan", "extract", "filter", "content_hash", "score", "report"]
        # Verify ordering: content_hash after filter, before score
        assert stages.index("content_hash") > stages.index("filter")
        assert stages.index("content_hash") < stages.index("score")

    def test_has_audio_includes_audio_fingerprint(self) -> None:
        """has_audio=True includes audio_fingerprint between filter and score."""
        stages = compute_stage_list(has_audio=True)
        assert stages == ["scan", "extract", "filter", "audio_fingerprint", "score", "report"]
        assert stages.index("audio_fingerprint") > stages.index("filter")
        assert stages.index("audio_fingerprint") < stages.index("score")

    def test_has_both_content_and_audio(self) -> None:
        """has_content + has_audio includes both, with content_hash before audio_fingerprint."""
        stages = compute_stage_list(has_content=True, has_audio=True)
        assert stages == ["scan", "extract", "filter", "content_hash", "audio_fingerprint", "score", "report"]
        assert stages.index("content_hash") < stages.index("audio_fingerprint")

    def test_ssim_ignores_has_content_audio(self) -> None:
        """SSIM path ignores has_content and has_audio flags."""
        stages = compute_stage_list(is_ssim=True, has_content=True, has_audio=True)
        assert stages == ["scan", "extract", "filter", "ssim_extract", "score", "report"]
        assert "content_hash" not in stages
        assert "audio_fingerprint" not in stages


# ---------------------------------------------------------------------------
# PipelineController.linked()
# ---------------------------------------------------------------------------


class TestPipelineControllerLinked:
    def test_linked_shares_pause(self) -> None:
        """Linked controllers share pause state."""
        base = PipelineController()
        linked = base.linked()
        base.pause()
        assert linked.is_paused
        base.resume()
        assert not linked.is_paused

    def test_linked_shares_cancel(self) -> None:
        """Linked controllers share cancel state."""
        base = PipelineController()
        linked = base.linked()
        base.cancel()
        assert linked.is_cancelled

    def test_linked_independent_stage_tracking(self) -> None:
        """Linked controllers have independent stage tracking."""
        base = PipelineController()
        linked = base.linked()

        base.enter_stage("scan")
        base.complete_stage("scan")
        base.enter_stage("extract")

        linked.enter_stage("scan")

        # Base has completed scan, active extract
        assert "scan" in base.completed_stages
        assert base.active_stage == "extract"

        # Linked has active scan, no completed stages
        assert linked.completed_stages == []
        assert linked.active_stage == "scan"

    def test_linked_shares_on_pause_callback(self) -> None:
        """on_pause callback set on base fires when linked controller pauses."""
        base = PipelineController()
        linked = base.linked()
        called = []
        base.on_pause = lambda: called.append("paused")
        linked.pause()
        assert called == ["paused"]

    def test_linked_shares_on_resume_callback(self) -> None:
        """on_resume callback set on base fires when linked controller resumes."""
        base = PipelineController()
        linked = base.linked()
        called = []
        base.on_resume = lambda: called.append("resumed")
        linked.pause()
        linked.resume()
        assert called == ["resumed"]

    @pytest.mark.asyncio
    async def test_linked_wait_if_paused_blocks_both(self) -> None:
        """Pausing base blocks wait_if_paused on linked controller."""
        base = PipelineController()
        linked = base.linked()
        base.pause()

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(linked.wait_if_paused(), timeout=0.1)

        base.resume()
        # Should not hang after resume
        await asyncio.wait_for(linked.wait_if_paused(), timeout=0.1)


# ---------------------------------------------------------------------------
# score_stage: stage_start fires before accumulation
# ---------------------------------------------------------------------------


class TestScoreStageStartTiming:
    @pytest.mark.asyncio
    async def test_score_stage_start_before_accumulation_empty(self) -> None:
        """score_stage emits stage_start before accumulating, and stage_end on <2 items."""
        in_q: asyncio.Queue = asyncio.Queue()
        await in_q.put(None)  # sentinel immediately — empty pipeline

        progress = _make_progress_mock()
        controller = PipelineController()
        config = MagicMock(comparators=None, workers=0, mode="video", threshold=50.0)

        result = await score_stage(in_q, None, config, progress, controller)

        assert result == []
        progress.stage_start.assert_called_once_with("score")
        progress.stage_end.assert_called_once()
        end_args, end_kwargs = progress.stage_end.call_args
        assert end_args[0] == "score"
        assert end_kwargs["total"] == 0

    @pytest.mark.asyncio
    async def test_score_stage_start_before_accumulation_one_item(self) -> None:
        """score_stage with exactly 1 item: stage_start fires, then stage_end with total=0."""
        in_q: asyncio.Queue = asyncio.Queue()
        await in_q.put(MagicMock())
        await in_q.put(None)

        progress = _make_progress_mock()
        controller = PipelineController()
        config = MagicMock(comparators=None, workers=0, mode="video", threshold=50.0)

        result = await score_stage(in_q, None, config, progress, controller)

        assert result == []
        progress.stage_start.assert_called_once_with("score")
        progress.stage_end.assert_called_once()
        end_args, end_kwargs = progress.stage_end.call_args
        assert end_args[0] == "score"
        assert end_kwargs["total"] == 0

    @pytest.mark.asyncio
    async def test_score_stage_start_order(self) -> None:
        """stage_start('score') is called before any queue items are consumed."""
        in_q: asyncio.Queue = asyncio.Queue()
        call_order: list[str] = []

        progress = MagicMock()
        progress.stage_start = MagicMock(side_effect=lambda name: call_order.append(f"start:{name}"))
        progress.stage_end = MagicMock(side_effect=lambda *a, **kw: call_order.append(f"end:{a[0]}"))
        progress.progress = MagicMock()

        # We'll delay putting the sentinel so we can observe the order
        await in_q.put(None)

        controller = PipelineController()
        config = MagicMock(comparators=None, workers=0, mode="video", threshold=50.0)

        await score_stage(in_q, None, config, progress, controller)

        # stage_start must precede stage_end
        assert call_order[0] == "start:score"
        assert call_order[-1] == "end:score"


# ---------------------------------------------------------------------------
# extract_stage: non-blocking future harvesting
# ---------------------------------------------------------------------------


class TestExtractStageNonBlockingHarvest:
    @pytest.mark.asyncio
    async def test_extract_stage_progress_with_few_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """extract_stage with fewer items than max_concurrent still emits intermediate progress.

        With workers=8, max_concurrent=8. Putting only 2 items means we never hit
        the `len(pending) >= max_concurrent` threshold. The non-blocking harvest
        of already-completed futures should still fire progress events.
        """

        def _fast_extract(path, cache, mode, **kwargs):
            meta = MagicMock()
            meta.path = path
            return meta

        import duplicates_detector.metadata

        monkeypatch.setattr(duplicates_detector.metadata, "_extract_one_with_cache", _fast_extract)

        in_q: asyncio.Queue[Path | None] = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock(workers=8, mode="video")

        await in_q.put(Path("/fake/a.mp4"))
        await in_q.put(Path("/fake/b.mp4"))
        await in_q.put(None)

        await extract_stage(in_q, out_q, None, config, progress, ctrl)

        # Collect results (excluding sentinel)
        results = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                results.append(item)
        assert len(results) == 2

        # The forced final progress event must always be emitted
        final_call = progress.progress.call_args_list[-1]
        assert final_call.kwargs.get("force") is True

        # stage_start and stage_end should both fire
        progress.stage_start.assert_called_once_with("extract", total=None)
        progress.stage_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_stage_emits_definitive_total_in_final_progress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """extract_stage final forced progress event reflects the total items processed."""

        def _fast_extract(path, cache, mode, **kwargs):
            meta = MagicMock()
            meta.path = path
            return meta

        import duplicates_detector.metadata

        monkeypatch.setattr(duplicates_detector.metadata, "_extract_one_with_cache", _fast_extract)

        in_q: asyncio.Queue[Path | None] = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        progress = _make_progress_mock()
        config = MagicMock(workers=8, mode="video")

        for i in range(3):
            await in_q.put(Path(f"/fake/file{i}.mp4"))
        await in_q.put(None)

        await extract_stage(in_q, out_q, None, config, progress, ctrl)

        # The final forced progress event
        final_call = progress.progress.call_args_list[-1]
        assert final_call.kwargs.get("force") is True
        # current should equal the number of items processed
        assert final_call.args[0] == "extract"
        # The stage_end total should be 3
        end_kwargs = progress.stage_end.call_args.kwargs
        assert end_kwargs["total"] == 3


class TestHashStagePreHash:
    @pytest.mark.asyncio
    async def test_byte_identical_files_still_get_real_hashes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Files with same file_size and pre_hash still go through real PDQ hashing.

        Pre-hashes feed the scorer's byte-identical fast path (SHA-256 verified)
        but no longer produce synthetic content hashes (which caused false
        positives when files shared the first 4KB but differed afterwards).
        """
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

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            hash_calls.append(m.path)
            return replace(m, content_hash=(1, 2, 3, 4))

        monkeypatch.setattr("duplicates_detector.content._hash_one_with_cache", _fake_hash)

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
        config.no_pre_hash = False

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
        # Both files went through real PDQ hashing (no synthetic shortcut)
        assert len(hash_calls) == 2
        assert items[0].content_hash is not None
        assert items[1].content_hash is not None
        # Pre-hashes were still computed for the scorer's byte-identical path
        assert items[0].pre_hash is not None
        assert items[1].pre_hash is not None

    @pytest.mark.asyncio
    async def test_unique_prehash_files_go_through_pdq(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Files with unique (file_size, pre_hash) proceed to normal PDQ hashing."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(b"content_a_unique")
        p2.write_bytes(b"content_b_unique_and_different_length")

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

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            hash_calls.append(m.path)
            return replace(m, content_hash=(1, 2, 3, 4))

        monkeypatch.setattr("duplicates_detector.content._hash_one_with_cache", _fake_hash)

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
        config.no_pre_hash = False

        await in_q.put(meta1)
        await in_q.put(meta2)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        assert len(hash_calls) == 2

    @pytest.mark.asyncio
    async def test_passthrough_when_content_disabled(self) -> None:
        """Pre-hash logic does not run when content is False."""
        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = False

        meta = MagicMock()
        meta.pre_hash = None
        await in_q.put(meta)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 1
        assert items[0].pre_hash is None

    @pytest.mark.asyncio
    async def test_ssim_mode_skips_pre_hash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When content_method is 'ssim', hash_stage does PDQ without pre-hash grouping."""
        p = tmp_path / "a.mp4"
        p.write_bytes(b"content")
        st = p.stat()
        meta = VideoMetadata(
            path=p,
            filename="a",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st.st_size,
            mtime=st.st_mtime,
        )

        pre_hash_calls: list[Path] = []

        def _fake_hash(m, cache, *, rotation_invariant=False, is_image=False, is_document=False):
            return replace(m, content_hash=(1, 2, 3, 4))

        def _fake_pre_hash(m, cache):
            pre_hash_calls.append(m.path)
            return replace(m, pre_hash="should_not_be_called")

        monkeypatch.setattr("duplicates_detector.content._hash_one_with_cache", _fake_hash)
        monkeypatch.setattr("duplicates_detector.content._pre_hash_one_with_cache", _fake_pre_hash)

        in_q: asyncio.Queue = asyncio.Queue()
        out_q: asyncio.Queue = asyncio.Queue()
        ctrl = PipelineController()
        config = MagicMock()
        config.content = True
        config.content_method = "ssim"
        config.workers = 1
        config.mode = Mode.VIDEO
        config.rotation_invariant = False
        config.visible_stages = frozenset()

        await in_q.put(meta)
        await in_q.put(None)

        await hash_stage(in_q, out_q, None, config, None, ctrl)

        items = []
        while not out_q.empty():
            item = out_q.get_nowait()
            if item is not None:
                items.append(item)

        assert len(items) == 1
        assert len(pre_hash_calls) == 0
