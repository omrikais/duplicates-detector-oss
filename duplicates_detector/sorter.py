from __future__ import annotations

from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.scorer import ScoredPair


def sort_pairs(pairs: list[ScoredPair], sort_by: str) -> list[ScoredPair]:
    """Sort scored pairs by the given field. Returns a new list."""
    match sort_by:
        case "score":
            return sorted(pairs, key=lambda p: p.total_score, reverse=True)
        case "size":
            return sorted(pairs, key=lambda p: p.file_a.file_size + p.file_b.file_size, reverse=True)
        case "path":
            return sorted(pairs, key=lambda p: str(p.file_a.path))
        case "mtime":
            return sorted(
                pairs,
                key=lambda p: max(p.file_a.mtime or 0.0, p.file_b.mtime or 0.0),
                reverse=True,
            )
        case _:
            raise ValueError(f"Unknown sort field: {sort_by!r}")


def sort_groups(groups: list[DuplicateGroup], sort_by: str) -> list[DuplicateGroup]:
    """Sort duplicate groups by the given field. Returns a new list."""
    match sort_by:
        case "score":
            return sorted(groups, key=lambda g: g.max_score, reverse=True)
        case "size":
            return sorted(
                groups,
                key=lambda g: sum(m.file_size for m in g.members),
                reverse=True,
            )
        case "path":
            return sorted(groups, key=lambda g: str(g.members[0].path))
        case "mtime":
            return sorted(
                groups,
                key=lambda g: max((m.mtime or 0.0) for m in g.members),
                reverse=True,
            )
        case _:
            raise ValueError(f"Unknown sort field: {sort_by!r}")
