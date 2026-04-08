from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from io import StringIO
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch, MagicMock, call, ANY

from rich.console import Console

import pytest

from duplicates_detector.cli import (
    parse_args,
    main,
    _run_single_pipeline_ssim,
    _build_parser,
    _parse_thumbnail_size,
    _validate_content_params,
    _validate_replay_conflicts,
)
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.pipeline import PipelineController, PipelineResult
from duplicates_detector.scanner import MediaFile
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.summary import PipelineStats


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self):
        args = parse_args(["/some/dir"])
        assert args.directories == ["/some/dir"]
        assert args.no_recursive is None
        assert args.threshold is None
        assert args.workers is None
        assert args.extensions is None
        assert args.verbose is None
        assert args.interactive is False

    def test_interactive_flag(self):
        args = parse_args(["-i", "/some/dir"])
        assert args.interactive is True

    def test_all_flags(self):
        args = parse_args(
            [
                "/videos",
                "--no-recursive",
                "--threshold",
                "80",
                "--workers",
                "4",
                "--extensions",
                "mp4,mkv",
                "-v",
                "-i",
            ]
        )
        assert args.no_recursive is True
        assert args.threshold == 80
        assert args.workers == 4
        assert args.extensions == "mp4,mkv"
        assert args.verbose is True
        assert args.interactive is True

    def test_default_directory(self):
        args = parse_args([])
        assert args.directories == ["."]

    def test_multiple_directories(self):
        args = parse_args(["/dir_a", "/dir_b", "/dir_c"])
        assert args.directories == ["/dir_a", "/dir_b", "/dir_c"]

    def test_extensions_string(self):
        args = parse_args(["--extensions", "mp4,avi,mkv", "/dir"])
        assert args.extensions == "mp4,avi,mkv"

    def test_dry_run_flag(self):
        args = parse_args(["--dry-run", "/dir"])
        assert args.dry_run is True

    def test_dry_run_default_false(self):
        args = parse_args(["/dir"])
        assert args.dry_run is False

    def test_format_default(self):
        args = parse_args(["/dir"])
        assert args.format is None

    def test_format_json(self):
        args = parse_args(["--format", "json", "/dir"])
        assert args.format == "json"

    def test_format_csv(self):
        args = parse_args(["--format", "csv", "/dir"])
        assert args.format == "csv"

    def test_format_shell(self):
        args = parse_args(["--format", "shell", "/dir"])
        assert args.format == "shell"

    def test_format_html(self):
        args = parse_args(["--format", "html", "/dir"])
        assert args.format == "html"

    def test_format_invalid_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(["--format", "xml", "/dir"])

    def test_exclude_default_none(self):
        args = parse_args(["/dir"])
        assert args.exclude is None

    def test_exclude_single(self):
        args = parse_args(["--exclude", "**/thumbnails/**", "/dir"])
        assert args.exclude == ["**/thumbnails/**"]

    def test_exclude_multiple(self):
        args = parse_args(
            [
                "--exclude",
                "**/thumbnails/**",
                "--exclude",
                "*.tmp",
                "/dir",
            ]
        )
        assert args.exclude == ["**/thumbnails/**", "*.tmp"]

    def test_reference_default_none(self):
        args = parse_args(["/dir"])
        assert args.reference is None

    def test_reference_single(self):
        args = parse_args(["--reference", "/ref", "/dir"])
        assert args.reference == ["/ref"]

    def test_reference_multiple(self):
        args = parse_args(["--reference", "/ref_a", "--reference", "/ref_b", "/dir"])
        assert args.reference == ["/ref_a", "/ref_b"]

    def test_output_default_none(self):
        args = parse_args(["/dir"])
        assert args.output is None

    def test_output_flag(self):
        args = parse_args(["--output", "results.json", "/dir"])
        assert args.output == "results.json"


# ---------------------------------------------------------------------------
# filter flags in parse_args
# ---------------------------------------------------------------------------


class TestFilterFlags:
    def test_min_size_default_none(self):
        args = parse_args(["/dir"])
        assert args.min_size is None

    def test_max_size_default_none(self):
        args = parse_args(["/dir"])
        assert args.max_size is None

    def test_min_duration_default_none(self):
        args = parse_args(["/dir"])
        assert args.min_duration is None

    def test_max_duration_default_none(self):
        args = parse_args(["/dir"])
        assert args.max_duration is None

    def test_min_size_parsed(self):
        args = parse_args(["--min-size", "10MB", "/dir"])
        assert args.min_size == 10 * 1024**2

    def test_max_size_parsed(self):
        args = parse_args(["--max-size", "1.5GB", "/dir"])
        assert args.max_size == int(1.5 * 1024**3)

    def test_min_duration_parsed(self):
        args = parse_args(["--min-duration", "30.5", "/dir"])
        assert args.min_duration == 30.5

    def test_max_duration_parsed(self):
        args = parse_args(["--max-duration", "3600", "/dir"])
        assert args.max_duration == 3600.0

    def test_invalid_size_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--min-size", "banana", "/dir"])

    def test_invalid_duration_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--min-duration", "not-a-number", "/dir"])

    def test_min_resolution_default_none(self):
        args = parse_args(["/dir"])
        assert args.min_resolution is None

    def test_max_resolution_default_none(self):
        args = parse_args(["/dir"])
        assert args.max_resolution is None

    def test_min_resolution_arg(self):
        args = parse_args(["--min-resolution", "1920x1080", "/dir"])
        assert args.min_resolution == "1920x1080"

    def test_max_resolution_arg(self):
        args = parse_args(["--max-resolution", "3840x2160", "/dir"])
        assert args.max_resolution == "3840x2160"

    def test_min_bitrate_arg(self):
        args = parse_args(["--min-bitrate", "5Mbps", "/dir"])
        assert args.min_bitrate == "5Mbps"

    def test_max_bitrate_arg(self):
        args = parse_args(["--max-bitrate", "20Mbps", "/dir"])
        assert args.max_bitrate == "20Mbps"

    def test_codec_arg(self):
        args = parse_args(["--codec", "h264,hevc", "/dir"])
        assert args.codec == "h264,hevc"

    def test_ignore_file_arg(self):
        args = parse_args(["--ignore-file", "/tmp/ignored.json", "/dir"])
        assert args.ignore_file == "/tmp/ignored.json"

    def test_log_arg(self):
        args = parse_args(["--log", "/tmp/actions.jsonl", "/dir"])
        assert args.log == "/tmp/actions.jsonl"

    def test_clear_ignored(self):
        args = parse_args(["--clear-ignored", "/dir"])
        assert args.clear_ignored is True

    def test_clear_ignored_default_false(self):
        args = parse_args(["/dir"])
        assert args.clear_ignored is False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _make_meta(
    path: str,
    duration: float = 120.0,
    is_reference: bool = False,
    file_size: int = 1_000_000,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(path),
        filename=Path(path).stem,
        duration=duration,
        width=1920,
        height=1080,
        file_size=file_size,
        mtime=1_700_000_000.0,
        is_reference=is_reference,
    )


def _make_pair(file_a: VideoMetadata, file_b: VideoMetadata, score: float = 85.0) -> ScoredPair:
    return ScoredPair(
        file_a=file_a,
        file_b=file_b,
        total_score=score,
        breakdown={"content": score},
        detail={"content": (score / 100.0, 100.0)},
    )


def _make_ssim_args(tmp_path: Path, *, mode: str = "video") -> argparse.Namespace:
    return argparse.Namespace(
        directories=[str(tmp_path)],
        reference=None,
        extensions=None,
        exclude=None,
        no_recursive=False,
        workers=1,
        verbose=False,
        quiet=True,
        min_resolution=None,
        max_resolution=None,
        min_bitrate=None,
        max_bitrate=None,
        codec=None,
        min_size=None,
        max_size=None,
        min_duration=None,
        max_duration=None,
        audio=False,
        threshold=50,
        rotation_invariant=False,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Helper: mock _scan_files_iter for the fast file-count pass in _main_scan.
# The count pass calls scanner._scan_files_iter before run_pipeline.  Tests
# that mock run_pipeline but scan an empty tmp_path need this patch so the
# count >= 2 gate does not trigger an early return.
# ---------------------------------------------------------------------------
_SCAN_ITER_TARGET = "duplicates_detector.scanner._scan_files_iter"


def _mock_scan_iter(*paths: Path):
    """Return a patch context that makes _scan_files_iter yield *paths*."""
    return patch(_SCAN_ITER_TARGET, side_effect=lambda *a, **kw: iter(paths))


def _mock_scan_iter_video():
    """Convenience: 2 video files for the count pass."""
    return _mock_scan_iter(Path("a.mp4"), Path("b.mp4"))


def _mock_scan_iter_auto():
    """Convenience: 1 video + 1 image for the auto-mode count pass."""
    return _mock_scan_iter(Path("a.mp4"), Path("b.jpg"))


def _wait_for(predicate, *, timeout: float = 1.0, interval: float = 0.01) -> bool:
    """Poll until *predicate* becomes true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestMain:
    def test_full_pipeline(self, tmp_path):
        """All pipeline steps are called in order with correct args."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path)])

        mock_pipeline.assert_called_once()
        mock_report.assert_called_once()

    def test_file_not_found_exits_1(self):
        with patch(
            "duplicates_detector.cli.run_pipeline",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("nope"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["/nonexistent"])
            assert exc_info.value.code == 1

    def test_not_a_directory_exits_1(self):
        with patch(
            "duplicates_detector.cli.run_pipeline",
            new_callable=AsyncMock,
            side_effect=NotADirectoryError("nope"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["/some/file"])
            assert exc_info.value.code == 1

    def test_permission_error_exits_1(self):
        with patch(
            "duplicates_detector.cli.run_pipeline",
            new_callable=AsyncMock,
            side_effect=PermissionError("denied"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["/protected"])
            assert exc_info.value.code == 1

    def test_runtime_error_exits_1(self):
        with patch(
            "duplicates_detector.cli.run_pipeline",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ffprobe missing"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["/dir"])
            assert exc_info.value.code == 1

    def test_keyboard_interrupt_exits_130(self):
        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=KeyboardInterrupt,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["/dir"])
            assert exc_info.value.code == 130

    def test_fewer_than_2_files(self):
        """Pipeline runs but scan finds < 2 files — early return before reporting."""
        with (
            _mock_scan_iter(Path("only_one.mp4")),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=1),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main(["/dir"])
            mock_pipeline.assert_called_once()
            mock_report.assert_not_called()

    def test_fewer_than_2_metadata(self):
        """Pipeline runs and scan found 2+ files but no pairs — reporting still called."""
        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main(["/dir"])
            mock_pipeline.assert_called_once()
            mock_report.assert_called_once()

    def test_extensions_parsed_to_frozenset(self):
        """--extensions causes the pipeline to receive a frozenset of extensions."""
        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
        ):
            main(["--extensions", "mp4,mkv,avi", "/dir"])

        extensions = mock_pipeline.call_args.kwargs.get("extensions")
        assert extensions == frozenset({".mp4", ".mkv", ".avi"})

    def test_no_recursive_flag(self):
        """--no-recursive causes the pipeline to receive recursive=False."""
        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
        ):
            main(["--no-recursive", "/dir"])

        assert mock_pipeline.call_args.kwargs.get("recursive") is False

    def test_multiple_directories_passed_to_scanner(self):
        """Multiple directories are passed through to run_pipeline."""
        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
        ):
            main(["/dir_a", "/dir_b"])

        dirs = mock_pipeline.call_args.kwargs.get("directories")
        assert dirs is not None
        dir_strs = [str(d) for d in dirs]
        assert "/dir_a" in dir_strs
        assert "/dir_b" in dir_strs

    def test_interactive_calls_review_duplicates(self, tmp_path):
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates") as mock_review,
        ):
            main([str(tmp_path), "-i"])

        mock_review.assert_called_once_with(
            pairs,
            dry_run=False,
            keep_strategy=None,
            deleter=ANY,
            action_log=ANY,
            ignore_list=ANY,
            verbose=False,
            sidecar_extensions=ANY,
            no_sidecars=ANY,
        )

    def test_size_filter_reduces_metadata_before_scoring(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        metadata = [
            _make_meta("a.mp4"),  # file_size=1_000_000 (default)
            _make_meta("b.mp4"),
            _make_meta("c.mp4"),
        ]
        # Override file_size on the first item to make it small
        metadata[0] = VideoMetadata(
            path=Path("a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=100,
        )

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--min-size", "1KB"])

        # Pipeline handles filtering internally; verify it was called
        mock_pipeline.assert_called_once()

    def test_zero_max_duration_still_applies_filter(self, tmp_path):
        """Regression: --max-duration 0 must not be skipped by the truthiness gate."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--max-duration", "0"])

        # Pipeline receives max_duration=0.0 (not skipped by truthiness gate)
        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["max_duration"] == 0.0

    def test_duration_filter_reduces_metadata_before_scoring(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        metadata = [
            _make_meta("a.mp4", duration=10.0),
            _make_meta("b.mp4", duration=120.0),
            _make_meta("c.mp4", duration=130.0),
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--min-duration", "60"])

        # Pipeline handles filtering internally; verify it was called
        mock_pipeline.assert_called_once()

    def test_dry_run_passed_to_review(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates") as mock_review,
        ):
            main([str(tmp_path), "-i", "--dry-run"])

        mock_review.assert_called_once_with(
            pairs,
            dry_run=True,
            keep_strategy=None,
            deleter=ANY,
            action_log=ANY,
            ignore_list=ANY,
            verbose=False,
            sidecar_extensions=ANY,
            no_sidecars=ANY,
        )

    def test_interactive_not_called_without_flag(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates") as mock_review,
        ):
            main([str(tmp_path)])

        mock_review.assert_not_called()

    def test_interactive_not_called_when_no_pairs(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates") as mock_review,
        ):
            main([str(tmp_path), "-i"])

        mock_review.assert_not_called()

    def test_format_json_calls_write_json(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_json") as mock_json,
        ):
            main([str(tmp_path), "--format", "json"])

        mock_json.assert_called_once()

    def test_format_csv_calls_write_csv(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_csv") as mock_csv,
        ):
            main([str(tmp_path), "--format", "csv"])

        mock_csv.assert_called_once()

    def test_format_shell_calls_write_shell(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_shell") as mock_shell,
        ):
            main([str(tmp_path), "--format", "shell"])

        mock_shell.assert_called_once()

    def test_format_html_calls_write_html(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.html_report.write_html") as mock_html,
            patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}),
        ):
            main([str(tmp_path), "--format", "html", "--quiet"])

        mock_html.assert_called_once()

    def test_format_html_hint_without_output(self, tmp_path, capsys):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.html_report.write_html"),
            patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}),
        ):
            main([str(tmp_path), "--format", "html"])

        captured = capsys.readouterr()
        assert "hint" in captured.err.lower() or "output" in captured.err.lower()

    def test_format_html_hint_suppressed_with_quiet(self, tmp_path, capsys):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.html_report.write_html"),
            patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}),
        ):
            main([str(tmp_path), "--format", "html", "--quiet"])

        captured = capsys.readouterr()
        assert "hint" not in captured.err.lower()

    def test_format_html_json_envelope_ignored(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.html_report.write_html") as mock_html,
            patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}),
        ):
            main([str(tmp_path), "--format", "html", "--json-envelope", "--quiet"])

        mock_html.assert_called_once()

    def test_output_writes_json_to_file(self, tmp_path):
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        outfile = tmp_path / "out.json"

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main([str(tmp_path), "--format", "json", "--output", str(outfile)])

        assert outfile.exists()
        data = json.loads(outfile.read_text())
        assert len(data) == 1
        assert data[0]["score"] == 85.0

    def test_shell_output_is_executable(self, tmp_path):
        import stat

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        outfile = tmp_path / "cleanup.sh"

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main([str(tmp_path), "--format", "shell", "--output", str(outfile)])

        mode = outfile.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_exclude_passed_to_scanner(self):
        """--exclude patterns are forwarded to run_pipeline."""
        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
        ):
            main(["--exclude", "**/thumbs/**", "--exclude", "*.tmp", "/dir"])

        exclude = mock_pipeline.call_args.kwargs.get("exclude")
        assert exclude == ["**/thumbs/**", "*.tmp"]

    def test_interactive_works_with_json_format(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_json"),
            patch("duplicates_detector.advisor.review_duplicates") as mock_review,
        ):
            main([str(tmp_path), "--format", "json", "-i"])

        mock_review.assert_called_once_with(
            pairs,
            dry_run=False,
            keep_strategy=None,
            deleter=ANY,
            action_log=ANY,
            ignore_list=ANY,
            verbose=False,
            sidecar_extensions=ANY,
            no_sidecars=ANY,
        )


# ---------------------------------------------------------------------------
# reference directory handling
# ---------------------------------------------------------------------------


class TestReferenceDirectories:
    def test_reference_dirs_combined_with_scan_dirs(self, tmp_path):
        ref_dir = tmp_path / "ref"
        ref_dir.mkdir()

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
        ):
            main([str(tmp_path), "--reference", str(ref_dir)])

        # Reference dirs are combined with scan dirs and passed to pipeline
        dirs = mock_pipeline.call_args.kwargs.get("directories")
        assert dirs is not None
        dir_strs = [str(d) for d in dirs]
        assert str(tmp_path) in dir_strs
        assert str(ref_dir) in dir_strs

    def test_reference_files_tagged_in_metadata(self, tmp_path):
        ref_dir = tmp_path / "ref"
        ref_dir.mkdir()
        regular_file = tmp_path / "a.mp4"
        ref_file = ref_dir / "b.mp4"
        regular_file.touch()
        ref_file.touch()

        files = [regular_file, ref_file]
        metadata = [
            _make_meta(str(regular_file)),
            _make_meta(str(ref_file)),
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--reference", str(ref_dir)])

        # Pipeline receives reference_dirs for tagging
        mock_pipeline.assert_called_once()
        ref_dirs = mock_pipeline.call_args.kwargs.get("reference_dirs")
        assert ref_dirs is not None
        assert any(ref_dir.resolve() == rd or ref_dir == rd for rd in ref_dirs)

    def test_symlinked_file_in_reference_dir_is_reference(self, tmp_path):
        """A symlink inside a reference dir pointing outside is still reference."""
        ref_dir = tmp_path / "ref"
        ref_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "movie.mp4"
        target.touch()
        symlink = ref_dir / "movie.mp4"
        symlink.symlink_to(target)

        regular_file = tmp_path / "other.mp4"
        regular_file.touch()

        files = [regular_file, symlink]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--reference", str(ref_dir)])

        # Pipeline receives reference_dirs for tagging
        mock_pipeline.assert_called_once()
        ref_dirs = mock_pipeline.call_args.kwargs.get("reference_dirs")
        assert ref_dirs is not None

    def test_reference_dir_not_found_exits_1(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            main([str(tmp_path), "--reference", "/nonexistent/ref/dir"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# --keep flag
# ---------------------------------------------------------------------------


class TestKeepParseArgs:
    def test_keep_default_none(self):
        args = parse_args(["/dir"])
        assert args.keep is None

    def test_keep_biggest(self):
        args = parse_args(["--keep", "biggest", "/dir"])
        assert args.keep == "biggest"

    def test_keep_all_strategies_accepted(self):
        for strategy in ["newest", "oldest", "biggest", "smallest", "longest", "highest-res"]:
            args = parse_args(["--keep", strategy, "/dir"])
            assert args.keep == strategy

    def test_keep_invalid_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(["--keep", "random", "/dir"])


class TestKeepMain:
    def _setup(self, tmp_path, a_size=1_000_000, b_size=2_000_000):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [
            _make_meta("a.mp4", file_size=a_size),
            _make_meta("b.mp4", file_size=b_size),
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_keep_passed_to_reporter(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--keep", "biggest"])

        assert mock_report.call_args.kwargs.get("keep_strategy") == "biggest"

    def test_keep_without_interactive_calls_auto_delete(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete") as mock_auto,
        ):
            main([str(tmp_path), "--keep", "biggest"])

        mock_auto.assert_called_once()
        assert mock_auto.call_args.kwargs["strategy"] == "biggest"
        assert mock_auto.call_args.kwargs["dry_run"] is False

    def test_keep_with_interactive_calls_review(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates") as mock_review,
        ):
            main([str(tmp_path), "--keep", "biggest", "-i"])

        mock_review.assert_called_once()
        assert mock_review.call_args.kwargs["keep_strategy"] == "biggest"

    def test_keep_with_dry_run(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete") as mock_auto,
        ):
            main([str(tmp_path), "--keep", "biggest", "--dry-run"])

        assert mock_auto.call_args.kwargs["dry_run"] is True

    def test_keep_without_pairs_no_auto_delete(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete") as mock_auto,
        ):
            main([str(tmp_path), "--keep", "biggest"])

        mock_auto.assert_not_called()

    def test_keep_with_json_format_no_auto_delete(self, tmp_path):
        """Machine-readable formats should not trigger auto-delete."""
        files, metadata, pairs = self._setup(tmp_path)

        for fmt in ["json", "csv", "shell"]:
            writer = f"duplicates_detector.cli.write_{fmt}"
            with (
                _mock_scan_iter_video(),
                patch("duplicates_detector.cli.find_video_files", return_value=files),
                patch(
                    "duplicates_detector.cli.run_pipeline",
                    new_callable=AsyncMock,
                    return_value=PipelineResult(pairs=pairs, files_scanned=2),
                ),
                patch(writer),
                patch("duplicates_detector.advisor.auto_delete") as mock_auto,
            ):
                main([str(tmp_path), "--keep", "biggest", "--format", fmt])

            mock_auto.assert_not_called()


# ---------------------------------------------------------------------------
# --group flag
# ---------------------------------------------------------------------------


class TestGroupParseArgs:
    def test_group_default_none(self):
        args = parse_args(["/dir"])
        assert args.group is None

    def test_group_flag_true(self):
        args = parse_args(["--group", "/dir"])
        assert args.group is True


class TestGroupMain:
    def _setup(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [
            _make_meta("a.mp4", file_size=2_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_group_calls_group_duplicates(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=[]) as mock_group,
            patch("duplicates_detector.cli.print_group_table"),
        ):
            main([str(tmp_path), "--group"])

        mock_group.assert_called_once_with(pairs)

    def test_group_table_calls_print_group_table(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=[MagicMock()]),
            patch("duplicates_detector.cli.print_group_table") as mock_report,
        ):
            main([str(tmp_path), "--group"])

        mock_report.assert_called_once()

    def test_group_json_calls_write_group_json(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=[MagicMock()]),
            patch("duplicates_detector.cli.write_group_json") as mock_json,
        ):
            main([str(tmp_path), "--group", "--format", "json"])

        mock_json.assert_called_once()

    def test_group_csv_calls_write_group_csv(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=[MagicMock()]),
            patch("duplicates_detector.cli.write_group_csv") as mock_csv,
        ):
            main([str(tmp_path), "--group", "--format", "csv"])

        mock_csv.assert_called_once()

    def test_group_shell_calls_write_group_shell(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=[MagicMock()]),
            patch("duplicates_detector.cli.write_group_shell") as mock_shell,
        ):
            main([str(tmp_path), "--group", "--format", "shell"])

        mock_shell.assert_called_once()

    def test_group_interactive_calls_review_groups(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)
        mock_groups = [MagicMock()]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=mock_groups),
            patch("duplicates_detector.cli.print_group_table"),
            patch("duplicates_detector.advisor.review_groups") as mock_review,
        ):
            main([str(tmp_path), "--group", "-i"])

        mock_review.assert_called_once_with(
            mock_groups,
            dry_run=False,
            keep_strategy=None,
            deleter=ANY,
            action_log=ANY,
            ignore_list=ANY,
            verbose=False,
            sidecar_extensions=ANY,
            no_sidecars=ANY,
        )

    def test_group_keep_calls_auto_delete_groups(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)
        mock_groups = [MagicMock()]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=mock_groups),
            patch("duplicates_detector.cli.print_group_table"),
            patch("duplicates_detector.advisor.auto_delete_groups") as mock_auto,
        ):
            main([str(tmp_path), "--group", "--keep", "biggest"])

        mock_auto.assert_called_once()
        assert mock_auto.call_args.kwargs["strategy"] == "biggest"

    def test_group_keep_interactive_calls_review_groups_with_strategy(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)
        mock_groups = [MagicMock()]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=mock_groups),
            patch("duplicates_detector.cli.print_group_table"),
            patch("duplicates_detector.advisor.review_groups") as mock_review,
        ):
            main([str(tmp_path), "--group", "--keep", "biggest", "-i"])

        mock_review.assert_called_once_with(
            mock_groups,
            dry_run=False,
            keep_strategy="biggest",
            deleter=ANY,
            action_log=ANY,
            ignore_list=ANY,
            verbose=False,
            sidecar_extensions=ANY,
            no_sidecars=ANY,
        )

    def test_group_keep_json_no_auto_delete(self, tmp_path):
        """Machine-readable formats should not trigger auto-delete in group mode."""
        files, metadata, pairs = self._setup(tmp_path)

        for fmt in ["json", "csv", "shell"]:
            writer = f"duplicates_detector.cli.write_group_{fmt}"
            with (
                _mock_scan_iter_video(),
                patch("duplicates_detector.cli.find_video_files", return_value=files),
                patch(
                    "duplicates_detector.cli.run_pipeline",
                    new_callable=AsyncMock,
                    return_value=PipelineResult(pairs=pairs, files_scanned=2),
                ),
                patch("duplicates_detector.cli.group_duplicates", return_value=[MagicMock()]),
                patch(writer),
                patch("duplicates_detector.advisor.auto_delete_groups") as mock_auto,
            ):
                main([str(tmp_path), "--group", "--keep", "biggest", "--format", fmt])

            mock_auto.assert_not_called()

    def test_without_group_flag_unchanged(self, tmp_path):
        """Without --group, standard pair pipeline is used."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates") as mock_group,
            patch("duplicates_detector.cli.print_table") as mock_table,
        ):
            main([str(tmp_path)])

        mock_group.assert_not_called()
        mock_table.assert_called_once()

    def test_group_dry_run_passed_through(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)
        mock_groups = [MagicMock()]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=mock_groups),
            patch("duplicates_detector.cli.print_group_table"),
            patch("duplicates_detector.advisor.auto_delete_groups") as mock_auto,
        ):
            main([str(tmp_path), "--group", "--keep", "biggest", "--dry-run"])

        assert mock_auto.call_args.kwargs["dry_run"] is True


