from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path


def _atomic_json_save(cache_dir: Path, cache_file: Path, payload: dict) -> None:
    """Persist a JSON payload atomically via tempfile + os.replace."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warnings.warn(
            f"Cannot create cache directory, skipping save: {exc}",
            stacklevel=3,
        )
        return
    data = json.dumps(payload, separators=(",", ":"))
    try:
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp_path, cache_file)
    except OSError as exc:
        warnings.warn(
            f"Failed to save cache {cache_file.name}: {exc}",
            stacklevel=3,
        )


_CACHE_FILENAME = "content-hashes.json"
_CACHE_VERSION = 1

_METADATA_CACHE_FILENAME = "metadata.json"
_METADATA_CACHE_VERSION = 2

_AUDIO_CACHE_FILENAME = "audio-fingerprints.json"
_AUDIO_CACHE_VERSION = 1


class ContentHashCache:
    """Disk-backed cache for perceptual content hashes.

    Stores hashes keyed by resolved file path with validation fields
    (file_size, mtime, interval, hash_size) to detect stale entries.

    .. deprecated::
        Use :class:`~duplicates_detector.cache_db.CacheDB` instead.
        This class will be removed once the sequential pipeline is fully
        replaced by the async pipeline.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        if cache_dir is None:
            xdg = os.environ.get("XDG_CACHE_HOME")
            base = Path(xdg) if xdg else Path.home() / ".cache"
            cache_dir = base / "duplicates-detector"
        self._cache_dir = cache_dir
        self._cache_file = cache_dir / _CACHE_FILENAME
        self._data: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        """Load the cache from disk, degrading gracefully on errors."""
        if not self._cache_file.exists():
            return
        try:
            raw = self._cache_file.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.warn(
                f"Content hash cache is corrupt, starting fresh: {exc}",
                stacklevel=2,
            )
            return
        if not isinstance(parsed, dict) or parsed.get("version") != _CACHE_VERSION:
            return
        hashes = parsed.get("hashes")
        if isinstance(hashes, dict):
            self._data = hashes

    def get(
        self,
        path: Path,
        file_size: int,
        mtime: float | None,
        interval: float,
        hash_size: int,
        algorithm: str = "phash",
        rotation_invariant: bool = False,
        strategy: str = "interval",
        scene_threshold: float | None = None,
    ) -> tuple[int, ...] | None:
        """Return cached hash if all validation fields match, else None."""
        key = str(path.resolve())
        entry = self._data.get(key)
        if not isinstance(entry, dict):
            self.misses += 1
            return None
        if (
            entry.get("file_size") != file_size
            or entry.get("mtime") != mtime
            or entry.get("interval") != interval
            or entry.get("hash_size") != hash_size
            or entry.get("algorithm", "phash") != algorithm
            or entry.get("rotation_invariant", False) != rotation_invariant
            or entry.get("strategy", "interval") != strategy
            or (strategy == "scene" and entry.get("scene_threshold") != scene_threshold)
        ):
            self.misses += 1
            return None
        stored = entry.get("hash")
        if not isinstance(stored, list) or not all(isinstance(v, int) for v in stored):
            self.misses += 1
            return None
        self.hits += 1
        return tuple(stored)

    def put(
        self,
        path: Path,
        file_size: int,
        mtime: float | None,
        content_hash: tuple[int, ...],
        interval: float,
        hash_size: int,
        algorithm: str = "phash",
        rotation_invariant: bool = False,
        strategy: str = "interval",
        scene_threshold: float | None = None,
    ) -> None:
        """Store a content hash with its validation fields."""
        key = str(path.resolve())
        self._data[key] = {
            "file_size": file_size,
            "mtime": mtime,
            "hash": list(content_hash),
            "interval": interval,
            "hash_size": hash_size,
            "algorithm": algorithm,
            "rotation_invariant": rotation_invariant,
            "strategy": strategy,
            "scene_threshold": scene_threshold,
        }

    def save(self) -> None:
        """Persist the cache to disk atomically via tempfile + rename."""
        _atomic_json_save(self._cache_dir, self._cache_file, {"version": _CACHE_VERSION, "hashes": self._data})


