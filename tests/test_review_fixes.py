"""Tests for bug fixes from the document-mode code review.

== Round 1 ==

Fix 1: Gate TF-IDF setup on ``content_method`` parameter (scorer.py)
    - ``find_duplicates()`` should only build a TF-IDF matrix when
      ``content_method="tfidf"`` is explicitly passed, not when items
      happen to have ``text_content``.

Fix 2: ``_normalize_pdf_date()`` in metadata.py
    - PDF ``CreationDate`` values must be converted to ISO 8601 so that
      ``DocMetaComparator`` can parse them with ``datetime.fromisoformat()``.

Fix 3: Text rehydration via ``_extract_text_only()`` (pipeline.py)
    - Cache-hit documents with ``--content-method tfidf`` need their
      ``text_content`` re-extracted since it is transient / not cached.

== Round 2 (commit 619d24c) ==

Fix 4: Guard TF-IDF against empty vocabulary (tfidf.py + scorer.py)
    - ``build_tfidf_matrix()`` catches ``ValueError`` from
      ``TfidfVectorizer.fit_transform()`` when all documents have empty
      vocabulary, returning ``None`` instead of crashing.
    - The scorer checks ``if matrix is not None:`` before attaching.

Fix 5: Scikit-learn preflight for tfidf (cli.py)
    - ``_validate_content_params()`` now checks for scikit-learn when
      ``content_method == "tfidf"``, raising ``SystemExit(1)`` if missing.

Fix 6: Single-line text page_count (metadata.py)
    - Changed from ``text_content.count("\\n")`` to
      ``len(text_content.splitlines())`` so single-line text gets
      ``page_count=1`` (not 0).
"""

from __future__ import annotations

import argparse
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.comparators import ContentComparator, get_document_content_comparators
from duplicates_detector.config import Mode
from duplicates_detector.metadata import VideoMetadata, _normalize_pdf_date, _extract_text_only, extract_one_document


# ---------------------------------------------------------------------------
# Helper factory (mirrors pattern in test_document_tfidf.py)
# ---------------------------------------------------------------------------


def _doc(
    name: str,
    *,
    text_content: str | None = None,
    page_count: int | None = 10,
    file_size: int = 1000,
    content_hash: tuple[int, ...] | None = None,
    doc_title: str | None = None,
    doc_author: str | None = None,
    doc_created: str | None = None,
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
        content_hash=content_hash,
        doc_title=doc_title,
        doc_author=doc_author,
        doc_created=doc_created,
    )


# ===========================================================================
# Fix 1: TF-IDF gated on content_method
# ===========================================================================


class TestTfidfGatedOnContentMethod:
    """find_duplicates() must only build a TF-IDF matrix when content_method='tfidf'."""

    def test_no_tfidf_when_content_method_is_none(self) -> None:
        """With text_content present but content_method=None (default),
        the ContentComparator must NOT get a _tfidf_matrix.
        """
        from duplicates_detector.scorer import find_duplicates

        text = "The quick brown fox jumps over the lazy dog and then goes home"
        a = _doc("report_v1", text_content=text, page_count=10)
        b = _doc("report_v2", text_content=text, page_count=10)

        comps = get_document_content_comparators()
        content_comp = next(c for c in comps if isinstance(c, ContentComparator))

        find_duplicates(
            [a, b],
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
            # content_method defaults to None — TF-IDF should NOT fire
        )

        # ContentComparator must NOT have had TF-IDF matrix attached
        assert content_comp._tfidf_matrix is None

    def test_no_tfidf_when_content_method_is_simhash(self) -> None:
        """With content_method='simhash', no TF-IDF matrix should be built."""
        from duplicates_detector.scorer import find_duplicates

        text = "The quick brown fox jumps over the lazy dog and then goes home"
        a = _doc("report_v1", text_content=text, page_count=10)
        b = _doc("report_v2", text_content=text, page_count=10)

        comps = get_document_content_comparators()
        content_comp = next(c for c in comps if isinstance(c, ContentComparator))

        find_duplicates(
            [a, b],
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
            content_method="simhash",
        )

        assert content_comp._tfidf_matrix is None

    def test_no_content_score_without_tfidf_or_hash(self) -> None:
        """When content_method is not 'tfidf' and no content_hash, content breakdown is None."""
        from duplicates_detector.scorer import find_duplicates

        text = "The quick brown fox jumps over the lazy dog and then goes home"
        # Use filenames that pass the filename gate (no numbered-series or distinct-word mismatch)
        a = _doc("quarterly_report", text_content=text, page_count=10)
        b = _doc("quarterly_report_copy", text_content=text, page_count=10)

        comps = get_document_content_comparators()
        pairs = find_duplicates(
            [a, b],
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
            # No content_method → no TF-IDF; no content_hash → no simhash
        )

        # Should still produce a pair (from other comparators),
        # but the content breakdown should be None (no scoring path available)
        assert len(pairs) >= 1
        assert pairs[0].breakdown.get("content") is None

    def test_tfidf_builds_matrix_when_content_method_tfidf(self) -> None:
        """With content_method='tfidf', the TF-IDF matrix IS built and content scores appear."""
        from duplicates_detector.scorer import find_duplicates

        text = "The quick brown fox jumps over the lazy dog and then goes home to rest"
        a = _doc("report_v1", text_content=text, page_count=10)
        b = _doc("report_v2", text_content=text, page_count=10)

        comps = get_document_content_comparators()
        content_comp = next(c for c in comps if isinstance(c, ContentComparator))

        pairs = find_duplicates(
            [a, b],
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
            content_method="tfidf",
        )

        # TF-IDF matrix should have been set
        assert content_comp._tfidf_matrix is not None
        # Pairs should contain a content score
        assert len(pairs) >= 1
        assert "content" in pairs[0].breakdown
        assert pairs[0].breakdown["content"] is not None
        assert pairs[0].breakdown["content"] > 0