# ---------------------------------------------------------------------------
# --content flag
# ---------------------------------------------------------------------------


class TestContentParseArgs:
    def test_default_none(self):
        args = parse_args(["/dir"])
        assert args.content is None

    def test_flag_true(self):
        args = parse_args(["--content", "/dir"])
        assert args.content is True


class TestContentMain:
    @staticmethod
    def _setup(tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 20.0, "duration": 20.0, "resolution": 10.0, "file_size": 10.0, "content": 25.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_content_triggers_hash_extraction(self, tmp_path):
        """--content flag enables content hashing in the pipeline."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--content"])

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["content"] is True

    def test_content_uses_content_comparators(self, tmp_path):
        """--content causes content comparators to be passed to the pipeline."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--content"])

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["comparators"] is not None
        names = [c.name for c in call_kwargs["comparators"]]
        assert "content" in names

    def test_no_content_uses_default_comparators(self, tmp_path):
        """Without --content, default comparators (None) are passed."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path)])

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs.get("comparators") is None

    def test_content_with_group(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=[MagicMock()]),
            patch("duplicates_detector.cli.print_group_table"),
        ):
            main([str(tmp_path), "--content", "--group"])

    def test_content_with_keep(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete") as mock_auto,
        ):
            main([str(tmp_path), "--content", "--keep", "biggest"])

        mock_auto.assert_called_once()


# ---------------------------------------------------------------------------
# --no-content-cache flag
# ---------------------------------------------------------------------------


class TestContentCacheParseArgs:
    def test_no_content_cache_default_none(self):
        args = parse_args(["/dir"])
        assert args.no_content_cache is None

    def test_no_content_cache_flag(self):
        args = parse_args(["--no-content-cache", "/dir"])
        assert args.no_content_cache is True

    def test_cache_flag_without_content_ignored(self, tmp_path):
        """--no-content-cache without --content runs normally (no error)."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--no-content-cache"])  # no error

    def test_content_cache_passed_to_extraction(self, tmp_path):
        """--content passes content=True to run_pipeline (caching handled by CacheDB)."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 20.0, "duration": 20.0, "resolution": 10.0, "file_size": 10.0, "content": 25.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--content", "--no-content-cache"])

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["content"] is True

    def test_content_cache_enabled_by_default(self, tmp_path):
        """--content uses CacheDB for caching (always enabled)."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 20.0, "duration": 20.0, "resolution": 10.0, "file_size": 10.0, "content": 25.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--content"])

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["content"] is True
        assert mock_pipeline.call_args.kwargs["cache"] is not None


# ---------------------------------------------------------------------------
# --no-metadata-cache flag
# ---------------------------------------------------------------------------


class TestMetadataCacheParseArgs:
    def test_no_metadata_cache_default_none(self):
        args = parse_args(["/dir"])
        assert args.no_metadata_cache is None

    def test_no_metadata_cache_flag(self):
        args = parse_args(["--no-metadata-cache", "/dir"])
        assert args.no_metadata_cache is True


class TestMetadataCacheMain:
    @staticmethod
    def _setup(tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 25.0, "resolution": 15.0, "file_size": 15.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_cache_passed_to_extract_all(self, tmp_path):
        """CacheDB instance is created and passed to run_pipeline as cache."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path)])

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["cache"] is not None  # CacheDB is always created

    def test_no_cache_flag_passes_none(self, tmp_path):
        """CacheDB is always created regardless of --no-metadata-cache (legacy flag)."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--no-metadata-cache"])

        call_kwargs = mock_pipeline.call_args.kwargs
        # CacheDB is always created; legacy --no-metadata-cache is a no-op for the pipeline
        assert call_kwargs["cache"] is not None

    def test_cache_with_content_mode(self, tmp_path):
        """Cache works with content mode (--content)."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--content"])

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["cache"] is not None
        assert call_kwargs["content"] is True

    def test_cache_with_verbose(self, tmp_path):
        """Verbose flag is passed through pipeline (run_pipeline doesn't take verbose)."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "-v"])

        mock_pipeline.assert_called_once()


# ---------------------------------------------------------------------------
# config flags in parse_args
# ---------------------------------------------------------------------------


class TestConfigParseArgs:
    def test_save_config_flag(self):
        args = parse_args(["--save-config", "/dir"])
        assert args.save_config is True

    def test_save_config_default(self):
        args = parse_args(["/dir"])
        assert args.save_config is False

    def test_no_config_flag(self):
        args = parse_args(["--no-config", "/dir"])
        assert args.no_config is True

    def test_no_config_default(self):
        args = parse_args(["/dir"])
        assert args.no_config is False

    def test_show_config_flag(self):
        args = parse_args(["--show-config", "/dir"])
        assert args.show_config is True

    def test_show_config_default(self):
        args = parse_args(["/dir"])
        assert args.show_config is False

    def test_configurable_fields_default_to_none(self):
        """Threshold, workers, format, and boolean flags default to None."""
        args = parse_args(["/dir"])
        assert args.threshold is None
        assert args.workers is None
        assert args.format is None
        assert args.no_recursive is None
        assert args.verbose is None
        assert args.content is None
        assert args.group is None
        assert args.no_content_cache is None
        assert args.no_metadata_cache is None


# ---------------------------------------------------------------------------
# config integration in main
# ---------------------------------------------------------------------------


class TestConfigMainIntegration:
    def test_save_config_exits_early(self, tmp_path):
        """--save-config writes config and returns without running pipeline."""
        with (
            patch("duplicates_detector.config.save_config") as mock_save,
            patch("duplicates_detector.config.get_config_path", return_value=tmp_path / "config.toml"),
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
        ):
            main(["--save-config", str(tmp_path)])

        mock_save.assert_called_once()
        mock_scan.assert_not_called()

    def test_show_config_exits_early(self, tmp_path):
        """--show-config prints config and returns without running pipeline."""
        with (
            patch("duplicates_detector.config.show_config") as mock_show,
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
        ):
            main(["--show-config", str(tmp_path)])

        mock_show.assert_called_once()
        mock_scan.assert_not_called()

    def test_no_config_skips_loading(self, tmp_path):
        """--no-config causes load_config to not be called."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.config.load_config") as mock_load,
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--no-config", str(tmp_path)])

        mock_load.assert_not_called()

    def test_config_values_applied(self, tmp_path):
        """Config file values are applied when CLI flags are not set."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.config.load_config", return_value={"threshold": 30}),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path)])

        assert (
            mock_pipeline.call_args.kwargs["threshold"] == 30.0 or mock_pipeline.call_args.kwargs.get("threshold") == 30
        )

    def test_cli_overrides_config(self, tmp_path):
        """CLI flags override config file values."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.config.load_config", return_value={"threshold": 30}),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--threshold", "80", str(tmp_path)])

        assert mock_pipeline.call_args.kwargs["threshold"] == 80


# ---------------------------------------------------------------------------
# --action / --move-to-dir
# ---------------------------------------------------------------------------


class TestActionParseArgs:
    def test_action_default_none(self):
        args = parse_args(["/path"])
        assert args.action is None

    def test_action_delete(self):
        args = parse_args(["--action", "delete", "/path"])
        assert args.action == "delete"

    def test_action_trash(self):
        args = parse_args(["--action", "trash", "/path"])
        assert args.action == "trash"

    def test_action_move_to(self):
        args = parse_args(["--action", "move-to", "/path"])
        assert args.action == "move-to"

    def test_action_invalid_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(["--action", "nuke", "/path"])

    def test_move_to_dir_default_none(self):
        args = parse_args(["/path"])
        assert args.move_to_dir is None

    def test_move_to_dir(self):
        args = parse_args(["--move-to-dir", "/tmp/staging", "/path"])
        assert args.move_to_dir == "/tmp/staging"


class TestActionValidation:
    def test_move_to_without_dir_errors(self, tmp_path):
        """--action move-to without --move-to-dir should exit with error."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["--action", "move-to", str(tmp_path)])
        assert exc_info.value.code == 1

    def test_move_to_dir_without_action_warns(self, tmp_path, capsys):
        """--move-to-dir without --action move-to should print a warning."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--move-to-dir", "/tmp/staging", str(tmp_path)])
        # Warning goes to stderr (Console(stderr=True))
        captured = capsys.readouterr()
        assert "ignored" in captured.err.lower()

    def test_trash_without_send2trash_errors(self, tmp_path):
        """--action trash without send2trash installed should exit with error."""
        import importlib

        with (
            patch.dict("sys.modules", {"send2trash": None}),
            patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError("No module named 'send2trash'"))
                    if name == "send2trash"
                    else importlib.__import__(name, *a, **kw)
                ),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["--action", "trash", str(tmp_path)])
        assert exc_info.value.code == 1

    def test_move_to_creates_directory(self, tmp_path):
        """--action move-to should create the staging directory."""
        staging = tmp_path / "new_staging_dir"
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--action", "move-to", "--move-to-dir", str(staging), str(tmp_path)])
        assert staging.is_dir()

    def test_move_to_invalid_dir_errors_gracefully(self, tmp_path):
        """--action move-to with uncreatable dir should exit 1, not traceback."""
        # Use an existing file as the staging dir path — mkdir will fail
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"x")

        with pytest.raises(SystemExit) as exc_info:
            main(["--action", "move-to", "--move-to-dir", str(blocker), str(tmp_path)])
        assert exc_info.value.code == 1

    def test_move_to_dry_run_does_not_create_directory(self, tmp_path):
        """--action move-to --dry-run should NOT create the staging directory."""
        staging = tmp_path / "new_staging_dir"
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--action", "move-to", "--move-to-dir", str(staging), "--dry-run", str(tmp_path)])
        assert not staging.exists()

    def test_trash_dry_run_without_send2trash_succeeds(self, tmp_path):
        """--action trash --dry-run should NOT require send2trash."""
        import importlib

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch.dict("sys.modules", {"send2trash": None}),
            patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError("No module named 'send2trash'"))
                    if name == "send2trash"
                    else importlib.__import__(name, *a, **kw)
                ),
            ),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            # Should not raise SystemExit
            main(["--action", "trash", "--dry-run", str(tmp_path)])

    def test_deleter_passed_to_auto_delete(self, tmp_path):
        """Verify that a deleter kwarg is passed to advisor functions."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pair = ScoredPair(
            file_a=metadata[0],
            file_b=metadata[1],
            total_score=80.0,
            breakdown={"filename": 30.0},
            detail={},
        )

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[pair], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete") as mock_ad,
        ):
            main(["--keep", "biggest", str(tmp_path)])
        assert "deleter" in mock_ad.call_args.kwargs


