from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.cache_db import CacheDB
from duplicates_detector.metadata import VideoMetadata, _extract_one_with_cache


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[CacheDB]:
    """Create a CacheDB instance with cleanup."""
    instance = CacheDB(tmp_path / "cache")
    yield instance
    instance.close()


def _make_meta(path: Path, **kwargs: object) -> VideoMetadata:
    """Build a VideoMetadata with sensible defaults, all fields overridable."""
    defaults: dict[str, object] = {
        "path": path,
        "filename": path.stem,
        "file_size": 1000,
        "duration": 60.0,
        "width": 1920,
        "height": 1080,
    }
    defaults.update(kwargs)
    return VideoMetadata(**defaults)  # type: ignore[arg-type]


# -----------------------------------------------------------------------
# _extract_one_with_cache
# -----------------------------------------------------------------------


class TestExtractOneWithCache:
    def test_cache_hit_skips_extraction(self, tmp_path: Path, cache: CacheDB) -> None:
        """When the cache has a matching entry, extraction is skipped entirely."""
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        st = p.stat()
        cached_data: dict[str, object] = {"duration": 120.0, "width": 1920, "height": 1080}
        cache.put_metadata(p, cached_data, file_size=st.st_size, mtime=st.st_mtime)

        with patch("duplicates_detector.metadata.extract_one") as mock_extract:
            result = _extract_one_with_cache(p, cache, mode="video")
            mock_extract.assert_not_called()

        assert result is not None
        assert result.duration == 120.0
        assert result.width == 1920
        assert result.filename == "video"

    def test_cache_miss_extracts_and_stores(self, tmp_path: Path, cache: CacheDB) -> None:
        """On cache miss, extracts metadata and stores the result."""
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        mock_meta = _make_meta(p, file_size=4, duration=60.0, width=1280, height=720)

        with patch("duplicates_detector.metadata.extract_one", return_value=mock_meta):
            result = _extract_one_with_cache(p, cache, mode="video")

        assert result is not None
        assert result.duration == 60.0
        assert result.width == 1280

        # Verify it was stored in the cache
        st = p.stat()
        cached = cache.get_metadata(p, file_size=st.st_size, mtime=st.st_mtime)
        assert cached is not None
        assert cached["duration"] == 60.0
        assert cached["width"] == 1280

    def test_stat_failure_returns_none(self, tmp_path: Path, cache: CacheDB) -> None:
        """When the file doesn't exist, returns None without touching the cache."""
        p = tmp_path / "nonexistent.mp4"
        result = _extract_one_with_cache(p, cache)
        assert result is None

    def test_no_cache_still_works(self, tmp_path: Path) -> None:
        """When cache_db is None, extraction works normally."""
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        mock_meta = _make_meta(p, file_size=4, duration=60.0, width=1280, height=720)

        with patch("duplicates_detector.metadata.extract_one", return_value=mock_meta):
            result = _extract_one_with_cache(p, None, mode="video")

        assert result is not None
        assert result.duration == 60.0

    def test_image_mode_uses_extract_one_image(self, tmp_path: Path, cache: CacheDB) -> None:
        """In image mode, delegates to extract_one_image."""
        p = tmp_path / "photo.jpg"
        p.write_bytes(b"fake-image")
        mock_meta = _make_meta(p, file_size=10, duration=None, width=4000, height=3000)

        with (
            patch("duplicates_detector.metadata.extract_one_image", return_value=mock_meta) as mock_img,
            patch("duplicates_detector.metadata.extract_one") as mock_vid,
        ):
            result = _extract_one_with_cache(p, cache, mode="image")
            mock_img.assert_called_once_with(p)
            mock_vid.assert_not_called()

        assert result is not None
        assert result.width == 4000

    def test_audio_mode_uses_extract_one_audio(self, tmp_path: Path, cache: CacheDB) -> None:
        """In audio mode, delegates to extract_one_audio."""
        p = tmp_path / "song.mp3"
        p.write_bytes(b"fake-audio")
        mock_meta = _make_meta(
            p,
            file_size=10,
            duration=180.0,
            width=None,
            height=None,
            tag_title="test",
            tag_artist="artist",
        )

        with (
            patch("duplicates_detector.metadata.extract_one_audio", return_value=mock_meta) as mock_aud,
            patch("duplicates_detector.metadata.extract_one") as mock_vid,
        ):
            result = _extract_one_with_cache(p, cache, mode="audio")
            mock_aud.assert_called_once_with(p)
            mock_vid.assert_not_called()

        assert result is not None
        assert result.tag_title == "test"

    def test_extraction_failure_returns_none_no_cache(self, tmp_path: Path, cache: CacheDB) -> None:
        """When extraction returns None, no cache entry is stored."""
        p = tmp_path / "corrupt.mp4"
        p.write_bytes(b"corrupt")

        with patch("duplicates_detector.metadata.extract_one", return_value=None):
            result = _extract_one_with_cache(p, cache, mode="video")

        assert result is None
        st = p.stat()
        assert cache.get_metadata(p, file_size=st.st_size, mtime=st.st_mtime) is None

    def test_cache_stores_all_fields(self, tmp_path: Path, cache: CacheDB) -> None:
        """All metadata fields (exif, tags, etc.) round-trip through the cache."""
        p = tmp_path / "rich.mp4"
        p.write_bytes(b"data")
        mock_meta = _make_meta(
            p,
            file_size=4,
            duration=30.0,
            width=1920,
            height=1080,
            codec="h264",
            bitrate=5000000,
            framerate=29.97,
            audio_channels=2,
            exif_datetime=1700000000.0,
            exif_camera="canon eos r5",
            exif_lens="rf 50mm f1.2",
            exif_gps_lat=40.7128,
            exif_gps_lon=-74.006,
            exif_width=8192,
            exif_height=5464,
            tag_title="clip",
            tag_artist="me",
            tag_album="album",
        )

        with patch("duplicates_detector.metadata.extract_one", return_value=mock_meta):
            _extract_one_with_cache(p, cache, mode="video")

        st = p.stat()
        cached = cache.get_metadata(p, file_size=st.st_size, mtime=st.st_mtime)
        assert cached is not None
        assert cached["codec"] == "h264"
        assert cached["exif_camera"] == "canon eos r5"
        assert cached["tag_title"] == "clip"
        assert cached["exif_gps_lat"] == 40.7128


