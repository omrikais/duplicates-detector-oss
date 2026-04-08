from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import calendar
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from duplicates_detector.progress import make_progress

if TYPE_CHECKING:
    from duplicates_detector.cache import MetadataCache
    from duplicates_detector.cache_db import CacheDB
    from duplicates_detector.progress import ProgressEmitter


_INITIAL_FFPROBE_TIMEOUT = 30.0
_RETRY_FFPROBE_TIMEOUT = 90.0
_RETRY_FFPROBE_MAX_WORKERS = 4


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    path: Path
    filename: str  # stem only, no extension
    duration: float | None  # seconds
    width: int | None
    height: int | None
    file_size: int  # bytes
    codec: str | None = None  # video codec name (e.g., "h264", "hevc")
    bitrate: int | None = None  # container bitrate in bits/sec
    framerate: float | None = None  # video frame rate (fps)
    audio_channels: int | None = None  # audio channel count
    mtime: float | None = None  # modification time (epoch seconds)
    is_reference: bool = False
    content_hash: tuple[int, ...] | None = None
    pre_hash: str | None = None  # MD5 hex digest of first 4KB
    content_frames: tuple[bytes, ...] | None = None  # raw PNG frame data for SSIM
    exif_datetime: float | None = None  # DateTimeOriginal as epoch seconds
    exif_camera: str | None = None  # "make model" normalized lowercase
    exif_lens: str | None = None  # LensModel normalized lowercase
    exif_gps_lat: float | None = None  # GPS latitude (decimal degrees)
    exif_gps_lon: float | None = None  # GPS longitude (decimal degrees)
    exif_width: int | None = None  # EXIF-reported image width
    exif_height: int | None = None  # EXIF-reported image height
    audio_fingerprint: tuple[int, ...] | None = None  # raw Chromaprint fingerprint (int32 values)
    tag_title: str | None = None  # audio tag: track title (lowercase stripped)
    tag_artist: str | None = None  # audio tag: artist name (lowercase stripped)
    tag_album: str | None = None  # audio tag: album name (lowercase stripped)
    sidecars: tuple[Path, ...] | None = None  # associated sidecar file paths
    clip_embedding: tuple[float, ...] | None = None  # CLIP ViT-B/32 embedding (flattened float32)
    page_count: int | None = None  # document page/line count
    doc_title: str | None = None  # document title (lowercase stripped)
    doc_author: str | None = None  # document author (lowercase stripped)
    doc_created: str | None = None  # document creation date (ISO 8601)
    text_content: str | None = None  # extracted text (transient, not cached)