# ---------------------------------------------------------------------------
# --cache-dir flag
# ---------------------------------------------------------------------------


class TestCacheDirParseArgs:
    def test_cache_dir_default_none(self):
        args = parse_args(["/dir"])
        assert args.cache_dir is None

    def test_cache_dir_value(self):
        args = parse_args(["--cache-dir", "/tmp/my-cache", "/dir"])
        assert args.cache_dir == "/tmp/my-cache"


class TestCacheDirMain:
    @staticmethod
    def _setup(tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 25.0, "resolution": 15.0, "file_size": 15.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_cache_dir_passed_to_metadata_cache(self, tmp_path):
        """--cache-dir causes CacheDB to be created at the specified location."""
        files, metadata, pairs = self._setup(tmp_path)
        cache_dir = tmp_path / "custom-cache"

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--cache-dir", str(cache_dir), str(tmp_path)])

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["cache"] is not None

    def test_cache_dir_passed_to_content_hashes(self, tmp_path):
        """--cache-dir with --content passes CacheDB to pipeline."""
        files, metadata, pairs = self._setup(tmp_path)
        cache_dir = tmp_path / "custom-cache"

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--cache-dir", str(cache_dir), "--content", str(tmp_path)])

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["content"] is True
        assert mock_pipeline.call_args.kwargs["cache"] is not None

    def test_no_cache_dir_passes_none(self, tmp_path):
        """Without --cache-dir, CacheDB uses default XDG location."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path)])

        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs["cache"] is not None

    def test_cache_dir_with_no_metadata_cache(self, tmp_path):
        """--no-metadata-cache takes precedence: no MetadataCache created."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--cache-dir", "/tmp/cache", "--no-metadata-cache", str(tmp_path)])

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["cache"] is not None  # CacheDB always created


# ---------------------------------------------------------------------------
# --sort flag
# ---------------------------------------------------------------------------


class TestSortFlag:
    @staticmethod
    def _setup(tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_parse_sort_flag(self):
        args = parse_args(["--sort", "size", "/some/dir"])
        assert args.sort == "size"

    def test_parse_sort_default(self):
        args = parse_args(["/some/dir"])
        assert args.sort is None

    def test_sort_called_before_report(self, tmp_path):
        """--sort invokes sort_pairs before reporting."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.sorter.sort_pairs", return_value=pairs) as mock_sort,
        ):
            main([str(tmp_path), "--sort", "size"])

        mock_sort.assert_called_once_with(pairs, "size")


# ---------------------------------------------------------------------------
# --limit flag
# ---------------------------------------------------------------------------


class TestLimitFlag:
    @staticmethod
    def _setup(tmp_path, n=3):
        files = [tmp_path / f"{i}.mp4" for i in range(n)]
        metadata = [_make_meta(f"{i}.mp4") for i in range(n)]
        pairs = []
        for i in range(n - 1):
            pairs.append(
                ScoredPair(
                    file_a=metadata[i],
                    file_b=metadata[i + 1],
                    total_score=85.0 - i * 5,
                    breakdown={"filename": 30.0, "duration": 35.0},
                    detail={},
                )
            )
        return files, metadata, pairs

    def test_parse_limit_flag(self):
        args = parse_args(["--limit", "5", "/some/dir"])
        assert args.limit == 5

    def test_parse_limit_default(self):
        args = parse_args(["/some/dir"])
        assert args.limit is None

    def test_limit_zero_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["--limit", "0", str(tmp_path)])

    def test_limit_negative_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["--limit", "-1", str(tmp_path)])

    def test_limit_truncates_pairs(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path, n=5)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--limit", "2"])

        called_pairs = mock_report.call_args[0][0]
        assert len(called_pairs) == 2

    def test_limit_passes_max_rows_to_print_table(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path, n=3)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--limit", "1"])

        assert mock_report.call_args.kwargs.get("max_rows") == 1


# ---------------------------------------------------------------------------
# --quiet / --no-color flags
# ---------------------------------------------------------------------------


class TestQuietFlag:
    @staticmethod
    def _setup(tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_parse_quiet_flag(self):
        args = parse_args(["-q", "/some/dir"])
        assert args.quiet is True

    def test_parse_no_color_flag(self):
        args = parse_args(["--no-color", "/some/dir"])
        assert args.no_color is True

    def test_quiet_and_interactive_conflict(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["-q", "-i", str(tmp_path)])

    def test_quiet_runs_pipeline_without_verbose_output(self, tmp_path):
        """Quiet flag causes pipeline to run normally (scanning is handled inside pipeline)."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "-q"])

        # Pipeline is called even with quiet flag
        mock_pipeline.assert_called_once()

    def test_quiet_passes_quiet_to_extract_all(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "-q"])

        # Quiet flag is handled by pipeline internally
        mock_pipeline.assert_called_once()

    def test_quiet_passes_quiet_to_find_duplicates(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "-q"])

        # Quiet flag is handled by pipeline internally
        mock_pipeline.assert_called_once()

    def test_quiet_skips_summary(self, tmp_path):
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary") as mock_summary,
        ):
            main([str(tmp_path), "-q"])

        mock_summary.assert_not_called()


# ---------------------------------------------------------------------------
# Structured dry-run report
# ---------------------------------------------------------------------------


class TestDryRunReport:
    @staticmethod
    def _setup(tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 1000)
        metadata = [
            _make_meta("a.mp4", file_size=2_000_000),
            _make_meta("b.mp4", file_size=1_000_000),
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_dry_run_json_passes_summary(self, tmp_path):
        """--keep --dry-run --format json passes dry_run_summary to write_json."""
        files, metadata, pairs = self._setup(tmp_path)

        from duplicates_detector.advisor import DeletionSummary

        mock_summary = DeletionSummary(deleted=[Path("/videos/b.mp4")], skipped=0, errors=[], bytes_freed=1_000_000)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.advisor.auto_delete", return_value=mock_summary),
            patch("duplicates_detector.cli.write_json") as mock_json,
        ):
            main([str(tmp_path), "--keep", "biggest", "--dry-run", "--format", "json"])

        assert mock_json.call_args.kwargs.get("dry_run_summary") is not None

    def test_dry_run_shell_passes_summary(self, tmp_path):
        """--keep --dry-run --format shell passes dry_run_summary to write_shell."""
        files, metadata, pairs = self._setup(tmp_path)

        from duplicates_detector.advisor import DeletionSummary

        mock_summary = DeletionSummary(deleted=[Path("/videos/b.mp4")], skipped=0, errors=[], bytes_freed=1_000_000)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.advisor.auto_delete", return_value=mock_summary),
            patch("duplicates_detector.cli.write_shell") as mock_shell,
        ):
            main([str(tmp_path), "--keep", "biggest", "--dry-run", "--format", "shell"])

        assert mock_shell.call_args.kwargs.get("dry_run_summary") is not None

    def test_no_dry_run_no_summary_to_json(self, tmp_path):
        """Without --dry-run, no dry_run_summary passed to write_json."""
        files, metadata, pairs = self._setup(tmp_path)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_json") as mock_json,
        ):
            main([str(tmp_path), "--format", "json"])

        summary = mock_json.call_args.kwargs.get("dry_run_summary")
        assert summary is None

    def test_csv_gets_no_summary(self, tmp_path):
        """CSV format never gets dry_run_summary."""
        files, metadata, pairs = self._setup(tmp_path)

        from duplicates_detector.advisor import DeletionSummary

        mock_summary = DeletionSummary(deleted=[Path("/videos/b.mp4")], skipped=0, errors=[], bytes_freed=1_000_000)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.advisor.auto_delete", return_value=mock_summary),
            patch("duplicates_detector.cli.write_csv") as mock_csv,
        ):
            main([str(tmp_path), "--keep", "biggest", "--dry-run", "--format", "csv"])

        # write_csv should not receive dry_run_summary kwarg
        assert "dry_run_summary" not in (mock_csv.call_args.kwargs or {})


# ---------------------------------------------------------------------------
# _build_parser / --print-completion (tab completion)
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_argument_parser(self):
        import argparse

        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parse_args_uses_build_parser(self):
        args = parse_args(["/some/dir"])
        assert args.directories == ["/some/dir"]
        assert hasattr(args, "print_completion")


class TestPrintCompletion:
    def test_parse_bash(self):
        args = parse_args(["--print-completion", "bash"])
        assert args.print_completion == "bash"

    def test_parse_zsh(self):
        args = parse_args(["--print-completion", "zsh"])
        assert args.print_completion == "zsh"

    def test_parse_fish(self):
        args = parse_args(["--print-completion", "fish"])
        assert args.print_completion == "fish"

    def test_default_none(self):
        args = parse_args(["/some/dir"])
        assert args.print_completion is None

    def test_invalid_shell_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--print-completion", "powershell"])

    def test_main_prints_completion_and_returns(self):
        with (
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
        ):
            main(["--print-completion", "bash"])
        mock_scan.assert_not_called()

    def test_completion_output_contains_markers(self, capsys):
        main(["--print-completion", "bash"])
        captured = capsys.readouterr()
        # shtab generates bash completions that contain COMPREPLY or complete
        assert "duplicates" in captured.out.lower() or "compreply" in captured.out.lower()


# ---------------------------------------------------------------------------
# --action hardlink / symlink
# ---------------------------------------------------------------------------


