from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """A cluster of files connected by scored pair relationships."""

    group_id: int
    members: tuple[VideoMetadata, ...]
    pairs: tuple[ScoredPair, ...]
    max_score: float
    min_score: float
    avg_score: float


class _UnionFind:
    """Disjoint set with path compression and union by rank."""

    __slots__ = ("_parent", "_rank")

    def __init__(self) -> None:
        self._parent: dict[Path, Path] = {}
        self._rank: dict[Path, int] = {}

    def _ensure(self, x: Path) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: Path) -> Path:
        self._ensure(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: Path, b: Path) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


def group_duplicates(pairs: list[ScoredPair]) -> list[DuplicateGroup]:
    """Group scored pairs into connected clusters using union-find.

    Each group contains all files transitively connected by at least one
    scored pair.  Groups are sorted by descending ``max_score``.
    """
    if not pairs:
        return []

    uf = _UnionFind()
    file_map: dict[Path, VideoMetadata] = {}

    for pair in pairs:
        uf.union(pair.file_a.path, pair.file_b.path)
        file_map.setdefault(pair.file_a.path, pair.file_a)
        file_map.setdefault(pair.file_b.path, pair.file_b)

    # Collect clusters by root
    cluster_members: dict[Path, set[Path]] = defaultdict(set)
    cluster_pairs: dict[Path, list[ScoredPair]] = defaultdict(list)

    for pair in pairs:
        root = uf.find(pair.file_a.path)
        cluster_pairs[root].append(pair)
        cluster_members[root].add(pair.file_a.path)
        cluster_members[root].add(pair.file_b.path)

    # Build groups
    raw_groups: list[tuple[float, list[VideoMetadata], list[ScoredPair]]] = []
    for root, member_paths in cluster_members.items():
        p_list = cluster_pairs[root]
        scores = [p.total_score for p in p_list]
        members = sorted(
            (file_map[path] for path in member_paths),
            key=lambda m: str(m.path),
        )
        raw_groups.append((max(scores), members, p_list))

    # Sort by max_score descending, assign sequential group_id
    raw_groups.sort(key=lambda g: g[0], reverse=True)

    groups: list[DuplicateGroup] = []
    for idx, (max_score, members, p_list) in enumerate(raw_groups, 1):
        scores = [p.total_score for p in p_list]
        groups.append(
            DuplicateGroup(
                group_id=idx,
                members=tuple(members),
                pairs=tuple(p_list),
                max_score=max_score,
                min_score=min(scores),
                avg_score=sum(scores) / len(scores),
            )
        )

    return groups
