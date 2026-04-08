from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from duplicates_detector.cache import (
    ContentHashCache,
    _CACHE_FILENAME,
    _CACHE_VERSION,
    MetadataCache,
    _METADATA_CACHE_FILENAME,
    _METADATA_CACHE_VERSION,
)


@pytest.fixture
def cache_dir(tmp_path):
    """Provide a temporary directory for the cache."""
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def sample_hash():
    return (0xABCD, 0x1234, 0x5678)


class TestContentHashCache:
    def test_cache_hit(self, cache_dir, sample_hash):
        """Pre-populated cache returns stored hash on get()."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8)
        assert result == sample_hash
        assert cache.hits == 1
        assert cache.misses == 0

    def test_cache_miss_stale_mtime(self, cache_dir, sample_hash):
        """Different mtime causes a cache miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 100.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=999.0, interval=2.0, hash_size=8)
        assert result is None
        assert cache.misses == 1

    def test_cache_miss_stale_size(self, cache_dir, sample_hash):
        """Different file_size causes a cache miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=9999, mtime=123.0, interval=2.0, hash_size=8)
        assert result is None
        assert cache.misses == 1

    def test_cache_miss_different_interval(self, cache_dir, sample_hash):
        """Different interval causes a cache miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=5.0, hash_size=8)
        assert result is None
        assert cache.misses == 1

    def test_cache_miss_different_hash_size(self, cache_dir, sample_hash):
        """Different hash_size causes a cache miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=16)
        assert result is None
        assert cache.misses == 1

    def test_cache_put_and_get(self, cache_dir, sample_hash):
        """Round-trip: put() then get() returns the hash."""
        cache = ContentHashCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")

        cache.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8)
        result = cache.get(p, file_size=500, mtime=42.0, interval=2.0, hash_size=8)

        assert result == sample_hash
        assert cache.hits == 1

    def test_cache_save_and_load(self, cache_dir, sample_hash):
        """Save to disk, create new instance, verify data persists."""
        p = Path("/videos/test.mp4")
        cache1 = ContentHashCache(cache_dir=cache_dir)
        cache1.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8)
        cache1.save()

        # New instance should load from disk
        cache2 = ContentHashCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0, interval=2.0, hash_size=8)
        assert result == sample_hash

    def test_cache_corrupt_file(self, cache_dir):
        """Garbage in cache file results in fresh cache."""
        (cache_dir / _CACHE_FILENAME).write_text("NOT JSON!!!")

        with pytest.warns(UserWarning, match="corrupt"):
            cache = ContentHashCache(cache_dir=cache_dir)

        # Should behave as empty cache
        result = cache.get(Path("/x.mp4"), file_size=1, mtime=1.0, interval=2.0, hash_size=8)
        assert result is None

    def test_cache_missing_file(self, cache_dir):
        """No cache file on disk results in fresh cache."""
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(Path("/x.mp4"), file_size=1, mtime=1.0, interval=2.0, hash_size=8)
        assert result is None
        assert cache.misses == 1

    def test_cache_version_mismatch(self, cache_dir, sample_hash):
        """Wrong version number results in fresh cache."""
        p = Path("/videos/test.mp4")
        data = {
            "version": 999,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8)
        assert result is None

    def test_cache_atomic_write(self, cache_dir, sample_hash):
        """save() writes to a tempfile then renames (no partial writes)."""
        cache = ContentHashCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        cache.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8)

        # Before save, cache file should not exist
        assert not (cache_dir / _CACHE_FILENAME).exists()

        cache.save()

        # After save, cache file should exist and be valid JSON
        assert (cache_dir / _CACHE_FILENAME).exists()
        loaded = json.loads((cache_dir / _CACHE_FILENAME).read_text())
        assert loaded["version"] == _CACHE_VERSION
        assert str(p.resolve()) in loaded["hashes"]

    def test_xdg_cache_home(self, tmp_path):
        """XDG_CACHE_HOME environment variable is respected."""
        xdg_dir = tmp_path / "xdg-cache"
        xdg_dir.mkdir()

        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(xdg_dir)}):
            cache = ContentHashCache()

        expected = xdg_dir / "duplicates-detector"
        assert cache._cache_dir == expected

    def test_default_cache_dir_without_xdg(self):
        """Without XDG_CACHE_HOME, falls back to ~/.cache/."""
        env = os.environ.copy()
        env.pop("XDG_CACHE_HOME", None)
        with patch.dict(os.environ, env, clear=True):
            cache = ContentHashCache()

        assert cache._cache_dir == Path.home() / ".cache" / "duplicates-detector"

    def test_save_creates_directory(self, tmp_path, sample_hash):
        """save() creates the cache directory if it doesn't exist."""
        cache_dir = tmp_path / "nonexistent" / "nested"
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(Path("/a.mp4"), file_size=1, mtime=1.0, content_hash=sample_hash, interval=2.0, hash_size=8)
        cache.save()

        assert cache_dir.exists()
        assert (cache_dir / _CACHE_FILENAME).exists()

    def test_get_with_none_mtime(self, cache_dir):
        """Cache works correctly when mtime is None."""
        cache = ContentHashCache(cache_dir=cache_dir)
        h = (1, 2, 3)
        cache.put(Path("/a.mp4"), file_size=100, mtime=None, content_hash=h, interval=2.0, hash_size=8)

        result = cache.get(Path("/a.mp4"), file_size=100, mtime=None, interval=2.0, hash_size=8)
        assert result == h

        # Non-None mtime should miss
        result2 = cache.get(Path("/a.mp4"), file_size=100, mtime=1.0, interval=2.0, hash_size=8)
        assert result2 is None

    def test_non_dict_entry_is_cache_miss(self, cache_dir):
        """Malformed entry (not a dict) is treated as a miss, not an error."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {str(p.resolve()): "not a dict"},
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8)
        assert result is None
        assert cache.misses == 1

    def test_non_integer_hash_elements_is_cache_miss(self, cache_dir):
        """Hash list with non-integer elements is treated as a miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": ["a", "b", "c"],
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))

        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8)
        assert result is None
        assert cache.misses == 1


