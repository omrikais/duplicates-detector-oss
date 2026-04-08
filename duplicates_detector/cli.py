from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any, TextIO, cast

if TYPE_CHECKING:
    from duplicates_detector.cache_db import CacheDB
    from duplicates_detector.progress import ProgressEmitter
import asyncio
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from duplicates_detector import __version__
from duplicates_detector.config import Mode
from duplicates_detector.scanner import (
    DEFAULT_AUDIO_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_IMAGE_EXTENSIONS,
    DEFAULT_VIDEO_EXTENSIONS,
    find_media_files,
    find_video_files,
)
from duplicates_detector.pipeline import PipelineController, PipelineResult, run_pipeline
from duplicates_detector.scorer import ScoredPair, find_duplicates
from duplicates_detector.grouper import DuplicateGroup, group_duplicates
from duplicates_detector.reporter import (
    print_table,
    write_json,
    write_csv,
    write_shell,
    print_group_table,
    write_group_json,
    write_group_csv,
    write_group_shell,
    load_replay_json,
    write_markdown,
    write_group_markdown,
)
from duplicates_detector.filters import filter_metadata, parse_bitrate, parse_resolution, parse_size
from duplicates_detector.summary import PipelineStats, print_summary

console = Console(stderr=True)


def _default_content_method(args: argparse.Namespace, mode: str) -> str:
    """Return the effective content method, defaulting by mode."""
    return getattr(args, "content_method", None) or ("simhash" if mode == Mode.DOCUMENT else "phash")


def _get_sessions_dir() -> Path:
    """Return the sessions directory under XDG_DATA_HOME."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    data_dir = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
    return data_dir / "duplicates-detector" / "sessions"


def _merge_stage_timings(
    prior_stage_timings: dict[str, float],
    current_stage_timings: dict[str, float],
) -> dict[str, float]:
    """Merge completed-stage timings across pause/resume checkpoints.

    Previously completed stages keep their original saved timing history.
    Newly completed stages from the current run are appended.
    """
    merged = dict(prior_stage_timings)
    for stage, elapsed in current_stage_timings.items():
        merged.setdefault(stage, elapsed)
    return merged


def _compute_session_stage_list(args: argparse.Namespace, *, mode: str, is_replay: bool) -> list[str]:
    """Return the externally visible stage order for this scan run."""
    from duplicates_detector.pipeline import compute_stage_list

    content_method = _default_content_method(args, mode)
    return compute_stage_list(
        is_replay=is_replay,
        is_ssim=bool(args.content) and content_method == "ssim",
        embed_thumbnails=bool(args.embed_thumbnails),
        has_content=bool(args.content) and content_method != "ssim",
        has_audio=bool(args.audio) and mode != Mode.IMAGE,
    )


def _build_pause_snapshot(
    args: argparse.Namespace,
    *,
    mode: str,
    is_replay: bool,
    controller: PipelineController,
    aggregator: Any | None = None,
) -> tuple[list[str], str | None, dict[str, float]]:
    """Merge pipeline and post-pipeline stage state for a pause checkpoint."""
    from duplicates_detector.pipeline import _CANONICAL_STAGES

    stage_order = _compute_session_stage_list(args, mode=mode, is_replay=is_replay)
    canonical_stages = set(_CANONICAL_STAGES)
    controller_snapshot = controller.stage_snapshot()
    aggregated_snapshot = aggregator.unified_stage_snapshot() if aggregator is not None else None

    controller_completed = set(controller_snapshot.completed_stages)
    aggregated_completed = set(aggregated_snapshot.completed_stages) if aggregated_snapshot is not None else set()

    completed_stages: list[str] = []
    stage_timings: dict[str, float] = {}
    for stage in stage_order:
        if aggregated_snapshot is not None and stage in canonical_stages:
            if stage in aggregated_completed:
                completed_stages.append(stage)
                elapsed = aggregated_snapshot.stage_timings.get(stage)
                if elapsed is not None:
                    stage_timings[stage] = elapsed
                continue
            if stage in controller_completed:
                completed_stages.append(stage)
                elapsed = controller_snapshot.stage_timings.get(stage)
                if elapsed is not None:
                    stage_timings[stage] = elapsed
            continue
        if stage in controller_completed:
            completed_stages.append(stage)
            elapsed = controller_snapshot.stage_timings.get(stage)
            if elapsed is not None:
                stage_timings[stage] = elapsed

    if aggregated_snapshot is not None:
        active_stage = aggregated_snapshot.active_stage
        controller_active = controller_snapshot.active_stage
        if controller_active in {"scan", "thumbnail", "report"} or active_stage is None:
            active_stage = controller_active
    else:
        active_stage = controller_snapshot.active_stage

    return completed_stages, active_stage, stage_timings


@contextmanager
def _controller_stage(controller: PipelineController | None, stage: str):
    """Track a synchronous post-pipeline stage on the shared controller."""
    if controller is None:
        yield
        return

    controller.wait_if_paused_blocking()
    controller.enter_stage(stage)
    try:
        yield
        controller.wait_if_paused_blocking()
    except Exception:
        raise
    else:
        controller.complete_stage(stage)


class _PauseAwareTextWriter:
    """Delegate a text stream while honoring controller pauses between writes."""

    def __init__(self, wrapped: Any, controller: PipelineController | None) -> None:
        self._wrapped = wrapped
        self._controller = controller

    def _wait_if_paused(self) -> None:
        if self._controller is not None:
            self._controller.wait_if_paused_blocking()

    def write(self, data: str) -> int:
        self._wait_if_paused()
        return self._wrapped.write(data)

    def writelines(self, lines: list[str]) -> None:
        self._wait_if_paused()
        self._wrapped.writelines(lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def _start_parent_liveness_monitor() -> None:
    """Exit when the parent process closes our stdin pipe.

    When the GUI launches the CLI with ``--machine-progress``, stdin is a
    pipe whose write-end is held by the parent.  If the parent is killed
    (including SIGKILL, which cannot be caught), the kernel closes that
    write-end and our blocking ``read()`` returns EOF immediately.

    Only activated when stdin is actually a pipe (not a terminal or
    ``/dev/null``), so normal terminal usage is never affected.
    """
    import stat
    import threading

    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (OSError, ValueError):
        return
    if not stat.S_ISFIFO(mode):
        return

    def _monitor() -> None:
        # Dup the fd to avoid Python's buffered I/O on sys.stdin.
        # During interpreter shutdown, _Py_Finalize closes sys.stdin's
        # BufferedReader; if we were blocking on .read() at that point,
        # CPython 3.14+ aborts with a "busy buffer" fatal error.
        # A dup'd raw fd sidesteps the issue entirely.
        fd = os.dup(sys.stdin.fileno())
        try:
            while True:
                chunk = os.read(fd, 1)
                if not chunk:  # EOF — parent is gone
                    break
        except OSError:
            pass  # fd closed or pipe broken
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        os._exit(0)

    threading.Thread(target=_monitor, name="parent-liveness", daemon=True).start()


def _parse_extensions_arg(raw_extensions: str | None) -> frozenset[str] | None:
    """Parse a comma-separated extension string into normalized suffixes."""
    if not raw_extensions:
        return None
    return frozenset(f".{ext.strip().lstrip('.').lower()}" for ext in raw_extensions.split(","))


def _resolve_scan_directories(args: argparse.Namespace) -> list[Path]:
    """Return the full directory list used by discovery and pipeline scans."""
    return [Path(d) for d in args.directories + (args.reference or [])]


def _resolve_scan_extensions(args: argparse.Namespace, mode: str) -> frozenset[str]:
    """Return the effective extension set for a single discovery pass."""
    parsed_extensions = _parse_extensions_arg(args.extensions)
    if mode == Mode.AUTO:
        if parsed_extensions is None:
            return DEFAULT_VIDEO_EXTENSIONS | DEFAULT_IMAGE_EXTENSIONS
        return frozenset(
            ext for ext in parsed_extensions if ext in DEFAULT_VIDEO_EXTENSIONS or ext in DEFAULT_IMAGE_EXTENSIONS
        )
    if parsed_extensions is not None:
        return parsed_extensions
    if mode == Mode.IMAGE:
        return DEFAULT_IMAGE_EXTENSIONS
    if mode == Mode.AUDIO:
        return DEFAULT_AUDIO_EXTENSIONS
    if mode == Mode.DOCUMENT:
        return DEFAULT_DOCUMENT_EXTENSIONS
    return DEFAULT_VIDEO_EXTENSIONS


def _resolve_auto_pipeline_extensions(args: argparse.Namespace) -> tuple[frozenset[str], frozenset[str]]:
    """Return the effective video/image extension sets for auto mode."""
    parsed_extensions = _parse_extensions_arg(args.extensions)
    if parsed_extensions is None:
        return DEFAULT_VIDEO_EXTENSIONS, DEFAULT_IMAGE_EXTENSIONS
    video_extensions = frozenset(ext for ext in parsed_extensions if ext in DEFAULT_VIDEO_EXTENSIONS)
    image_extensions = frozenset(ext for ext in parsed_extensions if ext in DEFAULT_IMAGE_EXTENSIONS)
    return video_extensions, image_extensions


def _discover_seeded_paths(
    args: argparse.Namespace,
    mode: str,
    *,
    progress_emitter: ProgressEmitter | None,
    controller: PipelineController,
) -> tuple[list[Path], dict[str, int], float]:
    """Discover files once under controller ownership and return seeded paths."""
    from duplicates_detector.scanner import _scan_files_iter

    directories = [str(path) for path in _resolve_scan_directories(args)]
    recursive = not args.no_recursive
    exclude = args.exclude
    extensions = _resolve_scan_extensions(args, mode)

    paths: list[Path] = []
    counts_by_mode: dict[str, int] = {}
    video_extensions, image_extensions = _resolve_auto_pipeline_extensions(args)
    scan_start = time.monotonic()

    controller.enter_stage("scan")
    if progress_emitter is not None:
        progress_emitter.stage_start("scan")

    try:
        for path in _scan_files_iter(
            directories,
            recursive=recursive,
            extensions=extensions,
            exclude=exclude,
            pause_waiter=controller.wait_if_paused_blocking,
        ):
            if controller.is_cancelled:
                break
            paths.append(path)
            controller.files_discovered = len(paths)
            if mode == Mode.AUTO:
                suffix = path.suffix.lower()
                if suffix in video_extensions:
                    counts_by_mode["video"] = counts_by_mode.get("video", 0) + 1
                elif suffix in image_extensions:
                    counts_by_mode["image"] = counts_by_mode.get("image", 0) + 1
            if progress_emitter is not None:
                progress_emitter.progress("scan", current=len(paths))
    except Exception:
        raise
    else:
        elapsed = time.monotonic() - scan_start
        if mode != Mode.AUTO:
            counts_by_mode[mode] = len(paths)
        else:
            counts_by_mode.setdefault("video", 0)
            counts_by_mode.setdefault("image", 0)

        if progress_emitter is not None:
            progress_emitter.progress("scan", current=len(paths), total=len(paths), force=True)
            progress_emitter.stage_end("scan", total=len(paths), elapsed=elapsed)
        controller.complete_stage("scan")
        return paths, counts_by_mode, elapsed


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments for the ``scan`` subcommand."""
    parser.add_argument(
        "directories",
        nargs="*",
        default=None,
        help="Directories to scan (default: current directory)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        default=None,
        help="Only scan the top-level directory, not subdirectories",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        metavar="N",
        help="Minimum similarity score (0-100) to report (default: 50)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel workers (default: auto-detect based on CPU cores)",
    )
    parser.add_argument(
        "--extensions",
        type=str,
        default=None,
        metavar="EXT,EXT",
        help="Comma-separated video extensions to match (e.g., mp4,mkv,avi)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="PATTERN",
        help="Glob pattern to exclude paths (repeatable, e.g., --exclude '**/thumbnails/**')",
    )
    parser.add_argument(
        "--reference",
        action="append",
        default=None,
        metavar="DIR",
        help="Reference directory — files participate in comparison but are never deleted (repeatable)",
    )
    parser.add_argument(
        "--min-size",
        type=parse_size,
        default=None,
        metavar="SIZE",
        help="Minimum file size to include (e.g., 10MB, 1.5GB, 500KB)",
    )
    parser.add_argument(
        "--max-size",
        type=parse_size,
        default=None,
        metavar="SIZE",
        help="Maximum file size to include (e.g., 10MB, 1.5GB, 500KB)",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=None,
        metavar="SECS",
        help="Minimum duration in seconds to include",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SECS",
        help="Maximum duration in seconds to include",
    )
    parser.add_argument(
        "--min-resolution",
        type=str,
        default=None,
        metavar="WxH",
        help="Minimum resolution to include (e.g., 1280x720, 1920x1080)",
    )
    parser.add_argument(
        "--max-resolution",
        type=str,
        default=None,
        metavar="WxH",
        help="Maximum resolution to include (e.g., 1920x1080, 3840x2160)",
    )
    parser.add_argument(
        "--min-bitrate",
        type=str,
        default=None,
        metavar="RATE",
        help="Minimum container bitrate to include (e.g., 1000000, 5Mbps, 500kbps)",
    )
    parser.add_argument(
        "--max-bitrate",
        type=str,
        default=None,
        metavar="RATE",
        help="Maximum container bitrate to include (e.g., 20Mbps, 50000kbps)",
    )
    parser.add_argument(
        "--codec",
        type=str,
        default=None,
        metavar="CODEC,...",
        help="Restrict to specific video codecs (comma-separated, e.g., h264,hevc,av1)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=None,
        help="Show detailed progress information and full file paths",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=None,
        help="Suppress progress bars and summary output",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=None,
        help="Disable colored output",
    )
    parser.add_argument(
        "--machine-progress",
        action="store_true",
        default=None,
        help="Emit JSON-lines progress events to stderr (for GUI frontends)",
    )
    parser.add_argument(
        "--content",
        action="store_true",
        default=None,
        help="Enable content-based perceptual hashing for more accurate detection (slower)",
    )
    parser.add_argument(
        "--content-method",
        choices=["phash", "ssim", "clip", "simhash", "tfidf"],
        default=None,
        metavar="METHOD",
        help=(
            "Content method: phash (PDQ perceptual hash, default for video/image), "
            "ssim (structural similarity), clip (CLIP ViT-B/32 embeddings), "
            "simhash (SimHash text fingerprint, default for document), "
            "tfidf (TF-IDF cosine similarity, document only)"
        ),
    )
    parser.add_argument(
        "--rotation-invariant",
        action="store_true",
        default=None,
        help="Compute content hashes for all rotations and flips "
        "(4-8x slower, catches rotated/flipped duplicates). Only affects image mode.",
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        default=None,
        help="Enable Chromaprint audio fingerprinting for more accurate video duplicate detection (requires fpcalc)",
    )
    parser.add_argument(
        "--no-audio-cache",
        action="store_true",
        default=None,
        help="Disable disk cache for audio fingerprints (re-extract every run)",
    )
    parser.add_argument(
        "--no-content-cache",
        action="store_true",
        default=None,
        help="Disable disk cache for content hashes (re-extract every run)",
    )
    parser.add_argument(
        "--no-metadata-cache",
        action="store_true",
        default=None,
        help="Disable disk cache for metadata (re-run ffprobe on every file)",
    )
    parser.add_argument(
        "--no-pre-hash",
        action="store_true",
        default=None,
        help="Disable pre-hash computation (MD5 of first 4KB) used for byte-identical detection",
    )
    parser.add_argument(
        "--sidecar-extensions",
        type=str,
        default=None,
        metavar="EXTS",
        help="Comma-separated sidecar extensions to detect (default: .xmp,.aae,.thm,.json)",
    )
    parser.add_argument(
        "--no-sidecars",
        action="store_true",
        default=None,
        help="Disable sidecar file detection and co-deletion",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Directory for metadata and content hash caches (default: XDG_CACHE_HOME/duplicates-detector)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        metavar="N",
        help="Minimum similarity score (0-100) to include in results",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default=None,
        metavar="SPEC",
        help="Custom comparator weights (e.g., 'filename=50,duration=30,resolution=10,filesize=10')",
    )
    parser.add_argument(
        "--ignore-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to the ignored-pairs JSON file (default: $XDG_DATA_HOME/duplicates-detector/ignored-pairs.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["video", "image", "audio", "auto", "document"],
        default=None,
        metavar="MODE",
        help="Detection mode: video (default), image, audio, auto (mixed media), or document",
    )
    config_group = parser.add_argument_group("Configuration")
    config_group.add_argument(
        "--no-config",
        action="store_true",
        default=False,
        help="Ignore the config file for this run",
    )
    config_group.add_argument(
        "--profile",
        type=str,
        default=None,
        metavar="NAME",
        help="Load a named profile (from ~/.config/duplicates-detector/profiles/)",
    )


