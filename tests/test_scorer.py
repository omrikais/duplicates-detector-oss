from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from duplicates_detector.comparators import get_default_comparators, get_content_comparators
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.progress import ProgressEmitter
from duplicates_detector.scorer import (
    ScoredPair,
    _MIN_FILENAME_RATIO,
    _bucket_by_duration,
    _content_pass_serial,
    _filename_pass_parallel,
    _filename_pass_serial,
    _pair_key,
    _score_pair,
    _resolution_tier,
    _filesize_tier,
    _refine_large_buckets,
    find_duplicates,
)


# ---------------------------------------------------------------------------
# _bucket_by_duration
# ---------------------------------------------------------------------------


class TestBucketByDuration:
    def test_groups_similar(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=100.0),
            make_metadata(path="b.mp4", duration=101.0),
            make_metadata(path="c.mp4", duration=103.0),
        ]
        buckets = _bucket_by_duration(items, tolerance=2.0)
        assert len(buckets) == 1
        assert len(buckets[0]) == 3

    def test_separates_different(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=10.0),
            make_metadata(path="b.mp4", duration=100.0),
        ]
        buckets = _bucket_by_duration(items, tolerance=2.0)
        # Each alone → excluded (< 2 items)
        assert len(buckets) == 0

    def test_none_catch_all(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=None),
            make_metadata(path="b.mp4", duration=None),
        ]
        buckets = _bucket_by_duration(items, tolerance=2.0)
        assert len(buckets) == 1
        assert all(v.duration is None for v in buckets[0])

    def test_single_item_excluded(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=10.0),
            make_metadata(path="b.mp4", duration=100.0),
            make_metadata(path="c.mp4", duration=200.0),
        ]
        buckets = _bucket_by_duration(items, tolerance=2.0)
        # All singles → no buckets
        assert len(buckets) == 0

    def test_mixed_known_and_unknown(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=50.0),
            make_metadata(path="b.mp4", duration=50.5),
            make_metadata(path="c.mp4", duration=None),
            make_metadata(path="d.mp4", duration=None),
        ]
        buckets = _bucket_by_duration(items, tolerance=2.0)
        # One bucket for known pair, one for unknown pair
        assert len(buckets) == 2
        known_bucket = [b for b in buckets if b[0].duration is not None][0]
        unknown_bucket = [b for b in buckets if b[0].duration is None][0]
        assert len(known_bucket) == 2
        assert len(unknown_bucket) == 2

    def test_none_duration_in_known_goes_to_unknown(self, make_metadata):
        """If None-duration item leaks into sorted list, it falls into the unknown bucket."""
        a = make_metadata(path="a.mp4", duration=10.0)
        b = make_metadata(path="b.mp4", duration=None)
        # Patch sorted() to bypass the list-comprehension filter and inject bad data.
        with patch("builtins.sorted", return_value=[a, b]):
            buckets = _bucket_by_duration([a])
            # b (None duration) ends up in the unknown catch-all bucket
            assert any(b in bucket for bucket in buckets)


# ---------------------------------------------------------------------------
# _resolution_tier
# ---------------------------------------------------------------------------


class TestResolutionTier:
    @pytest.mark.parametrize(
        "width, height, expected",
        [
            (640, 360, "sd"),  # 230400 pixels → sd (> 153600)
            (640, 240, "ld"),  # 153600 pixels → ld (≤ 153600)
            (854, 480, "sd"),  # 409920 pixels → sd
            (1280, 720, "hd"),  # 921600 pixels → hd
            (1920, 1080, "fhd"),  # 2073600 pixels → fhd
            (2560, 1440, "qhd"),  # 3686400 pixels → qhd
            (3840, 2160, "uhd"),  # 8294400 pixels → uhd
        ],
    )
    def test_classifications(self, make_metadata, width, height, expected):
        v = make_metadata(width=width, height=height)
        assert _resolution_tier(v) == expected

    def test_unknown(self, make_metadata):
        v = make_metadata(width=None, height=None)
        assert _resolution_tier(v) == "unknown"


# ---------------------------------------------------------------------------
# _filesize_tier
# ---------------------------------------------------------------------------


class TestFilesizeTier:
    @pytest.mark.parametrize(
        "file_size, expected_tier",
        [
            (1 * 1024 * 1024, 0),  # 1 MB → log2(1) = 0
            (2 * 1024 * 1024, 1),  # 2 MB → log2(2) = 1
            (1024 * 1024 * 1024, 10),  # 1 GB → log2(1024) = 10
        ],
    )
    def test_log_scale(self, make_metadata, file_size, expected_tier):
        v = make_metadata(file_size=file_size)
        assert _filesize_tier(v) == expected_tier

    def test_zero(self, make_metadata):
        v = make_metadata(file_size=0)
        assert _filesize_tier(v) == -1


# ---------------------------------------------------------------------------
# _refine_large_buckets
# ---------------------------------------------------------------------------


class TestRefineLargeBuckets:
    def test_small_untouched(self, make_metadata):
        bucket = [make_metadata(path=f"{i}.mp4") for i in range(5)]
        result = _refine_large_buckets([bucket], max_pairs=100)
        assert len(result) == 1
        assert result[0] is bucket

    def test_splits_large(self, make_metadata):
        # Create a large bucket with varied resolutions, 2 items per resolution+size combo
        items = []
        for i in range(100):
            if i < 50:
                items.append(make_metadata(path=f"{i}.mp4", width=1920, height=1080, file_size=(i + 1) * 1024 * 1024))
            else:
                items.append(make_metadata(path=f"{i}.mp4", width=1280, height=720, file_size=(i + 1) * 1024 * 1024))

        result = _refine_large_buckets([items], max_pairs=10)
        # Should be split into sub-buckets
        assert len(result) > 1
        # Sub-bucketing may drop single-item sub-buckets
        total_items = sum(len(b) for b in result)
        assert total_items >= 98  # nearly all items preserved


# ---------------------------------------------------------------------------
# _pair_key
# ---------------------------------------------------------------------------


class TestPairKey:
    def test_canonical_order(self, make_metadata):
        a = make_metadata(path="aaa.mp4")
        b = make_metadata(path="zzz.mp4")
        assert _pair_key(a, b) == (Path("aaa.mp4"), Path("zzz.mp4"))
        assert _pair_key(b, a) == (Path("aaa.mp4"), Path("zzz.mp4"))

    def test_same_path(self, make_metadata):
        a = make_metadata(path="same.mp4")
        b = make_metadata(path="same.mp4")
        key = _pair_key(a, b)
        assert key[0] == key[1]


# ---------------------------------------------------------------------------
# _score_pair
# ---------------------------------------------------------------------------


