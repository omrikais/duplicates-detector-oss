from __future__ import annotations

import csv as _csv
import json as _json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table
from rich.text import Text

from duplicates_detector.filters import format_size_human
from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.keeper import pick_keep, pick_keep_from_group, pick_delete
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair

if TYPE_CHECKING:
    from duplicates_detector.advisor import DeletionSummary
    from duplicates_detector.summary import PipelineStats

_THUMBNAIL_ABSENT = object()


def score_color(score: float) -> str:
    if score >= 80:
        return "bold red"
    if score >= 60:
        return "bold yellow"
    return "bold green"


def _display_path(path: Path, verbose: bool) -> str:
    if verbose:
        return str(path)
    return path.name


_MAX_TABLE_ROWS = 500


def _pause_checkpoint(pause_waiter: Callable[[], None] | None) -> None:
    """Block cooperatively when a caller has requested a pause."""
    if pause_waiter is not None:
        pause_waiter()


def _dump_json_pause_aware(
    payload: Any,
    output: TextIO,
    *,
    pause_waiter: Callable[[], None] | None,
) -> None:
    """Write JSON incrementally so pause requests can take effect mid-report."""
    if pause_waiter is None or getattr(output, "seekable", lambda: False)():
        # Fast path: skip per-chunk pause callbacks when writing to a file
        # (seekable output) or when no pause support is needed.  json.dump()
        # writes directly without per-chunk callback overhead — critical for
        # large outputs (386K pairs × ~15M chunks × 2 Event.wait() per chunk
        # = 30s+ of pure lock overhead).  Coarse-grained _pause_checkpoint()
        # calls in the caller still honour pause requests between records.
        _json.dump(payload, output, indent=2)
        return
    encoder = _json.JSONEncoder(indent=2)
    for chunk in encoder.iterencode(payload):
        _pause_checkpoint(pause_waiter)
        output.write(chunk)


def _format_breakdown_verbose(pair: ScoredPair) -> str:
    """Format breakdown with raw scores: 'name: raw × weight = weighted'."""
    parts: list[str] = []
    for name, val in pair.breakdown.items():
        if val is None:
            parts.append(f"{name}: n/a")
        else:
            raw, weight = pair.detail[name]
            parts.append(f"{name}: {raw:.2f} \u00d7 {weight:g} = {val:.1f}")
    return " | ".join(parts)