class TestContentHashCacheAlgorithm:
    """Tests for the algorithm field in ContentHashCache."""

    def test_cache_hit_with_algorithm(self, cache_dir, sample_hash):
        """Cache hit when algorithm matches."""
        p = Path("/videos/test.mp4")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8, algorithm="dhash")
        result = cache.get(p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, algorithm="dhash")
        assert result == sample_hash
        assert cache.hits == 1

    def test_cache_miss_algorithm_mismatch(self, cache_dir, sample_hash):
        """Different algorithm causes a cache miss."""
        p = Path("/videos/test.mp4")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8, algorithm="dhash")
        result = cache.get(p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, algorithm="phash")
        assert result is None
        assert cache.misses == 1

    def test_missing_algorithm_defaults_to_phash(self, cache_dir, sample_hash):
        """Legacy cache entry without 'algorithm' key matches phash requests."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                    # No "algorithm" key — legacy entry
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8, algorithm="phash")
        assert result == sample_hash
        assert cache.hits == 1

    def test_missing_algorithm_non_phash_misses(self, cache_dir, sample_hash):
        """Legacy cache entry without 'algorithm' key misses for non-phash requests."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8, algorithm="dhash")
        assert result is None
        assert cache.misses == 1

    def test_algorithm_persisted_to_disk(self, cache_dir, sample_hash):
        """Algorithm field survives save/load cycle."""
        p = Path("/videos/test.mp4")
        cache1 = ContentHashCache(cache_dir=cache_dir)
        cache1.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8, algorithm="whash")
        cache1.save()
        cache2 = ContentHashCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, algorithm="whash")
        assert result == sample_hash

    def test_default_algorithm_is_phash(self, cache_dir, sample_hash):
        """Omitting algorithm parameter defaults to phash."""
        p = Path("/videos/test.mp4")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(p, file_size=500, mtime=42.0, content_hash=sample_hash, interval=2.0, hash_size=8)
        result = cache.get(p, file_size=500, mtime=42.0, interval=2.0, hash_size=8)
        assert result == sample_hash


