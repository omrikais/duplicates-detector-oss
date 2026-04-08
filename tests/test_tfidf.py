from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.tfidf import build_tfidf_matrix, compare_tfidf


def _doc_with_text(text: str, path: str = "/tmp/doc.txt") -> VideoMetadata:
    return VideoMetadata(
        path=Path(path),
        filename="doc",
        duration=None,
        width=None,
        height=None,
        file_size=100,
        text_content=text,
    )


def test_identical_documents():
    items = [
        _doc_with_text("the quick brown fox jumps over the lazy dog", "/tmp/a.txt"),
        _doc_with_text("the quick brown fox jumps over the lazy dog", "/tmp/b.txt"),
    ]
    matrix = build_tfidf_matrix(items)
    sim = compare_tfidf(matrix, 0, 1)
    assert sim == pytest.approx(1.0)


def test_different_documents():
    items = [
        _doc_with_text("quantum physics and advanced mathematics", "/tmp/a.txt"),
        _doc_with_text("cooking recipes for italian pasta dishes", "/tmp/b.txt"),
    ]
    matrix = build_tfidf_matrix(items)
    sim = compare_tfidf(matrix, 0, 1)
    assert sim < 0.5


def test_similar_documents():
    items = [
        _doc_with_text("the quick brown fox jumps over the lazy dog", "/tmp/a.txt"),
        _doc_with_text("the quick brown fox leaps over the lazy dog", "/tmp/b.txt"),
    ]
    matrix = build_tfidf_matrix(items)
    sim = compare_tfidf(matrix, 0, 1)
    assert sim > 0.5


def test_none_text_content_skipped():
    items = [
        _doc_with_text("hello world", "/tmp/a.txt"),
        VideoMetadata(
            path=Path("/tmp/b.txt"),
            filename="b",
            duration=None,
            width=None,
            height=None,
            file_size=100,
            text_content=None,
        ),
    ]
    matrix = build_tfidf_matrix(items)
    sim = compare_tfidf(matrix, 0, 1)
    assert sim == pytest.approx(0.0)