class MetadataCache:
    """Disk-backed cache for ffprobe metadata results.

    Stores duration/width/height keyed by resolved file path with
    file_size + mtime validation to detect stale entries.  Entries not
    accessed during the current session are pruned on save.

    .. deprecated::
        Use :class:`~duplicates_detector.cache_db.CacheDB` instead.
        This class will be removed once the sequential pipeline is fully
        replaced by the async pipeline.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        if cache_dir is None:
            xdg = os.environ.get("XDG_CACHE_HOME")
            base = Path(xdg) if xdg else Path.home() / ".cache"
            cache_dir = base / "duplicates-detector"
        self._cache_dir = cache_dir
        self._cache_file = cache_dir / _METADATA_CACHE_FILENAME
        self._data: dict[str, dict] = {}
        self._accessed: set[str] = set()
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        """Load the cache from disk, degrading gracefully on errors."""
        if not self._cache_file.exists():
            return
        try:
            raw = self._cache_file.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.warn(
                f"Metadata cache is corrupt, starting fresh: {exc}",
                stacklevel=2,
            )
            return
        if not isinstance(parsed, dict) or parsed.get("version") != _METADATA_CACHE_VERSION:
            return
        metadata = parsed.get("metadata")
        if isinstance(metadata, dict):
            self._data = metadata

    def get(
        self,
        path: Path,
        file_size: int,
        mtime: float,
    ) -> dict | None:
        """Return cached metadata if validation fields match, else None.

        Returns a dict with keys ``duration``, ``width``, ``height``,
        ``codec``, ``bitrate``, ``framerate``, ``audio_channels``
        (values may be ``None``).  Returns ``None`` on cache miss.
        """
        key = str(path.resolve())
        entry = self._data.get(key)
        if not isinstance(entry, dict):
            self.misses += 1
            return None
        if entry.get("file_size") != file_size or entry.get("mtime") != mtime:
            self.misses += 1
            return None
        duration = entry.get("duration")
        width = entry.get("width")
        height = entry.get("height")
        codec = entry.get("codec")
        bitrate = entry.get("bitrate")
        framerate = entry.get("framerate")
        audio_channels = entry.get("audio_channels")
        exif_datetime = entry.get("exif_datetime")
        exif_camera = entry.get("exif_camera")
        exif_lens = entry.get("exif_lens")
        exif_gps_lat = entry.get("exif_gps_lat")
        exif_gps_lon = entry.get("exif_gps_lon")
        exif_width = entry.get("exif_width")
        exif_height = entry.get("exif_height")
        tag_title = entry.get("tag_title")
        tag_artist = entry.get("tag_artist")
        tag_album = entry.get("tag_album")
        if not (
            (duration is None or isinstance(duration, (int, float)))
            and (width is None or isinstance(width, int))
            and (height is None or isinstance(height, int))
            and (codec is None or isinstance(codec, str))
            and (bitrate is None or isinstance(bitrate, int))
            and (framerate is None or isinstance(framerate, (int, float)))
            and (audio_channels is None or isinstance(audio_channels, int))
            and (exif_datetime is None or isinstance(exif_datetime, (int, float)))
            and (exif_camera is None or isinstance(exif_camera, str))
            and (exif_lens is None or isinstance(exif_lens, str))
            and (exif_gps_lat is None or isinstance(exif_gps_lat, (int, float)))
            and (exif_gps_lon is None or isinstance(exif_gps_lon, (int, float)))
            and (exif_width is None or isinstance(exif_width, int))
            and (exif_height is None or isinstance(exif_height, int))
            and (tag_title is None or isinstance(tag_title, str))
            and (tag_artist is None or isinstance(tag_artist, str))
            and (tag_album is None or isinstance(tag_album, str))
        ):
            self.misses += 1
            return None
        self._accessed.add(key)
        self.hits += 1
        return {
            "duration": duration,
            "width": width,
            "height": height,
            "codec": codec,
            "bitrate": bitrate,
            "framerate": framerate,
            "audio_channels": audio_channels,
            "exif_datetime": exif_datetime,
            "exif_camera": exif_camera,
            "exif_lens": exif_lens,
            "exif_gps_lat": exif_gps_lat,
            "exif_gps_lon": exif_gps_lon,
            "exif_width": exif_width,
            "exif_height": exif_height,
            "tag_title": tag_title,
            "tag_artist": tag_artist,
            "tag_album": tag_album,
        }

    def put(
        self,
        path: Path,
        file_size: int,
        mtime: float | None,
        duration: float | None,
        width: int | None,
        height: int | None,
        codec: str | None = None,
        bitrate: int | None = None,
        framerate: float | None = None,
        audio_channels: int | None = None,
        exif_datetime: float | None = None,
        exif_camera: str | None = None,
        exif_lens: str | None = None,
        exif_gps_lat: float | None = None,
        exif_gps_lon: float | None = None,
        exif_width: int | None = None,
        exif_height: int | None = None,
        tag_title: str | None = None,
        tag_artist: str | None = None,
        tag_album: str | None = None,
    ) -> None:
        """Store metadata with its validation fields."""
        key = str(path.resolve())
        self._data[key] = {
            "file_size": file_size,
            "mtime": mtime,
            "duration": duration,
            "width": width,
            "height": height,
            "codec": codec,
            "bitrate": bitrate,
            "framerate": framerate,
            "audio_channels": audio_channels,
            "exif_datetime": exif_datetime,
            "exif_camera": exif_camera,
            "exif_lens": exif_lens,
            "exif_gps_lat": exif_gps_lat,
            "exif_gps_lon": exif_gps_lon,
            "exif_width": exif_width,
            "exif_height": exif_height,
            "tag_title": tag_title,
            "tag_artist": tag_artist,
            "tag_album": tag_album,
        }
        self._accessed.add(key)

    def save(self) -> None:
        """Persist to disk atomically, pruning entries not seen this session."""
        pruned = {k: v for k, v in self._data.items() if k in self._accessed}
        _atomic_json_save(self._cache_dir, self._cache_file, {"version": _METADATA_CACHE_VERSION, "metadata": pruned})


class AudioFingerprintCache:
    """Disk-backed cache for Chromaprint audio fingerprints.

    Stores fingerprints keyed by resolved file path with validation
    fields (file_size, mtime) to detect stale entries.

    .. deprecated::
        Use :class:`~duplicates_detector.cache_db.CacheDB` instead.
        This class will be removed once the sequential pipeline is fully
        replaced by the async pipeline.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        if cache_dir is None:
            xdg = os.environ.get("XDG_CACHE_HOME")
            base = Path(xdg) if xdg else Path.home() / ".cache"
            cache_dir = base / "duplicates-detector"
        self._cache_dir = cache_dir
        self._cache_file = cache_dir / _AUDIO_CACHE_FILENAME
        self._data: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        """Load the cache from disk, degrading gracefully on errors."""
        if not self._cache_file.exists():
            return
        try:
            raw = self._cache_file.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.warn(
                f"Audio fingerprint cache is corrupt, starting fresh: {exc}",
                stacklevel=2,
            )
            return
        if not isinstance(parsed, dict) or parsed.get("version") != _AUDIO_CACHE_VERSION:
            return
        fingerprints = parsed.get("fingerprints")
        if isinstance(fingerprints, dict):
            self._data = fingerprints

    def get(
        self,
        path: Path,
        file_size: int,
        mtime: float | None,
    ) -> tuple[int, ...] | None:
        """Return cached fingerprint if validation fields match, else None."""
        key = str(path.resolve())
        entry = self._data.get(key)
        if not isinstance(entry, dict):
            self.misses += 1
            return None
        if entry.get("file_size") != file_size or entry.get("mtime") != mtime:
            self.misses += 1
            return None
        stored = entry.get("fingerprint")
        if not isinstance(stored, list) or not all(isinstance(v, int) for v in stored):
            self.misses += 1
            return None
        self.hits += 1
        return tuple(stored)

    def put(
        self,
        path: Path,
        file_size: int,
        mtime: float | None,
        fingerprint: tuple[int, ...],
    ) -> None:
        """Store a fingerprint with its validation fields."""
        key = str(path.resolve())
        self._data[key] = {
            "file_size": file_size,
            "mtime": mtime,
            "fingerprint": list(fingerprint),
        }

    def save(self) -> None:
        """Persist the cache to disk atomically via tempfile + rename."""
        _atomic_json_save(
            self._cache_dir, self._cache_file, {"version": _AUDIO_CACHE_VERSION, "fingerprints": self._data}
        )


# New unified cache — re-exported for convenience
from duplicates_detector.cache_db import CacheDB  # noqa: E402, F401