class TestContentHashCacheRotationInvariant:
    """Tests for the rotation_invariant field in ContentHashCache."""

    def test_cache_hit_with_rotation_invariant(self, cache_dir, sample_hash):
        """Cache hit when rotation_invariant matches."""
        p = Path("/images/test.png")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=0.0,
            hash_size=8,
            rotation_invariant=True,
        )
        result = cache.get(p, file_size=500, mtime=42.0, interval=0.0, hash_size=8, rotation_invariant=True)
        assert result == sample_hash
        assert cache.hits == 1

    def test_cache_miss_rotation_invariant_mismatch(self, cache_dir, sample_hash):
        """Different rotation_invariant value causes a cache miss."""
        p = Path("/images/test.png")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=0.0,
            hash_size=8,
            rotation_invariant=True,
        )
        result = cache.get(p, file_size=500, mtime=42.0, interval=0.0, hash_size=8, rotation_invariant=False)
        assert result is None
        assert cache.misses == 1

    def test_missing_rotation_invariant_defaults_false(self, cache_dir, sample_hash):
        """Legacy cache entry without 'rotation_invariant' key matches False requests."""
        p = Path("/images/test.png")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 0.0,
                    "hash_size": 8,
                    "algorithm": "phash",
                    # No "rotation_invariant" key — legacy entry
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=0.0, hash_size=8, rotation_invariant=False)
        assert result == sample_hash
        assert cache.hits == 1

    def test_missing_rotation_invariant_misses_for_true(self, cache_dir, sample_hash):
        """Legacy cache entry without 'rotation_invariant' misses for True requests."""
        p = Path("/images/test.png")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 0.0,
                    "hash_size": 8,
                    "algorithm": "phash",
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=0.0, hash_size=8, rotation_invariant=True)
        assert result is None
        assert cache.misses == 1

    def test_rotation_invariant_stores_8_hashes(self, cache_dir):
        """8-tuple hashes round-trip correctly through the cache."""
        p = Path("/images/test.png")
        h8 = tuple(range(8))
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=h8,
            interval=0.0,
            hash_size=8,
            rotation_invariant=True,
        )
        result = cache.get(p, file_size=500, mtime=42.0, interval=0.0, hash_size=8, rotation_invariant=True)
        assert result == h8

    def test_rotation_invariant_persisted_to_disk(self, cache_dir, sample_hash):
        """rotation_invariant field survives save/load cycle."""
        p = Path("/images/test.png")
        cache1 = ContentHashCache(cache_dir=cache_dir)
        cache1.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=0.0,
            hash_size=8,
            rotation_invariant=True,
        )
        cache1.save()
        cache2 = ContentHashCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0, interval=0.0, hash_size=8, rotation_invariant=True)
        assert result == sample_hash


