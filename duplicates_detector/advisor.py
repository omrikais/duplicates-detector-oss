from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.prompt import Prompt

from duplicates_detector.deleter import (
    Deleter,
    HardlinkDeleter,
    MoveDeleter,
    PermanentDeleter,
    ReflinkDeleter,
    SymlinkDeleter,
    TrashDeleter,
)

if TYPE_CHECKING:
    from duplicates_detector.actionlog import ActionLog
    from duplicates_detector.ignorelist import IgnoreList

from duplicates_detector.filters import format_size_human
from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.keeper import pick_delete, pick_keep_from_group
from duplicates_detector.reporter import (
    format_audio_channels,
    format_bitrate,
    format_codec,
    format_framerate,
    score_color,
)
from duplicates_detector.scorer import ScoredPair


@dataclass(frozen=True, slots=True)
class DeletionSummary:
    """Result of an interactive deletion session."""

    deleted: list[Path]
    skipped: int
    errors: list[tuple[Path, str]]
    bytes_freed: int
    sidecars_deleted: int = 0
    sidecar_bytes_freed: int = 0


@dataclass(frozen=True, slots=True)
class _DeletionOutcome:
    """Result of a single file deletion attempt."""

    success: bool
    bytes_freed: int = 0
    destination: Path | None = None
    error: str | None = None
    already_gone: bool = False
    sidecars_deleted: int = 0
    sidecar_bytes_freed: int = 0


class _DeletionAccumulator:
    """Mutable accumulator for deletion state across an interactive or auto session."""

    __slots__ = (
        "deleted_paths",
        "deleted_list",
        "errors",
        "skipped",
        "bytes_freed",
        "sidecars_deleted",
        "sidecar_bytes_freed",
    )

    def __init__(self) -> None:
        self.deleted_paths: set[Path] = set()
        self.deleted_list: list[Path] = []
        self.errors: list[tuple[Path, str]] = []
        self.skipped: int = 0
        self.bytes_freed: int = 0
        self.sidecars_deleted: int = 0
        self.sidecar_bytes_freed: int = 0

    def apply_outcome(self, target_path: Path, outcome: _DeletionOutcome) -> None:
        """Update accumulators from a single deletion outcome."""
        if outcome.success:
            self.deleted_paths.add(target_path)
            self.deleted_list.append(target_path)
            self.bytes_freed += outcome.bytes_freed
            self.sidecars_deleted += outcome.sidecars_deleted
            self.sidecar_bytes_freed += outcome.sidecar_bytes_freed
        elif outcome.already_gone:
            self.deleted_paths.add(target_path)
            self.skipped += 1
        elif outcome.error:
            self.errors.append((target_path, outcome.error))

    def to_summary(self) -> DeletionSummary:
        return DeletionSummary(
            deleted=self.deleted_list,
            skipped=self.skipped,
            errors=self.errors,
            bytes_freed=self.bytes_freed,
            sidecars_deleted=self.sidecars_deleted,
            sidecar_bytes_freed=self.sidecar_bytes_freed,
        )


