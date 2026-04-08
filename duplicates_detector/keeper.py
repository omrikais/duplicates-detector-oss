from __future__ import annotations

from collections.abc import Callable, Sequence

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair

STRATEGIES: tuple[str, ...] = (
    "newest",
    "oldest",
    "biggest",
    "smallest",
    "longest",
    "highest-res",
    "edited",
)


def pick_keep(
    pair: ScoredPair,
    strategy: str,
    *,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> str | None:
    """Determine which file in the pair to keep.

    Returns ``"a"``, ``"b"``, or ``None`` (undecidable).
    *sidecar_extensions* is forwarded to sidecar rediscovery for replay mode.
    *no_sidecars* suppresses all sidecar-aware decisions.
    """
    a = pair.file_a
    b = pair.file_b

    sc_ext = sidecar_extensions
    no_sc = no_sidecars
    match strategy:
        case "newest":
            return _compare(a.mtime, b.mtime, higher_wins=True, tie_a=a, tie_b=b, sc_ext=sc_ext, no_sc=no_sc)
        case "oldest":
            return _compare(a.mtime, b.mtime, higher_wins=False, tie_a=a, tie_b=b, sc_ext=sc_ext, no_sc=no_sc)
        case "biggest":
            if a.file_size > b.file_size:
                return "a"
            if b.file_size > a.file_size:
                return "b"
            return None
        case "smallest":
            if a.file_size < b.file_size:
                return "a"
            if b.file_size < a.file_size:
                return "b"
            return None
        case "longest":
            return _compare(a.duration, b.duration, higher_wins=True, tie_a=a, tie_b=b, sc_ext=sc_ext, no_sc=no_sc)
        case "highest-res":
            pix_a = _pixels(a.width, a.height)
            pix_b = _pixels(b.width, b.height)
            return _compare(pix_a, pix_b, higher_wins=True, tie_a=a, tie_b=b, sc_ext=sc_ext, no_sc=no_sc)
        case "edited":
            sc_a = _sidecar_count(a, sc_ext, no_sc)
            sc_b = _sidecar_count(b, sc_ext, no_sc)
            if sc_a != sc_b:
                return "a" if sc_a > sc_b else "b"
            # Fall back to newest
            return _compare(a.mtime, b.mtime, higher_wins=True, tie_a=a, tie_b=b, sc_ext=sc_ext, no_sc=no_sc)
        case _:
            raise ValueError(f"Unknown strategy: {strategy!r}")


def pick_delete(
    pair: ScoredPair,
    strategy: str,
    *,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> str | None:
    """Determine which file in the pair to delete (inverse of :func:`pick_keep`)."""
    result = pick_keep(pair, strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars)
    if result is None:
        return None
    return "b" if result == "a" else "a"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sidecar_count(
    meta: VideoMetadata,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> int:
    """Return the number of sidecars, rediscovering from filesystem if unknown.

    ``None`` means sidecars were never populated (e.g. replay mode).
    Rediscovery ensures the ``edited`` strategy works correctly after
    round-tripping through JSON.  *sidecar_extensions* (comma-separated)
    is forwarded to :func:`find_sidecars` so custom extensions survive
    replay round-trips.  When *no_sidecars* is ``True``, returns 0
    unconditionally so ``--no-sidecars`` suppresses sidecar-aware keeper
    selection as well as co-deletion.
    """
    if no_sidecars:
        return 0
    sc = getattr(meta, "sidecars", None)
    if sc is not None:
        return len(sc)
    try:
        from duplicates_detector.sidecar import find_sidecars

        kwargs: dict[str, object] = {}
        if sidecar_extensions is not None:
            from duplicates_detector.sidecar import parse_sidecar_extensions

            kwargs["extensions"] = parse_sidecar_extensions(sidecar_extensions)
        return len(find_sidecars(meta.path, **kwargs))  # type: ignore[arg-type]
    except (OSError, AttributeError):
        return 0


def _pixels(width: int | None, height: int | None) -> int | None:
    if width is None or height is None:
        return None
    return width * height


def _compare(
    val_a: float | int | None,
    val_b: float | int | None,
    *,
    higher_wins: bool,
    tie_a: object,
    tie_b: object,
    sc_ext: str | None = None,
    no_sc: bool = False,
) -> str | None:
    """Generic comparison with None handling and file-size tie-breaking.

    *tie_a* and *tie_b* must have a ``file_size`` attribute used for
    tie-breaking (larger file wins the tie).
    """
    if val_a is None and val_b is None:
        return None
    if val_a is None:
        return "b"
    if val_b is None:
        return "a"

    if higher_wins:
        if val_a > val_b:
            return "a"
        if val_b > val_a:
            return "b"
    else:
        if val_a < val_b:
            return "a"
        if val_b < val_a:
            return "b"

    # Tie-break 1: largest file_size wins.
    size_a = tie_a.file_size  # type: ignore[union-attr]
    size_b = tie_b.file_size  # type: ignore[union-attr]
    if size_a > size_b:
        return "a"
    if size_b > size_a:
        return "b"

    # Tie-break 2: more sidecars wins.
    sc_a = _sidecar_count(tie_a, sc_ext, no_sc)  # type: ignore[arg-type]
    sc_b = _sidecar_count(tie_b, sc_ext, no_sc)  # type: ignore[arg-type]
    if sc_a > sc_b:
        return "a"
    if sc_b > sc_a:
        return "b"
    return None


# ---------------------------------------------------------------------------
# Group-level helpers (N-member selection)
# ---------------------------------------------------------------------------


def pick_keep_from_group(
    members: Sequence[VideoMetadata],
    strategy: str,
    *,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> VideoMetadata | None:
    """Select the best file to keep from a group of *N* members.

    Returns the :class:`VideoMetadata` of the keeper, or ``None`` if
    undecidable (all members tie on the primary metric and file-size
    tie-breaker).
    *sidecar_extensions* is forwarded to sidecar rediscovery for replay mode.
    *no_sidecars* suppresses all sidecar-aware decisions.
    """
    sc_ext = sidecar_extensions
    no_sc = no_sidecars
    match strategy:
        case "newest":
            return _pick_best(members, key=lambda m: m.mtime, higher_wins=True, sc_ext=sc_ext, no_sc=no_sc)
        case "oldest":
            return _pick_best(members, key=lambda m: m.mtime, higher_wins=False, sc_ext=sc_ext, no_sc=no_sc)
        case "biggest":
            return _pick_best_size(members, bigger_wins=True)
        case "smallest":
            return _pick_best_size(members, bigger_wins=False)
        case "longest":
            return _pick_best(members, key=lambda m: m.duration, higher_wins=True, sc_ext=sc_ext, no_sc=no_sc)
        case "highest-res":
            return _pick_best(
                members,
                key=lambda m: _pixels(m.width, m.height),
                higher_wins=True,
                sc_ext=sc_ext,
                no_sc=no_sc,
            )
        case "edited":
            return _pick_best(
                members,
                key=lambda m: _sidecar_count(m, sc_ext, no_sc),
                higher_wins=True,
                sc_ext=sc_ext,
                no_sc=no_sc,
            )
        case _:
            raise ValueError(f"Unknown strategy: {strategy!r}")


def pick_deletes_from_group(
    members: Sequence[VideoMetadata],
    strategy: str,
    *,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> list[VideoMetadata]:
    """Return the members to delete (all except the keeper).

    Returns an empty list if the strategy is undecidable.
    """
    keeper = pick_keep_from_group(members, strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars)
    if keeper is None:
        return []
    return [m for m in members if m.path != keeper.path]


def _pick_best(
    members: Sequence[VideoMetadata],
    *,
    key: Callable[[VideoMetadata], float | int | None],
    higher_wins: bool,
    sc_ext: str | None = None,
    no_sc: bool = False,
) -> VideoMetadata | None:
    """Generic N-member comparison with None handling and file-size tie-break."""
    # Filter out members where the key value is None
    candidates = [(m, key(m)) for m in members if key(m) is not None]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    # Sort by primary key, then by file_size descending as tie-breaker
    candidates.sort(
        key=lambda pair: (pair[1], pair[0].file_size),  # type: ignore[arg-type]
        reverse=higher_wins,
    )

    best_meta, best_val = candidates[0]
    # Check for tie on primary key
    second_val = candidates[1][1]
    if best_val != second_val:
        return best_meta

    # Tied on primary — use file_size then sidecar count to break tie
    tied = [m for m, v in candidates if v == best_val]
    tied.sort(key=lambda m: (m.file_size, _sidecar_count(m, sc_ext, no_sc)), reverse=True)
    if tied[0].file_size > tied[1].file_size:
        return tied[0]
    # File sizes also tied — try sidecar count
    if _sidecar_count(tied[0], sc_ext, no_sc) > _sidecar_count(tied[1], sc_ext, no_sc):
        return tied[0]
    return None


def _pick_best_size(
    members: Sequence[VideoMetadata],
    *,
    bigger_wins: bool,
) -> VideoMetadata | None:
    """Size-based selection with no secondary tie-breaker."""
    if not members:
        return None
    sorted_members = sorted(members, key=lambda m: m.file_size, reverse=bigger_wins)
    if len(sorted_members) < 2:
        return sorted_members[0]
    if sorted_members[0].file_size == sorted_members[1].file_size:
        return None
    return sorted_members[0]
