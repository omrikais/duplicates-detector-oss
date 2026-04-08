from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.content import compare_simhash, compute_document_simhash


class TestComputeDocumentSimhash:
    """Tests for compute_document_simhash()."""

    def test_simhash_identical_text(self, tmp_path: Path) -> None:
        """Two files with identical text produce the same hash."""
        text = "The quick brown fox jumps over the lazy dog and then goes home"
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text(text)
        f2.write_text(text)

        h1 = compute_document_simhash(f1, ".txt")
        h2 = compute_document_simhash(f2, ".txt")

        assert h1 is not None
        assert h2 is not None
        assert h1 == h2

    def test_simhash_similar_text(self, tmp_path: Path) -> None:
        """Two files with one word changed produce similarity > 0.8."""
        base = "The quick brown fox jumps over the lazy dog and then goes home to rest"
        changed = "The quick brown fox jumps over the lazy cat and then goes home to rest"
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text(base)
        f2.write_text(changed)

        h1 = compute_document_simhash(f1, ".txt")
        h2 = compute_document_simhash(f2, ".txt")

        assert h1 is not None
        assert h2 is not None
        similarity = compare_simhash(h1, h2)
        assert similarity > 0.8

    def test_simhash_different_text(self, tmp_path: Path) -> None:
        """Unrelated content produces similarity < 0.8."""
        text_a = (
            "Machine learning algorithms process training data to build statistical models "
            "that predict outcomes from input features using gradient descent optimization"
        )
        text_b = (
            "Ancient Roman architecture featured arches columns and domes constructed from "
            "concrete and marble materials quarried from distant Mediterranean provinces"
        )
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text(text_a)
        f2.write_text(text_b)

        h1 = compute_document_simhash(f1, ".txt")
        h2 = compute_document_simhash(f2, ".txt")

        assert h1 is not None
        assert h2 is not None
        similarity = compare_simhash(h1, h2)
        assert similarity < 0.8

    def test_simhash_storage_format(self, tmp_path: Path) -> None:
        """Hash is a 4-element tuple with last 3 elements being 0."""
        f = tmp_path / "doc.txt"
        f.write_text("Some words to compute a simhash fingerprint value here")

        h = compute_document_simhash(f, ".txt")

        assert h is not None
        assert len(h) == 4
        assert h[1] == 0
        assert h[2] == 0
        assert h[3] == 0

    def test_simhash_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns None."""
        f = tmp_path / "empty.txt"
        f.write_text("")

        h = compute_document_simhash(f, ".txt")

        assert h is None

    def test_simhash_single_word(self, tmp_path: Path) -> None:
        """File with a single word (< 2 words) returns None."""
        f = tmp_path / "one.txt"
        f.write_text("hello")

        h = compute_document_simhash(f, ".txt")

        assert h is None

    def test_simhash_md_extension(self, tmp_path: Path) -> None:
        """Markdown files are handled like plain text."""
        f = tmp_path / "readme.md"
        f.write_text("# Heading\n\nSome content in a markdown file with enough words")

        h = compute_document_simhash(f, ".md")

        assert h is not None
        assert len(h) == 4

    def test_simhash_unknown_extension(self, tmp_path: Path) -> None:
        """Unknown extension returns None."""
        f = tmp_path / "data.xyz"
        f.write_text("some content here")

        h = compute_document_simhash(f, ".xyz")

        assert h is None


class TestCompareSimhash:
    """Tests for compare_simhash()."""

    def test_compare_simhash_perfect_match(self) -> None:
        """Same tuple returns 1.0."""
        h = (12345678, 0, 0, 0)
        assert compare_simhash(h, h) == 1.0

    def test_compare_simhash_empty_a(self) -> None:
        """Empty first tuple returns 0.0."""
        assert compare_simhash((), (1, 0, 0, 0)) == 0.0

    def test_compare_simhash_empty_b(self) -> None:
        """Empty second tuple returns 0.0."""
        assert compare_simhash((1, 0, 0, 0), ()) == 0.0

    def test_compare_simhash_both_empty(self) -> None:
        """Both empty returns 0.0."""
        assert compare_simhash((), ()) == 0.0

    def test_compare_simhash_one_bit_different(self) -> None:
        """One bit difference yields similarity = 63/64."""
        h1 = (0b0, 0, 0, 0)
        h2 = (0b1, 0, 0, 0)
        expected = 1.0 - 1 / 64
        assert compare_simhash(h1, h2) == pytest.approx(expected)

    def test_compare_simhash_all_bits_different(self) -> None:
        """All 64 bits different yields similarity = 0.0."""
        h1 = (0, 0, 0, 0)
        h2 = ((1 << 64) - 1, 0, 0, 0)  # all 64 bits set
        assert compare_simhash(h1, h2) == 0.0