def _execute_deletion(
    target_path: Path,
    kept_path: Path,
    deleter: Deleter,
    *,
    dry_run: bool,
    action_log: ActionLog | None,
    score: float,
    strategy: str,
    console: Console,
    sidecars: tuple[Path, ...] | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> _DeletionOutcome:
    """Execute a single file deletion with logging and error handling.

    When *sidecars* is provided, associated sidecar files are deleted
    after the main file using the same deleter.  For ``.lrdata``
    directories: PermanentDeleter uses ``shutil.rmtree()``, TrashDeleter
    uses ``send2trash()``, MoveDeleter uses ``shutil.move()``, and
    link-based deleters skip with a warning.  When *sidecars* is None
    (e.g. replay mode), sidecars are rediscovered from the filesystem
    unless *no_sidecars* is True.  An empty tuple means sidecars were
    explicitly disabled by the pipeline.
    """
    # Rediscover sidecars from filesystem if metadata lacks them (e.g. replay).
    # None = unknown (replay); () = explicitly disabled (--no-sidecars).
    # no_sidecars=True suppresses rediscovery (replay with --no-sidecars).
    if sidecars is None and not no_sidecars:
        from duplicates_detector.sidecar import find_sidecars, parse_sidecar_extensions

        kwargs: dict[str, object] = {}
        if sidecar_extensions is not None:
            kwargs["extensions"] = parse_sidecar_extensions(sidecar_extensions)
        found = find_sidecars(target_path, **kwargs)  # type: ignore[arg-type]
        if found:
            sidecars = tuple(found)

    try:
        destination = None
        if dry_run:
            file_size = target_path.stat().st_size
        else:
            result = deleter.remove(target_path, link_target=kept_path)
            file_size = result.bytes_freed
            destination = result.destination
        verb = deleter.dry_verb if dry_run else deleter.verb
        console.print(f"  [red]{verb}:[/red] {target_path}")
        if action_log is not None:
            action_log.log(
                action=deleter.verb.lower(),
                path=target_path,
                score=score,
                strategy=strategy,
                kept=kept_path,
                bytes_freed=file_size,
                destination=destination,
                dry_run=dry_run,
            )
    except FileNotFoundError:
        console.print(f"  [yellow]Already gone:[/yellow] {target_path}")
        return _DeletionOutcome(success=False, already_gone=True)
    except PermissionError:
        console.print(f"  [red]Permission denied:[/red] {target_path}")
        return _DeletionOutcome(success=False, error="Permission denied")
    except OSError as e:
        console.print(f"  [red]Error removing {target_path}:[/red] {e}")
        return _DeletionOutcome(success=False, error=str(e))

    # Process sidecars
    sc_deleted = 0
    sc_bytes = 0
    if sidecars:
        for sc_path in sidecars:
            try:
                # Link-based deleters skip sidecars in both live and dry-run
                if isinstance(deleter, (HardlinkDeleter, SymlinkDeleter, ReflinkDeleter)):
                    continue
                sc_size = _sidecar_size(sc_path)
                sc_destination: Path | None = None
                if not dry_run:
                    removed, sc_destination = _remove_sidecar(sc_path, deleter, console)
                    if not removed:
                        continue
                sc_verb = deleter.dry_verb if dry_run else deleter.verb
                console.print(f"    [dim]{sc_verb} sidecar:[/dim] {sc_path.name}")
                if action_log is not None:
                    action_log.log(
                        action=deleter.verb.lower(),
                        path=sc_path,
                        score=score,
                        strategy=strategy,
                        kept=kept_path,
                        bytes_freed=sc_size,
                        destination=sc_destination,
                        dry_run=dry_run,
                        sidecar_of=target_path,
                    )
                sc_deleted += 1
                sc_bytes += sc_size
            except OSError as e:
                console.print(f"    [red]Sidecar error {sc_path.name}:[/red] {e}")

    return _DeletionOutcome(
        success=True,
        bytes_freed=file_size,
        destination=destination,
        sidecars_deleted=sc_deleted,
        sidecar_bytes_freed=sc_bytes,
    )


def _sidecar_size(sc_path: Path) -> int:
    """Return the total size of a sidecar (file or directory tree)."""

    if sc_path.is_dir():
        return sum(f.stat().st_size for f in sc_path.rglob("*") if f.is_file())
    return sc_path.stat().st_size


def _remove_sidecar(sc_path: Path, deleter: Deleter, console: Console) -> tuple[bool, Path | None]:
    """Remove a single sidecar file or directory using the appropriate method.

    Returns ``(removed, destination)`` where *removed* is False when the
    sidecar was skipped and *destination* is the move target for MoveDeleter.
    """
    import shutil

    if isinstance(deleter, (HardlinkDeleter, SymlinkDeleter, ReflinkDeleter)):
        kind = "directory" if sc_path.is_dir() else "file"
        console.print(f"    [yellow]Skipping sidecar {kind} (unsupported for {deleter.verb}):[/yellow] {sc_path}")
        return (False, None)

    if sc_path.is_dir():
        if isinstance(deleter, PermanentDeleter):
            shutil.rmtree(sc_path)
        elif isinstance(deleter, TrashDeleter):
            from send2trash import send2trash

            send2trash(str(sc_path))
        elif isinstance(deleter, MoveDeleter):
            target = deleter.destination / sc_path.name
            if target.exists():
                stem = sc_path.stem
                suffix = sc_path.suffix
                counter = 1
                while target.exists():
                    target = deleter.destination / f"{stem}_{counter}{suffix}"
                    counter += 1
            shutil.move(str(sc_path), str(target))
            return (True, target)
        else:
            raise TypeError(f"Unsupported deleter type for directory sidecar: {type(deleter).__name__}")
    else:
        result = deleter.remove(sc_path)
        return (True, result.destination)
    return (True, None)


def _format_metadata(meta) -> str:
    """One-line metadata summary: size | duration | resolution | codec | bitrate | fps | audio.

    Only includes non-None fields so images display cleanly without 'n/a' clutter.
    """
    parts = [format_size_human(meta.file_size)]
    if meta.duration is not None:
        m, s = divmod(int(meta.duration), 60)
        h, m = divmod(m, 60)
        parts.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
    if meta.width is not None and meta.height is not None:
        parts.append(f"{meta.width}x{meta.height}")
    if meta.codec is not None:
        parts.append(format_codec(meta.codec))
    if meta.bitrate is not None:
        parts.append(format_bitrate(meta.bitrate))
    if meta.framerate is not None:
        parts.append(format_framerate(meta.framerate))
    if meta.audio_channels is not None:
        parts.append(format_audio_channels(meta.audio_channels))
    if meta.tag_artist is not None:
        parts.append(f"Artist: {rich_escape(meta.tag_artist)}")
    if meta.tag_title is not None:
        parts.append(f"Title: {rich_escape(meta.tag_title)}")
    if meta.tag_album is not None:
        parts.append(f"Album: {rich_escape(meta.tag_album)}")
    return "  |  ".join(parts)


def _render_pair(pair: ScoredPair, index: int, total: int, *, verbose: bool = False) -> Panel:
    """Build a Rich Panel showing one duplicate pair."""
    score_style = score_color(pair.total_score)
    if verbose and pair.detail:
        from duplicates_detector.reporter import _format_breakdown_verbose

        breakdown_str = _format_breakdown_verbose(pair)
    else:
        breakdown_str = " | ".join(
            f"{name}: n/a" if val is None else f"{name}: {val}" for name, val in pair.breakdown.items()
        )

    a_ref = " [dim](reference)[/dim]" if pair.file_a.is_reference else ""
    b_ref = " [dim](reference)[/dim]" if pair.file_b.is_reference else ""

    a_sidecars = ""
    if pair.file_a.sidecars:
        a_sidecars = f"\n     [dim]Sidecars: {', '.join(s.name for s in pair.file_a.sidecars)}[/dim]"
    b_sidecars = ""
    if pair.file_b.sidecars:
        b_sidecars = f"\n     [dim]Sidecars: {', '.join(s.name for s in pair.file_b.sidecars)}[/dim]"

    lines = [
        f"  [bold cyan]A:[/bold cyan]{a_ref} {pair.file_a.path}",
        f"     {_format_metadata(pair.file_a)}{a_sidecars}",
        "",
        f"  [bold cyan]B:[/bold cyan]{b_ref} {pair.file_b.path}",
        f"     {_format_metadata(pair.file_b)}{b_sidecars}",
        "",
        f"  Score: [{score_style}]{pair.total_score:.1f}[/{score_style}]  ({breakdown_str})",
    ]

    return Panel(
        "\n".join(lines),
        title=f"Pair {index}/{total}",
        border_style="blue",
    )


def _print_summary(
    summary: DeletionSummary,
    console: Console,
    *,
    dry_run: bool = False,
    unit: str = "pair",
    deleter: Deleter | None = None,
) -> None:
    """Print end-of-session summary."""
    effective_deleter = deleter or PermanentDeleter()
    console.print("[bold]Summary:[/bold]")
    sidecar_suffix = ""
    if summary.sidecars_deleted > 0:
        sidecar_suffix = f" + {summary.sidecars_deleted} sidecar(s)"
    if dry_run:
        console.print(
            f"  {effective_deleter.dry_verb}: {len(summary.deleted)} file(s){sidecar_suffix}, "
            f"would free {format_size_human(summary.bytes_freed + summary.sidecar_bytes_freed)}"
        )
    else:
        console.print(
            f"  {effective_deleter.verb}: {len(summary.deleted)} file(s){sidecar_suffix}, "
            f"{format_size_human(summary.bytes_freed + summary.sidecar_bytes_freed)} freed"
        )
        if isinstance(effective_deleter, MoveDeleter):
            console.print(f"  Files moved to: {effective_deleter.destination}")
    if summary.skipped:
        console.print(f"  Skipped: {summary.skipped} {unit}(s)")
    if summary.errors:
        console.print(f"  Errors:  {len(summary.errors)}")
        for path, msg in summary.errors:
            console.print(f"    [red]{path}[/red]: {msg}")


def review_duplicates(
    pairs: list[ScoredPair],
    *,
    console: Console | None = None,
    dry_run: bool = False,
    keep_strategy: str | None = None,
    deleter: Deleter | None = None,
    action_log: ActionLog | None = None,
    ignore_list: IgnoreList | None = None,
    verbose: bool = False,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> DeletionSummary:
    """Walk the user through each duplicate pair interactively.

    For each pair, the user can:
      a — delete file A
      b — delete file B
      s — skip this pair
      q — quit the review (remaining pairs are skipped)

    Pairs where either file has already been deleted are auto-skipped.
    """
    if console is None:
        console = Console()

    effective_deleter = deleter or PermanentDeleter()
    acc = _DeletionAccumulator()

    if not pairs:
        console.print("[green]No pairs to review.[/green]")
        return DeletionSummary([], 0, [], 0)

    console.print()
    s_bang_hint = ", [bold]s![/bold] to skip & remember" if ignore_list is not None else ""
    console.print(
        f"[bold]Interactive review: {len(pairs)} pair(s).[/bold]  "
        "Choose [bold]a[/bold]/[bold]b[/bold] to delete, "
        f"[bold]s[/bold] to skip{s_bang_hint}, [bold]q[/bold] to quit."
    )
    if dry_run:
        console.print("[bold yellow]DRY RUN — no files will be removed.[/bold yellow]")
    console.print()

    for idx, pair in enumerate(pairs, 1):
        # Auto-skip if either file was already deleted
        a_gone = pair.file_a.path in acc.deleted_paths
        b_gone = pair.file_b.path in acc.deleted_paths
        if a_gone or b_gone:
            gone = pair.file_a.path if a_gone else pair.file_b.path
            console.print(f"  [dim]Pair {idx}/{len(pairs)}: skipped ({gone.name} already deleted)[/dim]")
            acc.skipped += 1
            continue

        # Skip pairs where both files are reference
        a_is_ref = pair.file_a.is_reference
        b_is_ref = pair.file_b.is_reference
        if a_is_ref and b_is_ref:
            console.print(f"  [dim]Pair {idx}/{len(pairs)}: skipped (both files are reference)[/dim]")
            acc.skipped += 1
            continue

        console.print(_render_pair(pair, idx, len(pairs), verbose=verbose))

        # Restrict choices based on reference status
        if a_is_ref:
            choices = ["b", "s", "q"]
        elif b_is_ref:
            choices = ["a", "s", "q"]
        else:
            choices = ["a", "b", "s", "q"]
        if ignore_list is not None:
            choices.insert(-1, "s!")

        # Compute keep-strategy recommendation
        default_choice = "s"
        if keep_strategy:
            recommendation = pick_delete(
                pair,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
            if recommendation and recommendation in choices:
                rec_target = pair.file_a if recommendation == "a" else pair.file_b
                if not rec_target.is_reference:
                    default_choice = recommendation
                    console.print(
                        f"  [dim]Strategy '{keep_strategy}' recommends deleting file {recommendation.upper()}[/dim]"
                    )

        choice = Prompt.ask(
            f"  {effective_deleter.prompt_verb}",
            choices=choices,
            default=default_choice,
            console=console,
        )

        if choice == "q":
            acc.skipped += len(pairs) - idx
            console.print("[dim]Quitting interactive review.[/dim]")
            break

        if choice == "s":
            acc.skipped += 1
            continue

        if choice == "s!":
            if ignore_list is not None:
                ignore_list.add(pair.file_a.path, pair.file_b.path)
            acc.skipped += 1
            continue

        target = pair.file_a if choice == "a" else pair.file_b
        kept = pair.file_b if choice == "a" else pair.file_a

        outcome = _execute_deletion(
            target.path,
            kept.path,
            effective_deleter,
            dry_run=dry_run,
            action_log=action_log,
            score=pair.total_score,
            strategy=keep_strategy or "interactive",
            console=console,
            sidecars=target.sidecars,
            sidecar_extensions=sidecar_extensions,
            no_sidecars=no_sidecars,
        )
        acc.apply_outcome(target.path, outcome)

        console.print()

    if ignore_list is not None:
        ignore_list.save()

    console.print()
    summary = acc.to_summary()
    _print_summary(summary, console, dry_run=dry_run, deleter=effective_deleter)
    return summary


def auto_delete(
    pairs: list[ScoredPair],
    *,
    strategy: str,
    console: Console | None = None,
    dry_run: bool = False,
    deleter: Deleter | None = None,
    action_log: ActionLog | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> DeletionSummary:
    """Auto-delete files based on keep strategy without user interaction.

    Respects reference protection: if the file to delete is a reference,
    the pair is skipped.  Both-reference pairs are always skipped.
    """
    if console is None:
        console = Console()

    effective_deleter = deleter or PermanentDeleter()
    acc = _DeletionAccumulator()

    if not pairs:
        console.print("[green]No pairs to process.[/green]")
        return DeletionSummary([], 0, [], 0)

    label = (
        f"DRY RUN: would auto-{effective_deleter.prompt_verb.lower()}"
        if dry_run
        else f"Auto-{effective_deleter.gerund.lower()}"
    )
    console.print(f"\n[bold]{label} using strategy '{strategy}'...[/bold]")

    for pair in pairs:
        # Auto-skip if either file was already deleted
        if pair.file_a.path in acc.deleted_paths or pair.file_b.path in acc.deleted_paths:
            acc.skipped += 1
            continue

        # Skip both-reference pairs
        if pair.file_a.is_reference and pair.file_b.is_reference:
            acc.skipped += 1
            continue

        delete_choice = pick_delete(pair, strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars)
        if delete_choice is None:
            acc.skipped += 1
            continue

        target = pair.file_a if delete_choice == "a" else pair.file_b
        kept = pair.file_b if delete_choice == "a" else pair.file_a

        # Skip if target is a reference file
        if target.is_reference:
            acc.skipped += 1
            continue

        outcome = _execute_deletion(
            target.path,
            kept.path,
            effective_deleter,
            dry_run=dry_run,
            action_log=action_log,
            score=pair.total_score,
            strategy=strategy,
            console=console,
            sidecars=target.sidecars,
            sidecar_extensions=sidecar_extensions,
            no_sidecars=no_sidecars,
        )
        acc.apply_outcome(target.path, outcome)

    console.print()
    summary = acc.to_summary()
    _print_summary(summary, console, dry_run=dry_run, deleter=effective_deleter)
    return summary


# ---------------------------------------------------------------------------
# Group-mode interactive review and auto-delete
# ---------------------------------------------------------------------------


def _render_group(
    group: DuplicateGroup,
    alive: list,
    index: int,
    total: int,
) -> Panel:
    """Build a Rich Panel showing one duplicate group."""
    score_range = (
        f"{group.max_score:.1f}"
        if group.min_score == group.max_score
        else f"{group.min_score:.1f}\u2013{group.max_score:.1f}"
    )

    lines: list[str] = []
    for idx, member in enumerate(alive, 1):
        ref_tag = " [dim](reference)[/dim]" if member.is_reference else ""
        lines.append(f"  [bold cyan]{idx}.[/bold cyan]{ref_tag} {member.path}")
        lines.append(f"     {_format_metadata(member)}")
        lines.append("")

    lines.append(f"  Score range: [{score_color(group.max_score)}]{score_range}[/{score_color(group.max_score)}]")

    return Panel(
        "\n".join(lines),
        title=f"Group {index}/{total} ({len(alive)} files)",
        border_style="blue",
    )


def review_groups(
    groups: list[DuplicateGroup],
    *,
    console: Console | None = None,
    dry_run: bool = False,
    keep_strategy: str | None = None,
    deleter: Deleter | None = None,
    action_log: ActionLog | None = None,
    ignore_list: IgnoreList | None = None,
    verbose: bool = False,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> DeletionSummary:
    """Walk the user through each duplicate group interactively.

    For each group, the user can:
      1..N — keep that numbered file (delete all others)
      s    — skip this group
      q    — quit the review
    """
    if console is None:
        console = Console()

    effective_deleter = deleter or PermanentDeleter()
    acc = _DeletionAccumulator()

    if not groups:
        console.print("[green]No groups to review.[/green]")
        return DeletionSummary([], 0, [], 0)

    console.print()
    s_bang_hint = ", [bold]s![/bold] to skip & remember" if ignore_list is not None else ""
    console.print(
        f"[bold]Interactive review: {len(groups)} group(s).[/bold]  "
        "Choose a number to [bold]keep[/bold] that file (delete others), "
        f"[bold]s[/bold] to skip{s_bang_hint}, [bold]q[/bold] to quit."
    )
    if dry_run:
        console.print("[bold yellow]DRY RUN \u2014 no files will be removed.[/bold yellow]")
    console.print()

    for idx, group in enumerate(groups, 1):
        # Filter to alive members
        alive = [m for m in group.members if m.path not in acc.deleted_paths]
        deletable = [m for m in alive if not m.is_reference]

        if len(alive) < 2 or len(deletable) < 1:
            console.print(f"  [dim]Group {idx}/{len(groups)}: skipped (nothing to delete)[/dim]")
            acc.skipped += 1
            continue

        console.print(_render_group(group, alive, idx, len(groups)))

        # Build choices: member numbers + s + [s!] + q
        member_choices = [str(i) for i in range(1, len(alive) + 1)]
        choices = member_choices + ["s", "q"]
        if ignore_list is not None:
            choices.insert(-1, "s!")

        # Compute keep-strategy recommendation
        default_choice = "s"
        if keep_strategy:
            keeper = pick_keep_from_group(
                tuple(alive),
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
            if keeper is not None:
                keeper_idx = next(
                    (i for i, m in enumerate(alive, 1) if m.path == keeper.path),
                    None,
                )
                if keeper_idx is not None:
                    default_choice = str(keeper_idx)
                    console.print(f"  [dim]Strategy '{keep_strategy}' recommends keeping file {keeper_idx}[/dim]")

        choice = Prompt.ask(
            "  Keep file",
            choices=choices,
            default=default_choice,
            console=console,
        )

        if choice == "q":
            acc.skipped += len(groups) - idx
            console.print("[dim]Quitting interactive review.[/dim]")
            break

        if choice == "s":
            acc.skipped += 1
            continue

        if choice == "s!":
            if ignore_list is not None:
                for i in range(len(alive)):
                    for j in range(i + 1, len(alive)):
                        ignore_list.add(alive[i].path, alive[j].path)
            acc.skipped += 1
            continue

        # Delete all non-keeper, non-reference alive members
        keeper_idx = int(choice) - 1
        keeper_meta = alive[keeper_idx]
        for member in alive:
            if member.path == keeper_meta.path:
                continue
            if member.is_reference:
                console.print(f"  [dim]Skipping reference file: {member.path}[/dim]")
                continue
            outcome = _execute_deletion(
                member.path,
                keeper_meta.path,
                effective_deleter,
                dry_run=dry_run,
                action_log=action_log,
                score=group.max_score,
                strategy=keep_strategy or "interactive",
                console=console,
                sidecars=member.sidecars,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
            acc.apply_outcome(member.path, outcome)

        console.print()

    if ignore_list is not None:
        ignore_list.save()

    console.print()
    summary = acc.to_summary()
    _print_summary(summary, console, dry_run=dry_run, unit="group", deleter=effective_deleter)
    return summary


def auto_delete_groups(
    groups: list[DuplicateGroup],
    *,
    strategy: str,
    console: Console | None = None,
    dry_run: bool = False,
    deleter: Deleter | None = None,
    action_log: ActionLog | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> DeletionSummary:
    """Auto-delete files from groups based on keep strategy.

    For each group, the strategy picks a keeper and all other non-reference
    members are deleted.
    """
    if console is None:
        console = Console()

    effective_deleter = deleter or PermanentDeleter()
    acc = _DeletionAccumulator()

    if not groups:
        console.print("[green]No groups to process.[/green]")
        return DeletionSummary([], 0, [], 0)

    label = (
        f"DRY RUN: would auto-{effective_deleter.prompt_verb.lower()}"
        if dry_run
        else f"Auto-{effective_deleter.gerund.lower()}"
    )
    console.print(f"\n[bold]{label} using strategy '{strategy}' (grouped)...[/bold]")

    for group in groups:
        # Filter to alive members
        alive = [m for m in group.members if m.path not in acc.deleted_paths]
        if len(alive) < 2:
            acc.skipped += 1
            continue

        # All reference → skip
        deletable = [m for m in alive if not m.is_reference]
        if not deletable:
            acc.skipped += 1
            continue

        keeper = pick_keep_from_group(
            tuple(alive),
            strategy,
            sidecar_extensions=sidecar_extensions,
            no_sidecars=no_sidecars,
        )
        if keeper is None:
            acc.skipped += 1
            continue

        for member in alive:
            if member.path == keeper.path:
                continue
            if member.is_reference:
                continue
            outcome = _execute_deletion(
                member.path,
                keeper.path,
                effective_deleter,
                dry_run=dry_run,
                action_log=action_log,
                score=group.max_score,
                strategy=strategy,
                console=console,
                sidecars=member.sidecars,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
            acc.apply_outcome(member.path, outcome)

    console.print()
    summary = acc.to_summary()
    _print_summary(summary, console, dry_run=dry_run, unit="group", deleter=effective_deleter)
    return summary