class TestActionHardlinkSymlink:
    def test_parse_hardlink(self):
        args = parse_args(["--action", "hardlink", "/dir"])
        assert args.action == "hardlink"

    def test_parse_symlink(self):
        args = parse_args(["--action", "symlink", "/dir"])
        assert args.action == "symlink"

    def test_hardlink_requires_keep_or_interactive(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--action", "hardlink"])

    def test_symlink_requires_keep_or_interactive(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--action", "symlink"])

    def test_hardlink_with_keep_is_ok(self, tmp_path):
        """--action hardlink --keep biggest should not error on validation."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 10)
        metadata = [
            VideoMetadata(path=f, filename=f.stem, duration=120.0, width=1920, height=1080, file_size=10) for f in files
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0], file_b=metadata[1], total_score=80.0, breakdown={"filename": 30.0}, detail={}
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete"),
        ):
            main([str(tmp_path), "--action", "hardlink", "--keep", "biggest"])

    def test_hardlink_with_interactive_is_ok(self, tmp_path):
        """--action hardlink -i should not error on validation."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 10)
        metadata = [
            VideoMetadata(path=f, filename=f.stem, duration=120.0, width=1920, height=1080, file_size=10) for f in files
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0], file_b=metadata[1], total_score=80.0, breakdown={"filename": 30.0}, detail={}
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates"),
        ):
            main([str(tmp_path), "--action", "hardlink", "-i"])


# ---------------------------------------------------------------------------
# --action reflink
# ---------------------------------------------------------------------------


class TestActionReflink:
    def test_parse_reflink(self):
        args = parse_args(["--action", "reflink", "/dir"])
        assert args.action == "reflink"

    def test_reflink_requires_keep_or_interactive(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--action", "reflink"])

    def test_reflink_with_keep_is_ok(self, tmp_path):
        """--action reflink --keep biggest should not error on validation."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 10)
        metadata = [
            VideoMetadata(path=f, filename=f.stem, duration=120.0, width=1920, height=1080, file_size=10) for f in files
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0], file_b=metadata[1], total_score=80.0, breakdown={"filename": 30.0}, detail={}
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.auto_delete"),
        ):
            main([str(tmp_path), "--action", "reflink", "--keep", "biggest"])

    def test_reflink_with_interactive_is_ok(self, tmp_path):
        """--action reflink -i should not error on validation."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 10)
        metadata = [
            VideoMetadata(path=f, filename=f.stem, duration=120.0, width=1920, height=1080, file_size=10) for f in files
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0], file_b=metadata[1], total_score=80.0, breakdown={"filename": 30.0}, detail={}
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.advisor.review_duplicates"),
        ):
            main([str(tmp_path), "--action", "reflink", "-i"])


# ---------------------------------------------------------------------------
# --weights
# ---------------------------------------------------------------------------


class TestWeightsFlag:
    def test_parse_weights(self):
        args = parse_args(["--weights", "filename=50,duration=30,resolution=10,filesize=10", "/dir"])
        assert args.weights == "filename=50,duration=30,resolution=10,filesize=10"

    def test_parse_weights_default_none(self):
        args = parse_args(["/dir"])
        assert args.weights is None

    def test_weights_sum_not_100_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--weights", "filename=50,duration=30,resolution=10,filesize=5"])

    def test_weights_content_without_flag_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--weights", "filename=20,duration=20,resolution=10,filesize=10,content=40"])

    def test_weights_missing_key_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--weights", "filename=50,duration=50"])

    def test_weights_invalid_format_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--weights", "filename:50"])

    def test_valid_weights_pipeline_runs(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 10)
        metadata = [
            VideoMetadata(path=f, filename=f.stem, duration=120.0, width=1920, height=1080, file_size=10) for f in files
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--weights", "filename=50,duration=30,resolution=10,filesize=10"])
        # Verify custom comparators were passed to the pipeline
        assert mock_pipeline.call_args.kwargs.get("comparators") is not None


# ---------------------------------------------------------------------------
# --clear-ignored
# ---------------------------------------------------------------------------


class TestClearIgnored:
    def test_clear_ignored_exits_early(self, tmp_path):
        """--clear-ignored clears the ignore list, saves, and exits without scanning."""
        with (
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
            patch("duplicates_detector.ignorelist.IgnoreList.clear") as mock_clear,
            patch("duplicates_detector.ignorelist.IgnoreList.save") as mock_save,
            patch("duplicates_detector.ignorelist.IgnoreList._load"),
            patch("duplicates_detector.ignorelist.IgnoreList.__len__", return_value=3),
        ):
            main(["--clear-ignored", str(tmp_path)])

        mock_scan.assert_not_called()
        mock_clear.assert_called_once()
        mock_save.assert_called_once()

    def test_clear_ignored_with_custom_file(self, tmp_path):
        ignore_file = tmp_path / "my-ignored.json"
        with (
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
            patch("duplicates_detector.ignorelist.IgnoreList.clear") as mock_clear,
            patch("duplicates_detector.ignorelist.IgnoreList.save") as mock_save,
            patch("duplicates_detector.ignorelist.IgnoreList._load"),
            patch("duplicates_detector.ignorelist.IgnoreList.__len__", return_value=0),
        ):
            main(["--clear-ignored", "--ignore-file", str(ignore_file), str(tmp_path)])

        mock_scan.assert_not_called()
        mock_clear.assert_called_once()
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# --generate-undo
# ---------------------------------------------------------------------------


class TestGenerateUndo:
    def test_generate_undo_flag_parses(self):
        args = parse_args(["--generate-undo", "actions.jsonl"])
        assert args.generate_undo == "actions.jsonl"

    def test_generate_undo_early_exit(self, tmp_path):
        """--generate-undo calls run_generate_undo and exits without scanning."""
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        with (
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
            patch("duplicates_detector.undoscript.run_generate_undo") as mock_undo,
        ):
            main(["--generate-undo", str(log)])

        mock_scan.assert_not_called()
        mock_undo.assert_called_once()

    def test_generate_undo_with_output(self, tmp_path):
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        with patch("duplicates_detector.undoscript.run_generate_undo") as mock_undo:
            main(["--generate-undo", str(log), "--output", "undo.sh"])

        assert mock_undo.call_args.kwargs["output_file"] == "undo.sh"

    def test_generate_undo_with_directories_errors(self, tmp_path):
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        with pytest.raises(SystemExit) as exc_info:
            main(["--generate-undo", str(log), str(tmp_path)])
        assert exc_info.value.code == 1

    def test_generate_undo_with_keep_errors(self, tmp_path):
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        with pytest.raises(SystemExit) as exc_info:
            main(["--generate-undo", str(log), "--keep", "biggest"])
        assert exc_info.value.code == 1

    def test_generate_undo_with_content_errors(self, tmp_path):
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        with pytest.raises(SystemExit) as exc_info:
            main(["--generate-undo", str(log), "--content"])
        assert exc_info.value.code == 1

    def test_generate_undo_with_quiet_allowed(self, tmp_path):
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        with patch("duplicates_detector.undoscript.run_generate_undo") as mock_undo:
            main(["--generate-undo", str(log), "-q"])
        mock_undo.assert_called_once()
        assert mock_undo.call_args.kwargs["quiet"] is True


# ---------------------------------------------------------------------------
# Invalid resolution / bitrate runtime parse failures
# ---------------------------------------------------------------------------


class TestInvalidResolutionBitrateRuntime:
    def test_invalid_min_resolution_exits_1(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main([str(tmp_path), "--min-resolution", "notaresolution"])
            assert exc_info.value.code == 1

    def test_invalid_max_resolution_exits_1(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main([str(tmp_path), "--max-resolution", "abc"])
            assert exc_info.value.code == 1

    def test_invalid_min_bitrate_exits_1(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main([str(tmp_path), "--min-bitrate", "notabitrate"])
            assert exc_info.value.code == 1

    def test_invalid_max_bitrate_exits_1(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main([str(tmp_path), "--max-bitrate", "xyz"])
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Dry-run logging with machine-readable formats
# ---------------------------------------------------------------------------


class TestDryRunLogging:
    def _setup(self, tmp_path, a_size=1_000_000, b_size=2_000_000):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [
            _make_meta("a.mp4", file_size=a_size),
            _make_meta("b.mp4", file_size=b_size),
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0},
                detail={},
            )
        ]
        return files, metadata, pairs

    def test_json_dry_run_keep_opens_action_log(self, tmp_path):
        """--keep --dry-run --format json --log FILE should open and write to action log."""
        files, metadata, pairs = self._setup(tmp_path)
        log_file = tmp_path / "actions.jsonl"

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_json"),
            patch("duplicates_detector.advisor.auto_delete") as mock_auto,
            patch("duplicates_detector.actionlog.ActionLog.open") as mock_open,
            patch("duplicates_detector.actionlog.ActionLog.close") as mock_close,
        ):
            main(
                [
                    str(tmp_path),
                    "--keep",
                    "biggest",
                    "--dry-run",
                    "--format",
                    "json",
                    "--log",
                    str(log_file),
                ]
            )

        mock_open.assert_called_once()
        mock_auto.assert_called_once()
        # Verify action_log was passed to auto_delete
        assert mock_auto.call_args.kwargs.get("action_log") is not None
        mock_close.assert_called_once()

    def test_shell_dry_run_keep_opens_action_log(self, tmp_path):
        """--keep --dry-run --format shell --log FILE should open and write to action log."""
        files, metadata, pairs = self._setup(tmp_path)
        log_file = tmp_path / "actions.jsonl"

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_shell"),
            patch("duplicates_detector.advisor.auto_delete") as mock_auto,
            patch("duplicates_detector.actionlog.ActionLog.open") as mock_open,
            patch("duplicates_detector.actionlog.ActionLog.close") as mock_close,
        ):
            main(
                [
                    str(tmp_path),
                    "--keep",
                    "biggest",
                    "--dry-run",
                    "--format",
                    "shell",
                    "--log",
                    str(log_file),
                ]
            )

        mock_open.assert_called_once()
        mock_auto.assert_called_once()
        # Verify action_log was passed to auto_delete
        assert mock_auto.call_args.kwargs.get("action_log") is not None
        mock_close.assert_called_once()

    def test_group_json_dry_run_keep_opens_action_log(self, tmp_path):
        """Group mode: --keep --dry-run --format json --log FILE should log."""
        files, metadata, pairs = self._setup(tmp_path)
        log_file = tmp_path / "actions.jsonl"
        mock_groups = [MagicMock()]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.group_duplicates", return_value=mock_groups),
            patch("duplicates_detector.cli.write_group_json"),
            patch("duplicates_detector.advisor.auto_delete_groups") as mock_auto,
            patch("duplicates_detector.actionlog.ActionLog.open") as mock_open,
            patch("duplicates_detector.actionlog.ActionLog.close") as mock_close,
        ):
            main(
                [
                    str(tmp_path),
                    "--group",
                    "--keep",
                    "biggest",
                    "--dry-run",
                    "--format",
                    "json",
                    "--log",
                    str(log_file),
                ]
            )

        mock_open.assert_called_once()
        mock_auto.assert_called_once()
        # Verify action_log was passed to auto_delete_groups
        assert mock_auto.call_args.kwargs.get("action_log") is not None
        mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# --rotation-invariant
# ---------------------------------------------------------------------------


class TestRotationInvariantFlag:
    def test_default_none(self):
        args = parse_args(["/dir"])
        assert args.rotation_invariant is None

    def test_explicit_flag(self):
        args = parse_args(["--rotation-invariant", "/dir"])
        assert args.rotation_invariant is True

    def test_without_content_no_error(self, tmp_path):
        """--rotation-invariant without --content is silently ignored."""
        files = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
        metadata = [
            VideoMetadata(
                path=files[0],
                filename="a.jpg",
                duration=None,
                width=100,
                height=100,
                file_size=1000,
                mtime=1.0,
            ),
            VideoMetadata(
                path=files[1],
                filename="b.jpg",
                duration=None,
                width=100,
                height=100,
                file_size=1000,
                mtime=1.0,
            ),
        ]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 40.0, "resolution": 25.0, "file_size": 20.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--rotation-invariant", "--mode", "image", str(tmp_path)])


# ---------------------------------------------------------------------------
# --json-envelope
# ---------------------------------------------------------------------------


class TestJsonEnvelopeFlag:
    def test_json_envelope_default_none(self):
        args = parse_args(["/dir"])
        assert args.json_envelope is None

    def test_json_envelope_flag(self):
        args = parse_args(["--json-envelope", "/dir"])
        assert args.json_envelope is True

    def test_json_envelope_output_structure(self, tmp_path):
        """--json-envelope wraps JSON output with version, generated_at, args, stats."""
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--output",
                    str(out_file),
                ]
            )

        data = json.loads(out_file.read_text())
        assert "version" in data
        assert "generated_at" in data
        assert "args" in data
        assert "stats" in data
        assert "pairs" in data
        assert isinstance(data["pairs"], list)
        assert len(data["pairs"]) == 1

    def test_json_envelope_without_json_format_ignored(self, tmp_path):
        """--json-envelope without --format json doesn't affect table output."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_table,
        ):
            main([str(tmp_path), "--json-envelope"])

        mock_table.assert_called_once()

    def test_json_envelope_args_stable_keys(self, tmp_path):
        """Envelope args contains the full stable key set (always present, null when unset)."""
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--output",
                    str(out_file),
                ]
            )

        data = json.loads(out_file.read_text())
        expected_keys = {
            "directories",
            "threshold",
            "content",
            "content_method",
            "weights",
            "keep",
            "action",
            "group",
            "sort",
            "limit",
            "min_score",
            "exclude",
            "reference",
            "min_size",
            "max_size",
            "min_duration",
            "max_duration",
            "min_resolution",
            "max_resolution",
            "min_bitrate",
            "max_bitrate",
            "codec",
            "mode",
            "embed_thumbnails",
            "thumbnail_size",
        }
        assert set(data["args"].keys()) == expected_keys

    def test_json_envelope_nulls_for_unset_filters(self, tmp_path):
        """Unset filter/optional args are null (not omitted) in envelope."""
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--output",
                    str(out_file),
                ]
            )

        data = json.loads(out_file.read_text())
        args_obj = data["args"]
        # These should be null when not set
        for key in [
            "weights",
            "keep",
            "exclude",
            "reference",
            "min_size",
            "max_size",
            "min_duration",
            "max_duration",
            "min_resolution",
            "max_resolution",
            "min_bitrate",
            "max_bitrate",
            "codec",
            "limit",
        ]:
            assert args_obj[key] is None, f"Expected {key} to be null, got {args_obj[key]}"

    def test_json_envelope_weights_structured(self, tmp_path):
        """Envelope args.weights is a structured dict, not a raw CLI string."""
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--weights",
                    "filename=50,duration=30,resolution=10,file_size=10",
                    "--output",
                    str(out_file),
                ]
            )

        data = json.loads(out_file.read_text())
        weights = data["args"]["weights"]
        assert isinstance(weights, dict)
        assert weights == {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}

    def test_json_envelope_weights_null_when_unset(self, tmp_path):
        """Envelope args.weights is null when no custom weights are set."""
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--output",
                    str(out_file),
                ]
            )

        data = json.loads(out_file.read_text())
        assert data["args"]["weights"] is None


# ---------------------------------------------------------------------------
# --mode flag (image deduplication mode)
# ---------------------------------------------------------------------------


def _make_image_meta(path: str, file_size: int = 1_000_000) -> VideoMetadata:
    return VideoMetadata(
        path=Path(path),
        filename=Path(path).stem,
        duration=None,
        width=1920,
        height=1080,
        file_size=file_size,
        mtime=1_700_000_000.0,
    )


class TestModeFlag:
    def test_mode_parses(self):
        args = parse_args([".", "--mode", "image"])
        assert args.mode == "image"

    def test_mode_default_none(self):
        args = parse_args(["."])
        assert args.mode is None

    def test_mode_document_parses(self):
        """--mode document is accepted as a valid choice."""
        args = parse_args([".", "--mode", "document"])
        assert args.mode == "document"

    def test_image_mode_longest_error(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "image", "--keep", "longest"])

    def test_image_mode_duration_error(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "image", "--min-duration", "10"])

    def test_image_mode_bitrate_error(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "image", "--min-bitrate", "5Mbps"])

    def test_image_mode_weights_validation(self, tmp_path):
        """Image mode should reject weights with 'duration' key."""
        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "image",
                    "--weights",
                    "filename=35,duration=35,resolution=15,filesize=15",
                ]
            )

    def test_image_mode_valid_weights(self, tmp_path):
        """Image mode should accept weights with 'exif' key."""
        files = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
        for f in files:
            f.touch()
        metadata = [_make_image_meta("a.jpg"), _make_image_meta("b.jpg")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "image",
                    "--weights",
                    "filename=25,resolution=20,filesize=15,exif=40",
                ]
            )
        # Should not raise

    def test_exif_rejected_in_video_mode(self, tmp_path):
        """Video mode should reject weights with 'exif' key."""
        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--weights",
                    "filename=20,duration=20,resolution=10,filesize=10,exif=40",
                ]
            )

    def test_image_mode_missing_exif_key_errors(self, tmp_path):
        """Image mode weights without 'exif' key should error (missing required key)."""
        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "image",
                    "--weights",
                    "filename=40,resolution=30,filesize=30",
                ]
            )


# ---------------------------------------------------------------------------
# --min-score flag
# ---------------------------------------------------------------------------


class TestMinScore:
    def test_min_score_flag_parses(self):
        args = parse_args(["--min-score", "80", "/dir"])
        assert args.min_score == 80

    @pytest.mark.parametrize("value", ["-1", "101", "150", "-50"])
    def test_min_score_rejects_out_of_range(self, value):
        with pytest.raises(SystemExit):
            main(["--min-score", value, "/dir"])

    def test_min_score_default_none(self):
        args = parse_args(["/dir"])
        assert args.min_score is None

    def test_min_score_filters_pairs(self, tmp_path):
        """--min-score 60 keeps only pairs at or above 60."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4"), _make_meta("c.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=90.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 15.0, "file_size": 10.0},
                detail={},
            ),
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[2],
                total_score=70.0,
                breakdown={"filename": 20.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            ),
            ScoredPair(
                file_a=metadata[1],
                file_b=metadata[2],
                total_score=50.0,
                breakdown={"filename": 10.0, "duration": 25.0, "resolution": 10.0, "file_size": 5.0},
                detail={},
            ),
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--min-score", "60"])

        reported_pairs = mock_report.call_args[0][0]
        assert len(reported_pairs) == 2
        assert all(p.total_score >= 60 for p in reported_pairs)

    def test_min_score_with_limit(self, tmp_path):
        """--min-score filters first, then --limit caps output."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4"), _make_meta("c.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=90.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 15.0, "file_size": 10.0},
                detail={},
            ),
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[2],
                total_score=70.0,
                breakdown={"filename": 20.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            ),
            ScoredPair(
                file_a=metadata[1],
                file_b=metadata[2],
                total_score=50.0,
                breakdown={"filename": 10.0, "duration": 25.0, "resolution": 10.0, "file_size": 5.0},
                detail={},
            ),
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--min-score", "60", "--limit", "1"])

        reported_pairs = mock_report.call_args[0][0]
        assert len(reported_pairs) == 1
        assert reported_pairs[0].total_score == 90.0

    def test_min_score_with_group(self, tmp_path):
        """Pairs below --min-score are excluded before grouping."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4"), _make_meta("c.mp4")]
        # Only the a-b pair is above 60; a-c is below.
        # Without min-score, grouping would transitively link a-b-c.
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=80.0,
                breakdown={"filename": 30.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            ),
            ScoredPair(
                file_a=metadata[1],
                file_b=metadata[2],
                total_score=55.0,
                breakdown={"filename": 15.0, "duration": 25.0, "resolution": 10.0, "file_size": 5.0},
                detail={},
            ),
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_group_table") as mock_group_report,
        ):
            main([str(tmp_path), "--min-score", "60", "--group"])

        groups = mock_group_report.call_args[0][0]
        # Only one pair (80.0) survives, so only one group with 2 members
        assert len(groups) == 1
        assert len(groups[0].members) == 2

    def test_min_score_zero_results(self, tmp_path):
        """--min-score 100 with no perfect pairs → empty output, clean exit."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--min-score", "100"])

        reported_pairs = mock_report.call_args[0][0]
        assert len(reported_pairs) == 0

    def test_min_score_below_threshold_no_effect(self, tmp_path):
        """--threshold 70 --min-score 50 → all pairs pass since scorer already filtered."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=75.0,
                breakdown={"filename": 25.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_report,
        ):
            main([str(tmp_path), "--threshold", "70", "--min-score", "50"])

        reported_pairs = mock_report.call_args[0][0]
        assert len(reported_pairs) == 1


# ---------------------------------------------------------------------------
# --profile / --save-profile
# ---------------------------------------------------------------------------


class TestProfileParseArgs:
    def test_profile_default_none(self):
        args = parse_args(["/dir"])
        assert args.profile is None

    def test_profile_flag(self):
        args = parse_args(["--profile", "photos", "/dir"])
        assert args.profile == "photos"

    def test_save_profile_default_none(self):
        args = parse_args(["/dir"])
        assert args.save_profile is None

    def test_save_profile_flag(self):
        args = parse_args(["--save-profile", "camera-roll", "/dir"])
        assert args.save_profile == "camera-roll"


class TestProfileMainIntegration:
    def test_save_profile_exits_early(self, tmp_path, monkeypatch):
        """--save-profile writes profile and returns without running pipeline."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch("duplicates_detector.cli.find_video_files") as mock_scan:
            main(["--save-profile", "test-prof", str(tmp_path)])

        mock_scan.assert_not_called()
        profile_path = tmp_path / "duplicates-detector" / "profiles" / "test-prof.toml"
        assert profile_path.exists()

    def test_save_profile_image_mode_drops_audio(self, tmp_path, monkeypatch):
        """--save-profile --mode image should not persist audio settings."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        main(
            [
                "--save-profile",
                "img-prof",
                "--mode",
                "image",
                "--content",
                str(tmp_path),
            ]
        )
        profile_path = tmp_path / "duplicates-detector" / "profiles" / "img-prof.toml"
        content = profile_path.read_text()
        assert "audio" not in content or "audio = false" in content

    def test_save_profile_invalid_name(self, tmp_path):
        """--save-profile with invalid name exits with error."""
        with pytest.raises(SystemExit):
            main(["--save-profile", "../bad", str(tmp_path)])

    def test_save_profile_empty_name(self, tmp_path):
        """--save-profile '' exits with error instead of falling through to pipeline."""
        with pytest.raises(SystemExit):
            main(["--save-profile", "", str(tmp_path)])

    def test_profile_empty_name(self, tmp_path):
        """--profile '' exits with error instead of silently skipping."""
        with pytest.raises(SystemExit):
            main(["--profile", "", str(tmp_path)])

    def test_profile_merges_between_config_and_cli(self, tmp_path, monkeypatch):
        """--profile values apply between global config and CLI flags."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        # Create a profile with threshold=80
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text("threshold = 80\n")

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.config.load_config", return_value={"threshold": 30}),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--profile", "test", str(tmp_path)])

        # Profile (80) overrides config (30)
        assert mock_pipeline.call_args.kwargs["threshold"] == 80

    def test_cli_overrides_profile(self, tmp_path, monkeypatch):
        """CLI flags override profile values."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text("threshold = 80\n")

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--profile", "test", "--threshold", "95", str(tmp_path)])

        assert mock_pipeline.call_args.kwargs["threshold"] == 95

    def test_no_config_with_profile(self, tmp_path, monkeypatch):
        """--no-config skips global config but still honors --profile."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text("threshold = 70\n")

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.config.load_config") as mock_load,
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--no-config", "--profile", "test", str(tmp_path)])

        mock_load.assert_not_called()
        assert mock_pipeline.call_args.kwargs["threshold"] == 70

    def test_show_config_with_profile(self, tmp_path, monkeypatch):
        """--show-config includes profile-influenced effective config."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text('mode = "image"\n')

        with (
            patch("duplicates_detector.config.show_config") as mock_show,
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
        ):
            main(["--show-config", "--profile", "test", str(tmp_path)])

        mock_show.assert_called_once()
        mock_scan.assert_not_called()
        # The effective config should include mode=image from profile
        shown = mock_show.call_args[0][0]
        assert shown.get("mode") == "image"

    def test_missing_profile_error(self, tmp_path, monkeypatch):
        """--profile with nonexistent profile exits with error."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with pytest.raises(SystemExit):
            main(["--profile", "nonexistent", str(tmp_path)])

    def test_exclude_additive_across_layers(self, tmp_path, monkeypatch):
        """Exclude patterns are additive across config, profile, and CLI."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text('exclude = ["*.bak"]\n')

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.config.load_config", return_value={"exclude": ["*.log"]}),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--profile", "test", "--exclude", "*.tmp", str(tmp_path)])

        # exclude should be config(*.log) + profile(*.bak) + CLI(*.tmp)
        assert mock_pipeline.call_args is not None
        exclude_arg = cast(list[str], mock_pipeline.call_args.kwargs["exclude"])
        assert "*.log" in exclude_arg
        assert "*.bak" in exclude_arg
        assert "*.tmp" in exclude_arg


