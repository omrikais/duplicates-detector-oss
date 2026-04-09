from __future__ import annotations

import math
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from duplicates_detector.metadata import VideoMetadata

# Patterns stripped from filenames before comparison
_QUALITY_MARKERS = re.compile(
    r"""
    \b(
        \d{3,4}p                             # 720p, 1080p, 2160p
        | [xh]\.?264                         # x264, h.264, h264
        | [xh]\.?265                         # x265, h.265, h265
        | hevc | avc
        | bluray | blu-ray | bdrip | brrip
        | webrip | web-dl | webdl | hdrip
        | dvdrip | dvdscr
        | hdtv | pdtv | sdtv
        | remux
        | 10bit | 8bit
        | hdr | hdr10 | dv
        | aac | ac3 | dts | flac | mp3 | atmos
        | 5\.1 | 7\.1 | 2\.0
        | proper | repack
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SEPARATORS = re.compile(r"[.\-_\[\](){}]+")
_NON_DIGIT = re.compile(r"\D")
_DIGIT_RUN = re.compile(r"\d+")


def _is_numeric_id(normalized: str) -> bool:
    """Check if a normalized filename is primarily numeric (likely an auto-generated ID).

    Filenames from messaging apps (Telegram, WhatsApp) are mostly digits —
    fuzzy string matching unreliably reports high similarity even when the
    IDs are completely different.
    """
    chars = normalized.replace(" ", "")
    if not chars:
        return False
    digit_count = sum(1 for c in chars if c.isdigit())
    return digit_count / len(chars) > 0.5


class Comparator(ABC):
    """Base class for pairwise video comparators."""

    name: str
    weight: float  # max contribution to total score (points out of 100)

    @abstractmethod
    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        """Return similarity between 0.0 (no match) and 1.0 (perfect match).

        Return None when metadata is missing and comparison is impossible.
        """


def normalize_filename(filename: str) -> str:
    """Strip quality markers and normalize a filename for comparison."""
    cleaned = _QUALITY_MARKERS.sub(" ", filename)
    cleaned = _SEPARATORS.sub(" ", cleaned)
    return " ".join(cleaned.lower().split())


def _weighted_average(parts: list[tuple[float, float]]) -> float | None:
    """Compute redistributed weighted average of (sub_weight, sub_score) pairs.

    Returns None when no sub-fields have data on both sides.
    """
    if not parts:
        return None
    total_weight = sum(w for w, _ in parts)
    return sum(w / total_weight * s for w, s in parts)


class FileNameComparator(Comparator):
    """Compare filenames after stripping quality markers and normalizing."""

    name = "filename"
    weight = 35.0

    def __init__(self) -> None:
        self._normalized_cache: dict[str, str] = {}

    def set_normalized_cache(self, cache: dict[str, str]) -> None:
        """Pre-populate normalized filename cache to avoid per-pair recomputation."""
        self._normalized_cache = cache

    def _normalize(self, filename: str) -> str:
        """Return cached normalized filename, computing on miss."""
        cached = self._normalized_cache.get(filename)
        if cached is not None:
            return cached
        result = normalize_filename(filename)
        self._normalized_cache[filename] = result
        return result

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        na = self._normalize(a.filename)
        nb = self._normalize(b.filename)
        if not na or not nb:
            return 0.0
        # Numeric ID filenames (e.g. Telegram/WhatsApp): small character
        # differences represent entirely different files, so require exact
        # digit match instead of fuzzy comparison.
        if _is_numeric_id(na) and _is_numeric_id(nb):
            if _NON_DIGIT.sub("", na) != _NON_DIGIT.sub("", nb):
                return 0.0
        # Numbered series: identical text skeleton but different numbers
        # means different entries (e.g. "# 94 Russia Moscow" vs
        # "# 423 Russia Moscow", or "Movie Part 1" vs "Movie Part 2").
        text_a = " ".join(_DIGIT_RUN.sub("", na).split())
        text_b = " ".join(_DIGIT_RUN.sub("", nb).split())
        if text_a and text_a == text_b:
            if _DIGIT_RUN.findall(na) != _DIGIT_RUN.findall(nb):
                return 0.0
        ratio = fuzz.token_sort_ratio(na, nb) / 100.0

        # Distinct content words: if each filename has a unique alphabetic
        # word (≥3 chars) not present in the other, they describe different
        # content — e.g. "Mexico Guadalupe" vs "Mexico Izamal".
        # Only apply when the fuzzy score is moderate; high similarity
        # overrides this to handle compound-word splits ("Endgame" vs
        # "End Game") safely.
        if ratio < 0.85:
            tokens_a = set(na.split())
            tokens_b = set(nb.split())
            unique_a = tokens_a - tokens_b
            unique_b = tokens_b - tokens_a
            has_word_a = any(len(t) >= 3 and t.isalpha() for t in unique_a)
            has_word_b = any(len(t) >= 3 and t.isalpha() for t in unique_b)
            if has_word_a and has_word_b:
                return 0.0

        return ratio


class DurationComparator(Comparator):
    """Compare video durations. Linear falloff within MAX_DIFF seconds."""

    name = "duration"
    weight = 35.0
    MAX_DIFF: float = 5.0

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        if a.duration is None or b.duration is None:
            return None
        diff = abs(a.duration - b.duration)
        if diff >= self.MAX_DIFF:
            return 0.0
        return 1.0 - (diff / self.MAX_DIFF)


class ResolutionComparator(Comparator):
    """Compare video resolutions by total pixel count ratio."""

    name = "resolution"
    weight = 15.0

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        if a.width is None or b.width is None or a.height is None or b.height is None:
            return None
        pixels_a = a.width * a.height
        pixels_b = b.width * b.height
        if pixels_a == 0 or pixels_b == 0:
            return 0.0
        return min(pixels_a, pixels_b) / max(pixels_a, pixels_b)


class FileSizeComparator(Comparator):
    """Compare file sizes by byte ratio."""

    name = "file_size"
    weight = 15.0

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        if a.file_size == 0 or b.file_size == 0:
            return 0.0
        return min(a.file_size, b.file_size) / max(a.file_size, b.file_size)


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in meters between two GPS points."""
    r = 6_371_000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class ExifComparator(Comparator):
    """Compare images by EXIF metadata similarity (datetime, camera, lens, GPS, dimensions)."""

    name = "exif"
    weight = 40.0

    # Sub-field weights (must sum to 1.0)
    _SUB_WEIGHTS: dict[str, float] = {
        "datetime": 0.35,
        "camera": 0.20,
        "lens": 0.10,
        "gps": 0.25,
        "dimensions": 0.10,
    }

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        parts: list[tuple[float, float]] = []  # (sub_weight, sub_score)

        # DateTime: linear falloff over 1 hour
        if a.exif_datetime is not None and b.exif_datetime is not None:
            diff = abs(a.exif_datetime - b.exif_datetime)
            parts.append((self._SUB_WEIGHTS["datetime"], max(0.0, 1.0 - diff / 3600.0)))

        # Camera: exact match
        if a.exif_camera is not None and b.exif_camera is not None:
            parts.append((self._SUB_WEIGHTS["camera"], 1.0 if a.exif_camera == b.exif_camera else 0.0))

        # Lens: exact match
        if a.exif_lens is not None and b.exif_lens is not None:
            parts.append((self._SUB_WEIGHTS["lens"], 1.0 if a.exif_lens == b.exif_lens else 0.0))

        # GPS: haversine distance, linear falloff over 1km
        if (
            a.exif_gps_lat is not None
            and a.exif_gps_lon is not None
            and b.exif_gps_lat is not None
            and b.exif_gps_lon is not None
        ):
            dist = _haversine_meters(a.exif_gps_lat, a.exif_gps_lon, b.exif_gps_lat, b.exif_gps_lon)
            parts.append((self._SUB_WEIGHTS["gps"], max(0.0, 1.0 - dist / 1000.0)))

        # Dimensions: EXIF dims match actual dims for both files
        if (
            a.exif_width is not None
            and a.exif_height is not None
            and b.exif_width is not None
            and b.exif_height is not None
            and a.width is not None
            and a.height is not None
            and b.width is not None
            and b.height is not None
        ):
            a_match = a.exif_width == a.width and a.exif_height == a.height
            b_match = b.exif_width == b.width and b.exif_height == b.height
            cross_match = a.exif_width == b.exif_width and a.exif_height == b.exif_height
            parts.append((self._SUB_WEIGHTS["dimensions"], 1.0 if (a_match and b_match and cross_match) else 0.0))

        return _weighted_average(parts)


class ContentComparator(Comparator):
    """Compare videos by perceptual hash similarity."""

    name = "content"
    weight = 40.0

    def __init__(self, *, rotation_invariant: bool = False, is_document: bool = False) -> None:
        self._rotation_invariant = rotation_invariant
        self._is_document = is_document
        self._tfidf_matrix: Any = None
        self._tfidf_index_map: dict[Path, int] | None = None

    def set_tfidf_data(self, matrix: Any, index_map: dict[Path, int]) -> None:
        """Attach a pre-built TF-IDF matrix and path-to-row-index mapping.

        Called by the scorer when ``--content-method tfidf`` is active.
        The matrix is a scipy sparse matrix; *index_map* maps each file
        path to its row index.
        """
        self._tfidf_matrix = matrix
        self._tfidf_index_map = index_map

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        # TF-IDF pairwise: uses pre-built matrix for cosine similarity lookup
        if self._tfidf_matrix is not None and self._tfidf_index_map is not None:
            idx_a = self._tfidf_index_map.get(a.path)
            idx_b = self._tfidf_index_map.get(b.path)
            if idx_a is not None and idx_b is not None:
                from duplicates_detector.tfidf import compare_tfidf

                return compare_tfidf(self._tfidf_matrix, idx_a, idx_b)
            return None
        if self._is_document and a.content_hash is not None and b.content_hash is not None:
            from duplicates_detector.content import compare_simhash

            return compare_simhash(a.content_hash, b.content_hash)
        if a.clip_embedding is not None and b.clip_embedding is not None:
            from duplicates_detector.clip import compare_clip_embeddings

            return compare_clip_embeddings(a.clip_embedding, b.clip_embedding)
        if a.content_frames is not None and b.content_frames is not None:
            from duplicates_detector.content import compare_ssim_frames

            return compare_ssim_frames(a.content_frames, b.content_frames)
        if a.content_hash is not None and b.content_hash is not None:
            from duplicates_detector.content import compare_content_hashes

            return compare_content_hashes(
                a.content_hash,
                b.content_hash,
                rotation_invariant=self._rotation_invariant,
            )
        return None


class AudioComparator(Comparator):
    """Compare videos by Chromaprint audio fingerprint similarity."""

    name = "audio"
    weight = 30.0

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        if a.audio_fingerprint is None or b.audio_fingerprint is None:
            return None
        from duplicates_detector.audio import compare_audio_fingerprints

        return compare_audio_fingerprints(a.audio_fingerprint, b.audio_fingerprint)


def _build_comparators(
    specs: list[tuple[type[Comparator], float]],
    *,
    rotation_invariant: bool = False,
    is_document: bool = False,
) -> list[Comparator]:
    """Instantiate comparators from a (class, weight) spec list.

    ContentComparator receives the rotation_invariant and is_document kwargs;
    all other classes are constructed with no arguments.
    """
    comps: list[Comparator] = []
    for cls, weight in specs:
        if cls is ContentComparator:
            comp = cls(rotation_invariant=rotation_invariant, is_document=is_document)
        else:
            comp = cls()
        comp.weight = weight
        comps.append(comp)
    return comps


def get_default_comparators() -> list[Comparator]:
    """Return the default set of comparators."""
    return _build_comparators(
        [
            (FileNameComparator, 35.0),
            (DurationComparator, 35.0),
            (ResolutionComparator, 15.0),
            (FileSizeComparator, 15.0),
            (DirectoryComparator, 0.0),
        ]
    )


def get_content_comparators(*, rotation_invariant: bool = False) -> list[Comparator]:
    """Return comparators including ContentComparator with adjusted weights."""
    return _build_comparators(
        [
            (FileNameComparator, 20.0),
            (DurationComparator, 20.0),
            (ResolutionComparator, 10.0),
            (FileSizeComparator, 10.0),
            (ContentComparator, 40.0),
            (DirectoryComparator, 0.0),
        ],
        rotation_invariant=rotation_invariant,
    )


# ---------------------------------------------------------------------------
# Configurable weights
# ---------------------------------------------------------------------------

# Maps CLI/config keys to internal comparator names.
# Both "filesize" and "file_size" are accepted.
_WEIGHT_KEY_MAP: dict[str, str] = {
    "filename": "filename",
    "duration": "duration",
    "resolution": "resolution",
    "filesize": "file_size",
    "file_size": "file_size",
    "content": "content",
    "exif": "exif",
    "audio": "audio",
    "tags": "tags",
    "directory": "directory",
    "page_count": "page_count",
    "doc_meta": "doc_meta",
}

_DEFAULT_KEYS = {"filename", "duration", "resolution", "filesize", "directory"}
_CONTENT_KEYS = _DEFAULT_KEYS | {"content"}

_IMAGE_DEFAULT_KEYS = {"filename", "resolution", "filesize", "exif", "directory"}
_IMAGE_CONTENT_KEYS = _IMAGE_DEFAULT_KEYS | {"content"}

_AUDIO_DEFAULT_KEYS = {"filename", "duration", "resolution", "filesize", "audio", "directory"}
_AUDIO_CONTENT_KEYS = _AUDIO_DEFAULT_KEYS | {"content"}

_AUDIO_MODE_DEFAULT_KEYS = {"filename", "duration", "tags", "directory"}
_AUDIO_MODE_FINGERPRINT_KEYS = _AUDIO_MODE_DEFAULT_KEYS | {"audio"}

_DOCUMENT_DEFAULT_KEYS = {"filename", "filesize", "page_count", "doc_meta", "directory"}
_DOCUMENT_CONTENT_KEYS = _DOCUMENT_DEFAULT_KEYS | {"content"}


def parse_weights(spec: str) -> dict[str, float]:
    """Parse a comma-separated ``key=value`` weight specification.

    Returns a dict mapping canonical comparator names to weights.
    Accepts both ``filesize`` and ``file_size`` as keys.

    Raises ``ValueError`` on invalid format, unknown keys, negative values,
    or duplicate keys.
    """
    result: dict[str, float] = {}
    seen_canonical: set[str] = set()

    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"invalid weight format (expected key=value): {part!r}")
        key_str, val_str = part.split("=", 1)
        key_str = key_str.strip().lower()
        val_str = val_str.strip()

        if key_str not in _WEIGHT_KEY_MAP:
            raise ValueError(f"unknown weight key: {key_str!r}")

        canonical = _WEIGHT_KEY_MAP[key_str]
        if canonical in seen_canonical:
            raise ValueError(f"duplicate weight key: {key_str!r}")
        seen_canonical.add(canonical)

        try:
            value = float(val_str)
        except ValueError:
            raise ValueError(f"invalid weight value for {key_str!r}: {val_str!r}")

        if not math.isfinite(value):
            raise ValueError(f"weight for {key_str!r} must be a finite number, got {value}")
        if value < 0:
            raise ValueError(f"weight for {key_str!r} must be non-negative, got {value}")

        result[canonical] = value

    return result