class TestContentHashCacheStrategy:
    """Tests for the strategy and scene_threshold fields in ContentHashCache."""

    def test_scene_cache_hit(self, cache_dir, sample_hash):
        """Cache hit when strategy and scene_threshold match."""
        p = Path("/videos/test.mp4")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=2.0,
            hash_size=8,
            strategy="scene",
            scene_threshold=0.3,
        )
        result = cache.get(
            p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, strategy="scene", scene_threshold=0.3
        )
        assert result == sample_hash
        assert cache.hits == 1

    def test_scene_vs_interval_no_collision(self, cache_dir, sample_hash):
        """Scene and interval entries for the same file don't collide."""
        p = Path("/videos/test.mp4")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=2.0,
            hash_size=8,
            strategy="interval",
        )
        result = cache.get(
            p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, strategy="scene", scene_threshold=0.3
        )
        assert result is None
        assert cache.misses == 1

    def test_different_thresholds_no_collision(self, cache_dir, sample_hash):
        """Different scene_threshold values cause a cache miss."""
        p = Path("/videos/test.mp4")
        cache = ContentHashCache(cache_dir=cache_dir)
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=2.0,
            hash_size=8,
            strategy="scene",
            scene_threshold=0.3,
        )
        result = cache.get(
            p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, strategy="scene", scene_threshold=0.5
        )
        assert result is None
        assert cache.misses == 1

    def test_missing_strategy_defaults_to_interval(self, cache_dir, sample_hash):
        """Legacy cache entry without 'strategy' key matches interval requests."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                    # No "strategy" key — legacy entry
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8, strategy="interval")
        assert result == sample_hash
        assert cache.hits == 1

    def test_missing_strategy_non_interval_misses(self, cache_dir, sample_hash):
        """Legacy cache entry without 'strategy' misses for scene requests."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _CACHE_VERSION,
            "hashes": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "hash": list(sample_hash),
                    "interval": 2.0,
                    "hash_size": 8,
                }
            },
        }
        (cache_dir / _CACHE_FILENAME).write_text(json.dumps(data))
        cache = ContentHashCache(cache_dir=cache_dir)
        result = cache.get(
            p, file_size=1000, mtime=123.0, interval=2.0, hash_size=8, strategy="scene", scene_threshold=0.3
        )
        assert result is None
        assert cache.misses == 1

    def test_strategy_persisted_to_disk(self, cache_dir, sample_hash):
        """Strategy and scene_threshold fields survive save/load cycle."""
        p = Path("/videos/test.mp4")
        cache1 = ContentHashCache(cache_dir=cache_dir)
        cache1.put(
            p,
            file_size=500,
            mtime=42.0,
            content_hash=sample_hash,
            interval=2.0,
            hash_size=8,
            strategy="scene",
            scene_threshold=0.4,
        )
        cache1.save()
        cache2 = ContentHashCache(cache_dir=cache_dir)
        result = cache2.get(
            p, file_size=500, mtime=42.0, interval=2.0, hash_size=8, strategy="scene", scene_threshold=0.4
        )
        assert result == sample_hash