def _add_scan_only_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments specific to the ``scan`` subcommand."""
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactively review each pair and choose files to delete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview interactive deletions without removing files",
    )
    parser.add_argument(
        "--keep",
        choices=["newest", "oldest", "biggest", "smallest", "longest", "highest-res", "edited"],
        default=None,
        metavar="STRATEGY",
        help="Auto-select which file to keep: newest, oldest, biggest, smallest, longest, highest-res, edited",
    )
    parser.add_argument(
        "--action",
        choices=["delete", "trash", "move-to", "hardlink", "symlink", "reflink"],
        default=None,
        metavar="ACTION",
        help="Deletion method: delete (default), trash, move-to, hardlink, symlink, or reflink",
    )
    parser.add_argument(
        "--move-to-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Staging directory for --action move-to",
    )
    parser.add_argument(
        "--group",
        action="store_true",
        default=None,
        help="Group transitive duplicates into clusters instead of showing pairs",
    )
    parser.add_argument(
        "--sort",
        choices=["score", "size", "path", "mtime"],
        default=None,
        metavar="FIELD",
        help="Sort results by: score (default), size, path, or mtime",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of pairs (or groups) to display",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv", "shell", "html", "markdown"],
        default=None,
        metavar="FORMAT",
        help="Output format: table (default), json, csv, shell, html, or markdown",
    )
    parser.add_argument(
        "--json-envelope",
        action="store_true",
        default=None,
        help="Wrap JSON output in envelope with version, args, and stats",
    )
    parser.add_argument(
        "--embed-thumbnails",
        action="store_true",
        default=None,
        help="Embed base64 thumbnails in JSON envelope output (requires --json-envelope)",
    )
    parser.add_argument(
        "--thumbnail-size",
        type=str,
        default=None,
        metavar="WxH",
        help="Thumbnail dimensions as WxH (default: 160x90 video, 160x160 image)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    parser.add_argument(
        "--clear-ignored",
        action="store_true",
        default=False,
        help="Clear the ignored-pairs list and exit",
    )
    parser.add_argument(
        "--log",
        type=str,
        default=None,
        metavar="FILE",
        help="Append JSON-lines action log to FILE (one record per deletion/move/link)",
    )
    parser.add_argument(
        "--generate-undo",
        type=str,
        default=None,
        metavar="LOG_FILE",
        help="Generate a shell script to undo actions recorded in a --log file",
    )
    # Session management
    session_group = parser.add_argument_group("Session Management")
    session_group.add_argument(
        "--resume",
        metavar="SESSION_ID",
        default=None,
        help="Resume a previously paused scan session (mutually exclusive with directory arguments)",
    )
    session_group.add_argument(
        "--list-sessions",
        action="store_true",
        default=False,
        help="List available scan sessions and exit",
    )
    session_group.add_argument(
        "--list-sessions-json",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    session_group.add_argument(
        "--delete-session",
        metavar="SESSION_ID",
        default=None,
        help="Delete a specific saved session and exit",
    )
    session_group.add_argument(
        "--clear-sessions",
        action="store_true",
        default=False,
        help="Clear all saved scan sessions and exit",
    )
    session_group.add_argument(
        "--pause-file",
        metavar="PATH",
        default=None,
        help="Path to pause control file for GUI integration",
    )
    session_group.add_argument(
        "--cache-stats",
        action="store_true",
        default=False,
        help="Show cache hit/miss statistics in summary",
    )

    config_group = parser.add_argument_group("Scan Configuration")
    config_group.add_argument(
        "--save-config",
        action="store_true",
        default=False,
        help="Write current flags to config file and exit",
    )
    config_group.add_argument(
        "--show-config",
        action="store_true",
        default=False,
        help="Print the resolved config (after merge) and exit",
    )
    config_group.add_argument(
        "--save-profile",
        type=str,
        default=None,
        metavar="NAME",
        help="Save current flags as a named profile and exit",
    )
    config_group.add_argument(
        "--replay",
        type=str,
        default=None,
        metavar="FILE",
        help="Load previously generated JSON envelope output and re-apply filters/strategies without re-scanning",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (extracted for shtab completion support)."""
    parser = argparse.ArgumentParser(
        prog="duplicates-detector",
        description="Detect duplicate/similar video or image files by comparing metadata and filenames.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--print-completion",
        choices=["bash", "zsh", "fish"],
        default=None,
        metavar="SHELL",
        help="Print shell completion script and exit",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    scan_parser = subparsers.add_parser("scan", help="Scan directories for duplicates (default)")
    _add_common_args(scan_parser)
    _add_scan_only_args(scan_parser)

    return parser


_SUBCOMMANDS = frozenset({"scan"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    if argv is None:
        argv = sys.argv[1:]

    # Root-level action flags (--version, --print-completion) print and exit.
    # They must be handled before subcommand inference because argparse with
    # subparsers rejects unknown positionals before reaching the flag.
    # --help/-h at argv[0] shows root help; trailing --help gets prepended
    # with "scan" and shows scan-specific help.
    for i, arg in enumerate(argv):
        if arg == "--":
            break  # respect standard separator — everything after is positional
        if arg == "--version":
            parser.parse_args(["--version"])  # prints and exits
        if arg == "--print-completion" or arg.startswith("--print-completion="):
            # Forward the flag (and its value if separate) to the root parser.
            return parser.parse_args(argv[i : i + (1 if "=" in arg else 2)])
    if argv and argv[0] in {"-h", "--help"}:
        return parser.parse_args(argv)

    # Default subcommand: if the first positional isn't "scan",
    # prepend "scan" for backward compatibility.  We must skip option values
    # so that e.g. ``--profile myprofile`` (where the value is a profile name)
    # doesn't trick the heuristic.  We collect the set of no-value flags
    # (nargs==0: store_true, store_false, count, help, version) from all
    # subparsers; any other flag consumes the next token as its value.
    _no_value_flags: set[str] = set()
    _no_value_short_letters: set[str] = set()  # single chars for bundled-flag detection
    for sp_action in parser._subparsers._actions if parser._subparsers else []:
        choices = getattr(sp_action, "choices", None)
        if not isinstance(choices, dict):
            continue
        for sub_parser in choices.values():
            for action in sub_parser._actions:
                if action.option_strings and action.nargs == 0:
                    _no_value_flags.update(action.option_strings)
                    for opt in action.option_strings:
                        if len(opt) == 2 and opt[0] == "-" and opt[1] != "-":
                            _no_value_short_letters.add(opt[1])

    def _is_no_value_flag(arg: str) -> bool:
        """Return True if *arg* is a flag that does not consume the next token."""
        if "=" in arg:
            return True  # value is inline
        if arg in _no_value_flags:
            return True
        # Bundled short flags like ``-vq``: all letters must be known no-value.
        if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2:
            return all(ch in _no_value_short_letters for ch in arg[1:])
        return False

    first_positional = None
    first_positional_idx = -1
    skip_next = False
    for idx, arg in enumerate(argv):
        if arg == "--":
            break
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("-"):
            if not _is_no_value_flag(arg):
                skip_next = True
            continue
        first_positional = arg
        first_positional_idx = idx
        break

    if first_positional not in _SUBCOMMANDS:
        argv = ["scan", *argv]
    elif first_positional_idx > 0:
        # Subcommand found after flags (e.g. ``--no-config scan /tmp``).
        # Move it to the front so argparse sees it before subparser flags.
        argv = [argv[first_positional_idx], *argv[:first_positional_idx], *argv[first_positional_idx + 1 :]]

    args = parser.parse_args(argv)
    # Save original directories before normalization (needed by
    # _validate_generate_undo_conflicts to distinguish "no dirs" from ".").
    args._raw_directories = getattr(args, "directories", None)
    # Normalize: nargs="*" with default=None yields [] when no positionals
    # are given; normalize to ["."] for downstream code.
    if not getattr(args, "directories", None):
        args.directories = ["."]
    return args


def _is_reference(path: Path, reference_dirs: list[Path]) -> bool:
    """Check if *path* is inside any of the *reference_dirs*.

    Checks both the resolved and original path so that symlinks inside a
    reference directory are still treated as reference files even when
    their target lives outside the directory.
    """
    resolved = path.resolve()
    return any(resolved.is_relative_to(ref) or path.is_relative_to(ref) for ref in reference_dirs)


def _compute_space_recoverable(
    pairs: list[ScoredPair],
    groups: list[DuplicateGroup] | None,
) -> int:
    """Estimate bytes recoverable by deleting duplicate files.

    For group mode, sums all members except the largest per group.
    For pair mode, sums the smaller file in each pair.
    Deduplicates by resolved path to avoid double-counting.
    """
    if groups is not None:
        seen: set[Path] = set()
        total = 0
        for group in groups:
            has_ref = any(m.is_reference for m in group.members)
            if has_ref:
                # A reference file is always kept — all non-reference
                # members are recoverable.
                for m in group.members:
                    resolved = m.path.resolve()
                    if not m.is_reference and resolved not in seen:
                        seen.add(resolved)
                        total += m.file_size
            else:
                # No reference files — keep the largest, rest deletable.
                sizes = sorted(
                    [(m.file_size, m.path.resolve()) for m in group.members],
                    reverse=True,
                )
                for file_size, resolved in sizes[1:]:
                    if resolved not in seen:
                        seen.add(resolved)
                        total += file_size
        return total

    seen_pair: set[Path] = set()
    total_pair = 0
    for pair in pairs:
        a, b = pair.file_a, pair.file_b
        # Pick the smaller non-reference file as the deletion candidate.
        # If both are reference, nothing is recoverable.
        if a.is_reference and b.is_reference:
            continue
        if a.is_reference:
            candidate_size, candidate_path = b.file_size, b.path.resolve()
        elif b.is_reference or a.file_size <= b.file_size:
            candidate_size, candidate_path = a.file_size, a.path.resolve()
        else:
            candidate_size, candidate_path = b.file_size, b.path.resolve()
        if candidate_path not in seen_pair:
            seen_pair.add(candidate_path)
            total_pair += candidate_size
    return total_pair


def _parse_thumbnail_size(spec: str | None, mode: str) -> tuple[int, int] | None:
    """Parse a ``WxH`` thumbnail size spec, or return mode-appropriate defaults.

    Returns ``None`` when *mode* is ``"auto"`` and no explicit *spec* is given
    (the batch generator handles per-file defaults).
    """
    if spec is None:
        if mode == Mode.IMAGE:
            return (160, 160)
        if mode == Mode.AUTO:
            return None
        if mode == Mode.AUDIO:
            return (160, 160)
        return (160, 90)
    parts = spec.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid thumbnail size: {spec!r} (expected WxH, e.g. 160x90)")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"Invalid thumbnail size: {spec!r} (expected WxH, e.g. 160x90)") from None
    if w <= 0 or h <= 0:
        raise ValueError(f"Thumbnail dimensions must be positive: {spec!r}")
    return (w, h)


def _validate_weights(
    weights_spec: str, *, content: bool, console: Console, mode: str = Mode.VIDEO, audio: bool = False
) -> dict[str, float]:
    """Parse and validate a weights spec string.

    Returns the parsed weights dict on success, or raises SystemExit(1) with
    a user-friendly error message on failure.
    """
    from duplicates_detector.comparators import parse_weights

    try:
        weights_dict = parse_weights(weights_spec)
    except ValueError as e:
        console.print(f"[red]Error: --weights: {e}[/red]")
        raise SystemExit(1)

    if mode == Mode.IMAGE:
        expected_keys = {"filename", "resolution", "file_size", "exif"}
        if "duration" in weights_dict:
            console.print("[red]Error: --weights includes 'duration' but --mode image does not use duration[/red]")
            raise SystemExit(1)
        if "audio" in weights_dict:
            console.print("[red]Error: --weights includes 'audio' but image mode does not use audio[/red]")
            raise SystemExit(1)
        if "tags" in weights_dict:
            console.print("[red]Error: --weights includes 'tags' but image mode does not use tags[/red]")
            raise SystemExit(1)
    elif mode == Mode.DOCUMENT:
        expected_keys = {"filename", "file_size", "page_count", "doc_meta"}
        for key in ("duration", "resolution", "exif", "tags", "audio"):
            if key in weights_dict:
                console.print(f"[red]Error: --weights key '{key}' is not valid in document mode[/red]")
                raise SystemExit(1)
    elif mode == Mode.AUDIO:
        expected_keys = {"filename", "duration", "tags"}
        if "resolution" in weights_dict:
            console.print("[red]Error: --weights includes 'resolution' but audio mode does not use resolution[/red]")
            raise SystemExit(1)
        if "file_size" in weights_dict or "filesize" in weights_dict:
            console.print("[red]Error: --weights includes 'filesize' but audio mode does not use file_size[/red]")
            raise SystemExit(1)
        if "exif" in weights_dict:
            console.print("[red]Error: --weights includes 'exif' but audio mode does not use EXIF[/red]")
            raise SystemExit(1)
        if "content" in weights_dict:
            console.print("[red]Error: --weights includes 'content' but audio mode does not use content hashing[/red]")
            raise SystemExit(1)
    else:
        expected_keys = {"filename", "duration", "resolution", "file_size"}
        if "exif" in weights_dict:
            console.print("[red]Error: --weights includes 'exif' but video mode does not use EXIF[/red]")
            raise SystemExit(1)
        if "tags" in weights_dict:
            console.print("[red]Error: --weights includes 'tags' but video mode does not use tags[/red]")
            raise SystemExit(1)

    if mode != Mode.AUDIO:
        if content:
            expected_keys.add("content")
        elif "content" in weights_dict:
            console.print("[red]Error: --weights includes 'content' but --content is not set[/red]")
            raise SystemExit(1)

    if audio and mode not in (Mode.IMAGE,):
        expected_keys.add("audio")
    elif "audio" in weights_dict:
        console.print("[red]Error: --weights includes 'audio' but --audio is not set[/red]")
        raise SystemExit(1)

    # 'directory' is an optional boost key — not required but allowed in any mode
    allowed_keys = expected_keys | {"directory"}
    unknown = set(weights_dict.keys()) - allowed_keys
    if unknown:
        console.print(f"[red]Error: --weights has unknown keys: {', '.join(sorted(unknown))}[/red]")
        raise SystemExit(1)

    missing = expected_keys - set(weights_dict.keys())
    if missing:
        console.print(f"[red]Error: --weights is missing keys: {', '.join(sorted(missing))}[/red]")
        raise SystemExit(1)

    has_directory = "directory" in weights_dict and weights_dict["directory"] > 0
    total = sum(weights_dict.values())
    if not has_directory and abs(total - 100.0) > 0.01:
        console.print(f"[red]Error: --weights must sum to 100, got {total}[/red]")
        raise SystemExit(1)

    return weights_dict


def _validate_replay_conflicts(raw_args: argparse.Namespace, console: Console) -> None:
    """Check that scan-specific flags are not combined with --replay.

    Raises SystemExit(1) if conflicting flags are found.  Warns (but does
    not error) for ``mode`` and ``threshold`` if explicitly set on CLI.
    """
    conflicts: list[str] = []

    # Content flags
    for attr in (
        "content",
        "content_method",
        "rotation_invariant",
    ):
        if getattr(raw_args, attr, None) is not None:
            conflicts.append(f"--{attr.replace('_', '-')}")

    # Audio flags
    if getattr(raw_args, "audio", None) is not None:
        conflicts.append("--audio")
    if getattr(raw_args, "no_audio_cache", None) is not None:
        conflicts.append("--no-audio-cache")

    # Cache flags
    if getattr(raw_args, "no_metadata_cache", None) is not None:
        conflicts.append("--no-metadata-cache")
    if getattr(raw_args, "no_content_cache", None) is not None:
        conflicts.append("--no-content-cache")
    if getattr(raw_args, "cache_dir", None) is not None:
        conflicts.append("--cache-dir")

    # Filter flags
    for attr in (
        "min_size",
        "max_size",
        "min_duration",
        "max_duration",
        "min_resolution",
        "max_resolution",
        "min_bitrate",
        "max_bitrate",
        "codec",
    ):
        if getattr(raw_args, attr, None) is not None:
            conflicts.append(f"--{attr.replace('_', '-')}")

    # Other
    if getattr(raw_args, "exclude", None) is not None:
        conflicts.append("--exclude")
    if getattr(raw_args, "weights", None) is not None:
        conflicts.append("--weights")

    # Directories (only error when user explicitly provided dirs;
    # parser default is None → argparse yields [] for no positionals,
    # non-empty list for explicit positional args)
    if raw_args.directories is not None and len(raw_args.directories) > 0:
        conflicts.append("directories")

    if conflicts:
        console.print(
            f"[red]Error: --replay conflicts with: {', '.join(conflicts)}. "
            f"These flags are not applicable when replaying from a JSON file.[/red]"
        )
        raise SystemExit(1)

    # Warnings (not errors)
    if getattr(raw_args, "mode", None) is not None:
        console.print("[yellow]Warning: --mode is ignored in replay mode[/yellow]")
    if getattr(raw_args, "threshold", None) is not None:
        console.print("[yellow]Warning: --threshold is ignored in replay mode[/yellow]")


def _validate_generate_undo_conflicts(raw_args: argparse.Namespace, console: Console) -> None:
    """Check that scan/action flags are not combined with --generate-undo.

    Raises SystemExit(1) if conflicting flags are found.
    """
    conflicts: list[str] = []

    # Value-type flags (default=None, so not-None means explicitly set)
    for attr in (
        "keep",
        "action",
        "weights",
        "codec",
        "min_size",
        "max_size",
        "min_duration",
        "max_duration",
        "min_resolution",
        "max_resolution",
        "min_bitrate",
        "max_bitrate",
        "replay",
    ):
        if getattr(raw_args, attr, None) is not None:
            conflicts.append(f"--{attr.replace('_', '-')}")

    # Boolean flags (store_true, default=False or None)
    for attr in ("content", "audio", "interactive", "dry_run"):
        if getattr(raw_args, attr, None) is True:
            conflicts.append(f"--{attr.replace('_', '-')}")

    if getattr(raw_args, "exclude", None) is not None:
        conflicts.append("--exclude")
    if getattr(raw_args, "reference", None) is not None:
        conflicts.append("--reference")

    # Directories
    if raw_args.directories is not None and len(raw_args.directories) > 0:
        conflicts.append("directories")

    if conflicts:
        console.print(
            f"[red]Error: --generate-undo conflicts with: {', '.join(conflicts)}. "
            f"Scan and action flags are not applicable when generating an undo script.[/red]"
        )
        raise SystemExit(1)


def _validate_content_params(args: argparse.Namespace, console: Console, *, mode: str = Mode.VIDEO) -> None:
    """Validate content params (--content-method)."""
    if not args.content:
        return
    content_method = _default_content_method(args, mode)
    # Document mode only supports simhash/tfidf
    if mode == Mode.DOCUMENT and content_method in ("phash", "ssim", "clip"):
        console.print(
            f"[red]Error: --content-method {content_method} is not supported in document mode"
            " (use simhash or tfidf)[/red]"
        )
        raise SystemExit(1)
    # Non-document modes reject simhash/tfidf
    if mode != Mode.DOCUMENT and content_method in ("simhash", "tfidf"):
        console.print(f"[red]Error: --content-method {content_method} is only supported in document mode[/red]")
        raise SystemExit(1)
    if content_method == "tfidf":
        try:
            import sklearn  # noqa: F401
        except ImportError:
            console.print("[red]Error: --content-method tfidf requires scikit-learn: pip install scikit-learn[/red]")
            raise SystemExit(1)
    elif content_method == "ssim":
        try:
            import skimage  # noqa: F401
        except ImportError:
            console.print(
                '[red]Error: --content-method ssim requires scikit-image: pip install "duplicates-detector[ssim]"[/red]'
            )
            raise SystemExit(1)
    elif content_method == "clip":
        if mode == Mode.AUDIO:
            console.print("[red]Error: --content-method clip is not supported in audio mode[/red]")
            raise SystemExit(1)
        try:
            import onnxruntime  # noqa: F401  # type: ignore[import-not-found]
        except ImportError:
            console.print(
                '[red]Error: --content-method clip requires onnxruntime: pip install "duplicates-detector[clip]"[/red]'
            )
            raise SystemExit(1)
    if mode not in (Mode.IMAGE, Mode.AUTO, Mode.DOCUMENT):
        from duplicates_detector.content import check_ffmpeg

        try:
            check_ffmpeg()
        except RuntimeError:
            console.print("[red]Error: --content requires ffmpeg for video content hashing[/red]")
            raise SystemExit(1)
    elif mode == Mode.AUTO:
        from duplicates_detector.content import check_ffmpeg

        try:
            check_ffmpeg()
        except RuntimeError:
            console.print(
                "[yellow]Warning: ffmpeg not found; video content hashing will be skipped in auto mode[/yellow]"
            )


def _resolve_comparators(
    args: argparse.Namespace,
    *,
    mode: str,
    weights_dict: dict[str, float] | None,
) -> list | None:
    """Resolve the comparator list from CLI arguments and mode.

    This is the complex, mode-specific comparator resolution logic that
    was previously inlined in ``_run_single_pipeline``.  Returns the
    comparator list (or ``None`` for default comparators).
    """
    # Document mode has its own comparator resolution
    if mode == Mode.DOCUMENT:
        if args.content:
            if weights_dict:
                from duplicates_detector.comparators import get_weighted_document_content_comparators

                return get_weighted_document_content_comparators(weights_dict)
            from duplicates_detector.comparators import get_document_content_comparators

            return get_document_content_comparators()
        if weights_dict:
            from duplicates_detector.comparators import get_weighted_document_comparators

            return get_weighted_document_comparators(weights_dict)
        from duplicates_detector.comparators import get_document_comparators

        return get_document_comparators()

    audio = bool(args.audio) and mode not in (Mode.IMAGE,)
    comparators = None
    if args.content:
        content_method = getattr(args, "content_method", None) or "phash"

        if content_method == "ssim":
            if mode == Mode.IMAGE:
                from duplicates_detector.comparators import (
                    get_image_content_comparators,
                    get_weighted_image_content_comparators,
                )

                if weights_dict:
                    comparators = get_weighted_image_content_comparators(weights_dict)
                else:
                    comparators = get_image_content_comparators()
            else:
                if audio:
                    from duplicates_detector.comparators import (
                        get_audio_content_comparators,
                        get_weighted_audio_content_comparators,
                    )

                    if weights_dict:
                        comparators = get_weighted_audio_content_comparators(weights_dict)
                    else:
                        comparators = get_audio_content_comparators()
                else:
                    from duplicates_detector.comparators import get_content_comparators

                    if weights_dict:
                        from duplicates_detector.comparators import get_weighted_content_comparators

                        comparators = get_weighted_content_comparators(weights_dict)
                    else:
                        comparators = get_content_comparators()
        else:
            # pHash/PDQ/CLIP path — same comparator setup, different hash_stage dispatch
            if mode == Mode.IMAGE:
                from duplicates_detector.comparators import (
                    get_image_content_comparators,
                    get_weighted_image_content_comparators,
                )

                rotation_invariant = bool(args.rotation_invariant)
                if weights_dict:
                    comparators = get_weighted_image_content_comparators(
                        weights_dict, rotation_invariant=rotation_invariant
                    )
                else:
                    comparators = get_image_content_comparators(rotation_invariant=rotation_invariant)
            else:
                if audio:
                    from duplicates_detector.comparators import (
                        get_audio_content_comparators,
                        get_weighted_audio_content_comparators,
                    )

                    if weights_dict:
                        comparators = get_weighted_audio_content_comparators(weights_dict)
                    else:
                        comparators = get_audio_content_comparators()
                else:
                    from duplicates_detector.comparators import get_content_comparators

                    if weights_dict:
                        from duplicates_detector.comparators import get_weighted_content_comparators

                        comparators = get_weighted_content_comparators(weights_dict)
                    else:
                        comparators = get_content_comparators()
    elif mode == Mode.AUDIO and audio:
        from duplicates_detector.comparators import (
            get_audio_mode_fingerprint_comparators,
            get_weighted_audio_mode_fingerprint_comparators,
        )

        if weights_dict:
            comparators = get_weighted_audio_mode_fingerprint_comparators(weights_dict)
        else:
            comparators = get_audio_mode_fingerprint_comparators()
    elif mode == Mode.AUDIO:
        from duplicates_detector.comparators import (
            get_audio_mode_comparators,
            get_weighted_audio_mode_comparators,
        )

        if weights_dict:
            comparators = get_weighted_audio_mode_comparators(weights_dict)
        else:
            comparators = get_audio_mode_comparators()
    elif audio:
        from duplicates_detector.comparators import get_audio_comparators, get_weighted_audio_comparators

        if weights_dict:
            comparators = get_weighted_audio_comparators(weights_dict)
        else:
            comparators = get_audio_comparators()
    elif weights_dict:
        if mode == Mode.IMAGE:
            from duplicates_detector.comparators import get_weighted_image_comparators

            comparators = get_weighted_image_comparators(weights_dict)
        else:
            from duplicates_detector.comparators import get_weighted_comparators

            comparators = get_weighted_comparators(weights_dict)

    return comparators


def _run_single_pipeline(
    args: argparse.Namespace,
    *,
    pstats: PipelineStats,
    pipeline_start: float,
    mode: str,
    file_noun: str,
    weights_dict: dict[str, float] | None,
    progress_emitter: ProgressEmitter | None = None,
    cache_db: CacheDB | None = None,
    controller: PipelineController | None = None,
    pre_scanned_paths: list[Path] | None = None,
    pre_scan_elapsed: float | None = None,
) -> list[ScoredPair] | None:
    """Run the single-mode pipeline (video, image, or audio).

    Uses the async streaming pipeline from ``pipeline.py`` for the full
    scan -> extract -> filter -> hash -> audio -> score flow.

    Falls back to a legacy sequential path for SSIM content method, which
    is not yet supported by the async pipeline.

    Returns scored pairs, or ``None`` if fewer than 2 files survive
    filtering (caller should return early).
    """
    from duplicates_detector.scorer import compute_config_hash

    # Resolve comparators (complex, mode-specific logic)
    comparators = _resolve_comparators(args, mode=mode, weights_dict=weights_dict)

    # Compute config hash for scoring cache
    audio = bool(args.audio) and mode not in (Mode.IMAGE,)
    effective_weights = weights_dict or {}
    if not effective_weights and comparators:
        effective_weights = {c.name: c.weight for c in comparators}
    config_hash = compute_config_hash(
        effective_weights,
        has_content=bool(args.content),
        has_audio=audio,
        content_method=_default_content_method(args, mode),
        mode=mode,
    )

    # SSIM content method: async pipeline doesn't support SSIM frame extraction,
    # so fall back to the legacy sequential path.
    content_method = _default_content_method(args, mode)
    if args.content and content_method == "ssim":
        return _run_single_pipeline_ssim(
            args,
            pstats=pstats,
            pipeline_start=pipeline_start,
            mode=mode,
            file_noun=file_noun,
            comparators=comparators,
            config_hash=config_hash,
            progress_emitter=progress_emitter,
            cache_db=cache_db,
        )

    # Parse resolution/bitrate/codec filter args for pipeline config
    min_resolution = None
    max_resolution = None
    min_bitrate = None
    max_bitrate = None
    codecs = None
    try:
        if args.min_resolution:
            min_resolution = parse_resolution(args.min_resolution)
        if args.max_resolution:
            max_resolution = parse_resolution(args.max_resolution)
        if args.min_bitrate:
            min_bitrate = parse_bitrate(args.min_bitrate)
        if args.max_bitrate:
            max_bitrate = parse_bitrate(args.max_bitrate)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    if args.codec:
        codecs = frozenset(c.strip().lower() for c in args.codec.split(","))

    # Build reference dirs
    reference_dirs: list[Path] | None = None
    if args.reference:
        reference_dirs = list(dict.fromkeys(p for d in args.reference for p in (Path(d), Path(d).resolve())))

    # Determine extensions
    extensions = _resolve_scan_extensions(args, mode)

    # Use the provided controller or create a fresh one
    if controller is None:
        ctrl = PipelineController()
    else:
        ctrl = controller

    # Content hashing params
    rotation_invariant = bool(args.rotation_invariant) if mode == Mode.IMAGE else False

    # Run the async pipeline (pause file watching is managed by the
    # caller's threading watcher — pass pause_file=None to avoid a
    # redundant asyncio watcher inside run_pipeline).
    result = asyncio.run(
        run_pipeline(
            directories=_resolve_scan_directories(args),
            recursive=not args.no_recursive,
            extensions=extensions,
            exclude=args.exclude,
            mode=mode,
            workers=args.workers or 0,
            cache=cache_db,
            progress=progress_emitter,
            controller=ctrl,
            # Filter params
            min_size=args.min_size,
            max_size=args.max_size,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            min_resolution=min_resolution,
            max_resolution=max_resolution,
            min_bitrate=min_bitrate,
            max_bitrate=max_bitrate,
            codecs=codecs,
            # Content hashing
            content=bool(args.content) and content_method != "ssim",
            rotation_invariant=rotation_invariant,
            content_method=content_method,
            # Pre-hash control
            no_pre_hash=bool(getattr(args, "no_pre_hash", False)),
            # Audio
            audio=audio,
            # Scoring
            comparators=comparators,
            threshold=args.threshold,
            config_hash=config_hash,
            # Reference
            reference_dirs=reference_dirs,
            # Sidecar
            no_sidecars=bool(getattr(args, "no_sidecars", False)),
            sidecar_extensions=getattr(args, "sidecar_extensions", None),
            # Pause
            pause_file=None,
            pre_scanned_paths=pre_scanned_paths,
            seeded_scan_time=pre_scan_elapsed,
            seeded_discovered_paths=set(pre_scanned_paths) if pre_scanned_paths is not None else None,
        )
    )
    pairs = result.pairs

    # Fill pstats from real pipeline stats (not approximations).
    pstats.scan_time = result.scan_time
    pstats.files_scanned = result.files_scanned
    pstats.discovered_paths = result.discovered_paths
    pstats.extract_time = result.extract_time
    pstats.filter_time = result.filter_time
    pstats.content_hash_time = result.content_hash_time
    pstats.audio_fingerprint_time = result.audio_fingerprint_time
    pstats.scoring_time = result.scoring_time
    pstats.total_pairs_scored = result.total_pairs_scored
    pstats.files_after_filter = result.files_after_filter
    pstats.content_mode = bool(args.content)
    if cache_db is not None:
        stats = cache_db.stats()
        pstats.metadata_cache_hits = stats.get("metadata_hits", 0)
        pstats.metadata_cache_misses = stats.get("metadata_misses", 0)
        pstats.metadata_cache_enabled = True
        if args.content:
            pstats.content_cache_enabled = True
            pstats.content_cache_hits = stats.get("content_hits", 0)
            pstats.content_cache_misses = stats.get("content_misses", 0)
    else:
        pstats.metadata_cache_enabled = False

    # Empty list is a valid result (no duplicates found); only return None
    # for the SSIM fallback path where metadata < 2 is an early exit.
    return pairs


def _run_single_pipeline_ssim(
    args: argparse.Namespace,
    *,
    pstats: PipelineStats,
    pipeline_start: float,
    mode: str,
    file_noun: str,
    comparators: list | None,
    config_hash: str,
    progress_emitter: ProgressEmitter | None = None,
    cache_db: CacheDB | None = None,
) -> list[ScoredPair] | None:
    """Legacy sequential path for SSIM content method.

    The async pipeline does not support SSIM frame extraction, so this
    preserves the original sequential metadata -> filter -> SSIM -> score flow.
    """
    from duplicates_detector.metadata import extract_all, extract_all_audio, extract_all_images

    # Determine extensions and scan directories
    all_dirs = args.directories + (args.reference or [])
    if args.extensions:
        extensions: frozenset[str] | None = frozenset(
            f".{ext.strip().lstrip('.').lower()}" for ext in args.extensions.split(",")
        )
    elif mode == Mode.IMAGE:
        extensions = DEFAULT_IMAGE_EXTENSIONS
    elif mode == Mode.AUDIO:
        extensions = DEFAULT_AUDIO_EXTENSIONS
    else:
        extensions = None

    if progress_emitter is not None:
        progress_emitter.stage_start("scan")
    scan_t0 = time.monotonic()
    files = find_video_files(
        all_dirs,
        recursive=not args.no_recursive,
        extensions=extensions,
        exclude=args.exclude,
        quiet=True,
    )
    pstats.scan_time = time.monotonic() - scan_t0
    if progress_emitter is not None:
        progress_emitter.stage_end("scan", total=len(files), elapsed=pstats.scan_time)
    pstats.files_scanned = len(files)
    pstats.discovered_paths = set(files)

    # Extract metadata
    t0 = time.monotonic()
    if mode == Mode.IMAGE:
        metadata = extract_all_images(
            files,
            workers=args.workers,
            verbose=args.verbose,
            cache=None,
            cache_db=cache_db,
            quiet=args.quiet,
            progress_emitter=progress_emitter,
        )
    elif mode == Mode.AUDIO:
        metadata = extract_all_audio(
            files,
            workers=args.workers,
            verbose=args.verbose,
            cache=None,
            cache_db=cache_db,
            quiet=args.quiet,
            progress_emitter=progress_emitter,
        )
    else:
        metadata = extract_all(
            files,
            workers=args.workers,
            verbose=args.verbose,
            cache=None,
            cache_db=cache_db,
            quiet=args.quiet,
            progress_emitter=progress_emitter,
        )
    pstats.extract_time = time.monotonic() - t0
    pstats.extraction_failures = len(files) - len(metadata)

    if cache_db is not None:
        stats = cache_db.stats()
        pstats.metadata_cache_hits = stats.get("metadata_hits", 0)
        pstats.metadata_cache_misses = stats.get("metadata_misses", 0)
        pstats.metadata_cache_enabled = True
    else:
        pstats.metadata_cache_enabled = False

    # Tag reference files
    if args.reference:
        ref_dirs = list(dict.fromkeys(p for d in args.reference for p in (Path(d), Path(d).resolve())))
        metadata = [replace(m, is_reference=True) if _is_reference(m.path, ref_dirs) else m for m in metadata]

    # Filter
    min_resolution = None
    max_resolution = None
    min_bitrate = None
    max_bitrate = None
    codecs_set = None
    try:
        if args.min_resolution:
            min_resolution = parse_resolution(args.min_resolution)
        if args.max_resolution:
            max_resolution = parse_resolution(args.max_resolution)
        if args.min_bitrate:
            min_bitrate = parse_bitrate(args.min_bitrate)
        if args.max_bitrate:
            max_bitrate = parse_bitrate(args.max_bitrate)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    if args.codec:
        codecs_set = frozenset(c.strip().lower() for c in args.codec.split(","))

    if progress_emitter is not None:
        progress_emitter.stage_start("filter")
    filter_t0 = time.monotonic()
    if any(
        v is not None
        for v in (
            args.min_size,
            args.max_size,
            args.min_duration,
            args.max_duration,
            min_resolution,
            max_resolution,
            min_bitrate,
            max_bitrate,
            codecs_set,
        )
    ):
        metadata = filter_metadata(
            metadata,
            min_size=args.min_size,
            max_size=args.max_size,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            min_resolution=min_resolution,
            max_resolution=max_resolution,
            min_bitrate=min_bitrate,
            max_bitrate=max_bitrate,
            codecs=codecs_set,
        )
    pstats.filter_time = time.monotonic() - filter_t0
    if progress_emitter is not None:
        progress_emitter.stage_end("filter", total=len(metadata), elapsed=pstats.filter_time)

    pstats.files_after_filter = len(metadata)

    if len(metadata) < 2:
        if not args.quiet:
            console.print("[yellow]Could not extract metadata from enough files.[/yellow]")
            pstats.total_time = time.monotonic() - pipeline_start
            print_summary(pstats, console=console)
        return None

    # SSIM frame extraction
    pstats.content_mode = True
    t0 = time.monotonic()

    if mode == Mode.IMAGE:
        from duplicates_detector.content import extract_all_image_ssim_frames

        if args.verbose:
            console.print(f"Extracting frames (SSIM) from [bold]{len(metadata)}[/bold] {file_noun}s...")
        metadata = extract_all_image_ssim_frames(
            metadata,
            workers=args.workers,
            verbose=args.verbose,
            quiet=args.quiet,
            progress_emitter=progress_emitter,
        )
    else:
        from duplicates_detector.content import extract_all_ssim_frames

        if args.verbose:
            console.print(f"Extracting frames (SSIM) from [bold]{len(metadata)}[/bold] {file_noun}s...")
        metadata = extract_all_ssim_frames(
            metadata,
            workers=args.workers,
            verbose=args.verbose,
            quiet=args.quiet,
            progress_emitter=progress_emitter,
        )

    pstats.content_hash_time = time.monotonic() - t0
    pstats.content_cache_enabled = False

    # Audio fingerprints (if --audio, video mode only)
    audio = bool(args.audio) and mode not in (Mode.IMAGE,)
    if audio:
        from duplicates_detector.audio import extract_all_audio_fingerprints

        t0 = time.monotonic()
        if args.verbose:
            console.print(f"Extracting audio fingerprints from [bold]{len(metadata)}[/bold] {file_noun}s...")
        metadata = extract_all_audio_fingerprints(
            metadata,
            workers=args.workers,
            verbose=args.verbose,
            cache=None,
            quiet=args.quiet,
            progress_emitter=progress_emitter,
        )
        pstats.audio_fingerprint_time = time.monotonic() - t0

    # Score
    scoring_stats: dict[str, int] = {}
    t0 = time.monotonic()
    pairs = find_duplicates(
        metadata,
        threshold=args.threshold,
        workers=args.workers,
        verbose=args.verbose,
        comparators=comparators,
        stats=scoring_stats,
        quiet=args.quiet,
        mode=mode,
        content_method=_default_content_method(args, mode) if getattr(args, "content", False) else None,
        progress_emitter=progress_emitter,
    )
    pstats.scoring_time = time.monotonic() - t0
    pstats.total_pairs_scored = scoring_stats.get("total_pairs_scored", 0)

    return pairs


def _run_auto_pipeline(
    args: argparse.Namespace,
    *,
    pstats: PipelineStats,
    pipeline_start: float,
    progress_emitter: ProgressEmitter | None = None,
    cache_db: CacheDB | None = None,
    controller: PipelineController | None = None,
    _pause_state: dict[str, Any] | None = None,
    pre_scanned_paths: list[Path] | None = None,
    pre_scan_elapsed: float | None = None,
    discovered_counts_by_mode: dict[str, int] | None = None,
) -> list[ScoredPair] | None:
    """Run the auto-mode dual sub-pipeline (video + image) concurrently.

    Both sub-pipelines run concurrently via ``asyncio.gather()`` in a single
    event loop.  Live unified progress is emitted via an
    :class:`~duplicates_detector.progress.AggregatingProgressEmitter`.

    Returns merged pairs sorted by score, or ``None`` if the caller should
    return early.
    """
    from duplicates_detector.pipeline import _CANONICAL_STAGES, compute_visible_stage_set
    from duplicates_detector.scorer import compute_config_hash

    # Parse filter args (shared across both sub-pipelines)
    min_resolution = None
    max_resolution = None
    min_bitrate = None
    max_bitrate = None
    codecs = None
    try:
        if args.min_resolution:
            min_resolution = parse_resolution(args.min_resolution)
        if args.max_resolution:
            max_resolution = parse_resolution(args.max_resolution)
        if args.min_bitrate:
            min_bitrate = parse_bitrate(args.min_bitrate)
        if args.max_bitrate:
            max_bitrate = parse_bitrate(args.max_bitrate)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    if args.codec:
        codecs = frozenset(c.strip().lower() for c in args.codec.split(","))

    # Reference dirs
    reference_dirs: list[Path] | None = None
    if args.reference:
        reference_dirs = list(dict.fromkeys(p for d in args.reference for p in (Path(d), Path(d).resolve())))

    audio = bool(args.audio)
    content_method = getattr(args, "content_method", None) or "phash"
    rotation_invariant = bool(args.rotation_invariant)
    all_dirs = _resolve_scan_directories(args)
    video_extensions, image_extensions = _resolve_auto_pipeline_extensions(args)
    seeded_video_paths = (
        [path for path in pre_scanned_paths if path.suffix.lower() in video_extensions]
        if pre_scanned_paths is not None
        else None
    )
    seeded_image_paths = (
        [path for path in pre_scanned_paths if path.suffix.lower() in image_extensions]
        if pre_scanned_paths is not None
        else None
    )

    # SSIM fallback: the async pipeline does not support SSIM, so delegate
    # to the legacy auto-mode path for SSIM content method.
    if args.content and content_method == "ssim":
        return _run_auto_pipeline_ssim(
            args,
            pstats=pstats,
            pipeline_start=pipeline_start,
            progress_emitter=progress_emitter,
            cache_db=cache_db,
        )

    # --- Build kwargs for each sub-pipeline ---
    base_ctrl = controller or PipelineController()

    # Shared filter/content kwargs
    common_kwargs: dict[str, Any] = {
        "directories": all_dirs,
        "recursive": not args.no_recursive,
        "exclude": args.exclude,
        "workers": args.workers or 0,
        "cache": cache_db,
        "min_size": args.min_size,
        "max_size": args.max_size,
        "min_duration": args.min_duration,
        "max_duration": args.max_duration,
        "min_resolution": min_resolution,
        "max_resolution": max_resolution,
        "min_bitrate": min_bitrate,
        "max_bitrate": max_bitrate,
        "codecs": codecs,
        "threshold": args.threshold,
        "reference_dirs": reference_dirs,
        "no_sidecars": bool(getattr(args, "no_sidecars", False)),
        "sidecar_extensions": getattr(args, "sidecar_extensions", None),
        "no_pre_hash": bool(getattr(args, "no_pre_hash", False)),
        "pause_file": None,  # managed at outer level for auto mode
    }

    video_comparators = _resolve_comparators(args, mode=Mode.VIDEO, weights_dict=None)
    video_weights = {c.name: c.weight for c in video_comparators} if video_comparators else {}
    video_kwargs: dict[str, Any] = {
        **common_kwargs,
        "extensions": video_extensions,
        "mode": Mode.VIDEO,
        "content": bool(args.content),
        "rotation_invariant": False,
        "content_method": content_method,
        "audio": audio,
        "comparators": video_comparators,
        "config_hash": compute_config_hash(
            video_weights,
            has_content=bool(args.content),
            has_audio=audio,
            content_method=content_method,
            mode=Mode.VIDEO,
        ),
    }

    image_comparators = _resolve_comparators(args, mode=Mode.IMAGE, weights_dict=None)
    image_weights = {c.name: c.weight for c in image_comparators} if image_comparators else {}
    image_kwargs: dict[str, Any] = {
        **common_kwargs,
        "extensions": image_extensions,
        "mode": Mode.IMAGE,
        "content": bool(args.content),
        "rotation_invariant": rotation_invariant,
        "content_method": content_method,
        "audio": False,
        "comparators": image_comparators,
        "config_hash": compute_config_hash(
            image_weights,
            has_content=bool(args.content),
            has_audio=False,
            content_method=content_method,
            mode=Mode.IMAGE,
        ),
    }

    # --- Controller and progress setup ---
    # Always set up both sub-pipelines with linked controllers and
    # aggregating progress.  If one type has no files, its pipeline
    # completes instantly (scan finds nothing, sentinel propagates).
    video_ctrl = base_ctrl
    image_ctrl = base_ctrl.linked()
    aggregator = None
    if progress_emitter is not None:
        from duplicates_detector.progress import AggregatingProgressEmitter

        video_visible = compute_visible_stage_set(
            mode=Mode.VIDEO,
            has_content=bool(args.content),
            has_audio=audio,
            content_method=content_method,
        )
        image_visible = compute_visible_stage_set(
            mode=Mode.IMAGE,
            has_content=bool(args.content),
            has_audio=False,
            content_method=content_method,
        )
        expected_stage_counts = {
            stage: int(stage in video_visible) + int(stage in image_visible) for stage in _CANONICAL_STAGES
        }
        expected_stage_counts["scan"] = 0
        aggregator = AggregatingProgressEmitter(
            progress_emitter,
            sub_count=2,
            expected_stage_counts=expected_stage_counts,
        )
        video_progress: Any = aggregator.create_sub_emitter(0)
        image_progress: Any = aggregator.create_sub_emitter(1)
    else:
        video_progress = None
        image_progress = None

    # Store aggregator in _pause_state for unified session persistence
    if aggregator is not None and _pause_state is not None:
        _pause_state["aggregator"] = aggregator

    # --- Initialize empty results ---
    video_result = PipelineResult(pairs=[])
    image_result = PipelineResult(pairs=[])

    # --- Run concurrently in a single event loop ---
    async def _run_concurrent() -> dict[str, PipelineResult]:
        # Both sub-pipelines always launch; empty ones complete instantly.
        video_coro = run_pipeline(
            **video_kwargs,
            progress=video_progress,
            controller=video_ctrl,
            pre_scanned_paths=seeded_video_paths,
            seeded_scan_time=pre_scan_elapsed,
            seeded_discovered_paths=set(seeded_video_paths or []),
            expected_file_count=(discovered_counts_by_mode or {}).get("video"),
        )
        image_coro = run_pipeline(
            **image_kwargs,
            progress=image_progress,
            controller=image_ctrl,
            pre_scanned_paths=seeded_image_paths,
            seeded_scan_time=pre_scan_elapsed,
            seeded_discovered_paths=set(seeded_image_paths or []),
            expected_file_count=(discovered_counts_by_mode or {}).get("image"),
        )

        # Pause-file watching is managed by the caller's threading watcher
        # which spans the entire scan lifecycle. No async watcher needed.
        results = await asyncio.gather(video_coro, image_coro)
        return {"video": results[0], "image": results[1]}

    result_map = asyncio.run(_run_concurrent())
    video_result = result_map.get("video", video_result)
    image_result = result_map.get("image", image_result)

    # --- Merge results ---
    pairs: list[ScoredPair] = list(video_result.pairs) + list(image_result.pairs)
    pairs.sort(key=lambda p: p.total_score, reverse=True)

    pstats.content_mode = bool(args.content)
    if pre_scanned_paths is not None:
        pstats.files_scanned = len(pre_scanned_paths)
        pstats.scan_time = pre_scan_elapsed or 0.0
        pstats.discovered_paths = set(pre_scanned_paths)
    else:
        pstats.files_scanned = video_result.files_scanned + image_result.files_scanned
        pstats.scan_time = max(video_result.scan_time, image_result.scan_time)
        pstats.discovered_paths = video_result.discovered_paths | image_result.discovered_paths
    pstats.total_pairs_scored = video_result.total_pairs_scored + image_result.total_pairs_scored
    pstats.files_after_filter = video_result.files_after_filter + image_result.files_after_filter
    pstats.extract_time = max(video_result.extract_time, image_result.extract_time)
    pstats.scoring_time = max(video_result.scoring_time, image_result.scoring_time)
    if cache_db is not None:
        stats = cache_db.stats()
        pstats.metadata_cache_hits = stats.get("metadata_hits", 0)
        pstats.metadata_cache_misses = stats.get("metadata_misses", 0)
        pstats.metadata_cache_enabled = True
        if args.content:
            pstats.content_cache_enabled = True
            pstats.content_cache_hits = stats.get("content_hits", 0)
            pstats.content_cache_misses = stats.get("content_misses", 0)
    else:
        pstats.metadata_cache_enabled = False

    return pairs


def _run_auto_pipeline_ssim(
    args: argparse.Namespace,
    *,
    pstats: PipelineStats,
    pipeline_start: float,
    progress_emitter: ProgressEmitter | None = None,
    cache_db: CacheDB | None = None,
) -> list[ScoredPair] | None:
    """Legacy sequential path for auto-mode SSIM content method.

    The async pipeline does not support SSIM frame extraction, so this
    preserves the original sequential dual-pipeline flow.
    """
    from duplicates_detector.metadata import extract_all, extract_all_images

    # Discover files internally (legacy path does its own scan).
    all_dirs = args.directories + (args.reference or [])
    if progress_emitter is not None:
        progress_emitter.stage_start("scan")
    scan_t0 = time.monotonic()
    media_files = find_media_files(
        all_dirs,
        recursive=not args.no_recursive,
        exclude=args.exclude,
        quiet=True,
    )
    if args.extensions:
        video_extensions, image_extensions = _resolve_auto_pipeline_extensions(args)
        allowed_extensions = video_extensions | image_extensions
        media_files = [mf for mf in media_files if mf.path.suffix.lower() in allowed_extensions]
    video_paths = [mf.path for mf in media_files if mf.media_type == "video"]
    image_paths = [mf.path for mf in media_files if mf.media_type == "image"]
    pstats.scan_time = time.monotonic() - scan_t0
    if progress_emitter is not None:
        progress_emitter.stage_end("scan", total=len(video_paths) + len(image_paths), elapsed=pstats.scan_time)
    pstats.files_scanned = len(video_paths) + len(image_paths)

    sub_quiet = args.quiet or progress_emitter is not None

    # Extract metadata for each type
    extract_total = len(video_paths) + len(image_paths)
    if progress_emitter is not None:
        progress_emitter.stage_start("extract", total=extract_total)
    t0 = time.monotonic()
    video_metadata = (
        extract_all(
            video_paths,
            workers=args.workers,
            verbose=args.verbose,
            cache=None,
            cache_db=cache_db,
            quiet=sub_quiet,
            progress_emitter=None,
        )
        if video_paths
        else []
    )
    if progress_emitter is not None and video_paths:
        progress_emitter.progress("extract", current=len(video_paths), total=extract_total, force=True)
    image_metadata = (
        extract_all_images(
            image_paths,
            workers=args.workers,
            verbose=args.verbose,
            cache=None,
            cache_db=cache_db,
            quiet=sub_quiet,
            progress_emitter=None,
        )
        if image_paths
        else []
    )
    if progress_emitter is not None:
        progress_emitter.progress("extract", current=extract_total, total=extract_total, force=True)
        progress_emitter.stage_end("extract", total=extract_total, elapsed=time.monotonic() - t0)
    all_metadata = list(video_metadata) + list(image_metadata)
    pstats.extract_time = time.monotonic() - t0
    pstats.extraction_failures = (len(video_paths) + len(image_paths)) - len(all_metadata)

    if cache_db is not None:
        db_stats = cache_db.stats()
        pstats.metadata_cache_hits = db_stats.get("metadata_hits", 0)
        pstats.metadata_cache_misses = db_stats.get("metadata_misses", 0)
        pstats.metadata_cache_enabled = True
    else:
        pstats.metadata_cache_enabled = False

    # Tag reference files
    if args.reference:
        ref_dirs = list(dict.fromkeys(p for d in args.reference for p in (Path(d), Path(d).resolve())))
        all_metadata = [replace(m, is_reference=True) if _is_reference(m.path, ref_dirs) else m for m in all_metadata]

    # Filter
    min_resolution = None
    max_resolution = None
    min_bitrate = None
    max_bitrate = None
    codecs = None
    try:
        if args.min_resolution:
            min_resolution = parse_resolution(args.min_resolution)
        if args.max_resolution:
            max_resolution = parse_resolution(args.max_resolution)
        if args.min_bitrate:
            min_bitrate = parse_bitrate(args.min_bitrate)
        if args.max_bitrate:
            max_bitrate = parse_bitrate(args.max_bitrate)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    if args.codec:
        codecs = frozenset(c.strip().lower() for c in args.codec.split(","))

    if progress_emitter is not None:
        progress_emitter.stage_start("filter")
    filter_t0 = time.monotonic()
    if any(
        v is not None
        for v in (
            args.min_size,
            args.max_size,
            args.min_duration,
            args.max_duration,
            min_resolution,
            max_resolution,
            min_bitrate,
            max_bitrate,
            codecs,
        )
    ):
        all_metadata = filter_metadata(
            all_metadata,
            min_size=args.min_size,
            max_size=args.max_size,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            min_resolution=min_resolution,
            max_resolution=max_resolution,
            min_bitrate=min_bitrate,
            max_bitrate=max_bitrate,
            codecs=codecs,
        )
    pstats.filter_time = time.monotonic() - filter_t0
    if progress_emitter is not None:
        progress_emitter.stage_end("filter", total=len(all_metadata), elapsed=pstats.filter_time)

    pstats.files_after_filter = len(all_metadata)

    if len(all_metadata) < 2:
        if not args.quiet:
            console.print("[yellow]Could not extract metadata from enough files.[/yellow]")
            pstats.total_time = time.monotonic() - pipeline_start
            print_summary(pstats, console=console)
        return None

    # Re-split by extension after filtering
    video_metadata_list = [m for m in all_metadata if m.path.suffix.lower() in DEFAULT_VIDEO_EXTENSIONS]
    image_metadata_list = [m for m in all_metadata if m.path.suffix.lower() not in DEFAULT_VIDEO_EXTENSIONS]

    # SSIM frame extraction
    audio = bool(args.audio)
    pstats.content_mode = True
    video_comparators = None
    image_comparators = None

    ssim_total = len(video_metadata_list) + len(image_metadata_list)
    if progress_emitter is not None:
        progress_emitter.stage_start("ssim_extract", total=ssim_total)
    t0 = time.monotonic()

    if video_metadata_list:
        from duplicates_detector.content import extract_all_ssim_frames

        video_metadata_list = list(
            extract_all_ssim_frames(
                video_metadata_list,
                workers=args.workers,
                verbose=args.verbose,
                quiet=sub_quiet,
                progress_emitter=None,
            )
        )
        if progress_emitter is not None:
            progress_emitter.progress("ssim_extract", current=len(video_metadata_list), total=ssim_total, force=True)
        if audio:
            from duplicates_detector.comparators import get_audio_content_comparators

            video_comparators = get_audio_content_comparators()
        else:
            from duplicates_detector.comparators import get_content_comparators

            video_comparators = get_content_comparators()

    if image_metadata_list:
        from duplicates_detector.content import extract_all_image_ssim_frames
        from duplicates_detector.comparators import get_image_content_comparators

        image_metadata_list = list(
            extract_all_image_ssim_frames(
                image_metadata_list,
                workers=args.workers,
                verbose=args.verbose,
                quiet=sub_quiet,
                progress_emitter=None,
            )
        )
        image_comparators = get_image_content_comparators()

    pstats.content_hash_time = time.monotonic() - t0
    pstats.content_cache_enabled = False
    if progress_emitter is not None:
        progress_emitter.progress("ssim_extract", current=ssim_total, total=ssim_total, force=True)
        progress_emitter.stage_end("ssim_extract", total=ssim_total, elapsed=pstats.content_hash_time)

    # Score each type separately
    if progress_emitter is not None:
        progress_emitter.stage_start("score")
    score_t0 = time.monotonic()
    pairs: list[ScoredPair] = []
    total_pairs_scored = 0
    score_progress_current = 0
    score_progress_total = 0

    if len(video_metadata_list) >= 2:
        video_scoring_stats: dict[str, int] = {}
        t0 = time.monotonic()
        video_pairs = find_duplicates(
            video_metadata_list,
            threshold=args.threshold,
            workers=args.workers,
            verbose=args.verbose,
            comparators=video_comparators,
            stats=video_scoring_stats,
            quiet=args.quiet,
            mode=Mode.VIDEO,
            progress_emitter=progress_emitter,
            _emit_score_stage=False,
        )
        pstats.scoring_time += time.monotonic() - t0
        total_pairs_scored += video_scoring_stats.get("total_pairs_scored", 0)
        score_progress_current = video_scoring_stats.get("_progress_current", 0)
        score_progress_total = video_scoring_stats.get("_progress_total", 0)
        pairs.extend(video_pairs)

    if len(image_metadata_list) >= 2:
        image_scoring_stats: dict[str, int] = {}
        t0 = time.monotonic()
        image_pairs_result = find_duplicates(
            image_metadata_list,
            threshold=args.threshold,
            workers=args.workers,
            verbose=args.verbose,
            comparators=image_comparators,
            stats=image_scoring_stats,
            quiet=args.quiet,
            mode=Mode.IMAGE,
            progress_emitter=progress_emitter,
            _emit_score_stage=False,
            _progress_offset=score_progress_current,
            _total_offset=score_progress_total,
        )
        pstats.scoring_time += time.monotonic() - t0
        total_pairs_scored += image_scoring_stats.get("total_pairs_scored", 0)
        score_progress_total = image_scoring_stats.get("_progress_total", score_progress_total)
        pairs.extend(image_pairs_result)

    if progress_emitter is not None:
        progress_emitter.stage_end(
            "score", total=score_progress_total, elapsed=time.monotonic() - score_t0, pairs_found=len(pairs)
        )

    pairs.sort(key=lambda p: p.total_score, reverse=True)
    pstats.total_pairs_scored = total_pairs_scored
    return pairs


def _run_replay(
    replay_path: Path,
    *,
    reference_dirs: list[str] | None,
    verbose: bool,
    quiet: bool,
    pstats: PipelineStats,
) -> tuple[list[ScoredPair], str | None]:
    """Load pairs from a JSON envelope and return (pairs, envelope_mode).

    *envelope_mode* is the ``args.mode`` stored in the source envelope, or
    ``None`` when it cannot be determined.  Raises ``SystemExit(1)`` on
    errors.
    """
    import json as _replay_json

    if not replay_path.is_file():
        console.print(f"[red]Error: replay file not found: {replay_path}[/red]")
        raise SystemExit(1)
    try:
        _envelope_data = _replay_json.loads(replay_path.read_text(encoding="utf-8"))
        pairs = load_replay_json(replay_path, _data=_envelope_data)
    except (ValueError, KeyError, _replay_json.JSONDecodeError) as exc:
        console.print(f"[red]Error loading replay file: {exc}[/red]")
        raise SystemExit(1) from None

    # Extract original mode from envelope for thumbnail dispatch
    envelope_mode: str | None = None
    _envelope_args = _envelope_data.get("args") if isinstance(_envelope_data, dict) else None
    if isinstance(_envelope_args, dict):
        _rm = _envelope_args.get("mode")
        if _rm in tuple(Mode):
            envelope_mode = _rm

    if not pairs:
        if not quiet:
            console.print("[yellow]No pairs found in replay file.[/yellow]")
        return [], envelope_mode

    # Apply --reference tags
    if reference_dirs:
        ref_dirs = list(dict.fromkeys(p for d in reference_dirs for p in (Path(d), Path(d).resolve())))
        new_pairs: list[ScoredPair] = []
        for pair in pairs:
            a, b = pair.file_a, pair.file_b
            a_ref = a.is_reference or _is_reference(a.path, ref_dirs)
            b_ref = b.is_reference or _is_reference(b.path, ref_dirs)
            if a_ref != a.is_reference or b_ref != b.is_reference:
                new_pairs.append(
                    ScoredPair(
                        file_a=replace(a, is_reference=a_ref),
                        file_b=replace(b, is_reference=b_ref),
                        total_score=pair.total_score,
                        breakdown=pair.breakdown,
                        detail=pair.detail,
                    )
                )
            else:
                new_pairs.append(pair)
        pairs = new_pairs

    # Populate stats
    unique_paths: set[str] = set()
    for pair in pairs:
        unique_paths.add(str(pair.file_a.path))
        unique_paths.add(str(pair.file_b.path))
    pstats.replay_source = str(replay_path)
    pstats.files_scanned = len(unique_paths)
    pstats.files_after_filter = len(unique_paths)
    pstats.total_pairs_scored = len(pairs)
    pstats.metadata_cache_enabled = False
    pstats.content_cache_enabled = False

    if verbose:
        console.print(f"Loaded [bold]{len(pairs)}[/bold] pair(s) from {replay_path}")

    return pairs, envelope_mode


def main(argv: list[str] | None = None) -> None:
    global console  # noqa: PLW0603

    args = parse_args(argv)

    if getattr(args, "print_completion", None):
        import shtab

        print(shtab.complete(_build_parser(), args.print_completion))
        return

    _main_scan(args)


def _handle_scan_config_commands(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any]) -> bool:
    """Handle config inspection and persistence commands that exit early."""
    global console  # noqa: PLW0603

    if args.show_config:
        from duplicates_detector.config import merge_config, namespace_to_config, show_config

        merged = merge_config(args, config, profile)
        if merged.no_color and "NO_COLOR" not in os.environ:
            os.environ["NO_COLOR"] = "1"
        show_mode = merged.mode or Mode.VIDEO
        if merged.weights:
            _validate_weights(
                merged.weights, content=bool(merged.content), console=console, mode=show_mode, audio=bool(merged.audio)
            )
        if show_mode != Mode.AUDIO:
            _validate_content_params(merged, console, mode=show_mode)
        effective = namespace_to_config(merged)
        show_config(effective)
        return True

    if args.save_config:
        from duplicates_detector.config import (
            merge_config,
            namespace_to_config,
            save_config,
            get_config_path,
        )

        merged = merge_config(args, config, profile)
        if merged.no_color and "NO_COLOR" not in os.environ:
            os.environ["NO_COLOR"] = "1"
            console = Console(stderr=True, no_color=True)
        save_mode = merged.mode or Mode.VIDEO
        if save_mode == Mode.AUDIO:
            merged.content = False
            merged.content_method = None
            merged.rotation_invariant = False
        if merged.weights:
            _validate_weights(
                merged.weights, content=bool(merged.content), console=console, mode=save_mode, audio=bool(merged.audio)
            )
        if save_mode != Mode.AUDIO:
            _validate_content_params(merged, console, mode=save_mode)
        if merged.embed_thumbnails:
            if not merged.json_envelope:
                console.print("[red]Error: --embed-thumbnails requires --json-envelope[/red]")
                raise SystemExit(1)
            if merged.format and merged.format not in ("json", "table"):
                console.print("[red]Error: --embed-thumbnails requires --format json[/red]")
                raise SystemExit(1)
            # Auto-promote format to "json" so the saved config is self-consistent
            merged.format = "json"
        if merged.embed_thumbnails and merged.thumbnail_size is not None:
            try:
                _parse_thumbnail_size(merged.thumbnail_size, save_mode)
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                raise SystemExit(1) from None
        if save_mode == Mode.IMAGE:
            merged.audio = False  # irrelevant for image mode
            merged.no_audio_cache = False
        if not merged.content:
            merged.content_method = None
        save_config(namespace_to_config(merged))
        console.print(f"Config saved to {get_config_path()}")
        return True

    if args.save_profile is not None:
        from duplicates_detector.config import (
            merge_config,
            namespace_to_config,
            save_profile,
            validate_profile_name,
        )

        try:
            validate_profile_name(args.save_profile)
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise SystemExit(1) from None

        merged = merge_config(args, config, profile)
        if merged.no_color and "NO_COLOR" not in os.environ:
            os.environ["NO_COLOR"] = "1"
            console = Console(stderr=True, no_color=True)
        save_mode = merged.mode or Mode.VIDEO
        if save_mode == Mode.AUDIO:
            merged.content = False
            merged.content_method = None
            merged.rotation_invariant = False
        if merged.weights:
            _validate_weights(
                merged.weights, content=bool(merged.content), console=console, mode=save_mode, audio=bool(merged.audio)
            )
        if save_mode != Mode.AUDIO:
            _validate_content_params(merged, console, mode=save_mode)
        if merged.embed_thumbnails:
            if not merged.json_envelope:
                console.print("[red]Error: --embed-thumbnails requires --json-envelope[/red]")
                raise SystemExit(1)
            if merged.format and merged.format not in ("json", "table"):
                console.print("[red]Error: --embed-thumbnails requires --format json[/red]")
                raise SystemExit(1)
            merged.format = "json"
        if merged.embed_thumbnails and merged.thumbnail_size is not None:
            try:
                _parse_thumbnail_size(merged.thumbnail_size, save_mode)
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                raise SystemExit(1) from None
        if save_mode == Mode.IMAGE:
            merged.audio = False  # irrelevant for image mode
            merged.no_audio_cache = False
        if save_mode == Mode.AUDIO:
            merged.content = False
            merged.content_method = None
            merged.rotation_invariant = False
        if not merged.content:
            merged.content_method = None
        profile_path = save_profile(args.save_profile, namespace_to_config(merged))
        console.print(f"Profile saved to {profile_path}")
        return True

    return False


def _handle_scan_session_commands(
    args: argparse.Namespace,
    raw_args: argparse.Namespace,
) -> tuple[bool, str | None, float, dict[str, float]]:
    """Handle session-related and standalone scan commands."""
    if args.clear_ignored:
        from duplicates_detector.ignorelist import IgnoreList

        ignore_list = IgnoreList(Path(args.ignore_file) if args.ignore_file else None)
        count = len(ignore_list)
        ignore_list.clear()
        try:
            ignore_list.save()
        except OSError as exc:
            console.print(f"[red]Error writing ignore list: {exc}[/red]")
            raise SystemExit(1) from None
        if not args.quiet:
            console.print(f"Cleared {count} ignored pair(s) from {ignore_list._path}")
        return True, None, 0.0, {}

    if args.generate_undo is not None:
        _validate_generate_undo_conflicts(raw_args, console)
        from duplicates_detector.undoscript import run_generate_undo

        run_generate_undo(
            args.generate_undo,
            output_file=args.output,
            quiet=getattr(args, "quiet", False),
        )
        return True, None, 0.0, {}

    if getattr(args, "list_sessions_json", False):
        import json as _json
        from duplicates_detector.session import SessionManager

        mgr = SessionManager(_get_sessions_dir())
        sessions = mgr.list_sessions()
        print(_json.dumps([s.to_dict() for s in sessions]))
        return True, None, 0.0, {}

    if getattr(args, "list_sessions", False):
        from duplicates_detector.session import SessionManager

        mgr = SessionManager(_get_sessions_dir())
        sessions = mgr.list_sessions()
        if not sessions:
            console.print("[dim]No saved sessions.[/dim]")
        else:
            from datetime import datetime

            for s in sessions:
                ts = datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d %H:%M")
                dirs = ", ".join(s.directories[:2])
                if len(s.directories) > 2:
                    dirs += f" +{len(s.directories) - 2}"
                console.print(f"  [bold]{s.session_id}[/bold] — {ts} — {dirs} — stage: {s.active_stage}")
        return True, None, 0.0, {}

    if getattr(args, "delete_session", None):
        from duplicates_detector.session import SessionManager

        mgr = SessionManager(_get_sessions_dir())
        _sid = args.delete_session
        session = mgr.load(_sid)
        if session is None:
            console.print(f"[red]Session '{_sid}' not found.[/red]")
            raise SystemExit(1)
        mgr.delete(_sid)
        if not args.quiet:
            console.print(f"[green]Session '{_sid}' deleted.[/green]")
        return True, None, 0.0, {}

    if getattr(args, "clear_sessions", False):
        from duplicates_detector.session import SessionManager

        mgr = SessionManager(_get_sessions_dir())
        mgr.clear_all()
        if not args.quiet:
            console.print("[green]All sessions cleared.[/green]")
        return True, None, 0.0, {}

    resumed_from = getattr(args, "resume", None)
    if not resumed_from:
        return False, None, 0.0, {}

    # Validate mutual exclusivity: --resume cannot combine with dirs or config flags
    if raw_args.directories is not None and len(raw_args.directories) > 0:
        console.print("[red]Error: --resume cannot be combined with directory arguments[/red]")
        raise SystemExit(1)
    from duplicates_detector.session import EPHEMERAL_CONFIG_KEYS, RESUME_OVERRIDE_KEYS
    from duplicates_detector.config import DEFAULTS

    _resume_conflicts = []
    for key in DEFAULTS:
        if key in EPHEMERAL_CONFIG_KEYS or key in RESUME_OVERRIDE_KEYS:
            continue
        raw_val = getattr(raw_args, key, None)
        if raw_val is not None:
            _resume_conflicts.append(f"--{key.replace('_', '-')}")
    if _resume_conflicts:
        console.print(
            f"[red]Error: --resume cannot be combined with {', '.join(_resume_conflicts)} "
            f"(session contains full config snapshot)[/red]"
        )
        raise SystemExit(1)

    from duplicates_detector.session import SessionManager

    mgr = SessionManager(_get_sessions_dir())
    session = mgr.load(resumed_from)
    if session is None:
        console.print(f"[red]Session '{resumed_from}' not found.[/red]")
        raise SystemExit(1)
    # Resume by re-running with the session's directories and config.
    # The CacheDB handles skip-ahead (cached results are reused).
    if not args.quiet:
        console.print(f"[green]Resuming session {session.session_id}...[/green]")
    args.directories = session.directories
    # Restore config fields from the session snapshot, but only when the
    # user didn't explicitly override them on the command line.
    for key, value in session.config.items():
        if value is None:
            continue
        if not hasattr(args, key):
            continue
        # If the user explicitly set this flag on CLI, don't overwrite.
        raw_val = getattr(raw_args, key, None)
        if raw_val is not None:
            continue
        setattr(args, key, value)

    return False, resumed_from, session.elapsed_seconds, dict(session.stage_timings)


def _validate_mode_specific_scan_args(
    args: argparse.Namespace,
    *,
    mode: str,
    is_replay: bool,
    cli_audio: Any,
    cli_content: Any,
) -> None:
    """Validate mode-specific scan arguments after config merge."""
    if is_replay:
        return

    if mode == Mode.IMAGE:
        if args.keep == "longest":
            console.print("[red]Error: --keep longest is not supported in image mode (no duration)[/red]")
            raise SystemExit(1)
        if args.min_duration is not None or args.max_duration is not None:
            console.print("[red]Error: --min-duration / --max-duration are not supported in image mode[/red]")
            raise SystemExit(1)
        if args.min_bitrate is not None or args.max_bitrate is not None:
            console.print("[red]Error: --min-bitrate / --max-bitrate are not supported in image mode[/red]")
            raise SystemExit(1)
        if args.audio:
            if cli_audio:
                console.print("[red]Error: --audio is not supported in image mode (images have no audio)[/red]")
                raise SystemExit(1)
            console.print("[yellow]Warning: --audio from config/profile is ignored in image mode[/yellow]")
            args.audio = False
    elif mode == Mode.AUDIO:
        if args.keep == "highest-res":
            console.print("[red]Error: --keep highest-res is not supported in audio mode (no resolution)[/red]")
            raise SystemExit(1)
        if args.min_resolution is not None or args.max_resolution is not None:
            console.print("[red]Error: --min-resolution / --max-resolution are not supported in audio mode[/red]")
            raise SystemExit(1)
        if args.content:
            if cli_content:
                console.print(
                    "[red]Error: --content is not supported in audio mode"
                    " (use --audio for Chromaprint fingerprinting)[/red]"
                )
                raise SystemExit(1)
            console.print("[yellow]Warning: --content from config/profile is ignored in audio mode[/yellow]")
            args.content = False
        if args.rotation_invariant:
            console.print("[yellow]Warning: --rotation-invariant is ignored in audio mode[/yellow]")
        if getattr(args, "content_method", None) is not None:
            console.print("[yellow]Warning: --content-method is ignored in audio mode[/yellow]")
        # Check mutagen availability
        try:
            import mutagen  # noqa: F401
        except ImportError:
            console.print(
                "[red]Error: Audio mode requires mutagen. Install with: pip install 'duplicates-detector[audio]'[/red]"
            )
            raise SystemExit(1)
    elif mode == Mode.AUTO:
        if args.keep == "longest":
            console.print("[red]Error: --keep longest is not supported in auto mode (images have no duration)[/red]")
            raise SystemExit(1)
        if args.weights:
            console.print(
                "[red]Error: --weights is not supported in auto mode"
                " (video and image use incompatible weight keys; use separate runs)[/red]"
            )
            raise SystemExit(1)
        if args.extensions:
            console.print(
                "[red]Error: --extensions is not supported in auto mode"
                " (auto mode scans all video and image extensions; use separate runs for custom extensions)[/red]"
            )
            raise SystemExit(1)
    elif mode == Mode.DOCUMENT:
        if args.keep == "longest":
            console.print("[red]Error: --keep longest is not supported in document mode (no duration)[/red]")
            raise SystemExit(1)
        if args.keep == "highest-res":
            console.print("[red]Error: --keep highest-res is not supported in document mode (no resolution)[/red]")
            raise SystemExit(1)
        if args.min_duration is not None or args.max_duration is not None:
            console.print("[red]Error: --min-duration / --max-duration are not supported in document mode[/red]")
            raise SystemExit(1)
        if args.min_resolution is not None or args.max_resolution is not None:
            console.print("[red]Error: --min-resolution / --max-resolution are not supported in document mode[/red]")
            raise SystemExit(1)
        if args.min_bitrate is not None or args.max_bitrate is not None:
            console.print("[red]Error: --min-bitrate / --max-bitrate are not supported in document mode[/red]")
            raise SystemExit(1)
        if args.audio:
            if cli_audio:
                console.print("[red]Error: --audio is not supported in document mode (documents have no audio)[/red]")
                raise SystemExit(1)
            console.print("[yellow]Warning: --audio from config/profile is ignored in document mode[/yellow]")
            args.audio = False
        if args.rotation_invariant:
            console.print("[yellow]Warning: --rotation-invariant is ignored in document mode[/yellow]")
        # Check pdfminer availability
        try:
            from pdfminer.high_level import extract_text  # noqa: F401
        except ImportError:
            console.print(
                "[red]Error: Document mode requires pdfminer.six."
                " Install with: pip install 'duplicates-detector[document]'[/red]"
            )
            raise SystemExit(1)

    # Warn on rotation-invariant with SSIM/CLIP
    content_method = _default_content_method(args, mode)
    if args.content and content_method == "clip":
        if args.rotation_invariant:
            console.print("[yellow]Warning: --rotation-invariant is ignored with --content-method clip[/yellow]")
    if args.content and content_method == "ssim":
        if args.rotation_invariant:
            console.print("[yellow]Warning: --rotation-invariant is ignored with --content-method ssim[/yellow]")


def _report_and_review_scan_results(
    args: argparse.Namespace,
    *,
    mode: str,
    pairs: list[ScoredPair],
    groups: list[DuplicateGroup] | None,
    pstats: PipelineStats,
    pipeline_start: float,
    deleter: Any,
    progress_emitter: ProgressEmitter | None,
    ignore_list: Any,
    controller: PipelineController | None = None,
) -> Any:
    """Render results, optionally perform review actions, and return deletion status."""
    import io

    from duplicates_detector.advisor import DeletionSummary

    pause_waiter = controller.wait_if_paused_blocking if controller is not None else None

    # Initialize action_log early so pre-compute dry-run can log too
    action_log = None
    if args.log:
        from duplicates_detector.actionlog import ActionLog

        action_log = ActionLog(Path(args.log))
        action_log.open()

    dry_run_summary: DeletionSummary | None = None
    sink_console = Console(file=io.StringIO())
    try:
        if args.keep and args.dry_run and not args.interactive and args.format in ("json", "shell", "html", "markdown"):
            if groups is not None and groups:
                from duplicates_detector.advisor import auto_delete_groups

                dry_run_summary = auto_delete_groups(
                    groups,
                    strategy=args.keep,
                    dry_run=True,
                    deleter=deleter,
                    console=sink_console,
                    action_log=action_log,
                    sidecar_extensions=getattr(args, "sidecar_extensions", None),
                    no_sidecars=bool(getattr(args, "no_sidecars", False)),
                )
            elif not groups and pairs:
                from duplicates_detector.advisor import auto_delete

                dry_run_summary = auto_delete(
                    pairs,
                    strategy=args.keep,
                    dry_run=True,
                    deleter=deleter,
                    console=sink_console,
                    action_log=action_log,
                    sidecar_extensions=getattr(args, "sidecar_extensions", None),
                    no_sidecars=bool(getattr(args, "no_sidecars", False)),
                )

        # 4a. Build JSON envelope (if --json-envelope and --format json)
        envelope: dict | None = None
        if args.json_envelope and args.format == "json":
            from datetime import datetime, timezone

            from duplicates_detector.comparators import parse_weights

            pstats.total_time = time.monotonic() - pipeline_start

            # Weights: parse string to dict, or pass through dict from config
            weights_obj: dict[str, float] | None = None
            if args.weights:
                weights_obj = parse_weights(args.weights) if isinstance(args.weights, str) else args.weights

            args_dict: dict = {
                "directories": [str(d) for d in args.directories],
                "threshold": args.threshold,
                "content": bool(args.content),
                "content_method": _default_content_method(args, mode) if args.content else None,
                "weights": weights_obj,
                "keep": args.keep,
                "action": args.action or "delete",
                "group": bool(args.group),
                "sort": args.sort,
                "limit": args.limit,
                "min_score": args.min_score,
                "exclude": args.exclude or None,
                "reference": [str(r) for r in args.reference] if args.reference else None,
                "min_size": args.min_size,
                "max_size": args.max_size,
                "min_duration": args.min_duration,
                "max_duration": args.max_duration,
                "min_resolution": args.min_resolution,
                "max_resolution": args.max_resolution,
                "min_bitrate": args.min_bitrate,
                "max_bitrate": args.max_bitrate,
                "codec": args.codec,
                "mode": mode,
                "embed_thumbnails": bool(args.embed_thumbnails),
                "thumbnail_size": (
                    list(_parse_thumbnail_size(args.thumbnail_size, mode) or ()) if args.embed_thumbnails else None
                ),
            }

            stats_dict: dict = {
                "files_scanned": pstats.files_scanned,
                "files_after_filter": pstats.files_after_filter,
                "total_pairs_scored": pstats.total_pairs_scored,
                "pairs_above_threshold": pstats.pairs_above_threshold,
                "groups_count": pstats.groups_count,
                "space_recoverable": pstats.space_recoverable,
                "scan_time": round(pstats.scan_time, 3),
                "extract_time": round(pstats.extract_time, 3),
                "filter_time": round(pstats.filter_time, 3),
                "content_hash_time": round(pstats.content_hash_time, 3),
                "scoring_time": round(pstats.scoring_time, 3),
                "total_time": round(pstats.total_time, 3),
            }

            from duplicates_detector.analytics import analytics_to_dict, compute_analytics

            # When groups are limited, restrict analytics to pairs within retained
            # groups so the envelope stays internally consistent.
            analytics_pairs = pairs
            analytics_all_paths = pstats.discovered_paths if pstats else None
            if groups is not None and args.limit is not None:
                retained_paths: set[Path] = set()
                for g in groups:
                    for m in g.members:
                        retained_paths.add(m.path)
                analytics_pairs = [
                    p for p in pairs if p.file_a.path in retained_paths or p.file_b.path in retained_paths
                ]
                if analytics_all_paths is not None:
                    analytics_all_paths = analytics_all_paths & retained_paths

            analytics_result = compute_analytics(
                analytics_pairs,
                all_paths=analytics_all_paths,
                groups=groups,
                keep_strategy=args.keep,
            )

            envelope = {
                "version": __version__,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "args": args_dict,
                "stats": stats_dict,
                "analytics": analytics_to_dict(analytics_result),
            }

        # 4b. Generate thumbnails (if --embed-thumbnails)
        thumbnails: dict[Path, str | None] | None = None
        if args.embed_thumbnails:
            from duplicates_detector.thumbnails import (
                collect_group_metadata,
                collect_pair_metadata,
                generate_thumbnails_batch,
            )

            all_meta = collect_group_metadata(groups) if groups is not None else collect_pair_metadata(pairs)
            thumb_size = _parse_thumbnail_size(args.thumbnail_size, mode)
            with _controller_stage(controller, "thumbnail"):
                thumbnails = generate_thumbnails_batch(
                    all_meta,
                    mode=mode,
                    max_size=thumb_size,
                    quiet=args.quiet,
                    progress_emitter=progress_emitter,
                    controller=controller,
                )

        # 5. Report
        report_start = time.monotonic()
        with _controller_stage(controller, "report"):
            if progress_emitter is not None:
                progress_emitter.stage_start("report")
            output_file = None
            try:
                if args.output:
                    output_file = open(args.output, "w", newline="")
                # File output (--output): write directly to the file handle
                # without _PauseAwareTextWriter.  pause_waiter is still passed
                # for coarse-grained checkpoints (between records/groups);
                # _dump_json_pause_aware auto-detects seekable outputs and uses
                # json.dump() to skip the expensive per-chunk pause loop.
                # Stdout output: wrap in _PauseAwareTextWriter so pause
                # requests can interrupt the (potentially blocking) pipe writes.
                if output_file is not None:
                    report_file: TextIO | None = output_file
                    report_pause_waiter = pause_waiter
                elif controller is not None:
                    report_file = cast(
                        TextIO,
                        _PauseAwareTextWriter(sys.stdout, controller),
                    )
                    report_pause_waiter = pause_waiter
                else:
                    report_file = None
                    report_pause_waiter = pause_waiter

                _sc_ext = getattr(args, "sidecar_extensions", None)
                _no_sc = bool(getattr(args, "no_sidecars", False))

                if groups is not None:
                    match args.format:
                        case "table":
                            print_group_table(
                                groups,
                                verbose=args.verbose,
                                file=report_file,
                                keep_strategy=args.keep,
                                max_rows=args.limit,
                                quiet=args.quiet,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                            if args.limit is None:
                                from duplicates_detector.reporter import _MAX_TABLE_ROWS

                                if len(groups) > _MAX_TABLE_ROWS:
                                    pstats.display_limit = _MAX_TABLE_ROWS
                        case "json":
                            write_group_json(
                                groups,
                                file=report_file,
                                keep_strategy=args.keep,
                                dry_run_summary=dry_run_summary,
                                envelope=envelope,
                                thumbnails=thumbnails,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                        case "csv":
                            write_group_csv(
                                groups,
                                file=report_file,
                                keep_strategy=args.keep,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                        case "shell":
                            write_group_shell(
                                groups,
                                file=report_file,
                                keep_strategy=args.keep,
                                dry_run_summary=dry_run_summary,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                        case "html":
                            from duplicates_detector.analytics import compute_analytics
                            from duplicates_detector.html_report import write_group_html

                            _group_pairs = [p for g in groups for p in g.pairs]
                            _html_analytics = compute_analytics(
                                _group_pairs,
                                all_paths=pstats.discovered_paths if pstats else None,
                                groups=groups,
                                keep_strategy=args.keep,
                            )
                            write_group_html(
                                groups,
                                file=report_file,
                                keep_strategy=args.keep,
                                verbose=args.verbose,
                                stats=pstats,
                                mode=mode,
                                dry_run_summary=dry_run_summary,
                                quiet=args.quiet,
                                pause_controller=controller,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                                analytics=_html_analytics,
                            )
                        case "markdown":
                            write_group_markdown(
                                groups,
                                file=report_file,
                                keep_strategy=args.keep,
                                verbose=args.verbose,
                                stats=pstats,
                                mode=mode,
                                dry_run_summary=dry_run_summary,
                                quiet=args.quiet,
                            )
                else:
                    match args.format:
                        case "table":
                            title_map = {
                                "auto": "Potential Duplicate Media",
                                "image": "Potential Duplicate Images",
                                "audio": "Potential Duplicate Audio Files",
                                "video": "Potential Duplicate Videos",
                            }
                            table_title = title_map.get(mode, "Potential Duplicates")
                            print_table(
                                pairs,
                                verbose=args.verbose,
                                file=report_file,
                                keep_strategy=args.keep,
                                max_rows=args.limit,
                                quiet=args.quiet,
                                title=table_title,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                            if args.limit is None:
                                from duplicates_detector.reporter import _MAX_TABLE_ROWS

                                if len(pairs) > _MAX_TABLE_ROWS:
                                    pstats.display_limit = _MAX_TABLE_ROWS
                        case "json":
                            write_json(
                                pairs,
                                file=report_file,
                                keep_strategy=args.keep,
                                dry_run_summary=dry_run_summary,
                                envelope=envelope,
                                thumbnails=thumbnails,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                        case "csv":
                            write_csv(
                                pairs,
                                file=report_file,
                                keep_strategy=args.keep,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                        case "shell":
                            write_shell(
                                pairs,
                                file=report_file,
                                keep_strategy=args.keep,
                                dry_run_summary=dry_run_summary,
                                pause_waiter=report_pause_waiter,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                            )
                        case "html":
                            from duplicates_detector.analytics import compute_analytics
                            from duplicates_detector.html_report import write_html

                            _html_analytics = compute_analytics(
                                pairs,
                                all_paths=pstats.discovered_paths if pstats else None,
                            )
                            write_html(
                                pairs,
                                file=report_file,
                                keep_strategy=args.keep,
                                verbose=args.verbose,
                                stats=pstats,
                                mode=mode,
                                dry_run_summary=dry_run_summary,
                                quiet=args.quiet,
                                pause_controller=controller,
                                sidecar_extensions=_sc_ext,
                                no_sidecars=_no_sc,
                                analytics=_html_analytics,
                            )
                        case "markdown":
                            write_markdown(
                                pairs,
                                file=report_file,
                                keep_strategy=args.keep,
                                verbose=args.verbose,
                                stats=pstats,
                                mode=mode,
                                dry_run_summary=dry_run_summary,
                                quiet=args.quiet,
                            )

                # Flush stdout so the GUI receives the complete JSON envelope
                # without waiting for Python's block-buffered pipe to fill or
                # for process exit.  Without this, small outputs can sit in the
                # buffer indefinitely while post-report processing runs.
                sys.stdout.flush()
            finally:
                if output_file is not None:
                    output_file.close()

            if progress_emitter is not None:
                if controller is not None:
                    controller.wait_if_paused_blocking()
                progress_emitter.stage_end(
                    "report",
                    total=len(groups) if groups is not None else len(pairs),
                    elapsed=time.monotonic() - report_start,
                )

        if args.format == "shell" and args.output:
            os.chmod(args.output, 0o755)

        if args.format == "html" and not args.output and not args.quiet:
            Console(stderr=True).print(
                "[yellow]Hint: HTML output is best written to a file with --output report.html[/yellow]"
            )

        # 6. Auto-delete / interactive review
        # Skip if dry-run summary was already pre-computed for json/shell/html
        quiet_console: Console | None = None
        if args.quiet:
            quiet_console = Console(file=io.StringIO())

        deletion_summary = None
        if dry_run_summary is None:
            if groups is not None:
                if args.keep and not args.interactive and args.format == "table" and groups:
                    from duplicates_detector.advisor import auto_delete_groups

                    deletion_summary = auto_delete_groups(
                        groups,
                        strategy=args.keep,
                        dry_run=args.dry_run,
                        deleter=deleter,
                        console=quiet_console,
                        action_log=action_log,
                        sidecar_extensions=getattr(args, "sidecar_extensions", None),
                        no_sidecars=bool(getattr(args, "no_sidecars", False)),
                    )
                elif args.interactive and groups:
                    from duplicates_detector.advisor import review_groups

                    review_groups(
                        groups,
                        dry_run=args.dry_run,
                        keep_strategy=args.keep,
                        deleter=deleter,
                        action_log=action_log,
                        ignore_list=ignore_list,
                        verbose=args.verbose,
                        sidecar_extensions=getattr(args, "sidecar_extensions", None),
                        no_sidecars=bool(getattr(args, "no_sidecars", False)),
                    )
            else:
                if args.keep and not args.interactive and args.format == "table" and pairs:
                    from duplicates_detector.advisor import auto_delete

                    deletion_summary = auto_delete(
                        pairs,
                        strategy=args.keep,
                        dry_run=args.dry_run,
                        deleter=deleter,
                        console=quiet_console,
                        action_log=action_log,
                        sidecar_extensions=getattr(args, "sidecar_extensions", None),
                        no_sidecars=bool(getattr(args, "no_sidecars", False)),
                    )
                elif args.interactive and pairs:
                    from duplicates_detector.advisor import review_duplicates

                    review_duplicates(
                        pairs,
                        dry_run=args.dry_run,
                        keep_strategy=args.keep,
                        deleter=deleter,
                        action_log=action_log,
                        ignore_list=ignore_list,
                        verbose=args.verbose,
                        sidecar_extensions=getattr(args, "sidecar_extensions", None),
                        no_sidecars=bool(getattr(args, "no_sidecars", False)),
                    )
        return deletion_summary
    finally:
        if action_log is not None:
            action_log.close()


def _main_scan(args: argparse.Namespace) -> None:
    """Entry point for the ``scan`` subcommand (existing behavior)."""
    global console  # noqa: PLW0603

    # Apply --no-color early so all Console instances (including show_config,
    # save_config, and pipeline modules) respect the setting.
    if args.no_color:
        os.environ["NO_COLOR"] = "1"
        console = Console(stderr=True, no_color=True)

    # Apply --quiet early to suppress warnings from load_config()
    if args.quiet:
        import warnings

        warnings.filterwarnings("ignore")

    # Config file handling
    if not args.no_config:
        from duplicates_detector.config import load_config

        config = load_config()
    else:
        config = {}

    # Profile loading (--profile is honored even with --no-config)
    profile: dict = {}
    if args.profile is not None:
        from duplicates_detector.config import load_profile

        profile = load_profile(args.profile)

    if _handle_scan_config_commands(args, config, profile):
        return

    # Save raw CLI flags before merge (sentinel None = not on CLI, True = explicit)
    cli_audio = args.audio
    cli_content = args.content
    raw_args = argparse.Namespace(**vars(args))
    # Restore raw directories for conflict checks (_validate_generate_undo_conflicts
    # needs to distinguish "no directories given" from "defaulted to .")
    raw_args.directories = getattr(args, "_raw_directories", args.directories)

    # Apply config defaults
    from duplicates_detector.config import merge_config

    args = merge_config(args, config, profile)

    should_return, _resumed_from, _prior_elapsed, _prior_stage_timings = _handle_scan_session_commands(args, raw_args)
    if should_return:
        return

    # Check for replay mode
    is_replay = bool(args.replay)
    if is_replay:
        _validate_replay_conflicts(raw_args, console)

    # Validate --quiet + --interactive mutually exclusive
    if args.quiet and args.interactive:
        console.print("[red]Error: --quiet and --interactive are mutually exclusive[/red]")
        raise SystemExit(1)

    # Apply --quiet (warning suppression already set pre-merge for CLI flag;
    # this catches config-derived quiet for the remaining effects)
    if args.quiet:
        args.verbose = False
        # Suppress warnings in case quiet came from config (idempotent if already set)
        import warnings

        warnings.filterwarnings("ignore")

    # Apply no_color from config (the pre-merge check only catches the CLI flag;
    # config-derived no_color lands here after merge_config)
    if args.no_color and "NO_COLOR" not in os.environ:
        os.environ["NO_COLOR"] = "1"
        console = Console(stderr=True, no_color=True)

    # Validate --limit
    if args.limit is not None and args.limit <= 0:
        console.print("[red]Error: --limit must be greater than 0[/red]")
        raise SystemExit(1)

    # Validate --min-score
    if args.min_score is not None and not (0 <= args.min_score <= 100):
        console.print("[red]Error: --min-score must be between 0 and 100[/red]")
        raise SystemExit(1)

    # Resolve mode
    mode = args.mode or Mode.VIDEO

    # Validate content params (only meaningful with --content)
    # Skipped for audio mode: --content is either rejected (explicit) or cleared (config) in mode validation below.
    if not is_replay and mode != Mode.AUDIO:
        _validate_content_params(args, console, mode=mode)
    if mode == Mode.AUTO:
        file_noun = "media"
    elif mode == Mode.IMAGE:
        file_noun = "image"
    elif mode == Mode.AUDIO:
        file_noun = "audio"
    elif mode == Mode.DOCUMENT:
        file_noun = "document"
    else:
        file_noun = "video"

    # Validate --embed-thumbnails
    if args.embed_thumbnails:
        if not args.json_envelope:
            console.print("[red]Error: --embed-thumbnails requires --json-envelope[/red]")
            raise SystemExit(1)
        if args.format and args.format != "json":
            console.print("[red]Error: --embed-thumbnails requires --format json[/red]")
            raise SystemExit(1)

    # Validate --thumbnail-size (only when --embed-thumbnails is active)
    if args.embed_thumbnails and args.thumbnail_size is not None:
        try:
            _parse_thumbnail_size(args.thumbnail_size, mode)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1) from None

    _validate_mode_specific_scan_args(
        args,
        mode=mode,
        is_replay=is_replay,
        cli_audio=cli_audio,
        cli_content=cli_content,
    )

    # Validate --action / --move-to-dir combination
    action = args.action or "delete"

    if action == "move-to" and not args.move_to_dir:
        console.print("[red]Error: --action move-to requires --move-to-dir DIR[/red]")
        raise SystemExit(1)

    if args.move_to_dir and action != "move-to":
        console.print("[yellow]Warning: --move-to-dir is ignored without --action move-to[/yellow]")

    if action == "trash" and not args.dry_run:
        try:
            import send2trash as _s2t  # noqa: F401
        except ImportError:
            console.print(
                '[red]Error: --action trash requires send2trash: pip install "duplicates-detector[trash]"[/red]'
            )
            raise SystemExit(1)

    move_dir = Path(args.move_to_dir).resolve() if args.move_to_dir else None
    if action == "move-to" and not args.dry_run:
        try:
            if move_dir is None:
                raise ValueError("--move-to-dir is required with --action move-to")
            move_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            console.print(f"[red]Error: cannot create staging directory {move_dir}: {e}[/red]")
            raise SystemExit(1)

    if action in ("hardlink", "symlink", "reflink") and not args.keep and not args.interactive:
        console.print(f"[red]Error: --action {action} requires --keep STRATEGY or --interactive[/red]")
        raise SystemExit(1)

    from duplicates_detector.deleter import make_deleter

    deleter = make_deleter(action, move_to_dir=move_dir)

    # Validate --weights
    weights_dict: dict[str, float] | None = None
    if not is_replay and args.weights:
        weights_dict = _validate_weights(
            args.weights, content=bool(args.content), console=console, mode=mode, audio=bool(args.audio)
        )

    cache_dir: Path | None = None
    if not is_replay:
        if args.cache_dir:
            cache_dir = Path(args.cache_dir).expanduser().resolve()

    import threading as _threading

    _pause_watcher_stop: _threading.Event | None = None
    _pause_watcher_thread: _threading.Thread | None = None
    session_id: str | None = None
    progress_emitter: ProgressEmitter | None = None

    try:
        pipeline_start = time.monotonic()
        pstats = PipelineStats()
        if args.machine_progress:
            from duplicates_detector.progress import ProgressEmitter as _ProgressEmitter

            progress_emitter = _ProgressEmitter(threaded=True)
            _start_parent_liveness_monitor()

        import uuid

        session_id = uuid.uuid4().hex[:12]

        from duplicates_detector.session import SessionManager as _PruneMgr

        _PruneMgr(_get_sessions_dir()).prune()

        cache_db: CacheDB | None = None
        pipeline_controller: PipelineController | None = None

        content_method = _default_content_method(args, mode)
        uses_seeded_discovery = not (bool(getattr(args, "content", False)) and content_method == "ssim")

        # Replay sessions can emit session_start immediately because there is
        # no scan stage before replay. Normal scans emit session_start before
        # discovery begins, with total_files starting at 0 until scan completes.
        if progress_emitter is not None and is_replay:
            progress_emitter.session_start(
                session_id=session_id,
                total_files=0,
                stages=_compute_session_stage_list(args, mode=mode, is_replay=is_replay),
                resumed_from=_resumed_from,
                prior_elapsed_seconds=_prior_elapsed,
            )

        if is_replay:
            if progress_emitter is not None:
                progress_emitter.stage_start("replay")
            t0 = time.monotonic()
            pairs, envelope_mode = _run_replay(
                Path(args.replay),
                reference_dirs=args.reference,
                verbose=args.verbose,
                quiet=args.quiet,
                pstats=pstats,
            )
            if progress_emitter is not None:
                progress_emitter.stage_end("replay", total=len(pairs), elapsed=time.monotonic() - t0)
            if envelope_mode is not None:
                mode = envelope_mode
            if not pairs:
                return

        else:
            # --- Normal scan path ---

            # Validate reference directories
            if args.reference:
                for ref in args.reference:
                    ref_path = Path(ref)
                    if not ref_path.exists():
                        raise FileNotFoundError(f"Reference directory not found: {ref}")
                    if not ref_path.is_dir():
                        raise NotADirectoryError(f"Reference path is not a directory: {ref}")

            # Create PipelineController for pause/cancel coordination.
            pipeline_controller = PipelineController()

            # Wire pause/resume callbacks for session save + progress emission.
            from duplicates_detector.session import (
                SessionManager as _SessionMgr,
                ScanSession as _ScanSession,
                build_session_config,
            )
            from datetime import datetime, timezone

            _session_mgr = _SessionMgr(_get_sessions_dir())
            _pause_state: dict[str, Any] = {}

            def _on_pause() -> None:
                session_file = _get_sessions_dir() / f"{session_id}.json"
                snapshot_completed, snapshot_active, snapshot_timings = _build_pause_snapshot(
                    args,
                    mode=mode,
                    is_replay=False,
                    controller=pipeline_controller,
                    aggregator=_pause_state.get("aggregator"),
                )
                session = _ScanSession(
                    session_id=session_id,
                    directories=[str(d) for d in (args.directories or [])],
                    config=build_session_config(args),
                    completed_stages=snapshot_completed,
                    active_stage=snapshot_active or "paused",
                    total_files=pipeline_controller.files_discovered,
                    elapsed_seconds=_prior_elapsed + (time.monotonic() - pipeline_start),
                    stage_timings=_merge_stage_timings(_prior_stage_timings, snapshot_timings),
                    paused_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                )
                _session_mgr.save(session)
                if progress_emitter is not None:
                    progress_emitter.pause(session_id, str(session_file))

            def _on_resume() -> None:
                if progress_emitter is not None:
                    progress_emitter.resume(session_id)

            pipeline_controller.on_pause = _on_pause
            pipeline_controller.on_resume = _on_resume

            def _setup_pause_signals(controller: PipelineController) -> None:
                import signal

                if not hasattr(signal, "SIGUSR1"):
                    return

                # signal.signal() rather than loop.add_signal_handler() because
                # this runs in a sync context before the async pipeline starts.
                # On CPython, signal handlers run between bytecodes in the main
                # thread — safe for asyncio.Event.clear/set (single-word writes)
                # and the _on_pause() callback (session save + stderr write).
                # The file watcher provides a redundant backup path.
                def _handle_pause_signal(signum: int, frame: object) -> None:
                    if signum == signal.SIGUSR1:
                        if not controller.is_paused:
                            controller.pause()
                    elif hasattr(signal, "SIGUSR2") and signum == signal.SIGUSR2:
                        if controller.is_paused:
                            controller.resume()

                signal.signal(signal.SIGUSR1, _handle_pause_signal)
                if hasattr(signal, "SIGUSR2"):
                    signal.signal(signal.SIGUSR2, _handle_pause_signal)

            _setup_pause_signals(pipeline_controller)

            if args.verbose:
                all_dirs = args.directories + (args.reference or [])
                label = ", ".join(all_dirs)
                console.print(f"Scanning [bold]{label}[/bold] ...")

            pause_file_path = Path(args.pause_file) if getattr(args, "pause_file", None) else None
            _pause_watcher_stop = _threading.Event()

            if pause_file_path is not None:

                def _watch_pause_file_thread() -> None:
                    assert _pause_watcher_stop is not None
                    while not _pause_watcher_stop.is_set():
                        try:
                            content = pause_file_path.read_text(encoding="utf-8").strip().lower()
                        except OSError:
                            content = ""
                        try:
                            if content == "pause" and not pipeline_controller.is_paused:
                                pipeline_controller.pause()
                            elif content == "resume" and pipeline_controller.is_paused:
                                pipeline_controller.resume()
                        except Exception:
                            pass  # Suppress to prevent watcher thread crash
                        _pause_watcher_stop.wait(0.5)

                _pause_watcher_thread = _threading.Thread(
                    target=_watch_pause_file_thread,
                    name="dd-pause-file-watcher",
                    daemon=True,
                )
                _pause_watcher_thread.start()

            if progress_emitter is not None:
                progress_emitter.session_start(
                    session_id=session_id,
                    total_files=0,
                    stages=_compute_session_stage_list(args, mode=mode, is_replay=False),
                    resumed_from=_resumed_from,
                    prior_elapsed_seconds=_prior_elapsed,
                )

            discovered_paths: list[Path] | None = None
            discovered_counts: dict[str, int] | None = None
            discovered_elapsed: float | None = None
            if uses_seeded_discovery:
                discovered_paths, discovered_counts, discovered_elapsed = _discover_seeded_paths(
                    args,
                    mode,
                    progress_emitter=progress_emitter,
                    controller=pipeline_controller,
                )

            # Create CacheDB before the pipeline (stages need it).
            # Pruning is deferred to after the pipeline completes.
            from duplicates_detector.cache_db import CacheDB as _CacheDB

            if cache_dir is not None:
                default_cache_dir = cache_dir
            else:
                xdg = os.environ.get("XDG_CACHE_HOME")
                default_cache_dir = (Path(xdg) if xdg else Path.home() / ".cache") / "duplicates-detector"
            cache_db = _CacheDB(default_cache_dir)

            # Run the seeded pipeline. SSIM fallback keeps its internal scan path.
            if mode == Mode.AUTO:
                auto_result = _run_auto_pipeline(
                    args,
                    pstats=pstats,
                    pipeline_start=pipeline_start,
                    progress_emitter=progress_emitter,
                    cache_db=cache_db,
                    controller=pipeline_controller,
                    _pause_state=_pause_state,
                    pre_scanned_paths=discovered_paths,
                    pre_scan_elapsed=discovered_elapsed,
                    discovered_counts_by_mode=discovered_counts,
                )
                if auto_result is None:
                    return
                pairs = auto_result
            else:
                single_result = _run_single_pipeline(
                    args,
                    pstats=pstats,
                    pipeline_start=pipeline_start,
                    mode=mode,
                    file_noun=file_noun,
                    weights_dict=weights_dict,
                    progress_emitter=progress_emitter,
                    cache_db=cache_db,
                    controller=pipeline_controller,
                    pre_scanned_paths=discovered_paths,
                    pre_scan_elapsed=discovered_elapsed,
                )
                if single_result is None:
                    return
                pairs = single_result

            # Post-pipeline checks.
            if pstats.files_scanned < 2:
                if not args.quiet:
                    console.print(
                        f"[yellow]Found {pstats.files_scanned} {file_noun} file(s). "
                        f"Need at least 2 to compare.[/yellow]"
                    )
                return

            if args.verbose:
                console.print(f"Found [bold]{pstats.files_scanned}[/bold] {file_noun} files.")

            # Prune cache with discovered paths.
            if pstats.discovered_paths:
                cache_db.prune(pstats.discovered_paths)

        # 3a. Filter ignored pairs
        # In replay mode, emit a filter stage so machine-progress consumers
        # see the expected replay → filter → report stage sequence.  In
        # non-replay mode the metadata filter stage already ran earlier.
        if is_replay and progress_emitter is not None:
            progress_emitter.stage_start("filter")
        filter_t0 = time.monotonic()

        from duplicates_detector.ignorelist import IgnoreList

        ignore_list = IgnoreList(Path(args.ignore_file) if args.ignore_file else None)
        if len(ignore_list) > 0:
            pre_ignore = len(pairs)
            pairs = [p for p in pairs if not ignore_list.contains(p.file_a.path, p.file_b.path)]
            if args.verbose:
                ignored = pre_ignore - len(pairs)
                if ignored:
                    console.print(f"  [dim]Filtered out {ignored} ignored pair(s).[/dim]")

        pstats.pairs_above_threshold = len(pairs)

        # 3a2. Filter by --min-score
        if args.min_score is not None:
            pairs = [p for p in pairs if p.total_score >= args.min_score]
            pstats.pairs_after_min_score = len(pairs)

        if is_replay and progress_emitter is not None:
            progress_emitter.stage_end("filter", total=len(pairs), elapsed=time.monotonic() - filter_t0)

        # 3b. Group if requested
        groups = group_duplicates(pairs) if args.group else None
        if groups is not None:
            pstats.groups_count = len(groups)

        pstats.space_recoverable = _compute_space_recoverable(pairs, groups)

        # 3b. Sort results
        if args.sort and args.sort != "score":
            from duplicates_detector.sorter import sort_groups, sort_pairs

            if groups is not None:
                groups = sort_groups(groups, args.sort)
            else:
                pairs = sort_pairs(pairs, args.sort)

        # 3c. Record total result count before display truncation
        if groups is not None:
            pstats.total_result_count = len(groups)
        else:
            pstats.total_result_count = len(pairs)

        # 3d. Limit results
        if args.limit is not None:
            if groups is not None:
                groups = groups[: args.limit]
            else:
                pairs = pairs[: args.limit]
            pstats.display_limit = args.limit

        deletion_summary = _report_and_review_scan_results(
            args,
            mode=mode,
            pairs=pairs,
            groups=groups,
            pstats=pstats,
            pipeline_start=pipeline_start,
            deleter=deleter,
            progress_emitter=progress_emitter,
            ignore_list=ignore_list,
            controller=pipeline_controller,
        )

        # Copy sidecar stats from deletion summary into pipeline stats for the summary panel.
        # Skip during dry-run — the advisor's own summary already uses conditional language;
        # print_summary() would misleadingly say "deleted" / "freed".
        if deletion_summary is not None and not args.dry_run and isinstance(deletion_summary.sidecars_deleted, int):
            pstats.sidecars_deleted = deletion_summary.sidecars_deleted
            pstats.sidecar_bytes_freed = deletion_summary.sidecar_bytes_freed

        if pipeline_controller is not None:
            pipeline_controller.wait_if_paused_blocking()

        # 6. Summary panel (to stderr, unless quiet)
        pstats.total_time = time.monotonic() - pipeline_start
        if not args.quiet:
            print_summary(pstats, console=console)

        # 6a. Cache statistics (--cache-stats)
        if getattr(args, "cache_stats", False) and cache_db is not None:
            _cache_stats = cache_db.stats()
            console.print("\n[bold]Cache Statistics:[/bold]")
            for _k, _v in sorted(_cache_stats.items()):
                console.print(f"  {_k}: {_v}")

        # 6b. Emit session_end event
        if progress_emitter is not None:
            _total_elapsed = _prior_elapsed + (time.monotonic() - pipeline_start)
            _cache_time_saved = 0.0
            if cache_db is not None:
                _cstats = cache_db.stats()
                _cache_time_saved = (
                    _cstats.get("metadata_hits", 0) * 0.05
                    + _cstats.get("content_hits", 0) * 0.2
                    + _cstats.get("audio_hits", 0) * 0.3
                    + _cstats.get("score_hits", 0) * 0.005
                )
            progress_emitter.session_end(
                session_id=session_id,
                total_elapsed=_total_elapsed,
                cache_time_saved=_cache_time_saved,
            )

        # 6c. Delete session file on successful completion
        from duplicates_detector.session import SessionManager as _SessionMgr

        _SessionMgr(_get_sessions_dir()).delete(session_id)

        # Signal deletion errors via exit code (critical for quiet/scripted workflows
        # where console output is suppressed)
        if deletion_summary is not None and isinstance(deletion_summary.errors, list) and deletion_summary.errors:
            sys.exit(1)

    except OSError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        from duplicates_detector.session import SessionManager as _CancelMgr

        if session_id is not None:
            _CancelMgr(_get_sessions_dir()).delete(session_id)
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(130)
    finally:
        # Flush any pending machine-progress events so the GUI receives a clean termination.
        if progress_emitter is not None:
            progress_emitter.close()
        # Stop the pause-file watcher thread that spans the entire scan lifecycle.
        if _pause_watcher_stop is not None:
            _pause_watcher_stop.set()
        if _pause_watcher_thread is not None:
            _pause_watcher_thread.join(timeout=1.0)
