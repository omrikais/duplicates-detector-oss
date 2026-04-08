from __future__ import annotations

from pathlib import Path

from duplicates_detector.grouper import DuplicateGroup, _UnionFind, group_duplicates
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(
    path: str = "video.mp4",
    duration: float | None = 120.0,
    file_size: int = 1_000_000,
    is_reference: bool = False,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(path),
        filename=Path(path).stem,
        duration=duration,
        width=1920,
        height=1080,
        file_size=file_size,
        mtime=1_700_000_000.0,
        is_reference=is_reference,
    )


def _make_pair(
    a: VideoMetadata,
    b: VideoMetadata,
    score: float = 75.0,
) -> ScoredPair:
    return ScoredPair(
        file_a=a,
        file_b=b,
        total_score=score,
        breakdown={"filename": 30.0, "duration": 35.0, "resolution": 5.0, "file_size": 5.0},
        detail={},
    )


# ---------------------------------------------------------------------------
# Tests: _UnionFind
# ---------------------------------------------------------------------------


class TestUnionFind:
    def test_single_element_is_own_root(self):
        uf = _UnionFind()
        p = Path("a.mp4")
        assert uf.find(p) == p

    def test_two_elements_union(self):
        uf = _UnionFind()
        a, b = Path("a.mp4"), Path("b.mp4")
        uf.union(a, b)
        assert uf.find(a) == uf.find(b)

    def test_disjoint_sets_stay_separate(self):
        uf = _UnionFind()
        a, b, c, d = Path("a"), Path("b"), Path("c"), Path("d")
        uf.union(a, b)
        uf.union(c, d)
        assert uf.find(a) == uf.find(b)
        assert uf.find(c) == uf.find(d)
        assert uf.find(a) != uf.find(c)

    def test_transitive_union(self):
        uf = _UnionFind()
        a, b, c = Path("a"), Path("b"), Path("c")
        uf.union(a, b)
        uf.union(b, c)
        assert uf.find(a) == uf.find(c)

    def test_path_compression(self):
        """After find, parent should point closer to root."""
        uf = _UnionFind()
        a, b, c, d = Path("a"), Path("b"), Path("c"), Path("d")
        uf.union(a, b)
        uf.union(b, c)
        uf.union(c, d)
        root = uf.find(d)
        # After find with compression, d's parent should be root
        assert uf.find(d) == root
        assert uf.find(a) == root


# ---------------------------------------------------------------------------
# Tests: group_duplicates
# ---------------------------------------------------------------------------


class TestGroupDuplicates:
    def test_empty_pairs_returns_empty(self):
        assert group_duplicates([]) == []

    def test_single_pair_one_group(self):
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        pair = _make_pair(a, b, score=80.0)
        groups = group_duplicates([pair])

        assert len(groups) == 1
        g = groups[0]
        assert g.group_id == 1
        assert len(g.members) == 2
        assert len(g.pairs) == 1
        assert g.max_score == 80.0
        assert g.min_score == 80.0
        assert g.avg_score == 80.0

    def test_two_independent_pairs_two_groups(self):
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        c = _make_meta("c.mp4")
        d = _make_meta("d.mp4")
        p1 = _make_pair(a, b, score=90.0)
        p2 = _make_pair(c, d, score=70.0)
        groups = group_duplicates([p1, p2])

        assert len(groups) == 2
        # Sorted by max_score descending
        assert groups[0].max_score == 90.0
        assert groups[1].max_score == 70.0
        assert groups[0].group_id == 1
        assert groups[1].group_id == 2

    def test_transitive_merge_three_files(self):
        """A↔B and B↔C → one group {A, B, C}."""
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        c = _make_meta("c.mp4")
        p1 = _make_pair(a, b, score=80.0)
        p2 = _make_pair(b, c, score=60.0)
        groups = group_duplicates([p1, p2])

        assert len(groups) == 1
        g = groups[0]
        assert len(g.members) == 3
        assert len(g.pairs) == 2
        assert g.max_score == 80.0
        assert g.min_score == 60.0
        assert g.avg_score == 70.0

    def test_transitive_chain(self):
        """A↔B, B↔C, C↔D → one group {A, B, C, D}."""
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        c = _make_meta("c.mp4")
        d = _make_meta("d.mp4")
        p1 = _make_pair(a, b, score=90.0)
        p2 = _make_pair(b, c, score=70.0)
        p3 = _make_pair(c, d, score=50.0)
        groups = group_duplicates([p1, p2, p3])

        assert len(groups) == 1
        assert len(groups[0].members) == 4

    def test_score_statistics(self):
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        c = _make_meta("c.mp4")
        p1 = _make_pair(a, b, score=90.0)
        p2 = _make_pair(b, c, score=60.0)
        groups = group_duplicates([p1, p2])

        g = groups[0]
        assert g.max_score == 90.0
        assert g.min_score == 60.0
        assert g.avg_score == 75.0

    def test_groups_sorted_by_max_score_descending(self):
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        c = _make_meta("c.mp4")
        d = _make_meta("d.mp4")
        p1 = _make_pair(a, b, score=60.0)
        p2 = _make_pair(c, d, score=90.0)
        groups = group_duplicates([p1, p2])

        assert groups[0].max_score == 90.0
        assert groups[1].max_score == 60.0

    def test_members_sorted_by_path(self):
        b = _make_meta("b.mp4")
        a = _make_meta("a.mp4")
        pair = _make_pair(b, a, score=75.0)
        groups = group_duplicates([pair])

        paths = [str(m.path) for m in groups[0].members]
        assert paths == sorted(paths)

    def test_group_ids_sequential(self):
        metas = [_make_meta(f"{c}.mp4") for c in "abcdef"]
        p1 = _make_pair(metas[0], metas[1], score=90.0)
        p2 = _make_pair(metas[2], metas[3], score=80.0)
        p3 = _make_pair(metas[4], metas[5], score=70.0)
        groups = group_duplicates([p1, p2, p3])

        ids = [g.group_id for g in groups]
        assert ids == [1, 2, 3]

    def test_frozen_dataclass(self):
        a = _make_meta("a.mp4")
        b = _make_meta("b.mp4")
        pair = _make_pair(a, b)
        groups = group_duplicates([pair])

        import pytest

        with pytest.raises(AttributeError):
            groups[0].group_id = 99  # type: ignore[misc]

    def test_large_cluster(self):
        """All files connected in a star topology through a central node."""
        center = _make_meta("center.mp4")
        spokes = [_make_meta(f"spoke_{i}.mp4") for i in range(5)]
        pairs = [_make_pair(center, s, score=80.0 - i) for i, s in enumerate(spokes)]
        groups = group_duplicates(pairs)

        assert len(groups) == 1
        assert len(groups[0].members) == 6