def check_ffprobe() -> None:
    """Raise RuntimeError if ffprobe is not available on PATH."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found on PATH. Install ffmpeg: https://ffmpeg.org/download.html")


def _has_probe_metadata(meta: VideoMetadata) -> bool:
    """Return True when ffprobe yielded any media-specific metadata."""
    return any(
        value is not None
        for value in (
            meta.duration,
            meta.width,
            meta.height,
            meta.codec,
            meta.bitrate,
            meta.framerate,
            meta.audio_channels,
        )
    )


def extract_one(path: Path, timeout: float = _INITIAL_FFPROBE_TIMEOUT) -> VideoMetadata | None:
    """Run ffprobe on a single file and return VideoMetadata.

    Returns None if the file cannot be read at all (missing, permission denied).
    Fields may be None if ffprobe cannot extract them (corrupt file).
    """
    try:
        stat_result = path.stat()
        file_size = stat_result.st_size
        mtime = stat_result.st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return None

    duration: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    framerate: float | None = None
    audio_channels: int | None = None

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_entries",
                "format=duration,bit_rate:stream=width,height,duration,codec_name,r_frame_rate,codec_type,channels",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)

            fmt = data.get("format", {})
            if "duration" in fmt:
                duration = float(fmt["duration"])
            if "bit_rate" in fmt:
                try:
                    bitrate = int(fmt["bit_rate"])
                except (ValueError, TypeError):
                    pass

            streams = data.get("streams", [])

            # Find first video stream
            video_stream = next(
                (s for s in streams if s.get("codec_type") == "video"),
                None,
            )
            if video_stream:
                w = video_stream.get("width")
                h = video_stream.get("height")
                if w is not None and h is not None:
                    width = int(w)
                    height = int(h)
                codec = video_stream.get("codec_name")
                rfr = video_stream.get("r_frame_rate")
                if rfr and "/" in rfr:
                    try:
                        num, den = rfr.split("/")
                        if int(den) > 0:
                            framerate = round(int(num) / int(den), 3)
                    except (ValueError, TypeError):
                        pass
                # Fall back to stream-level duration (MKV, TS, AVI, etc.)
                if duration is None and "duration" in video_stream:
                    duration = float(video_stream["duration"])

            # Find first audio stream
            audio_stream = next(
                (s for s in streams if s.get("codec_type") == "audio"),
                None,
            )
            if audio_stream:
                ch = audio_stream.get("channels")
                if ch is not None:
                    audio_channels = int(ch)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError):
        pass

    return VideoMetadata(
        path=path,
        filename=path.stem,
        duration=duration,
        width=width,
        height=height,
        codec=codec,
        bitrate=bitrate,
        framerate=framerate,
        audio_channels=audio_channels,
        file_size=file_size,
        mtime=mtime,
    )


def _extract_exif(img: object) -> dict[str, float | str | int | None]:
    """Extract EXIF metadata from a PIL Image object.

    Returns a dict with keys: exif_datetime, exif_camera, exif_lens,
    exif_gps_lat, exif_gps_lon, exif_width, exif_height.
    All values may be None. Never raises — EXIF failures are silently ignored.
    """
    result: dict[str, float | str | int | None] = {
        "exif_datetime": None,
        "exif_camera": None,
        "exif_lens": None,
        "exif_gps_lat": None,
        "exif_gps_lon": None,
        "exif_width": None,
        "exif_height": None,
    }
    try:
        exif = img.getexif()  # type: ignore[union-attr]
        if not exif:
            return result

        # Camera make (tag 271) + model (tag 272)
        make = str(exif.get(271, "")).strip()
        model = str(exif.get(272, "")).strip()
        camera = f"{make} {model}".strip().lower()
        if camera:
            result["exif_camera"] = camera

        # EXIF sub-IFD (tag 0x8769)
        exif_ifd = exif.get_ifd(0x8769)
        if exif_ifd:
            # DateTimeOriginal (tag 36867)
            dt_str = exif_ifd.get(36867)
            if dt_str and isinstance(dt_str, str):
                try:
                    result["exif_datetime"] = float(
                        calendar.timegm(datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").timetuple())
                    )
                except (ValueError, OSError):
                    pass

            # LensModel (tag 42036)
            lens = exif_ifd.get(42036)
            if lens and isinstance(lens, str):
                result["exif_lens"] = lens.strip().lower()

            # ExifImageWidth (tag 40962) and ExifImageHeight (tag 40963)
            ew = exif_ifd.get(40962)
            eh = exif_ifd.get(40963)
            if isinstance(ew, int) and isinstance(eh, int):
                result["exif_width"] = ew
                result["exif_height"] = eh

        # GPS sub-IFD (tag 0x8825)
        gps_ifd = exif.get_ifd(0x8825)
        if gps_ifd:
            lat_data = gps_ifd.get(2)  # GPSLatitude
            lat_ref = gps_ifd.get(1)  # GPSLatitudeRef
            lon_data = gps_ifd.get(4)  # GPSLongitude
            lon_ref = gps_ifd.get(3)  # GPSLongitudeRef
            if lat_data and lon_data and lat_ref and lon_ref:
                try:
                    lat = float(lat_data[0]) + float(lat_data[1]) / 60.0 + float(lat_data[2]) / 3600.0
                    if lat_ref == "S":
                        lat = -lat
                    lon = float(lon_data[0]) + float(lon_data[1]) / 60.0 + float(lon_data[2]) / 3600.0
                    if lon_ref == "W":
                        lon = -lon
                    result["exif_gps_lat"] = lat
                    result["exif_gps_lon"] = lon
                except (TypeError, ValueError, IndexError, ZeroDivisionError):
                    pass
    except Exception:
        pass
    return result


def extract_one_image(path: Path) -> VideoMetadata | None:
    """Read image metadata using PIL and return VideoMetadata.

    Returns None if the file cannot be read at all (missing, permission denied,
    unsupported format, or corrupt image data).
    Video-specific fields (duration, bitrate, framerate, audio_channels) are None.
    """
    try:
        stat_result = path.stat()
        file_size = stat_result.st_size
        mtime = stat_result.st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return None

    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            codec = (img.format or "").lower() or None
            exif = _extract_exif(img)
    except Exception:
        return None

    return VideoMetadata(
        path=path,
        filename=path.stem,
        duration=None,
        width=width,
        height=height,
        codec=codec,
        bitrate=None,
        framerate=None,
        audio_channels=None,
        file_size=file_size,
        mtime=mtime,
        exif_datetime=exif.get("exif_datetime"),  # type: ignore[arg-type]
        exif_camera=exif.get("exif_camera"),  # type: ignore[arg-type]
        exif_lens=exif.get("exif_lens"),  # type: ignore[arg-type]
        exif_gps_lat=exif.get("exif_gps_lat"),  # type: ignore[arg-type]
        exif_gps_lon=exif.get("exif_gps_lon"),  # type: ignore[arg-type]
        exif_width=exif.get("exif_width"),  # type: ignore[arg-type]
        exif_height=exif.get("exif_height"),  # type: ignore[arg-type]
    )


_VIDEO_CACHE_FIELDS = ("duration", "width", "height", "codec", "bitrate", "framerate", "audio_channels")
_IMAGE_CACHE_FIELDS = _VIDEO_CACHE_FIELDS + (
    "exif_datetime",
    "exif_camera",
    "exif_lens",
    "exif_gps_lat",
    "exif_gps_lon",
    "exif_width",
    "exif_height",
)
_AUDIO_CACHE_FIELDS = _VIDEO_CACHE_FIELDS + ("tag_title", "tag_artist", "tag_album")
_DOCUMENT_CACHE_FIELDS = ("page_count", "doc_title", "doc_author", "doc_created")


def _extract_all_generic(
    files: list[Path],
    *,
    extract_fn: Callable[[Path], VideoMetadata | None],
    cache_fields: tuple[str, ...],
    cache_skip_fn: Callable[[VideoMetadata], bool],
    task_label: str,
    workers: int = 0,
    verbose: bool = False,
    cache: MetadataCache | None = None,
    cache_db: CacheDB | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
    result_filter: Callable[[VideoMetadata], bool] | None = None,
    retry_fn: Callable[[Path, float], VideoMetadata | None] | None = None,
) -> list[VideoMetadata]:
    """Generic extraction pipeline shared by video/image/audio modes.

    Args:
        extract_fn: Per-file extraction function (e.g. extract_one, extract_one_image).
        cache_fields: Tuple of VideoMetadata field names to read/write from cache.
        cache_skip_fn: Returns True when a result should NOT be stored in cache
            (i.e. all meaningful fields are None — likely a transient failure).
        task_label: Label for the Rich progress bar.
        result_filter: When provided, only results passing this predicate are
            added to ``results``. Items that fail are collected as retry
            candidates (only meaningful when ``retry_fn`` is also set).
        retry_fn: When provided and there are retry candidates, runs a second
            extraction pass with reduced workers and ``_RETRY_FFPROBE_TIMEOUT``.
            Signature: ``(path, timeout) -> VideoMetadata | None``.

    Returns combined cached + extracted results.
    """
    console = Console(stderr=True)

    if workers <= 0:
        workers = min((os.cpu_count() or 4) * 8, 128)

    # Pre-pass: check cache for each file (prefer CacheDB over legacy JSON)
    cached_results: list[VideoMetadata] = []
    to_extract: list[Path] = files
    if cache_db is not None or cache is not None:
        to_extract = []
        for path in files:
            try:
                st = path.stat()
            except (FileNotFoundError, PermissionError, OSError):
                to_extract.append(path)
                continue
            if cache_db is not None:
                hit = cache_db.get_metadata(path, file_size=st.st_size, mtime=st.st_mtime)
            else:
                assert cache is not None
                hit = cache.get(path, file_size=st.st_size, mtime=st.st_mtime)
            if hit is not None:
                kwargs: dict[str, object] = {field: hit.get(field) for field in cache_fields}
                cached_results.append(
                    VideoMetadata(
                        path=path,
                        filename=path.stem,
                        file_size=st.st_size,
                        mtime=st.st_mtime,
                        **kwargs,  # type: ignore[arg-type]
                    )
                )
            else:
                to_extract.append(path)

    results: list[VideoMetadata] = []
    skipped: list[Path] = []
    retry_candidates: dict[Path, VideoMetadata] = {}

    if progress_emitter is not None:
        progress_emitter.stage_start("extract", total=len(files))
    extract_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(extract_fn, f): f for f in to_extract}

        with make_progress(console=console, quiet=quiet, progress_emitter=progress_emitter) as progress:
            task = progress.add_task(task_label, total=len(to_extract))

            for completed, future in enumerate(as_completed(futures), 1):
                meta = future.result()
                if meta is not None:
                    if result_filter is not None:
                        if result_filter(meta):
                            results.append(meta)
                        else:
                            retry_candidates[futures[future]] = meta
                    else:
                        results.append(meta)
                else:
                    skipped.append(futures[future])
                progress.advance(task)
                if progress_emitter is not None:
                    progress_emitter.progress(
                        "extract",
                        current=len(cached_results) + completed,
                        total=len(files),
                        file=str(futures[future]),
                    )

    # Retry pass (video mode: re-extract with longer timeout)
    if retry_candidates and retry_fn is not None:
        retry_workers = min(
            _RETRY_FFPROBE_MAX_WORKERS,
            len(retry_candidates),
            max(1, workers // 8),
        )
        retried: dict[Path, VideoMetadata] = {}
        with ThreadPoolExecutor(max_workers=retry_workers) as executor:
            futures = {executor.submit(retry_fn, path, _RETRY_FFPROBE_TIMEOUT): path for path in retry_candidates}
            for future in as_completed(futures):
                path = futures[future]
                meta = future.result()
                if meta is not None:
                    retried[path] = meta

        for path, original_meta in retry_candidates.items():
            meta = retried.get(path, original_meta)
            results.append(meta)

    if progress_emitter is not None:
        progress_emitter.progress(
            "extract",
            current=len(files),
            total=len(files),
            force=True,
        )
        progress_emitter.stage_end("extract", total=len(files), elapsed=time.monotonic() - extract_start)

    # Post-pass: store newly extracted metadata in cache
    # Skip all-None entries (likely transient failures) so they
    # get retried on the next run instead of being permanently cached.
    if cache_db is not None:
        for meta in results:
            if cache_skip_fn(meta):
                continue
            data = {field: getattr(meta, field) for field in cache_fields}
            cache_db.put_metadata(
                meta.path,
                data,
                file_size=meta.file_size,
                mtime=meta.mtime or 0.0,
            )
    if cache is not None:
        for meta in results:
            if cache_skip_fn(meta):
                continue
            data = {field: getattr(meta, field) for field in cache_fields}
            cache.put(
                path=meta.path,
                file_size=meta.file_size,
                mtime=meta.mtime,
                **data,
            )
        cache.save()
        if verbose:
            total = cache.hits + cache.misses
            rate = cache.hits / total if total else 0
            console.print(
                f"  [dim]Metadata cache: {cache.hits} hits, {cache.misses} misses ({rate:.0%} hit rate)[/dim]"
            )

    if verbose and skipped:
        for path in skipped:
            console.print(f"  [dim]Skipped: {path}[/dim]")

    return cached_results + results


def extract_all(
    files: list[Path],
    *,
    workers: int = 0,
    verbose: bool = False,
    cache: MetadataCache | None = None,
    cache_db: CacheDB | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract metadata from all files in parallel.

    Args:
        workers: Number of parallel ffprobe threads. 0 = auto-detect
                 (cpu_count * 8, capped at 128). ffprobe is I/O-bound
                 (subprocess.run releases the GIL) so over-subscribing
                 CPU cores is beneficial.
        cache: Optional MetadataCache (legacy JSON). When provided, files
               whose stat matches a cached entry skip ffprobe entirely.
        cache_db: Optional CacheDB (SQLite). Preferred over ``cache``
                  when both are provided.

    Returns only successfully extracted items (skips None results).
    """
    check_ffprobe()
    return _extract_all_generic(
        files,
        extract_fn=extract_one,
        cache_fields=_VIDEO_CACHE_FIELDS,
        cache_skip_fn=lambda m: m.duration is None and m.width is None and m.height is None,
        task_label="Extracting metadata",
        result_filter=_has_probe_metadata,
        retry_fn=extract_one,
        workers=workers,
        verbose=verbose,
        cache=cache,
        cache_db=cache_db,
        quiet=quiet,
        progress_emitter=progress_emitter,
    )