def _apply_weights(comps: list[Comparator], weights: dict[str, float]) -> list[Comparator]:
    """Apply custom weights to comparators in-place and return the list.

    When the directory comparator has weight > 0, total weights are
    renormalized to sum to 100 so existing comparator ratios are preserved.
    """
    for comp in comps:
        if comp.name in weights:
            comp.weight = weights[comp.name]
    # Renormalize when directory weight is active (non-zero)
    dir_comp = next((c for c in comps if c.name == "directory"), None)
    if dir_comp is not None and dir_comp.weight > 0:
        total = sum(c.weight for c in comps if c.weight > 0)
        if total > 0 and total != 100.0:
            factor = 100.0 / total
            for c in comps:
                c.weight *= factor
    return comps


def get_weighted_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create default comparators with custom weights applied."""
    return _apply_weights(get_default_comparators(), weights)


def get_weighted_content_comparators(
    weights: dict[str, float], *, rotation_invariant: bool = False
) -> list[Comparator]:
    """Create content comparators with custom weights applied."""
    return _apply_weights(get_content_comparators(rotation_invariant=rotation_invariant), weights)


# ---------------------------------------------------------------------------
# Image mode comparators
# ---------------------------------------------------------------------------


def get_image_comparators() -> list[Comparator]:
    """Return the default set of comparators for image mode (no duration)."""
    return _build_comparators(
        [
            (FileNameComparator, 25.0),
            (ResolutionComparator, 20.0),
            (FileSizeComparator, 15.0),
            (ExifComparator, 40.0),
            (DirectoryComparator, 0.0),
        ]
    )


def get_image_content_comparators(*, rotation_invariant: bool = False) -> list[Comparator]:
    """Return image comparators including ContentComparator."""
    return _build_comparators(
        [
            (FileNameComparator, 15.0),
            (ResolutionComparator, 10.0),
            (FileSizeComparator, 10.0),
            (ExifComparator, 25.0),
            (ContentComparator, 40.0),
            (DirectoryComparator, 0.0),
        ],
        rotation_invariant=rotation_invariant,
    )


def get_weighted_image_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create image comparators with custom weights applied."""
    return _apply_weights(get_image_comparators(), weights)


