"""Tests for duplicates_detector.analytics."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from duplicates_detector.analytics import (
    AnalyticsResult,
    DirectoryStats,
    FiletypeEntry,
    ScoreBucket,
    TimelineEntry,
    analytics_to_dict,
    compute_analytics,
    compute_creation_timeline,
    compute_directory_stats,
    compute_filetype_breakdown,
    compute_score_distribution,
)
from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair


def _pair(
    path_a: str,
    path_b: str,
    score: float,
    *,
    size_a: int = 1000,
    size_b: int = 500,
    mtime_a: float | None = None,
    mtime_b: float | None = None,
) -> ScoredPair:
    from duplicates_detector.metadata import VideoMetadata

    meta_a = VideoMetadata(
        path=Path(path_a),
        filename=Path(path_a).stem,
        duration=None,
        width=None,
        height=None,
        file_size=size_a,
        codec=None,
        bitrate=None,
        framerate=None,
        audio_channels=None,
        mtime=mtime_a,
    )
    meta_b = VideoMetadata(
        path=Path(path_b),
        filename=Path(path_b).stem,
        duration=None,
        width=None,
        height=None,
        file_size=size_b,
        codec=None,
        bitrate=None,
        framerate=None,
        audio_channels=None,
        mtime=mtime_b,
    )
    return ScoredPair(
        file_a=meta_a,
        file_b=meta_b,
        total_score=score,
        breakdown={"filename": score},
        detail={"filename": (score / 100.0, 100)},
    )


class TestScoreDistribution:
    def test_basic_buckets(self):
        pairs = [
            _pair("/a/1.mp4", "/b/1.mp4", 52.0),
            _pair("/a/2.mp4", "/b/2.mp4", 57.0),
            _pair("/a/3.mp4", "/b/3.mp4", 93.0),
        ]
        result = compute_score_distribution(pairs)
        assert isinstance(result, tuple)
        by_range = {b.range: b.count for b in result}
        assert by_range["50-55"] == 1
        assert by_range["55-60"] == 1
        assert by_range["90-95"] == 1

    def test_score_100_in_last_bucket(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 100.0)]
        result = compute_score_distribution(pairs)
        assert result[-1].count == 1
        assert result[-1].min <= 100

    def test_scores_below_50(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 23.0)]
        result = compute_score_distribution(pairs)
        assert result[0].min <= 23

    def test_empty_pairs(self):
        result = compute_score_distribution([])
        assert result == ()


class TestFiletypeBreakdown:
    def test_groups_by_extension(self):
        pairs = [
            _pair("/a/vid.mp4", "/b/vid2.mp4", 80.0),
            _pair("/a/pic.jpg", "/b/pic2.jpg", 70.0),
        ]
        result = compute_filetype_breakdown(pairs)
        exts = {e.extension: e.count for e in result}
        assert exts[".mp4"] == 2
        assert exts[".jpg"] == 2

    def test_deduplicates_files(self):
        pairs = [
            _pair("/a/vid.mp4", "/b/vid2.mp4", 80.0),
            _pair("/a/vid.mp4", "/c/vid3.mp4", 70.0),
        ]
        result = compute_filetype_breakdown(pairs)
        exts = {e.extension: e.count for e in result}
        assert exts[".mp4"] == 3

    def test_empty(self):
        assert compute_filetype_breakdown([]) == ()


class TestCreationTimeline:
    def test_groups_by_date(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 80.0, mtime_a=1705276800.0, mtime_b=1705276800.0)]
        result = compute_creation_timeline(pairs)
        assert len(result) == 1
        assert result[0].date == "2024-01-15"
        assert result[0].total_files == 2

    def test_no_mtime_excluded(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 80.0)]
        result = compute_creation_timeline(pairs)
        assert result == ()

    def test_sorted_chronologically(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 80.0, mtime_a=1705363200.0, mtime_b=1705276800.0)]
        result = compute_creation_timeline(pairs)
        dates = [e.date for e in result]
        assert dates == sorted(dates)

    def test_timeline_with_all_paths_separates_totals(self, tmp_path: Path):
        """When all_paths is provided, total_files reflects the full directory
        population while duplicate_files counts only pair-sourced files."""
        # Use a fixed mtime: 2024-01-15 00:00:00 UTC.
        target_mtime = 1705276800.0

        # Create 5 temporary files all with the same mtime.
        files: list[Path] = []
        for i in range(5):
            f = tmp_path / f"file{i}.mp4"
            f.write_bytes(b"x")
            os.utime(f, (target_mtime, target_mtime))
            files.append(f)

        # Pairs reference only the first 2 files.
        pairs = [_pair(str(files[0]), str(files[1]), 80.0, mtime_a=target_mtime, mtime_b=target_mtime)]
        all_paths = set(files)

        result = compute_creation_timeline(pairs, all_paths=all_paths)
        assert len(result) == 1
        assert result[0].date == "2024-01-15"
        assert result[0].total_files == 5
        assert result[0].duplicate_files == 2

    def test_timeline_without_all_paths_equals_totals(self):
        """Without all_paths, total_files equals duplicate_files (backward compat)."""
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 80.0, mtime_a=1705276800.0, mtime_b=1705276800.0)]
        result = compute_creation_timeline(pairs)
        assert len(result) == 1
        assert result[0].total_files == result[0].duplicate_files

    def test_timeline_all_paths_days_without_duplicates(self, tmp_path: Path):
        """Days with scanned files but no duplicates show total_files > 0
        and duplicate_files == 0."""
        # Day with duplicates: 2024-01-15.
        dup_mtime = 1705276800.0
        # Day without duplicates: 2024-01-20.
        no_dup_mtime = 1705708800.0

        # Create files for both days.
        dup_file_a = tmp_path / "dup_a.mp4"
        dup_file_b = tmp_path / "dup_b.mp4"
        solo_file = tmp_path / "solo.mp4"
        for f, mt in [(dup_file_a, dup_mtime), (dup_file_b, dup_mtime), (solo_file, no_dup_mtime)]:
            f.write_bytes(b"x")
            os.utime(f, (mt, mt))

        pairs = [_pair(str(dup_file_a), str(dup_file_b), 80.0, mtime_a=dup_mtime, mtime_b=dup_mtime)]
        all_paths = {dup_file_a, dup_file_b, solo_file}

        result = compute_creation_timeline(pairs, all_paths=all_paths)
        by_date = {e.date: e for e in result}

        # Day with duplicates.
        assert by_date["2024-01-15"].total_files == 2
        assert by_date["2024-01-15"].duplicate_files == 2

        # Day without duplicates — solo file appears in total but not duplicates.
        assert by_date["2024-01-20"].total_files == 1
        assert by_date["2024-01-20"].duplicate_files == 0


class TestDirectoryStats:
    def test_basic_per_directory(self):
        pairs = [_pair("/downloads/a.mp4", "/backup/a.mp4", 80.0, size_a=1000, size_b=500)]
        result = compute_directory_stats(pairs)
        by_path = {d.path: d for d in result}
        assert "/downloads" in by_path
        assert "/backup" in by_path

    def test_density_without_all_paths(self):
        pairs = [_pair("/downloads/a.mp4", "/downloads/b.mp4", 80.0)]
        result = compute_directory_stats(pairs)
        assert result[0].duplicate_density == 1.0

    def test_density_with_all_paths(self):
        pairs = [_pair("/downloads/a.mp4", "/downloads/b.mp4", 80.0)]
        all_paths = {
            Path("/downloads/a.mp4"),
            Path("/downloads/b.mp4"),
            Path("/downloads/c.mp4"),
            Path("/downloads/d.mp4"),
        }
        result = compute_directory_stats(pairs, all_paths=all_paths)
        assert result[0].total_files == 4
        assert result[0].duplicate_files == 2
        assert result[0].duplicate_density == pytest.approx(0.5)

    def test_recoverable_not_double_counted(self):
        pairs = [
            _pair("/a/small.mp4", "/b/big.mp4", 80.0, size_a=500, size_b=1000),
            _pair("/a/small.mp4", "/c/big2.mp4", 70.0, size_a=500, size_b=1000),
        ]
        result = compute_directory_stats(pairs)
        by_path = {d.path: d for d in result}
        assert by_path["/a"].recoverable_size == 500

    def test_empty(self):
        assert compute_directory_stats([]) == ()

    def test_recoverable_with_groups_and_keep_strategy(self):
        """Group-aware recoverable: keep_strategy='biggest' keeps the largest,
        marking all other non-reference members as recoverable.

        With sizes {10MB, 100MB, 50MB}, 'biggest' unambiguously keeps 100MB,
        so both 10MB and 50MB (60MB total) are recoverable.  The pair-level
        heuristic would only see 10MB recoverable from the first pair."""
        small = _pair("/data/small.mp4", "/data/large.mp4", 85.0, size_a=10_000_000, size_b=100_000_000)
        medium_pair = _pair("/data/large.mp4", "/data/medium.mp4", 90.0, size_a=100_000_000, size_b=50_000_000)

        # Build a group with 3 members: small(10MB), large(100MB), medium(50MB).
        members = (small.file_a, small.file_b, medium_pair.file_b)
        group = DuplicateGroup(
            group_id=1,
            members=members,
            pairs=(small, medium_pair),
            max_score=90.0,
            min_score=85.0,
            avg_score=87.5,
        )

        pairs = [small, medium_pair]
        result = compute_directory_stats(pairs, groups=[group], keep_strategy="biggest")
        by_path = {d.path: d for d in result}

        # With "biggest", the 100MB file is kept; 10MB + 50MB = 60MB recoverable.
        assert by_path["/data"].recoverable_size == 60_000_000

    def test_recoverable_falls_back_to_pair_heuristic(self):
        """Without groups or keep_strategy, the pair-level heuristic is used
        (smaller endpoint per pair marked as recoverable)."""
        pairs = [_pair("/a/small.mp4", "/a/big.mp4", 80.0, size_a=500, size_b=1000)]

        # groups=None → pair heuristic: small(500) is recoverable.
        result_no_groups = compute_directory_stats(pairs, groups=None, keep_strategy="biggest")
        assert result_no_groups[0].recoverable_size == 500

        # keep_strategy=None → pair heuristic.
        result_no_strategy = compute_directory_stats(
            pairs,
            groups=[
                DuplicateGroup(
                    group_id=1,
                    members=(pairs[0].file_a, pairs[0].file_b),
                    pairs=(pairs[0],),
                    max_score=80.0,
                    min_score=80.0,
                    avg_score=80.0,
                )
            ],
            keep_strategy=None,
        )
        assert result_no_strategy[0].recoverable_size == 500

    def test_recoverable_with_groups_reference_aware(self):
        """Reference files are never counted as recoverable in group mode,
        even when they are not the keeper.

        Group has 3 members: reference(200KB), big_copy(150KB), small_copy(100KB).
        keep_strategy='biggest' picks big_copy as keeper among non-ref members.
        small_copy is recoverable. Reference is protected (not recoverable)."""
        ref_meta = VideoMetadata(
            path=Path("/ref/master.mp4"),
            filename="master",
            duration=None,
            width=None,
            height=None,
            file_size=200_000,
            codec=None,
            bitrate=None,
            framerate=None,
            audio_channels=None,
            mtime=None,
            is_reference=True,
        )
        big_copy = VideoMetadata(
            path=Path("/data/big_copy.mp4"),
            filename="big_copy",
            duration=None,
            width=None,
            height=None,
            file_size=150_000,
            codec=None,
            bitrate=None,
            framerate=None,
            audio_channels=None,
            mtime=None,
        )
        small_copy = VideoMetadata(
            path=Path("/data/small_copy.mp4"),
            filename="small_copy",
            duration=None,
            width=None,
            height=None,
            file_size=100_000,
            codec=None,
            bitrate=None,
            framerate=None,
            audio_channels=None,
            mtime=None,
        )
        pair_ref_big = ScoredPair(
            file_a=ref_meta,
            file_b=big_copy,
            total_score=85.0,
            breakdown={"filename": 85.0},
            detail={"filename": (0.85, 100)},
        )
        pair_ref_small = ScoredPair(
            file_a=ref_meta,
            file_b=small_copy,
            total_score=80.0,
            breakdown={"filename": 80.0},
            detail={"filename": (0.80, 100)},
        )
        group = DuplicateGroup(
            group_id=1,
            members=(ref_meta, big_copy, small_copy),
            pairs=(pair_ref_big, pair_ref_small),
            max_score=85.0,
            min_score=80.0,
            avg_score=82.5,
        )

        result = compute_directory_stats([pair_ref_big, pair_ref_small], groups=[group], keep_strategy="biggest")
        by_path = {d.path: d for d in result}

        # Reference (200KB) must NOT be recoverable.
        assert by_path["/ref"].recoverable_size == 0
        # big_copy(150KB) is keeper → not recoverable. small_copy(100KB) → recoverable.
        assert by_path["/data"].recoverable_size == 100_000


class TestComputeAnalytics:
    def test_returns_analytics_result(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 80.0)]
        result = compute_analytics(pairs)
        assert isinstance(result, AnalyticsResult)
        assert len(result.directory_stats) > 0
        assert len(result.score_distribution) > 0


class TestAnalyticsToDict:
    def test_round_trips_all_sections(self):
        pairs = [_pair("/a/1.mp4", "/b/1.mp4", 80.0, mtime_a=1705276800.0, mtime_b=1705276800.0)]
        result = compute_analytics(pairs)
        d = analytics_to_dict(result)
        assert "directory_stats" in d
        assert "score_distribution" in d
        assert "filetype_breakdown" in d
        assert "creation_timeline" in d
        assert isinstance(d["directory_stats"][0], dict)
        assert "path" in d["directory_stats"][0]