# ---------------------------------------------------------------------------
# --mode auto (mixed media deduplication)
# ---------------------------------------------------------------------------


class TestAutoMode:
    def test_mode_auto_parses(self):
        args = parse_args([".", "--mode", "auto"])
        assert args.mode == "auto"

    def test_auto_mode_rejects_longest(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "auto", "--keep", "longest"])

    def test_auto_mode_rejects_weights(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "auto", "--weights", "filename=50,duration=30,resolution=10,filesize=10"])

    def test_auto_mode_rejects_extensions(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "auto", "--extensions", "mp4,jpg"])

    def test_auto_mode_allows_duration_filters(self, tmp_path):
        """--min-duration should not error in auto mode (images pass through)."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--min-duration", "10"])

    def test_auto_mode_allows_bitrate_filters(self, tmp_path):
        """--min-bitrate should not error in auto mode."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--min-bitrate", "5Mbps"])

    def test_auto_mode_runs_both_pipelines(self, tmp_path):
        """Auto mode calls run_pipeline for each type with sufficient files."""
        video_path = tmp_path / "a.mp4"
        image_path = tmp_path / "b.jpg"
        video_path.touch()
        image_path.touch()
        media_files = [
            MediaFile(path=video_path, media_type="video"),
            MediaFile(path=image_path, media_type="image"),
        ]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto"])

        # Auto mode calls run_pipeline for each type (but needs >=2 files per type)
        # With only 1 video and 1 image, neither sub-pipeline has enough files
        # So run_pipeline may not be called at all

    def test_auto_mode_only_videos(self, tmp_path):
        """Both sub-pipelines always launch; the empty one completes instantly."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto"])

        # Both sub-pipelines always launch (video + image); the image one completes instantly
        assert mock_pipeline.call_count == 2
        modes = [c.kwargs.get("mode") for c in mock_pipeline.call_args_list]
        assert "video" in modes
        assert "image" in modes

    def test_auto_mode_only_images(self, tmp_path):
        """Both sub-pipelines always launch; both modes are present."""
        media_files = [
            MediaFile(path=tmp_path / "a.jpg", media_type="image"),
            MediaFile(path=tmp_path / "b.jpg", media_type="image"),
        ]
        for mf in media_files:
            mf.path.touch()

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto"])

        # Both sub-pipelines always launch; video one completes instantly
        assert mock_pipeline.call_count == 2
        modes = [c.kwargs.get("mode") for c in mock_pipeline.call_args_list]
        assert "image" in modes
        assert "video" in modes

    def test_auto_mode_table_title(self, tmp_path):
        """Reporter should get 'Potential Duplicate Media' title."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pair = ScoredPair(
            file_a=metadata[0],
            file_b=metadata[1],
            total_score=85.0,
            breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
            detail={},
        )

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[pair], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table") as mock_table,
        ):
            main([str(tmp_path), "--mode", "auto"])

        mock_table.assert_called_once()
        assert mock_table.call_args.kwargs.get("title") == "Potential Duplicate Media"

    def test_auto_mode_json_envelope(self, tmp_path):
        """JSON envelope should contain mode: auto."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()
        pair = ScoredPair(
            file_a=_make_meta("a.mp4"),
            file_b=_make_meta("b.mp4"),
            total_score=85.0,
            breakdown={},
            detail={},
        )

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[pair], files_scanned=2),
            ),
            patch("duplicates_detector.cli.write_json") as mock_json,
        ):
            main([str(tmp_path), "--mode", "auto", "--format", "json", "--json-envelope"])

        mock_json.assert_called_once()
        envelope = mock_json.call_args.kwargs.get("envelope")
        assert envelope is not None
        assert envelope["args"]["mode"] == "auto"

    def test_auto_mode_content_both_types(self, tmp_path):
        """With --content in auto mode, both sub-pipelines are called with content=True."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--content"])

        # Both sub-pipelines always launch with content=True
        assert mock_pipeline.call_count == 2
        for call_obj in mock_pipeline.call_args_list:
            assert call_obj.kwargs["content"] is True

    def test_auto_mode_profile(self, tmp_path, monkeypatch):
        """Profile with mode=auto drives auto-mode run."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "mixed.toml").write_text('mode = "auto"\n')

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--profile", "mixed", str(tmp_path)])

        # Auto mode calls run_pipeline twice (video + image sub-pipelines)
        assert mock_pipeline.call_count == 2

    def test_save_profile_auto_mode(self, tmp_path, monkeypatch):
        """--save-profile preserves mode=auto."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)

        main(["--save-profile", "auto_test", "--mode", "auto", str(tmp_path)])

        profile_file = profile_dir / "auto_test.toml"
        assert profile_file.exists()
        content = profile_file.read_text()
        assert 'mode = "auto"' in content

    def test_show_config_auto_mode(self, tmp_path, capsys):
        """--show-config with auto mode works."""
        main(["--show-config", "--mode", "auto", str(tmp_path)])
        # Should not raise


# ---------------------------------------------------------------------------
# --content-method flag
# ---------------------------------------------------------------------------


def _import_blocker(blocked_name: str):
    """Create a side_effect for builtins.__import__ that blocks one module."""
    _real_import = __import__

    def _blocker(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == blocked_name or name.startswith(blocked_name + "."):
            raise ImportError(f"No module named '{name}'")
        return _real_import(name, *args, **kwargs)

    return _blocker


class TestContentMethod:
    """Tests for --content-method flag."""

    def test_flag_default_none(self):
        args = parse_args(["/dir"])
        assert args.content_method is None

    def test_flag_phash(self):
        args = parse_args(["--content-method", "phash", "/dir"])
        assert args.content_method == "phash"

    def test_flag_ssim(self):
        args = parse_args(["--content-method", "ssim", "/dir"])
        assert args.content_method == "ssim"

    def test_flag_clip(self):
        args = parse_args(["--content-method", "clip", "/dir"])
        assert args.content_method == "clip"

    def test_invalid_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--content-method", "invalid", "/dir"])

    def test_clip_audio_mode_errors(self, tmp_path):
        """--content --content-method clip --mode audio exits with error."""
        with pytest.raises(SystemExit):
            main(["--content", "--content-method", "clip", "--mode", "audio", str(tmp_path), "--no-config"])

    def test_clip_without_onnxruntime_errors(self, tmp_path):
        """--content --content-method clip without onnxruntime exits with error."""
        import sys as _sys

        saved = _sys.modules.get("onnxruntime")
        _sys.modules["onnxruntime"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(SystemExit):
                main(["--content", "--content-method", "clip", str(tmp_path), "--no-config"])
        finally:
            if saved is not None:
                _sys.modules["onnxruntime"] = saved
            elif "onnxruntime" in _sys.modules:
                del _sys.modules["onnxruntime"]

    def test_without_content_ignored(self, tmp_path):
        """--content-method without --content is silently ignored (no error)."""
        # Create dummy files
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()
        # Should not raise — flag is simply unused without --content
        with patch("duplicates_detector.cli.find_video_files", return_value=[tmp_path / "a.mp4", tmp_path / "b.mp4"]):
            with patch("duplicates_detector.cli.run_pipeline", new_callable=AsyncMock) as mock_pipeline:
                mock_pipeline.return_value = PipelineResult(pairs=[])
                # Pipeline exits early with "not enough files" — that's fine
                main(["--content-method", "ssim", str(tmp_path), "--no-config"])

    def test_ssim_without_scikit_image_errors(self, tmp_path):
        """--content --content-method ssim without scikit-image exits with error."""
        import importlib
        import sys as _sys

        saved = _sys.modules.get("skimage")
        _sys.modules["skimage"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(SystemExit):
                main(["--content", "--content-method", "ssim", str(tmp_path), "--no-config"])
        finally:
            if saved is not None:
                _sys.modules["skimage"] = saved
            elif "skimage" in _sys.modules:
                del _sys.modules["skimage"]


# ---------------------------------------------------------------------------
# Document mode validation
# ---------------------------------------------------------------------------


class TestDocumentMode:
    def test_document_mode_rejects_duration_weights(self, tmp_path):
        """--mode document --weights with 'duration' key should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--weights", "duration=50,filename=50"])

    def test_document_mode_rejects_keep_longest(self, tmp_path):
        """--keep longest is not supported in document mode (no duration)."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--keep", "longest"])

    def test_document_mode_rejects_keep_highest_res(self, tmp_path):
        """--keep highest-res is not supported in document mode (no resolution)."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--keep", "highest-res"])

    def test_document_mode_rejects_audio_flag(self, tmp_path):
        """--audio is not supported in document mode."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--audio"])

    def test_document_mode_rejects_phash_content_method(self, tmp_path):
        """--content --content-method phash in document mode should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--content", "--content-method", "phash", "--no-config"])

    def test_document_mode_rejects_ssim_content_method(self, tmp_path):
        """--content --content-method ssim in document mode should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--content", "--content-method", "ssim", "--no-config"])

    def test_document_mode_rejects_clip_content_method(self, tmp_path):
        """--content --content-method clip in document mode should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "document", "--content", "--content-method", "clip", "--no-config"])

    def test_video_mode_rejects_simhash_content_method(self, tmp_path):
        """--content --content-method simhash in video mode should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--content", "--content-method", "simhash", "--no-config"])

    def test_audio_mode_rejects_simhash_content_method(self, tmp_path):
        """--content --content-method simhash in audio mode should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "audio", "--content", "--content-method", "simhash", "--no-config"])

    def test_image_mode_rejects_tfidf_content_method(self, tmp_path):
        """--content --content-method tfidf in image mode should error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "image", "--content", "--content-method", "tfidf", "--no-config"])


class TestSSIMSingleModeFallback:
    def test_run_single_pipeline_ssim_populates_scan_stats_and_discovered_paths(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta(str(files[0])), _make_meta(str(files[1]))]
        pair = _make_pair(metadata[0], metadata[1], score=98.0)
        args = _make_ssim_args(tmp_path, mode="video")

        def _fake_find_duplicates(*_args, **kwargs):
            kwargs["stats"]["total_pairs_scored"] = 1
            return [pair]

        with (
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch("duplicates_detector.metadata.extract_all", return_value=metadata),
            patch("duplicates_detector.content.extract_all_ssim_frames", return_value=metadata),
            patch("duplicates_detector.cli.find_duplicates", side_effect=_fake_find_duplicates),
        ):
            pstats = PipelineStats()
            result = _run_single_pipeline_ssim(
                args,
                pstats=pstats,
                pipeline_start=0.0,
                mode="video",
                file_noun="video",
                comparators=None,
                config_hash="unused",
            )

        assert result == [pair]
        assert pstats.files_scanned == len(files)
        assert pstats.discovered_paths == set(files)

    def test_main_ssim_video_writes_output_and_prunes_discovered_paths(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()
        metadata = [_make_meta(str(files[0])), _make_meta(str(files[1]))]
        pair = _make_pair(metadata[0], metadata[1], score=97.0)
        output_file = tmp_path / "output.json"
        mock_cache = MagicMock()
        mock_cache.stats.return_value = {}
        mock_cache.prune = MagicMock()

        def _fake_find_duplicates(*_args, **kwargs):
            kwargs["stats"]["total_pairs_scored"] = 1
            return [pair]

        with (
            _mock_scan_iter(*files),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch("duplicates_detector.metadata.extract_all", return_value=metadata),
            patch("duplicates_detector.content.extract_all_ssim_frames", return_value=metadata),
            patch("duplicates_detector.cli.find_duplicates", side_effect=_fake_find_duplicates),
            patch("duplicates_detector.cache_db.CacheDB", return_value=mock_cache),
        ):
            main(
                [
                    str(tmp_path),
                    "--content",
                    "--content-method",
                    "ssim",
                    "--format",
                    "json",
                    "--output",
                    str(output_file),
                    "--no-config",
                    "-q",
                ]
            )

        assert output_file.exists()
        assert isinstance(json.loads(output_file.read_text()), list)
        mock_cache.prune.assert_called_once_with(set(files))

    def test_main_ssim_image_writes_output_and_prunes_discovered_paths(self, tmp_path):
        files = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
        for path in files:
            path.touch()
        metadata = [_make_meta(str(files[0])), _make_meta(str(files[1]))]
        pair = _make_pair(metadata[0], metadata[1], score=96.0)
        output_file = tmp_path / "output.json"
        mock_cache = MagicMock()
        mock_cache.stats.return_value = {}
        mock_cache.prune = MagicMock()

        def _fake_find_duplicates(*_args, **kwargs):
            kwargs["stats"]["total_pairs_scored"] = 1
            return [pair]

        with (
            _mock_scan_iter(*files),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch("duplicates_detector.metadata.extract_all_images", return_value=metadata),
            patch("duplicates_detector.content.extract_all_image_ssim_frames", return_value=metadata),
            patch("duplicates_detector.cli.find_duplicates", side_effect=_fake_find_duplicates),
            patch("duplicates_detector.cache_db.CacheDB", return_value=mock_cache),
        ):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "image",
                    "--content",
                    "--content-method",
                    "ssim",
                    "--format",
                    "json",
                    "--output",
                    str(output_file),
                    "--no-config",
                    "-q",
                ]
            )

        assert output_file.exists()
        assert isinstance(json.loads(output_file.read_text()), list)
        mock_cache.prune.assert_called_once_with(set(files))


# ---------------------------------------------------------------------------
# --audio / --no-audio-cache
# ---------------------------------------------------------------------------