# -----------------------------------------------------------------------
# _hash_one_with_cache
# -----------------------------------------------------------------------


class TestHashOneWithCache:
    def test_cache_hit_skips_hashing(self, tmp_path: Path, cache: CacheDB) -> None:
        """When the cache has a matching content hash, hashing is skipped."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake-video")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size)

        # Pre-populate the cache
        cache.put_content_hash(
            p,
            file_size=st.st_size,
            mtime=st.st_mtime,
            hashes=(123, 456, 789, 101),
            rotation_invariant=False,
        )

        with patch("duplicates_detector.content._extract_sparse_hashes") as mock_hash:
            result = _hash_one_with_cache(meta, cache)
            mock_hash.assert_not_called()

        assert result.content_hash == (123, 456, 789, 101)

    def test_cache_miss_computes_and_stores(self, tmp_path: Path, cache: CacheDB) -> None:
        """On cache miss, computes the hash and stores it."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake-video")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size)

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=(111, 222, 333, 444)):
            result = _hash_one_with_cache(meta, cache)

        assert result.content_hash == (111, 222, 333, 444)

        # Verify it was cached
        cached = cache.get_content_hash(
            p,
            file_size=st.st_size,
            mtime=st.st_mtime,
            rotation_invariant=False,
        )
        assert cached == (111, 222, 333, 444)

    def test_stat_failure_returns_unchanged(self, tmp_path: Path, cache: CacheDB) -> None:
        """When stat() fails, returns the original meta unchanged."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "gone.mp4"
        meta = _make_meta(p)
        result = _hash_one_with_cache(meta, cache)
        assert result is meta
        assert result.content_hash is None

    def test_no_cache_still_works(self, tmp_path: Path) -> None:
        """When cache_db is None, hashing works normally."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        meta = _make_meta(p, file_size=4)

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=(42, 43, 44, 45)):
            result = _hash_one_with_cache(meta, None)

        assert result.content_hash == (42, 43, 44, 45)

    def test_image_mode_uses_image_hash(self, tmp_path: Path, cache: CacheDB) -> None:
        """When is_image=True, uses compute_image_content_hash."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "photo.jpg"
        p.write_bytes(b"img")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size, duration=None)

        with (
            patch(
                "duplicates_detector.content.compute_image_content_hash",
                return_value=(99, 100, 101, 102),
            ) as mock_img,
            patch("duplicates_detector.content._extract_sparse_hashes") as mock_vid,
        ):
            result = _hash_one_with_cache(meta, cache, is_image=True)
            mock_img.assert_called_once()
            mock_vid.assert_not_called()

        assert result.content_hash == (99, 100, 101, 102)

        # Check that the cache stored the hash
        cached = cache.get_content_hash(
            p,
            file_size=st.st_size,
            mtime=st.st_mtime,
            rotation_invariant=False,
        )
        assert cached == (99, 100, 101, 102)

    def test_scene_strategy_uses_scene_hash(self, tmp_path: Path, cache: CacheDB) -> None:
        """PDQ hashing doesn't use strategy — this is now a basic video hash test."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"vid")
        meta = _make_meta(p, file_size=3)

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=(55, 66, 77, 88)):
            result = _hash_one_with_cache(meta, cache)

        assert result.content_hash == (55, 66, 77, 88)

    def test_hash_none_not_cached(self, tmp_path: Path, cache: CacheDB) -> None:
        """When hashing returns None, no entry is stored in cache."""
        from duplicates_detector.content import _hash_one_with_cache

        p = tmp_path / "broken.mp4"
        p.write_bytes(b"bad")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size)

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=None):
            result = _hash_one_with_cache(meta, cache)

        assert result.content_hash is None
        cached = cache.get_content_hash(
            p,
            file_size=st.st_size,
            mtime=st.st_mtime,
            rotation_invariant=False,
        )
        assert cached is None


