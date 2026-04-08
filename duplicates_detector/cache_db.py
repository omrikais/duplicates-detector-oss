from __future__ import annotations

import atexit
import json
import os
import sqlite3
import threading
import time
import logging
import warnings
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2

_CREATE_TABLES_SQL = """\
CREATE TABLE IF NOT EXISTS metadata (
    path       TEXT PRIMARY KEY,
    file_size  INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    data       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_hashes (
    path                TEXT PRIMARY KEY,
    file_size           INTEGER NOT NULL,
    mtime               REAL NOT NULL,
    rotation_invariant  INTEGER NOT NULL,
    hashes              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_fingerprints (
    path         TEXT PRIMARY KEY,
    file_size    INTEGER NOT NULL,
    mtime        REAL NOT NULL,
    fingerprint  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scored_pairs (
    path_a       TEXT NOT NULL,
    path_b       TEXT NOT NULL,
    mtime_a      REAL NOT NULL,
    mtime_b      REAL NOT NULL,
    config_hash  TEXT NOT NULL,
    score        REAL NOT NULL,
    detail       TEXT NOT NULL,
    PRIMARY KEY (path_a, path_b, config_hash)
);

CREATE INDEX IF NOT EXISTS idx_scored_pairs_paths ON scored_pairs (path_a, path_b);

CREATE TABLE IF NOT EXISTS pre_hashes (
    path       TEXT PRIMARY KEY,
    file_size  INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    pre_hash   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sha256_hashes (
    path       TEXT PRIMARY KEY,
    file_size  INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    sha256     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_embeddings (
    path       TEXT PRIMARY KEY,
    file_size  INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    embedding  BLOB NOT NULL
);
"""


