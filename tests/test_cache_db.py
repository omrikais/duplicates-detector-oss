from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from duplicates_detector.cache_db import CacheDB


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for the SQLite cache."""
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def db(cache_dir: Path) -> Iterator[CacheDB]:
    """Create a CacheDB instance with cleanup."""
    instance = CacheDB(cache_dir)
    yield instance
    instance.close()


class TestCacheDBInit:
    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        """CacheDB creates cache_dir when it doesn't exist."""
        missing = tmp_path / "does" / "not" / "exist"
        db = CacheDB(missing)
        try:
            assert missing.exists()
            assert (missing / "cache.db").exists()
        finally:
            db.close()

    def test_wal_mode(self, cache_dir: Path) -> None:
        """Database is opened in WAL journal mode."""
        db = CacheDB(cache_dir)
        try:
            conn = sqlite3.connect(str(cache_dir / "cache.db"))
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
            assert mode == "wal"
        finally:
            db.close()

    def test_creates_all_tables(self, cache_dir: Path) -> None:
        """Schema creates all expected tables including clip_embeddings."""
        db = CacheDB(cache_dir)
        try:
            conn = sqlite3.connect(str(cache_dir / "cache.db"))
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            conn.close()
            assert tables >= {
                "metadata",
                "content_hashes",
                "audio_fingerprints",
                "scored_pairs",
                "pre_hashes",
                "sha256_hashes",
                "clip_embeddings",
            }
        finally:
            db.close()


class TestMetadataPutAndGet:
    def test_put_and_get_roundtrip(self, db: CacheDB, tmp_path: Path) -> None:
        """Stored metadata is returned on get when file_size and mtime match."""
        p = tmp_path / "video.mp4"
        p.touch()
        data = {"duration": 120.0, "width": 1920, "height": 1080, "codec": "h264"}

        db.put_metadata(p.resolve(), data, file_size=5000, mtime=1700000000.0)
        result = db.get_metadata(p.resolve(), file_size=5000, mtime=1700000000.0)

        assert result is not None
        assert result["duration"] == 120.0
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["codec"] == "h264"

    def test_put_replaces_existing(self, db: CacheDB, tmp_path: Path) -> None:
        """Second put for the same path replaces the previous entry."""
        p = tmp_path / "video.mp4"
        p.touch()

        db.put_metadata(p.resolve(), {"duration": 100.0}, file_size=5000, mtime=1.0)
        db.put_metadata(p.resolve(), {"duration": 200.0}, file_size=6000, mtime=2.0)

        result = db.get_metadata(p.resolve(), file_size=6000, mtime=2.0)
        assert result is not None
        assert result["duration"] == 200.0

    def test_miss_returns_none_for_absent_key(self, db: CacheDB, tmp_path: Path) -> None:
        """get_metadata returns None for a path never stored."""
        p = tmp_path / "nonexistent.mp4"
        result = db.get_metadata(p.resolve(), file_size=100, mtime=1.0)
        assert result is None