class TestMetadataCache:
    def test_cache_hit(self, cache_dir):
        """Pre-populated cache returns stored metadata on get()."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "duration": 90.5,
                    "width": 1920,
                    "height": 1080,
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0)
        assert result == {
            "duration": 90.5,
            "width": 1920,
            "height": 1080,
            "codec": None,
            "bitrate": None,
            "framerate": None,
            "audio_channels": None,
            "exif_datetime": None,
            "exif_camera": None,
            "exif_lens": None,
            "exif_gps_lat": None,
            "exif_gps_lon": None,
            "exif_width": None,
            "exif_height": None,
            "tag_title": None,
            "tag_artist": None,
            "tag_album": None,
        }
        assert cache.hits == 1
        assert cache.misses == 0

    def test_cache_miss_not_found(self, cache_dir):
        """Unknown path returns None."""
        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(Path("/unknown.mp4"), file_size=1, mtime=1.0)
        assert result is None
        assert cache.misses == 1

    def test_cache_miss_stale_mtime(self, cache_dir):
        """Different mtime causes a cache miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 100.0,
                    "duration": 90.5,
                    "width": 1920,
                    "height": 1080,
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=999.0)
        assert result is None
        assert cache.misses == 1

    def test_cache_miss_stale_size(self, cache_dir):
        """Different file_size causes a cache miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "duration": 90.5,
                    "width": 1920,
                    "height": 1080,
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=9999, mtime=123.0)
        assert result is None
        assert cache.misses == 1

    def test_preserves_none_values(self, cache_dir):
        """Cached None duration/width/height are returned faithfully."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 500,
                    "mtime": 42.0,
                    "duration": None,
                    "width": None,
                    "height": None,
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=500, mtime=42.0)
        assert result == {
            "duration": None,
            "width": None,
            "height": None,
            "codec": None,
            "bitrate": None,
            "framerate": None,
            "audio_channels": None,
            "exif_datetime": None,
            "exif_camera": None,
            "exif_lens": None,
            "exif_gps_lat": None,
            "exif_gps_lon": None,
            "exif_width": None,
            "exif_height": None,
            "tag_title": None,
            "tag_artist": None,
            "tag_album": None,
        }
        assert cache.hits == 1

    def test_put_and_get_roundtrip(self, cache_dir):
        """Round-trip: put() then get() returns the stored values."""
        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")

        cache.put(p, file_size=500, mtime=42.0, duration=120.5, width=1280, height=720)
        result = cache.get(p, file_size=500, mtime=42.0)

        assert result == {
            "duration": 120.5,
            "width": 1280,
            "height": 720,
            "codec": None,
            "bitrate": None,
            "framerate": None,
            "audio_channels": None,
            "exif_datetime": None,
            "exif_camera": None,
            "exif_lens": None,
            "exif_gps_lat": None,
            "exif_gps_lon": None,
            "exif_width": None,
            "exif_height": None,
            "tag_title": None,
            "tag_artist": None,
            "tag_album": None,
        }
        assert cache.hits == 1

    def test_save_and_load_roundtrip(self, cache_dir):
        """Save to disk, create new instance, verify data persists."""
        p = Path("/videos/test.mp4")
        cache1 = MetadataCache(cache_dir=cache_dir)
        cache1.put(p, file_size=500, mtime=42.0, duration=120.5, width=1280, height=720)
        cache1.save()

        cache2 = MetadataCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0)
        assert result == {
            "duration": 120.5,
            "width": 1280,
            "height": 720,
            "codec": None,
            "bitrate": None,
            "framerate": None,
            "audio_channels": None,
            "exif_datetime": None,
            "exif_camera": None,
            "exif_lens": None,
            "exif_gps_lat": None,
            "exif_gps_lon": None,
            "exif_width": None,
            "exif_height": None,
            "tag_title": None,
            "tag_artist": None,
            "tag_album": None,
        }

    def test_put_and_get_roundtrip_with_new_fields(self, cache_dir):
        """Round-trip with codec/bitrate/framerate/audio_channels populated."""
        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")

        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            duration=120.5,
            width=1280,
            height=720,
            codec="hevc",
            bitrate=5_000_000,
            framerate=29.97,
            audio_channels=6,
        )
        result = cache.get(p, file_size=500, mtime=42.0)

        assert result == {
            "duration": 120.5,
            "width": 1280,
            "height": 720,
            "codec": "hevc",
            "bitrate": 5_000_000,
            "framerate": 29.97,
            "audio_channels": 6,
            "exif_datetime": None,
            "exif_camera": None,
            "exif_lens": None,
            "exif_gps_lat": None,
            "exif_gps_lon": None,
            "exif_width": None,
            "exif_height": None,
            "tag_title": None,
            "tag_artist": None,
            "tag_album": None,
        }

    def test_save_and_load_roundtrip_with_new_fields(self, cache_dir):
        """Save/load preserves new fields through disk persistence."""
        p = Path("/videos/test.mp4")
        cache1 = MetadataCache(cache_dir=cache_dir)
        cache1.put(
            p,
            file_size=500,
            mtime=42.0,
            duration=120.5,
            width=1280,
            height=720,
            codec="h264",
            bitrate=8_000_000,
            framerate=23.976,
            audio_channels=2,
        )
        cache1.save()

        cache2 = MetadataCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0)
        assert result is not None
        assert result["codec"] == "h264"
        assert result["bitrate"] == 8_000_000
        assert result["framerate"] == 23.976
        assert result["audio_channels"] == 2

    def test_auto_prune_on_save(self, cache_dir):
        """Only entries accessed in this session survive save."""
        p1 = Path("/videos/a.mp4")
        p2 = Path("/videos/b.mp4")

        # Seed cache with two entries
        cache1 = MetadataCache(cache_dir=cache_dir)
        cache1.put(p1, file_size=100, mtime=1.0, duration=60.0, width=1920, height=1080)
        cache1.put(p2, file_size=200, mtime=2.0, duration=90.0, width=1280, height=720)
        cache1.save()

        # New session: only access p1
        cache2 = MetadataCache(cache_dir=cache_dir)
        cache2.get(p1, file_size=100, mtime=1.0)  # hit — marks as accessed
        # p2 not accessed
        cache2.save()

        # Verify p2 was pruned
        cache3 = MetadataCache(cache_dir=cache_dir)
        assert cache3.get(p1, file_size=100, mtime=1.0) is not None
        assert cache3.get(p2, file_size=200, mtime=2.0) is None

    def test_corrupt_file(self, cache_dir):
        """Garbage in cache file results in fresh cache."""
        (cache_dir / _METADATA_CACHE_FILENAME).write_text("NOT JSON!!!")

        with pytest.warns(UserWarning, match="corrupt"):
            cache = MetadataCache(cache_dir=cache_dir)

        result = cache.get(Path("/x.mp4"), file_size=1, mtime=1.0)
        assert result is None

    def test_missing_file(self, cache_dir):
        """No cache file on disk results in fresh cache."""
        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(Path("/x.mp4"), file_size=1, mtime=1.0)
        assert result is None
        assert cache.misses == 1

    def test_version_mismatch(self, cache_dir):
        """Wrong version number results in fresh cache."""
        p = Path("/videos/test.mp4")
        data = {
            "version": 999,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "duration": 90.5,
                    "width": 1920,
                    "height": 1080,
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0)
        assert result is None

    def test_v1_cache_silently_discarded(self, cache_dir):
        """Old v1 cache (pre-codec fields) is silently discarded."""
        p = Path("/videos/test.mp4")
        data = {
            "version": 1,  # old version
            "metadata": {
                str(p.resolve()): {
                    "file_size": 1000,
                    "mtime": 123.0,
                    "duration": 90.5,
                    "width": 1920,
                    "height": 1080,
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0)
        assert result is None  # v1 != v2, treated as empty cache

    def test_atomic_write(self, cache_dir):
        """save() writes to a tempfile then renames (no partial writes)."""
        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        cache.put(p, file_size=500, mtime=42.0, duration=120.5, width=1280, height=720)

        assert not (cache_dir / _METADATA_CACHE_FILENAME).exists()

        cache.save()

        assert (cache_dir / _METADATA_CACHE_FILENAME).exists()
        loaded = json.loads((cache_dir / _METADATA_CACHE_FILENAME).read_text())
        assert loaded["version"] == _METADATA_CACHE_VERSION
        assert str(p.resolve()) in loaded["metadata"]

    def test_xdg_cache_home(self, tmp_path):
        """XDG_CACHE_HOME environment variable is respected."""
        xdg_dir = tmp_path / "xdg-cache"
        xdg_dir.mkdir()

        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(xdg_dir)}):
            cache = MetadataCache()

        expected = xdg_dir / "duplicates-detector"
        assert cache._cache_dir == expected

    def test_default_cache_dir_without_xdg(self):
        """Without XDG_CACHE_HOME, falls back to ~/.cache/."""
        env = os.environ.copy()
        env.pop("XDG_CACHE_HOME", None)
        with patch.dict(os.environ, env, clear=True):
            cache = MetadataCache()

        assert cache._cache_dir == Path.home() / ".cache" / "duplicates-detector"

    def test_hit_miss_counters(self, cache_dir):
        """hits and misses counters increment correctly."""
        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        cache.put(p, file_size=500, mtime=42.0, duration=60.0, width=1920, height=1080)

        cache.get(p, file_size=500, mtime=42.0)  # hit
        cache.get(p, file_size=500, mtime=42.0)  # hit
        cache.get(p, file_size=999, mtime=42.0)  # miss (stale size)
        cache.get(Path("/other.mp4"), file_size=1, mtime=1.0)  # miss (not found)

        assert cache.hits == 2
        assert cache.misses == 2

    def test_non_dict_entry_is_miss(self, cache_dir):
        """Malformed entry (not a dict) is treated as a miss."""
        p = Path("/videos/test.mp4")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {str(p.resolve()): "not a dict"},
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0)
        assert result is None
        assert cache.misses == 1

    @pytest.mark.parametrize(
        "bad_field,bad_value",
        [
            ("duration", "oops"),
            ("width", 3.14),
            ("height", "big"),
            ("duration", [1, 2]),
            ("width", {"x": 1}),
            ("codec", 123),
            ("bitrate", "fast"),
            ("framerate", "slow"),
            ("audio_channels", 3.14),
        ],
    )
    def test_malformed_metadata_values_are_miss(self, cache_dir, bad_field, bad_value):
        """Non-numeric/wrong-type values in cached entry are treated as a miss."""
        p = Path("/videos/test.mp4")
        entry = {
            "file_size": 1000,
            "mtime": 123.0,
            "duration": 90.5,
            "width": 1920,
            "height": 1080,
        }
        entry[bad_field] = bad_value
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {str(p.resolve()): entry},
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=1000, mtime=123.0)
        assert result is None
        assert cache.misses == 1

    def test_save_creates_directory(self, tmp_path):
        """save() creates the cache directory if it doesn't exist."""
        cache_dir = tmp_path / "nonexistent" / "nested"
        cache = MetadataCache(cache_dir=cache_dir)
        cache.put(Path("/a.mp4"), file_size=1, mtime=1.0, duration=60.0, width=1920, height=1080)
        cache.save()

        assert cache_dir.exists()
        assert (cache_dir / _METADATA_CACHE_FILENAME).exists()