class CacheDB:
    """SQLite-backed unified cache for all pipeline data.

    Covers metadata, content hashes, audio fingerprints, scored pairs, pre-hashes, SHA-256, and CLIP embeddings.

    Thread-safe: each thread gets its own connection via ``threading.local()``.
    Corruption is handled gracefully by renaming the broken file and starting fresh.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._db_path = cache_dir / "cache.db"
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._stats: dict[str, int] = {
            "metadata_hits": 0,
            "metadata_misses": 0,
            "content_hits": 0,
            "content_misses": 0,
            "audio_hits": 0,
            "audio_misses": 0,
            "score_hits": 0,
            "score_misses": 0,
            "pre_hash_hits": 0,
            "pre_hash_misses": 0,
            "sha256_hits": 0,
            "sha256_misses": 0,
            "clip_hits": 0,
            "clip_misses": 0,
        }
        self._stats_lock = threading.Lock()
        self._write_lock = threading.Lock()

        cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_json_caches()
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Return the per-thread SQLite connection, creating it lazily.

        ``PRAGMA synchronous = NORMAL`` skips per-commit fsyncs in WAL mode
        (fsyncs only at checkpoint), which is safe for a cache — at worst
        the last few writes are lost on power failure and re-extracted on
        next run.
        """
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
            with self._connections_lock:
                self._connections.append(conn)
        return conn

    def _init_db(self) -> None:
        """Verify schema version and create tables if needed.

        If the database file exists but is corrupt, ``_recreate_db()``
        handles recovery.
        """
        try:
            conn = self._conn()
            # Check if the schema_version user_version pragma matches
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                # Fresh database — create tables and set version
                self._create_tables(conn)
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                conn.commit()
            elif version == _SCHEMA_VERSION:
                # Additive migration: create pre_hashes table if it doesn't exist yet
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pre_hashes "
                    "(path TEXT PRIMARY KEY, file_size INTEGER NOT NULL, "
                    "mtime REAL NOT NULL, pre_hash TEXT NOT NULL)"
                )
                # Additive migration: create sha256_hashes table if it doesn't exist yet
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS sha256_hashes "
                    "(path TEXT PRIMARY KEY, file_size INTEGER NOT NULL, "
                    "mtime REAL NOT NULL, sha256 TEXT NOT NULL)"
                )
                # Additive migration: create clip_embeddings table if it doesn't exist yet
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS clip_embeddings "
                    "(path TEXT PRIMARY KEY, file_size INTEGER NOT NULL, "
                    "mtime REAL NOT NULL, embedding BLOB NOT NULL)"
                )
                conn.commit()
            elif version != _SCHEMA_VERSION:
                # Schema version mismatch — recreate
                conn.close()
                self._local.conn = None
                with self._connections_lock:
                    try:
                        self._connections.remove(conn)
                    except ValueError:
                        pass
                self._recreate_db()
        except sqlite3.DatabaseError:
            # Corrupt or unreadable — recreate
            # Clean up the broken connection from thread-local state
            broken_conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
            if broken_conn is not None:
                try:
                    broken_conn.close()
                except Exception:
                    pass
                self._local.conn = None
                with self._connections_lock:
                    try:
                        self._connections.remove(broken_conn)
                    except ValueError:
                        pass
            self._recreate_db()

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """Create all tables (idempotent via IF NOT EXISTS)."""
        conn.executescript(_CREATE_TABLES_SQL)

    def _recreate_db(self) -> None:
        """Handle corruption: rename the broken file and create a fresh database."""
        if self._db_path.exists():
            timestamp = int(time.time())
            corrupt_path = self._db_path.with_suffix(f".db.corrupt.{timestamp}")
            try:
                os.replace(str(self._db_path), str(corrupt_path))
            except OSError as exc:
                warnings.warn(
                    f"Cannot rename corrupt cache database: {exc}",
                    stacklevel=3,
                )
            # Also clean up WAL/SHM files if present
            for suffix in (".db-wal", ".db-shm"):
                sidecar = self._cache_dir / f"cache{suffix}"
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except OSError:
                        pass

        conn = self._conn()
        self._create_tables(conn)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()

    # ------------------------------------------------------------------
    # Metadata operations
    # ------------------------------------------------------------------

    def get_metadata(self, path: Path, *, file_size: int, mtime: float) -> dict | None:
        """Return cached metadata dict if file_size and mtime match, else None.

        Increments hit or miss counters accordingly.
        """
        path = path.resolve()
        key = str(path)
        conn = self._conn()
        row = conn.execute(
            "SELECT data FROM metadata WHERE path = ? AND file_size = ? AND mtime = ?",
            (key, file_size, mtime),
        ).fetchone()

        if row is None:
            with self._stats_lock:
                self._stats["metadata_misses"] += 1
            return None

        with self._stats_lock:
            self._stats["metadata_hits"] += 1
        return json.loads(row[0])

    def put_metadata(self, path: Path, data: dict, *, file_size: int, mtime: float) -> None:
        """Store metadata with validation fields. Replaces any existing entry for the path."""
        path = path.resolve()
        key = str(path)
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (path, file_size, mtime, data) VALUES (?, ?, ?, ?)",
                (key, file_size, mtime, json.dumps(data, separators=(",", ":"))),
            )
            conn.commit()

    def put_metadata_batch(self, rows: list[tuple[Path, dict, int, float]]) -> None:
        """Store multiple metadata entries in a single transaction.

        Each tuple: ``(path, data_dict, file_size, mtime)``.
        """
        if not rows:
            return
        conn = self._conn()
        prepared = [(str(p.resolve()), fs, mt, json.dumps(d, separators=(",", ":"))) for p, d, fs, mt in rows]
        with self._write_lock:
            conn.executemany(
                "INSERT OR REPLACE INTO metadata (path, file_size, mtime, data) VALUES (?, ?, ?, ?)",
                [(k, fs, mt, data) for k, fs, mt, data in prepared],
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Content hash operations
    # ------------------------------------------------------------------

    def get_content_hash(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
        rotation_invariant: bool,
    ) -> tuple[int, ...] | None:
        """Return cached content hashes if file_size, mtime, and rotation_invariant match, else None."""
        path = path.resolve()
        conn = self._conn()
        row = conn.execute(
            "SELECT hashes FROM content_hashes WHERE path = ? AND file_size = ? "
            "AND mtime = ? AND rotation_invariant = ?",
            (
                str(path),
                file_size,
                mtime,
                int(rotation_invariant),
            ),
        ).fetchone()
        if row is None:
            with self._stats_lock:
                self._stats["content_misses"] += 1
            return None
        with self._stats_lock:
            self._stats["content_hits"] += 1
        return tuple(json.loads(row[0]))

    def put_content_hash(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
        hashes: tuple[int, ...],
        rotation_invariant: bool,
    ) -> None:
        """Store content hashes with validation fields. Replaces any existing entry for the path."""
        path = path.resolve()
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO content_hashes "
                "(path, file_size, mtime, rotation_invariant, hashes) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(path),
                    file_size,
                    mtime,
                    int(rotation_invariant),
                    json.dumps(list(hashes)),
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Pre-hash operations
    # ------------------------------------------------------------------

    def get_pre_hash(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
    ) -> str | None:
        """Return cached pre-hash hex digest if file_size and mtime match, else None."""
        path = path.resolve()
        conn = self._conn()
        row = conn.execute(
            "SELECT pre_hash FROM pre_hashes WHERE path = ? AND file_size = ? AND mtime = ?",
            (str(path), file_size, mtime),
        ).fetchone()
        if row is not None:
            with self._stats_lock:
                self._stats["pre_hash_hits"] += 1
            return row[0]
        with self._stats_lock:
            self._stats["pre_hash_misses"] += 1
        return None

    def put_pre_hash(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
        pre_hash: str,
    ) -> None:
        """Store pre-hash hex digest with validation fields."""
        path = path.resolve()
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO pre_hashes (path, file_size, mtime, pre_hash) VALUES (?, ?, ?, ?)",
                (str(path), file_size, mtime, pre_hash),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # SHA-256 hash operations
    # ------------------------------------------------------------------

    def get_sha256(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
    ) -> str | None:
        """Return cached SHA-256 hex digest if file_size and mtime match, else None."""
        path = path.resolve()
        conn = self._conn()
        row = conn.execute(
            "SELECT sha256 FROM sha256_hashes WHERE path = ? AND file_size = ? AND mtime = ?",
            (str(path), file_size, mtime),
        ).fetchone()
        if row is not None:
            with self._stats_lock:
                self._stats["sha256_hits"] += 1
            return row[0]
        with self._stats_lock:
            self._stats["sha256_misses"] += 1
        return None

    def put_sha256(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
        sha256: str,
    ) -> None:
        """Store SHA-256 hex digest with validation fields."""
        path = path.resolve()
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO sha256_hashes (path, file_size, mtime, sha256) VALUES (?, ?, ?, ?)",
                (str(path), file_size, mtime, sha256),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # CLIP embedding operations
    # ------------------------------------------------------------------

    def get_clip_embedding(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
    ) -> tuple[float, ...] | None:
        """Return cached CLIP embedding if file_size and mtime match, else None."""
        import numpy as np

        path = path.resolve()
        conn = self._conn()
        row = conn.execute(
            "SELECT embedding FROM clip_embeddings WHERE path = ? AND file_size = ? AND mtime = ?",
            (str(path), file_size, mtime),
        ).fetchone()
        if row is not None:
            with self._stats_lock:
                self._stats["clip_hits"] += 1
            arr = np.frombuffer(row[0], dtype=np.float32)
            return tuple(float(v) for v in arr)
        with self._stats_lock:
            self._stats["clip_misses"] += 1
        return None

    def put_clip_embedding(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
        embedding: tuple[float, ...],
    ) -> None:
        """Store CLIP embedding as float32 BLOB with validation fields."""
        import numpy as np

        path = path.resolve()
        blob = np.array(embedding, dtype=np.float32).tobytes()
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO clip_embeddings (path, file_size, mtime, embedding) VALUES (?, ?, ?, ?)",
                (str(path), file_size, mtime, blob),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Audio fingerprint operations
    # ------------------------------------------------------------------

    def get_audio_fingerprint(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
    ) -> tuple[int, ...] | None:
        """Return cached audio fingerprint if file_size and mtime match, else None."""
        path = path.resolve()
        conn = self._conn()
        row = conn.execute(
            "SELECT fingerprint FROM audio_fingerprints WHERE path = ? AND file_size = ? AND mtime = ?",
            (str(path), file_size, mtime),
        ).fetchone()
        if row is None:
            with self._stats_lock:
                self._stats["audio_misses"] += 1
            return None
        with self._stats_lock:
            self._stats["audio_hits"] += 1
        return tuple(json.loads(row[0]))

    def put_audio_fingerprint(
        self,
        path: Path,
        *,
        file_size: int,
        mtime: float,
        fingerprint: tuple[int, ...],
    ) -> None:
        """Store audio fingerprint. Replaces any existing entry for the path."""
        path = path.resolve()
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO audio_fingerprints (path, file_size, mtime, fingerprint) VALUES (?, ?, ?, ?)",
                (str(path), file_size, mtime, json.dumps(list(fingerprint))),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Scored pair operations
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_pair(path_a: Path, path_b: Path, mtime_a: float, mtime_b: float) -> tuple[str, str, float, float]:
        """Return (key_a, key_b, mt_a, mt_b) in canonical order (sorted by resolved path string)."""
        ka = str(path_a.resolve())
        kb = str(path_b.resolve())
        if ka > kb:
            ka, kb = kb, ka
            mtime_a, mtime_b = mtime_b, mtime_a
        return ka, kb, mtime_a, mtime_b

    def get_scored_pair(
        self,
        path_a: Path,
        path_b: Path,
        *,
        config_hash: str,
        mtime_a: float,
        mtime_b: float,
    ) -> dict | None:
        """Return cached scored pair dict if config_hash and mtimes match, else None.

        The pair ``(path_a, path_b)`` is stored in canonical order so that
        lookup is independent of argument order.
        """
        ka, kb, mt_a, mt_b = self._canonical_pair(path_a, path_b, mtime_a, mtime_b)
        conn = self._conn()
        row = conn.execute(
            "SELECT score, detail FROM scored_pairs "
            "WHERE path_a = ? AND path_b = ? AND config_hash = ? AND mtime_a = ? AND mtime_b = ?",
            (ka, kb, config_hash, mt_a, mt_b),
        ).fetchone()
        if row is None:
            with self._stats_lock:
                self._stats["score_misses"] += 1
            return None
        with self._stats_lock:
            self._stats["score_hits"] += 1
        return {"score": row[0], "detail": json.loads(row[1])}

    def put_scored_pair(
        self,
        path_a: Path,
        path_b: Path,
        *,
        mtime_a: float,
        mtime_b: float,
        config_hash: str,
        score: float,
        detail: dict,
    ) -> None:
        """Store a scored pair. Canonical ordering ensures consistent primary keys."""
        ka, kb, mt_a, mt_b = self._canonical_pair(path_a, path_b, mtime_a, mtime_b)
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO scored_pairs "
                "(path_a, path_b, mtime_a, mtime_b, config_hash, score, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ka, kb, mt_a, mt_b, config_hash, score, json.dumps(detail, separators=(",", ":"))),
            )
            conn.commit()

    def put_scored_pairs_bulk(
        self,
        rows: list[tuple[str, str, float, float, str, float, str]],
    ) -> None:
        """Store multiple scored pairs in a single transaction.

        Each tuple: (path_a, path_b, mtime_a, mtime_b, config_hash, score, detail_json).
        Paths should already be resolved and in canonical order (a < b).
        """
        if not rows:
            return
        conn = self._conn()
        with self._write_lock:
            conn.executemany(
                "INSERT OR REPLACE INTO scored_pairs "
                "(path_a, path_b, mtime_a, mtime_b, config_hash, score, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        # Every pair stored was a cache miss (not found, had to be scored)
        with self._stats_lock:
            self._stats["score_misses"] += len(rows)

    def get_scored_pairs_bulk(
        self,
        paths: set[Path],
        *,
        config_hash: str,
        mtimes: dict[Path, float],
    ) -> list[dict]:
        """Return all cached scored pairs where both paths are in *paths* and mtimes match.

        Uses a temporary table for efficient bulk lookup.
        """
        conn = self._conn()
        with self._write_lock:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _bulk_paths (path TEXT PRIMARY KEY, mtime REAL NOT NULL)")
            conn.execute("DELETE FROM _bulk_paths")

            rows = [(str(p.resolve()), mtimes[p]) for p in paths if p in mtimes]
            if rows:
                conn.executemany("INSERT INTO _bulk_paths (path, mtime) VALUES (?, ?)", rows)

            results = conn.execute(
                "SELECT sp.path_a, sp.path_b, sp.score, sp.detail "
                "FROM scored_pairs sp "
                "INNER JOIN _bulk_paths ba ON sp.path_a = ba.path AND sp.mtime_a = ba.mtime "
                "INNER JOIN _bulk_paths bb ON sp.path_b = bb.path AND sp.mtime_b = bb.mtime "
                "WHERE sp.config_hash = ?",
                (config_hash,),
            ).fetchall()

            conn.execute("DROP TABLE IF EXISTS _bulk_paths")
            conn.commit()
        parsed = [{"path_a": r[0], "path_b": r[1], "score": r[2], "detail": json.loads(r[3])} for r in results]
        if parsed:
            with self._stats_lock:
                self._stats["score_hits"] += len(parsed)
        return parsed

    # ------------------------------------------------------------------
    # JSON migration
    # ------------------------------------------------------------------

    def _migrate_json_caches(self) -> None:
        """Migrate legacy JSON cache files into the SQLite database.

        Handles ``metadata.json``, ``content-hashes.json``, and ``audio-fingerprints.json``.
        On success each JSON file is renamed to ``.bak``.  Failures are logged
        but never block startup.
        """
        for method in (
            self._migrate_metadata_json,
            self._migrate_content_hashes_json,
            self._migrate_audio_fingerprints_json,
        ):
            try:
                method()
            except Exception:
                logger.debug("JSON cache migration failed for %s", method.__name__, exc_info=True)

    def _migrate_metadata_json(self) -> None:
        path = self._cache_dir / "metadata.json"
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or parsed.get("version") != 2:
            return
        metadata = parsed.get("metadata")
        if not isinstance(metadata, dict):
            return
        conn = self._conn()
        for file_path, entry in metadata.items():
            if not isinstance(entry, dict):
                continue
            file_size = entry.pop("file_size", None)
            mtime = entry.pop("mtime", None)
            if file_size is None or mtime is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO metadata (path, file_size, mtime, data) VALUES (?, ?, ?, ?)",
                (file_path, file_size, mtime, json.dumps(entry, separators=(",", ":"))),
            )
        conn.commit()
        path.rename(path.with_suffix(".json.bak"))

    def _migrate_content_hashes_json(self) -> None:
        path = self._cache_dir / "content-hashes.json"
        if not path.exists():
            return
        # Legacy JSON content hash caches used the old pHash/imagehash format
        # which is incompatible with the new PDQ hashing. Simply rename the
        # file to .bak without migrating -- the hashes will be recomputed.
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or parsed.get("version") != 1:
            return
        logger.info(
            "Legacy content hash cache uses incompatible format; renamed to %s "
            "(hashes will be recomputed on next --content scan)",
            path.with_suffix(".json.bak").name,
        )
        path.rename(path.with_suffix(".json.bak"))

    def _migrate_audio_fingerprints_json(self) -> None:
        path = self._cache_dir / "audio-fingerprints.json"
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or parsed.get("version") != 1:
            return
        fingerprints = parsed.get("fingerprints")
        if not isinstance(fingerprints, dict):
            return
        conn = self._conn()
        for file_path, entry in fingerprints.items():
            if not isinstance(entry, dict):
                continue
            fp = entry.get("fingerprint")
            if not isinstance(fp, list):
                continue
            conn.execute(
                "INSERT OR IGNORE INTO audio_fingerprints (path, file_size, mtime, fingerprint) VALUES (?, ?, ?, ?)",
                (
                    file_path,
                    entry.get("file_size", 0),
                    entry.get("mtime", 0.0),
                    json.dumps(fp),
                ),
            )
        conn.commit()
        path.rename(path.with_suffix(".json.bak"))

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune(self, active_paths: set[Path]) -> int:
        """Remove entries from all tables whose paths are not in *active_paths*.

        Uses a temporary table for efficient bulk comparison.
        Returns the total number of deleted rows across all tables.
        """
        conn = self._conn()
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _active_paths (path TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _active_paths")

        active_strings = [(str(p.resolve()),) for p in active_paths]
        if active_strings:
            conn.executemany("INSERT INTO _active_paths (path) VALUES (?)", active_strings)

        deleted = 0
        for table in (
            "metadata",
            "content_hashes",
            "audio_fingerprints",
            "pre_hashes",
            "sha256_hashes",
            "clip_embeddings",
        ):
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE path NOT IN (SELECT path FROM _active_paths)"  # noqa: S608
            )
            deleted += cursor.rowcount

        # scored_pairs: remove if either path_a or path_b is not active
        cursor = conn.execute(
            "DELETE FROM scored_pairs WHERE"
            " path_a NOT IN (SELECT path FROM _active_paths)"
            " OR path_b NOT IN (SELECT path FROM _active_paths)"
        )
        deleted += cursor.rowcount

        conn.execute("DROP TABLE IF EXISTS _active_paths")
        conn.commit()
        return deleted

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return a dict with per-table ``hits`` and ``misses`` counters."""
        with self._stats_lock:
            return dict(self._stats)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Commit any pending writes across all connections.

        No-op when all writes auto-commit (the default), but called by
        pipeline stages at boundaries for safety.
        """

    def close(self) -> None:
        """Flush pending writes and close all tracked per-thread connections."""
        self.flush()
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
        self._local.conn = None
