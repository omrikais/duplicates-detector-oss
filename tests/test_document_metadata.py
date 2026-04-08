from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.metadata import extract_one_document, VideoMetadata


class TestExtractTxtFile:
    def test_extract_txt_file(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("line one\nline two\nline three", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.path == f
        assert meta.filename == "notes"
        assert meta.page_count == 3  # three lines
        # Text extraction is deferred to content-hash / score stage
        assert meta.text_content is None
        assert meta.doc_title is None
        assert meta.doc_author is None
        assert meta.doc_created is None
        assert meta.file_size > 0
        assert meta.mtime is not None

    def test_extract_txt_trailing_newline(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("line one\nline two\nline three\n", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.page_count == 3  # three newlines


class TestExtractMdFile:
    def test_extract_md_file(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# Title\n\nSome content\n", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.path == f
        assert meta.filename == "readme"
        assert meta.page_count == 3  # three newlines
        assert meta.text_content is None
        assert meta.doc_title is None
        assert meta.doc_author is None


class TestExtractPdfFile:
    def test_extract_pdf_file(self, tmp_path: Path) -> None:
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake content")

        mock_pdf_meta = MagicMock(
            return_value={
                "page_count": 5,
                "doc_title": "my report",
                "doc_author": "jane doe",
                "doc_created": "2024-01-01T12:00:00",
            }
        )

        with patch("duplicates_detector.metadata._extract_pdf_metadata", mock_pdf_meta):
            meta = extract_one_document(f)

        assert meta is not None
        assert meta.page_count == 5
        assert meta.doc_title == "my report"
        assert meta.doc_author == "jane doe"
        assert meta.doc_created == "2024-01-01T12:00:00"
        # Text extraction is deferred to the content-hash / score stage.
        assert meta.text_content is None


class TestExtractDocxFile:
    def test_extract_docx_file(self, tmp_path: Path) -> None:
        f = tmp_path / "document.docx"
        f.write_bytes(b"PK fake docx")

        with patch(
            "duplicates_detector.metadata._extract_docx",
            return_value=(None, 3, "my document", "john doe", "2024-01-01T12:00:00"),
        ):
            meta = extract_one_document(f)

        assert meta is not None
        assert meta.text_content is None
        assert meta.page_count == 3
        assert meta.doc_title == "my document"
        assert meta.doc_author == "john doe"
        assert meta.doc_created == "2024-01-01T12:00:00"


class TestExtractDocumentEdgeCases:
    def test_extract_document_nonexistent_file(self) -> None:
        result = extract_one_document(Path("/nonexistent/path/doc.txt"))
        assert result is None

    def test_extract_document_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.page_count == 0
        assert meta.text_content is None

    def test_extract_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "file.xyz"
        f.write_text("some content", encoding="utf-8")

        result = extract_one_document(f)
        assert result is None

    def test_extract_document_video_fields_none(self, tmp_path: Path) -> None:
        """Document metadata leaves video-specific fields as None."""
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")

        meta = extract_one_document(f)

        assert meta is not None
        assert meta.duration is None
        assert meta.width is None
        assert meta.height is None
        assert meta.codec is None
        assert meta.bitrate is None
        assert meta.framerate is None
        assert meta.audio_channels is None


class TestDocumentFieldsOnVideoMetadata:
    def test_document_fields_default_none(self) -> None:
        meta = VideoMetadata(
            path=Path("video.mp4"),
            filename="video",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        assert meta.page_count is None
        assert meta.doc_title is None
        assert meta.doc_author is None
        assert meta.doc_created is None
        assert meta.text_content is None

    def test_document_fields_explicit_values(self) -> None:
        meta = VideoMetadata(
            path=Path("doc.pdf"),
            filename="doc",
            duration=None,
            width=None,
            height=None,
            file_size=5000,
            page_count=10,
            doc_title="my doc",
            doc_author="author",
            doc_created="2024-01-01",
            text_content="hello world",
        )
        assert meta.page_count == 10
        assert meta.doc_title == "my doc"
        assert meta.doc_author == "author"
        assert meta.doc_created == "2024-01-01"
        assert meta.text_content == "hello world"
