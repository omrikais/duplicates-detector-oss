from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.sorter import sort_groups, sort_pairs


def _meta(
    name: str = "video.mp4",
    file_size: int = 1_000_000,
    mtime: float | None = 1_700_000_000.0,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/videos/{name}"),
        filename=Path(name).stem,
        duration=120.0,
        width=1920,
        height=1080,
        file_size=file_size,
        mtime=mtime,
    )


def _pair(
    name_a: str = "a.mp4",
    name_b: str = "b.mp4",
    score: float = 75.0,
    size_a: int = 1_000_000,
    size_b: int = 1_000_000,
    mtime_a: float | None = 1_700_000_000.0,
    mtime_b: float | None = 1_700_000_000.0,
) -> ScoredPair:
    return ScoredPair(
        file_a=_meta(name_a, file_size=size_a, mtime=mtime_a),
        file_b=_meta(name_b, file_size=size_b, mtime=mtime_b),
        total_score=score,
        breakdown={"filename": 25.0, "duration": 30.0},
        detail={},
    )


def _group(
    group_id: int = 1,
    name_a: str = "a.mp4",
    name_b: str = "b.mp4",
    max_score: float = 75.0,
    size_a: int = 1_000_000,
    size_b: int = 1_000_000,
    mtime_a: float | None = 1_700_000_000.0,
    mtime_b: float | None = 1_700_000_000.0,
) -> DuplicateGroup:
    ma = _meta(name_a, file_size=size_a, mtime=mtime_a)
    mb = _meta(name_b, file_size=size_b, mtime=mtime_b)
    pair = ScoredPair(file_a=ma, file_b=mb, total_score=max_score, breakdown={"filename": 25.0}, detail={})
    return DuplicateGroup(
        group_id=group_id,
        members=(ma, mb),
        pairs=(pair,),
        max_score=max_score,
        min_score=max_score,
        avg_score=max_score,
    )


# ---------------------------------------------------------------------------
# sort_pairs
# ---------------------------------------------------------------------------


class TestSortPairs:
    def test_sort_by_score(self):
        pairs = [_pair(score=50.0), _pair(score=90.0), _pair(score=70.0)]
        result = sort_pairs(pairs, "score")
        assert [p.total_score for p in result] == [90.0, 70.0, 50.0]

    def test_sort_by_size(self):
        pairs = [
            _pair(size_a=100, size_b=100),
            _pair(size_a=500, size_b=500),
            _pair(size_a=200, size_b=300),
        ]
        result = sort_pairs(pairs, "size")
        sizes = [p.file_a.file_size + p.file_b.file_size for p in result]
        assert sizes == [1000, 500, 200]

    def test_sort_by_path(self):
        pairs = [
            _pair(name_a="c.mp4"),
            _pair(name_a="a.mp4"),
            _pair(name_a="b.mp4"),
        ]
        result = sort_pairs(pairs, "path")
        paths = [str(p.file_a.path) for p in result]
        assert paths == ["/videos/a.mp4", "/videos/b.mp4", "/videos/c.mp4"]

    def test_sort_by_mtime(self):
        pairs = [
            _pair(mtime_a=100.0, mtime_b=50.0),
            _pair(mtime_a=300.0, mtime_b=200.0),
            _pair(mtime_a=150.0, mtime_b=250.0),
        ]
        result = sort_pairs(pairs, "mtime")
        mtimes = [max(p.file_a.mtime or 0.0, p.file_b.mtime or 0.0) for p in result]
        assert mtimes == [300.0, 250.0, 100.0]

    def test_mtime_none_safe(self):
        pairs = [
            _pair(mtime_a=None, mtime_b=None),
            _pair(mtime_a=100.0, mtime_b=None),
        ]
        result = sort_pairs(pairs, "mtime")
        assert result[0].file_a.mtime == 100.0
        assert result[1].file_a.mtime is None

    def test_empty_list(self):
        assert sort_pairs([], "score") == []

    def test_invalid_field_raises(self):
        with pytest.raises(ValueError, match="Unknown sort field"):
            sort_pairs([], "invalid")

    def test_stable_sort(self):
        """Equal scores preserve original order."""
        pairs = [
            _pair(name_a="first.mp4", score=75.0),
            _pair(name_a="second.mp4", score=75.0),
        ]
        result = sort_pairs(pairs, "score")
        assert str(result[0].file_a.path).endswith("first.mp4")
        assert str(result[1].file_a.path).endswith("second.mp4")


# ---------------------------------------------------------------------------
# sort_groups
# ---------------------------------------------------------------------------


class TestSortGroups:
    def test_sort_by_score(self):
        groups = [_group(group_id=1, max_score=50.0), _group(group_id=2, max_score=90.0)]
        result = sort_groups(groups, "score")
        assert [g.max_score for g in result] == [90.0, 50.0]

    def test_sort_by_size(self):
        groups = [
            _group(group_id=1, size_a=100, size_b=100),
            _group(group_id=2, size_a=500, size_b=500),
        ]
        result = sort_groups(groups, "size")
        assert result[0].group_id == 2
        assert result[1].group_id == 1

    def test_sort_by_path(self):
        groups = [
            _group(group_id=1, name_a="c.mp4"),
            _group(group_id=2, name_a="a.mp4"),
        ]
        result = sort_groups(groups, "path")
        assert result[0].group_id == 2
        assert result[1].group_id == 1

    def test_sort_by_mtime(self):
        groups = [
            _group(group_id=1, mtime_a=100.0, mtime_b=50.0),
            _group(group_id=2, mtime_a=300.0, mtime_b=200.0),
        ]
        result = sort_groups(groups, "mtime")
        assert result[0].group_id == 2
        assert result[1].group_id == 1

    def test_mtime_none_safe(self):
        groups = [
            _group(group_id=1, mtime_a=None, mtime_b=None),
            _group(group_id=2, mtime_a=100.0, mtime_b=None),
        ]
        result = sort_groups(groups, "mtime")
        assert result[0].group_id == 2

    def test_empty_list(self):
        assert sort_groups([], "score") == []

    def test_invalid_field_raises(self):
        with pytest.raises(ValueError, match="Unknown sort field"):
            sort_groups([], "invalid")