class TestScorePair:
    def test_full_match(self, make_metadata):
        a = make_metadata(path="movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        b = make_metadata(path="movie.mkv", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score == 100.0

    def test_early_exit(self, make_metadata):
        a = make_metadata(path="aaa.mp4", duration=10.0, width=320, height=240, file_size=100)
        b = make_metadata(path="zzz.mp4", duration=9999.0, width=3840, height=2160, file_size=99_999_999)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators, threshold=99.0)
        assert result is None

    def test_rounding(self, make_metadata):
        a = make_metadata(path="movie_2020.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        b = make_metadata(path="movie_2020_v2.mp4", duration=121.0, width=1920, height=1080, file_size=900_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        # Check score is rounded to 1 decimal
        assert result.total_score == round(result.total_score, 1)
        for val in result.breakdown.values():
            assert val is not None
            assert val == round(val, 1)

    def test_identical_name_and_size_scores_100(self, make_metadata):
        """Same filename + same file size → 100 even with missing metadata."""
        a = make_metadata(path="dir_a/video.mp4", duration=None, width=None, height=None, file_size=5_000_000)
        b = make_metadata(path="dir_b/video.mp4", duration=None, width=None, height=None, file_size=5_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score == 100.0

    def test_identical_heuristic_normalized(self, make_metadata):
        """Heuristic uses normalized filenames — case/separator differences don't matter."""
        a = make_metadata(filename="My.Movie", file_size=5_000_000, duration=None, width=None, height=None)
        b = make_metadata(filename="my movie", file_size=5_000_000, duration=None, width=None, height=None)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score == 100.0

    def test_identical_name_different_size_no_override(self, make_metadata):
        """Same filename but different file size → normal scoring."""
        a = make_metadata(path="dir_a/video.mp4", duration=120.0, width=1920, height=1080, file_size=5_000_000)
        b = make_metadata(path="dir_b/video.mp4", duration=120.0, width=1920, height=1080, file_size=3_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score < 100.0

    def test_different_name_identical_size_no_override(self, make_metadata):
        """Different filename but same file size → normal scoring (no 100 override)."""
        a = make_metadata(path="my_holiday.mp4", duration=120.0, width=1920, height=1080, file_size=5_000_000)
        b = make_metadata(path="my_holiday_extended.mp4", duration=120.0, width=1920, height=1080, file_size=5_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score < 100.0

    def test_identical_name_zero_size_no_override(self, make_metadata):
        """Same filename but zero file size → not treated as identical."""
        a = make_metadata(path="dir_a/empty.mp4", duration=None, width=None, height=None, file_size=0)
        b = make_metadata(path="dir_b/empty.mp4", duration=None, width=None, height=None, file_size=0)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score < 100.0

    def test_identical_heuristic_bypasses_threshold(self, make_metadata):
        """Identical name+size pair survives even a high threshold."""
        a = make_metadata(path="dir_a/video.mp4", duration=None, width=None, height=None, file_size=5_000_000)
        b = make_metadata(path="dir_b/video.mp4", duration=None, width=None, height=None, file_size=5_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators, threshold=99.0)
        assert result is not None
        assert result.total_score == 100.0

    def test_filename_gate_rejects_low_similarity(self, make_metadata):
        """Dissimilar filenames are rejected even with perfect metadata match."""
        a = make_metadata(path="alpha.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        b = make_metadata(path="zzzzz.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        comparators = get_default_comparators()
        # Without the gate this would score ~65 (0 filename + 35 duration + 15 res + 15 size)
        result = _score_pair(a, b, comparators)
        assert result is None

    def test_filename_gate_passes_high_similarity(self, make_metadata):
        """Similar filenames pass the gate and score normally."""
        a = make_metadata(path="my_movie_2020.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        b = make_metadata(path="my_movie_2020_copy.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score > 80.0

    def test_filename_gate_bypassed_by_identical_heuristic(self, make_metadata):
        """Identical name+size heuristic takes priority over filename gate."""
        # This shouldn't trigger the gate since identical=True, but verify
        a = make_metadata(path="dir_a/video.mp4", duration=None, width=None, height=None, file_size=5_000_000)
        b = make_metadata(path="dir_b/video.mp4", duration=None, width=None, height=None, file_size=5_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score == 100.0

    def test_filename_gate_threshold_value(self):
        """Verify the filename gate constant is set to 60%."""
        assert _MIN_FILENAME_RATIO == 0.6

    def test_filename_gate_disabled_with_content_comparators(self, make_metadata):
        """With content comparators, dissimilar filenames pass the gate."""
        a = make_metadata(
            path="alpha.mp4",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
        )
        b = make_metadata(
            path="zzzzz.mp4",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
        )
        comparators = get_content_comparators()
        # Without has_content this would be rejected by filename gate.
        # With content comparators, the pair should pass and score > 0.
        result = _score_pair(a, b, comparators, has_content=True)
        assert result is not None
        assert result.total_score > 0

    def test_filename_gate_still_active_without_content(self, make_metadata):
        """Without content comparators, filename gate still rejects dissimilar names."""
        a = make_metadata(path="alpha.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        b = make_metadata(path="zzzzz.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators, has_content=False)
        assert result is None

    def test_filename_gate_active_when_content_hash_missing(self, make_metadata):
        """Content mode keeps the gate when either file lacks a content hash."""
        a = make_metadata(
            path="alpha.mp4",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
        )
        b = make_metadata(
            path="zzzzz.mp4",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            content_hash=None,  # hash extraction failed
        )
        comparators = get_content_comparators()
        result = _score_pair(a, b, comparators, has_content=True)
        assert result is None  # gate should reject — no content signal available


# ---------------------------------------------------------------------------
# Byte-identical fast path
# ---------------------------------------------------------------------------


class TestByteIdentical:
    def test_identical_pre_hash_and_size_scores_100(self, make_metadata, tmp_path):
        """Identical pre_hash + same file_size → SHA-256 verified → score 100."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        content = b"identical file content for sha256 test"
        p1.write_bytes(content)
        p2.write_bytes(content)

        a = make_metadata(path=str(p1), pre_hash="samehash", file_size=len(content))
        b = make_metadata(path=str(p2), pre_hash="samehash", file_size=len(content))
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        assert result is not None
        assert result.total_score == 100.0
        assert "byte_identical" in result.breakdown
        assert result.breakdown["byte_identical"] == 100.0
        assert "byte_identical" in result.detail
        assert result.detail["byte_identical"] == (1.0, 100.0)

    def test_different_sha256_falls_through(self, make_metadata, tmp_path):
        """Same pre_hash + same size but different content → falls through to normal scoring."""
        p1 = tmp_path / "movie.mp4"
        p2 = tmp_path / "movie.mkv"
        # Same length, different content
        p1.write_bytes(b"AAAAAAAAAA")
        p2.write_bytes(b"BBBBBBBBBB")

        a = make_metadata(path=str(p1), filename="movie", pre_hash="samehash", file_size=10, duration=120.0)
        b = make_metadata(path=str(p2), filename="movie", pre_hash="samehash", file_size=10, duration=120.0)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        # Falls through to normal scoring — "byte_identical" not in breakdown
        assert result is not None
        assert "byte_identical" not in result.breakdown

    def test_different_pre_hash_skips_sha256(self, make_metadata, tmp_path):
        """Different pre_hash → SHA-256 check skipped entirely."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(b"content")
        p2.write_bytes(b"content")

        a = make_metadata(path=str(p1), pre_hash="hash_a", file_size=7)
        b = make_metadata(path=str(p2), pre_hash="hash_b", file_size=7)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        # No byte_identical since pre-hashes differ
        if result is not None:
            assert "byte_identical" not in result.breakdown

    def test_different_sizes_skips_sha256(self, make_metadata, tmp_path):
        """Different file sizes → SHA-256 check skipped."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(b"short")
        p2.write_bytes(b"longer content")

        a = make_metadata(path=str(p1), pre_hash="samehash", file_size=5)
        b = make_metadata(path=str(p2), pre_hash="samehash", file_size=14)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        if result is not None:
            assert "byte_identical" not in result.breakdown

    def test_none_pre_hash_skips_sha256(self, make_metadata, tmp_path):
        """None pre_hash → SHA-256 check skipped."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(b"content")
        p2.write_bytes(b"content")

        a = make_metadata(path=str(p1), pre_hash=None, file_size=7)
        b = make_metadata(path=str(p2), pre_hash=None, file_size=7)
        comparators = get_default_comparators()
        result = _score_pair(a, b, comparators)
        if result is not None:
            assert "byte_identical" not in result.breakdown

    def test_sha256_lookup_is_used(self, make_metadata, tmp_path):
        """Pre-loaded SHA-256 lookup avoids re-reading files."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.write_bytes(b"content")
        p2.write_bytes(b"content")

        a = make_metadata(path=str(p1), pre_hash="samehash", file_size=7)
        b = make_metadata(path=str(p2), pre_hash="samehash", file_size=7)
        comparators = get_default_comparators()

        # Provide matching SHA-256 in lookup — files won't be read
        sha = "aaaa" * 16
        lookup = {Path(str(p1)): sha, Path(str(p2)): sha}
        result = _score_pair(a, b, comparators, sha256_lookup=lookup)
        assert result is not None
        assert result.total_score == 100.0
        assert "byte_identical" in result.detail

    def test_io_error_falls_through(self, make_metadata, tmp_path):
        """OSError during SHA-256 computation → falls through to normal scoring."""
        # Use non-existent paths to trigger OSError
        a = make_metadata(path="/nonexistent/a.mp4", pre_hash="samehash", file_size=100)
        b = make_metadata(path="/nonexistent/b.mp4", pre_hash="samehash", file_size=100)
        comparators = get_default_comparators()
        # Should not raise — falls through to normal scoring
        result = _score_pair(a, b, comparators)
        if result is not None:
            assert "byte_identical" not in result.breakdown


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------


class TestFindDuplicates:
    def test_empty_input(self):
        assert find_duplicates([]) == []

    def test_single_item(self, make_metadata):
        assert find_duplicates([make_metadata()]) == []

    def test_serial(self, make_metadata):
        # Use identical filenames (different paths) for a perfect match
        items = [
            make_metadata(path="dir_a/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
        ]
        results = find_duplicates(items, workers=1, threshold=50.0)
        assert len(results) >= 1
        assert results[0].total_score == 100.0

    def test_parallel_matches_serial(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=120.0, file_size=1_000_000),
            make_metadata(path="a_copy.mp4", duration=120.0, file_size=1_000_000),
            make_metadata(path="b.mp4", duration=500.0, file_size=5_000_000),
            make_metadata(path="b_copy.mp4", duration=500.0, file_size=5_000_000),
        ]
        serial = find_duplicates(items, workers=1, threshold=50.0)
        parallel = find_duplicates(items, workers=2, threshold=50.0)
        # Same number of pairs
        assert len(serial) == len(parallel)
        # Same scores (order may differ slightly due to parallel execution, but sorted)
        serial_scores = sorted(p.total_score for p in serial)
        parallel_scores = sorted(p.total_score for p in parallel)
        assert serial_scores == parallel_scores

    def test_threshold_filter(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=120.0, file_size=1_000_000),
            make_metadata(path="b.mp4", duration=120.0, file_size=1_000_000),
        ]
        # Very high threshold → no results (unless perfect match)
        high = find_duplicates(items, workers=1, threshold=100.1)
        assert len(high) == 0

    def test_sorted_descending(self, make_metadata):
        items = [
            make_metadata(path="a.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="a_copy.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="a_similar.mp4", duration=121.0, width=1920, height=1080, file_size=900_000),
        ]
        results = find_duplicates(items, workers=1, threshold=10.0)
        scores = [p.total_score for p in results]
        assert scores == sorted(scores, reverse=True)

    def test_cross_bucket_filename_matching(self, make_metadata):
        # Same filename stem, very different durations → caught by filename pass
        items = [
            make_metadata(path="dir_a/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/movie.mkv", duration=999.0, width=1920, height=1080, file_size=2_000_000),
        ]
        results = find_duplicates(items, workers=1, threshold=10.0)
        # Filename similarity (100% match) should produce a match via cross-bucket pass
        assert len(results) >= 1

    def test_seen_pairs_deduplication(self, make_metadata):
        # Two identical videos should produce exactly one pair
        items = [
            make_metadata(path="movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="movie_dup.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
        ]
        results = find_duplicates(items, workers=1, threshold=10.0)
        # Should have exactly 1 pair, not duplicated
        pair_keys = set()
        for r in results:
            key = (str(r.file_a.path), str(r.file_b.path))
            norm_key = tuple(sorted(key))
            assert norm_key not in pair_keys, "Duplicate pair found"
            pair_keys.add(norm_key)

    def test_parallel_no_duplicate_pairs(self, make_metadata):
        """Parallel execution never produces duplicate pair keys."""
        items = [
            make_metadata(path="a.mp4", duration=120.0, file_size=1_000_000),
            make_metadata(path="a_copy.mp4", duration=120.0, file_size=1_000_000),
            make_metadata(path="b.mp4", duration=500.0, file_size=5_000_000),
            make_metadata(path="b_copy.mp4", duration=500.0, file_size=5_000_000),
        ]
        results = find_duplicates(items, workers=2, threshold=10.0)
        pair_keys = [_pair_key(p.file_a, p.file_b) for p in results]
        assert len(pair_keys) == len(set(pair_keys)), "Duplicate pairs in parallel results"


# ---------------------------------------------------------------------------
# Filename pass parallel vs serial consistency
# ---------------------------------------------------------------------------


class TestFilenamePassDedup:
    def test_parallel_matches_serial_pairs(self, make_metadata):
        """Parallel filename pass produces identical pair set to serial."""
        from duplicates_detector.comparators import normalize_filename

        items = [
            make_metadata(path=f"movie_{i}.mp4", duration=float(i * 100), file_size=i * 1_000_000 + 1)
            for i in range(10)
        ]
        normalized = [normalize_filename(m.path.name) for m in items]
        bucketed_pairs: set[tuple[Path, Path]] = set()
        comparators = get_default_comparators()

        serial = _filename_pass_serial(
            items,
            normalized,
            bucketed_pairs,
            comparators,
            threshold=10.0,
        )
        parallel = _filename_pass_parallel(
            items,
            normalized,
            bucketed_pairs,
            threshold=10.0,
            workers=2,
            comparators=comparators,
        )

        serial_pairs, serial_eval_keys, _serial_cached = serial
        parallel_pairs, parallel_eval_keys, _parallel_cached = parallel
        serial_keys = {_pair_key(p.file_a, p.file_b) for p in serial_pairs}
        parallel_keys = {_pair_key(p.file_a, p.file_b) for p in parallel_pairs}
        assert serial_keys == parallel_keys
        assert serial_eval_keys == parallel_eval_keys

    def test_parallel_no_duplicate_keys(self, make_metadata):
        """Parallel filename pass output contains no duplicate pair keys."""
        from duplicates_detector.comparators import normalize_filename

        items = [
            make_metadata(path=f"movie_{i}.mp4", duration=float(i * 100), file_size=i * 1_000_000 + 1)
            for i in range(10)
        ]
        normalized = [normalize_filename(m.path.name) for m in items]
        bucketed_pairs: set[tuple[Path, Path]] = set()
        comparators = get_default_comparators()

        results, _eval_keys, _cached = _filename_pass_parallel(
            items,
            normalized,
            bucketed_pairs,
            threshold=10.0,
            workers=2,
            comparators=comparators,
        )
        pair_keys = [_pair_key(p.file_a, p.file_b) for p in results]
        assert len(pair_keys) == len(set(pair_keys)), "Duplicate pairs in parallel filename pass"


# ---------------------------------------------------------------------------
# find_duplicates with custom comparators
# ---------------------------------------------------------------------------


class TestFindDuplicatesWithCustomComparators:
    def test_custom_comparators_used(self, make_metadata):
        """Custom comparator list produces breakdown keys matching those comparators."""
        from duplicates_detector.comparators import ContentComparator, get_content_comparators

        items = [
            make_metadata(
                path="movie.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
            make_metadata(
                path="movie_dup.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
        ]
        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=10.0, comparators=comparators)
        assert len(results) >= 1
        assert "content" in results[0].breakdown

    def test_custom_comparators_parallel(self, make_metadata):
        """Parallel path also uses the custom comparator list."""
        from duplicates_detector.comparators import get_content_comparators

        items = [
            make_metadata(
                path="movie.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
            make_metadata(
                path="movie_dup.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
        ]
        comparators = get_content_comparators()
        serial = find_duplicates(items, workers=1, threshold=10.0, comparators=comparators)
        parallel = find_duplicates(items, workers=2, threshold=10.0, comparators=comparators)
        assert len(serial) == len(parallel)
        for s, p in zip(serial, parallel):
            assert s.total_score == pytest.approx(p.total_score, abs=0.1)
            assert "content" in p.breakdown

    def test_cross_bucket_content_mode_finds_renamed_files(self, make_metadata):
        """In content mode, renamed files with different durations are still found.

        Without the fix, these would be in different duration buckets and fail
        the 80% filename cutoff in the cross-bucket pass, never reaching scoring.
        """
        from duplicates_detector.comparators import get_content_comparators

        identical_hash = (0xABCD, 0x1234, 0x5678, 0x9ABC)
        items = [
            make_metadata(
                path="beach_vacation.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=identical_hash,
            ),
            make_metadata(
                path="summer_trip.mp4",
                duration=150.0,
                width=1920,
                height=1080,
                file_size=1_200_000,
                content_hash=identical_hash,
            ),
        ]
        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=10.0, comparators=comparators)
        assert len(results) >= 1
        assert results[0].breakdown.get("content") is not None

    def test_cross_bucket_default_mode_requires_filename_match(self, make_metadata):
        """Without content mode, different names + different durations → no match.

        Regression guard: the cross-bucket pass still requires filename similarity
        in metadata-only mode to avoid false positives.
        """
        items = [
            make_metadata(
                path="beach_vacation.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
            ),
            make_metadata(
                path="summer_trip.mp4",
                duration=150.0,
                width=1920,
                height=1080,
                file_size=1_200_000,
            ),
        ]
        results = find_duplicates(items, workers=1, threshold=10.0)
        assert len(results) == 0

    def test_cross_bucket_content_no_duplicate_pairs(self, make_metadata):
        """Similar names + content hashes + different buckets → found once, not twice.

        Pass 2 (filename) finds them via name similarity; Pass 3 (content)
        should skip them because their key is already in seen_pairs.
        """
        from duplicates_detector.comparators import get_content_comparators

        items = [
            make_metadata(
                path="beach_vacation_2024.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
            make_metadata(
                path="beach_vacation_2024_copy.mp4",
                duration=150.0,
                width=1920,
                height=1080,
                file_size=1_200_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
        ]
        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=10.0, comparators=comparators)
        # Should be found exactly once (by filename pass), not duplicated by content pass
        assert len(results) == 1

    def test_cross_bucket_content_mode_missing_hash_uses_filename_cutoff(self, make_metadata):
        """In content mode, pairs where either file has no content hash
        fall back to the 80% filename cutoff — the zero threshold only
        applies when both files have usable hashes.
        """
        from duplicates_detector.comparators import get_content_comparators

        items = [
            make_metadata(
                path="beach_vacation.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=None,  # extraction failed
            ),
            make_metadata(
                path="summer_trip.mp4",
                duration=150.0,
                width=1920,
                height=1080,
                file_size=1_200_000,
                content_hash=None,  # extraction failed
            ),
        ]
        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=10.0, comparators=comparators)
        # Different names, no content hashes → should NOT match (80% cutoff applies)
        assert len(results) == 0

    def test_content_pass_parallel_matches_serial(self, make_metadata):
        """Parallel content pass produces the same results as serial."""
        from duplicates_detector.comparators import get_content_comparators

        items = [
            make_metadata(
                path="totally_different.mp4",
                duration=120.0,
                width=1920,
                height=1080,
                file_size=1_000_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
            make_metadata(
                path="something_else.mp4",
                duration=150.0,
                width=1280,
                height=720,
                file_size=800_000,
                content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC),
            ),
            make_metadata(
                path="unrelated_video.mp4",
                duration=200.0,
                width=640,
                height=480,
                file_size=500_000,
                content_hash=(0xFFFF, 0xEEEE, 0xDDDD, 0xCCCC),
            ),
        ]
        comparators = get_content_comparators()
        serial = find_duplicates(items, workers=1, threshold=10.0, comparators=comparators)
        parallel = find_duplicates(items, workers=2, threshold=10.0, comparators=comparators)

        assert len(serial) == len(parallel)
        serial_keys = {(_pair_key(p.file_a, p.file_b), p.total_score) for p in serial}
        parallel_keys = {(_pair_key(p.file_a, p.file_b), p.total_score) for p in parallel}
        assert serial_keys == parallel_keys


# ---------------------------------------------------------------------------
# Filename gate disabled when weight=0
# ---------------------------------------------------------------------------


class TestFilenameGateWeightZero:
    def test_dissimilar_names_scored_when_filename_weight_zero(self):
        """When filename weight is 0, the filename gate should not reject pairs."""
        a = VideoMetadata(
            path=Path("/videos/completely_different.mp4"),
            filename="completely_different",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        b = VideoMetadata(
            path=Path("/videos/totally_unrelated.mp4"),
            filename="totally_unrelated",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        # Default comparators would gate on filename dissimilarity
        comps = get_default_comparators()
        result_default = _score_pair(a, b, comps, threshold=0.0)
        assert result_default is None  # Gate rejects

        # With filename weight=0, gate should be bypassed
        comps_zero = get_default_comparators()
        for c in comps_zero:
            if c.name == "filename":
                c.weight = 0.0
        result_zero = _score_pair(a, b, comps_zero, threshold=0.0)
        assert result_zero is not None  # Gate bypassed


# ---------------------------------------------------------------------------
# _bucket_by_resolution_tier — image mode bucketing
# ---------------------------------------------------------------------------


class TestBucketByResolutionTier:
    def test_groups_by_tier(self, make_metadata):
        from duplicates_detector.scorer import _bucket_by_resolution_tier

        items = [
            make_metadata(path="a.png", width=1920, height=1080),
            make_metadata(path="b.png", width=1920, height=1080),
            make_metadata(path="c.png", width=640, height=480),
            make_metadata(path="d.png", width=640, height=480),
        ]
        buckets = _bucket_by_resolution_tier(items)
        assert len(buckets) == 2

    def test_singles_dropped(self, make_metadata):
        from duplicates_detector.scorer import _bucket_by_resolution_tier

        items = [
            make_metadata(path="a.png", width=1920, height=1080),
            make_metadata(path="b.png", width=640, height=480),
        ]
        buckets = _bucket_by_resolution_tier(items)
        assert len(buckets) == 0  # each tier has only 1 item

    def test_unknown_resolution(self, make_metadata):
        from duplicates_detector.scorer import _bucket_by_resolution_tier

        items = [
            make_metadata(path="a.png", width=None, height=None),
            make_metadata(path="b.png", width=None, height=None),
        ]
        buckets = _bucket_by_resolution_tier(items)
        assert len(buckets) == 1


# ---------------------------------------------------------------------------
# find_duplicates — image mode
# ---------------------------------------------------------------------------


class TestFindDuplicatesImageMode:
    def test_image_mode(self, make_metadata):
        items = [
            make_metadata(path="dir_a/photo.png", duration=None, width=1920, height=1080, file_size=100_000),
            make_metadata(path="dir_b/photo.png", duration=None, width=1920, height=1080, file_size=100_000),
        ]
        # Use image comparators explicitly
        from duplicates_detector.comparators import get_image_comparators

        pairs = find_duplicates(items, threshold=0, comparators=get_image_comparators(), workers=1, mode="image")
        assert len(pairs) >= 1

    def test_image_mode_includes_exif_comparator(self, make_metadata):
        """Image mode comparators include ExifComparator."""
        from duplicates_detector.comparators import get_image_comparators

        comps = get_image_comparators()
        names = {c.name for c in comps}
        assert "exif" in names

    def test_exif_weight_contributes_to_score(self, make_metadata):
        """EXIF comparator contributes to total score in image mode."""
        t = 1_700_000_000.0
        items = [
            make_metadata(
                path="dir_a/photo_x.png",
                duration=None,
                width=4000,
                height=3000,
                file_size=5_000_000,
                exif_datetime=t,
                exif_camera="canon eos r5",
            ),
            make_metadata(
                path="dir_b/photo_y.png",
                duration=None,
                width=4000,
                height=3000,
                file_size=5_000_000,
                exif_datetime=t,
                exif_camera="canon eos r5",
            ),
        ]
        from duplicates_detector.comparators import get_image_comparators

        pairs = find_duplicates(items, threshold=0, comparators=get_image_comparators(), workers=1, mode="image")
        assert len(pairs) >= 1
        # EXIF should contribute to breakdown
        pair = pairs[0]
        assert "exif" in pair.breakdown
        exif_score = pair.breakdown["exif"]
        assert exif_score is not None and exif_score > 0


# ---------------------------------------------------------------------------
# Filename gate with content_frames (SSIM mode)
# ---------------------------------------------------------------------------


class TestFilenameGateWithContentFrames:
    """Filename gate is disabled when content_frames are present (SSIM mode)."""

    def test_dissimilar_names_scored_with_content_frames(self, make_metadata):
        """Pairs with dissimilar names pass filename gate when content_frames are present."""
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()

        items = [
            make_metadata(path="alpha.mp4", duration=120.0, content_frames=(frame,)),
            make_metadata(path="zzzzz.mp4", duration=120.0, content_frames=(frame,)),
        ]
        from duplicates_detector.comparators import get_content_comparators

        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Pass 3 includes content_frames items
# ---------------------------------------------------------------------------


class TestPass3IncludesContentFrames:
    """Pass 3 (content all-pairs) includes items with content_frames."""

    def test_content_frames_items_included_in_pass3(self, make_metadata):
        """Items with content_frames (but no content_hash) are included in pass 3 all-pairs."""
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()

        # Different durations → different buckets, dissimilar names → skip pass 2
        # Only pass 3 (content all-pairs) can find them
        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, content_frames=(frame,)),
            make_metadata(path="file_bbb.mp4", duration=1000.0, content_frames=(frame,)),
        ]
        from duplicates_detector.comparators import get_content_comparators

        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        # Should find the pair via pass 3
        assert len(results) >= 1


class TestContentFramesStrippedAfterScoring:
    """content_frames is stripped from scored pairs to free memory."""

    def test_content_frames_none_in_results(self, make_metadata):
        """ScoredPair metadata should have content_frames=None after scoring."""
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()

        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, content_frames=(frame,)),
            make_metadata(path="file_bbb.mp4", duration=10.0, content_frames=(frame,)),
        ]
        from duplicates_detector.comparators import get_content_comparators

        comparators = get_content_comparators()
        results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        assert len(results) >= 1
        for pair in results:
            assert pair.file_a.content_frames is None
            assert pair.file_b.content_frames is None


class TestClipEmbeddingStrippedAfterScoring:
    """clip_embedding is stripped from scored pairs to free memory."""

    def test_clip_embedding_none_in_results(self, make_metadata):
        """ScoredPair metadata should have clip_embedding=None after scoring."""
        from unittest.mock import patch

        from duplicates_detector.comparators import get_content_comparators

        emb = tuple(float(i) * 0.01 for i in range(512))
        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, clip_embedding=emb),
            make_metadata(path="file_bbb.mp4", duration=10.0, clip_embedding=emb),
        ]
        comparators = get_content_comparators()
        with patch("duplicates_detector.clip.compare_clip_embeddings", return_value=0.95):
            results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        assert len(results) >= 1
        for pair in results:
            assert pair.file_a.clip_embedding is None
            assert pair.file_b.clip_embedding is None


class TestSsimForcesSerialScoring:
    """SSIM mode forces serial scoring to avoid IPC fan-out of frame blobs."""

    def test_workers_forced_serial_with_content_frames(self, make_metadata):
        """Passing workers>1 with content_frames still produces correct results (serial fallback)."""
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()

        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, content_frames=(frame,)),
            make_metadata(path="file_bbb.mp4", duration=10.0, content_frames=(frame,)),
        ]
        from duplicates_detector.comparators import get_content_comparators

        comparators = get_content_comparators()
        # workers=4 should be forced to serial — no ProcessPoolExecutor used
        results = find_duplicates(items, workers=4, threshold=0.0, comparators=comparators)
        assert len(results) >= 1
        # Frames still stripped from results
        for pair in results:
            assert pair.file_a.content_frames is None
            assert pair.file_b.content_frames is None

    def test_phash_still_uses_requested_workers(self, make_metadata):
        """content_hash (pHash) items do NOT force serial — workers pass-through."""
        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, content_hash=(123, 456, 789, 101)),
            make_metadata(path="file_bbb.mp4", duration=10.0, content_hash=(456, 789, 101, 202)),
        ]
        # Should work fine with workers>1 (no frame blobs to serialize)
        results = find_duplicates(items, workers=2, threshold=0.0)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# ScoredPair.detail
# ---------------------------------------------------------------------------


class TestScoredPairDetail:
    def test_detail_populated(self, make_metadata):
        """detail has entries after scoring a normal pair."""
        a = make_metadata(path="movie_a.mp4", duration=100.0)
        b = make_metadata(path="movie_b.mp4", duration=100.5)
        comps = get_default_comparators()
        pair = _score_pair(a, b, comps, threshold=0.0)
        assert pair is not None
        assert len(pair.detail) > 0

    def test_detail_keys_match_non_none_breakdown(self, make_metadata):
        """detail keys = breakdown keys where value is not None."""
        a = make_metadata(path="movie_a.mp4", duration=100.0)
        b = make_metadata(path="movie_b.mp4", duration=100.5)
        comps = get_default_comparators()
        pair = _score_pair(a, b, comps, threshold=0.0)
        assert pair is not None
        non_none_keys = {k for k, v in pair.breakdown.items() if v is not None}
        assert set(pair.detail.keys()) == non_none_keys

    def test_detail_none_comparators_excluded(self, make_metadata):
        """Comparators returning None are not in detail."""
        a = make_metadata(path="movie_a.mp4", duration=None, width=None, height=None)
        b = make_metadata(path="movie_b.mp4", duration=None, width=None, height=None)
        comps = get_default_comparators()
        pair = _score_pair(a, b, comps, threshold=0.0)
        assert pair is not None
        for name, val in pair.breakdown.items():
            if val is None:
                assert name not in pair.detail

    def test_detail_weighted_product_matches_breakdown(self, make_metadata):
        """round(raw * weight, 1) == breakdown[name] for each detail entry."""
        a = make_metadata(path="movie_a.mp4", duration=100.0)
        b = make_metadata(path="movie_b.mp4", duration=100.5)
        comps = get_default_comparators()
        pair = _score_pair(a, b, comps, threshold=0.0)
        assert pair is not None
        for name, (raw, weight) in pair.detail.items():
            assert round(raw * weight, 1) == pair.breakdown[name]

    def test_detail_identical_file_heuristic(self, make_metadata):
        """Identical files have detail populated and total_score=100."""
        a = make_metadata(path="movie_a.mp4", duration=100.0, file_size=1_000_000)
        b = make_metadata(path="movie_a.mp4", duration=100.0, file_size=1_000_000)
        comps = get_default_comparators()
        pair = _score_pair(a, b, comps, threshold=0.0)
        assert pair is not None
        assert pair.total_score == 100.0
        assert len(pair.detail) > 0

    def test_detail_tuple_contains_weight(self, make_metadata):
        """Each detail value is a (float, float) tuple."""
        a = make_metadata(path="movie_a.mp4", duration=100.0)
        b = make_metadata(path="movie_b.mp4", duration=100.5)
        comps = get_default_comparators()
        pair = _score_pair(a, b, comps, threshold=0.0)
        assert pair is not None
        for _name, vals in pair.detail.items():
            assert isinstance(vals, tuple)
            assert len(vals) == 2
            assert isinstance(vals[0], float)
            assert isinstance(vals[1], (int, float))


# ---------------------------------------------------------------------------
# Filename gate with audio fingerprints
# ---------------------------------------------------------------------------


class TestFilenameGateWithAudioFingerprint:
    """Filename gate is disabled when audio fingerprints are present."""

    def test_dissimilar_names_scored_with_audio_fingerprints(self, make_metadata):
        """Pairs with dissimilar names pass filename gate when audio_fingerprint is present."""
        from duplicates_detector.comparators import get_audio_comparators

        fp = tuple(range(50))
        items = [
            make_metadata(path="alpha.mp4", duration=120.0, audio_fingerprint=fp),
            make_metadata(path="zzzzz.mp4", duration=120.0, audio_fingerprint=fp),
        ]
        comparators = get_audio_comparators()
        results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        assert len(results) >= 1

    def test_audio_fingerprint_gate_still_active_when_missing(self, make_metadata):
        """Filename gate stays active when one file lacks audio fingerprint."""
        from duplicates_detector.comparators import get_audio_comparators

        fp = tuple(range(50))
        a = make_metadata(path="alpha.mp4", duration=120.0, width=1920, height=1080, audio_fingerprint=fp)
        b = make_metadata(path="zzzzz.mp4", duration=120.0, width=1920, height=1080, audio_fingerprint=None)
        comparators = get_audio_comparators()
        result = _score_pair(a, b, comparators, has_content=True)
        assert result is None


# ---------------------------------------------------------------------------
# Pass 3 includes audio fingerprint items
# ---------------------------------------------------------------------------


class TestPass3IncludesAudioFingerprint:
    """Pass 3 (content all-pairs) includes items with audio_fingerprint."""

    def test_audio_items_included_in_pass3(self, make_metadata):
        """Items with audio_fingerprint are included in pass 3 all-pairs."""
        from duplicates_detector.comparators import get_audio_comparators

        fp = tuple(range(50))
        # Different durations → different buckets, dissimilar names → skip pass 2
        # Only pass 3 (content all-pairs) can find them
        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, audio_fingerprint=fp),
            make_metadata(path="file_bbb.mp4", duration=1000.0, audio_fingerprint=fp),
        ]
        comparators = get_audio_comparators()
        results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        # Should find the pair via pass 3
        assert len(results) >= 1


class TestPass3IncludesClipEmbedding:
    """Pass 3 (content all-pairs) includes items with clip_embedding."""

    def test_clip_items_included_in_pass3(self, make_metadata):
        """Items with clip_embedding are included in pass 3 all-pairs."""
        from unittest.mock import patch

        from duplicates_detector.comparators import get_content_comparators

        emb = tuple(float(i) * 0.01 for i in range(512))
        # Different durations -> different buckets, dissimilar names -> skip pass 2
        # Only pass 3 (content all-pairs) can find them
        items = [
            make_metadata(path="file_aaa.mp4", duration=10.0, clip_embedding=emb),
            make_metadata(path="file_bbb.mp4", duration=1000.0, clip_embedding=emb),
        ]
        comparators = get_content_comparators()
        with patch("duplicates_detector.clip.compare_clip_embeddings", return_value=0.95):
            results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        # Should find the pair via pass 3
        assert len(results) >= 1

    def test_clip_embedding_satisfies_pair_has_content(self, make_metadata):
        """clip_embedding satisfies pair_has_content, bypassing filename gate."""
        from unittest.mock import patch

        from duplicates_detector.comparators import get_content_comparators

        emb = tuple(float(i) * 0.01 for i in range(512))
        # Dissimilar filenames with same duration (same bucket)
        # Without content, the filename gate (0.6 threshold) would block these
        items = [
            make_metadata(path="alpha.mp4", duration=10.0, clip_embedding=emb),
            make_metadata(path="omega.mp4", duration=10.0, clip_embedding=emb),
        ]
        comparators = get_content_comparators()
        with patch("duplicates_detector.clip.compare_clip_embeddings", return_value=0.99):
            results = find_duplicates(items, workers=1, threshold=0.0, comparators=comparators)
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Machine progress emission in scoring passes
# ---------------------------------------------------------------------------


class TestScoreProgressEmission:
    """Verify that --machine-progress emits incremental updates in passes 2 & 3."""

    def test_pass2_emits_incremental_progress(self, make_metadata, monkeypatch):
        """Pass 2 (filename cross-bucket) emits progress events instead of a single lump-sum."""
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        # Two files in different duration buckets but identical filenames → pass 2 match
        items = [
            make_metadata(path="dir_a/movie.mp4", duration=10.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/movie.mp4", duration=999.0, width=1920, height=1080, file_size=1_000_000),
        ]
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=10.0, progress_emitter=emitter)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines]
        score_progress = [e for e in events if e["type"] == "progress" and e["stage"] == "score"]

        # Should have multiple progress events (pass 1 bucket scoring + pass 2 incremental),
        # not just a single one at the end.
        assert len(score_progress) >= 2

    def test_pass2_progress_current_monotonically_increases(self, make_metadata, monkeypatch):
        """Score progress 'current' values never decrease across events."""
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        items = [
            make_metadata(path="dir_a/movie.mp4", duration=10.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/movie.mp4", duration=999.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_c/movie.mp4", duration=500.0, width=1280, height=720, file_size=800_000),
        ]
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=0.0, progress_emitter=emitter)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines]
        currents = [e["current"] for e in events if e["type"] == "progress" and e["stage"] == "score"]

        for i in range(1, len(currents)):
            assert currents[i] >= currents[i - 1], f"current decreased: {currents}"

    def test_pass3_serial_emits_incremental_progress(self, make_metadata, monkeypatch):
        """Pass 3 (content all-pairs) emits per-pair progress in serial mode."""
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        # Three files with content hashes in different buckets → pass 3 all-pairs
        items = [
            make_metadata(
                path="a.mp4", duration=10.0, content_hash=(0x1234, 0x5678, 0x9ABC, 0xDEF0), file_size=1_000_000
            ),
            make_metadata(
                path="b.mp4", duration=500.0, content_hash=(0x1234, 0x5678, 0x9ABC, 0xDEF0), file_size=1_100_000
            ),
            make_metadata(
                path="c.mp4", duration=900.0, content_hash=(0x5678, 0x9ABC, 0xDEF0, 0x1234), file_size=1_200_000
            ),
        ]
        comparators = get_content_comparators()
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=0.0, comparators=comparators, progress_emitter=emitter)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines]
        score_progress = [e for e in events if e["type"] == "progress" and e["stage"] == "score"]

        # Pass 3 has 3 files → 3 pairs. Progress events should include
        # incremental updates from within pass 3, not just a single final event.
        assert len(score_progress) >= 3

    def test_content_pass_serial_on_pair_callback(self, make_metadata):
        """_content_pass_serial fires on_pair for each evaluated (non-skipped) pair."""
        items = [
            make_metadata(path="x.mp4", duration=10.0, content_hash=(0xAAAA, 0xBBBB, 0xCCCC, 0xDDDD)),
            make_metadata(path="y.mp4", duration=20.0, content_hash=(0xBBBB, 0xCCCC, 0xDDDD, 0xEEEE)),
            make_metadata(path="z.mp4", duration=30.0, content_hash=(0xCCCC, 0xDDDD, 0xEEEE, 0xFFFF)),
        ]
        comparators = get_content_comparators()
        call_count = 0

        def _on_pair():
            nonlocal call_count
            call_count += 1

        _content_pass_serial(items, set(), comparators, threshold=0.0, on_pair=_on_pair)
        # 3 items → 3 pairs, none already seen
        assert call_count == 3

    def test_content_pass_serial_on_pair_skips_seen(self, make_metadata):
        """_content_pass_serial does not fire on_pair for already-seen pairs."""
        items = [
            make_metadata(path="x.mp4", duration=10.0, content_hash=(0xAAAA, 0xBBBB, 0xCCCC, 0xDDDD)),
            make_metadata(path="y.mp4", duration=20.0, content_hash=(0xBBBB, 0xCCCC, 0xDDDD, 0xEEEE)),
        ]
        comparators = get_content_comparators()
        call_count = 0

        def _on_pair():
            nonlocal call_count
            call_count += 1

        seen = {_pair_key(items[0], items[1])}
        _content_pass_serial(items, seen, comparators, threshold=0.0, on_pair=_on_pair)
        assert call_count == 0

    def test_stage_end_total_reports_actual_comparisons(self, make_metadata, monkeypatch):
        """stage_end total reports actual comparisons evaluated, not inflated progress units."""
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        items = [
            make_metadata(path="dir_a/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
        ]
        stats: dict[str, int] = {}
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=0.0, progress_emitter=emitter, stats=stats)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines]

        score_end = [e for e in events if e["type"] == "stage_end" and e["stage"] == "score"]
        assert len(score_end) == 1

        # stage_end.total must equal actual comparisons, not the progress counter
        assert score_end[0]["total"] == stats["total_pairs_scored"]

        # Progress counter may be >= actual comparisons (per-item increments in pass 2)
        score_progress = [e for e in events if e["type"] == "progress" and e["stage"] == "score"]
        if score_progress:
            last_progress = score_progress[-1]
            assert last_progress["current"] >= stats["total_pairs_scored"]

    def test_stage_end_total_with_cross_bucket_matches(self, make_metadata, monkeypatch):
        """Pass 2 cross-bucket filename matching inflates the progress counter
        (per-item increments) beyond the actual pair count. stage_end.total must
        report actual_pairs_evaluated, not the inflated total_scored counter."""
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        # 4 items across 2 duration buckets, all with similar filenames to trigger pass 2.
        # Bucket 1 (duration ~10s): 2 items → 1 pair in pass 1
        # Bucket 2 (duration ~500s): 2 items → 1 pair in pass 1
        # Pass 2 checks all 4 items for cross-bucket filename matches.
        # The progress counter increments once per item in pass 2 (4 increments),
        # but actual cross-bucket pairs found depends on filename similarity.
        items = [
            make_metadata(path="dir_a/concert.mp4", duration=10.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/concert_hd.mp4", duration=11.0, width=1920, height=1080, file_size=1_100_000),
            make_metadata(path="dir_c/concert_live.mp4", duration=500.0, width=1280, height=720, file_size=2_000_000),
            make_metadata(path="dir_d/concert_edit.mp4", duration=501.0, width=1280, height=720, file_size=2_100_000),
        ]
        stats: dict[str, int] = {}
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=0.0, progress_emitter=emitter, stats=stats)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines]

        score_end = [e for e in events if e["type"] == "stage_end" and e["stage"] == "score"]
        assert len(score_end) == 1

        # The key regression check: stage_end.total must equal actual comparisons,
        # not the inflated progress counter (which counts per-item in pass 2).
        assert score_end[0]["total"] == stats["total_pairs_scored"]

        # The progress counter is allowed to exceed actual_pairs_evaluated
        # because pass 2 increments per-item, not per-pair.
        score_progress = [e for e in events if e["type"] == "progress" and e["stage"] == "score"]
        if score_progress:
            last_current = score_progress[-1]["current"]
            assert last_current >= stats["total_pairs_scored"]

    def test_emit_score_stage_false_suppresses_stage_end(self, make_metadata, monkeypatch):
        """When _emit_score_stage=False, no stage_start or stage_end events are emitted.

        The async pipeline relies on this to avoid duplicate stage lifecycle events
        when the pipeline controller manages stage boundaries externally.
        """
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        items = [
            make_metadata(path="dir_a/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
            make_metadata(path="dir_b/movie.mp4", duration=120.0, width=1920, height=1080, file_size=1_000_000),
        ]
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=0.0, progress_emitter=emitter, _emit_score_stage=False)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines] if lines else []

        # No stage_start or stage_end for "score" should be emitted
        score_lifecycle = [e for e in events if e["stage"] == "score" and e["type"] in ("stage_start", "stage_end")]
        assert score_lifecycle == []

        # But progress events should still be emitted (granular progress is not suppressed)
        score_progress = [e for e in events if e["type"] == "progress" and e["stage"] == "score"]
        assert len(score_progress) > 0

    def test_stage_end_total_with_many_items(self, make_metadata, monkeypatch):
        """With n items in a single bucket, stage_end.total must equal n*(n-1)/2.

        A single bucket means no cross-bucket pass 2, so the progress counter
        and actual pair count should agree. This validates that the fix does not
        regress the simple single-bucket case at scale.
        """
        import json
        import sys
        from io import StringIO

        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        n = 6
        # All items share similar duration (same bucket) and similar filenames
        # to avoid the _MIN_FILENAME_RATIO gate dropping them.
        items = [
            make_metadata(
                path=f"dir_{i}/recording.mp4",
                duration=60.0 + i * 0.1,  # within ±2s tolerance → same bucket
                width=1920,
                height=1080,
                file_size=1_000_000 + i * 1000,
            )
            for i in range(n)
        ]
        stats: dict[str, int] = {}
        emitter = ProgressEmitter()
        find_duplicates(items, workers=1, threshold=0.0, progress_emitter=emitter, stats=stats)

        lines = buf.getvalue().strip().splitlines()
        events = [json.loads(line) for line in lines]

        score_end = [e for e in events if e["type"] == "stage_end" and e["stage"] == "score"]
        assert len(score_end) == 1

        expected_pairs = n * (n - 1) // 2  # 6*5/2 = 15
        assert stats["total_pairs_scored"] == expected_pairs
        assert score_end[0]["total"] == expected_pairs

    def test_per_pair_progress_accuracy(self, make_metadata):
        """Progress events should report actual pair counts, not chunk proxies."""
        # 5 items with same duration → one bucket, 10 pairs = 5*4/2
        items = [make_metadata(filename=f"v{i}", duration=10.0, path=f"v{i}.mp4") for i in range(5)]
        progress_events: list[dict] = []

        class FakeEmitter:
            def stage_start(self, *a, **kw):  # noqa: ARG002
                pass

            def stage_end(self, *a, **kw):  # noqa: ARG002
                pass

            def progress(self, stage, *, current, total=None, **kw):  # noqa: ARG002
                if stage == "score":
                    progress_events.append({"current": current, "total": total})

        find_duplicates(items, workers=1, progress_emitter=FakeEmitter())  # type: ignore[arg-type]

        assert len(progress_events) > 0
        last = progress_events[-1]
        # The last progress event's current should equal total (all pairs processed)
        assert last["current"] == last["total"]


# ---------------------------------------------------------------------------
# Scoring cache integration (find_duplicates + CacheDB round-trip)
# ---------------------------------------------------------------------------


class TestScoringCacheIntegration:
    """Tests for cache_db / config_hash integration in find_duplicates."""

    def test_find_duplicates_scoring_cache_roundtrip(self, make_metadata, tmp_path):
        """Scoring cache: first call writes, second call hits cache."""
        from duplicates_detector.cache_db import CacheDB
        from duplicates_detector.scorer import compute_config_hash

        cache = CacheDB(tmp_path / "cache")
        try:
            (tmp_path / "a.mp4").write_bytes(b"x")
            (tmp_path / "b.mp4").write_bytes(b"x")
            m1 = make_metadata(filename="video_a", duration=10.0, path=str(tmp_path / "a.mp4"))
            m2 = make_metadata(filename="video_a_copy", duration=10.0, path=str(tmp_path / "b.mp4"))
            ch = compute_config_hash({"filename": 50, "duration": 30, "resolution": 10, "file_size": 10})

            # First run -- cache miss, scores computed and written
            pairs1 = find_duplicates([m1, m2], workers=1, cache_db=cache, config_hash=ch)
            stats_after_first = cache.stats()

            # Second run -- should hit cache
            pairs2 = find_duplicates([m1, m2], workers=1, cache_db=cache, config_hash=ch)
            stats_after_second = cache.stats()

            assert len(pairs1) > 0
            assert len(pairs2) == len(pairs1)
            assert abs(pairs1[0].total_score - pairs2[0].total_score) < 0.01
            assert stats_after_second["score_hits"] > stats_after_first["score_hits"]
        finally:
            cache.close()

    def test_cache_not_used_when_not_provided(self, make_metadata, tmp_path):
        """find_duplicates works normally when cache_db is None."""
        (tmp_path / "a.mp4").write_bytes(b"x")
        (tmp_path / "b.mp4").write_bytes(b"x")
        m1 = make_metadata(filename="video_a", duration=10.0, path=str(tmp_path / "a.mp4"))
        m2 = make_metadata(filename="video_a_copy", duration=10.0, path=str(tmp_path / "b.mp4"))

        # No cache_db -- should work identically to before
        pairs = find_duplicates([m1, m2], workers=1)
        assert len(pairs) > 0

    def test_cached_pair_has_correct_detail(self, make_metadata, tmp_path):
        """Cached pairs reconstruct breakdown and detail correctly."""
        from duplicates_detector.cache_db import CacheDB
        from duplicates_detector.scorer import compute_config_hash

        cache = CacheDB(tmp_path / "cache")
        try:
            (tmp_path / "a.mp4").write_bytes(b"x")
            (tmp_path / "b.mp4").write_bytes(b"x")
            m1 = make_metadata(filename="video_a", duration=10.0, path=str(tmp_path / "a.mp4"))
            m2 = make_metadata(filename="video_a_copy", duration=10.0, path=str(tmp_path / "b.mp4"))
            ch = compute_config_hash({"filename": 50, "duration": 30, "resolution": 10, "file_size": 10})

            # First run -- writes to cache
            pairs1 = find_duplicates([m1, m2], workers=1, cache_db=cache, config_hash=ch)

            # Second run -- reads from cache
            pairs2 = find_duplicates([m1, m2], workers=1, cache_db=cache, config_hash=ch)

            assert len(pairs1) == len(pairs2)
            p1, p2 = pairs1[0], pairs2[0]
            # detail keys should match
            assert set(p1.detail.keys()) == set(p2.detail.keys())
            # breakdown keys should match
            assert set(p1.breakdown.keys()) == set(p2.breakdown.keys())
        finally:
            cache.close()

    def test_stale_mtime_causes_cache_miss(self, make_metadata, tmp_path):
        """Modified files (changed mtime) bypass the scoring cache."""
        import os
        from duplicates_detector.cache_db import CacheDB
        from duplicates_detector.scorer import compute_config_hash

        cache = CacheDB(tmp_path / "cache")
        try:
            (tmp_path / "a.mp4").write_bytes(b"x")
            (tmp_path / "b.mp4").write_bytes(b"x")
            m1 = make_metadata(filename="video_a", duration=10.0, path=str(tmp_path / "a.mp4"))
            m2 = make_metadata(filename="video_a_copy", duration=10.0, path=str(tmp_path / "b.mp4"))
            ch = compute_config_hash({"filename": 50, "duration": 30, "resolution": 10, "file_size": 10})

            # First run -- populates cache
            pairs1 = find_duplicates([m1, m2], workers=1, cache_db=cache, config_hash=ch)
            stats1 = cache.stats()
            assert stats1["score_hits"] == 0  # first run: no cache hits

            # Touch file to change mtime
            os.utime(tmp_path / "a.mp4", (9999999.0, 9999999.0))

            # Second run -- mtime changed so bulk lookup won't find the pair
            pairs2 = find_duplicates([m1, m2], workers=1, cache_db=cache, config_hash=ch)
            stats2 = cache.stats()

            # Stale mtime means the bulk lookup finds nothing -- no new hits
            assert stats2["score_hits"] == stats1["score_hits"]
            # But the pair is still found via fresh scoring
            assert len(pairs2) == len(pairs1)
        finally:
            cache.close()