class TestMetadataCacheExif:
    """Tests for EXIF fields in MetadataCache."""

    def test_exif_roundtrip(self, cache_dir):
        """EXIF fields round-trip through put/get."""
        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/images/test.jpg")
        cache.put(
            p,
            file_size=500,
            mtime=42.0,
            duration=None,
            width=4000,
            height=3000,
            exif_datetime=1_700_000_000.0,
            exif_camera="canon eos r5",
            exif_lens="rf 24-70mm f2.8l",
            exif_gps_lat=40.7128,
            exif_gps_lon=-74.006,
            exif_width=4000,
            exif_height=3000,
        )
        result = cache.get(p, file_size=500, mtime=42.0)
        assert result is not None
        assert result["exif_datetime"] == 1_700_000_000.0
        assert result["exif_camera"] == "canon eos r5"
        assert result["exif_lens"] == "rf 24-70mm f2.8l"
        assert result["exif_gps_lat"] == pytest.approx(40.7128)
        assert result["exif_gps_lon"] == pytest.approx(-74.006)
        assert result["exif_width"] == 4000
        assert result["exif_height"] == 3000

    def test_backward_compat_missing_exif(self, cache_dir):
        """Old cache entries without EXIF fields return None for all EXIF keys."""
        p = Path("/images/test.jpg")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 500,
                    "mtime": 42.0,
                    "duration": None,
                    "width": 1920,
                    "height": 1080,
                    # No EXIF fields — legacy entry
                }
            },
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))
        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=500, mtime=42.0)
        assert result is not None
        assert result["exif_datetime"] is None
        assert result["exif_camera"] is None
        assert result["exif_lens"] is None
        assert result["exif_gps_lat"] is None
        assert result["exif_gps_lon"] is None
        assert result["exif_width"] is None
        assert result["exif_height"] is None

    def test_exif_persisted_to_disk(self, cache_dir):
        """EXIF fields survive save/load cycle."""
        p = Path("/images/test.jpg")
        cache1 = MetadataCache(cache_dir=cache_dir)
        cache1.put(
            p,
            file_size=500,
            mtime=42.0,
            duration=None,
            width=4000,
            height=3000,
            exif_datetime=1_700_000_000.0,
            exif_camera="canon eos r5",
        )
        cache1.save()

        cache2 = MetadataCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0)
        assert result is not None
        assert result["exif_datetime"] == 1_700_000_000.0
        assert result["exif_camera"] == "canon eos r5"

    @pytest.mark.parametrize(
        "bad_field,bad_value",
        [
            ("exif_datetime", "oops"),
            ("exif_camera", 123),
            ("exif_lens", 456),
            ("exif_gps_lat", "north"),
            ("exif_gps_lon", [1, 2]),
            ("exif_width", 3.14),
            ("exif_height", "big"),
        ],
    )
    def test_malformed_exif_values_are_miss(self, cache_dir, bad_field, bad_value):
        """Non-matching types in EXIF cache fields are treated as a miss."""
        p = Path("/images/test.jpg")
        entry = {
            "file_size": 500,
            "mtime": 42.0,
            "duration": None,
            "width": 4000,
            "height": 3000,
        }
        entry[bad_field] = bad_value
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {str(p.resolve()): entry},
        }
        (cache_dir / _METADATA_CACHE_FILENAME).write_text(json.dumps(data))
        cache = MetadataCache(cache_dir=cache_dir)
        result = cache.get(p, file_size=500, mtime=42.0)
        assert result is None
        assert cache.misses == 1