# ===========================================================================
# Fix 2: _normalize_pdf_date()
# ===========================================================================


class TestNormalizePdfDate:
    """_normalize_pdf_date converts PDF date strings to ISO 8601."""

    def test_basic_date(self) -> None:
        """D:20240101120000 → 2024-01-01T12:00:00"""
        result = _normalize_pdf_date("D:20240101120000")
        assert result == "2024-01-01T12:00:00"

    def test_date_with_positive_timezone(self) -> None:
        """D:20240101120000+05'30' → 2024-01-01T12:00:00+05:30"""
        result = _normalize_pdf_date("D:20240101120000+05'30'")
        assert result == "2024-01-01T12:00:00+05:30"

    def test_date_with_negative_timezone(self) -> None:
        """D:20240615083000-08'00' → 2024-06-15T08:30:00-08:00"""
        result = _normalize_pdf_date("D:20240615083000-08'00'")
        assert result == "2024-06-15T08:30:00-08:00"

    def test_date_with_z_suffix(self) -> None:
        """D:20240101120000Z → 2024-01-01T12:00:00+00:00"""
        result = _normalize_pdf_date("D:20240101120000Z")
        assert result == "2024-01-01T12:00:00+00:00"

    def test_invalid_input_returns_none(self) -> None:
        """Strings that don't match PDF date format return None."""
        assert _normalize_pdf_date("not a date") is None

    def test_empty_string_returns_none(self) -> None:
        assert _normalize_pdf_date("") is None

    def test_partial_match_returns_none(self) -> None:
        """'D:2024' is too short to contain all 14 digits."""
        assert _normalize_pdf_date("D:2024") is None

    def test_output_parseable_by_fromisoformat(self) -> None:
        """Normalized dates must be parseable by datetime.fromisoformat()."""
        from datetime import datetime

        for raw in [
            "D:20240101120000",
            "D:20240101120000+05'30'",
            "D:20240101120000Z",
            "D:20240615083000-08'00'",
        ]:
            result = _normalize_pdf_date(raw)
            assert result is not None
            # Must not raise
            dt = datetime.fromisoformat(result)
            assert dt.year == 2024