# -----------------------------------------------------------------------
# _fingerprint_one_with_cache
# -----------------------------------------------------------------------


class TestFingerprintOneWithCache:
    def test_cache_hit_skips_fpcalc(self, tmp_path: Path, cache: CacheDB) -> None:
        """When the cache has a matching fingerprint, fpcalc is skipped."""
        from duplicates_detector.audio import _fingerprint_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size)

        fp = tuple(range(100))
        cache.put_audio_fingerprint(
            p,
            file_size=st.st_size,
            mtime=st.st_mtime,
            fingerprint=fp,
        )

        with patch("duplicates_detector.audio.compute_audio_fingerprint") as mock_fp:
            result = _fingerprint_one_with_cache(meta, cache)
            mock_fp.assert_not_called()

        assert result.audio_fingerprint == fp

    def test_cache_miss_computes_and_stores(self, tmp_path: Path, cache: CacheDB) -> None:
        """On cache miss, computes the fingerprint and stores it."""
        from duplicates_detector.audio import _fingerprint_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size)

        fp = tuple(range(50))
        with patch("duplicates_detector.audio.compute_audio_fingerprint", return_value=fp):
            result = _fingerprint_one_with_cache(meta, cache)

        assert result.audio_fingerprint == fp

        # Verify it was cached
        cached = cache.get_audio_fingerprint(p, file_size=st.st_size, mtime=st.st_mtime)
        assert cached == fp

    def test_stat_failure_returns_unchanged(self, tmp_path: Path, cache: CacheDB) -> None:
        """When stat() fails, returns the original meta unchanged."""
        from duplicates_detector.audio import _fingerprint_one_with_cache

        p = tmp_path / "gone.mp4"
        meta = _make_meta(p)
        result = _fingerprint_one_with_cache(meta, cache)
        assert result is meta
        assert result.audio_fingerprint is None

    def test_no_cache_still_works(self, tmp_path: Path) -> None:
        """When cache_db is None, fingerprinting works normally."""
        from duplicates_detector.audio import _fingerprint_one_with_cache

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        meta = _make_meta(p, file_size=4)

        fp = tuple(range(30))
        with patch("duplicates_detector.audio.compute_audio_fingerprint", return_value=fp):
            result = _fingerprint_one_with_cache(meta, None)

        assert result.audio_fingerprint == fp

    def test_fingerprint_none_not_cached(self, tmp_path: Path, cache: CacheDB) -> None:
        """When fingerprinting returns None, no entry is stored in cache."""
        from duplicates_detector.audio import _fingerprint_one_with_cache

        p = tmp_path / "noaudio.mp4"
        p.write_bytes(b"no-audio")
        st = p.stat()
        meta = _make_meta(p, file_size=st.st_size)

        with patch("duplicates_detector.audio.compute_audio_fingerprint", return_value=None):
            result = _fingerprint_one_with_cache(meta, cache)

        assert result.audio_fingerprint is None
        cached = cache.get_audio_fingerprint(p, file_size=st.st_size, mtime=st.st_mtime)
        assert cached is None
