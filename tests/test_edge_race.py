"""Edge-case tests: race conditions (files becoming unreadable during scan).

Validates that files which exist at scan time but become unreadable
before metadata extraction, content hashing, or audio fingerprinting
are skipped gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from duplicates_detector.audio import compute_audio_fingerprint
from duplicates_detector.content import _extract_sparse_hashes, compute_image_content_hash
from duplicates_detector.metadata import extract_one


# ---------------------------------------------------------------------------
# File disappears during pipeline
# ---------------------------------------------------------------------------


class TestFileDisappearsDuringPipeline:
    def test_file_deleted_before_metadata_extraction(self, tmp_path: Path):
        """File exists at scan time, FileNotFoundError during ffprobe → None metadata."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)

        # Simulate file deleted between scan and extraction: stat() works, subprocess.run fails
        with patch(
            "duplicates_detector.metadata.subprocess.run",
            side_effect=FileNotFoundError("No such file"),
        ):
            meta = extract_one(f)

        # FileNotFoundError during subprocess.run is caught as OSError
        assert meta is not None
        assert meta.duration is None

    def test_file_deleted_before_content_hash(self):
        """File exists at metadata time, FileNotFoundError during ffmpeg → None hash."""
        with patch(
            "duplicates_detector.content.subprocess.run",
            side_effect=FileNotFoundError("No such file"),
        ):
            result = _extract_sparse_hashes(Path("/videos/deleted.mp4"), duration=60.0)

        # FileNotFoundError is a subclass of OSError, caught in _extract_single_frame_hash
        assert result is None

    def test_file_deleted_before_audio_fingerprint(self):
        """File exists at content time, FileNotFoundError during fpcalc → None fingerprint."""
        with patch(
            "duplicates_detector.audio.subprocess.run",
            side_effect=FileNotFoundError("No such file"),
        ):
            result = compute_audio_fingerprint(Path("/videos/deleted.mp4"), duration=60.0)

        # FileNotFoundError is caught as OSError
        assert result is None

    def test_file_permissions_changed_before_extraction(self, tmp_path: Path):
        """File readable at scan, PermissionError at extraction → None metadata."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)

        with patch(
            "duplicates_detector.metadata.subprocess.run",
            side_effect=PermissionError("Permission denied"),
        ):
            meta = extract_one(f)

        # PermissionError during subprocess.run is caught as OSError
        assert meta is not None
        assert meta.duration is None

    def test_file_replaced_with_directory(self, tmp_path: Path):
        """File replaced by directory between scan and extraction → graceful handling."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)

        # Simulate: stat() works but subprocess.run encounters a directory instead
        with patch(
            "duplicates_detector.metadata.subprocess.run",
            side_effect=IsADirectoryError("Is a directory"),
        ):
            meta = extract_one(f)

        # IsADirectoryError is a subclass of OSError
        assert meta is not None
        assert meta.duration is None

    def test_image_file_deleted_before_content_hash(self, tmp_path: Path):
        """Image file deleted between scan and PIL.Image.open → returns None."""
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\x00" * 100)
        f.unlink()  # Simulate deletion

        result = compute_image_content_hash(f)
        assert result is None


# ---------------------------------------------------------------------------
# Cache race conditions
# ---------------------------------------------------------------------------


class TestCacheRaceConditions:
    def test_cache_file_deleted_between_load_attempts(self, tmp_path: Path):
        """Cache file disappears during _load → starts with empty cache."""
        from duplicates_detector.cache import ContentHashCache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "content-hashes.json"
        cache_file.write_text(json.dumps({"version": 2, "entries": {}}))

        # Load cache, then corrupt the file, then try to load again
        cache = ContentHashCache(cache_dir=cache_dir)
        assert cache is not None  # No crash

        # Corrupt the cache file
        cache_file.write_text("NOT JSON AT ALL {{{")
        cache2 = ContentHashCache(cache_dir=cache_dir)
        # Should warn but not crash — starts with empty cache
        assert cache2 is not None
        assert (
            cache2.get(
                Path("/nonexistent.mp4"),
                100,
                1000.0,
                interval=2.0,
                hash_size=8,
            )
            is None
        )

    def test_cache_version_mismatch_discarded(self, tmp_path: Path):
        """Cache with wrong version → silently discarded, empty cache."""
        from duplicates_detector.cache import ContentHashCache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "content-hashes.json"
        cache_file.write_text(json.dumps({"version": 999, "entries": {}}))

        cache = ContentHashCache(cache_dir=cache_dir)
        assert (
            cache.get(
                Path("/test.mp4"),
                100,
                1000.0,
                interval=2.0,
                hash_size=8,
            )
            is None
        )