def get_weighted_image_content_comparators(
    weights: dict[str, float], *, rotation_invariant: bool = False
) -> list[Comparator]:
    """Create image content comparators with custom weights applied."""
    comps = get_image_content_comparators(rotation_invariant=rotation_invariant)
    return _apply_weights(comps, weights)


# ---------------------------------------------------------------------------
# Audio mode comparators (video + audio fingerprint)
# ---------------------------------------------------------------------------


def get_audio_comparators() -> list[Comparator]:
    """Return comparators for video mode with audio fingerprinting."""
    return _build_comparators(
        [
            (FileNameComparator, 25.0),
            (DurationComparator, 25.0),
            (ResolutionComparator, 10.0),
            (FileSizeComparator, 10.0),
            (AudioComparator, 30.0),
            (DirectoryComparator, 0.0),
        ]
    )


def get_audio_content_comparators(*, rotation_invariant: bool = False) -> list[Comparator]:
    """Return comparators for video mode with audio + visual content hashing."""
    return _build_comparators(
        [
            (FileNameComparator, 15.0),
            (DurationComparator, 15.0),
            (ResolutionComparator, 10.0),
            (FileSizeComparator, 10.0),
            (AudioComparator, 10.0),
            (ContentComparator, 40.0),
            (DirectoryComparator, 0.0),
        ],
        rotation_invariant=rotation_invariant,
    )