class TestAudioFlag:
    def test_audio_flag_parses(self):
        args = parse_args(["--audio", "/dir"])
        assert args.audio is True

    def test_audio_default_none(self):
        args = parse_args(["/dir"])
        assert args.audio is None

    def test_no_audio_cache_flag_parses(self):
        args = parse_args(["--no-audio-cache", "/dir"])
        assert args.no_audio_cache is True

    def test_no_audio_cache_default_none(self):
        args = parse_args(["/dir"])
        assert args.no_audio_cache is None

    def test_image_mode_explicit_audio_errors(self, tmp_path):
        """--mode image --audio on CLI should hard-error."""
        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "image", "--audio"])

    def test_image_mode_config_audio_warns_and_continues(self, tmp_path, capsys):
        """audio=true inherited from config in image mode should warn and continue."""
        files = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
        for f in files:
            f.touch()
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.config.load_config", return_value={"audio": True}),
        ):
            main([str(tmp_path), "--mode", "image"])
        captured = capsys.readouterr()
        assert "ignored in image mode" in captured.err.lower()

    def test_audio_weights_without_flag_errors(self, tmp_path):
        """--weights with 'audio' key but no --audio flag should error."""
        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--weights",
                    "filename=20,duration=20,resolution=10,filesize=10,audio=40",
                ]
            )

    def test_audio_weights_with_flag_accepted(self, tmp_path):
        """--audio --weights with 'audio' key should be accepted."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.write_bytes(b"x" * 10)
        metadata = [
            VideoMetadata(path=f, filename=f.stem, duration=120.0, width=1920, height=1080, file_size=10) for f in files
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.audio.extract_all_audio_fingerprints", return_value=metadata),
            patch("duplicates_detector.audio.check_fpcalc"),
        ):
            main(
                [
                    str(tmp_path),
                    "--audio",
                    "--weights",
                    "filename=20,duration=20,resolution=10,filesize=10,audio=40",
                    "--no-config",
                ]
            )

    def test_audio_weights_missing_audio_key_errors(self, tmp_path):
        """--audio --weights without 'audio' key should error (missing required key)."""
        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--audio",
                    "--weights",
                    "filename=35,duration=35,resolution=15,filesize=15",
                ]
            )

    def test_audio_weights_in_image_mode_errors(self, tmp_path):
        """--mode image --weights with 'audio' key should error."""
        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "image",
                    "--weights",
                    "filename=20,resolution=10,filesize=10,exif=20,audio=40",
                ]
            )

    def test_image_weights_valid_when_audio_inherited_from_config(self, tmp_path):
        """Image weights should not require 'audio' key even when audio=True is inherited from config."""
        from duplicates_detector.cli import _validate_weights

        console = Console(stderr=True)
        # This simulates audio=True inherited from a saved config while in image mode.
        # Should NOT error — audio is irrelevant in image mode.
        result = _validate_weights(
            "filename=25,resolution=20,filesize=15,exif=40",
            content=False,
            console=console,
            mode="image",
            audio=True,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# --replay: flag parsing
# ---------------------------------------------------------------------------


def _make_replay_envelope(pairs_data: list[dict] | None = None, groups_data: list[dict] | None = None) -> dict:
    """Build a minimal JSON envelope for replay tests."""
    envelope: dict = {
        "version": "1.0.0",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "args": {},
        "stats": {},
    }
    if pairs_data is not None:
        envelope["pairs"] = pairs_data
    if groups_data is not None:
        envelope["groups"] = groups_data
    return envelope


def _make_replay_pair(
    file_a: str = "/videos/a.mp4",
    file_b: str = "/videos/b.mp4",
    score: float = 85.0,
) -> dict:
    return {
        "file_a": file_a,
        "file_b": file_b,
        "score": score,
        "breakdown": {"filename": 25.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
        "detail": {
            "filename": [0.83, 30.0],
            "duration": [1.0, 30.0],
            "resolution": [1.0, 10.0],
            "file_size": [1.0, 10.0],
        },
        "file_a_metadata": {
            "duration": 120.0,
            "width": 1920,
            "height": 1080,
            "file_size": 1_000_000,
            "mtime": 1_700_000_000.0,
        },
        "file_b_metadata": {
            "duration": 120.0,
            "width": 1920,
            "height": 1080,
            "file_size": 1_000_000,
            "mtime": 1_700_000_000.0,
        },
        "file_a_is_reference": False,
        "file_b_is_reference": False,
    }


class TestReplayParseArgs:
    def test_replay_default_none(self):
        args = parse_args(["/dir"])
        assert args.replay is None

    def test_replay_flag_parses(self):
        args = parse_args(["--replay", "output.json"])
        assert args.replay == "output.json"


class TestReplayConflicts:
    """--replay should error when combined with scan-specific flags."""

    def _write_envelope(self, tmp_path, pairs=None):
        f = tmp_path / "replay.json"
        pairs = pairs or [_make_replay_pair()]
        f.write_text(json.dumps(_make_replay_envelope(pairs_data=pairs)))
        return str(f)

    def test_replay_conflicts_with_content(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--content"])

    def test_replay_conflicts_with_audio(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--audio"])

    def test_replay_conflicts_with_weights(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--weights", "filename=30,duration=25,resolution=25,file_size=20"])

    def test_replay_conflicts_with_min_size(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--min-size", "10MB"])

    def test_replay_conflicts_with_exclude(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--exclude", "*.tmp"])

    def test_replay_conflicts_with_codec(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--codec", "h264"])

    def test_replay_with_directories_errors(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "/some/dir"])

    def test_replay_with_explicit_dot_directory_errors(self, tmp_path):
        """Explicit '.' should also be caught, not confused with the parser default."""
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "."])

    def test_replay_conflicts_with_cache_dir(self, tmp_path):
        f = self._write_envelope(tmp_path)
        with pytest.raises(SystemExit):
            main(["--replay", f, "--cache-dir", str(tmp_path)])


class TestReplayCompatible:
    """--replay should work with post-scoring flags."""

    def _write_envelope(self, tmp_path, pairs=None):
        f = tmp_path / "replay.json"
        pairs = pairs or [_make_replay_pair()]
        f.write_text(json.dumps(_make_replay_envelope(pairs_data=pairs)))
        return str(f)

    def test_replay_allows_keep(self, tmp_path):
        f = self._write_envelope(tmp_path)
        # Should not raise
        main(["--replay", f, "--keep", "biggest", "--dry-run", "--format", "json"])

    def test_replay_allows_min_score(self, tmp_path):
        f = self._write_envelope(tmp_path)
        main(["--replay", f, "--min-score", "90", "--format", "json"])

    def test_replay_allows_sort(self, tmp_path):
        f = self._write_envelope(tmp_path)
        main(["--replay", f, "--sort", "size", "--format", "json"])

    def test_replay_allows_group(self, tmp_path):
        f = self._write_envelope(tmp_path)
        main(["--replay", f, "--group", "--format", "json"])

    def test_replay_allows_format(self, tmp_path):
        f = self._write_envelope(tmp_path)
        main(["--replay", f, "--format", "csv"])


class TestReplayModeValidationBypass:
    """Replay should bypass mode-specific validations (P2 fix)."""

    def _write_envelope(self, tmp_path, pairs=None):
        f = tmp_path / "replay.json"
        pairs = pairs or [_make_replay_pair()]
        f.write_text(json.dumps(_make_replay_envelope(pairs_data=pairs)))
        return str(f)

    def test_replay_with_image_mode_config_and_keep_longest(self, tmp_path):
        """--keep longest should work in replay even when config sets mode=image."""
        f = self._write_envelope(tmp_path)
        out = tmp_path / "out.json"
        ignore = str(tmp_path / "empty-ignore.json")
        with patch("duplicates_detector.config.load_config", return_value={"mode": "image"}):
            main(
                [
                    "--replay",
                    f,
                    "--keep",
                    "longest",
                    "--dry-run",
                    "--format",
                    "json",
                    "--output",
                    str(out),
                    "--ignore-file",
                    ignore,
                ]
            )
        data = json.loads(out.read_text())
        assert len(data) == 1

    def test_replay_with_explicit_image_mode_and_keep_longest(self, tmp_path):
        """--replay --mode image --keep longest should warn about mode but succeed."""
        f = self._write_envelope(tmp_path)
        out = tmp_path / "out.json"
        ignore = str(tmp_path / "empty-ignore.json")
        main(
            [
                "--replay",
                f,
                "--mode",
                "image",
                "--keep",
                "longest",
                "--dry-run",
                "--format",
                "json",
                "--output",
                str(out),
                "--ignore-file",
                ignore,
            ]
        )
        data = json.loads(out.read_text())
        assert len(data) == 1


class TestReplayMain:
    """End-to-end replay tests."""

    def _write_envelope(self, tmp_path, pairs=None, groups=None):
        f = tmp_path / "replay.json"
        envelope = _make_replay_envelope(pairs_data=pairs, groups_data=groups)
        f.write_text(json.dumps(envelope))
        return str(f)

    def test_replay_pair_mode(self, tmp_path):
        """Load envelope, verify JSON output, verify scan/extract NOT called."""
        f = self._write_envelope(tmp_path, pairs=[_make_replay_pair()])
        out = tmp_path / "out.json"
        ignore = str(tmp_path / "empty-ignore.json")

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files") as mock_scan,
            patch("duplicates_detector.cli.run_pipeline", new_callable=AsyncMock) as mock_pipeline,
        ):
            main(["--replay", f, "--format", "json", "--output", str(out), "--ignore-file", ignore])

        mock_scan.assert_not_called()
        mock_pipeline.assert_not_called()

        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["score"] == 85.0

    def test_replay_applies_min_score_filter(self, tmp_path):
        """Pairs below min-score are filtered out."""
        pairs = [
            _make_replay_pair(score=50.0),
            _make_replay_pair(file_a="/videos/c.mp4", file_b="/videos/d.mp4", score=70.0),
            _make_replay_pair(file_a="/videos/e.mp4", file_b="/videos/f.mp4", score=90.0),
        ]
        f = self._write_envelope(tmp_path, pairs=pairs)
        out = tmp_path / "out.json"

        main(["--replay", f, "--format", "json", "--output", str(out), "--min-score", "80"])

        data = json.loads(out.read_text())
        assert len(data) == 1
        assert data[0]["score"] == 90.0

    def test_replay_applies_reference(self, tmp_path):
        """--reference tags files under that dir."""
        pair = _make_replay_pair(file_a="/ref/a.mp4", file_b="/other/b.mp4")
        f = self._write_envelope(tmp_path, pairs=[pair])
        out = tmp_path / "out.json"

        ref_dir = tmp_path / "ref"
        ref_dir.mkdir()

        # Create the file paths so resolve works
        with patch("duplicates_detector.cli._is_reference") as mock_is_ref:
            mock_is_ref.side_effect = lambda path, ref_dirs: str(path).startswith("/ref/")
            main(["--replay", f, "--reference", str(ref_dir), "--format", "json", "--output", str(out)])

        data = json.loads(out.read_text())
        assert data[0]["file_a_is_reference"] is True

    def test_replay_with_group(self, tmp_path):
        """--group groups loaded pairs."""
        pairs = [
            _make_replay_pair(file_a="/videos/a.mp4", file_b="/videos/b.mp4", score=85.0),
            _make_replay_pair(file_a="/videos/a.mp4", file_b="/videos/c.mp4", score=80.0),
        ]
        f = self._write_envelope(tmp_path, pairs=pairs)
        out = tmp_path / "out.json"
        ignore = str(tmp_path / "empty-ignore.json")

        main(["--replay", f, "--group", "--format", "json", "--output", str(out), "--ignore-file", ignore])

        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert len(data) >= 1
        # Groups should have group_id
        assert "group_id" in data[0]

    def test_replay_file_not_found(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["--replay", str(tmp_path / "nonexistent.json")])

    def test_replay_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json{{{")
        with pytest.raises(SystemExit):
            main(["--replay", str(f)])

    def test_replay_empty_pairs(self, tmp_path):
        f = self._write_envelope(tmp_path, pairs=[])
        # Should not raise, just return
        main(["--replay", f])

    def test_replay_output_can_be_replayed(self, tmp_path):
        """Generate JSON envelope from replay, re-replay — same pairs."""
        pairs = [_make_replay_pair(score=85.0)]
        f1 = self._write_envelope(tmp_path, pairs=pairs)
        out1 = tmp_path / "out1.json"
        ignore = str(tmp_path / "empty-ignore.json")

        main(["--replay", f1, "--format", "json", "--json-envelope", "--output", str(out1), "--ignore-file", ignore])

        out2 = tmp_path / "out2.json"
        main(["--replay", str(out1), "--format", "json", "--output", str(out2), "--ignore-file", ignore])

        data = json.loads(out2.read_text())
        assert len(data) == 1
        assert data[0]["score"] == 85.0


# ---------------------------------------------------------------------------
# --embed-thumbnails / --thumbnail-size
# ---------------------------------------------------------------------------


class TestEmbedThumbnails:
    def test_embed_thumbnails_flag_parses(self):
        args = parse_args(["--embed-thumbnails", "/dir"])
        assert args.embed_thumbnails is True

    def test_embed_thumbnails_default_none(self):
        args = parse_args(["/dir"])
        assert args.embed_thumbnails is None

    def test_thumbnail_size_flag_parses(self):
        args = parse_args(["--thumbnail-size", "320x180", "/dir"])
        assert args.thumbnail_size == "320x180"

    def test_embed_thumbnails_without_json_envelope_errors(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            main([str(tmp_path), "--embed-thumbnails", "--format", "json"])

    def test_embed_thumbnails_without_format_json_errors(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            main([str(tmp_path), "--embed-thumbnails", "--json-envelope", "--format", "csv"])

    def test_embed_thumbnails_with_format_html_errors(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            main([str(tmp_path), "--embed-thumbnails", "--json-envelope", "--format", "html"])

    def test_thumbnail_size_without_embed_thumbnails_ignored(self, tmp_path):
        """--thumbnail-size without --embed-thumbnails does not error."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
        ):
            # Should not raise
            main([str(tmp_path), "--thumbnail-size", "320x180"])

    def test_thumbnail_size_invalid_format_errors(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            main(
                [
                    str(tmp_path),
                    "--embed-thumbnails",
                    "--json-envelope",
                    "--format",
                    "json",
                    "--thumbnail-size",
                    "big",
                ]
            )

    def test_thumbnail_size_zero_errors(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            main(
                [
                    str(tmp_path),
                    "--embed-thumbnails",
                    "--json-envelope",
                    "--format",
                    "json",
                    "--thumbnail-size",
                    "0x0",
                ]
            )

    def test_thumbnail_size_single_number_errors(self, tmp_path):
        """--thumbnail-size with a single number (no 'x') should error."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            main(
                [
                    str(tmp_path),
                    "--embed-thumbnails",
                    "--json-envelope",
                    "--format",
                    "json",
                    "--thumbnail-size",
                    "160",
                ]
            )

    def test_embed_thumbnails_calls_batch_generator(self, tmp_path):
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch(
                "duplicates_detector.thumbnails.generate_thumbnails_batch",
                return_value={
                    metadata[0].path.resolve(): "data:a",
                    metadata[1].path.resolve(): "data:b",
                },
            ) as mock_batch,
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--embed-thumbnails",
                    "--output",
                    str(out_file),
                ]
            )
        mock_batch.assert_called_once()

        data = json.loads(out_file.read_text())
        assert data["pairs"][0]["file_a_metadata"]["thumbnail"] == "data:a"
        assert data["pairs"][0]["file_b_metadata"]["thumbnail"] == "data:b"

    def test_embed_thumbnails_default_video_size(self):
        assert _parse_thumbnail_size(None, "video") == (160, 90)

    def test_embed_thumbnails_default_image_size(self):
        assert _parse_thumbnail_size(None, "image") == (160, 160)

    def test_embed_thumbnails_default_auto_size_is_none(self):
        assert _parse_thumbnail_size(None, "auto") is None

    def test_parse_thumbnail_size_explicit(self):
        assert _parse_thumbnail_size("320x180", "video") == (320, 180)

    def test_parse_thumbnail_size_case_insensitive(self):
        assert _parse_thumbnail_size("320X180", "video") == (320, 180)

    def test_embed_thumbnails_in_envelope_args(self, tmp_path):
        import json

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta("a.mp4"), _make_meta("b.mp4")]
        pairs = [
            ScoredPair(
                file_a=metadata[0],
                file_b=metadata[1],
                total_score=85.0,
                breakdown={"filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
        out_file = tmp_path / "result.json"
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=pairs, files_scanned=2),
            ),
            patch(
                "duplicates_detector.thumbnails.generate_thumbnails_batch",
                return_value={},
            ),
        ):
            main(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--embed-thumbnails",
                    "--output",
                    str(out_file),
                ]
            )

        data = json.loads(out_file.read_text())
        assert data["args"]["embed_thumbnails"] is True
        assert data["args"]["thumbnail_size"] == [160, 90]

    def test_save_config_embed_thumbnails_without_envelope_errors(self, tmp_path):
        """--save-config --embed-thumbnails without --json-envelope should error."""
        with (
            patch("duplicates_detector.config.save_config"),
            patch("duplicates_detector.config.get_config_path", return_value=tmp_path / "config.toml"),
            pytest.raises(SystemExit, match="1"),
        ):
            main(["--save-config", "--embed-thumbnails", str(tmp_path)])

    def test_save_config_embed_thumbnails_with_envelope_succeeds(self, tmp_path):
        """--save-config --embed-thumbnails --json-envelope should succeed and auto-set format=json."""
        with (
            patch("duplicates_detector.config.save_config") as mock_save,
            patch("duplicates_detector.config.get_config_path", return_value=tmp_path / "config.toml"),
        ):
            main(["--save-config", "--embed-thumbnails", "--json-envelope", str(tmp_path)])
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved.get("format") == "json"

    def test_save_config_embed_thumbnails_invalid_size_errors(self, tmp_path):
        """--save-config --embed-thumbnails --thumbnail-size with bad value should error."""
        with (
            patch("duplicates_detector.config.save_config"),
            patch("duplicates_detector.config.get_config_path", return_value=tmp_path / "config.toml"),
            pytest.raises(SystemExit, match="1"),
        ):
            main(
                [
                    "--save-config",
                    "--embed-thumbnails",
                    "--json-envelope",
                    "--thumbnail-size",
                    "big",
                    str(tmp_path),
                ]
            )

    def test_save_config_embed_thumbnails_with_format_csv_errors(self, tmp_path):
        """--save-config --embed-thumbnails --json-envelope --format csv should error."""
        with (
            patch("duplicates_detector.config.save_config"),
            patch("duplicates_detector.config.get_config_path", return_value=tmp_path / "config.toml"),
            pytest.raises(SystemExit, match="1"),
        ):
            main(["--save-config", "--embed-thumbnails", "--json-envelope", "--format", "csv", str(tmp_path)])

    def test_save_config_embed_thumbnails_catches_config_inherited_format(self, tmp_path):
        """Existing config format=csv should be rejected when saving --embed-thumbnails."""
        with (
            patch("duplicates_detector.config.save_config"),
            patch("duplicates_detector.config.get_config_path", return_value=tmp_path / "config.toml"),
            patch("duplicates_detector.config.load_config", return_value={"format": "csv", "json_envelope": True}),
            pytest.raises(SystemExit, match="1"),
        ):
            # No --format on CLI; csv comes from config
            main(["--save-config", "--embed-thumbnails", "--json-envelope", str(tmp_path)])

    def test_save_profile_embed_thumbnails_without_envelope_errors(self, tmp_path):
        """--save-profile --embed-thumbnails without --json-envelope should error."""
        with (
            patch("duplicates_detector.config.save_profile"),
            patch("duplicates_detector.config.validate_profile_name"),
            pytest.raises(SystemExit, match="1"),
        ):
            main(["--save-profile", "test", "--embed-thumbnails", str(tmp_path)])

    def test_replay_uses_envelope_mode_for_thumbnails(self, tmp_path):
        """--replay with --embed-thumbnails uses the envelope's original mode."""
        import json

        envelope = {
            "version": "1.0.0",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "args": {"mode": "image"},
            "stats": {},
            "pairs": [
                {
                    "file_a": "/photos/a.jpg",
                    "file_b": "/photos/b.jpg",
                    "score": 85.0,
                    "breakdown": {"filename": 30.0},
                    "detail": {},
                    "file_a_metadata": {
                        "duration": None,
                        "width": 1920,
                        "height": 1080,
                        "file_size": 5000,
                    },
                    "file_b_metadata": {
                        "duration": None,
                        "width": 1920,
                        "height": 1080,
                        "file_size": 5000,
                    },
                }
            ],
        }
        replay_file = tmp_path / "scan.json"
        replay_file.write_text(json.dumps(envelope))
        out_file = tmp_path / "out.json"

        with patch(
            "duplicates_detector.thumbnails.generate_thumbnails_batch",
            return_value={},
        ) as mock_batch:
            main(
                [
                    "--replay",
                    str(replay_file),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--embed-thumbnails",
                    "--output",
                    str(out_file),
                ]
            )
        # Should have been called with mode="image" from envelope, not default "video"
        mock_batch.assert_called_once()
        assert mock_batch.call_args[1]["mode"] == "image"


# ---------------------------------------------------------------------------
# Subcommand parsing
# ---------------------------------------------------------------------------


class TestSubcommandParsing:
    """Verify that scan subcommand routing and backward compatibility work."""

    def test_implicit_scan_backward_compat(self):
        """Bare directory arg (no subcommand) defaults to scan."""
        args = parse_args(["/tmp"])
        assert args.subcommand == "scan"
        assert args.directories == ["/tmp"]

    def test_explicit_scan(self):
        """Explicit 'scan' subcommand is parsed correctly."""
        args = parse_args(["scan", "/tmp"])
        assert args.subcommand == "scan"
        assert args.directories == ["/tmp"]

    def test_version_flag_still_works(self):
        """--version raises SystemExit(0) as before (not broken by subcommands)."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_version_flag_works_after_scan_positionals(self):
        """Root --version is honored even when it appears after scan args."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["scan", "/tmp", "--version"])
        assert exc_info.value.code == 0

    def test_print_completion_flag_works_after_subcommand_tokens(self):
        """Root --print-completion is honored even when mixed with subcommand tokens."""
        args = parse_args(["scan", "/tmp", "--print-completion", "bash"])
        assert args.print_completion == "bash"

    def test_root_action_flags_take_precedence_over_subcommand_parse_errors(self):
        """Global action flags intentionally short-circuit before subcommand parse errors."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["scan", "--output", "--version"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# --machine-progress flag
# ---------------------------------------------------------------------------


class TestMachineProgressFlag:
    def test_machine_progress_parsed_true(self):
        """--machine-progress sets machine_progress to True."""
        args = parse_args(["--machine-progress", "/dir"])
        assert args.machine_progress is True

    def test_machine_progress_default_none(self):
        """machine_progress defaults to None (sentinel) when not provided."""
        args = parse_args(["/dir"])
        assert args.machine_progress is None

    def test_machine_progress_scan_subcommand(self):
        """--machine-progress is accepted by explicit scan subcommand."""
        args = parse_args(["scan", "--machine-progress", "/dir"])
        assert args.machine_progress is True

    def test_machine_progress_replay_emits_replay_stage(self, tmp_path):
        """--machine-progress + --replay emits replay stage_start/stage_end."""
        envelope = _make_replay_envelope(pairs_data=[_make_replay_pair()])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))
        out = tmp_path / "out.json"

        buf = StringIO()
        with patch("sys.stderr", buf):
            main(
                [
                    "--replay",
                    str(f),
                    "--machine-progress",
                    "--quiet",
                    "--format",
                    "json",
                    "--output",
                    str(out),
                ]
            )

        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        events = [json.loads(line) for line in lines]

        replay_starts = [e for e in events if e["type"] == "stage_start" and e["stage"] == "replay"]
        replay_ends = [e for e in events if e["type"] == "stage_end" and e["stage"] == "replay"]

        assert len(replay_starts) == 1
        assert len(replay_ends) == 1
        assert "total" not in replay_starts[0], "stage_start should not set total (unknown until replay finishes)"
        assert replay_ends[0]["total"] == 1

    def test_machine_progress_replay_keeps_session_start_total_files_zero(self, tmp_path):
        """Replay keeps the existing session_start.total_files=0 contract."""
        envelope = _make_replay_envelope(pairs_data=[_make_replay_pair()])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))
        out = tmp_path / "out.json"

        buf = StringIO()
        with patch("sys.stderr", buf):
            main(
                [
                    "--replay",
                    str(f),
                    "--machine-progress",
                    "--quiet",
                    "--format",
                    "json",
                    "--output",
                    str(out),
                ]
            )

        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        events = [json.loads(line) for line in lines]
        session_starts = [e for e in events if e["type"] == "session_start"]

        assert len(session_starts) == 1
        assert session_starts[0]["total_files"] == 0


# ---------------------------------------------------------------------------
# --mode auto + --machine-progress (deduplicated stage emissions)
# ---------------------------------------------------------------------------


class TestAutoModeProgressStages:
    """Verify that auto mode uses AggregatingProgressEmitter for dual sub-pipelines
    and passes direct progress for single-type scans."""

    def test_auto_mode_seeds_both_subpipelines_without_rescanning(self, tmp_path):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.jpg").touch()

        buf = StringIO()
        with (
            _mock_scan_iter_auto(),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=[
                    PipelineResult(pairs=[], files_scanned=1),
                    PipelineResult(pairs=[], files_scanned=1),
                ],
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--machine-progress", "--quiet"])

        assert mock_pipeline.call_count == 2
        video_call = next(call_obj for call_obj in mock_pipeline.call_args_list if call_obj.kwargs["mode"] == "video")
        image_call = next(call_obj for call_obj in mock_pipeline.call_args_list if call_obj.kwargs["mode"] == "image")
        assert video_call.kwargs["pre_scanned_paths"] == [Path("a.mp4")]
        assert image_call.kwargs["pre_scanned_paths"] == [Path("b.jpg")]

        events = [json.loads(line) for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1
        assert session_starts[0]["total_files"] == 0
        scan_ends = [e for e in events if e["type"] == "stage_end" and e["stage"] == "scan"]
        assert len(scan_ends) == 1
        assert scan_ends[0]["total"] == 2

    def test_auto_mode_passes_progress_to_both_pipelines(self, tmp_path):
        """Auto mode passes progress emitters to both sub-pipelines."""
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.mp4", media_type="video"),
        ]
        for mf in media_files:
            mf.path.touch()

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--machine-progress", "--quiet"])

        # Both sub-pipelines receive progress emitters (via AggregatingProgressEmitter)
        assert mock_pipeline.call_count == 2
        for call_obj in mock_pipeline.call_args_list:
            assert call_obj.kwargs.get("progress") is not None

    def test_non_auto_mode_passes_progress(self, tmp_path):
        """Non-auto mode passes the progress emitter to run_pipeline."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.touch()

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "video", "--machine-progress", "--quiet"])

        # In non-auto mode, progress emitter should be passed through (not None)
        mock_pipeline.assert_called_once()
        assert mock_pipeline.call_args.kwargs.get("progress") is not None


