"""Tests for TF-IDF content method wired into document-mode scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.comparators import ContentComparator, get_document_content_comparators
from duplicates_detector.config import Mode
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import find_duplicates
from duplicates_detector.tfidf import build_tfidf_matrix, compare_tfidf


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _doc(
    name: str,
    *,
    text_content: str | None = None,
    page_count: int | None = 10,
    file_size: int = 1000,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/tmp/{name}.txt"),
        filename=name,
        duration=None,
        width=None,
        height=None,
        file_size=file_size,
        page_count=page_count,
        text_content=text_content,
    )


# ---------------------------------------------------------------------------
# TF-IDF matrix and compare functions
# ---------------------------------------------------------------------------


class TestTfidfDirect:
    """Unit tests for build_tfidf_matrix / compare_tfidf."""

    def test_identical_texts_similarity_one(self) -> None:
        text = "The quick brown fox jumps over the lazy dog"
        items = [_doc("a", text_content=text), _doc("b", text_content=text)]
        matrix = build_tfidf_matrix(items)
        assert compare_tfidf(matrix, 0, 1) == pytest.approx(1.0)

    def test_different_texts_low_similarity(self) -> None:
        text_a = (
            "Machine learning algorithms process training data to build statistical models "
            "that predict outcomes from input features using gradient descent optimization"
        )
        text_b = (
            "Ancient Roman architecture featured arches columns and domes constructed from "
            "concrete and marble materials quarried from distant Mediterranean provinces"
        )
        items = [_doc("a", text_content=text_a), _doc("b", text_content=text_b)]
        matrix = build_tfidf_matrix(items)
        sim = compare_tfidf(matrix, 0, 1)
        assert sim < 0.3

    def test_similar_texts_moderate_similarity(self) -> None:
        text_a = "The quick brown fox jumps over the lazy dog and then rests"
        text_b = "The quick brown fox leaps over the lazy cat and then sleeps"
        items = [_doc("a", text_content=text_a), _doc("b", text_content=text_b)]
        matrix = build_tfidf_matrix(items)
        sim = compare_tfidf(matrix, 0, 1)
        assert 0.3 < sim < 0.95

    def test_empty_text_treated_as_empty_string(self) -> None:
        items = [_doc("a", text_content=None), _doc("b", text_content="hello world")]
        matrix = build_tfidf_matrix(items)
        sim = compare_tfidf(matrix, 0, 1)
        assert sim == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ContentComparator with TF-IDF
# ---------------------------------------------------------------------------


class TestContentComparatorTfidf:
    """Tests for ContentComparator with TF-IDF matrix attached."""

    def test_tfidf_scoring_via_comparator(self) -> None:
        """ContentComparator.score() uses TF-IDF when matrix is attached."""
        text = "The quick brown fox jumps over the lazy dog multiple times"
        a = _doc("a", text_content=text)
        b = _doc("b", text_content=text)

        matrix = build_tfidf_matrix([a, b])
        index_map = {a.path: 0, b.path: 1}

        comp = ContentComparator(is_document=True)
        comp.set_tfidf_data(matrix, index_map)

        result = comp.score(a, b)
        assert result is not None
        assert result == pytest.approx(1.0)

    def test_tfidf_scoring_missing_index(self) -> None:
        """ContentComparator returns None when item path not in index map."""
        text = "Some document text content here for testing purposes"
        a = _doc("a", text_content=text)
        b = _doc("b", text_content=text)
        c = _doc("c", text_content=text)

        matrix = build_tfidf_matrix([a, b])
        index_map = {a.path: 0, b.path: 1}

        comp = ContentComparator(is_document=True)
        comp.set_tfidf_data(matrix, index_map)

        # c is not in the index map
        result = comp.score(a, c)
        assert result is None

    def test_tfidf_fallback_to_simhash(self) -> None:
        """Without TF-IDF matrix, falls back to simhash when content_hash available."""
        h = (12345678, 0, 0, 0)
        from dataclasses import replace

        a = replace(_doc("a"), content_hash=h)
        b = replace(_doc("b"), content_hash=h)

        comp = ContentComparator(is_document=True)
        # No TF-IDF data set — falls back to simhash
        result = comp.score(a, b)
        assert result is not None
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# find_duplicates integration with TF-IDF
# ---------------------------------------------------------------------------


class TestFindDuplicatesTfidf:
    """End-to-end test: find_duplicates() with TF-IDF content scoring."""

    def test_tfidf_produces_content_scores(self) -> None:
        """When items have text_content and document content comparators, TF-IDF scores appear."""
        text = "The quick brown fox jumps over the lazy dog and then goes home to rest"
        a = _doc("report_v1", text_content=text, page_count=10)
        b = _doc("report_v2", text_content=text, page_count=10)
        items = [a, b]

        comps = get_document_content_comparators()
        pairs = find_duplicates(
            items,
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
            content_method="tfidf",
        )

        assert len(pairs) >= 1
        pair = pairs[0]
        # Content comparator should have produced a score (not None)
        assert "content" in pair.breakdown
        assert pair.breakdown["content"] is not None
        assert pair.breakdown["content"] > 0

    def test_tfidf_different_docs_lower_content_score(self) -> None:
        """Different text content produces lower content scores than identical text."""
        text_same = "The quick brown fox jumps over the lazy dog and then goes home to rest"
        text_diff = (
            "Ancient Roman architecture featured arches columns and domes constructed from "
            "concrete and marble materials quarried from distant Mediterranean provinces"
        )

        same_a = _doc("same_v1", text_content=text_same, page_count=10)
        same_b = _doc("same_v2", text_content=text_same, page_count=10)
        diff_a = _doc("diff_v1", text_content=text_same, page_count=10)
        diff_b = _doc("diff_v2", text_content=text_diff, page_count=10)

        comps_same = get_document_content_comparators()
        pairs_same = find_duplicates(
            [same_a, same_b],
            threshold=0.0,
            comparators=comps_same,
            workers=1,
            mode=Mode.DOCUMENT,
            content_method="tfidf",
        )

        comps_diff = get_document_content_comparators()
        pairs_diff = find_duplicates(
            [diff_a, diff_b],
            threshold=0.0,
            comparators=comps_diff,
            workers=1,
            mode=Mode.DOCUMENT,
            content_method="tfidf",
        )

        assert len(pairs_same) >= 1
        assert len(pairs_diff) >= 1
        # Identical text → higher content score than different text
        assert pairs_same[0].breakdown["content"] > pairs_diff[0].breakdown["content"]  # type: ignore[operator]

    def test_tfidf_forces_serial(self) -> None:
        """TF-IDF mode forces serial scoring even when workers > 1."""
        text = "The quick brown fox jumps over the lazy dog and then goes home"
        items = [_doc(f"doc_{i}", text_content=text, page_count=10) for i in range(5)]

        comps = get_document_content_comparators()
        # Should not crash with workers > 1 (matrix not picklable)
        pairs = find_duplicates(
            items,
            threshold=0.0,
            comparators=comps,
            workers=4,
            mode=Mode.DOCUMENT,
            content_method="tfidf",
        )
        assert len(pairs) > 0

    def test_no_tfidf_without_text_content(self) -> None:
        """Without text_content, content comparator returns None for content score."""
        a = _doc("report_v1", page_count=10)
        b = _doc("report_v2", page_count=10)

        comps = get_document_content_comparators()
        pairs = find_duplicates(
            [a, b],
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
        )

        # Without text_content or content_hash, content comparator returns None
        if pairs:
            assert pairs[0].breakdown.get("content") is None


# ---------------------------------------------------------------------------
# I1 regression: compute_document_simhash pre_extracted_text
# ---------------------------------------------------------------------------


class TestSimhashPreExtractedText:
    """Tests for I1 fix: compute_document_simhash with pre_extracted_text."""

    def test_pre_extracted_text_matches_file_read(self, tmp_path: Path) -> None:
        """Pre-extracted text produces the same hash as reading from file."""
        from duplicates_detector.content import compute_document_simhash

        text = "The quick brown fox jumps over the lazy dog and then goes home to rest"
        f = tmp_path / "doc.txt"
        f.write_text(text)

        h_from_file = compute_document_simhash(f, ".txt")
        h_from_text = compute_document_simhash(f, ".txt", pre_extracted_text=text)

        assert h_from_file is not None
        assert h_from_text is not None
        assert h_from_file == h_from_text

    def test_pre_extracted_text_overrides_file(self, tmp_path: Path) -> None:
        """Pre-extracted text is used instead of reading the file."""
        from duplicates_detector.content import compute_document_simhash

        f = tmp_path / "doc.txt"
        f.write_text("Original content in the file with enough words for bigrams")

        different_text = "Completely different text that should produce a different hash value here"
        h_from_text = compute_document_simhash(f, ".txt", pre_extracted_text=different_text)
        h_from_file = compute_document_simhash(f, ".txt")

        assert h_from_text is not None
        assert h_from_file is not None
        # They should differ since the text differs
        assert h_from_text != h_from_file