def get_weighted_audio_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create audio comparators with custom weights applied."""
    return _apply_weights(get_audio_comparators(), weights)


def get_weighted_audio_content_comparators(
    weights: dict[str, float], *, rotation_invariant: bool = False
) -> list[Comparator]:
    """Create audio + content comparators with custom weights applied."""
    comps = get_audio_content_comparators(rotation_invariant=rotation_invariant)
    return _apply_weights(comps, weights)


# ---------------------------------------------------------------------------
# Audio file mode comparators (--mode audio)
# ---------------------------------------------------------------------------


class TagComparator(Comparator):
    """Compare audio files by ID3/tag metadata similarity (title, artist, album).

    Modeled after ExifComparator: sub-weights are redistributed when some
    tag fields are unavailable on both files.  Returns None when no sub-fields
    have data on both sides.
    """

    name = "tags"
    weight = 40.0

    # Sub-field weights (must sum to 1.0)
    _SUB_WEIGHTS: dict[str, float] = {
        "title": 0.45,
        "artist": 0.35,
        "album": 0.20,
    }

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        parts: list[tuple[float, float]] = []  # (sub_weight, sub_score)

        # Title: fuzzy match
        if a.tag_title is not None and b.tag_title is not None:
            ratio = fuzz.ratio(a.tag_title, b.tag_title) / 100.0
            parts.append((self._SUB_WEIGHTS["title"], ratio))

        # Artist: fuzzy match
        if a.tag_artist is not None and b.tag_artist is not None:
            ratio = fuzz.ratio(a.tag_artist, b.tag_artist) / 100.0
            parts.append((self._SUB_WEIGHTS["artist"], ratio))

        # Album: fuzzy match
        if a.tag_album is not None and b.tag_album is not None:
            ratio = fuzz.ratio(a.tag_album, b.tag_album) / 100.0
            parts.append((self._SUB_WEIGHTS["album"], ratio))

        return _weighted_average(parts)


class DirectoryComparator(Comparator):
    """Compare files by directory proximity.

    Same directory → 1.0, one level apart → 0.8, five+ levels → 0.0.
    Opt-in only (default weight 0).
    """

    name = "directory"
    weight = 0.0  # opt-in only

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float:
        if a.path.parent == b.path.parent:
            return 1.0
        try:
            common = Path(os.path.commonpath([a.path.parent, b.path.parent]))
            if common == common.parent:
                # Filesystem root (/ on POSIX, C:\ on Windows) is not meaningful shared hierarchy
                return 0.0
            depth_a = len(a.path.parent.relative_to(common).parts)
            depth_b = len(b.path.parent.relative_to(common).parts)
            max_depth = max(depth_a, depth_b)
            if max_depth == 0:
                return 1.0
            return max(0.0, 1.0 - (max_depth / 5.0))
        except (ValueError, TypeError):
            return 0.0


class PageCountComparator(Comparator):
    """Compare documents by page/line count similarity."""

    name = "page_count"
    weight = 15.0

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        if a.page_count is None or b.page_count is None:
            return None
        m = max(a.page_count, b.page_count)
        if m == 0:
            return None
        return 1.0 - abs(a.page_count - b.page_count) / m


class DocMetaComparator(Comparator):
    """Compare documents by metadata similarity (title, author, created date).

    Modeled after ExifComparator: sub-weights are redistributed when some
    fields are unavailable on both files.  Returns None when no sub-fields
    have data on both sides.
    """

    name = "doc_meta"
    weight = 40.0

    # Sub-field weights (must sum to 1.0)
    _SUB_WEIGHTS: dict[str, float] = {
        "title": 0.45,
        "author": 0.35,
        "created": 0.20,
    }

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float | None:
        parts: list[tuple[float, float]] = []  # (sub_weight, sub_score)

        # Title: fuzzy match
        if a.doc_title is not None and b.doc_title is not None:
            ratio = fuzz.ratio(a.doc_title, b.doc_title) / 100.0
            parts.append((self._SUB_WEIGHTS["title"], ratio))

        # Author: fuzzy match
        if a.doc_author is not None and b.doc_author is not None:
            ratio = fuzz.ratio(a.doc_author, b.doc_author) / 100.0
            parts.append((self._SUB_WEIGHTS["author"], ratio))

        # Created: date proximity — 1.0 same day, linear decay over 30 days
        if a.doc_created is not None and b.doc_created is not None:
            try:
                dt_a = datetime.fromisoformat(a.doc_created)
                dt_b = datetime.fromisoformat(b.doc_created)
                diff_days = abs((dt_a - dt_b).total_seconds()) / 86400.0
                parts.append((self._SUB_WEIGHTS["created"], max(0.0, 1.0 - diff_days / 30.0)))
            except (ValueError, TypeError):
                pass  # unparseable dates — skip this sub-field

        return _weighted_average(parts)


def get_audio_mode_comparators() -> list[Comparator]:
    """Return the default set of comparators for audio file mode (no resolution)."""
    return _build_comparators(
        [
            (FileNameComparator, 30.0),
            (DurationComparator, 30.0),
            (TagComparator, 40.0),
            (DirectoryComparator, 0.0),
        ]
    )


def get_audio_mode_fingerprint_comparators() -> list[Comparator]:
    """Return comparators for audio file mode with Chromaprint fingerprinting."""
    return _build_comparators(
        [
            (FileNameComparator, 15.0),
            (DurationComparator, 15.0),
            (TagComparator, 20.0),
            (AudioComparator, 50.0),
            (DirectoryComparator, 0.0),
        ]
    )


def get_weighted_audio_mode_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create audio-mode comparators with custom weights applied."""
    return _apply_weights(get_audio_mode_comparators(), weights)