# ---------------------------------------------------------------------------
# AudioFingerprintCache
# ---------------------------------------------------------------------------


class TestAudioFingerprintCache:
    def test_put_get_roundtrip(self, cache_dir):
        """put() followed by get() returns the fingerprint."""
        from duplicates_detector.cache import AudioFingerprintCache

        cache = AudioFingerprintCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        fp = (100, 200, 300, 400)
        cache.put(p, file_size=500, mtime=42.0, fingerprint=fp)
        result = cache.get(p, file_size=500, mtime=42.0)
        assert result == fp
        assert cache.hits == 1

    def test_stale_mtime(self, cache_dir):
        """Changed mtime → cache miss."""
        from duplicates_detector.cache import AudioFingerprintCache

        cache = AudioFingerprintCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        fp = (100, 200, 300)
        cache.put(p, file_size=500, mtime=42.0, fingerprint=fp)
        result = cache.get(p, file_size=500, mtime=99.0)
        assert result is None
        assert cache.misses == 1

    def test_stale_size(self, cache_dir):
        """Changed file_size → cache miss."""
        from duplicates_detector.cache import AudioFingerprintCache

        cache = AudioFingerprintCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        fp = (100, 200, 300)
        cache.put(p, file_size=500, mtime=42.0, fingerprint=fp)
        result = cache.get(p, file_size=999, mtime=42.0)
        assert result is None
        assert cache.misses == 1

    def test_missing_path(self, cache_dir):
        """get() for unknown path → cache miss."""
        from duplicates_detector.cache import AudioFingerprintCache

        cache = AudioFingerprintCache(cache_dir=cache_dir)
        result = cache.get(Path("/videos/unknown.mp4"), file_size=500, mtime=42.0)
        assert result is None
        assert cache.misses == 1

    def test_save_load_persistence(self, cache_dir):
        """Fingerprints survive save/load cycle."""
        from duplicates_detector.cache import AudioFingerprintCache

        cache1 = AudioFingerprintCache(cache_dir=cache_dir)
        p = Path("/videos/test.mp4")
        fp = (10, 20, 30, 40, 50)
        cache1.put(p, file_size=500, mtime=42.0, fingerprint=fp)
        cache1.save()

        cache2 = AudioFingerprintCache(cache_dir=cache_dir)
        result = cache2.get(p, file_size=500, mtime=42.0)
        assert result == fp
        assert cache2.hits == 1

    def test_corrupt_file_degrades_gracefully(self, cache_dir):
        """Corrupt cache file → empty cache (no crash)."""
        from duplicates_detector.cache import _AUDIO_CACHE_FILENAME, AudioFingerprintCache

        (cache_dir / _AUDIO_CACHE_FILENAME).write_text("NOT VALID JSON {{{{")
        cache = AudioFingerprintCache(cache_dir=cache_dir)
        result = cache.get(Path("/videos/test.mp4"), file_size=500, mtime=42.0)
        assert result is None

    def test_wrong_version_discarded(self, cache_dir):
        """Cache with wrong version → empty (discarded)."""
        from duplicates_detector.cache import _AUDIO_CACHE_FILENAME, AudioFingerprintCache

        data = {"version": 9999, "fingerprints": {}}
        (cache_dir / _AUDIO_CACHE_FILENAME).write_text(json.dumps(data))
        cache = AudioFingerprintCache(cache_dir=cache_dir)
        result = cache.get(Path("/videos/test.mp4"), file_size=500, mtime=42.0)
        assert result is None
