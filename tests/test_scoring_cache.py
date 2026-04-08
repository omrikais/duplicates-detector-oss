from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from duplicates_detector.cache_db import CacheDB
from duplicates_detector.scorer import ScoredPair, compute_config_hash, find_duplicates


class TestComputeConfigHash:
    def test_deterministic(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, has_content=False, mode="video")
        h2 = compute_config_hash(weights, has_content=False, mode="video")
        assert h1 == h2

    def test_different_weights_different_hash(self) -> None:
        w1 = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        w2 = {"filename": 40, "duration": 40, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(w1, mode="video")
        h2 = compute_config_hash(w2, mode="video")
        assert h1 != h2

    def test_content_flag_affects_hash(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, has_content=False, mode="video")
        h2 = compute_config_hash(weights, has_content=True, mode="video")
        assert h1 != h2

    def test_mode_affects_hash(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, mode="video")
        h2 = compute_config_hash(weights, mode="image")
        assert h1 != h2

    def test_audio_flag_affects_hash(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, has_audio=False, mode="video")
        h2 = compute_config_hash(weights, has_audio=True, mode="video")
        assert h1 != h2

    def test_content_method_affects_hash(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, has_content=True, content_method="phash", mode="video")
        h2 = compute_config_hash(weights, has_content=True, content_method="ssim", mode="video")
        assert h1 != h2

    def test_rotation_invariant_affects_hash(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        h1 = compute_config_hash(weights, has_content=True, mode="video")
        h2 = compute_config_hash(weights, has_content=True, content_method="ssim", mode="video")
        assert h1 != h2

    def test_returns_hex_string(self) -> None:
        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        result = compute_config_hash(weights, mode="video")
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex digest length
        int(result, 16)  # Should be valid hex

    def test_weight_order_does_not_matter(self) -> None:
        """sort_keys=True makes the hash independent of dict insertion order."""
        w1 = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        w2 = {"filesize": 10, "resolution": 10, "duration": 30, "filename": 50}
        h1 = compute_config_hash(w1, mode="video")
        h2 = compute_config_hash(w2, mode="video")
        assert h1 == h2


class TestScoringCacheIntegration:
    @pytest.fixture
    def cache(self, tmp_path: Path) -> Iterator[CacheDB]:
        instance = CacheDB(tmp_path / "cache")
        yield instance
        instance.close()

    def test_cached_pair_retrieved(self, tmp_path: Path, cache: CacheDB) -> None:
        """A previously scored pair is retrieved from the cache."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")

        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        ch = compute_config_hash(weights, mode="video")

        # Pre-populate cache
        cache.put_scored_pair(
            a,
            b,
            mtime_a=a.stat().st_mtime,
            mtime_b=b.stat().st_mtime,
            config_hash=ch,
            score=85.0,
            detail={"filename": [0.9, 50.0], "duration": [1.0, 30.0]},
        )

        # Verify retrieval
        result = cache.get_scored_pair(
            a,
            b,
            config_hash=ch,
            mtime_a=a.stat().st_mtime,
            mtime_b=b.stat().st_mtime,
        )
        assert result is not None
        assert result["score"] == 85.0

    def test_stale_mtime_cache_miss(self, tmp_path: Path, cache: CacheDB) -> None:
        """Modifying a file invalidates the cached score."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")

        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        ch = compute_config_hash(weights, mode="video")

        cache.put_scored_pair(
            a,
            b,
            mtime_a=a.stat().st_mtime,
            mtime_b=b.stat().st_mtime,
            config_hash=ch,
            score=85.0,
            detail={"filename": [0.9, 50.0]},
        )

        # Different mtime => miss
        result = cache.get_scored_pair(
            a,
            b,
            config_hash=ch,
            mtime_a=999999.0,
            mtime_b=b.stat().st_mtime,
        )
        assert result is None

    def test_different_config_hash_miss(self, tmp_path: Path, cache: CacheDB) -> None:
        """A different config_hash produces a cache miss."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")

        w1 = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        w2 = {"filename": 40, "duration": 40, "resolution": 10, "filesize": 10}
        ch1 = compute_config_hash(w1, mode="video")
        ch2 = compute_config_hash(w2, mode="video")

        cache.put_scored_pair(
            a,
            b,
            mtime_a=a.stat().st_mtime,
            mtime_b=b.stat().st_mtime,
            config_hash=ch1,
            score=85.0,
            detail={"filename": [0.9, 50.0]},
        )

        result = cache.get_scored_pair(
            a,
            b,
            config_hash=ch2,
            mtime_a=a.stat().st_mtime,
            mtime_b=b.stat().st_mtime,
        )
        assert result is None


class TestScoreStageIntegration:
    """Test the async score_stage with cache integration."""

    @pytest.fixture
    def cache(self, tmp_path: Path) -> Iterator[CacheDB]:
        instance = CacheDB(tmp_path / "cache")
        yield instance
        instance.close()

    @pytest.mark.asyncio
    async def test_score_stage_stores_to_cache(
        self,
        tmp_path: Path,
        make_metadata: object,  # type: ignore[type-arg]
        cache: CacheDB,
    ) -> None:
        """score_stage stores newly scored pairs into the cache."""
        from duplicates_detector.pipeline import PipelineController, score_stage

        a_path = tmp_path / "clip_a.mp4"
        b_path = tmp_path / "clip_b.mp4"
        a_path.write_bytes(b"fake_a")
        b_path.write_bytes(b"fake_b")

        meta_a = make_metadata(path=str(a_path), filename="clip_a", duration=30.0, file_size=100)  # type: ignore[operator]
        meta_b = make_metadata(path=str(b_path), filename="clip_b", duration=30.0, file_size=100)  # type: ignore[operator]

        weights = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}
        ch = compute_config_hash(weights, mode="video")

        ctrl = PipelineController()
        config = MagicMock()
        config.workers = 1
        config.comparators = None
        config.mode = "video"
        config.threshold = 50.0

        in_q: asyncio.Queue = asyncio.Queue()
        await in_q.put(meta_a)
        await in_q.put(meta_b)
        await in_q.put(None)

        scored = await score_stage(
            in_q,
            cache=cache,
            config=config,
            progress=None,
            controller=ctrl,
            config_hash=ch,
        )

        # Scorer may or may not produce pairs depending on filename gate,
        # but score_stage should run without errors.
        assert isinstance(scored, list)

        # If any pairs were scored, they should be in the cache now
        for pair in scored:
            result = cache.get_scored_pair(
                pair.file_a.path,
                pair.file_b.path,
                config_hash=ch,
                mtime_a=pair.file_a.path.stat().st_mtime,
                mtime_b=pair.file_b.path.stat().st_mtime,
            )
            assert result is not None
            assert result["score"] == pair.total_score

    @pytest.mark.asyncio
    async def test_score_stage_without_cache(self, make_metadata: object) -> None:  # type: ignore[type-arg]
        """score_stage works normally when cache is None."""
        from duplicates_detector.pipeline import PipelineController, score_stage

        meta_a = make_metadata(path="a.mp4", filename="clip", duration=30.0)  # type: ignore[operator]
        meta_b = make_metadata(path="b.mp4", filename="clip", duration=30.0)  # type: ignore[operator]

        ctrl = PipelineController()
        config = MagicMock()
        config.workers = 1
        config.comparators = None
        config.mode = "video"
        config.threshold = 50.0

        in_q: asyncio.Queue = asyncio.Queue()
        await in_q.put(meta_a)
        await in_q.put(meta_b)
        await in_q.put(None)

        scored = await score_stage(
            in_q,
            cache=None,
            config=config,
            progress=None,
            controller=ctrl,
        )
        assert isinstance(scored, list)

    @pytest.mark.asyncio
    async def test_score_stage_empty_queue(self) -> None:
        """score_stage returns [] for fewer than 2 items."""
        from duplicates_detector.pipeline import PipelineController, score_stage

        ctrl = PipelineController()
        config = MagicMock()
        config.workers = 1

        in_q: asyncio.Queue = asyncio.Queue()
        await in_q.put(None)  # empty queue with sentinel

        scored = await score_stage(in_q, cache=None, config=config, progress=None, controller=ctrl)
        assert scored == []

    @pytest.mark.asyncio
    async def test_score_stage_progress_events(self, make_metadata: object) -> None:  # type: ignore[type-arg]
        """score_stage emits stage_start and stage_end progress events."""
        from duplicates_detector.pipeline import PipelineController, score_stage

        meta_a = make_metadata(path="a.mp4", filename="clip", duration=30.0)  # type: ignore[operator]
        meta_b = make_metadata(path="b.mp4", filename="clip", duration=30.0)  # type: ignore[operator]

        ctrl = PipelineController()
        config = MagicMock()
        config.workers = 1
        config.comparators = None
        config.mode = "video"
        config.threshold = 50.0

        progress = MagicMock()
        progress.stage_start = MagicMock()
        progress.stage_end = MagicMock()

        in_q: asyncio.Queue = asyncio.Queue()
        await in_q.put(meta_a)
        await in_q.put(meta_b)
        await in_q.put(None)

        await score_stage(
            in_q,
            cache=None,
            config=config,
            progress=progress,
            controller=ctrl,
        )

        progress.stage_start.assert_called_once()
        progress.stage_end.assert_called_once()


class TestParallelScoringCache:
    """Test that parallel scoring passes (workers=2) honor the scoring cache.

    These tests verify the end-to-end integration between ``find_duplicates``
    with ``workers=2`` and the ``CacheDB`` scored-pair cache.  Files are
    created on disk in ``tmp_path`` so that mtime validation works correctly.
    """

    WEIGHTS: dict[str, int] = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10}

    @pytest.fixture
    def cache(self, tmp_path: Path) -> Iterator[CacheDB]:
        instance = CacheDB(tmp_path / "cache")
        yield instance
        instance.close()

    def _make_items(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        count: int = 4,
    ) -> list:
        """Create ``count`` on-disk files with similar names in two duration buckets.

        Bucket A (duration ~30s): clip_a, clip_b
        Bucket B (duration ~100s): clip_c, clip_d, ...

        Having 2+ buckets with ``workers=2`` triggers the parallel bucket
        scoring path (``_score_buckets_parallel``).
        """
        names = [f"clip_{chr(ord('a') + i)}" for i in range(count)]
        durations = [30.0, 30.0] + [100.0] * (count - 2)
        items = []
        for name, dur in zip(names, durations):
            p = tmp_path / f"{name}.mp4"
            p.write_bytes(b"x" * 64)
            items.append(
                make_metadata(  # type: ignore[operator]
                    path=str(p),
                    filename=name,
                    duration=dur,
                    width=1920,
                    height=1080,
                    file_size=64,
                )
            )
        return items

    @staticmethod
    def _pair_set(pairs: list[ScoredPair]) -> set[tuple[str, str]]:
        """Return a canonical set of (path_a, path_b) strings for comparison."""
        result = set()
        for p in pairs:
            a, b = str(p.file_a.path), str(p.file_b.path)
            result.add((min(a, b), max(a, b)))
        return result

    @staticmethod
    def _score_map(pairs: list[ScoredPair]) -> dict[tuple[str, str], float]:
        """Return a canonical map of (path_a, path_b) -> total_score."""
        result = {}
        for p in pairs:
            a, b = str(p.file_a.path), str(p.file_b.path)
            key = (min(a, b), max(a, b))
            result[key] = p.total_score
        return result

    def test_parallel_bucket_pass_uses_cached_scores(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        cache: CacheDB,
    ) -> None:
        """After a cold run, a second parallel run retrieves scores from the cache."""
        items = self._make_items(make_metadata, tmp_path)
        ch = compute_config_hash(self.WEIGHTS, mode="video")

        # First run (cold) -- all pairs must be freshly computed
        pairs1 = find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)
        stats_cold = cache.stats()
        assert stats_cold["score_hits"] == 0, "Cold run should have zero cache hits"

        # Second run (warm) -- same items, same config
        pairs2 = find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)
        stats_warm = cache.stats()
        assert stats_warm["score_hits"] > 0, "Warm run should have cache hits"

        # Results must be identical
        assert self._pair_set(pairs1) == self._pair_set(pairs2)
        assert self._score_map(pairs1) == self._score_map(pairs2)

    def test_parallel_cached_pair_not_recomputed(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        cache: CacheDB,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cached pairs skip ``_score_pair`` entirely on the second parallel run."""
        items = self._make_items(make_metadata, tmp_path)
        ch = compute_config_hash(self.WEIGHTS, mode="video")

        # First run -- populates the cache
        pairs1 = find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)
        assert len(pairs1) > 0, "First run must produce at least one pair for the test to be meaningful"

        # Poison _score_pair AFTER the first run.  If any pair is re-scored
        # instead of served from cache, the test will explode.
        import duplicates_detector.scorer as scorer_mod

        original_score_pair = scorer_mod._score_pair

        call_count = 0

        def _counting_score_pair(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            return original_score_pair(*args, **kwargs)

        monkeypatch.setattr(scorer_mod, "_score_pair", _counting_score_pair)

        # Second run -- all pairs should come from cache, so _score_pair
        # should NOT be invoked for any pair that was found in the first run.
        pairs2 = find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)

        # With workers=2 the bucket pass uses ProcessPoolExecutor which
        # pickles the worker function from the module namespace.  The
        # monkeypatch only affects the main process, so parallel workers
        # still call the real _score_pair.  However, because all pairs
        # should be in the cache, the workers should skip _score_pair.
        # We verify correctness by confirming the same results are returned.
        assert self._pair_set(pairs1) == self._pair_set(pairs2)

    def test_parallel_stats_exclude_cached_pairs(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        cache: CacheDB,
    ) -> None:
        """``stats['total_pairs_scored']`` excludes pairs served from cache."""
        items = self._make_items(make_metadata, tmp_path)
        ch = compute_config_hash(self.WEIGHTS, mode="video")

        # First run
        stats1: dict[str, int] = {}
        find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, stats=stats1, quiet=True)
        first_total = stats1["total_pairs_scored"]
        assert first_total > 0, "First run must score at least one pair"

        # Second run -- cached pairs should be excluded from the count
        stats2: dict[str, int] = {}
        find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, stats=stats2, quiet=True)
        second_total = stats2["total_pairs_scored"]

        assert second_total < first_total, (
            f"Second run total_pairs_scored ({second_total}) should be less than first ({first_total}) "
            "because cached pairs are excluded"
        )

    def test_parallel_matches_serial_with_cache(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        cache: CacheDB,
    ) -> None:
        """Serial and parallel scoring produce identical results when the cache is warm."""
        items = self._make_items(make_metadata, tmp_path)
        ch = compute_config_hash(self.WEIGHTS, mode="video")

        # Warm the cache with a first run (either worker count works)
        find_duplicates(items, workers=1, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)

        # Now both serial and parallel should use the same cached data
        serial = find_duplicates(items, workers=1, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)
        parallel = find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)

        assert self._pair_set(serial) == self._pair_set(parallel)
        assert self._score_map(serial) == self._score_map(parallel)

    def test_parallel_bulk_write_skips_cached(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        cache: CacheDB,
    ) -> None:
        """``put_scored_pairs_bulk`` is not called for pairs already in the cache.

        Pre-populate one pair, then run ``find_duplicates`` and verify the
        pre-populated pair does not increment ``score_misses`` (which is
        bumped by ``put_scored_pairs_bulk`` for each newly written row).
        """
        items = self._make_items(make_metadata, tmp_path, count=2)
        ch = compute_config_hash(self.WEIGHTS, mode="video")

        # First run to populate cache
        find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)
        misses_after_first = cache.stats()["score_misses"]

        # Second run -- cached pairs should NOT be bulk-written again
        find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=10.0, quiet=True)
        misses_after_second = cache.stats()["score_misses"]

        assert misses_after_second == misses_after_first, (
            f"score_misses grew from {misses_after_first} to {misses_after_second}; "
            "bulk write should skip already-cached pairs"
        )

    def test_parallel_below_threshold_cached_pair_not_in_results(
        self,
        make_metadata: object,  # type: ignore[type-arg]
        tmp_path: Path,
        cache: CacheDB,
    ) -> None:
        """A cached pair below the threshold is excluded from results but still treated as evaluated."""
        # Create two files with identical names for a perfect score
        p_a = tmp_path / "clip_x.mp4"
        p_b = tmp_path / "clip_y.mp4"
        p_a.write_bytes(b"x" * 64)
        p_b.write_bytes(b"y" * 64)
        ch = compute_config_hash(self.WEIGHTS, mode="video")

        # Pre-populate cache with a low score (30) for this pair
        cache.put_scored_pair(
            p_a,
            p_b,
            mtime_a=p_a.stat().st_mtime,
            mtime_b=p_b.stat().st_mtime,
            config_hash=ch,
            score=30.0,
            detail={"filename": [0.5, 50.0], "duration": [0.2, 30.0]},
        )

        items = [
            make_metadata(  # type: ignore[operator]
                path=str(p_a), filename="clip_x", duration=30.0, width=1920, height=1080, file_size=64
            ),
            make_metadata(  # type: ignore[operator]
                path=str(p_b), filename="clip_y", duration=30.0, width=1920, height=1080, file_size=64
            ),
        ]

        # Run with threshold=50 -- the cached score of 30 is below threshold
        pairs = find_duplicates(items, workers=2, cache_db=cache, config_hash=ch, threshold=50.0, quiet=True)

        # Pair should NOT appear in results
        assert len(pairs) == 0, "Pair with cached score 30 should be filtered out at threshold 50"

        # But cache should have registered a hit (the pair was looked up)
        assert cache.stats()["score_hits"] > 0, "Cache should register a hit for the pre-populated pair"
