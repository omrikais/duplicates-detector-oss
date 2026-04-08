from __future__ import annotations

from pathlib import Path

_DEFAULT_SIDECAR_EXTENSIONS = frozenset({".xmp", ".aae", ".thm", ".json"})
_LRDATA_SUFFIX = ".lrdata"


def parse_sidecar_extensions(raw: str) -> frozenset[str]:
    """Parse a comma-separated extension string into a frozenset with leading dots.

    Accepts both dotted (``.xmp,.aae``) and dotless (``xmp,aae``) forms,
    normalising each token to lowercase with a leading dot.
    """
    exts: set[str] = set()
    for token in raw.split(","):
        ext = token.strip().lower()
        if ext:
            if not ext.startswith("."):
                ext = "." + ext
            exts.add(ext)
    return frozenset(exts)


def find_sidecars(
    media_path: Path,
    *,
    extensions: frozenset[str] = _DEFAULT_SIDECAR_EXTENSIONS,
) -> list[Path]:
    """Discover sidecar files associated with *media_path*.

    Checks the same directory for:

    1. ``stem + ext``  (e.g. ``IMG_1234.xmp``)
    2. ``full_name + ext``  (e.g. ``IMG_1234.jpg.xmp``)
    3. ``stem + .lrdata/`` directory  (Lightroom sidecar data)

    For each extension, both the original case and its uppercase variant are
    probed so that e.g. ``IMG_1234.XMP`` is found on case-sensitive filesystems.
    The uppercase probe is skipped when the lowercase one already matched
    (avoids duplicates on case-insensitive macOS/Windows).

    Returns a sorted, deduplicated list of existing sidecar paths.
    """
    parent = media_path.parent
    stem = media_path.stem
    full_name = media_path.name

    found: set[Path] = set()

    for ext in extensions:
        ext_upper = ext.upper()

        # Pattern 1: stem + ext  (e.g. IMG_1234.xmp)
        candidate = parent / (stem + ext)
        if candidate.exists() and candidate != media_path:
            found.add(candidate)
        elif ext_upper != ext:
            candidate = parent / (stem + ext_upper)
            if candidate.exists() and candidate != media_path:
                found.add(candidate)

        # Pattern 2: full_name + ext  (e.g. IMG_1234.jpg.xmp)
        candidate = parent / (full_name + ext)
        if candidate.exists() and candidate != media_path:
            found.add(candidate)
        elif ext_upper != ext:
            candidate = parent / (full_name + ext_upper)
            if candidate.exists() and candidate != media_path:
                found.add(candidate)

    # Pattern 3: stem + .lrdata/ directory (check both cases)
    lrdata = parent / (stem + _LRDATA_SUFFIX)
    if lrdata.is_dir():
        found.add(lrdata)
    else:
        lrdata_upper = parent / (stem + _LRDATA_SUFFIX.upper())
        if lrdata_upper.is_dir():
            found.add(lrdata_upper)

    return sorted(found)
