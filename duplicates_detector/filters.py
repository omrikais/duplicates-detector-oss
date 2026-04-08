from __future__ import annotations

import re

from duplicates_detector.metadata import VideoMetadata

_SIZE_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)?\s*$",
    re.IGNORECASE,
)

_UNITS: dict[str, int] = {
    "b": 1,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
}

_RESOLUTION_RE = re.compile(
    r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$",
)

_BITRATE_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(bps|kbps|mbps|gbps)?\s*$",
    re.IGNORECASE,
)

_BITRATE_UNITS: dict[str, int] = {
    "bps": 1,
    "kbps": 1_000,
    "mbps": 1_000_000,
    "gbps": 1_000_000_000,
}


def parse_size(value: str) -> int:
    """Convert a human-readable size string to bytes.

    Accepts: ``"500"``, ``"10MB"``, ``"1.5gb"``, ``"100 KB"``, ``"2TB"``.
    No suffix means bytes.  Units are case-insensitive, powers of 1024.

    Raises:
        ValueError: If *value* cannot be parsed.
    """
    m = _SIZE_RE.match(value)
    if not m:
        raise ValueError(f"Invalid size: {value!r}")
    number = float(m.group(1))
    unit = (m.group(2) or "b").lower()
    return int(number * _UNITS[unit])


_FORMAT_UNITS: list[tuple[str, int]] = [
    ("TB", 1024**4),
    ("GB", 1024**3),
    ("MB", 1024**2),
    ("KB", 1024),
    ("B", 1),
]


def format_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable size string.

    Picks the largest unit where the value divides evenly (no remainder).
    Falls back to bytes if no larger unit divides evenly.

    Examples::

        >>> format_size(10485760)
        '10MB'
        >>> format_size(1073741824)
        '1GB'
        >>> format_size(500)
        '500B'
        >>> format_size(0)
        '0B'
    """
    if size_bytes == 0:
        return "0B"
    for suffix, multiplier in _FORMAT_UNITS:
        if size_bytes % multiplier == 0:
            return f"{size_bytes // multiplier}{suffix}"
    return f"{size_bytes}B"


def format_size_human(nbytes: int | float) -> str:
    """Format byte count as a human-readable string with one decimal place.

    Unlike :func:`format_size` (designed for compact config round-tripping),
    this always picks the largest sensible unit and shows one decimal place,
    making it suitable for user-facing display.

    Examples::

        >>> format_size_human(0)
        '0.0 B'
        >>> format_size_human(500)
        '500.0 B'
        >>> format_size_human(2048)
        '2.0 KB'
        >>> format_size_human(5 * 1024 * 1024)
        '5.0 MB'
    """
    value = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def parse_resolution(value: str) -> tuple[int, int]:
    """Parse a ``'WxH'`` resolution string into ``(width, height)``.

    Accepts: ``'1920x1080'``, ``'1280X720'``, ``'3840x2160'``.
    Case-insensitive ``x`` separator.  Both must be positive integers.

    Raises:
        ValueError: If *value* cannot be parsed.
    """
    m = _RESOLUTION_RE.match(value)
    if not m:
        raise ValueError(f"Invalid resolution: {value!r} (expected WxH, e.g., 1920x1080)")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid resolution: {value!r} (width and height must be positive)")
    return (w, h)


def parse_bitrate(value: str) -> int:
    """Parse a bitrate string into bits per second.

    Accepts: ``'5000000'`` (raw bps), ``'5Mbps'``, ``'5000kbps'``, ``'500Kbps'``.
    Units are case-insensitive.  No suffix means bits/sec.
    Uses SI powers of 1000 (not 1024).

    Raises:
        ValueError: If *value* cannot be parsed.
    """
    m = _BITRATE_RE.match(value)
    if not m:
        raise ValueError(f"Invalid bitrate: {value!r}")
    number = float(m.group(1))
    unit = (m.group(2) or "bps").lower()
    return int(number * _BITRATE_UNITS[unit])


_FORMAT_BITRATE_UNITS: list[tuple[str, int]] = [
    ("Gbps", 1_000_000_000),
    ("Mbps", 1_000_000),
    ("kbps", 1_000),
    ("bps", 1),
]


def format_bitrate_value(bps: int) -> str:
    """Convert bits/sec to a human-readable bitrate string for config storage.

    Picks the largest unit that divides evenly.

    Examples::

        >>> format_bitrate_value(5_000_000)
        '5Mbps'
        >>> format_bitrate_value(1500)
        '1500bps'
    """
    if bps == 0:
        return "0bps"
    for suffix, multiplier in _FORMAT_BITRATE_UNITS:
        if bps % multiplier == 0:
            return f"{bps // multiplier}{suffix}"
    return f"{bps}bps"


def filter_metadata(
    items: list[VideoMetadata],
    *,
    min_size: int | None = None,
    max_size: int | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    min_resolution: tuple[int, int] | None = None,
    max_resolution: tuple[int, int] | None = None,
    min_bitrate: int | None = None,
    max_bitrate: int | None = None,
    codecs: frozenset[str] | None = None,
) -> list[VideoMetadata]:
    """Filter metadata by size, duration, resolution, bitrate, and/or codec.

    Files with ``None`` values for the relevant field pass through
    (are NOT excluded).  Multiple filters use AND logic.
    Resolution comparison uses pixel count (width * height).
    Codec comparison is case-insensitive.
    """
    min_pixels = min_resolution[0] * min_resolution[1] if min_resolution else None
    max_pixels = max_resolution[0] * max_resolution[1] if max_resolution else None

    result: list[VideoMetadata] = []
    for v in items:
        if min_size is not None and v.file_size < min_size:
            continue
        if max_size is not None and v.file_size > max_size:
            continue
        if min_duration is not None and v.duration is not None and v.duration < min_duration:
            continue
        if max_duration is not None and v.duration is not None and v.duration > max_duration:
            continue
        if min_pixels is not None and v.width is not None and v.height is not None:
            if v.width * v.height < min_pixels:
                continue
        if max_pixels is not None and v.width is not None and v.height is not None:
            if v.width * v.height > max_pixels:
                continue
        if min_bitrate is not None and v.bitrate is not None and v.bitrate < min_bitrate:
            continue
        if max_bitrate is not None and v.bitrate is not None and v.bitrate > max_bitrate:
            continue
        if codecs is not None and v.codec is not None and v.codec.lower() not in codecs:
            continue
        result.append(v)
    return result
