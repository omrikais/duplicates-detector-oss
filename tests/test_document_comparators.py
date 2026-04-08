from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.comparators import (
    DocMetaComparator,
    PageCountComparator,
    _DOCUMENT_CONTENT_KEYS,
    _DOCUMENT_DEFAULT_KEYS,
    get_document_comparators,
    get_document_content_comparators,
    get_weighted_document_comparators,
    get_weighted_document_content_comparators,
)
from duplicates_detector.metadata import VideoMetadata


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _doc(
    *,
    path: str = "report.pdf",
    file_size: int = 100_000,
    page_count: int | None = None,
    doc_title: str | None = None,
    doc_author: str | None = None,
    doc_created: str | None = None,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(path),
        filename=Path(path).stem,
        duration=None,
        width=None,
        height=None,
        file_size=file_size,
        page_count=page_count,
        doc_title=doc_title,
        doc_author=doc_author,
        doc_created=doc_created,
    )


# ---------------------------------------------------------------------------
# PageCountComparator
# ---------------------------------------------------------------------------


class TestPageCountComparator:
    def test_name_and_weight(self):
        c = PageCountComparator()
        assert c.name == "page_count"
        assert c.weight == 15.0

    def test_identical_page_counts(self):
        a = _doc(page_count=10)
        b = _doc(page_count=10)
        assert PageCountComparator().score(a, b) == 1.0

    def test_different_page_counts(self):
        a = _doc(page_count=10)
        b = _doc(page_count=20)
        assert PageCountComparator().score(a, b) == 0.5

    def test_missing_page_count_a(self):
        a = _doc(page_count=None)
        b = _doc(page_count=10)
        assert PageCountComparator().score(a, b) is None

    def test_missing_page_count_b(self):
        a = _doc(page_count=10)
        b = _doc(page_count=None)
        assert PageCountComparator().score(a, b) is None

    def test_both_missing(self):
        a = _doc()
        b = _doc()
        assert PageCountComparator().score(a, b) is None

    def test_both_zero(self):
        a = _doc(page_count=0)
        b = _doc(page_count=0)
        assert PageCountComparator().score(a, b) is None

    def test_one_zero_one_nonzero(self):
        a = _doc(page_count=0)
        b = _doc(page_count=10)
        assert PageCountComparator().score(a, b) == pytest.approx(0.0)

    def test_large_difference(self):
        a = _doc(page_count=1)
        b = _doc(page_count=100)
        result = PageCountComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(0.01)

    def test_close_counts(self):
        a = _doc(page_count=99)
        b = _doc(page_count=100)
        result = PageCountComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# DocMetaComparator
# ---------------------------------------------------------------------------


class TestDocMetaComparator:
    def test_name_and_weight(self):
        c = DocMetaComparator()
        assert c.name == "doc_meta"
        assert c.weight == 40.0

    def test_all_fields_match(self):
        a = _doc(doc_title="annual report", doc_author="john doe", doc_created="2024-01-15")
        b = _doc(doc_title="annual report", doc_author="john doe", doc_created="2024-01-15")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(1.0)

    def test_no_fields_available(self):
        a = _doc()
        b = _doc()
        assert DocMetaComparator().score(a, b) is None

    def test_title_only_exact_match(self):
        """With only title available, weight is redistributed, so exact match → 1.0."""
        a = _doc(doc_title="annual report")
        b = _doc(doc_title="annual report")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(1.0)

    def test_title_only_partial_match(self):
        a = _doc(doc_title="annual report 2024")
        b = _doc(doc_title="annual report 2023")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert 0.5 < result < 1.0

    def test_author_only_exact_match(self):
        a = _doc(doc_author="jane smith")
        b = _doc(doc_author="jane smith")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(1.0)

    def test_author_only_different(self):
        a = _doc(doc_author="jane smith")
        b = _doc(doc_author="john doe")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result < 0.5

    def test_created_same_day(self):
        a = _doc(doc_created="2024-06-15T10:00:00")
        b = _doc(doc_created="2024-06-15T20:00:00")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        # Same day, ~10 hours apart → high score
        assert result > 0.95

    def test_created_30_days_apart(self):
        a = _doc(doc_created="2024-01-01")
        b = _doc(doc_created="2024-01-31")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(0.0)

    def test_created_15_days_apart(self):
        a = _doc(doc_created="2024-01-01")
        b = _doc(doc_created="2024-01-16")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(0.5)

    def test_created_unparseable(self):
        """Unparseable dates are silently skipped."""
        a = _doc(doc_created="not-a-date")
        b = _doc(doc_created="also-not-a-date")
        # Only created available, but unparseable → no parts → None
        assert DocMetaComparator().score(a, b) is None

    def test_redistribution_title_and_author(self):
        """When only title and author available, their sub-weights are redistributed."""
        a = _doc(doc_title="report", doc_author="alice")
        b = _doc(doc_title="report", doc_author="alice")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        # Both match exactly → 1.0 after redistribution
        assert result == pytest.approx(1.0)

    def test_redistribution_mixed_scores(self):
        """Title exact match + completely different author, no created date."""
        a = _doc(doc_title="report", doc_author="alice")
        b = _doc(doc_title="report", doc_author="bob")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        # title score=1.0 weight=0.45, author score~=0.0 weight=0.35
        # redistributed total_weight = 0.80
        # result = (0.45/0.80 * 1.0) + (0.35/0.80 * fuzz("alice","bob")/100)
        assert 0.4 < result < 0.8

    def test_one_side_missing_title(self):
        """One side has title, other doesn't → title sub-field skipped."""
        a = _doc(doc_title="report", doc_author="alice")
        b = _doc(doc_author="alice")
        result = DocMetaComparator().score(a, b)
        assert result is not None
        # Only author available on both sides → exact match → 1.0
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Key sets
# ---------------------------------------------------------------------------