class TestMetadataValidation:
    def test_miss_on_changed_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        """Stale mtime causes a cache miss."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 120.0}, file_size=5000, mtime=100.0)

        result = db.get_metadata(p.resolve(), file_size=5000, mtime=999.0)
        assert result is None

    def test_miss_on_changed_size(self, db: CacheDB, tmp_path: Path) -> None:
        """Stale file_size causes a cache miss."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 120.0}, file_size=5000, mtime=100.0)

        result = db.get_metadata(p.resolve(), file_size=9999, mtime=100.0)
        assert result is None

    def test_miss_on_both_changed(self, db: CacheDB, tmp_path: Path) -> None:
        """Stale file_size AND mtime causes a cache miss."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 120.0}, file_size=5000, mtime=100.0)

        result = db.get_metadata(p.resolve(), file_size=9999, mtime=999.0)
        assert result is None


class TestStatsTracking:
    def test_stats_starts_zero(self, db: CacheDB) -> None:
        """Fresh CacheDB reports zero hits and misses for all tables."""
        s = db.stats()
        assert s["metadata_hits"] == 0
        assert s["metadata_misses"] == 0
        assert s["content_hits"] == 0
        assert s["content_misses"] == 0
        assert s["audio_hits"] == 0
        assert s["audio_misses"] == 0
        assert s["score_hits"] == 0
        assert s["score_misses"] == 0

    def test_stats_counts_hit(self, db: CacheDB, tmp_path: Path) -> None:
        """Successful get increments metadata hit counter."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 120.0}, file_size=5000, mtime=100.0)

        db.get_metadata(p.resolve(), file_size=5000, mtime=100.0)
        db.get_metadata(p.resolve(), file_size=5000, mtime=100.0)

        s = db.stats()
        assert s["metadata_hits"] == 2
        assert s["metadata_misses"] == 0

    def test_stats_counts_miss(self, db: CacheDB, tmp_path: Path) -> None:
        """Failed get increments metadata miss counter."""
        p = tmp_path / "nonexistent.mp4"

        db.get_metadata(p.resolve(), file_size=100, mtime=1.0)
        db.get_metadata(p.resolve(), file_size=100, mtime=1.0)
        db.get_metadata(p.resolve(), file_size=100, mtime=1.0)

        s = db.stats()
        assert s["metadata_hits"] == 0
        assert s["metadata_misses"] == 3

    def test_stats_counts_miss_does_not_affect_other_tables(self, db: CacheDB, tmp_path: Path) -> None:
        """Metadata misses do not increment content/audio/score counters."""
        p = tmp_path / "nonexistent.mp4"
        db.get_metadata(p.resolve(), file_size=100, mtime=1.0)

        s = db.stats()
        assert s["metadata_misses"] == 1
        assert s["content_hits"] == 0
        assert s["content_misses"] == 0
        assert s["audio_hits"] == 0
        assert s["audio_misses"] == 0
        assert s["score_hits"] == 0
        assert s["score_misses"] == 0

    def test_stats_mixed(self, db: CacheDB, tmp_path: Path) -> None:
        """Stats track both hits and misses correctly."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 120.0}, file_size=5000, mtime=100.0)

        db.get_metadata(p.resolve(), file_size=5000, mtime=100.0)  # hit
        db.get_metadata(p.resolve(), file_size=9999, mtime=100.0)  # miss (wrong size)
        db.get_metadata(p.resolve(), file_size=5000, mtime=100.0)  # hit

        s = db.stats()
        assert s["metadata_hits"] == 2
        assert s["metadata_misses"] == 1

    def test_stats_thread_safe(self, db: CacheDB, tmp_path: Path) -> None:
        """Hit/miss counters are thread-safe under concurrent access."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 120.0}, file_size=5000, mtime=100.0)

        errors: list[Exception] = []

        def worker_hit() -> None:
            try:
                for _ in range(50):
                    db.get_metadata(p.resolve(), file_size=5000, mtime=100.0)
            except Exception as exc:
                errors.append(exc)

        def worker_miss() -> None:
            try:
                for _ in range(50):
                    db.get_metadata(p.resolve(), file_size=9999, mtime=100.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker_hit) for _ in range(4)]
        threads += [threading.Thread(target=worker_miss) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        s = db.stats()
        assert s["metadata_hits"] == 200  # 4 threads * 50 hits
        assert s["metadata_misses"] == 200  # 4 threads * 50 misses


class TestCorruptionRecovery:
    def test_corrupt_db_recreated(self, cache_dir: Path) -> None:
        """Corrupt database file is renamed and a fresh DB is created."""
        db_path = cache_dir / "cache.db"
        db_path.write_text("this is not a valid sqlite database")

        db = CacheDB(cache_dir)
        try:
            # Should have a working database now
            p = Path("/tmp/test.mp4")
            db.put_metadata(p, {"duration": 1.0}, file_size=100, mtime=1.0)
            result = db.get_metadata(p, file_size=100, mtime=1.0)
            assert result is not None

            # Corrupt file should have been renamed
            corrupt_files = list(cache_dir.glob("cache.db.corrupt.*"))
            assert len(corrupt_files) == 1
        finally:
            db.close()

    def test_corrupt_db_zero_bytes(self, cache_dir: Path) -> None:
        """Zero-byte database file is handled as corruption."""
        db_path = cache_dir / "cache.db"
        db_path.touch()  # 0 bytes

        db = CacheDB(cache_dir)
        try:
            p = Path("/tmp/test.mp4")
            db.put_metadata(p, {"duration": 1.0}, file_size=100, mtime=1.0)
            result = db.get_metadata(p, file_size=100, mtime=1.0)
            assert result is not None
        finally:
            db.close()


class TestPrune:
    def test_prune_removes_stale_entries(self, db: CacheDB, tmp_path: Path) -> None:
        """prune() removes metadata entries whose paths are not in the active set."""
        p1 = tmp_path / "keep.mp4"
        p2 = tmp_path / "remove.mp4"
        p1.touch()
        p2.touch()

        db.put_metadata(p1.resolve(), {"duration": 1.0}, file_size=100, mtime=1.0)
        db.put_metadata(p2.resolve(), {"duration": 2.0}, file_size=200, mtime=2.0)

        deleted = db.prune({p1.resolve()})

        assert deleted == 1
        assert db.get_metadata(p1.resolve(), file_size=100, mtime=1.0) is not None
        assert db.get_metadata(p2.resolve(), file_size=200, mtime=2.0) is None

    def test_prune_with_empty_active_set(self, db: CacheDB, tmp_path: Path) -> None:
        """prune() with empty set removes all entries."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 1.0}, file_size=100, mtime=1.0)

        deleted = db.prune(set())

        assert deleted == 1
        assert db.get_metadata(p.resolve(), file_size=100, mtime=1.0) is None

    def test_prune_with_all_active(self, db: CacheDB, tmp_path: Path) -> None:
        """prune() with all paths active removes nothing."""
        p1 = tmp_path / "a.mp4"
        p2 = tmp_path / "b.mp4"
        p1.touch()
        p2.touch()

        db.put_metadata(p1.resolve(), {"duration": 1.0}, file_size=100, mtime=1.0)
        db.put_metadata(p2.resolve(), {"duration": 2.0}, file_size=200, mtime=2.0)

        deleted = db.prune({p1.resolve(), p2.resolve()})

        assert deleted == 0
        assert db.get_metadata(p1.resolve(), file_size=100, mtime=1.0) is not None
        assert db.get_metadata(p2.resolve(), file_size=200, mtime=2.0) is not None


class TestPrunePathResolution:
    def test_prune_resolves_paths(self, tmp_path: Path) -> None:
        """prune() must resolve paths to match what put_* methods stored."""
        cache = CacheDB(tmp_path / "cachedata")
        sub = tmp_path / "sub"
        sub.mkdir()
        test_file = sub / "video.mp4"
        test_file.write_bytes(b"x")
        cache.put_metadata(test_file, {"duration": 10}, file_size=1, mtime=1.0)

        # Use a path with ".." that resolves to the same file but has a different string
        unresolved = tmp_path / "sub" / ".." / "sub" / "video.mp4"
        assert str(unresolved) != str(unresolved.resolve())  # precondition
        deleted = cache.prune({unresolved})
        assert deleted == 0  # entry should be KEPT, not deleted

    def test_prune_removes_absent_paths(self, tmp_path: Path) -> None:
        """prune() removes entries not in active set."""
        cache = CacheDB(tmp_path / "cachedata")
        test_file = tmp_path / "video.mp4"
        test_file.write_bytes(b"x")
        cache.put_metadata(test_file, {"duration": 10}, file_size=1, mtime=1.0)

        deleted = cache.prune(set())  # empty active set
        assert deleted == 1


class TestClose:
    def test_close_idempotent(self, cache_dir: Path) -> None:
        """close() can be called multiple times without error."""
        db = CacheDB(cache_dir)
        db.close()
        db.close()  # Should not raise

    def test_thread_local_connections(self, cache_dir: Path) -> None:
        """Each thread gets its own connection, all closed by close()."""
        db = CacheDB(cache_dir)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                p = Path(f"/tmp/thread_{threading.current_thread().name}.mp4")
                db.put_metadata(p, {"duration": 1.0}, file_size=100, mtime=1.0)
                db.get_metadata(p, file_size=100, mtime=1.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        db.close()


class TestContentHashCache:
    def test_put_and_get(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        hashes = (123456789, 987654321, 111111111, 444444444)
        db.put_content_hash(p, file_size=4, mtime=1000.0, hashes=hashes, rotation_invariant=False)
        result = db.get_content_hash(p, file_size=4, mtime=1000.0, rotation_invariant=False)
        assert result == hashes

    def test_put_and_get_rotation_invariant(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        hashes = (123456789, 987654321, 111111111, 444444444)
        db.put_content_hash(p, file_size=4, mtime=1000.0, hashes=hashes, rotation_invariant=True)
        result = db.get_content_hash(p, file_size=4, mtime=1000.0, rotation_invariant=True)
        assert result == hashes

    def test_miss_on_different_rotation_invariant(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_content_hash(p, file_size=4, mtime=1000.0, hashes=(1, 2, 3, 4), rotation_invariant=False)
        result = db.get_content_hash(p, file_size=4, mtime=1000.0, rotation_invariant=True)
        assert result is None

    def test_miss_on_changed_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_content_hash(p, file_size=4, mtime=1000.0, hashes=(1, 2, 3, 4), rotation_invariant=False)
        result = db.get_content_hash(p, file_size=4, mtime=9999.0, rotation_invariant=False)
        assert result is None


class TestAudioFingerprintCache:
    def test_put_and_get(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "song.mp3"
        p.write_bytes(b"fake")
        fp = (111, 222, 333, 444)
        db.put_audio_fingerprint(p, file_size=4, mtime=1000.0, fingerprint=fp)
        result = db.get_audio_fingerprint(p, file_size=4, mtime=1000.0)
        assert result == fp

    def test_miss_on_changed_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "song.mp3"
        p.write_bytes(b"fake")
        db.put_audio_fingerprint(p, file_size=4, mtime=1000.0, fingerprint=(1,))
        result = db.get_audio_fingerprint(p, file_size=4, mtime=9999.0)
        assert result is None


class TestDataIntegrity:
    def test_json_data_preserves_complex_types(self, db: CacheDB, tmp_path: Path) -> None:
        """Metadata dict with None values, nested data survives roundtrip."""
        p = tmp_path / "video.mp4"
        p.touch()
        data = {
            "duration": 120.5,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
            "bitrate": None,
            "framerate": 23.976,
            "audio_channels": 2,
            "exif_datetime": 1700000000.0,
            "exif_camera": "canon eos r5",
            "exif_lens": None,
            "exif_gps_lat": 37.7749,
            "exif_gps_lon": -122.4194,
        }

        db.put_metadata(p.resolve(), data, file_size=5000, mtime=100.0)
        result = db.get_metadata(p.resolve(), file_size=5000, mtime=100.0)

        assert result == data

    def test_path_stored_as_string(self, db: CacheDB, tmp_path: Path) -> None:
        """Paths are stored as resolved strings — relative and absolute resolve the same."""
        p = tmp_path / "video.mp4"
        p.touch()
        db.put_metadata(p.resolve(), {"duration": 1.0}, file_size=100, mtime=1.0)

        # Query with resolved path
        result = db.get_metadata(p.resolve(), file_size=100, mtime=1.0)
        assert result is not None


class TestScoringCache:
    @staticmethod
    def _config_hash() -> str:
        config = {"filename": 50, "duration": 30, "resolution": 10, "filesize": 10, "content": False, "audio": False}
        return hashlib.md5(json.dumps(config, sort_keys=True).encode()).hexdigest()

    def test_put_and_get(self, db: CacheDB, tmp_path: Path) -> None:
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        detail = {"filename": [0.85, 50.0], "duration": [1.0, 30.0]}
        db.put_scored_pair(a, b, mtime_a=1000.0, mtime_b=2000.0, config_hash=ch, score=72.5, detail=detail)
        result = db.get_scored_pair(a, b, config_hash=ch, mtime_a=1000.0, mtime_b=2000.0)
        assert result is not None
        assert result["score"] == 72.5
        assert result["detail"]["filename"] == [0.85, 50.0]

    def test_canonical_order(self, db: CacheDB, tmp_path: Path) -> None:
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        db.put_scored_pair(b, a, mtime_a=2000.0, mtime_b=1000.0, config_hash=ch, score=72.5, detail={})
        # Lookup with reversed order should still find it
        result = db.get_scored_pair(a, b, config_hash=ch, mtime_a=1000.0, mtime_b=2000.0)
        assert result is not None

    def test_miss_on_stale_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        db.put_scored_pair(a, b, mtime_a=1000.0, mtime_b=2000.0, config_hash=ch, score=72.5, detail={})
        result = db.get_scored_pair(a, b, config_hash=ch, mtime_a=9999.0, mtime_b=2000.0)
        assert result is None

    def test_bulk_get(self, db: CacheDB, tmp_path: Path) -> None:
        paths = []
        for i in range(5):
            p = tmp_path / f"file{i}.mp4"
            p.write_bytes(f"data{i}".encode())
            paths.append(p)
        ch = self._config_hash()
        mtimes = {p: float(i * 1000) for i, p in enumerate(paths)}
        # Store some pairs
        db.put_scored_pair(paths[0], paths[1], mtime_a=0.0, mtime_b=1000.0, config_hash=ch, score=80.0, detail={})
        db.put_scored_pair(paths[2], paths[3], mtime_a=2000.0, mtime_b=3000.0, config_hash=ch, score=60.0, detail={})
        results = db.get_scored_pairs_bulk(set(paths), config_hash=ch, mtimes=mtimes)
        assert len(results) == 2

    def test_stats_hit(self, db: CacheDB, tmp_path: Path) -> None:
        """Successful get_scored_pair increments score_hits."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        db.put_scored_pair(a, b, mtime_a=1000.0, mtime_b=2000.0, config_hash=ch, score=72.5, detail={})
        db.get_scored_pair(a, b, config_hash=ch, mtime_a=1000.0, mtime_b=2000.0)
        s = db.stats()
        assert s["score_hits"] == 1
        assert s["score_misses"] == 0

    def test_stats_miss(self, db: CacheDB, tmp_path: Path) -> None:
        """Failed get_scored_pair increments score_misses."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        db.get_scored_pair(a, b, config_hash=ch, mtime_a=1000.0, mtime_b=2000.0)
        s = db.stats()
        assert s["score_hits"] == 0
        assert s["score_misses"] == 1

    def test_replace_on_same_pair_and_config(self, db: CacheDB, tmp_path: Path) -> None:
        """Second put for the same (pair, config_hash) replaces the previous score."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        db.put_scored_pair(a, b, mtime_a=1000.0, mtime_b=2000.0, config_hash=ch, score=50.0, detail={})
        db.put_scored_pair(a, b, mtime_a=1000.0, mtime_b=2000.0, config_hash=ch, score=90.0, detail={"new": True})
        result = db.get_scored_pair(a, b, config_hash=ch, mtime_a=1000.0, mtime_b=2000.0)
        assert result is not None
        assert result["score"] == 90.0
        assert result["detail"] == {"new": True}

    def test_miss_on_different_config_hash(self, db: CacheDB, tmp_path: Path) -> None:
        """Different config_hash for the same pair is a miss."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"fake_a")
        b.write_bytes(b"fake_b")
        ch = self._config_hash()
        db.put_scored_pair(a, b, mtime_a=1000.0, mtime_b=2000.0, config_hash=ch, score=72.5, detail={})
        result = db.get_scored_pair(a, b, config_hash="different_hash", mtime_a=1000.0, mtime_b=2000.0)
        assert result is None

    def test_put_scored_pairs_bulk(self, tmp_path: Path) -> None:
        """put_scored_pairs_bulk stores multiple pairs retrievable via get_scored_pair."""
        cache = CacheDB(tmp_path / "bulk_cache")
        try:
            rows = [
                ("/a.mp4", "/b.mp4", 1.0, 2.0, "cfg1", 85.0, '{"filename":[0.8,50]}'),
                ("/c.mp4", "/d.mp4", 3.0, 4.0, "cfg1", 72.0, '{"filename":[0.7,50]}'),
            ]
            cache.put_scored_pairs_bulk(rows)
            r = cache.get_scored_pair(Path("/a.mp4"), Path("/b.mp4"), config_hash="cfg1", mtime_a=1.0, mtime_b=2.0)
            assert r is not None and r["score"] == 85.0
            r2 = cache.get_scored_pair(Path("/c.mp4"), Path("/d.mp4"), config_hash="cfg1", mtime_a=3.0, mtime_b=4.0)
            assert r2 is not None and r2["score"] == 72.0
        finally:
            cache.close()

    def test_put_scored_pairs_bulk_empty(self, db: CacheDB) -> None:
        """put_scored_pairs_bulk with empty list is a no-op."""
        db.put_scored_pairs_bulk([])
        # Should not raise, and stats remain unchanged
        s = db.stats()
        assert s["score_hits"] == 0
        assert s["score_misses"] == 0

    def test_put_scored_pairs_bulk_replaces_existing(self, tmp_path: Path) -> None:
        """put_scored_pairs_bulk replaces existing entries (INSERT OR REPLACE)."""
        cache = CacheDB(tmp_path / "replace_cache")
        try:
            rows = [("/a.mp4", "/b.mp4", 1.0, 2.0, "cfg1", 50.0, "{}")]
            cache.put_scored_pairs_bulk(rows)
            # Replace with new score
            rows2 = [("/a.mp4", "/b.mp4", 1.0, 2.0, "cfg1", 99.0, '{"new":true}')]
            cache.put_scored_pairs_bulk(rows2)
            r = cache.get_scored_pair(Path("/a.mp4"), Path("/b.mp4"), config_hash="cfg1", mtime_a=1.0, mtime_b=2.0)
            assert r is not None and r["score"] == 99.0
        finally:
            cache.close()

    def test_put_scored_pairs_bulk_tracks_misses(self, tmp_path: Path) -> None:
        """put_scored_pairs_bulk increments score_misses for each stored row."""
        cache = CacheDB(tmp_path / "miss_cache")
        try:
            rows = [
                ("/a.mp4", "/b.mp4", 1.0, 2.0, "cfg1", 85.0, '{"filename":[0.8,50]}'),
                ("/c.mp4", "/d.mp4", 3.0, 4.0, "cfg1", 72.0, '{"filename":[0.7,50]}'),
                ("/e.mp4", "/f.mp4", 5.0, 6.0, "cfg1", 60.0, '{"filename":[0.6,50]}'),
            ]
            cache.put_scored_pairs_bulk(rows)

            s = cache.stats()
            assert s["score_misses"] == 3
            assert s["score_hits"] == 0

            # Now retrieve those pairs via bulk get — should register as hits
            all_paths = {Path("/a.mp4"), Path("/b.mp4"), Path("/c.mp4"), Path("/d.mp4"), Path("/e.mp4"), Path("/f.mp4")}
            mtimes = {
                Path("/a.mp4"): 1.0,
                Path("/b.mp4"): 2.0,
                Path("/c.mp4"): 3.0,
                Path("/d.mp4"): 4.0,
                Path("/e.mp4"): 5.0,
                Path("/f.mp4"): 6.0,
            }
            results = cache.get_scored_pairs_bulk(all_paths, config_hash="cfg1", mtimes=mtimes)
            assert len(results) == 3

            s2 = cache.stats()
            assert s2["score_hits"] == 3
            assert s2["score_misses"] == 3
        finally:
            cache.close()


class TestPreHashCache:
    def test_put_and_get(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_pre_hash(p, file_size=4, mtime=1000.0, pre_hash="abc123")
        result = db.get_pre_hash(p, file_size=4, mtime=1000.0)
        assert result == "abc123"

    def test_miss_on_changed_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_pre_hash(p, file_size=4, mtime=1000.0, pre_hash="abc123")
        result = db.get_pre_hash(p, file_size=4, mtime=9999.0)
        assert result is None

    def test_miss_on_changed_file_size(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_pre_hash(p, file_size=4, mtime=1000.0, pre_hash="abc123")
        result = db.get_pre_hash(p, file_size=999, mtime=1000.0)
        assert result is None

    def test_miss_when_not_stored(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        result = db.get_pre_hash(p, file_size=4, mtime=1000.0)
        assert result is None

    def test_replace_on_same_path(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_pre_hash(p, file_size=4, mtime=1000.0, pre_hash="old")
        db.put_pre_hash(p, file_size=4, mtime=2000.0, pre_hash="new")
        assert db.get_pre_hash(p, file_size=4, mtime=2000.0) == "new"
        assert db.get_pre_hash(p, file_size=4, mtime=1000.0) is None

    def test_stats_tracking(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.get_pre_hash(p, file_size=4, mtime=1000.0)  # miss
        db.put_pre_hash(p, file_size=4, mtime=1000.0, pre_hash="abc")
        db.get_pre_hash(p, file_size=4, mtime=1000.0)  # hit
        stats = db.stats()
        assert stats["pre_hash_hits"] == 1
        assert stats["pre_hash_misses"] == 1


class TestPreHashPruning:
    def test_prune_removes_inactive_pre_hashes(self, db: CacheDB, tmp_path: Path) -> None:
        p1 = tmp_path / "keep.mp4"
        p2 = tmp_path / "remove.mp4"
        p1.write_bytes(b"keep")
        p2.write_bytes(b"remove")
        db.put_pre_hash(p1, file_size=4, mtime=1000.0, pre_hash="aaa")
        db.put_pre_hash(p2, file_size=6, mtime=1000.0, pre_hash="bbb")
        db.prune({p1})
        assert db.get_pre_hash(p1, file_size=4, mtime=1000.0) == "aaa"
        initial_misses = db.stats()["pre_hash_misses"]
        assert db.get_pre_hash(p2, file_size=6, mtime=1000.0) is None
        assert db.stats()["pre_hash_misses"] == initial_misses + 1


class TestSHA256Cache:
    def test_put_and_get_roundtrip(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_sha256(p, file_size=4, mtime=1000.0, sha256="deadbeef" * 8)
        result = db.get_sha256(p, file_size=4, mtime=1000.0)
        assert result == "deadbeef" * 8

    def test_miss_on_wrong_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_sha256(p, file_size=4, mtime=1000.0, sha256="deadbeef" * 8)
        result = db.get_sha256(p, file_size=4, mtime=9999.0)
        assert result is None

    def test_miss_on_wrong_size(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.put_sha256(p, file_size=4, mtime=1000.0, sha256="deadbeef" * 8)
        result = db.get_sha256(p, file_size=999, mtime=1000.0)
        assert result is None

    def test_stats_tracking(self, db: CacheDB, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")
        db.get_sha256(p, file_size=4, mtime=1000.0)  # miss
        db.put_sha256(p, file_size=4, mtime=1000.0, sha256="abc")
        db.get_sha256(p, file_size=4, mtime=1000.0)  # hit
        stats = db.stats()
        assert stats["sha256_hits"] == 1
        assert stats["sha256_misses"] == 1


class TestSHA256Pruning:
    def test_prune_removes_inactive_sha256(self, db: CacheDB, tmp_path: Path) -> None:
        p1 = tmp_path / "keep.mp4"
        p2 = tmp_path / "remove.mp4"
        p1.write_bytes(b"keep")
        p2.write_bytes(b"remove")
        db.put_sha256(p1, file_size=4, mtime=1000.0, sha256="aaa")
        db.put_sha256(p2, file_size=6, mtime=1000.0, sha256="bbb")
        db.prune({p1})
        assert db.get_sha256(p1, file_size=4, mtime=1000.0) == "aaa"
        initial_misses = db.stats()["sha256_misses"]
        assert db.get_sha256(p2, file_size=6, mtime=1000.0) is None
        assert db.stats()["sha256_misses"] == initial_misses + 1


class TestClipEmbeddingCache:
    def test_roundtrip_float_tuple(self, db: CacheDB, tmp_path: Path) -> None:
        """Stored CLIP embedding is returned as a tuple of floats on cache hit."""
        p = tmp_path / "image.jpg"
        p.write_bytes(b"fake image data")
        emb = tuple(float(i) * 0.01 for i in range(512))
        db.put_clip_embedding(p, file_size=15, mtime=1000.0, embedding=emb)
        result = db.get_clip_embedding(p, file_size=15, mtime=1000.0)
        assert result is not None
        assert len(result) == 512
        # Float32 roundtrip may lose precision; check close enough
        import numpy as np

        np.testing.assert_allclose(result, emb, rtol=1e-6)

    def test_miss_on_wrong_mtime(self, db: CacheDB, tmp_path: Path) -> None:
        """Changed mtime causes a cache miss for CLIP embeddings."""
        p = tmp_path / "image.jpg"
        p.write_bytes(b"fake image data")
        emb = tuple(float(i) for i in range(512))
        db.put_clip_embedding(p, file_size=15, mtime=1000.0, embedding=emb)
        result = db.get_clip_embedding(p, file_size=15, mtime=9999.0)
        assert result is None

    def test_miss_on_wrong_file_size(self, db: CacheDB, tmp_path: Path) -> None:
        """Changed file_size causes a cache miss for CLIP embeddings."""
        p = tmp_path / "image.jpg"
        p.write_bytes(b"fake image data")
        emb = tuple(float(i) for i in range(512))
        db.put_clip_embedding(p, file_size=15, mtime=1000.0, embedding=emb)
        result = db.get_clip_embedding(p, file_size=9999, mtime=1000.0)
        assert result is None

    def test_stats_tracking(self, db: CacheDB, tmp_path: Path) -> None:
        """CLIP hit/miss stats are tracked correctly."""
        p = tmp_path / "image.jpg"
        p.write_bytes(b"fake image data")
        emb = tuple(float(i) for i in range(512))
        db.put_clip_embedding(p, file_size=15, mtime=1000.0, embedding=emb)

        db.get_clip_embedding(p, file_size=15, mtime=1000.0)  # hit
        db.get_clip_embedding(p, file_size=15, mtime=9999.0)  # miss

        s = db.stats()
        assert s["clip_hits"] == 1
        assert s["clip_misses"] == 1


class TestClipEmbeddingPruning:
    def test_prune_removes_inactive_clip(self, db: CacheDB, tmp_path: Path) -> None:
        """Prune removes clip_embeddings for files not in the active set."""
        p1 = tmp_path / "keep.jpg"
        p2 = tmp_path / "remove.jpg"
        p1.write_bytes(b"keep")
        p2.write_bytes(b"remove")
        emb = tuple(float(i) for i in range(512))
        db.put_clip_embedding(p1, file_size=4, mtime=1000.0, embedding=emb)
        db.put_clip_embedding(p2, file_size=6, mtime=1000.0, embedding=emb)
        db.prune({p1})
        assert db.get_clip_embedding(p1, file_size=4, mtime=1000.0) is not None
        initial_misses = db.stats()["clip_misses"]
        assert db.get_clip_embedding(p2, file_size=6, mtime=1000.0) is None
        assert db.stats()["clip_misses"] == initial_misses + 1


class TestMigration:
    def test_migrate_metadata_json(self, tmp_path: Path) -> None:
        # Write a v2 JSON metadata cache
        cache_file = tmp_path / "metadata.json"
        cache_data = {
            "version": 2,
            "metadata": {
                "/fake/video.mp4": {
                    "file_size": 1000,
                    "mtime": 12345.0,
                    "duration": 120.0,
                    "width": 1920,
                    "height": 1080,
                }
            },
        }
        cache_file.write_text(json.dumps(cache_data))
        db = CacheDB(tmp_path)
        try:
            result = db.get_metadata(Path("/fake/video.mp4"), file_size=1000, mtime=12345.0)
            assert result is not None
            assert result["duration"] == 120.0
            # JSON file should be renamed to .bak
            assert not cache_file.exists()
            assert (tmp_path / "metadata.json.bak").exists()
        finally:
            db.close()

    def test_migrate_missing_json_no_error(self, tmp_path: Path) -> None:
        """No JSON files at all should not cause any errors."""
        db = CacheDB(tmp_path)
        try:
            assert db.stats()["metadata_hits"] == 0
        finally:
            db.close()

    def test_migrate_invalid_json_no_error(self, tmp_path: Path) -> None:
        """Corrupt JSON file should not block startup."""
        cache_file = tmp_path / "metadata.json"
        cache_file.write_text("this is not valid json")
        db = CacheDB(tmp_path)
        try:
            # Should work fine despite bad JSON
            p = Path("/tmp/test.mp4")
            db.put_metadata(p, {"duration": 1.0}, file_size=100, mtime=1.0)
            result = db.get_metadata(p, file_size=100, mtime=1.0)
            assert result is not None
        finally:
            db.close()

    def test_migrate_wrong_version_skipped(self, tmp_path: Path) -> None:
        """JSON cache with version != 2 is skipped (not migrated)."""
        cache_file = tmp_path / "metadata.json"
        cache_data = {"version": 99, "entries": {"/fake/video.mp4": {"file_size": 1000, "mtime": 12345.0}}}
        cache_file.write_text(json.dumps(cache_data))
        db = CacheDB(tmp_path)
        try:
            result = db.get_metadata(Path("/fake/video.mp4"), file_size=1000, mtime=12345.0)
            assert result is None
            # File should still exist since we didn't migrate
            assert cache_file.exists()
        finally:
            db.close()

    def test_migrate_content_hashes_json_renames(self, tmp_path: Path) -> None:
        """content-hashes.json v1 is renamed to .bak (legacy format not migrated)."""
        cache_file = tmp_path / "content-hashes.json"
        cache_data = {
            "version": 1,
            "hashes": {
                "/fake/video.mp4": {
                    "file_size": 1000,
                    "mtime": 12345.0,
                    "algorithm": "phash",
                    "hash_size": 8,
                    "rotation_invariant": False,
                    "strategy": "interval",
                    "scene_threshold": 0.3,
                    "interval": 2.0,
                    "hash": [123456, 789012],
                }
            },
        }
        cache_file.write_text(json.dumps(cache_data))
        db = CacheDB(tmp_path)
        try:
            # Legacy hashes are not migrated (incompatible format), just renamed
            assert not cache_file.exists()
            assert (tmp_path / "content-hashes.json.bak").exists()
        finally:
            db.close()

    def test_migrate_audio_fingerprints_json(self, tmp_path: Path) -> None:
        """audio-fingerprints.json v1 is migrated to SQLite."""
        cache_file = tmp_path / "audio-fingerprints.json"
        cache_data = {
            "version": 1,
            "fingerprints": {
                "/fake/song.mp3": {
                    "file_size": 5000,
                    "mtime": 99999.0,
                    "fingerprint": [111, 222, 333],
                }
            },
        }
        cache_file.write_text(json.dumps(cache_data))
        db = CacheDB(tmp_path)
        try:
            result = db.get_audio_fingerprint(
                Path("/fake/song.mp3"),
                file_size=5000,
                mtime=99999.0,
            )
            assert result is not None
            assert result == (111, 222, 333)
            assert not cache_file.exists()
            assert (tmp_path / "audio-fingerprints.json.bak").exists()
        finally:
            db.close()

    def test_migrate_v2_adds_pre_hashes_table(self, tmp_path: Path) -> None:
        """Existing v2 database without pre_hashes gets the table via additive migration."""
        cache_dir = tmp_path / "migrate_pre"
        cache_dir.mkdir()
        db_path = cache_dir / "cache.db"

        # Create a v2 database with only the original 4 tables (no pre_hashes)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """\
            CREATE TABLE metadata (
                path TEXT PRIMARY KEY, file_size INTEGER NOT NULL,
                mtime REAL NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE content_hashes (
                path TEXT PRIMARY KEY, file_size INTEGER NOT NULL,
                mtime REAL NOT NULL, rotation_invariant INTEGER NOT NULL,
                hashes TEXT NOT NULL
            );
            CREATE TABLE audio_fingerprints (
                path TEXT PRIMARY KEY, file_size INTEGER NOT NULL,
                mtime REAL NOT NULL, fingerprint TEXT NOT NULL
            );
            CREATE TABLE scored_pairs (
                path_a TEXT NOT NULL, path_b TEXT NOT NULL,
                mtime_a REAL NOT NULL, mtime_b REAL NOT NULL,
                config_hash TEXT NOT NULL, score REAL NOT NULL,
                detail TEXT NOT NULL,
                PRIMARY KEY (path_a, path_b, config_hash)
            );
            """
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()

        # Verify pre_hashes does NOT exist yet
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "pre_hashes" not in tables
        conn.close()

        # Instantiate CacheDB — should run additive migration
        db = CacheDB(cache_dir)
        try:
            # Verify pre_hashes table now exists
            raw = sqlite3.connect(str(db_path))
            tables = {
                row[0]
                for row in raw.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            raw.close()
            assert "pre_hashes" in tables
            assert "sha256_hashes" in tables

            # Verify operations work on the migrated tables
            p = tmp_path / "video.mp4"
            p.write_bytes(b"fake")
            db.put_pre_hash(p, file_size=4, mtime=1000.0, pre_hash="migrated_hash")
            result = db.get_pre_hash(p, file_size=4, mtime=1000.0)
            assert result == "migrated_hash"

            db.put_sha256(p, file_size=4, mtime=1000.0, sha256="migrated_sha256")
            result = db.get_sha256(p, file_size=4, mtime=1000.0)
            assert result == "migrated_sha256"
        finally:
            db.close()
