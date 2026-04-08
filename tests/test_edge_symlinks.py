"""Edge-case tests: circular symlinks.

Validates that circular, self-referencing, and dangling symlinks are
detected and skipped during scanning without hanging or crashing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from duplicates_detector.scanner import find_video_files

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="symlinks not reliable on Windows")


# ---------------------------------------------------------------------------
# Circular / broken symlinks
# ---------------------------------------------------------------------------


class TestCircularSymlinks:
    def test_self_referencing_symlink_skipped(self, tmp_path: Path):
        """symlink a.mp4 -> a.mp4 → skipped (not a regular file), no infinite loop."""
        d = tmp_path / "videos"
        d.mkdir()
        link = d / "a.mp4"
        try:
            link.symlink_to(link)
        except OSError:
            pytest.skip("Cannot create self-referencing symlink on this OS")
        result = find_video_files(d, quiet=True)
        assert len(result) == 0

    def test_circular_pair_skipped(self, tmp_path: Path):
        """a.mp4 -> b.mp4 -> a.mp4 → both skipped or deduplicated, no hang."""
        d = tmp_path / "videos"
        d.mkdir()
        a = d / "a.mp4"
        b = d / "b.mp4"
        try:
            a.symlink_to(b)
            b.symlink_to(a)
        except OSError:
            pytest.skip("Cannot create circular symlinks on this OS")
        result = find_video_files(d, quiet=True)
        # Circular symlinks are not regular files — is_file() returns False
        assert len(result) == 0

    def test_deep_circular_chain_skipped(self, tmp_path: Path):
        """a -> b -> c -> d -> a → resolved without infinite loop."""
        d = tmp_path / "videos"
        d.mkdir()
        links = [d / f"{c}.mp4" for c in "abcd"]
        try:
            for i, link in enumerate(links):
                link.symlink_to(links[(i + 1) % len(links)])
        except OSError:
            pytest.skip("Cannot create circular symlinks on this OS")
        result = find_video_files(d, quiet=True)
        assert len(result) == 0

    def test_dangling_symlink_skipped(self, tmp_path: Path):
        """Symlink target deleted → file skipped during scan."""
        d = tmp_path / "videos"
        d.mkdir()
        target = d / "real.mp4"
        target.touch()
        link = d / "link.mp4"
        link.symlink_to(target)
        target.unlink()  # Now the symlink dangles
        result = find_video_files(d, quiet=True)
        assert len(result) == 0

    def test_symlink_to_directory_skipped(self, tmp_path: Path):
        """Symlink points to a directory → skipped by is_file()."""
        d = tmp_path / "videos"
        d.mkdir()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        link = d / "link.mp4"
        link.symlink_to(subdir)
        result = find_video_files(d, quiet=True)
        assert len(result) == 0

    def test_broken_symlink_in_metadata_extraction(self, tmp_path: Path):
        """Symlink target disappears between scan and extraction → None metadata."""
        d = tmp_path / "videos"
        d.mkdir()
        target = d / "real.mp4"
        target.write_bytes(b"\x00" * 100)

        from duplicates_detector.metadata import extract_one

        # Simulate: file exists for stat but then disappears for ffprobe
        original_stat = Path.stat

        call_count = 0

        def mock_stat(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1 and self == target:
                raise FileNotFoundError("File disappeared")
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", mock_stat):
            meta = extract_one(target)

        # First stat() succeeds (for file_size), but subsequent operations may fail
        # The function catches FileNotFoundError and returns None
        assert meta is None or meta.duration is None

    def test_valid_symlink_resolves_and_deduplicates(self, tmp_path: Path):
        """Valid symlink to a real file → deduplicated by resolve()."""
        d = tmp_path / "videos"
        d.mkdir()
        real = d / "real.mp4"
        real.touch()
        link = d / "link.mp4"
        link.symlink_to(real)
        result = find_video_files(d, quiet=True)
        # Both resolve to the same path → only one in results
        assert len(result) == 1
