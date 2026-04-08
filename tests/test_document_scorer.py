"""Tests for document-mode scoring: page-count bucketing."""

from __future__ import annotations

from pathlib import Path

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import _bucket_by_page_count


def _doc(name: str, page_count: int | None = None) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/tmp/{name}.txt"),
        filename=name,
        duration=None,
        width=None,
        height=None,
        file_size=1000,
        page_count=page_count,
    )


def test_bucket_by_page_count_groups_similar() -> None:
    """3 docs with pages 10,11,12 should land in a single bucket."""
    items = [_doc("a", 10), _doc("b", 11), _doc("c", 12)]
    buckets = _bucket_by_page_count(items)
    assert len(buckets) == 1
    assert len(buckets[0]) == 3


def test_bucket_by_page_count_separates_distant() -> None:
    """Pages 5,6 and 50,51 are far apart -- should produce 2 separate buckets."""
    items = [_doc("a", 5), _doc("b", 6), _doc("c", 50), _doc("d", 51)]
    buckets = _bucket_by_page_count(items)
    assert len(buckets) == 2
    pages_per_bucket = [sorted(v.page_count for v in b) for b in buckets]  # type: ignore[misc]
    assert [5, 6] in pages_per_bucket
    assert [50, 51] in pages_per_bucket


def test_bucket_by_page_count_unknown_catchall() -> None:
    """2 unknown-page-count docs form their own bucket; 1 known is excluded (singleton)."""
    items = [_doc("a"), _doc("b"), _doc("c", 42)]
    buckets = _bucket_by_page_count(items)
    assert len(buckets) == 1
    # The bucket should contain the 2 unknowns
    assert all(v.page_count is None for v in buckets[0])
    assert len(buckets[0]) == 2


def test_bucket_by_page_count_single_item_excluded() -> None:
    """Two docs with distant page counts (10 vs 100) -- each bucket has 1 item, so 0 buckets."""
    items = [_doc("a", 10), _doc("b", 100)]
    buckets = _bucket_by_page_count(items)
    assert len(buckets) == 0