def extract_all_images(
    files: list[Path],
    *,
    workers: int = 0,
    verbose: bool = False,
    cache: MetadataCache | None = None,
    cache_db: CacheDB | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract metadata from image files in parallel.

    Uses PIL instead of ffprobe — does NOT require ffprobe/ffmpeg.
    Same interface as extract_all() but with image-appropriate cache
    skip conditions.
    """
    return _extract_all_generic(
        files,
        extract_fn=extract_one_image,
        cache_fields=_IMAGE_CACHE_FIELDS,
        cache_skip_fn=lambda m: m.width is None and m.height is None,
        task_label="Extracting image metadata",
        workers=workers,
        verbose=verbose,
        cache=cache,
        cache_db=cache_db,
        quiet=quiet,
        progress_emitter=progress_emitter,
    )


def _extract_tags(
    path: Path,
) -> dict[str, str | float | int | None]:
    """Extract audio metadata tags using mutagen.

    Returns a dict with keys: tag_title, tag_artist, tag_album, duration,
    codec, bitrate, audio_channels.  All values may be None.
    Never raises — tag extraction failures are silently ignored.
    """
    result: dict[str, str | float | int | None] = {
        "tag_title": None,
        "tag_artist": None,
        "tag_album": None,
        "duration": None,
        "codec": None,
        "bitrate": None,
        "audio_channels": None,
    }
    try:
        import mutagen  # type: ignore[import-untyped]

        audio = mutagen.File(path, easy=True)  # type: ignore[attr-defined]
        if audio is None:
            return result

        # Duration from mutagen.info
        if hasattr(audio, "info") and audio.info is not None:
            if hasattr(audio.info, "length") and audio.info.length:
                result["duration"] = float(audio.info.length)
            if hasattr(audio.info, "bitrate") and audio.info.bitrate:
                result["bitrate"] = int(audio.info.bitrate)
            if hasattr(audio.info, "channels") and audio.info.channels:
                result["audio_channels"] = int(audio.info.channels)

        # Codec from stream info (preferred) or file type (fallback)
        stream_codec = getattr(getattr(audio, "info", None), "codec", None)
        if isinstance(stream_codec, str) and stream_codec:
            # mutagen MP4 exposes codec as e.g. "mp4a.40.2" (AAC-LC), "alac" (ALAC)
            stream_codec_map = {"alac": "alac", "ac-3": "ac3", "ec-3": "eac3"}
            if stream_codec.startswith("mp4a"):
                result["codec"] = "aac"
            else:
                result["codec"] = stream_codec_map.get(stream_codec, stream_codec)
        else:
            type_name = type(audio).__name__.lower()
            codec_map = {
                "mp3": "mp3",
                "flac": "flac",
                "oggvorbis": "vorbis",
                "oggopus": "opus",
                "mp4": "aac",
                "aac": "aac",
                "wavpack": "wavpack",
                "musepack": "musepack",
                "asf": "wma",
                "aiff": "aiff",
                "dsf": "dsf",
                "dsdiff": "dff",
                "wave": "wav",
            }
            for key, codec in codec_map.items():
                if key in type_name:
                    result["codec"] = codec
                    break

        # Tags via EasyID3/EasyMP4Tags/etc. interface
        if hasattr(audio, "tags") and audio.tags is not None:
            for tag_key, result_key in (
                ("title", "tag_title"),
                ("artist", "tag_artist"),
                ("album", "tag_album"),
            ):
                val = audio.get(tag_key)
                if val:
                    text = val[0] if isinstance(val, list) else str(val)
                    text = text.strip().lower()
                    if text:
                        result[result_key] = text
    except Exception:
        pass
    return result


def extract_one_audio(path: Path) -> VideoMetadata | None:
    """Read audio file metadata using mutagen and return VideoMetadata.

    Returns None if the file cannot be read at all (missing, permission denied,
    unsupported format, or corrupt audio data).
    Video-specific fields (width, height, framerate) are None.
    """
    try:
        stat_result = path.stat()
        file_size = stat_result.st_size
        mtime = stat_result.st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return None

    tags = _extract_tags(path)

    return VideoMetadata(
        path=path,
        filename=path.stem,
        duration=tags.get("duration"),  # type: ignore[arg-type]
        width=None,
        height=None,
        codec=tags.get("codec"),  # type: ignore[arg-type]
        bitrate=tags.get("bitrate"),  # type: ignore[arg-type]
        framerate=None,
        audio_channels=tags.get("audio_channels"),  # type: ignore[arg-type]
        file_size=file_size,
        mtime=mtime,
        tag_title=tags.get("tag_title"),  # type: ignore[arg-type]
        tag_artist=tags.get("tag_artist"),  # type: ignore[arg-type]
        tag_album=tags.get("tag_album"),  # type: ignore[arg-type]
    )


def extract_all_audio(
    files: list[Path],
    *,
    workers: int = 0,
    verbose: bool = False,
    cache: MetadataCache | None = None,
    cache_db: CacheDB | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract metadata from audio files in parallel.

    Uses mutagen instead of ffprobe — does NOT require ffprobe/ffmpeg.
    Same interface as extract_all() but with audio-appropriate cache
    skip conditions.
    """
    return _extract_all_generic(
        files,
        extract_fn=extract_one_audio,
        cache_fields=_AUDIO_CACHE_FIELDS,
        cache_skip_fn=lambda m: (
            m.duration is None and m.tag_title is None and m.tag_artist is None and m.tag_album is None
        ),
        task_label="Extracting audio metadata",
        workers=workers,
        verbose=verbose,
        cache=cache,
        cache_db=cache_db,
        quiet=quiet,
        progress_emitter=progress_emitter,
    )


# ---------------------------------------------------------------------------
# Document extraction
# ---------------------------------------------------------------------------


_PDF_DATE_RE = re.compile(
    r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
    r"(?:([+-])(\d{2})'(\d{2})'?|Z)?",
)


def _normalize_pdf_date(raw: str) -> str | None:
    """Convert a PDF date string to ISO 8601.

    PDF dates look like ``D:20240101120000+05'30'`` or ``D:20240101120000Z``.
    Returns ``None`` if the string doesn't match the expected format.
    """
    m = _PDF_DATE_RE.search(raw)
    if m is None:
        return None
    year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
    sign, tz_h, tz_m = m.group(7), m.group(8), m.group(9)
    iso = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
    if sign and tz_h and tz_m:
        iso += f"{sign}{tz_h}:{tz_m}"
    elif "Z" in raw[m.start() : m.end() + 2]:
        iso += "+00:00"
    return iso


_PDF_HEADER = b"%PDF"

# Regexes for lightweight PDF trailer parsing — compiled once.
_RE_PAGE_COUNT = re.compile(rb"/Count\s+(\d+)")
_RE_PDF_STRING = re.compile(rb"\(([^)]*)\)")
_RE_HEX_STRING = re.compile(rb"<([0-9a-fA-F]+)>")


def _pdf_decode_string(raw: bytes) -> str | None:
    """Decode a PDF string value (literal or hex) to Python str."""
    # Try BOM-marked UTF-16BE first
    if raw[:2] == b"\xfe\xff":
        try:
            return raw.decode("utf-16-be")
        except Exception:
            pass
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _pdf_extract_string(data: bytes, key: bytes) -> str | None:
    """Find ``/Key (value)`` or ``/Key <hex>`` in raw PDF bytes."""
    idx = data.find(key)
    if idx == -1:
        return None
    after = data[idx + len(key) : idx + len(key) + 512]
    # Literal string: (...)
    m = _RE_PDF_STRING.search(after)
    if m:
        return _pdf_decode_string(m.group(1))
    # Hex string: <...>
    m = _RE_HEX_STRING.search(after)
    if m:
        try:
            raw = bytes.fromhex(m.group(1).decode("ascii"))
            return _pdf_decode_string(raw)
        except Exception:
            pass
    return None


_PDF_RAW_READ_LIMIT = 2 * 1024 * 1024  # 2 MB — read whole file up to this size


def _extract_pdf_metadata_raw(path: Path) -> dict[str, int | str | None]:
    """Lightweight fallback: extract PDF metadata from raw bytes.

    Reads at most 2 MB (small files) or head+tail 32 KB (large files).
    Finds ``/Count``, ``/Title``, ``/Author``, ``/CreationDate`` via regex.
    Less accurate than a real parser (~70% page-count hit rate) but
    guaranteed fast — no library, no recovery scans, no GIL stalls.
    """
    result: dict[str, int | str | None] = {
        "page_count": None,
        "doc_title": None,
        "doc_author": None,
        "doc_created": None,
    }
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            if file_size <= _PDF_RAW_READ_LIMIT:
                fh.seek(0)
                data = fh.read()
            else:
                chunk = 32768
                fh.seek(0)
                head = fh.read(chunk)
                fh.seek(-min(file_size, chunk), 2)
                data = head + fh.read()

            m = _RE_PAGE_COUNT.search(data)
            if m:
                result["page_count"] = int(m.group(1))
            for key_bytes, result_key, is_date in (
                (b"/Title", "doc_title", False),
                (b"/Author", "doc_author", False),
                (b"/CreationDate", "doc_created", True),
            ):
                val = _pdf_extract_string(data, key_bytes)
                if val:
                    val = val.strip()
                    if is_date:
                        normalized = _normalize_pdf_date(val)
                        result[result_key] = normalized if normalized is not None else val
                    elif val:
                        result[result_key] = val.lower()
    except Exception:
        pass
    return result


def _extract_pdf_metadata(path: Path) -> dict[str, int | str | None]:
    """Extract page count, title, author and creation date from a PDF.

    Two-tier strategy for speed + accuracy:

    1. **Header check** — rejects misnamed ``.pdf`` files instantly (reads
       4 bytes).
    2. **pypdf with ``strict=True``** — parses xref/catalog properly for
       accurate page counts and full Unicode metadata.  ``strict=True``
       raises immediately on corrupt structures instead of attempting
       expensive whole-file recovery scans.
    3. **Raw fallback** — on any pypdf error, falls back to regex-based
       extraction from raw bytes (fast but ~70% page-count accuracy).

    Never raises.  Returns a dict with keys ``page_count``, ``doc_title``,
    ``doc_author``, ``doc_created`` (all may be ``None``).
    """
    result: dict[str, int | str | None] = {
        "page_count": None,
        "doc_title": None,
        "doc_author": None,
        "doc_created": None,
    }
    try:
        with open(path, "rb") as fh:
            if not fh.read(len(_PDF_HEADER)).startswith(_PDF_HEADER):
                return result
    except Exception:
        return result

    # Tier 1: pypdf strict mode (fast + accurate for well-formed PDFs).
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]

        reader = PdfReader(path, strict=True)

        try:
            result["page_count"] = len(reader.pages)
        except Exception:
            pass

        meta = reader.metadata
        if meta is not None:
            for attr, result_key in (("title", "doc_title"), ("author", "doc_author")):
                val = getattr(meta, attr, None)
                if val is not None:
                    text = str(val).strip().lower()
                    if text:
                        result[result_key] = text
            created = getattr(meta, "creation_date", None)
            if created is not None:
                try:
                    result["doc_created"] = created.isoformat()
                except Exception:
                    result["doc_created"] = str(created)
        return result
    except Exception:
        pass

    # Tier 2: raw byte-level extraction (fallback for corrupt/unusual PDFs).
    return _extract_pdf_metadata_raw(path)