def get_weighted_audio_mode_fingerprint_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create audio-mode fingerprint comparators with custom weights applied."""
    return _apply_weights(get_audio_mode_fingerprint_comparators(), weights)


# ---------------------------------------------------------------------------
# Document mode comparators (--mode document)
# ---------------------------------------------------------------------------


def get_document_comparators() -> list[Comparator]:
    """Return the default set of comparators for document mode."""
    return _build_comparators(
        [
            (FileNameComparator, 30.0),
            (FileSizeComparator, 15.0),
            (PageCountComparator, 15.0),
            (DocMetaComparator, 40.0),
            (DirectoryComparator, 0.0),
        ]
    )


def get_document_content_comparators() -> list[Comparator]:
    """Return document comparators including ContentComparator (SimHash)."""
    return _build_comparators(
        [
            (FileNameComparator, 15.0),
            (FileSizeComparator, 10.0),
            (PageCountComparator, 10.0),
            (DocMetaComparator, 25.0),
            (ContentComparator, 40.0),
            (DirectoryComparator, 0.0),
        ],
        is_document=True,
    )


def get_weighted_document_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create document comparators with custom weights applied."""
    return _apply_weights(get_document_comparators(), weights)


def get_weighted_document_content_comparators(weights: dict[str, float]) -> list[Comparator]:
    """Create document content comparators with custom weights applied."""
    return _apply_weights(get_document_content_comparators(), weights)