class TestDocumentKeySets:
    def test_default_keys(self):
        assert {"filename", "filesize", "page_count", "doc_meta", "directory"} == _DOCUMENT_DEFAULT_KEYS

    def test_content_keys(self):
        assert {"filename", "filesize", "page_count", "doc_meta", "directory", "content"} == _DOCUMENT_CONTENT_KEYS

    def test_content_keys_superset(self):
        assert _DOCUMENT_DEFAULT_KEYS < _DOCUMENT_CONTENT_KEYS


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestDocumentFactoryFunctions:
    def test_get_document_comparators_names(self):
        comps = get_document_comparators()
        names = [c.name for c in comps]
        assert names == ["filename", "file_size", "page_count", "doc_meta", "directory"]

    def test_get_document_comparators_weights_sum_100(self):
        comps = get_document_comparators()
        scored = [c for c in comps if c.weight > 0]
        total = sum(c.weight for c in scored)
        assert total == pytest.approx(100.0)

    def test_get_document_comparators_individual_weights(self):
        comps = get_document_comparators()
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 30.0
        assert by_name["file_size"] == 15.0
        assert by_name["page_count"] == 15.0
        assert by_name["doc_meta"] == 40.0
        assert by_name["directory"] == 0.0

    def test_get_document_content_comparators_names(self):
        comps = get_document_content_comparators()
        names = [c.name for c in comps]
        assert names == ["filename", "file_size", "page_count", "doc_meta", "content", "directory"]

    def test_get_document_content_comparators_weights_sum_100(self):
        comps = get_document_content_comparators()
        scored = [c for c in comps if c.weight > 0]
        total = sum(c.weight for c in scored)
        assert total == pytest.approx(100.0)

    def test_get_document_content_comparators_individual_weights(self):
        comps = get_document_content_comparators()
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 15.0
        assert by_name["file_size"] == 10.0
        assert by_name["page_count"] == 10.0
        assert by_name["doc_meta"] == 25.0
        assert by_name["content"] == 40.0
        assert by_name["directory"] == 0.0

    def test_get_weighted_document_comparators(self):
        weights = {"filename": 50.0, "file_size": 20.0, "page_count": 10.0, "doc_meta": 20.0}
        comps = get_weighted_document_comparators(weights)
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 50.0
        assert by_name["file_size"] == 20.0
        assert by_name["page_count"] == 10.0
        assert by_name["doc_meta"] == 20.0

    def test_get_weighted_document_content_comparators(self):
        weights = {"content": 50.0, "filename": 10.0}
        comps = get_weighted_document_content_comparators(weights)
        by_name = {c.name: c.weight for c in comps}
        assert by_name["content"] == 50.0
        assert by_name["filename"] == 10.0


# ---------------------------------------------------------------------------
# Integration with make_metadata fixture
# ---------------------------------------------------------------------------


class TestDocComparatorsWithFixture:
    def test_page_count_via_fixture(self, make_metadata):
        a = make_metadata(path="a.pdf", page_count=10, duration=None, width=None, height=None)
        b = make_metadata(path="b.pdf", page_count=10, duration=None, width=None, height=None)
        assert PageCountComparator().score(a, b) == 1.0

    def test_doc_meta_via_fixture(self, make_metadata):
        a = make_metadata(path="a.pdf", doc_title="hello", doc_author="alice", duration=None, width=None, height=None)
        b = make_metadata(path="b.pdf", doc_title="hello", doc_author="alice", duration=None, width=None, height=None)
        result = DocMetaComparator().score(a, b)
        assert result is not None
        assert result == pytest.approx(1.0)