def _extract_docx(path: Path) -> tuple[str | None, int, str | None, str | None, str | None]:
    """Extract metadata from a .docx file — lightweight, no python-docx.

    Opens the ``.docx`` ZIP directly:
    - ``docProps/core.xml`` (tiny) → title, author, created
    - ``word/document.xml`` → count ``<w:p>`` tags via SAX (streaming, no DOM)

    Returns ``(text_content, page_count, doc_title, doc_author, doc_created)``.
    ``text_content`` is always ``None`` — deferred to content-hash / scoring.
    ``page_count`` is estimated as ``paragraph_count // 4`` (min 1).
    Raises on failure (caller catches).
    """
    import xml.etree.ElementTree as ET
    import zipfile

    title: str | None = None
    author: str | None = None
    created: str | None = None
    para_count = 0

    with zipfile.ZipFile(str(path), "r") as zf:
        # --- Core properties (title, author, created) ---
        if "docProps/core.xml" in zf.namelist():
            with zf.open("docProps/core.xml") as core_f:
                tree = ET.parse(core_f)
                root = tree.getroot()
                # Dublin Core + cp namespaces
                ns = {
                    "dc": "http://purl.org/dc/elements/1.1/",
                    "dcterms": "http://purl.org/dc/terms/",
                    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                }
                el = root.find("dc:title", ns)
                if el is not None and el.text:
                    title = el.text.strip().lower() or None
                el = root.find("dc:creator", ns)
                if el is not None and el.text:
                    author = el.text.strip().lower() or None
                el = root.find("dcterms:created", ns)
                if el is not None and el.text:
                    created = el.text.strip()

        # --- Paragraph count via streaming parse ---
        if "word/document.xml" in zf.namelist():
            with zf.open("word/document.xml") as doc_f:
                _WP_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
                for _event, elem in ET.iterparse(doc_f, events=("end",)):
                    if elem.tag == _WP_TAG:
                        para_count += 1
                        elem.clear()  # free memory immediately

    page_count = max(1, para_count // 4)
    return None, page_count, title, author, created


def extract_one_document(path: Path) -> VideoMetadata | None:
    """Read document metadata and text content and return VideoMetadata.

    Supports .pdf, .docx, .txt, .md extensions.
    Returns None if the file cannot be read at all.
    """
    try:
        stat_result = path.stat()
        file_size = stat_result.st_size
        mtime = stat_result.st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return None

    suffix = path.suffix.lower()
    text_content: str | None = None
    page_count: int | None = None
    doc_title: str | None = None
    doc_author: str | None = None
    doc_created: str | None = None

    try:
        if suffix == ".pdf":
            meta = _extract_pdf_metadata(path)
            page_count = meta.get("page_count")  # type: ignore[assignment]
            doc_title = meta.get("doc_title")  # type: ignore[assignment]
            doc_author = meta.get("doc_author")  # type: ignore[assignment]
            doc_created = meta.get("doc_created")  # type: ignore[assignment]
        elif suffix == ".docx":
            _, page_count, doc_title, doc_author, doc_created = _extract_docx(path)
        elif suffix in (".txt", ".md"):
            # Count lines without reading entire file into memory
            newlines = 0
            last_byte = b""
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    newlines += chunk.count(b"\n")
                    last_byte = chunk[-1:] if chunk else last_byte
            # Files not ending with \n still have a final line
            page_count = newlines + (1 if last_byte and last_byte != b"\n" else 0)
        else:
            return None
    except Exception:
        return None

    return VideoMetadata(
        path=path,
        filename=path.stem,
        duration=None,
        width=None,
        height=None,
        file_size=file_size,
        mtime=mtime,
        page_count=page_count,
        doc_title=doc_title,
        doc_author=doc_author,
        doc_created=doc_created,
        text_content=text_content,
    )


def _extract_text_only(path: Path) -> str | None:
    """Re-extract text content from a document file (no metadata).

    Used to rehydrate ``text_content`` for cache-hit documents when
    ``--content-method tfidf`` is active (text is transient, not cached).
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pdfminer.high_level import extract_text  # type: ignore[import-untyped]

            return extract_text(str(path))
        if suffix == ".docx":
            import docx  # type: ignore[import-untyped]

            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        if suffix in (".txt", ".md"):
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return None


def extract_all_documents(
    files: list[Path],
    *,
    workers: int = 0,
    verbose: bool = False,
    cache: MetadataCache | None = None,
    cache_db: CacheDB | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract metadata from document files in parallel.

    Uses pypdf/python-docx/stdlib — does NOT require ffprobe/ffmpeg.
    Same interface as extract_all() but with document-appropriate cache
    skip conditions.
    """
    return _extract_all_generic(
        files,
        extract_fn=extract_one_document,
        cache_fields=_DOCUMENT_CACHE_FIELDS,
        cache_skip_fn=lambda m: m.page_count is None and m.doc_title is None and m.doc_author is None,
        task_label="Extracting document metadata",
        workers=workers,
        verbose=verbose,
        cache=cache,
        cache_db=cache_db,
        quiet=quiet,
        progress_emitter=progress_emitter,
    )


# ---------------------------------------------------------------------------
# Per-file cache-aware worker (for async pipeline / ThreadPoolExecutor)
# ---------------------------------------------------------------------------


def _extract_one_with_cache(
    path: Path,
    cache_db: CacheDB | None,
    mode: str = "video",
    *,
    defer_cache_write: bool = False,
) -> VideoMetadata | None:
    """Extract metadata for one file, using CacheDB if available.

    Combines stat() + cache lookup + extract + cache store in one call,
    suitable for ThreadPoolExecutor workers.

    When *defer_cache_write* is True, the cache store is skipped — the
    caller is responsible for batching writes via ``put_metadata_batch``.
    """
    try:
        st = path.stat()
    except OSError:
        return None

    file_size = st.st_size
    mtime = st.st_mtime

    # Try cache first
    if cache_db is not None:
        cached = cache_db.get_metadata(path, file_size=file_size, mtime=mtime)
        if cached is not None:
            return VideoMetadata(
                path=path,
                filename=path.stem,
                file_size=file_size,
                mtime=mtime,
                duration=cached.get("duration"),
                width=cached.get("width"),
                height=cached.get("height"),
                codec=cached.get("codec"),
                bitrate=cached.get("bitrate"),
                framerate=cached.get("framerate"),
                audio_channels=cached.get("audio_channels"),
                exif_datetime=cached.get("exif_datetime"),
                exif_camera=cached.get("exif_camera"),
                exif_lens=cached.get("exif_lens"),
                exif_gps_lat=cached.get("exif_gps_lat"),
                exif_gps_lon=cached.get("exif_gps_lon"),
                exif_width=cached.get("exif_width"),
                exif_height=cached.get("exif_height"),
                tag_title=cached.get("tag_title"),
                tag_artist=cached.get("tag_artist"),
                tag_album=cached.get("tag_album"),
                page_count=cached.get("page_count"),
                doc_title=cached.get("doc_title"),
                doc_author=cached.get("doc_author"),
                doc_created=cached.get("doc_created"),
            )

    # Cache miss — do actual extraction
    from duplicates_detector.config import Mode  # lazy import to avoid circular dependency

    if mode == Mode.IMAGE:
        result = extract_one_image(path)
    elif mode == Mode.AUDIO:
        result = extract_one_audio(path)
    elif mode == Mode.DOCUMENT:
        result = extract_one_document(path)
    else:
        result = extract_one(path)

    if result is None:
        return None

    # Store in cache (unless deferred for batch writes)
    if cache_db is not None and not defer_cache_write:
        _cache_store_metadata(cache_db, path, result, file_size=file_size, mtime=mtime)

    return result


def _metadata_to_cache_dict(result: VideoMetadata) -> dict[str, float | int | str | None]:
    """Build the cache dict from a VideoMetadata instance."""
    return {
        "duration": result.duration,
        "width": result.width,
        "height": result.height,
        "codec": result.codec,
        "bitrate": result.bitrate,
        "framerate": result.framerate,
        "audio_channels": result.audio_channels,
        "exif_datetime": result.exif_datetime,
        "exif_camera": result.exif_camera,
        "exif_lens": result.exif_lens,
        "exif_gps_lat": result.exif_gps_lat,
        "exif_gps_lon": result.exif_gps_lon,
        "exif_width": result.exif_width,
        "exif_height": result.exif_height,
        "tag_title": result.tag_title,
        "tag_artist": result.tag_artist,
        "tag_album": result.tag_album,
        "page_count": result.page_count,
        "doc_title": result.doc_title,
        "doc_author": result.doc_author,
        "doc_created": result.doc_created,
    }


def _cache_store_metadata(
    cache_db: CacheDB, path: Path, result: VideoMetadata, *, file_size: int, mtime: float
) -> None:
    """Store a single metadata result in the cache."""
    cache_db.put_metadata(path, _metadata_to_cache_dict(result), file_size=file_size, mtime=mtime)