class TestPauseCheckpointStageTimings:
    """Pause checkpoints must persist real timing history."""

    def test_pause_checkpoint_preserves_completed_stage_timings(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        saved_sessions = []

        async def _pause_pipeline(*_args, **kwargs):
            controller = kwargs["controller"]
            controller.enter_stage("scan")
            controller.complete_stage("scan")
            controller.enter_stage("extract")
            controller.pause()
            controller.resume()
            return PipelineResult(pairs=[], files_scanned=2)

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.session.SessionManager.save",
                autospec=True,
                side_effect=lambda _self, session: saved_sessions.append(session),
            ),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=_pause_pipeline,
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--quiet"])

        assert len(saved_sessions) == 1
        checkpoint = saved_sessions[0]
        assert checkpoint.completed_stages == ["scan"]
        assert checkpoint.active_stage == "extract"
        assert "scan" in checkpoint.stage_timings
        assert checkpoint.stage_timings["scan"] >= 0.0
        assert "extract" not in checkpoint.stage_timings

    def test_pause_checkpoint_merges_prior_stage_timings_on_resume(self, tmp_path):
        from duplicates_detector.session import ScanSession, SessionManager

        sessions_dir = tmp_path / "sessions"
        mgr = SessionManager(sessions_dir)
        mgr.save(
            ScanSession(
                session_id="resume-timings",
                directories=[str(tmp_path)],
                config={"mode": "video"},
                completed_stages=["scan"],
                active_stage="extract",
                total_files=2,
                elapsed_seconds=5.0,
                stage_timings={"scan": 2.0},
            )
        )

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        saved_sessions = []

        async def _pause_pipeline(*_args, **kwargs):
            controller = kwargs["controller"]
            controller.enter_stage("scan")
            controller.complete_stage("scan")
            controller.enter_stage("extract")
            controller.complete_stage("extract")
            controller.enter_stage("filter")
            controller.pause()
            controller.resume()
            return PipelineResult(pairs=[], files_scanned=2)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.session.SessionManager.save",
                autospec=True,
                side_effect=lambda _self, session: saved_sessions.append(session),
            ),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=_pause_pipeline,
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--resume", "resume-timings", "--quiet"])

        assert len(saved_sessions) == 1
        checkpoint = saved_sessions[0]
        assert checkpoint.completed_stages == ["scan", "extract"]
        assert checkpoint.active_stage == "filter"
        assert checkpoint.stage_timings["scan"] == 2.0
        assert "extract" in checkpoint.stage_timings
        assert checkpoint.stage_timings["extract"] >= 0.0
        assert "filter" not in checkpoint.stage_timings

    def test_auto_mode_pause_checkpoint_preserves_aggregated_stage_timings(self, tmp_path):
        media_files = [
            MediaFile(path=tmp_path / "a.mp4", media_type="video"),
            MediaFile(path=tmp_path / "b.jpg", media_type="image"),
        ]
        for media_file in media_files:
            media_file.path.touch()

        saved_sessions = []
        call_count = {"value": 0}

        async def _pause_pipeline(*_args, **kwargs):
            call_count["value"] += 1
            progress = kwargs["progress"]
            controller = kwargs["controller"]
            scan_elapsed = 0.5 if call_count["value"] == 1 else 0.75
            extract_elapsed = 1.0 if call_count["value"] == 1 else 1.5

            progress.stage_start("scan", total=1)
            progress.stage_end("scan", total=1, elapsed=scan_elapsed)
            progress.stage_start("extract", total=1)
            progress.stage_end("extract", total=1, elapsed=extract_elapsed)

            if call_count["value"] == 2:
                controller.pause()
                controller.resume()

            return PipelineResult(pairs=[], files_scanned=1)

        with (
            patch("duplicates_detector.cli.find_media_files", return_value=media_files),
            patch(
                "duplicates_detector.session.SessionManager.save",
                autospec=True,
                side_effect=lambda _self, session: saved_sessions.append(session),
            ),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=_pause_pipeline,
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--mode", "auto", "--machine-progress", "--quiet"])

        assert len(saved_sessions) == 1
        checkpoint = saved_sessions[0]
        assert checkpoint.completed_stages == ["scan", "extract"]
        assert checkpoint.active_stage == "paused"
        assert checkpoint.stage_timings["extract"] == 1.5
        assert checkpoint.stage_timings["scan"] >= 0.0


class TestPauseDuringPostPipelineStages:
    """Pause/resume must cover thumbnail and report work too."""

    @staticmethod
    def _completed_pipeline_result(controller: PipelineController, pairs: list[ScoredPair]) -> PipelineResult:
        controller.files_discovered = 2
        for stage in ("scan", "extract", "filter", "score"):
            controller.enter_stage(stage)
            controller.complete_stage(stage)
        return PipelineResult(pairs=pairs, files_scanned=2)

    @staticmethod
    def _start_main_thread(argv: list[str], errors: list[BaseException]) -> threading.Thread:
        def _target() -> None:
            try:
                main(argv)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=_target, name="cli-main-test", daemon=True)
        thread.start()
        return thread

    def test_pause_during_thumbnail_stage_blocks_completion_until_resume(self, tmp_path):
        from duplicates_detector.session import SessionManager

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        pairs = [_make_pair(_make_meta(str(files[0])), _make_meta(str(files[1])))]
        sessions_dir = tmp_path / "sessions"
        controller_holder: dict[str, PipelineController] = {}
        pause_triggered = threading.Event()
        allow_thumbnail_return = threading.Event()
        errors: list[BaseException] = []

        async def _pipeline(*_args, **kwargs):
            controller = cast(PipelineController, kwargs["controller"])
            controller_holder["controller"] = controller
            return self._completed_pipeline_result(controller, pairs)

        def _pause_thumbnail(*_args, **_kwargs):
            controller = controller_holder["controller"]
            controller.pause()
            pause_triggered.set()
            assert allow_thumbnail_return.wait(timeout=1.0)
            return {}

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("signal.signal"),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=_pipeline,
            ),
            patch("duplicates_detector.thumbnails.generate_thumbnails_batch", side_effect=_pause_thumbnail),
        ):
            thread = self._start_main_thread(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--json-envelope",
                    "--embed-thumbnails",
                    "--quiet",
                ],
                errors,
            )

            assert pause_triggered.wait(timeout=1.0)
            assert _wait_for(lambda: len(list(sessions_dir.glob("*.json"))) == 1)

            session = SessionManager(sessions_dir).list_sessions()[0]
            assert session.active_stage == "thumbnail"
            assert session.completed_stages == ["scan", "extract", "filter", "score"]
            assert "thumbnail" not in session.stage_timings

            allow_thumbnail_return.set()
            thread.join(timeout=0.2)
            assert thread.is_alive()
            assert len(list(sessions_dir.glob("*.json"))) == 1

            controller_holder["controller"].resume()
            thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert errors == []
        assert list(sessions_dir.glob("*.json")) == []

    def test_pause_during_report_stage_blocks_completion_until_resume(self, tmp_path):
        from duplicates_detector.reporter import write_json as real_write_json
        from duplicates_detector.session import SessionManager

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        pairs = [_make_pair(_make_meta(str(files[0])), _make_meta(str(files[1])))]
        out_file = tmp_path / "result.json"
        sessions_dir = tmp_path / "sessions"
        controller_holder: dict[str, PipelineController] = {}
        pause_triggered = threading.Event()
        allow_report_return = threading.Event()
        errors: list[BaseException] = []

        async def _pipeline(*_args, **kwargs):
            controller = cast(PipelineController, kwargs["controller"])
            controller_holder["controller"] = controller
            return self._completed_pipeline_result(controller, pairs)

        def _pause_then_write_json(*args, **kwargs):
            controller = controller_holder["controller"]
            controller.pause()
            pause_triggered.set()
            assert allow_report_return.wait(timeout=1.0)
            return real_write_json(*args, **kwargs)

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("signal.signal"),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=_pipeline,
            ),
            patch("duplicates_detector.cli.write_json", side_effect=_pause_then_write_json),
        ):
            thread = self._start_main_thread(
                [
                    str(tmp_path),
                    "--format",
                    "json",
                    "--output",
                    str(out_file),
                    "--quiet",
                ],
                errors,
            )

            assert pause_triggered.wait(timeout=1.0)
            assert _wait_for(lambda: len(list(sessions_dir.glob("*.json"))) == 1)

            session = SessionManager(sessions_dir).list_sessions()[0]
            assert session.active_stage == "report"
            assert session.completed_stages == ["scan", "extract", "filter", "score"]
            assert "report" not in session.stage_timings

            allow_report_return.set()
            thread.join(timeout=0.2)
            assert thread.is_alive()
            assert len(list(sessions_dir.glob("*.json"))) == 1

            controller_holder["controller"].resume()
            thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert errors == []
        assert out_file.exists()
        assert list(sessions_dir.glob("*.json")) == []


# ---------------------------------------------------------------------------
# --resume + --machine-progress: session_start includes resumed_from
# ---------------------------------------------------------------------------


class TestResumeSessionStart:
    """Verify that --resume wires the session ID into the session_start event."""

    def _parse_progress_events(self, buf: StringIO) -> list[dict]:
        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        return [json.loads(line) for line in lines]

    def test_session_start_includes_resumed_from(self, tmp_path):
        """When resuming a paused session, session_start event must carry resumed_from."""
        from duplicates_detector.session import ScanSession, SessionManager

        sessions_dir = tmp_path / "sessions"
        mgr = SessionManager(sessions_dir)

        # Create a fake paused session
        session = ScanSession(
            session_id="paused-abc",
            directories=[str(tmp_path)],
            config={"mode": "video"},
            completed_stages=["scan"],
            active_stage="extract",
            total_files=2,
            elapsed_seconds=5.0,
            stage_timings={"scan": 2.0},
        )
        mgr.save(session)

        # Create dummy video files so the scanner finds something
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        metadata = [_make_meta(str(files[0])), _make_meta(str(files[1]))]

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--resume", "paused-abc", "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1, f"Expected 1 session_start, got {len(session_starts)}"
        assert session_starts[0]["resumed_from"] == "paused-abc"

    def test_session_start_resumed_from_none_without_resume(self, tmp_path):
        """Without --resume, session_start starts before discovery with total_files=0."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1, f"Expected 1 session_start, got {len(session_starts)}"
        assert session_starts[0]["resumed_from"] is None
        assert session_starts[0]["total_files"] == 0

    def test_pipeline_receives_progress_emitter(self, tmp_path):
        """Machine-progress scans must pass progress emitter to the pipeline."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        # Pipeline receives the progress emitter
        assert mock_pipeline.call_args.kwargs.get("progress") is not None

    def test_cli_seeds_run_pipeline_with_discovered_paths(self, tmp_path):
        """The CLI-owned discovery pass seeds run_pipeline with pre_scanned_paths."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        with (
            _mock_scan_iter_video(),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        assert mock_pipeline.call_args.kwargs["pre_scanned_paths"] == [Path("a.mp4"), Path("b.mp4")]

    def test_session_start_includes_prior_elapsed_on_resume(self, tmp_path):
        """When resuming, session_start carries prior_elapsed_seconds from the paused session."""
        from duplicates_detector.session import ScanSession, SessionManager

        sessions_dir = tmp_path / "sessions"
        mgr = SessionManager(sessions_dir)

        # Create a fake paused session with 42.5s of prior elapsed time
        session = ScanSession(
            session_id="elapsed-abc",
            directories=[str(tmp_path)],
            config={"mode": "video"},
            completed_stages=["scan"],
            active_stage="extract",
            total_files=2,
            elapsed_seconds=42.5,
            stage_timings={"scan": 2.0},
        )
        mgr.save(session)

        # Create dummy video files so the scanner finds something
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("duplicates_detector.cli.find_video_files", return_value=[tmp_path / "a.mp4", tmp_path / "b.mp4"]),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(["--resume", "elapsed-abc", "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1, f"Expected 1 session_start, got {len(session_starts)}"
        assert session_starts[0]["prior_elapsed_seconds"] == 42.5

    def test_session_start_prior_elapsed_zero_without_resume(self, tmp_path):
        """Without --resume, session_start has prior_elapsed_seconds=0.0."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1, f"Expected 1 session_start, got {len(session_starts)}"
        assert session_starts[0]["prior_elapsed_seconds"] == 0.0


# ---------------------------------------------------------------------------
# session_start must precede the first stage_start in the event stream
# ---------------------------------------------------------------------------