def print_table(
    pairs: list[ScoredPair],
    *,
    verbose: bool = False,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    max_rows: int | None = None,
    quiet: bool = False,
    title: str = "Potential Duplicate Videos",
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> int:
    """Print a Rich table of potential duplicate pairs.

    Returns the number of rows actually displayed.
    """
    if file is not None:
        console = Console(file=file, force_terminal=False)
    else:
        console = Console()

    if not pairs:
        console.print("[green]No duplicates found above threshold.[/green]")
        return 0

    effective_max = max_rows if max_rows is not None else _MAX_TABLE_ROWS
    truncated = len(pairs) > effective_max
    display_pairs = pairs[:effective_max] if truncated else pairs

    caption = f"{len(pairs)} pair(s) found"
    if truncated:
        caption += f" (showing top {effective_max})"

    table = Table(
        title=title,
        caption=caption,
        show_lines=True,
    )

    table.add_column("#", justify="right", style="dim", width=4)
    if verbose:
        table.add_column(
            "File A",
            style="cyan",
            min_width=20,
            ratio=1,
            no_wrap=False,
            overflow="fold",
        )
        table.add_column(
            "File B",
            style="cyan",
            min_width=20,
            ratio=1,
            no_wrap=False,
            overflow="fold",
        )
    else:
        table.add_column("File A", style="cyan", max_width=50)
        table.add_column("File B", style="cyan", max_width=50)
    table.add_column("Score", justify="right", style="bold", width=6)
    table.add_column("Breakdown", style="dim")

    for idx, pair in enumerate(display_pairs, 1):
        _pause_checkpoint(pause_waiter)
        if verbose and pair.detail:
            breakdown_str = _format_breakdown_verbose(pair)
        else:
            breakdown_str = " | ".join(
                f"{name}: n/a" if val is None else f"{name}: {val}" for name, val in pair.breakdown.items()
            )
        a_label = _display_path(pair.file_a.path, verbose)
        if pair.file_a.is_reference:
            a_label += " [dim]\\[REF][/dim]"
        b_label = _display_path(pair.file_b.path, verbose)
        if pair.file_b.is_reference:
            b_label += " [dim]\\[REF][/dim]"
        if keep_strategy:
            keep = pick_keep(pair, keep_strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars)
            if keep == "a":
                a_label += " [bold green]KEEP[/bold green]"
            elif keep == "b":
                b_label += " [bold green]KEEP[/bold green]"
        if verbose:
            details_a = _format_details(pair.file_a)
            if details_a:
                a_label += f"\n[dim]{details_a}[/dim]"
            if pair.file_a.sidecars:
                sc_names = ", ".join(p.name for p in pair.file_a.sidecars)
                a_label += f"\n[dim]Sidecars: {rich_escape(sc_names)}[/dim]"
            details_b = _format_details(pair.file_b)
            if details_b:
                b_label += f"\n[dim]{details_b}[/dim]"
            if pair.file_b.sidecars:
                sc_names = ", ".join(p.name for p in pair.file_b.sidecars)
                b_label += f"\n[dim]Sidecars: {rich_escape(sc_names)}[/dim]"
        table.add_row(
            str(idx),
            a_label,
            b_label,
            Text(f"{pair.total_score:.1f}", style=score_color(pair.total_score)),
            breakdown_str,
        )

    _pause_checkpoint(pause_waiter)
    console.print(table)

    if truncated and not quiet:
        warn_console = Console(stderr=True)
        warn_console.print(
            f"[yellow]Showing top {effective_max:,} of {len(pairs):,} pairs. "
            f"Use --limit or --min-score to refine.[/yellow]"
        )

    return len(display_pairs)


def _metadata_dict(meta: VideoMetadata, *, thumbnail: object = _THUMBNAIL_ABSENT) -> dict:
    """Convert VideoMetadata fields to a plain dict for JSON serialization.

    When *thumbnail* is provided (not the default sentinel), a ``"thumbnail"``
    key is included in the output — ``None`` for failures, data URI for successes.
    """
    d: dict = {
        "duration": meta.duration,
        "width": meta.width,
        "height": meta.height,
        "file_size": meta.file_size,
        "codec": meta.codec,
        "bitrate": meta.bitrate,
        "framerate": meta.framerate,
        "audio_channels": meta.audio_channels,
        "mtime": meta.mtime,
    }
    if meta.tag_title is not None:
        d["tag_title"] = meta.tag_title
    if meta.tag_artist is not None:
        d["tag_artist"] = meta.tag_artist
    if meta.tag_album is not None:
        d["tag_album"] = meta.tag_album
    if meta.page_count is not None:
        d["page_count"] = meta.page_count
    if meta.doc_title is not None:
        d["doc_title"] = meta.doc_title
    if meta.doc_author is not None:
        d["doc_author"] = meta.doc_author
    if meta.doc_created is not None:
        d["doc_created"] = meta.doc_created
    if thumbnail is not _THUMBNAIL_ABSENT:
        d["thumbnail"] = thumbnail
    return d


def _reconstruct_metadata(path_str: str, meta_dict: dict, is_reference: bool = False) -> VideoMetadata:
    """Build a VideoMetadata from a JSON path string + metadata dict."""
    p = Path(path_str)
    return VideoMetadata(
        path=p,
        filename=p.stem,
        duration=meta_dict.get("duration"),
        width=meta_dict.get("width"),
        height=meta_dict.get("height"),
        file_size=meta_dict.get("file_size", 0),
        codec=meta_dict.get("codec"),
        bitrate=meta_dict.get("bitrate"),
        framerate=meta_dict.get("framerate"),
        audio_channels=meta_dict.get("audio_channels"),
        mtime=meta_dict.get("mtime"),
        is_reference=is_reference,
        tag_title=meta_dict.get("tag_title"),
        tag_artist=meta_dict.get("tag_artist"),
        tag_album=meta_dict.get("tag_album"),
        page_count=meta_dict.get("page_count"),
        doc_title=meta_dict.get("doc_title"),
        doc_author=meta_dict.get("doc_author"),
        doc_created=meta_dict.get("doc_created"),
    )


def _reconstruct_pair(record: dict) -> ScoredPair:
    """Build a ScoredPair from a JSON pair record."""
    meta_a = _reconstruct_metadata(
        record["file_a"],
        record.get("file_a_metadata", {}),
        is_reference=record.get("file_a_is_reference", False),
    )
    meta_b = _reconstruct_metadata(
        record["file_b"],
        record.get("file_b_metadata", {}),
        is_reference=record.get("file_b_is_reference", False),
    )
    detail_raw = record.get("detail", {})
    detail = {name: (vals[0], vals[1]) for name, vals in detail_raw.items()}
    return ScoredPair(
        file_a=meta_a,
        file_b=meta_b,
        total_score=record["score"],
        breakdown=record.get("breakdown", {}),
        detail=detail,
    )


def load_replay_json(path: Path, *, _data: dict | list | None = None) -> list[ScoredPair]:
    """Load previously generated JSON envelope output and reconstruct ScoredPairs.

    Supports both pair-mode (``"pairs"`` key) and group-mode (``"groups"`` key)
    envelope output.  Bare JSON arrays (non-envelope output) raise ValueError.

    If *_data* is provided, it is used directly instead of reading/parsing the
    file.  This avoids a redundant parse when the caller already has the data.
    """
    data = _data if _data is not None else _json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        raise ValueError(
            "Replay requires JSON envelope output (--format json --json-envelope). Bare JSON arrays are not supported."
        )

    if not isinstance(data, dict):
        raise ValueError("Unexpected JSON structure: expected object or array")

    if "pairs" in data:
        return [_reconstruct_pair(rec) for rec in data["pairs"]]

    if "groups" in data:
        # Build path → (metadata_dict, is_reference) lookup from group files
        path_meta: dict[str, tuple[dict, bool]] = {}
        for group in data["groups"]:
            for f in group.get("files", []):
                p = f["path"]
                if p not in path_meta:
                    path_meta[p] = (f, f.get("is_reference", False))

        # Reconstruct unique pairs across all groups
        seen: set[tuple[str, str]] = set()
        pairs: list[ScoredPair] = []
        for group in data["groups"]:
            for rec in group.get("pairs", []):
                key = (rec["file_a"], rec["file_b"])
                if key in seen:
                    continue
                seen.add(key)

                # Enrich pair record with file metadata from the group files lookup
                meta_a_dict, a_ref = path_meta.get(rec["file_a"], ({}, False))
                meta_b_dict, b_ref = path_meta.get(rec["file_b"], ({}, False))
                meta_a = _reconstruct_metadata(rec["file_a"], meta_a_dict, is_reference=a_ref)
                meta_b = _reconstruct_metadata(rec["file_b"], meta_b_dict, is_reference=b_ref)

                detail_raw = rec.get("detail", {})
                detail = {name: (vals[0], vals[1]) for name, vals in detail_raw.items()}
                pairs.append(
                    ScoredPair(
                        file_a=meta_a,
                        file_b=meta_b,
                        total_score=rec["score"],
                        breakdown=rec.get("breakdown", {}),
                        detail=detail,
                    )
                )
        return pairs

    raise ValueError("JSON envelope must contain 'pairs' or 'groups' key")


def _build_dry_run_summary_dict(
    summary: DeletionSummary,
    strategy: str | None = None,
) -> dict:
    """Build a dict for the dry_run_summary JSON field."""
    files = []
    for path in summary.deleted:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        files.append(
            {
                "path": str(path),
                "size": size,
                "size_human": format_size_human(size),
            }
        )
    total_bytes = sum(f["size"] for f in files)
    result: dict = {
        "files_to_delete": files,
        "total_files": len(files),
        "total_bytes": total_bytes,
        "total_bytes_human": format_size_human(total_bytes),
    }
    if summary.sidecars_deleted > 0:
        result["sidecars_to_delete"] = summary.sidecars_deleted
        result["sidecar_bytes"] = summary.sidecar_bytes_freed
        result["sidecar_bytes_human"] = format_size_human(summary.sidecar_bytes_freed)
    if strategy is not None:
        result["strategy"] = strategy
    return result


def write_json(
    pairs: list[ScoredPair],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    dry_run_summary: DeletionSummary | None = None,
    envelope: dict[str, Any] | None = None,
    thumbnails: dict[Path, str | None] | None = None,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> None:
    """Write pairs as a JSON array to *file* or stdout."""
    records = []
    for pair in pairs:
        _pause_checkpoint(pause_waiter)
        thumb_a: object = _THUMBNAIL_ABSENT
        thumb_b: object = _THUMBNAIL_ABSENT
        if thumbnails is not None:
            thumb_a = thumbnails.get(pair.file_a.path.resolve())
            thumb_b = thumbnails.get(pair.file_b.path.resolve())
        record = {
            "file_a": str(pair.file_a.path),
            "file_b": str(pair.file_b.path),
            "score": pair.total_score,
            "breakdown": dict(pair.breakdown),
            "detail": {name: list(vals) for name, vals in pair.detail.items()},
            "file_a_metadata": _metadata_dict(pair.file_a, thumbnail=thumb_a),
            "file_b_metadata": _metadata_dict(pair.file_b, thumbnail=thumb_b),
            "file_a_is_reference": pair.file_a.is_reference,
            "file_b_is_reference": pair.file_b.is_reference,
        }
        if keep_strategy is not None:
            record["keep"] = pick_keep(
                pair,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
        records.append(record)

    output = file if file is not None else sys.stdout
    if envelope is not None:
        output_dict: dict[str, Any] = {**envelope, "pairs": records}
        if dry_run_summary is not None and dry_run_summary.deleted:
            output_dict["dry_run_summary"] = _build_dry_run_summary_dict(dry_run_summary, keep_strategy)
        _dump_json_pause_aware(output_dict, output, pause_waiter=pause_waiter)
    elif dry_run_summary is not None and dry_run_summary.deleted:
        wrapped = {
            "pairs": records,
            "dry_run_summary": _build_dry_run_summary_dict(dry_run_summary, keep_strategy),
        }
        _dump_json_pause_aware(wrapped, output, pause_waiter=pause_waiter)
    else:
        _dump_json_pause_aware(records, output, pause_waiter=pause_waiter)
    _pause_checkpoint(pause_waiter)
    output.write("\n")


def _breakdown_val(v: float | None) -> str:
    """Format a breakdown value for CSV (None → empty string)."""
    return "" if v is None else str(v)


_DEFAULT_BREAKDOWN_KEYS = ["filename", "duration", "resolution", "file_size"]


def write_csv(
    pairs: list[ScoredPair],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> None:
    """Write pairs as RFC 4180 CSV to *file* or stdout."""
    output = file if file is not None else sys.stdout
    # When writing to a file opened with newline="" (cli.py), csv.writer's
    # default \r\n terminator is passed through correctly.  For stdout on
    # Windows, text-mode newline translation would double the \r, so we
    # force \n for that path.
    terminator = "\r\n" if file is not None else "\n"
    writer = _csv.writer(output, lineterminator=terminator)

    breakdown_keys = list(pairs[0].breakdown.keys()) if pairs else _DEFAULT_BREAKDOWN_KEYS
    columns = (
        ["file_a", "file_b", "score"]
        + breakdown_keys
        + [
            "file_a_is_reference",
            "file_b_is_reference",
        ]
    )
    if keep_strategy is not None:
        columns.append("keep")
    _pause_checkpoint(pause_waiter)
    writer.writerow(columns)

    for pair in pairs:
        _pause_checkpoint(pause_waiter)
        row: list = [
            str(pair.file_a.path),
            str(pair.file_b.path),
            pair.total_score,
        ]
        for key in breakdown_keys:
            row.append(_breakdown_val(pair.breakdown.get(key)))
        row.extend(
            [
                str(pair.file_a.is_reference).lower(),
                str(pair.file_b.is_reference).lower(),
            ]
        )
        if keep_strategy is not None:
            row.append(
                pick_keep(pair, keep_strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars) or ""
            )
        writer.writerow(row)


_SHELL_HEADER = """\
#!/usr/bin/env bash
# Generated by duplicates-detector
# Review carefully before uncommenting any lines.
# Each pair shows the similarity score and both files.
# Uncomment the rm line for the file you want to delete.
"""


def write_shell(
    pairs: list[ScoredPair],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    dry_run_summary: DeletionSummary | None = None,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> None:
    """Write a bash script with commented-out rm commands."""
    output = file if file is not None else sys.stdout
    _pause_checkpoint(pause_waiter)
    output.write(_SHELL_HEADER)

    if not pairs:
        _pause_checkpoint(pause_waiter)
        output.write("\n# No duplicates found.\n")
        return

    for pair in pairs:
        _pause_checkpoint(pause_waiter)
        output.write(f"\n# --- Score: {pair.total_score:.1f} ---\n")
        delete = (
            pick_delete(pair, keep_strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars)
            if keep_strategy
            else None
        )

        if pair.file_a.is_reference:
            output.write(f"# (reference \u2014 do not delete) {pair.file_a.path}\n")
        elif delete == "a":
            output.write(f"rm -- {shlex.quote(str(pair.file_a.path))}\n")
        else:
            output.write(f"# rm -- {shlex.quote(str(pair.file_a.path))}\n")

        if pair.file_b.is_reference:
            output.write(f"# (reference \u2014 do not delete) {pair.file_b.path}\n")
        elif delete == "b":
            output.write(f"rm -- {shlex.quote(str(pair.file_b.path))}\n")
        else:
            output.write(f"# rm -- {shlex.quote(str(pair.file_b.path))}\n")

    if dry_run_summary is not None and dry_run_summary.deleted:
        total_bytes = sum(p.stat().st_size for p in dry_run_summary.deleted if p.exists())
        _pause_checkpoint(pause_waiter)
        output.write("\n# --- Dry Run Summary ---\n")
        output.write(f"# Files to delete: {len(dry_run_summary.deleted)}\n")
        output.write(f"# Space recoverable: {format_size_human(total_bytes)}\n")
        output.write("# Run without --dry-run to execute deletions.\n")


# ---------------------------------------------------------------------------
# Group-based output functions
# ---------------------------------------------------------------------------


def _format_member_size(file_size: int) -> str:
    """Human-readable file size for group table rows."""
    return format_size_human(file_size)


def _format_duration(duration: float | None) -> str:
    if duration is None:
        return "n/a"
    m, s = divmod(int(duration), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _format_resolution(width: int | None, height: int | None) -> str:
    if width is None or height is None:
        return "n/a"
    return f"{width}x{height}"


def format_codec(codec: str | None) -> str:
    """Format codec name for display."""
    if codec is None:
        return "n/a"
    display = {"h264": "H.264", "hevc": "H.265", "vp9": "VP9", "av1": "AV1", "mpeg4": "MPEG-4"}
    return display.get(codec, codec.upper())


def format_bitrate(bitrate: int | None) -> str:
    """Format bitrate as human-readable string."""
    if bitrate is None:
        return "n/a"
    if bitrate >= 1_000_000:
        return f"{bitrate / 1_000_000:.1f} Mbps"
    if bitrate >= 1_000:
        return f"{bitrate / 1_000:.0f} kbps"
    return f"{bitrate} bps"


def format_framerate(framerate: float | None) -> str:
    """Format frame rate for display."""
    if framerate is None:
        return "n/a"
    return f"{framerate:.3f}".rstrip("0").rstrip(".") + " fps"


def format_audio_channels(channels: int | None) -> str:
    """Format audio channel count for display."""
    if channels is None:
        return "n/a"
    labels = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}
    return labels.get(channels, f"{channels}ch")


def _format_details(meta: VideoMetadata) -> str:
    """Compact multi-line summary of codec/bitrate/framerate/audio for pair table.

    Only includes non-None fields. Returns empty string if all fields are None
    (e.g. for images which lack bitrate/framerate/audio).
    """
    parts: list[str] = []
    if meta.tag_artist is not None:
        parts.append(rich_escape(meta.tag_artist))
    if meta.tag_title is not None:
        parts.append(f'"{rich_escape(meta.tag_title)}"')
    if meta.tag_album is not None:
        parts.append(f"\\[{rich_escape(meta.tag_album)}]")
    if meta.codec is not None:
        parts.append(format_codec(meta.codec))
    if meta.bitrate is not None:
        parts.append(format_bitrate(meta.bitrate))
    if meta.framerate is not None:
        parts.append(format_framerate(meta.framerate))
    if meta.audio_channels is not None:
        parts.append(format_audio_channels(meta.audio_channels))
    return " \u00b7 ".join(parts)


def print_group_table(
    groups: list[DuplicateGroup],
    *,
    verbose: bool = False,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    max_rows: int | None = None,
    quiet: bool = False,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> int:
    """Print grouped duplicates as Rich tables, one per group.

    Returns the number of groups actually displayed.
    """
    if file is not None:
        console = Console(file=file, force_terminal=False)
    else:
        console = Console()

    if not groups:
        console.print("[green]No duplicates found above threshold.[/green]")
        return 0

    effective_max = max_rows if max_rows is not None else _MAX_TABLE_ROWS
    truncated = len(groups) > effective_max
    display_groups = groups[:effective_max] if truncated else groups

    total_files = sum(len(g.members) for g in groups)
    header = f"Found {len(groups)} group(s) containing {total_files} file(s)."
    if truncated:
        header += f" (showing top {effective_max})"
    _pause_checkpoint(pause_waiter)
    console.print(f"[bold]{header}[/bold]\n")

    for group in display_groups:
        _pause_checkpoint(pause_waiter)
        keeper = None
        if keep_strategy:
            keeper = pick_keep_from_group(
                group.members,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )

        score_range = (
            f"{group.max_score:.1f}"
            if group.min_score == group.max_score
            else f"{group.min_score:.1f}\u2013{group.max_score:.1f}"
        )
        title = (
            f"Group {group.group_id} ({len(group.members)} files) "
            f"\u2014 Score: {score_range} (avg {group.avg_score:.1f})"
        )

        table = Table(title=title, show_lines=False, show_edge=True)
        table.add_column("#", justify="right", style="dim", width=4)
        table.add_column(
            "File",
            style="cyan",
            min_width=20,
            ratio=1,
            no_wrap=not verbose,
            overflow="ellipsis" if not verbose else "fold",
        )
        table.add_column("Duration", justify="right")
        table.add_column("Resolution", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Codec", justify="right")
        table.add_column("Bitrate", justify="right")
        table.add_column("FPS", justify="right")
        table.add_column("Audio", justify="right")
        table.add_column("", no_wrap=True)  # markers column

        for idx, member in enumerate(group.members, 1):
            _pause_checkpoint(pause_waiter)
            label = _display_path(member.path, verbose)
            markers = ""
            if member.is_reference:
                markers += "[dim]\\[REF][/dim]"
            if keeper and member.path == keeper.path:
                markers += " [bold green]KEEP[/bold green]" if markers else "[bold green]KEEP[/bold green]"

            table.add_row(
                str(idx),
                label,
                _format_duration(member.duration),
                _format_resolution(member.width, member.height),
                _format_member_size(member.file_size),
                format_codec(member.codec),
                format_bitrate(member.bitrate),
                format_framerate(member.framerate),
                format_audio_channels(member.audio_channels),
                markers,
            )

        _pause_checkpoint(pause_waiter)
        console.print(table)
        console.print()

    if truncated and not quiet:
        warn_console = Console(stderr=True)
        warn_console.print(
            f"[yellow]Showing top {effective_max:,} of {len(groups):,} groups. "
            f"Use --limit or --min-score to refine.[/yellow]"
        )

    return len(display_groups)


def write_group_json(
    groups: list[DuplicateGroup],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    dry_run_summary: DeletionSummary | None = None,
    envelope: dict[str, Any] | None = None,
    thumbnails: dict[Path, str | None] | None = None,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> None:
    """Write groups as a JSON array to *file* or stdout."""
    records = []
    for group in groups:
        _pause_checkpoint(pause_waiter)
        keeper = None
        if keep_strategy is not None:
            k = pick_keep_from_group(
                group.members,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
            keeper = str(k.path) if k else None

        files = []
        for m in group.members:
            _pause_checkpoint(pause_waiter)
            f: dict[str, Any] = {
                "path": str(m.path),
                "duration": m.duration,
                "width": m.width,
                "height": m.height,
                "file_size": m.file_size,
                "codec": m.codec,
                "bitrate": m.bitrate,
                "framerate": m.framerate,
                "audio_channels": m.audio_channels,
                "mtime": m.mtime,
                "is_reference": m.is_reference,
            }
            if thumbnails is not None:
                f["thumbnail"] = thumbnails.get(m.path.resolve())
            files.append(f)
        pairs = [
            {
                "file_a": str(p.file_a.path),
                "file_b": str(p.file_b.path),
                "score": p.total_score,
                "breakdown": dict(p.breakdown),
                "detail": {name: list(vals) for name, vals in p.detail.items()},
            }
            for p in group.pairs
        ]
        record: dict = {
            "group_id": group.group_id,
            "file_count": len(group.members),
            "max_score": group.max_score,
            "min_score": group.min_score,
            "avg_score": group.avg_score,
            "files": files,
            "pairs": pairs,
        }
        if keep_strategy is not None:
            record["keep"] = keeper
        records.append(record)

    output = file if file is not None else sys.stdout
    if envelope is not None:
        output_dict: dict[str, Any] = {**envelope, "groups": records}
        if dry_run_summary is not None and dry_run_summary.deleted:
            output_dict["dry_run_summary"] = _build_dry_run_summary_dict(dry_run_summary, keep_strategy)
        _dump_json_pause_aware(output_dict, output, pause_waiter=pause_waiter)
    elif dry_run_summary is not None and dry_run_summary.deleted:
        wrapped = {
            "groups": records,
            "dry_run_summary": _build_dry_run_summary_dict(dry_run_summary, keep_strategy),
        }
        _dump_json_pause_aware(wrapped, output, pause_waiter=pause_waiter)
    else:
        _dump_json_pause_aware(records, output, pause_waiter=pause_waiter)
    _pause_checkpoint(pause_waiter)
    output.write("\n")


_GROUP_CSV_COLUMNS = [
    "group_id",
    "file_count",
    "max_score",
    "min_score",
    "avg_score",
    "path",
    "duration",
    "width",
    "height",
    "file_size",
    "codec",
    "bitrate",
    "framerate",
    "audio_channels",
    "is_reference",
]


def write_group_csv(
    groups: list[DuplicateGroup],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> None:
    """Write groups as RFC 4180 CSV, one row per member file."""
    output = file if file is not None else sys.stdout
    terminator = "\r\n" if file is not None else "\n"
    writer = _csv.writer(output, lineterminator=terminator)
    columns = list(_GROUP_CSV_COLUMNS)
    if keep_strategy is not None:
        columns.append("keep")
    _pause_checkpoint(pause_waiter)
    writer.writerow(columns)

    for group in groups:
        _pause_checkpoint(pause_waiter)
        keeper = None
        if keep_strategy is not None:
            keeper = pick_keep_from_group(
                group.members,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )

        for member in group.members:
            _pause_checkpoint(pause_waiter)
            row: list = [
                group.group_id,
                len(group.members),
                group.max_score,
                group.min_score,
                group.avg_score,
                str(member.path),
                member.duration if member.duration is not None else "",
                member.width if member.width is not None else "",
                member.height if member.height is not None else "",
                member.file_size,
                member.codec if member.codec is not None else "",
                member.bitrate if member.bitrate is not None else "",
                member.framerate if member.framerate is not None else "",
                member.audio_channels if member.audio_channels is not None else "",
                str(member.is_reference).lower(),
            ]
            if keep_strategy is not None:
                is_keep = keeper is not None and member.path == keeper.path
                row.append("true" if is_keep else "false")
            writer.writerow(row)


_GROUP_SHELL_HEADER = """\
#!/usr/bin/env bash
# Generated by duplicates-detector (grouped mode)
# Review carefully before uncommenting any lines.
# Each group shows the score range and all member files.
# Uncomment the rm lines for the files you want to delete.
"""


def write_group_shell(
    groups: list[DuplicateGroup],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    dry_run_summary: DeletionSummary | None = None,
    pause_waiter: Callable[[], None] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> None:
    """Write a bash script with grouped rm commands."""
    output = file if file is not None else sys.stdout
    _pause_checkpoint(pause_waiter)
    output.write(_GROUP_SHELL_HEADER)

    if not groups:
        _pause_checkpoint(pause_waiter)
        output.write("\n# No duplicates found.\n")
        return

    for group in groups:
        _pause_checkpoint(pause_waiter)
        score_range = (
            f"{group.max_score:.1f}"
            if group.min_score == group.max_score
            else f"{group.min_score:.1f}-{group.max_score:.1f}"
        )
        output.write(f"\n# --- Group {group.group_id} ({len(group.members)} files) Score: {score_range} ---\n")

        keeper = None
        if keep_strategy:
            keeper = pick_keep_from_group(
                group.members,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )

        for member in group.members:
            _pause_checkpoint(pause_waiter)
            if member.is_reference:
                output.write(f"# (reference \u2014 do not delete) {member.path}\n")
            elif keeper and member.path == keeper.path:
                output.write(f"# KEEP: {member.path}\n")
            elif keep_strategy and keeper and member.path != keeper.path:
                output.write(f"rm -- {shlex.quote(str(member.path))}\n")
            else:
                output.write(f"# rm -- {shlex.quote(str(member.path))}\n")

    if dry_run_summary is not None and dry_run_summary.deleted:
        total_bytes = sum(p.stat().st_size for p in dry_run_summary.deleted if p.exists())
        _pause_checkpoint(pause_waiter)
        output.write("\n# --- Dry Run Summary ---\n")
        output.write(f"# Files to delete: {len(dry_run_summary.deleted)}\n")
        output.write(f"# Space recoverable: {format_size_human(total_bytes)}\n")
        output.write("# Run without --dry-run to execute deletions.\n")


# ---------------------------------------------------------------------------
# Markdown output functions
# ---------------------------------------------------------------------------

_HOME_PREFIX = str(Path.home())


def _md_escape(text: str) -> str:
    """Escape characters that break GFM table cells."""
    return text.replace("|", "\\|")


def _shorten_path(p: Path) -> str:
    """Replace the user's home directory prefix with ``~``."""
    s = str(p)
    if s.startswith(_HOME_PREFIX + "/") or s == _HOME_PREFIX:
        return "~" + s[len(_HOME_PREFIX) :]
    return s


def _top_factor(detail: dict[str, tuple[float, float]]) -> str:
    """Return ``"name (N%)"`` for the comparator with highest ``raw_score * weight``."""
    if not detail:
        return ""
    best_name = ""
    best_value = -1.0
    for name, (raw_score, weight) in detail.items():
        value = raw_score * weight
        if value > best_value:
            best_value = value
            best_name = name
    return f"{best_name} ({int(detail[best_name][0] * 100)}%)" if best_name else ""


def _md_format_time(seconds: float) -> str:
    """Format seconds as a compact human-readable duration for markdown."""
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


def _md_metadata_columns(mode: str) -> list[str]:
    """Return mode-appropriate metadata column names for detail tables."""
    if mode == "audio":
        return ["Artist", "Album"]
    if mode == "image":
        return ["Dimensions"]
    # video (default) and auto
    return ["Duration", "Resolution", "Codec"]


def _md_metadata_value(meta: VideoMetadata, col: str) -> str:
    """Extract a single metadata column value for a detail row."""
    match col:
        case "Duration":
            return _format_duration(meta.duration)
        case "Resolution" | "Dimensions":
            return _format_resolution(meta.width, meta.height)
        case "Codec":
            return format_codec(meta.codec)
        case "Artist":
            return meta.tag_artist or "n/a"
        case "Album":
            return meta.tag_album or "n/a"
        case _:
            return "n/a"


def write_markdown(
    pairs: list[ScoredPair],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    verbose: bool = False,
    stats: PipelineStats | None = None,
    mode: str = "video",
    dry_run_summary: DeletionSummary | None = None,
    quiet: bool = False,
) -> None:
    """Write a GFM-compatible Markdown report of scored pairs."""
    import datetime

    output = file if file is not None else sys.stdout

    # --- Header ---
    output.write("# Duplicate Scan Report\n\n")
    header_parts: list[str] = [f"**Mode:** {mode}"]
    if stats is not None:
        header_parts.append(f"**Files scanned:** {stats.files_scanned}")
    header_parts.append(f"**Pairs found:** {len(pairs)}")
    if stats is not None and stats.space_recoverable:
        header_parts.append(f"**Space recoverable:** {format_size_human(stats.space_recoverable)}")
    if stats is not None and stats.total_time:
        header_parts.append(f"**Total time:** {_md_format_time(stats.total_time)}")
    header_parts.append(f"**Generated:** {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    output.write(" | ".join(header_parts) + "\n\n")

    if not pairs:
        output.write("No duplicates found above threshold.\n")
        return

    # --- Summary table ---
    truncated = len(pairs) > _MAX_TABLE_ROWS
    display_pairs = pairs[:_MAX_TABLE_ROWS] if truncated else pairs

    output.write("## Results\n\n")
    output.write("| # | File A | File B | Score | Top Factor |\n")
    output.write("|---|--------|--------|------:|------------|\n")
    for idx, pair in enumerate(display_pairs, 1):
        name_a = _md_escape(pair.file_a.path.name)
        name_b = _md_escape(pair.file_b.path.name)
        factor = _md_escape(_top_factor(pair.detail))
        output.write(f"| {idx} | {name_a} | {name_b} | {pair.total_score:.1f} | {factor} |\n")

    if truncated:
        output.write(f"\n*Showing 500 of {len(pairs)} pairs.*\n")

    output.write("\n")

    # --- Detail blocks per pair ---
    meta_cols = _md_metadata_columns(mode)
    for idx, pair in enumerate(display_pairs, 1):
        name_a = _md_escape(pair.file_a.path.name)
        name_b = _md_escape(pair.file_b.path.name)
        summary_line = f"Pair {idx}: {name_a} \u2194 {name_b} \u2014 {pair.total_score:.1f}"
        output.write(f"<details>\n<summary>{summary_line}</summary>\n\n")

        # Metadata comparison table
        output.write("| | File A | File B |\n")
        output.write("|---|--------|--------|\n")
        path_a = _md_escape(_shorten_path(pair.file_a.path))
        path_b = _md_escape(_shorten_path(pair.file_b.path))
        output.write(f"| Path | {path_a} | {path_b} |\n")
        output.write(
            f"| Size | {format_size_human(pair.file_a.file_size)} | {format_size_human(pair.file_b.file_size)} |\n"
        )
        for col in meta_cols:
            val_a = _md_escape(_md_metadata_value(pair.file_a, col))
            val_b = _md_escape(_md_metadata_value(pair.file_b, col))
            output.write(f"| {col} | {val_a} | {val_b} |\n")

        # Score breakdown
        output.write("\n**Score breakdown:**\n")
        for comp_name, (raw_score, weight) in pair.detail.items():
            contribution = raw_score * weight
            output.write(f"- {comp_name}: {raw_score:.2f} \u00d7 {weight:.0f} = **{contribution:.1f}**\n")

        output.write("\n</details>\n\n")

    # --- Dry-run summary ---
    if dry_run_summary is not None and dry_run_summary.deleted:
        output.write("---\n\n")
        output.write("## Dry Run Summary\n\n")
        output.write(f"- **Files to delete:** {len(dry_run_summary.deleted)}\n")
        output.write(f"- **Space recoverable:** {format_size_human(dry_run_summary.bytes_freed)}\n")
        output.write("- Run without `--dry-run` to execute deletions.\n")


def write_group_markdown(
    groups: list[DuplicateGroup],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    verbose: bool = False,
    stats: PipelineStats | None = None,
    mode: str = "video",
    dry_run_summary: DeletionSummary | None = None,
    quiet: bool = False,
) -> None:
    """Write a GFM-compatible Markdown report of grouped duplicates."""
    import datetime

    output = file if file is not None else sys.stdout

    # --- Header ---
    output.write("# Duplicate Scan Report (Grouped)\n\n")
    header_parts: list[str] = [f"**Mode:** {mode}"]
    if stats is not None:
        header_parts.append(f"**Files scanned:** {stats.files_scanned}")
    total_files = sum(len(g.members) for g in groups)
    header_parts.append(f"**Groups:** {len(groups)}")
    header_parts.append(f"**Files in groups:** {total_files}")
    if stats is not None and stats.space_recoverable:
        header_parts.append(f"**Space recoverable:** {format_size_human(stats.space_recoverable)}")
    header_parts.append(f"**Generated:** {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    output.write(" | ".join(header_parts) + "\n\n")

    if not groups:
        output.write("No duplicates found above threshold.\n")
        return

    meta_cols = _md_metadata_columns(mode)

    for group in groups:
        # --- Group header ---
        output.write(f"## Group {group.group_id} ({len(group.members)} files, avg score: {group.avg_score:.1f})\n\n")

        # --- Member table ---
        col_headers = ["File", "Size"] + meta_cols
        output.write("| " + " | ".join(col_headers) + " |\n")
        alignments = ["-" * max(len(h), 4) for h in col_headers]
        # Right-align Size
        alignments[1] = alignments[1] + ":"
        output.write("| " + " | ".join(alignments) + " |\n")

        for member in group.members:
            path_str = _md_escape(_shorten_path(member.path))
            size_str = format_size_human(member.file_size)
            meta_vals = [_md_escape(_md_metadata_value(member, col)) for col in meta_cols]
            output.write(f"| {path_str} | {size_str} | " + " | ".join(meta_vals) + " |\n")

        output.write("\n")

        # --- Pair scores in collapsible details ---
        output.write("<details>\n<summary>Pair scores</summary>\n\n")
        output.write("| File A | File B | Score |\n")
        output.write("|--------|--------|------:|\n")
        for pair in group.pairs:
            name_a = _md_escape(pair.file_a.path.name)
            name_b = _md_escape(pair.file_b.path.name)
            output.write(f"| {name_a} | {name_b} | {pair.total_score:.1f} |\n")
        output.write("\n</details>\n\n")

    # --- Dry-run summary ---
    if dry_run_summary is not None and dry_run_summary.deleted:
        output.write("---\n\n")
        output.write("## Dry Run Summary\n\n")
        output.write(f"- **Files to delete:** {len(dry_run_summary.deleted)}\n")
        output.write(f"- **Space recoverable:** {format_size_human(dry_run_summary.bytes_freed)}\n")
        output.write("- Run without `--dry-run` to execute deletions.\n")
