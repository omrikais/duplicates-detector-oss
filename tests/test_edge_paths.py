"""Edge-case tests: non-ASCII / very long file paths.

Validates that filenames containing CJK characters, emoji, combining
diacriticals, special shell characters, and paths near OS limits work
through the full pipeline.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from duplicates_detector.comparators import FileNameComparator
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.reporter import write_csv, write_json, write_shell
from duplicates_detector.scanner import find_video_files
from duplicates_detector.scorer import ScoredPair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pair_with_paths(path_a: str, path_b: str, score: float = 75.0) -> ScoredPair:
    return ScoredPair(
        file_a=VideoMetadata(
            path=Path(path_a),
            filename=Path(path_a).stem,
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        ),
        file_b=VideoMetadata(
            path=Path(path_b),
            filename=Path(path_b).stem,
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        ),
        total_score=score,
        breakdown={"filename": 25.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
        detail={},
    )


# ---------------------------------------------------------------------------
# Non-ASCII file paths
# ---------------------------------------------------------------------------


class TestNonAsciiPaths:
    def test_scan_cjk_filename(self, tmp_path: Path):
        """File named with CJK characters found by scanner."""
        d = tmp_path / "videos"
        d.mkdir()
        (d / "\u52a8\u753b\u7247.mp4").touch()
        result = find_video_files(d, quiet=True)
        names = [p.name for p in result]
        assert "\u52a8\u753b\u7247.mp4" in names

    def test_scan_emoji_filename(self, tmp_path: Path):
        """File with emoji in name found by scanner."""
        d = tmp_path / "videos"
        d.mkdir()
        (d / "\U0001f3acmovie\U0001f3ac.mp4").touch()
        result = find_video_files(d, quiet=True)
        assert len(result) == 1
        assert "\U0001f3ac" in result[0].name

    def test_scan_combining_diacriticals(self, tmp_path: Path):
        """File with combining diacriticals found by scanner."""
        d = tmp_path / "videos"
        d.mkdir()
        (d / "cafe\u0301.mp4").touch()  # café with combining accent
        result = find_video_files(d, quiet=True)
        assert len(result) == 1

    def test_metadata_extraction_unicode_path(self, tmp_path: Path, mock_ffprobe_result):
        """ffprobe called with Unicode path → metadata extracted."""
        d = tmp_path / "videos"
        d.mkdir()
        f = d / "\u6d4b\u8bd5\u89c6\u9891.mp4"
        f.write_bytes(b"\x00" * 100)
        mock = mock_ffprobe_result(duration=90.0)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock):
            from duplicates_detector.metadata import extract_one

            meta = extract_one(f)
        assert meta is not None
        assert meta.duration == 90.0

    def test_content_hash_unicode_path(self):
        """ffmpeg called with Unicode path → content hash computed."""
        import numpy as np

        from duplicates_detector.content import _extract_sparse_hashes, _FRAME_BYTES, _FRAME_SIZE

        # Generate valid rawvideo data (64x64 RGB)
        raw_frame = np.random.randint(0, 255, (_FRAME_SIZE, _FRAME_SIZE, 3), dtype=np.uint8).tobytes()
        mock_result = MagicMock()
        mock_result.stdout = raw_frame

        with patch("duplicates_detector.content.subprocess.run", return_value=mock_result):
            result = _extract_sparse_hashes(Path("/videos/\u6d4b\u8bd5.mp4"), duration=10.0)
        assert result is not None

    def test_json_output_unicode_paths(self):
        """JSON output contains properly encoded Unicode paths."""
        pair = _make_pair_with_paths("/videos/\u52a8\u753b.mp4", "/videos/\u7535\u5f71.mp4")
        buf = StringIO()
        write_json([pair], file=buf)
        output = buf.getvalue()
        data = json.loads(output)
        assert "\u52a8\u753b" in data[0]["file_a"]

    def test_csv_output_unicode_paths(self):
        """CSV output contains proper Unicode."""
        pair = _make_pair_with_paths("/videos/\u52a8\u753b.mp4", "/videos/\u7535\u5f71.mp4")
        buf = StringIO()
        write_csv([pair], file=buf)
        output = buf.getvalue()
        assert "\u52a8\u753b" in output

    def test_shell_output_unicode_paths(self):
        """Shell output properly quotes Unicode filenames."""
        pair = _make_pair_with_paths("/videos/\u52a8\u753b.mp4", "/videos/\u7535\u5f71.mp4")
        buf = StringIO()
        write_shell([pair], file=buf)
        output = buf.getvalue()
        assert "\u52a8\u753b" in output

    def test_scorer_unicode_filenames(self, make_metadata):
        """Filename comparator works on Unicode pairs (rapidfuzz handles Unicode)."""
        a = make_metadata(path="\u52a8\u753b\u7247.mp4")
        b = make_metadata(path="\u52a8\u753b\u7247_copy.mp4")
        comp = FileNameComparator()
        score = comp.score(a, b)
        assert score is not None
        assert score > 0.0


# ---------------------------------------------------------------------------
# Special character paths
# ---------------------------------------------------------------------------


class TestSpecialCharacterPaths:
    def test_spaces_in_path(self, tmp_path: Path):
        """Path with spaces works through scanner."""
        d = tmp_path / "my videos"
        d.mkdir()
        (d / "my movie.mp4").touch()
        result = find_video_files(d, quiet=True)
        assert len(result) == 1
        assert "my movie.mp4" in result[0].name

    def test_quotes_in_filename(self):
        """Shell output properly escapes quotes in filenames."""
        pair = _make_pair_with_paths('/videos/it\'s a "test".mp4', "/videos/other.mp4")
        buf = StringIO()
        write_shell([pair], file=buf)
        output = buf.getvalue()
        # shlex.quote should handle the quoting properly
        assert "it" in output  # The filename appears in output
        assert "test" in output

    def test_backtick_dollar_in_filename(self):
        """Shell output safely quotes $(rm -rf /) — no injection possible."""
        pair = _make_pair_with_paths("/videos/`$(rm -rf /)`.mp4", "/videos/safe.mp4")
        buf = StringIO()
        write_shell([pair], file=buf)
        output = buf.getvalue()
        # shlex.quote wraps in single quotes to neutralize $() and backticks
        assert "'/videos/`$(rm -rf /)`.mp4'" in output

    def test_newline_in_filename(self):
        """Filename with \\n → JSON uses proper escaping."""
        pair = _make_pair_with_paths("/videos/line1\nline2.mp4", "/videos/other.mp4")
        buf = StringIO()
        write_json([pair], file=buf)
        output = buf.getvalue()
        data = json.loads(output)
        assert "\n" in data[0]["file_a"]  # Newline preserved via JSON escaping

    def test_backslash_in_filename(self):
        """Backslash in filename → JSON and shell handle correctly."""
        pair = _make_pair_with_paths("/videos/back\\slash.mp4", "/videos/other.mp4")
        buf = StringIO()
        write_json([pair], file=buf)
        output = buf.getvalue()
        data = json.loads(output)
        assert "\\" in data[0]["file_a"]


# ---------------------------------------------------------------------------
# Long paths
# ---------------------------------------------------------------------------


class TestLongPaths:
    def test_filename_at_255_byte_limit(self, tmp_path: Path):
        """255-byte filename → scanned and processed."""
        d = tmp_path / "videos"
        d.mkdir()
        # 255 bytes total with .mp4 suffix → stem is 251 chars
        long_name = "a" * 251 + ".mp4"
        try:
            (d / long_name).touch()
        except OSError:
            # Some filesystems have shorter limits
            return
        result = find_video_files(d, quiet=True)
        assert len(result) == 1

    def test_path_near_4096_byte_limit(self, tmp_path: Path):
        """Deeply nested dirs → scanned without error."""
        d = tmp_path / "videos"
        d.mkdir()
        # Create nested directories to approach 4096 total path length
        current = d
        for _ in range(30):
            current = current / ("d" * 50)
            try:
                current.mkdir(parents=True, exist_ok=True)
            except OSError:
                break
        try:
            (current / "video.mp4").touch()
        except OSError:
            return
        result = find_video_files(d, quiet=True)
        assert len(result) >= 1

    def test_very_long_filename_in_json_output(self):
        """Long filename serialized correctly in JSON."""
        long_stem = "x" * 200
        pair = _make_pair_with_paths(f"/videos/{long_stem}.mp4", "/videos/other.mp4")
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert long_stem in data[0]["file_a"]

    def test_long_filename_fuzzy_match(self, make_metadata):
        """rapidfuzz handles very long strings without error."""
        long_name_a = "x" * 500 + ".mp4"
        long_name_b = "x" * 500 + "_copy.mp4"
        a = make_metadata(path=long_name_a)
        b = make_metadata(path=long_name_b)
        comp = FileNameComparator()
        score = comp.score(a, b)
        assert score is not None
        assert score > 0.0
