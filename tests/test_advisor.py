from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from duplicates_detector.advisor import (
    DeletionSummary,
    review_duplicates,
    auto_delete,
    review_groups,
    auto_delete_groups,
    _format_metadata,
)
from duplicates_detector.deleter import (
    DeletionResult,
    MoveDeleter,
    PermanentDeleter,
)
from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair


# ---------------------------------------------------------------------------
# _format_metadata
# ---------------------------------------------------------------------------


class TestFormatMetadata:
    def test_full_metadata(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=3661.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        result = _format_metadata(meta)
        assert "1920x1080" in result
        assert "1:01:01" in result

    def test_short_duration(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=65.0,
            width=1280,
            height=720,
            file_size=500_000,
        )
        result = _format_metadata(meta)
        assert "1:05" in result
        assert "1280x720" in result

    def test_missing_duration(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=None,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        result = _format_metadata(meta)
        # duration is omitted (not "n/a") when None
        assert "duration" not in result.lower()
        assert "1920x1080" in result

    def test_missing_resolution(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=120.0,
            width=None,
            height=None,
            file_size=1_000_000,
        )
        result = _format_metadata(meta)
        # resolution is omitted (not "n/a") when None
        assert "resolution" not in result.lower()
        assert "2:00" in result

    def test_with_codec(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            codec="h264",
        )
        result = _format_metadata(meta)
        assert "H.264" in result

    def test_with_bitrate(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            bitrate=8_000_000,
        )
        result = _format_metadata(meta)
        assert "8.0 Mbps" in result

    def test_with_framerate(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            framerate=23.976,
        )
        result = _format_metadata(meta)
        assert "23.976 fps" in result

    def test_with_audio_channels(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            audio_channels=6,
        )
        result = _format_metadata(meta)
        assert "5.1" in result

    def test_all_new_fields(self):
        meta = VideoMetadata(
            path=Path("/v/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            codec="hevc",
            bitrate=5_000_000,
            framerate=29.97,
            audio_channels=2,
        )
        result = _format_metadata(meta)
        assert "H.265" in result
        assert "5.0 Mbps" in result
        assert "29.97 fps" in result
        assert "Stereo" in result


# ---------------------------------------------------------------------------
# review_duplicates
# ---------------------------------------------------------------------------


def _make_meta(
    name: str = "a.mp4",
    file_size: int = 1_000_000,
    is_reference: bool = False,
    duration: float | None = 120.0,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/videos/{name}"),
        filename=Path(name).stem,
        duration=duration,
        width=1920,
        height=1080,
        file_size=file_size,
        is_reference=is_reference,
        sidecars=(),  # skip sidecar discovery on fake paths
    )


def _make_pair(
    a: str = "a.mp4",
    b: str = "b.mp4",
    score: float = 80.0,
    a_is_ref: bool = False,
    b_is_ref: bool = False,
    a_file_size: int = 1_000_000,
    b_file_size: int = 2_000_000,
) -> ScoredPair:
    return ScoredPair(
        file_a=_make_meta(a, file_size=a_file_size, is_reference=a_is_ref),
        file_b=_make_meta(b, file_size=b_file_size, is_reference=b_is_ref),
        total_score=score,
        breakdown={"filename": 30.0, "duration": 35.0},
        detail={},
    )


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, highlight=False, width=200), buf


class TestReviewDuplicates:
    def test_empty_pairs(self):
        con, buf = _console()
        result = review_duplicates([], console=con)
        assert result == DeletionSummary([], 0, [], 0)
        assert "No pairs" in buf.getvalue()

    def test_skip(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s"):
            result = review_duplicates([_make_pair()], console=con)
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_delete_file_a(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates([_make_pair()], console=con)
        assert len(result.deleted) == 1
        assert result.deleted[0] == Path("/videos/a.mp4")
        assert result.bytes_freed == 1_000_000
        mock_unlink.assert_called_once()

    def test_delete_file_b(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="b"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=2_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/b.mp4")),
        ):
            result = review_duplicates([_make_pair()], console=con)
        assert len(result.deleted) == 1
        assert result.deleted[0] == Path("/videos/b.mp4")
        assert result.bytes_freed == 2_000_000
        mock_unlink.assert_called_once()

    def test_quit_skips_remaining(self):
        pairs = [_make_pair("a.mp4", "b.mp4"), _make_pair("c.mp4", "d.mp4")]
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="q"):
            result = review_duplicates(pairs, console=con)
        # Quit at pair 1, so pair 2 is remaining (1 skipped)
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_auto_skip_already_deleted(self):
        # Both pairs share file a.mp4
        pairs = [_make_pair("a.mp4", "b.mp4"), _make_pair("a.mp4", "c.mp4")]
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates(pairs, console=con)
        assert len(result.deleted) == 1
        assert result.skipped == 1
        assert "already deleted" in buf.getvalue()

    def test_file_not_found_on_delete(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", side_effect=FileNotFoundError),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates([_make_pair()], console=con)
        assert len(result.deleted) == 0
        assert result.skipped == 1
        assert "Already gone" in buf.getvalue()

    def test_permission_error_on_delete(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "unlink", side_effect=PermissionError),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates([_make_pair()], console=con)
        assert len(result.deleted) == 0
        assert len(result.errors) == 1
        assert "Permission denied" in buf.getvalue()

    def test_os_error_on_delete(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "unlink", side_effect=OSError("disk error")),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates([_make_pair()], console=con)
        assert len(result.deleted) == 0
        assert len(result.errors) == 1
        assert "disk error" in buf.getvalue()

    def test_dry_run_does_not_unlink(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates([_make_pair()], console=con, dry_run=True)
        mock_unlink.assert_not_called()
        assert len(result.deleted) == 1
        assert result.bytes_freed == 1_000_000

    def test_dry_run_summary_wording(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            review_duplicates([_make_pair()], console=con, dry_run=True)
        output = buf.getvalue()
        assert "Would delete" in output
        assert "Deleted:" not in output

    def test_dry_run_banner(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s"):
            review_duplicates([_make_pair()], console=con, dry_run=True)
        assert "DRY RUN" in buf.getvalue()

    def test_dry_run_auto_skip_works(self):
        pairs = [_make_pair("a.mp4", "b.mp4"), _make_pair("a.mp4", "c.mp4")]
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates(pairs, console=con, dry_run=True)
        assert len(result.deleted) == 1
        assert result.skipped == 1
        assert "already deleted" in buf.getvalue()

    def test_summary_output(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=5_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            review_duplicates([_make_pair()], console=con)
        output = buf.getvalue()
        assert "Summary" in output
        assert "Deleted: 1 file(s)" in output


# ---------------------------------------------------------------------------
# reference file protection in interactive mode
# ---------------------------------------------------------------------------


class TestReferenceProtection:
    def test_reference_a_only_offers_b(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="b") as mock_ask,
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=2_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/b.mp4")),
        ):
            result = review_duplicates([_make_pair(a_is_ref=True)], console=con)
        mock_ask.assert_called_once()
        assert mock_ask.call_args.kwargs["choices"] == ["b", "s", "q"]
        assert len(result.deleted) == 1
        mock_unlink.assert_called_once()

    def test_reference_b_only_offers_a(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a") as mock_ask,
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = review_duplicates([_make_pair(b_is_ref=True)], console=con)
        mock_ask.assert_called_once()
        assert mock_ask.call_args.kwargs["choices"] == ["a", "s", "q"]
        assert len(result.deleted) == 1
        mock_unlink.assert_called_once()

    def test_both_reference_auto_skipped(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask") as mock_ask:
            result = review_duplicates(
                [_make_pair(a_is_ref=True, b_is_ref=True)],
                console=con,
            )
        mock_ask.assert_not_called()
        assert result.skipped == 1
        assert len(result.deleted) == 0
        assert "both files are reference" in buf.getvalue()

    def test_reference_shown_in_panel(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s"):
            review_duplicates([_make_pair(a_is_ref=True)], console=con)
        output = buf.getvalue()
        assert "reference" in output

    def test_neither_reference_normal_prompt(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask:
            review_duplicates([_make_pair()], console=con)
        mock_ask.assert_called_once()
        assert mock_ask.call_args.kwargs["choices"] == ["a", "b", "s", "q"]


# ---------------------------------------------------------------------------
# keep strategy recommendation in interactive mode
# ---------------------------------------------------------------------------


class TestKeepRecommendation:
    def test_recommendation_sets_default(self):
        # b is bigger (2MB vs 1MB), so strategy=biggest keeps b, deletes a
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a") as mock_ask,
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            review_duplicates([_make_pair()], console=con, keep_strategy="biggest")
        assert mock_ask.call_args.kwargs["default"] == "a"

    def test_recommendation_shown_in_output(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s"):
            review_duplicates([_make_pair()], console=con, keep_strategy="biggest")
        output = buf.getvalue()
        assert "recommends" in output.lower() or "Strategy" in output

    def test_user_can_override_recommendation(self):
        # Strategy recommends deleting a, but user chooses s (skip)
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s"):
            result = review_duplicates([_make_pair()], console=con, keep_strategy="biggest")
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_undecidable_default_stays_skip(self):
        # Same file sizes → undecidable
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask:
            review_duplicates(
                [_make_pair(a_file_size=1_000_000, b_file_size=1_000_000)],
                console=con,
                keep_strategy="biggest",
            )
        assert mock_ask.call_args.kwargs["default"] == "s"

    def test_recommendation_respects_reference(self):
        # Strategy says delete a (keep biggest=b), but a is reference → fall back to skip
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask:
            review_duplicates(
                [_make_pair(a_is_ref=True)],
                console=con,
                keep_strategy="biggest",
            )
        # "a" not in choices (reference), so default should be "s"
        assert mock_ask.call_args.kwargs["default"] == "s"

    def test_no_strategy_default_is_skip(self):
        con, buf = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask:
            review_duplicates([_make_pair()], console=con)
        assert mock_ask.call_args.kwargs["default"] == "s"


# ---------------------------------------------------------------------------
# auto_delete
# ---------------------------------------------------------------------------


class TestAutoDelete:
    def test_basic_auto_delete(self):
        # b bigger → keep b, delete a
        con, buf = _console()
        with (
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = auto_delete([_make_pair()], strategy="biggest", console=con)
        assert len(result.deleted) == 1
        mock_unlink.assert_called_once()
        assert result.bytes_freed == 1_000_000

    def test_dry_run_no_unlink(self):
        con, buf = _console()
        with (
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = auto_delete(
                [_make_pair()],
                strategy="biggest",
                console=con,
                dry_run=True,
            )
        mock_unlink.assert_not_called()
        assert len(result.deleted) == 1
        assert "Would delete" in buf.getvalue()

    def test_skips_undecidable(self):
        con, buf = _console()
        result = auto_delete(
            [_make_pair(a_file_size=1_000_000, b_file_size=1_000_000)],
            strategy="biggest",
            console=con,
        )
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_skips_both_reference(self):
        con, buf = _console()
        result = auto_delete(
            [_make_pair(a_is_ref=True, b_is_ref=True)],
            strategy="biggest",
            console=con,
        )
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_skips_reference_target(self):
        # Strategy says delete a (keep biggest=b), but a is reference → skip
        con, buf = _console()
        result = auto_delete(
            [_make_pair(a_is_ref=True)],
            strategy="biggest",
            console=con,
        )
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_tracks_already_deleted(self):
        # Two pairs sharing file a
        pairs = [
            _make_pair("a.mp4", "b.mp4"),
            _make_pair("a.mp4", "c.mp4"),
        ]
        con, buf = _console()
        with (
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            result = auto_delete(pairs, strategy="biggest", console=con)
        assert len(result.deleted) == 1
        assert result.skipped == 1

    def test_empty_pairs(self):
        con, buf = _console()
        result = auto_delete([], strategy="biggest", console=con)
        assert result == DeletionSummary([], 0, [], 0)
        assert "No pairs" in buf.getvalue()

    def test_summary_printed(self):
        con, buf = _console()
        with (
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=5_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            auto_delete([_make_pair()], strategy="biggest", console=con)
        output = buf.getvalue()
        assert "Summary" in output


# ---------------------------------------------------------------------------
# Group-mode helpers
# ---------------------------------------------------------------------------


def _make_group(
    members: list[VideoMetadata] | None = None,
    pairs: list[ScoredPair] | None = None,
    group_id: int = 1,
) -> DuplicateGroup:
    if members is None:
        members = [
            _make_meta("a.mp4", file_size=2_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
            _make_meta("c.mp4", file_size=500_000),
        ]
    if pairs is None:
        pairs = [
            ScoredPair(
                file_a=members[0],
                file_b=members[1],
                total_score=80.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        if len(members) > 2:
            pairs.append(
                ScoredPair(
                    file_a=members[1],
                    file_b=members[2],
                    total_score=70.0,
                    breakdown={"filename": 25.0, "duration": 30.0},
                    detail={},
                )
            )
    scores = [p.total_score for p in pairs]
    return DuplicateGroup(
        group_id=group_id,
        members=tuple(members),
        pairs=tuple(pairs),
        max_score=max(scores),
        min_score=min(scores),
        avg_score=sum(scores) / len(scores),
    )


# ---------------------------------------------------------------------------
# review_groups
# ---------------------------------------------------------------------------


class TestReviewGroups:
    def test_empty_groups(self):
        con, buf = _console()
        result = review_groups([], console=con)
        assert result == DeletionSummary([], 0, [], 0)
        assert "No groups" in buf.getvalue()

    def test_skip_group(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s"),
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            result = review_groups([_make_group()], console=con)
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_keep_file_1_deletes_others(self):
        """User keeps file 1 (a.mp4), deletes b.mp4 and c.mp4."""
        con, buf = _console()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            # Return unique paths for each resolve call
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4"), Path("/videos/c.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="1"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=500_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            result = review_groups([_make_group()], console=con)
        assert len(result.deleted) == 2
        assert mock_unlink.call_count == 2

    def test_quit_skips_remaining(self):
        groups = [_make_group(group_id=1), _make_group(group_id=2)]
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="q"),
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            result = review_groups(groups, console=con)
        # Quit at group 1, so group 2 is remaining (1 skipped)
        assert result.skipped == 1

    def test_all_reference_auto_skipped(self):
        members = [
            _make_meta("a.mp4", is_reference=True),
            _make_meta("b.mp4", is_reference=True),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask") as mock_ask,
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            result = review_groups([group], console=con)
        mock_ask.assert_not_called()
        assert result.skipped == 1

    def test_reference_not_deleted_when_not_keeper(self):
        """Reference file in group is skipped during deletion even if not chosen as keeper."""
        members = [
            _make_meta("a.mp4", file_size=2_000_000),
            _make_meta("b.mp4", file_size=1_000_000, is_reference=True),
            _make_meta("c.mp4", file_size=500_000),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4"), Path("/videos/c.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="1"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=500_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            result = review_groups([group], console=con)
        # Only c.mp4 deleted (b.mp4 is reference, skipped)
        assert len(result.deleted) == 1
        assert mock_unlink.call_count == 1
        assert "Skipping reference" in buf.getvalue()

    def test_dry_run_no_unlink(self):
        con, buf = _console()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4"), Path("/videos/c.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="1"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=500_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            result = review_groups([_make_group()], console=con, dry_run=True)
        mock_unlink.assert_not_called()
        assert len(result.deleted) == 2
        assert "Would delete" in buf.getvalue()

    def test_summary_uses_group_unit(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s"),
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            review_groups([_make_group()], console=con)
        assert "group(s)" in buf.getvalue()


class TestGroupKeepRecommendation:
    def test_recommendation_sets_default(self):
        # a.mp4 is biggest (2MB), should be recommended as keeper
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask,
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            review_groups(
                [_make_group()],
                console=con,
                keep_strategy="biggest",
            )
        assert mock_ask.call_args.kwargs["default"] == "1"

    def test_undecidable_default_is_skip(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask,
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            review_groups([group], console=con, keep_strategy="biggest")
        assert mock_ask.call_args.kwargs["default"] == "s"

    def test_no_strategy_default_is_skip(self):
        con, buf = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask,
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            review_groups([_make_group()], console=con)
        assert mock_ask.call_args.kwargs["default"] == "s"


# ---------------------------------------------------------------------------
# auto_delete_groups
# ---------------------------------------------------------------------------


class TestAutoDeleteGroups:
    def test_basic_auto_delete(self):
        con, buf = _console()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4"), Path("/videos/c.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=500_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            result = auto_delete_groups(
                [_make_group()],
                strategy="biggest",
                console=con,
            )
        # a.mp4 is biggest (2MB) → kept; b and c deleted
        assert len(result.deleted) == 2
        assert mock_unlink.call_count == 2

    def test_dry_run_no_unlink(self):
        con, buf = _console()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4"), Path("/videos/c.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=500_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            result = auto_delete_groups(
                [_make_group()],
                strategy="biggest",
                console=con,
                dry_run=True,
            )
        mock_unlink.assert_not_called()
        assert len(result.deleted) == 2

    def test_skips_undecidable(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        with patch.object(Path, "resolve", side_effect=lambda: Path("/unique")):
            result = auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
            )
        assert result.skipped == 1
        assert len(result.deleted) == 0

    def test_skips_all_reference(self):
        members = [
            _make_meta("a.mp4", is_reference=True),
            _make_meta("b.mp4", is_reference=True),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        with patch.object(Path, "resolve", side_effect=lambda: Path("/unique")):
            result = auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
            )
        assert result.skipped == 1

    def test_reference_files_protected(self):
        members = [
            _make_meta("a.mp4", file_size=2_000_000),
            _make_meta("b.mp4", file_size=1_000_000, is_reference=True),
            _make_meta("c.mp4", file_size=500_000),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4"), Path("/videos/c.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=500_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            result = auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
            )
        # Only c.mp4 deleted (b.mp4 is reference)
        assert len(result.deleted) == 1
        assert mock_unlink.call_count == 1

    def test_empty_groups(self):
        con, buf = _console()
        result = auto_delete_groups([], strategy="biggest", console=con)
        assert result == DeletionSummary([], 0, [], 0)
        assert "No groups" in buf.getvalue()

    def test_summary_uses_group_unit(self):
        """When groups are skipped, the summary should say 'group(s)'."""
        # Equal sizes → undecidable → skipped
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        con, buf = _console()
        with patch.object(Path, "resolve", side_effect=lambda: Path("/unique")):
            auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
            )
        assert "group(s)" in buf.getvalue()


# ---------------------------------------------------------------------------
# Deleter integration
# ---------------------------------------------------------------------------


class TestDeleterIntegration:
    """Verify that the deleter parameter is threaded through all 4 advisor functions."""

    def _mock_deleter(self, bytes_freed: int = 500_000):
        """Create a mock deleter that returns a DeletionResult."""
        d = MagicMock(spec=PermanentDeleter)
        d.remove.return_value = DeletionResult(
            path=Path("/videos/a.mp4"),
            bytes_freed=bytes_freed,
        )
        d.verb = "Deleted"
        d.dry_verb = "Would delete"
        d.prompt_verb = "Delete"
        return d

    def test_review_duplicates_uses_deleter(self):
        pair = _make_pair()
        con, buf = _console()
        mock_d = self._mock_deleter()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "resolve", return_value=Path("/videos/a.mp4")),
        ):
            review_duplicates([pair], console=con, deleter=mock_d)
        mock_d.remove.assert_called_once()

    def test_auto_delete_uses_deleter(self):
        pair = _make_pair()
        con, _ = _console()
        mock_d = self._mock_deleter()
        with patch.object(Path, "resolve", return_value=Path("/videos/unique")):
            auto_delete([pair], strategy="biggest", console=con, deleter=mock_d)
        mock_d.remove.assert_called_once()

    def test_review_groups_uses_deleter(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_d = self._mock_deleter()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="2"),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            review_groups([group], console=con, deleter=mock_d)
        mock_d.remove.assert_called_once()

    def test_auto_delete_groups_uses_deleter(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_d = self._mock_deleter()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with patch.object(Path, "resolve", side_effect=resolve_side_effect):
            auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
                deleter=mock_d,
            )
        mock_d.remove.assert_called_once()

    def test_default_deleter_is_permanent(self):
        """deleter=None should fall back to PermanentDeleter (Path.unlink)."""
        pair = _make_pair()
        con, _ = _console()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "unlink") as mock_unlink,
            patch.object(Path, "stat", return_value=MagicMock(st_size=100)),
            patch.object(Path, "resolve", return_value=Path("/videos/a.mp4")),
        ):
            review_duplicates([pair], console=con, deleter=None)
        mock_unlink.assert_called_once()

    def test_dry_run_does_not_call_deleter_remove(self):
        pair = _make_pair()
        con, _ = _console()
        mock_d = self._mock_deleter()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=100)),
            patch.object(Path, "resolve", return_value=Path("/videos/a.mp4")),
        ):
            review_duplicates([pair], console=con, dry_run=True, deleter=mock_d)
        mock_d.remove.assert_not_called()

    def test_deleter_oserror_caught(self):
        pair = _make_pair()
        con, buf = _console()
        mock_d = self._mock_deleter()
        mock_d.remove.side_effect = OSError("disk full")
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "resolve", return_value=Path("/videos/a.mp4")),
        ):
            result = review_duplicates([pair], console=con, deleter=mock_d)
        assert len(result.errors) == 1
        assert "disk full" in result.errors[0][1]

    def test_deleter_verb_in_summary(self):
        pair = _make_pair()
        con, buf = _console()
        mock_d = self._mock_deleter()
        mock_d.verb = "Trashed"
        mock_d.dry_verb = "Would trash"
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "resolve", return_value=Path("/videos/a.mp4")),
        ):
            review_duplicates([pair], console=con, deleter=mock_d)
        output = buf.getvalue()
        assert "Trashed" in output


# ---------------------------------------------------------------------------
# link_target passed to deleter
# ---------------------------------------------------------------------------


class TestLinkTarget:
    def _mock_deleter(self, bytes_freed: int = 500_000):
        d = MagicMock(spec=PermanentDeleter)
        d.remove.return_value = DeletionResult(
            path=Path("/videos/a.mp4"),
            bytes_freed=bytes_freed,
        )
        d.verb = "Deleted"
        d.dry_verb = "Would delete"
        d.prompt_verb = "Delete"
        return d

    def test_review_duplicates_passes_link_target(self):
        pair = _make_pair()
        con, buf = _console()
        mock_d = self._mock_deleter()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "resolve", return_value=Path("/videos/a.mp4")),
        ):
            review_duplicates([pair], console=con, deleter=mock_d)
        # When deleting "a", the kept file is "b"
        call_kwargs = mock_d.remove.call_args.kwargs
        assert "link_target" in call_kwargs
        assert call_kwargs["link_target"] == pair.file_b.path

    def test_auto_delete_passes_link_target(self):
        pair = _make_pair()
        con, _ = _console()
        mock_d = self._mock_deleter()
        with patch.object(Path, "resolve", return_value=Path("/videos/unique")):
            auto_delete([pair], strategy="biggest", console=con, deleter=mock_d)
        call_kwargs = mock_d.remove.call_args.kwargs
        assert "link_target" in call_kwargs
        # biggest keeps b (2MB), deletes a → link_target is b's path
        assert call_kwargs["link_target"] == pair.file_b.path

    def test_review_groups_passes_link_target(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_d = self._mock_deleter()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="2"),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            review_groups([group], console=con, deleter=mock_d)
        call_kwargs = mock_d.remove.call_args.kwargs
        assert "link_target" in call_kwargs
        # Keeper is b.mp4 (index 2), so a.mp4 deleted with link_target=b.mp4
        assert call_kwargs["link_target"] == members[1].path

    def test_auto_delete_groups_passes_link_target(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_d = self._mock_deleter()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with patch.object(Path, "resolve", side_effect=resolve_side_effect):
            auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
                deleter=mock_d,
            )
        call_kwargs = mock_d.remove.call_args.kwargs
        assert "link_target" in call_kwargs
        # biggest keeps b (2MB), link_target should be b's path
        assert call_kwargs["link_target"] == members[1].path


# ---------------------------------------------------------------------------
# Action log integration
# ---------------------------------------------------------------------------


class TestActionLogIntegration:
    """Verify that advisor functions call action_log.log() with expected fields."""

    @staticmethod
    def _mock_action_log():
        return MagicMock()

    def test_review_duplicates_logs_action(self):
        pair = _make_pair()
        con, _ = _console()
        mock_log = self._mock_action_log()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            review_duplicates([pair], console=con, dry_run=True, action_log=mock_log)
        mock_log.log.assert_called_once()
        kw = mock_log.log.call_args.kwargs
        assert kw["action"] == "deleted"
        assert kw["score"] == pair.total_score
        assert kw["strategy"] == "interactive"
        assert kw["kept"] == pair.file_b.path
        assert kw["dry_run"] is True

    def test_review_duplicates_logs_with_keep_strategy(self):
        pair = _make_pair()
        con, _ = _console()
        mock_log = self._mock_action_log()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="a"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            review_duplicates(
                [pair],
                console=con,
                keep_strategy="biggest",
                action_log=mock_log,
                dry_run=True,
            )
        kw = mock_log.log.call_args.kwargs
        assert kw["strategy"] == "biggest"

    def test_auto_delete_logs_action(self):
        pair = _make_pair()
        con, _ = _console()
        mock_log = self._mock_action_log()
        with (
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            auto_delete([pair], strategy="biggest", console=con, action_log=mock_log)
        mock_log.log.assert_called_once()
        kw = mock_log.log.call_args.kwargs
        assert kw["action"] == "deleted"
        assert kw["score"] == pair.total_score
        assert kw["strategy"] == "biggest"
        assert kw["kept"] == pair.file_b.path
        assert kw["dry_run"] is False

    def test_auto_delete_dry_run_logs_dry_run_true(self):
        pair = _make_pair()
        con, _ = _console()
        mock_log = self._mock_action_log()
        with (
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")),
        ):
            auto_delete([pair], strategy="biggest", console=con, dry_run=True, action_log=mock_log)
        kw = mock_log.log.call_args.kwargs
        assert kw["dry_run"] is True

    def test_review_groups_logs_action(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_log = self._mock_action_log()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="2"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            review_groups([group], console=con, action_log=mock_log, dry_run=True)
        mock_log.log.assert_called_once()
        kw = mock_log.log.call_args.kwargs
        assert kw["action"] == "deleted"
        assert kw["score"] == group.max_score
        assert kw["strategy"] == "interactive"
        assert kw["kept"] == members[1].path
        assert kw["dry_run"] is True

    def test_auto_delete_groups_logs_action(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_log = self._mock_action_log()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch.object(Path, "unlink"),
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
                action_log=mock_log,
            )
        mock_log.log.assert_called_once()
        kw = mock_log.log.call_args.kwargs
        assert kw["action"] == "deleted"
        assert kw["score"] == group.max_score
        assert kw["strategy"] == "biggest"
        assert kw["kept"] == members[1].path
        assert kw["dry_run"] is False

    def test_auto_delete_groups_dry_run_logs_dry_run_true(self):
        members = [
            _make_meta("a.mp4", file_size=1_000_000),
            _make_meta("b.mp4", file_size=2_000_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_log = self._mock_action_log()
        call_count = [0]

        def resolve_side_effect():
            call_count[0] += 1
            paths = [Path("/videos/a.mp4"), Path("/videos/b.mp4")]
            return paths[min(call_count[0] - 1, len(paths) - 1)]

        with (
            patch.object(Path, "stat", return_value=MagicMock(st_size=1_000_000)),
            patch.object(Path, "resolve", side_effect=resolve_side_effect),
        ):
            auto_delete_groups(
                [group],
                strategy="biggest",
                console=con,
                dry_run=True,
                action_log=mock_log,
            )
        kw = mock_log.log.call_args.kwargs
        assert kw["dry_run"] is True

    def test_move_deleter_logs_destination(self):
        pair = _make_pair()
        con, _ = _console()
        mock_log = self._mock_action_log()
        mock_d = MagicMock()
        mock_d.verb = "Moved"
        mock_d.dry_verb = "Would move"
        mock_d.gerund = "Moving"
        mock_d.prompt_verb = "Move"
        mock_d.remove.return_value = DeletionResult(
            path=Path("/videos/a.mp4"),
            bytes_freed=1_000_000,
            destination=Path("/staging/a.mp4"),
        )
        with patch.object(Path, "resolve", side_effect=lambda: Path("/videos/a.mp4")):
            auto_delete([pair], strategy="biggest", console=con, deleter=mock_d, action_log=mock_log)
        kw = mock_log.log.call_args.kwargs
        assert kw["destination"] == Path("/staging/a.mp4")


# ---------------------------------------------------------------------------
# Ignore-list (s!) behavior in interactive review
# ---------------------------------------------------------------------------


class TestIgnoreListIntegration:
    """Verify s! choice adds pairs to ignore list and save is called."""

    @staticmethod
    def _mock_ignore_list():
        return MagicMock()

    def test_pair_mode_s_bang_adds_pair(self):
        pair = _make_pair()
        con, _ = _console()
        mock_il = self._mock_ignore_list()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s!"):
            result = review_duplicates([pair], console=con, ignore_list=mock_il)
        mock_il.add.assert_called_once_with(pair.file_a.path, pair.file_b.path)
        assert result.skipped == 1

    def test_pair_mode_s_bang_saves(self):
        pair = _make_pair()
        con, _ = _console()
        mock_il = self._mock_ignore_list()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s!"):
            review_duplicates([pair], console=con, ignore_list=mock_il)
        mock_il.save.assert_called_once()

    def test_pair_mode_s_bang_in_choices(self):
        pair = _make_pair()
        con, _ = _console()
        mock_il = self._mock_ignore_list()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s!") as mock_ask:
            review_duplicates([pair], console=con, ignore_list=mock_il)
        choices = mock_ask.call_args.kwargs["choices"]
        assert "s!" in choices

    def test_pair_mode_no_s_bang_without_ignore_list(self):
        pair = _make_pair()
        con, _ = _console()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="s") as mock_ask:
            review_duplicates([pair], console=con, ignore_list=None)
        choices = mock_ask.call_args.kwargs["choices"]
        assert "s!" not in choices

    def test_group_mode_s_bang_adds_all_pairwise(self):
        members = [
            _make_meta("a.mp4", file_size=2_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
            _make_meta("c.mp4", file_size=500_000),
        ]
        group = _make_group(members=members)
        con, _ = _console()
        mock_il = self._mock_ignore_list()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s!"),
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            result = review_groups([group], console=con, ignore_list=mock_il)
        # 3 members → 3 pairwise combos: (a,b), (a,c), (b,c)
        assert mock_il.add.call_count == 3
        assert result.skipped == 1

    def test_group_mode_s_bang_saves(self):
        group = _make_group()
        con, _ = _console()
        mock_il = self._mock_ignore_list()
        with (
            patch("duplicates_detector.advisor.Prompt.ask", return_value="s!"),
            patch.object(Path, "resolve", side_effect=lambda: Path("/unique")),
        ):
            review_groups([group], console=con, ignore_list=mock_il)
        mock_il.save.assert_called_once()

    def test_save_called_on_quit(self):
        pair = _make_pair()
        con, _ = _console()
        mock_il = self._mock_ignore_list()
        with patch("duplicates_detector.advisor.Prompt.ask", return_value="q"):
            review_duplicates([pair], console=con, ignore_list=mock_il)
        mock_il.save.assert_called_once()


# ---------------------------------------------------------------------------
# Sidecar co-deletion
# ---------------------------------------------------------------------------


class TestSidecarCoDeletion:
    def test_sidecars_deleted_with_media(self, tmp_path):
        """Sidecar files are deleted alongside the main media file."""
        media_a = tmp_path / "a.jpg"
        media_a.write_bytes(b"A" * 1000)
        sidecar_xmp = tmp_path / "a.xmp"
        sidecar_xmp.write_bytes(b"X" * 200)
        sidecar_aae = tmp_path / "a.aae"
        sidecar_aae.write_bytes(b"Y" * 100)
        media_b = tmp_path / "b.jpg"
        media_b.write_bytes(b"B" * 2000)

        meta_a = VideoMetadata(
            path=media_a,
            filename="a",
            duration=None,
            width=1920,
            height=1080,
            file_size=1000,
            sidecars=(sidecar_xmp, sidecar_aae),
        )
        meta_b = VideoMetadata(
            path=media_b,
            filename="b",
            duration=None,
            width=1920,
            height=1080,
            file_size=2000,
        )
        pair = ScoredPair(
            file_a=meta_a,
            file_b=meta_b,
            total_score=80.0,
            breakdown={"filename": 30.0},
            detail={},
        )
        con, buf = _console()
        result = auto_delete(
            [pair],
            strategy="biggest",
            console=con,
            deleter=PermanentDeleter(),
        )
        # media_a deleted (b is bigger), plus 2 sidecars
        assert not media_a.exists()
        assert not sidecar_xmp.exists()
        assert not sidecar_aae.exists()
        assert media_b.exists()
        assert result.sidecars_deleted == 2
        assert result.sidecar_bytes_freed == 300

    def test_sidecar_logged_with_sidecar_of(self, tmp_path):
        """Action log entries for sidecars include sidecar_of field."""
        import json

        log_file = tmp_path / "actions.jsonl"
        media_a = tmp_path / "a.jpg"
        media_a.write_bytes(b"A" * 1000)
        sidecar = tmp_path / "a.xmp"
        sidecar.write_bytes(b"X" * 200)
        media_b = tmp_path / "b.jpg"
        media_b.write_bytes(b"B" * 2000)

        from duplicates_detector.actionlog import ActionLog

        meta_a = VideoMetadata(
            path=media_a,
            filename="a",
            duration=None,
            width=1920,
            height=1080,
            file_size=1000,
            sidecars=(sidecar,),
        )
        meta_b = VideoMetadata(
            path=media_b,
            filename="b",
            duration=None,
            width=1920,
            height=1080,
            file_size=2000,
        )
        pair = ScoredPair(
            file_a=meta_a,
            file_b=meta_b,
            total_score=80.0,
            breakdown={"filename": 30.0},
            detail={},
        )
        con, _ = _console()
        with ActionLog(log_file) as action_log:
            auto_delete(
                [pair],
                strategy="biggest",
                console=con,
                deleter=PermanentDeleter(),
                action_log=action_log,
            )

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2  # main file + sidecar
        main_record = json.loads(lines[0])
        sidecar_record = json.loads(lines[1])
        assert "sidecar_of" not in main_record
        assert "sidecar_of" in sidecar_record
        assert sidecar_record["sidecar_of"] == str(media_a.resolve())