class TestDocMetaComparatorWithPdfDates:
    """DocMetaComparator integration: normalized PDF dates produce valid scores."""

    def test_pdf_dates_produce_created_subscore(self) -> None:
        """Two items with normalized PDF-format dates should get a doc_meta score
        that includes the created sub-field contribution.
        """
        from duplicates_detector.comparators import DocMetaComparator

        # Simulate dates that _normalize_pdf_date would produce from PDF metadata
        iso_date = _normalize_pdf_date("D:20240101120000+05'30'")
        assert iso_date is not None  # sanity

        a = _doc("report_v1", doc_created=iso_date)
        b = _doc("report_v2", doc_created=iso_date)

        score = DocMetaComparator().score(a, b)
        # Both have the same parseable date → created subscore should be 1.0,
        # and since it's the only available sub-field, the total should be 1.0
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_pdf_dates_different_days_produce_decay(self) -> None:
        """Two items 15 days apart should produce ~0.5 created subscore."""
        date_a = _normalize_pdf_date("D:20240101120000")
        date_b = _normalize_pdf_date("D:20240116120000")
        assert date_a is not None and date_b is not None

        from duplicates_detector.comparators import DocMetaComparator

        a = _doc("report_v1", doc_created=date_a)
        b = _doc("report_v2", doc_created=date_b)

        score = DocMetaComparator().score(a, b)
        assert score is not None
        assert score == pytest.approx(0.5)

    def test_unnormalized_pdf_date_fails_to_score(self) -> None:
        """Raw PDF dates (not normalized) fail fromisoformat → created field is skipped.

        This confirms the bug that _normalize_pdf_date was introduced to fix.
        """
        from duplicates_detector.comparators import DocMetaComparator

        # Raw PDF dates are NOT valid ISO 8601
        a = _doc("report_v1", doc_created="D:20240101120000+05'30'")
        b = _doc("report_v2", doc_created="D:20240101120000+05'30'")

        # With only unparseable created dates and no other doc_meta fields,
        # DocMetaComparator should return None (no scoreable sub-fields)
        score = DocMetaComparator().score(a, b)
        assert score is None


# ===========================================================================
# Fix 3: _extract_text_only()
# ===========================================================================


class TestExtractTextOnly:
    """_extract_text_only re-extracts text from document files."""

    def test_txt_file_returns_text(self, tmp_path: Path) -> None:
        """Plain .txt files should return their content."""
        f = tmp_path / "notes.txt"
        f.write_text("Hello, world!", encoding="utf-8")

        result = _extract_text_only(f)
        assert result == "Hello, world!"

    def test_md_file_returns_text(self, tmp_path: Path) -> None:
        """.md files should also return their content."""
        f = tmp_path / "readme.md"
        f.write_text("# Title\n\nBody text", encoding="utf-8")

        result = _extract_text_only(f)
        assert result == "# Title\n\nBody text"

    def test_unsupported_extension_returns_none(self, tmp_path: Path) -> None:
        """Unsupported extensions should return None."""
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")

        result = _extract_text_only(f)
        assert result is None

    def test_nonexistent_file_returns_none(self) -> None:
        """Missing files should return None (not raise)."""
        result = _extract_text_only(Path("/nonexistent/path/doc.txt"))
        assert result is None

    def test_empty_txt_file_returns_empty_string(self, tmp_path: Path) -> None:
        """Empty .txt files should return empty string, not None."""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        result = _extract_text_only(f)
        assert result == ""

    def test_txt_with_unicode(self, tmp_path: Path) -> None:
        """Unicode text should be handled correctly."""
        f = tmp_path / "unicode.txt"
        f.write_text("Héllo wörld 日本語", encoding="utf-8")

        result = _extract_text_only(f)
        assert result == "Héllo wörld 日本語"

    def test_csv_extension_returns_none(self, tmp_path: Path) -> None:
        """.csv is not a supported document extension."""
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3", encoding="utf-8")

        result = _extract_text_only(f)
        assert result is None

    def test_pdf_extension_attempts_extraction(self, tmp_path: Path) -> None:
        """.pdf files call pdfminer; when pdfminer is not installed, returns None."""

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        # Simulate ImportError (pdfminer not installed)
        with patch.dict("sys.modules", {"pdfminer": None, "pdfminer.high_level": None}):
            result = _extract_text_only(f)
            # Should return None (pdfminer import fails, exception caught)
            assert result is None

    def test_docx_extension_delegates_to_extract_docx(self, tmp_path: Path) -> None:
        """.docx files use docx.Document directly."""

        f = tmp_path / "doc.docx"
        f.write_bytes(b"PK fake docx")

        mock_para = MagicMock()
        mock_para.text = "Extracted text from docx"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        mock_docx_mod = MagicMock()
        mock_docx_mod.Document.return_value = mock_doc

        with patch.dict("sys.modules", {"docx": mock_docx_mod}):
            result = _extract_text_only(f)
            assert result == "Extracted text from docx"


# ===========================================================================
# Fix 4: Guard TF-IDF against empty vocabulary
# ===========================================================================