class TestSessionStartBeforeFirstStage:
    """session_start must be emitted before any stage_start event."""

    def _parse_progress_events(self, buf: StringIO) -> list[dict]:
        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        return [json.loads(line) for line in lines]

    def test_session_start_before_pipeline_stage_start(self, tmp_path):
        """session_start must precede the report stage_start in event stream.

        In the async pipeline redesign, scan/extract/filter/score stage events
        are emitted inside run_pipeline (which is mocked in this test).  The
        session_start is emitted after outer file discovery but before the
        async pipeline runs, and the report stage_start is emitted after the
        pipeline completes.
        """
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        types = [e["type"] for e in events]
        assert "session_start" in types, f"No session_start found in {types}"
        ss_idx = types.index("session_start")
        # session_start should precede the report stage_start (emitted by cli.py after pipeline)
        stage_starts = [(i, e) for i, e in enumerate(events) if e["type"] == "stage_start"]
        if stage_starts:
            first_stage_idx = stage_starts[0][0]
            assert ss_idx < first_stage_idx, (
                f"session_start at index {ss_idx} but first stage_start at index {first_stage_idx}"
            )


class TestSessionStartCountAlignment:
    """The seeded discovery inputs and emitted scan stats must stay aligned."""

    def _parse_progress_events(self, buf: StringIO) -> list[dict]:
        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        return [json.loads(line) for line in lines]

    def test_discovery_and_pipeline_share_inputs(self, tmp_path):
        scan_dir = tmp_path / "scan"
        ref_dir = tmp_path / "reference"
        scan_dir.mkdir()
        ref_dir.mkdir()

        count_iter = MagicMock(side_effect=lambda *args, **kwargs: iter([Path("a.mp4"), Path("b.mkv")]))
        buf = StringIO()

        with (
            patch(_SCAN_ITER_TARGET, count_iter),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
        ):
            main(
                [
                    str(scan_dir),
                    "--reference",
                    str(ref_dir),
                    "--extensions",
                    "mp4,mkv",
                    "--exclude",
                    "**/skip/**",
                    "--no-recursive",
                    "--machine-progress",
                    "--quiet",
                ]
            )

        count_call = count_iter.call_args
        assert count_call is not None
        assert count_call.args[0] == [str(scan_dir), str(ref_dir)]
        assert count_call.kwargs["recursive"] is False
        assert count_call.kwargs["extensions"] == frozenset({".mp4", ".mkv"})
        assert count_call.kwargs["exclude"] == ["**/skip/**"]

        pipeline_kwargs = mock_pipeline.call_args.kwargs
        assert pipeline_kwargs["directories"] == [scan_dir, ref_dir]
        assert pipeline_kwargs["recursive"] is False
        assert pipeline_kwargs["extensions"] == frozenset({".mp4", ".mkv"})
        assert pipeline_kwargs["exclude"] == ["**/skip/**"]
        assert pipeline_kwargs["pre_scanned_paths"] == [Path("a.mp4"), Path("b.mkv")]

        events = self._parse_progress_events(buf)
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1
        assert session_starts[0]["total_files"] == 0
        scan_ends = [e for e in events if e["type"] == "stage_end" and e["stage"] == "scan"]
        assert len(scan_ends) == 1
        assert scan_ends[0]["total"] == 2


class TestOuterDiscoveryPauseAwareness:
    """The remaining CLI discovery path must honor pause/resume before pipeline startup."""

    def test_outer_discovery_waits_for_resume_before_calling_pipeline(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        controller = __import__("duplicates_detector.pipeline", fromlist=["PipelineController"]).PipelineController()
        waiter_reached = threading.Event()
        run_pipeline_called = threading.Event()
        errors: list[BaseException] = []

        def _fake_scan_iter(*_args, **kwargs):
            pause_waiter = kwargs.get("pause_waiter")
            assert pause_waiter is not None
            yield Path("a.mp4")
            controller.pause()
            waiter_reached.set()
            pause_waiter()
            yield Path("b.mp4")

        async def _fake_pipeline(*_args, **_kwargs):
            run_pipeline_called.set()
            return PipelineResult(pairs=[], files_scanned=2)

        def _target() -> None:
            try:
                main([str(tmp_path), "--machine-progress", "--quiet"])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with (
            patch("duplicates_detector.cli.PipelineController", return_value=controller),
            patch(_SCAN_ITER_TARGET, side_effect=_fake_scan_iter),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("signal.signal"),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                side_effect=_fake_pipeline,
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            thread = threading.Thread(target=_target, name="cli-discovery-pause", daemon=True)
            thread.start()

            assert waiter_reached.wait(timeout=1.0)
            time.sleep(0.1)
            assert thread.is_alive()
            assert not run_pipeline_called.is_set()

            controller.resume()
            thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert errors == []
        assert run_pipeline_called.is_set()


class TestMachineProgressStageParity:
    """session_start.stages must match the emitted lifecycle stage set."""

    def _parse_progress_events(self, buf: StringIO) -> list[dict]:
        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        return [json.loads(line) for line in lines]

    @staticmethod
    def _emitted_stage_names(events: list[dict]) -> list[str]:
        names: list[str] = []
        for event in events:
            if event.get("type") not in {"stage_start", "stage_end"}:
                continue
            stage = event["stage"]
            if stage not in names:
                names.append(stage)
        return names

    @staticmethod
    def _fake_find_duplicates(*_args, **kwargs):
        stats = kwargs.get("stats")
        if isinstance(stats, dict):
            stats["total_pairs_scored"] = 1
        progress = kwargs.get("progress_emitter")
        if progress is not None:
            progress.progress("score", current=1, total=1, force=True)
        return []

    def _assert_stage_contract(self, events: list[dict]) -> None:
        session_starts = [e for e in events if e["type"] == "session_start"]
        assert len(session_starts) == 1
        advertised = session_starts[0]["stages"]
        emitted = self._emitted_stage_names(events)
        assert emitted == advertised
        for stage in advertised:
            assert any(e["type"] == "stage_start" and e["stage"] == stage for e in events), stage
            assert any(e["type"] == "stage_end" and e["stage"] == stage for e in events), stage

    def test_default_scan_emits_only_advertised_stages(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        def _fake_extract(path, cache, mode):
            return _make_meta(str(path))

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch("duplicates_detector.metadata._extract_one_with_cache", side_effect=_fake_extract),
            patch("duplicates_detector.scorer.find_duplicates", side_effect=self._fake_find_duplicates),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet", "--no-config"])

        self._assert_stage_contract(self._parse_progress_events(buf))

    def test_content_scan_emits_content_hash_and_matches_advertised_stages(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        def _fake_extract(path, cache, mode):
            return _make_meta(str(path))

        def _fake_hash(meta, cache, *, rotation_invariant, is_image, is_document=False):
            return meta

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("sys.stderr", buf),
            patch("duplicates_detector.metadata._extract_one_with_cache", side_effect=_fake_extract),
            patch("duplicates_detector.content._hash_one_with_cache", side_effect=_fake_hash),
            patch("duplicates_detector.scorer.find_duplicates", side_effect=self._fake_find_duplicates),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--content", "--machine-progress", "--quiet", "--no-config"])

        events = self._parse_progress_events(buf)
        self._assert_stage_contract(events)
        advertised = [e for e in events if e["type"] == "session_start"][0]["stages"]
        assert "content_hash" in advertised

    def test_audio_scan_emits_audio_fingerprint_and_matches_advertised_stages(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()

        def _fake_extract(path, cache, mode):
            return _make_meta(str(path))

        def _fake_fingerprint(meta, cache):
            return meta

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch("duplicates_detector.metadata._extract_one_with_cache", side_effect=_fake_extract),
            patch("duplicates_detector.audio._fingerprint_one_with_cache", side_effect=_fake_fingerprint),
            patch("duplicates_detector.scorer.find_duplicates", side_effect=self._fake_find_duplicates),
            patch("duplicates_detector.cli.print_table"),
        ):
            main([str(tmp_path), "--audio", "--machine-progress", "--quiet", "--no-config"])

        events = self._parse_progress_events(buf)
        self._assert_stage_contract(events)
        advertised = [e for e in events if e["type"] == "session_start"][0]["stages"]
        assert "audio_fingerprint" in advertised

    def test_replay_emits_only_advertised_stages(self, tmp_path):
        envelope = _make_replay_envelope(pairs_data=[_make_replay_pair()])
        replay_file = tmp_path / "replay.json"
        replay_file.write_text(json.dumps(envelope))
        out = tmp_path / "out.json"

        buf = StringIO()
        with patch("sys.stderr", buf):
            main(
                [
                    "--replay",
                    str(replay_file),
                    "--machine-progress",
                    "--quiet",
                    "--format",
                    "json",
                    "--output",
                    str(out),
                ]
            )

        self._assert_stage_contract(self._parse_progress_events(buf))

    def test_replay_with_thumbnails_emits_only_advertised_stages(self, tmp_path):
        envelope = _make_replay_envelope(
            pairs_data=[
                _make_replay_pair(
                    file_a=str(tmp_path / "a.mp4"),
                    file_b=str(tmp_path / "b.mp4"),
                )
            ]
        )
        replay_file = tmp_path / "replay.json"
        replay_file.write_text(json.dumps(envelope))
        out = tmp_path / "out.json"

        buf = StringIO()
        with (
            patch("sys.stderr", buf),
            patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:image/jpeg;base64,AAA"),
        ):
            main(
                [
                    "--replay",
                    str(replay_file),
                    "--embed-thumbnails",
                    "--machine-progress",
                    "--quiet",
                    "--format",
                    "json",
                    "--json-envelope",
                    "--output",
                    str(out),
                ]
            )

        events = self._parse_progress_events(buf)
        self._assert_stage_contract(events)
        advertised = [e for e in events if e["type"] == "session_start"][0]["stages"]
        assert advertised == ["replay", "filter", "thumbnail", "report"]

    def test_ssim_scan_emits_only_advertised_stages(self, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for path in files:
            path.touch()
        metadata = [_make_meta(str(files[0])), _make_meta(str(files[1]))]

        def _fake_extract_all(
            files,
            *,
            workers=0,
            verbose=False,
            cache=None,
            cache_db=None,
            quiet=False,
            progress_emitter=None,
        ):
            if progress_emitter is not None:
                progress_emitter.stage_start("extract", total=len(files))
                progress_emitter.progress("extract", current=len(files), total=len(files), force=True)
                progress_emitter.stage_end("extract", total=len(files), elapsed=0.001)
            return metadata

        def _fake_ssim_extract(
            metadata_items,
            *,
            workers=0,
            verbose=False,
            quiet=False,
            interval=2.0,
            strategy="interval",
            scene_threshold=0.3,
            progress_emitter=None,
        ):
            if progress_emitter is not None:
                progress_emitter.stage_start("ssim_extract", total=len(metadata_items))
                progress_emitter.progress(
                    "ssim_extract", current=len(metadata_items), total=len(metadata_items), force=True
                )
                progress_emitter.stage_end("ssim_extract", total=len(metadata_items), elapsed=0.001)
            return metadata_items

        def _fake_ssim_find_duplicates(*_args, **kwargs):
            stats = kwargs.get("stats")
            if isinstance(stats, dict):
                stats["total_pairs_scored"] = 1
            progress = kwargs.get("progress_emitter")
            if progress is not None:
                progress.stage_start("score")
                progress.progress("score", current=1, total=1, force=True)
                progress.stage_end("score", total=1, elapsed=0.001, pairs_found=0)
            return []

        buf = StringIO()
        with (
            _mock_scan_iter(*files),
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("sys.stderr", buf),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch("duplicates_detector.metadata.extract_all", side_effect=_fake_extract_all),
            patch("duplicates_detector.content.extract_all_ssim_frames", side_effect=_fake_ssim_extract),
            patch("duplicates_detector.cli.find_duplicates", side_effect=_fake_ssim_find_duplicates),
            patch("duplicates_detector.cli.print_table"),
        ):
            main(
                [
                    str(tmp_path),
                    "--content",
                    "--content-method",
                    "ssim",
                    "--machine-progress",
                    "--quiet",
                    "--no-config",
                ]
            )

        self._assert_stage_contract(self._parse_progress_events(buf))


# ---------------------------------------------------------------------------
# session_end.cache_time_saved includes score cache hits
# ---------------------------------------------------------------------------


class TestSessionEndCacheTimeSaved:
    """Verify that session_end.cache_time_saved includes score_hits * 0.005."""

    def _parse_progress_events(self, buf: StringIO) -> list[dict]:
        lines = [line for line in buf.getvalue().strip().splitlines() if line.startswith("{")]
        return [json.loads(line) for line in lines]

    def test_cache_time_saved_includes_score_hits(self, tmp_path):
        """cache_time_saved formula: metadata*0.05 + content*0.2 + audio*0.3 + score*0.005."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        mock_stats = {
            "metadata_hits": 100,
            "metadata_misses": 10,
            "content_hits": 20,
            "content_misses": 5,
            "audio_hits": 10,
            "audio_misses": 2,
            "score_hits": 200,
            "score_misses": 50,
        }
        expected_time_saved = 100 * 0.05 + 20 * 0.2 + 10 * 0.3 + 200 * 0.005  # 5 + 4 + 3 + 1 = 13.0

        mock_cache = MagicMock()
        mock_cache.stats.return_value = mock_stats
        mock_cache.prune = MagicMock()

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cache_db.CacheDB", return_value=mock_cache),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_ends = [e for e in events if e["type"] == "session_end"]
        assert len(session_ends) == 1, f"Expected 1 session_end, got {len(session_ends)}"
        assert session_ends[0]["cache_time_saved"] == pytest.approx(expected_time_saved)

    def test_cache_time_saved_zero_without_cache(self, tmp_path):
        """When cache_db is None (--no-cache), cache_time_saved should be 0."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch(
                "duplicates_detector.cache_db.CacheDB",
                return_value=MagicMock(
                    stats=MagicMock(return_value={}),
                    prune=MagicMock(),
                ),
            ),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_ends = [e for e in events if e["type"] == "session_end"]
        assert len(session_ends) == 1
        assert session_ends[0]["cache_time_saved"] == pytest.approx(0.0)

    def test_cache_time_saved_score_only(self, tmp_path):
        """When only score_hits are present, cache_time_saved = score_hits * 0.005."""
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        mock_stats = {"score_hits": 400, "score_misses": 100}

        mock_cache = MagicMock()
        mock_cache.stats.return_value = mock_stats
        mock_cache.prune = MagicMock()

        buf = StringIO()
        with (
            _mock_scan_iter_video(),
            patch("sys.stderr", buf),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cache_db.CacheDB", return_value=mock_cache),
        ):
            main([str(tmp_path), "--machine-progress", "--quiet"])

        events = self._parse_progress_events(buf)
        session_ends = [e for e in events if e["type"] == "session_end"]
        assert len(session_ends) == 1
        assert session_ends[0]["cache_time_saved"] == pytest.approx(400 * 0.005)


# ---------------------------------------------------------------------------
# --resume mutual exclusivity validation (M3)
# ---------------------------------------------------------------------------


class TestResumeMutualExclusivity:
    """--resume must not be combined with directory arguments or config flags."""

    def test_resume_with_directories_exits(self, tmp_path):
        """--resume + explicit directories -> SystemExit(1)."""
        from duplicates_detector.session import ScanSession, SessionManager

        sessions_dir = tmp_path / "sessions"
        mgr = SessionManager(sessions_dir)
        session = ScanSession(
            session_id="abc123",
            directories=[str(tmp_path)],
            config={"mode": "video"},
            completed_stages=[],
            active_stage="scan",
            total_files=0,
            elapsed_seconds=0.0,
            stage_timings={},
        )
        mgr.save(session)

        with (
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            pytest.raises(SystemExit, match="1"),
        ):
            main(["--resume", "abc123", str(tmp_path)])

    def test_resume_with_config_flags_exits(self, tmp_path):
        """--resume + --mode/--content -> SystemExit(1)."""
        from duplicates_detector.session import ScanSession, SessionManager

        sessions_dir = tmp_path / "sessions"
        mgr = SessionManager(sessions_dir)
        session = ScanSession(
            session_id="abc123",
            directories=[str(tmp_path)],
            config={"mode": "video"},
            completed_stages=[],
            active_stage="scan",
            total_files=0,
            elapsed_seconds=0.0,
            stage_timings={},
        )
        mgr.save(session)

        with (
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            pytest.raises(SystemExit, match="1"),
        ):
            main(["--resume", "abc123", "--mode", "image"])

    def test_resume_without_conflicts_succeeds(self, tmp_path):
        """--resume alone (no dirs, no config flags) should not error on validation."""
        from duplicates_detector.session import ScanSession, SessionManager

        sessions_dir = tmp_path / "sessions"
        mgr = SessionManager(sessions_dir)
        session = ScanSession(
            session_id="abc123",
            directories=[str(tmp_path)],
            config={"mode": "video"},
            completed_stages=[],
            active_stage="scan",
            total_files=0,
            elapsed_seconds=0.0,
            stage_timings={},
        )
        mgr.save(session)

        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]

        with (
            _mock_scan_iter_video(),
            patch("duplicates_detector.cli._get_sessions_dir", return_value=sessions_dir),
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ),
            patch("duplicates_detector.cli.print_table"),
        ):
            # Should not raise
            main(["--resume", "abc123", "--quiet"])


# ---------------------------------------------------------------------------
# SIGUSR1 toggle pause (M4)
# ---------------------------------------------------------------------------


class TestSIGUSR1Handler:
    """SIGUSR1 should toggle the pipeline controller between paused and running."""

    @pytest.mark.skipif(not hasattr(__import__("signal"), "SIGUSR1"), reason="Unix only")
    def test_sigusr1_toggles_pause(self, tmp_path):
        """Sending SIGUSR1 pauses a running controller, sending again resumes."""
        import os
        import signal

        from duplicates_detector.pipeline import PipelineController

        controller = PipelineController()
        assert not controller.is_paused

        # Register the handler the same way cli.py does
        def _toggle_pause(signum: int, frame: object) -> None:
            if controller.is_paused:
                controller.resume()
            else:
                controller.pause()

        signal.signal(signal.SIGUSR1, _toggle_pause)

        # First signal -> pause
        os.kill(os.getpid(), signal.SIGUSR1)
        assert controller.is_paused

        # Second signal -> resume
        os.kill(os.getpid(), signal.SIGUSR1)
        assert not controller.is_paused