class TestTfidfEmptyVocabularyGuard:
    """build_tfidf_matrix() must return None when TfidfVectorizer cannot
    build a vocabulary (all-empty docs or only single-char tokens).
    """

    def test_all_empty_text_returns_none(self) -> None:
        """All items with empty text_content → None (no vocabulary)."""
        from duplicates_detector.tfidf import build_tfidf_matrix

        items = [
            _doc("a", text_content=""),
            _doc("b", text_content=""),
        ]
        result = build_tfidf_matrix(items)
        assert result is None

    def test_all_none_text_returns_none(self) -> None:
        """All items with None text_content (coerced to "") → None."""
        from duplicates_detector.tfidf import build_tfidf_matrix

        items = [
            _doc("a", text_content=None),
            _doc("b", text_content=None),
        ]
        result = build_tfidf_matrix(items)
        assert result is None

    def test_single_char_tokens_returns_none(self) -> None:
        """Text with only single-character tokens → None.

        TfidfVectorizer's default token_pattern requires tokens of 2+
        characters, so 'a b c' produces an empty vocabulary.
        """
        from duplicates_detector.tfidf import build_tfidf_matrix

        items = [
            _doc("a", text_content="a b c"),
            _doc("b", text_content="x y z"),
        ]
        result = build_tfidf_matrix(items)
        assert result is None

    def test_valid_text_returns_matrix(self) -> None:
        """Items with real multi-character tokens → a non-None sparse matrix."""
        from duplicates_detector.tfidf import build_tfidf_matrix

        items = [
            _doc("a", text_content="The quick brown fox jumps"),
            _doc("b", text_content="The lazy dog sleeps soundly"),
        ]
        result = build_tfidf_matrix(items)
        assert result is not None
        # Matrix should have 2 rows (one per item)
        assert result.shape[0] == 2

    def test_find_duplicates_empty_text_no_crash(self) -> None:
        """find_duplicates() with content_method='tfidf' and all-empty-text
        documents must not crash — it simply produces pairs without content scores.
        """
        from duplicates_detector.scorer import find_duplicates

        a = _doc("quarterly_report", text_content="", page_count=10)
        b = _doc("quarterly_report_copy", text_content="", page_count=10)

        comps = get_document_content_comparators()
        # Should not raise ValueError
        pairs = find_duplicates(
            [a, b],
            threshold=0.0,
            comparators=comps,
            workers=1,
            mode=Mode.DOCUMENT,
            content_method="tfidf",
        )

        # Pairs are still produced from other comparators (filename, page_count, etc.)
        assert len(pairs) >= 1
        # Content score should be None since TF-IDF matrix could not be built
        assert pairs[0].breakdown.get("content") is None


# ===========================================================================
# Fix 5: Scikit-learn preflight for tfidf
# ===========================================================================


class TestTfidfSklearnPreflight:
    """_validate_content_params() must check for scikit-learn availability
    when content_method is 'tfidf'.
    """

    def _make_args(self) -> argparse.Namespace:
        """Create a minimal argparse.Namespace for tfidf validation."""
        return argparse.Namespace(
            content=True,
            content_method="tfidf",
        )

    def test_sklearn_available_no_error(self) -> None:
        """When scikit-learn is importable, no error is raised."""
        from rich.console import Console

        from duplicates_detector.cli import _validate_content_params

        out = StringIO()
        c = Console(file=out, no_color=True)
        args = self._make_args()

        # Should not raise (sklearn is installed in test env)
        _validate_content_params(args, c, mode=Mode.DOCUMENT)

    def test_sklearn_missing_raises_system_exit(self) -> None:
        """When sklearn import fails, SystemExit(1) is raised with a helpful message."""
        from rich.console import Console

        from duplicates_detector.cli import _validate_content_params

        out = StringIO()
        c = Console(file=out, no_color=True)
        args = self._make_args()

        saved = sys.modules.get("sklearn")
        sys.modules["sklearn"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(SystemExit) as exc_info:
                _validate_content_params(args, c, mode=Mode.DOCUMENT)

            assert exc_info.value.code == 1
            output = out.getvalue()
            assert "scikit-learn" in output
        finally:
            if saved is not None:
                sys.modules["sklearn"] = saved
            elif "sklearn" in sys.modules:
                del sys.modules["sklearn"]


# ===========================================================================
# Fix 6: Single-line text page_count via splitlines()
# ===========================================================================


class TestPageCountSplitlines:
    """page_count for .txt/.md files uses len(splitlines()), not count('\\n').

    This means single-line text without a trailing newline correctly gets
    page_count=1 instead of 0.
    """

    def test_single_line_text_page_count_is_one(self, tmp_path: Path) -> None:
        """A single-line .txt file with no newline → page_count=1."""
        f = tmp_path / "single.txt"
        f.write_text("hello", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.page_count == 1

    def test_empty_file_page_count_is_zero(self, tmp_path: Path) -> None:
        """An empty .txt file → page_count=0."""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.page_count == 0
