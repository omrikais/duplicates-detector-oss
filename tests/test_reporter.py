from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.reporter import (
    print_table,
    write_json,
    write_csv,
    write_shell,
    score_color,
    print_group_table,
    write_group_json,
    write_group_csv,
    write_group_shell,
    format_codec,
    format_bitrate,
    format_framerate,
    format_audio_channels,
    _format_details,
    _format_breakdown_verbose,
    _metadata_dict,
    _reconstruct_metadata,
    _THUMBNAIL_ABSENT,
    load_replay_json,
)
from duplicates_detector.grouper import DuplicateGroup


def _make_pair(
    path_a: str = "movie_a.mp4",
    path_b: str = "movie_b.mp4",
    score: float = 75.0,
    breakdown: dict[str, float | None] | None = None,
    detail: dict[str, tuple[float, float]] | None = None,
    a_is_ref: bool = False,
    b_is_ref: bool = False,
    a_file_size: int = 1_000_000,
    b_file_size: int = 1_000_000,
    a_duration: float | None = 120.0,
    b_duration: float | None = 120.0,
    a_codec: str | None = None,
    b_codec: str | None = None,
    a_bitrate: int | None = None,
    b_bitrate: int | None = None,
    a_framerate: float | None = None,
    b_framerate: float | None = None,
    a_audio_channels: int | None = None,
    b_audio_channels: int | None = None,
) -> ScoredPair:
    if breakdown is None:
        breakdown = {"filename": 25.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}
    if detail is None:
        # Derive detail from breakdown using assumed default weights
        _default_weights = {"filename": 30, "duration": 25, "resolution": 25, "file_size": 20}
        detail = {}
        for name, val in breakdown.items():
            if val is not None:
                w = _default_weights.get(name, 10)
                detail[name] = (val / w if w else 0.0, float(w))
    return ScoredPair(
        file_a=VideoMetadata(
            path=Path(f"/videos/{path_a}"),
            filename=Path(path_a).stem,
            duration=a_duration,
            width=1920,
            height=1080,
            file_size=a_file_size,
            is_reference=a_is_ref,
            codec=a_codec,
            bitrate=a_bitrate,
            framerate=a_framerate,
            audio_channels=a_audio_channels,
        ),
        file_b=VideoMetadata(
            path=Path(f"/videos/{path_b}"),
            filename=Path(path_b).stem,
            duration=b_duration,
            width=1920,
            height=1080,
            file_size=b_file_size,
            is_reference=b_is_ref,
            codec=b_codec,
            bitrate=b_bitrate,
            framerate=b_framerate,
            audio_channels=b_audio_channels,
        ),
        total_score=score,
        breakdown=breakdown,
        detail=detail,
    )


class TestScoreColor:
    def test_red(self):
        assert "red" in score_color(80.0)
        assert "red" in score_color(95.0)

    def test_yellow(self):
        assert "yellow" in score_color(60.0)
        assert "yellow" in score_color(79.9)

    def test_green(self):
        assert "green" in score_color(59.9)
        assert "green" in score_color(10.0)


class TestFormatCodec:
    def test_none(self):
        assert format_codec(None) == "n/a"

    def test_h264(self):
        assert format_codec("h264") == "H.264"

    def test_hevc(self):
        assert format_codec("hevc") == "H.265"

    def test_vp9(self):
        assert format_codec("vp9") == "VP9"

    def test_av1(self):
        assert format_codec("av1") == "AV1"

    def test_unknown(self):
        assert format_codec("prores") == "PRORES"


class TestFormatBitrate:
    def test_none(self):
        assert format_bitrate(None) == "n/a"

    def test_mbps(self):
        assert format_bitrate(8_000_000) == "8.0 Mbps"

    def test_kbps(self):
        assert format_bitrate(128_000) == "128 kbps"

    def test_bps(self):
        assert format_bitrate(500) == "500 bps"


class TestFormatFramerate:
    def test_none(self):
        assert format_framerate(None) == "n/a"

    def test_whole_number(self):
        assert format_framerate(30.0) == "30 fps"

    def test_fractional(self):
        assert format_framerate(23.976) == "23.976 fps"

    def test_60fps(self):
        assert format_framerate(60.0) == "60 fps"


class TestFormatAudioChannels:
    def test_none(self):
        assert format_audio_channels(None) == "n/a"

    def test_mono(self):
        assert format_audio_channels(1) == "Mono"

    def test_stereo(self):
        assert format_audio_channels(2) == "Stereo"

    def test_surround_51(self):
        assert format_audio_channels(6) == "5.1"

    def test_surround_71(self):
        assert format_audio_channels(8) == "7.1"

    def test_unusual_count(self):
        assert format_audio_channels(4) == "4ch"


class TestFormatDetails:
    def test_all_fields(self):
        meta = VideoMetadata(
            path=Path("/test.mp4"),
            filename="test",
            duration=60.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            codec="h264",
            bitrate=8_000_000,
            framerate=30.0,
            audio_channels=2,
        )
        result = _format_details(meta)
        assert "H.264" in result
        assert "8.0 Mbps" in result
        assert "30 fps" in result
        assert "Stereo" in result
        assert "\u00b7" in result  # middle dot separator

    def test_all_none(self):
        meta = VideoMetadata(
            path=Path("/test.mp4"),
            filename="test",
            duration=60.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        result = _format_details(meta)
        assert result == ""

    def test_partial_fields(self):
        meta = VideoMetadata(
            path=Path("/test.mp4"),
            filename="test",
            duration=60.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            codec="hevc",
            audio_channels=6,
        )
        result = _format_details(meta)
        assert "H.265" in result
        assert "5.1" in result
        assert "n/a" not in result


class TestPrintTable:
    def _capture(self, pairs, verbose=False):
        """Capture print_table output by monkeypatching Console."""
        buf = StringIO()

        from unittest.mock import patch
        from rich.console import Console as RealConsole

        # Patch Console in the reporter module so print_table uses our buffer
        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=200)
        ):
            print_table(pairs, verbose=verbose)

        return buf.getvalue()

    def test_empty_pairs_no_duplicates_message(self):
        output = self._capture([])
        assert "No duplicates found" in output

    def test_table_contains_filenames(self):
        pair = _make_pair("alpha.mp4", "beta.mp4", score=70.0)
        output = self._capture([pair])
        assert "alpha.mp4" in output
        assert "beta.mp4" in output

    def test_table_contains_scores(self):
        pair = _make_pair(score=82.5)
        output = self._capture([pair])
        assert "82.5" in output

    def test_table_contains_breakdown(self):
        pair = _make_pair(breakdown={"filename": 30.0, "duration": 35.0})
        output = self._capture([pair])
        assert "filename" in output
        assert "duration" in output

    def test_verbose_shows_full_paths(self):
        pair = _make_pair("movie_a.mp4", "movie_b.mp4", score=70.0)
        output = self._capture([pair], verbose=True)
        assert "/videos/movie_a.mp4" in output

    def test_non_verbose_shows_just_filename(self):
        pair = _make_pair("movie_a.mp4", "movie_b.mp4", score=70.0)
        output = self._capture([pair], verbose=False)
        assert "movie_a.mp4" in output
        # Full path should NOT appear
        assert "/videos/movie_a.mp4" not in output


class TestPrintTableTitle:
    def _capture(self, pairs, **kwargs):
        buf = StringIO()

        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=200)
        ):
            print_table(pairs, **kwargs)
        return buf.getvalue()

    def test_default_title(self):
        pair = _make_pair()
        output = self._capture([pair])
        assert "Potential Duplicate Videos" in output

    def test_custom_title(self):
        pair = _make_pair()
        output = self._capture([pair], title="Potential Duplicate Media")
        assert "Potential Duplicate Media" in output
        assert "Potential Duplicate Videos" not in output

    def test_image_title(self):
        pair = _make_pair()
        output = self._capture([pair], title="Potential Duplicate Images")
        assert "Potential Duplicate Images" in output


class TestPrintTableMetadataColumns:
    """Verify that the pair table includes codec/bitrate/framerate/audio columns in verbose mode."""

    def _capture(self, pairs, verbose=True):
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=300)
        ):
            print_table(pairs, verbose=verbose)
        return buf.getvalue()

    def test_metadata_columns_present_with_values(self):
        pair = _make_pair(
            a_codec="h264",
            b_codec="hevc",
            a_bitrate=8_000_000,
            b_bitrate=4_000_000,
            a_framerate=30.0,
            b_framerate=23.976,
            a_audio_channels=2,
            b_audio_channels=6,
        )
        output = self._capture([pair])
        assert "H.264" in output
        assert "H.265" in output
        assert "8.0 Mbps" in output
        assert "4.0 Mbps" in output
        assert "30 fps" in output
        assert "23.976 fps" in output
        assert "Stereo" in output
        assert "5.1" in output

    def test_metadata_columns_hidden_without_verbose(self):
        pair = _make_pair(
            a_codec="h264",
            b_codec="hevc",
            a_bitrate=8_000_000,
            b_bitrate=4_000_000,
        )
        output = self._capture([pair], verbose=False)
        assert "H.264" not in output
        assert "H.265" not in output
        assert "8.0 Mbps" not in output

    def test_metadata_columns_empty_when_missing(self):
        pair = _make_pair()  # all metadata fields None by default
        output = self._capture([pair])
        # When all metadata fields are None, details line is empty (not "n/a")
        assert "n/a" not in output

    def test_metadata_columns_mixed(self):
        pair = _make_pair(
            a_codec="h264",
            b_codec=None,
            a_bitrate=None,
            b_bitrate=128_000,
        )
        output = self._capture([pair])
        assert "H.264" in output
        assert "128 kbps" in output

    def test_ref_and_keep_markers_still_work_with_metadata(self):
        pair = _make_pair(
            a_is_ref=True,
            b_is_ref=False,
            a_file_size=2_000_000,
            b_file_size=1_000_000,
            a_codec="h264",
            b_codec="hevc",
        )
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=300)
        ):
            print_table([pair], verbose=True, keep_strategy="biggest")
        output = buf.getvalue()
        assert "[REF]" in output
        assert "KEEP" in output
        assert "H.264" in output
        assert "H.265" in output

    def test_verbose_full_paths_and_metadata_visible_at_80_cols(self):
        """Full paths, REF, KEEP, and metadata must survive at 80-col width."""
        pair = _make_pair(
            a_is_ref=True,
            b_is_ref=False,
            a_file_size=2_000_000,
            b_file_size=1_000_000,
            a_codec="h264",
            b_codec="hevc",
            a_bitrate=8_000_000,
            b_bitrate=4_000_000,
            a_framerate=30.0,
            b_framerate=23.976,
            a_audio_channels=2,
            b_audio_channels=6,
        )
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=80)
        ):
            print_table([pair], verbose=True, keep_strategy="biggest")
        output = buf.getvalue()
        # Full paths visible (fold, not truncate)
        assert "/videos/movie_a.mp4" in output
        assert "/videos/movie_b.mp4" in output
        assert "[REF]" in output
        assert "KEEP" in output
        # Metadata values visible in consolidated Details columns
        assert "H.264" in output
        assert "H.265" in output
        assert "8.0 Mbps" in output
        assert "Stereo" in output


class TestPrintTableToFile:
    def test_table_to_file_strips_ansi(self):
        pair = _make_pair()
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=False, width=300)
        ):
            print_table([pair], file=buf)
        content = buf.getvalue()
        assert "\x1b[" not in content
        assert "movie_a" in content

    def test_empty_pairs_to_file(self):
        buf = StringIO()
        print_table([], file=buf)
        content = buf.getvalue()
        assert "No duplicates found" in content


class TestWriteJson:
    def test_empty_pairs_returns_empty_array(self):
        import json

        buf = StringIO()
        write_json([], file=buf)
        assert json.loads(buf.getvalue()) == []

    def test_single_pair_structure(self):
        import json

        pair = _make_pair("alpha.mp4", "beta.mp4", score=75.0)
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert len(data) == 1
        record = data[0]
        assert record["file_a"] == "/videos/alpha.mp4"
        assert record["file_b"] == "/videos/beta.mp4"
        assert record["score"] == 75.0
        assert "filename" in record["breakdown"]

    def test_metadata_fields_present(self):
        import json

        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        fa = data[0]["file_a_metadata"]
        assert fa["duration"] == 120.0
        assert fa["width"] == 1920
        assert fa["height"] == 1080
        assert fa["file_size"] == 1_000_000
        assert fa["codec"] is None
        assert fa["bitrate"] is None
        assert fa["framerate"] is None
        assert fa["audio_channels"] is None

    def test_none_breakdown_becomes_null(self):
        import json

        pair = _make_pair(breakdown={"filename": 25.0, "duration": None})
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert data[0]["breakdown"]["duration"] is None

    def test_writes_to_stdout_when_no_file(self, capsys):
        import json

        pair = _make_pair()
        write_json([pair])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 1


class TestWriteCsv:
    def test_empty_pairs_headers_only(self):
        buf = StringIO()
        write_csv([], file=buf)
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 1
        assert "file_a" in lines[0]

    def test_single_pair_row(self):
        pair = _make_pair("alpha.mp4", "beta.mp4", score=75.0)
        buf = StringIO()
        write_csv([pair], file=buf)
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 2
        assert "/videos/alpha.mp4" in lines[1]
        assert "75.0" in lines[1]

    def test_none_breakdown_empty_field(self):
        import csv

        pair = _make_pair(
            breakdown={"filename": 25.0, "duration": None, "resolution": 10.0, "file_size": 10.0},
        )
        buf = StringIO()
        write_csv([pair], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        row = next(reader)
        dur_idx = header.index("duration")
        assert row[dur_idx] == ""

    def test_rfc4180_quoting_paths_with_commas(self):
        import csv

        pair = _make_pair("movie,part1.mp4", "movie_b.mp4")
        buf = StringIO()
        write_csv([pair], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        next(reader)  # skip header
        row = next(reader)
        assert "movie,part1" in row[0]

    def test_content_breakdown_column(self):
        import csv

        pair = _make_pair(
            breakdown={
                "filename": 15.0,
                "duration": 18.0,
                "resolution": 8.0,
                "file_size": 9.0,
                "content": 30.0,
            },
        )
        buf = StringIO()
        write_csv([pair], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "content" in header
        row = next(reader)
        content_idx = header.index("content")
        assert row[content_idx] == "30.0"


class TestWriteShell:
    def test_empty_pairs_header_and_no_duplicates(self):
        buf = StringIO()
        write_shell([], file=buf)
        content = buf.getvalue()
        assert content.startswith("#!/usr/bin/env bash")
        assert "No duplicates found" in content

    def test_single_pair_commented_rm(self):
        pair = _make_pair("alpha.mp4", "beta.mp4", score=75.0)
        buf = StringIO()
        write_shell([pair], file=buf)
        content = buf.getvalue()
        assert "# rm " in content
        assert "/videos/alpha.mp4" in content
        assert "/videos/beta.mp4" in content

    def test_paths_with_spaces_are_quoted(self):
        pair = _make_pair("my movie.mp4", "other movie.mp4")
        buf = StringIO()
        write_shell([pair], file=buf)
        content = buf.getvalue()
        assert "'/videos/my movie.mp4'" in content

    def test_score_in_comment(self):
        pair = _make_pair(score=92.5)
        buf = StringIO()
        write_shell([pair], file=buf)
        content = buf.getvalue()
        assert "# --- Score: 92.5 ---" in content


# ---------------------------------------------------------------------------
# reference markers in output formats
# ---------------------------------------------------------------------------


class TestReferenceMarkers:
    def _capture_table(self, pairs, verbose=False):
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=200)
        ):
            print_table(pairs, verbose=verbose)
        return buf.getvalue()

    def test_table_shows_ref_marker(self):
        pair = _make_pair("alpha.mp4", "beta.mp4", a_is_ref=True)
        output = self._capture_table([pair])
        assert "[REF]" in output

    def test_table_no_ref_marker_for_non_reference(self):
        pair = _make_pair("alpha.mp4", "beta.mp4")
        output = self._capture_table([pair])
        assert "[REF]" not in output

    def test_json_includes_reference_fields(self):
        import json

        pair = _make_pair("alpha.mp4", "beta.mp4", a_is_ref=True, b_is_ref=False)
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert data[0]["file_a_is_reference"] is True
        assert data[0]["file_b_is_reference"] is False

    def test_json_reference_fields_default_false(self):
        import json

        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert data[0]["file_a_is_reference"] is False
        assert data[0]["file_b_is_reference"] is False

    def test_csv_includes_reference_columns(self):
        import csv

        pair = _make_pair("alpha.mp4", "beta.mp4", a_is_ref=True, b_is_ref=False)
        buf = StringIO()
        write_csv([pair], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "file_a_is_reference" in header
        assert "file_b_is_reference" in header
        row = next(reader)
        a_ref_idx = header.index("file_a_is_reference")
        b_ref_idx = header.index("file_b_is_reference")
        assert row[a_ref_idx] == "true"
        assert row[b_ref_idx] == "false"

    def test_shell_reference_file_not_deletable(self):
        pair = _make_pair("alpha.mp4", "beta.mp4", a_is_ref=True, b_is_ref=False)
        buf = StringIO()
        write_shell([pair], file=buf)
        content = buf.getvalue()
        assert "reference" in content
        assert "do not delete" in content
        assert "/videos/alpha.mp4" in content
        # Non-reference file should have the normal rm line
        assert "# rm -- " in content
        assert "/videos/beta.mp4" in content


# ---------------------------------------------------------------------------
# keep strategy markers in output formats
# ---------------------------------------------------------------------------


class TestKeepMarkers:
    def _capture_table(self, pairs, keep_strategy=None, verbose=False):
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=200)
        ):
            print_table(pairs, verbose=verbose, keep_strategy=keep_strategy)
        return buf.getvalue()

    def test_table_shows_keep_marker(self):
        pair = _make_pair(a_file_size=2_000_000, b_file_size=1_000_000)
        output = self._capture_table([pair], keep_strategy="biggest")
        assert "KEEP" in output

    def test_table_no_keep_marker_without_strategy(self):
        pair = _make_pair()
        output = self._capture_table([pair])
        assert "KEEP" not in output

    def test_table_no_keep_marker_when_undecidable(self):
        pair = _make_pair(a_file_size=1_000_000, b_file_size=1_000_000)
        output = self._capture_table([pair], keep_strategy="biggest")
        assert "KEEP" not in output

    def test_json_includes_keep_field(self):
        import json

        pair = _make_pair(a_file_size=2_000_000, b_file_size=1_000_000)
        buf = StringIO()
        write_json([pair], file=buf, keep_strategy="biggest")
        data = json.loads(buf.getvalue())
        assert data[0]["keep"] == "a"

    def test_json_keep_null_when_undecidable(self):
        import json

        pair = _make_pair(a_file_size=1_000_000, b_file_size=1_000_000)
        buf = StringIO()
        write_json([pair], file=buf, keep_strategy="biggest")
        data = json.loads(buf.getvalue())
        assert data[0]["keep"] is None

    def test_json_no_keep_field_without_strategy(self):
        import json

        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert "keep" not in data[0]

    def test_csv_includes_keep_column(self):
        import csv

        pair = _make_pair(a_file_size=2_000_000, b_file_size=1_000_000)
        buf = StringIO()
        write_csv([pair], file=buf, keep_strategy="biggest")
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "keep" in header
        row = next(reader)
        keep_idx = header.index("keep")
        assert row[keep_idx] == "a"

    def test_csv_no_keep_column_without_strategy(self):
        import csv

        pair = _make_pair()
        buf = StringIO()
        write_csv([pair], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "keep" not in header

    def test_shell_uncomments_rm_for_delete_candidate(self):
        pair = _make_pair(a_file_size=2_000_000, b_file_size=1_000_000)
        buf = StringIO()
        write_shell([pair], file=buf, keep_strategy="biggest")
        content = buf.getvalue()
        lines = content.strip().split("\n")
        # The smaller file (b) should have an uncommented rm
        uncommented_rms = [l for l in lines if l.startswith("rm ")]
        assert len(uncommented_rms) == 1
        assert "movie_b.mp4" in uncommented_rms[0]

    def test_shell_both_commented_when_undecidable(self):
        pair = _make_pair(a_file_size=1_000_000, b_file_size=1_000_000)
        buf = StringIO()
        write_shell([pair], file=buf, keep_strategy="biggest")
        content = buf.getvalue()
        lines = content.strip().split("\n")
        uncommented_rms = [l for l in lines if l.startswith("rm ")]
        assert len(uncommented_rms) == 0

    def test_shell_reference_overrides_strategy(self):
        pair = _make_pair(a_is_ref=True, a_file_size=500_000, b_file_size=2_000_000)
        buf = StringIO()
        write_shell([pair], file=buf, keep_strategy="smallest")
        content = buf.getvalue()
        # Strategy says keep a (smallest), delete b — but a is reference
        # Reference annotation should still appear for a
        assert "reference" in content
        assert "do not delete" in content


# ---------------------------------------------------------------------------
# Group output format helpers
# ---------------------------------------------------------------------------


def _make_group_meta(
    name: str = "video.mp4",
    file_size: int = 1_000_000,
    duration: float | None = 120.0,
    width: int | None = 1920,
    height: int | None = 1080,
    is_reference: bool = False,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/videos/{name}"),
        filename=Path(name).stem,
        duration=duration,
        width=width,
        height=height,
        file_size=file_size,
        mtime=1_700_000_000.0,
        is_reference=is_reference,
    )


def _make_group(
    members: list[VideoMetadata] | None = None,
    pairs: list[ScoredPair] | None = None,
    group_id: int = 1,
) -> DuplicateGroup:
    if members is None:
        members = [
            _make_group_meta("alpha.mp4", file_size=2_000_000),
            _make_group_meta("beta.mp4", file_size=1_000_000),
        ]
    if pairs is None:
        # Build a single pair from the first two members
        pairs = [
            ScoredPair(
                file_a=members[0],
                file_b=members[1],
                total_score=75.0,
                breakdown={"filename": 25.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0},
                detail={},
            )
        ]
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
# Group output format tests
# ---------------------------------------------------------------------------


class TestPrintGroupTable:
    def _capture(self, groups, verbose=False, keep_strategy=None):
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=200)
        ):
            print_group_table(groups, verbose=verbose, keep_strategy=keep_strategy)
        return buf.getvalue()

    def test_empty_groups_no_duplicates_message(self):
        output = self._capture([])
        assert "No duplicates found" in output

    def test_single_group_shows_members(self):
        group = _make_group()
        output = self._capture([group])
        assert "alpha.mp4" in output
        assert "beta.mp4" in output

    def test_group_shows_score_range(self):
        group = _make_group()
        output = self._capture([group])
        assert "75.0" in output

    def test_verbose_shows_full_paths(self):
        group = _make_group()
        output = self._capture([group], verbose=True)
        assert "/videos/alpha.mp4" in output

    def test_reference_marker_shown(self):
        members = [
            _make_group_meta("alpha.mp4", is_reference=True),
            _make_group_meta("beta.mp4"),
        ]
        group = _make_group(members=members)
        output = self._capture([group])
        assert "[REF]" in output

    def test_keep_strategy_marks_keeper(self):
        members = [
            _make_group_meta("alpha.mp4", file_size=2_000_000),
            _make_group_meta("beta.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        output = self._capture([group], keep_strategy="biggest")
        assert "KEEP" in output


class TestWriteGroupJson:
    def test_empty_groups_empty_array(self):
        import json

        buf = StringIO()
        write_group_json([], file=buf)
        assert json.loads(buf.getvalue()) == []

    def test_single_group_structure(self):
        import json

        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        assert len(data) == 1
        record = data[0]
        assert record["group_id"] == 1
        assert record["file_count"] == 2
        assert record["max_score"] == 75.0
        assert len(record["files"]) == 2
        assert len(record["pairs"]) == 1

    def test_files_array_contents(self):
        import json

        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        f = data[0]["files"][0]
        assert "path" in f
        assert "duration" in f
        assert "file_size" in f
        assert "is_reference" in f
        assert "codec" in f
        assert "bitrate" in f
        assert "framerate" in f
        assert "audio_channels" in f

    def test_pairs_array_contents(self):
        import json

        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        p = data[0]["pairs"][0]
        assert "file_a" in p
        assert "file_b" in p
        assert "score" in p
        assert "breakdown" in p

    def test_keep_field_with_strategy(self):
        import json

        members = [
            _make_group_meta("alpha.mp4", file_size=2_000_000),
            _make_group_meta("beta.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        buf = StringIO()
        write_group_json([group], file=buf, keep_strategy="biggest")
        data = json.loads(buf.getvalue())
        assert data[0]["keep"] == "/videos/alpha.mp4"

    def test_no_keep_field_without_strategy(self):
        import json

        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        assert "keep" not in data[0]

    def test_reference_field_present(self):
        import json

        members = [
            _make_group_meta("alpha.mp4", is_reference=True),
            _make_group_meta("beta.mp4"),
        ]
        group = _make_group(members=members)
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        assert data[0]["files"][0]["is_reference"] is True
        assert data[0]["files"][1]["is_reference"] is False


class TestWriteGroupCsv:
    def test_empty_groups_header_only(self):
        buf = StringIO()
        write_group_csv([], file=buf)
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 1
        header = lines[0]
        assert "group_id" in header
        assert "codec" in header
        assert "bitrate" in header
        assert "framerate" in header
        assert "audio_channels" in header

    def test_single_group_rows(self):
        group = _make_group()
        buf = StringIO()
        write_group_csv([group], file=buf)
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 3  # header + 2 members

    def test_group_id_column(self):
        import csv

        group = _make_group()
        buf = StringIO()
        write_group_csv([group], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        row = next(reader)
        gid_idx = header.index("group_id")
        assert row[gid_idx] == "1"

    def test_keep_column_with_strategy(self):
        import csv

        members = [
            _make_group_meta("alpha.mp4", file_size=2_000_000),
            _make_group_meta("beta.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        buf = StringIO()
        write_group_csv([group], file=buf, keep_strategy="biggest")
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "keep" in header
        keep_idx = header.index("keep")
        row1 = next(reader)
        row2 = next(reader)
        # alpha has bigger size, should be "true"
        assert row1[keep_idx] == "true"
        assert row2[keep_idx] == "false"

    def test_no_keep_column_without_strategy(self):
        import csv

        group = _make_group()
        buf = StringIO()
        write_group_csv([group], file=buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "keep" not in header


class TestWriteGroupShell:
    def test_empty_groups_header_and_no_duplicates(self):
        buf = StringIO()
        write_group_shell([], file=buf)
        content = buf.getvalue()
        assert content.startswith("#!/usr/bin/env bash")
        assert "No duplicates found" in content

    def test_single_group_commented_rm(self):
        group = _make_group()
        buf = StringIO()
        write_group_shell([group], file=buf)
        content = buf.getvalue()
        assert "# rm " in content
        assert "Group 1" in content

    def test_reference_not_deletable(self):
        members = [
            _make_group_meta("alpha.mp4", is_reference=True),
            _make_group_meta("beta.mp4"),
        ]
        group = _make_group(members=members)
        buf = StringIO()
        write_group_shell([group], file=buf)
        content = buf.getvalue()
        assert "reference" in content
        assert "do not delete" in content

    def test_keep_strategy_marks_keeper(self):
        members = [
            _make_group_meta("alpha.mp4", file_size=2_000_000),
            _make_group_meta("beta.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        buf = StringIO()
        write_group_shell([group], file=buf, keep_strategy="biggest")
        content = buf.getvalue()
        assert "KEEP" in content
        # beta should have uncommented rm
        lines = content.strip().split("\n")
        uncommented_rms = [l for l in lines if l.startswith("rm ")]
        assert len(uncommented_rms) == 1
        assert "beta.mp4" in uncommented_rms[0]

    def test_paths_with_spaces_quoted(self):
        members = [
            _make_group_meta("my movie.mp4", file_size=2_000_000),
            _make_group_meta("other movie.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        buf = StringIO()
        write_group_shell([group], file=buf)
        content = buf.getvalue()
        assert "'/videos/my movie.mp4'" in content


# ---------------------------------------------------------------------------
# max_rows parameter in print_table
# ---------------------------------------------------------------------------


class TestPrintTableMaxRows:
    def _capture(self, pairs, max_rows=None, verbose=False):
        buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        with patch(
            "duplicates_detector.reporter.Console", lambda **kw: RealConsole(file=buf, force_terminal=True, width=200)
        ):
            print_table(pairs, verbose=verbose, max_rows=max_rows)
        return buf.getvalue()

    def test_max_rows_limits_display(self):
        pairs = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0 - i) for i in range(10)]
        output = self._capture(pairs, max_rows=3)
        assert "showing top 3" in output

    def test_max_rows_none_uses_default(self):
        pairs = [_make_pair()]
        output = self._capture(pairs, max_rows=None)
        assert "1 pair(s) found" in output

    def test_max_rows_larger_than_pairs(self):
        pairs = [_make_pair()]
        output = self._capture(pairs, max_rows=100)
        assert "1 pair(s) found" in output
        assert "showing" not in output


# ---------------------------------------------------------------------------
# dry_run_summary in JSON/shell output
# ---------------------------------------------------------------------------


class TestDryRunSummaryJson:
    def test_flat_array_without_summary(self):
        """Without dry_run_summary, JSON is a flat array (backward compat)."""
        import json

        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert isinstance(data, list)

    def test_wrapped_with_summary(self, tmp_path):
        """With dry_run_summary, JSON is wrapped with pairs + summary."""
        import json

        from duplicates_detector.advisor import DeletionSummary

        # Create a real file for stat()
        target = tmp_path / "b.mp4"
        target.write_bytes(b"x" * 500)

        summary = DeletionSummary(deleted=[target], skipped=0, errors=[], bytes_freed=500)
        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf, keep_strategy="biggest", dry_run_summary=summary)
        data = json.loads(buf.getvalue())
        assert "pairs" in data
        assert "dry_run_summary" in data
        assert data["dry_run_summary"]["total_files"] == 1
        assert data["dry_run_summary"]["strategy"] == "biggest"
        assert len(data["dry_run_summary"]["files_to_delete"]) == 1

    def test_empty_summary_stays_flat(self):
        """Empty deleted list keeps output as flat array."""
        import json

        from duplicates_detector.advisor import DeletionSummary

        summary = DeletionSummary(deleted=[], skipped=0, errors=[], bytes_freed=0)
        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf, dry_run_summary=summary)
        data = json.loads(buf.getvalue())
        assert isinstance(data, list)


class TestDryRunSummaryShell:
    def test_shell_summary_present(self, tmp_path):
        from duplicates_detector.advisor import DeletionSummary

        target = tmp_path / "b.mp4"
        target.write_bytes(b"x" * 500)

        summary = DeletionSummary(deleted=[target], skipped=0, errors=[], bytes_freed=500)
        pair = _make_pair()
        buf = StringIO()
        write_shell([pair], file=buf, keep_strategy="biggest", dry_run_summary=summary)
        content = buf.getvalue()
        assert "Dry Run Summary" in content
        assert "Files to delete: 1" in content
        assert "Run without --dry-run" in content

    def test_shell_no_summary_without_flag(self):
        pair = _make_pair()
        buf = StringIO()
        write_shell([pair], file=buf)
        content = buf.getvalue()
        assert "Dry Run Summary" not in content


class TestDryRunSummaryGroupJson:
    def test_wrapped_with_summary(self, tmp_path):
        import json

        from duplicates_detector.advisor import DeletionSummary

        target = tmp_path / "beta.mp4"
        target.write_bytes(b"x" * 1000)

        summary = DeletionSummary(deleted=[target], skipped=0, errors=[], bytes_freed=1000)
        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf, keep_strategy="biggest", dry_run_summary=summary)
        data = json.loads(buf.getvalue())
        assert "groups" in data
        assert "dry_run_summary" in data

    def test_flat_without_summary(self):
        import json

        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        assert isinstance(data, list)


class TestDryRunSummaryGroupShell:
    def test_summary_present(self, tmp_path):
        from duplicates_detector.advisor import DeletionSummary

        target = tmp_path / "beta.mp4"
        target.write_bytes(b"x" * 1000)

        summary = DeletionSummary(deleted=[target], skipped=0, errors=[], bytes_freed=1000)
        group = _make_group()
        buf = StringIO()
        write_group_shell([group], file=buf, keep_strategy="biggest", dry_run_summary=summary)
        content = buf.getvalue()
        assert "Dry Run Summary" in content

    def test_no_summary_without_flag(self):
        group = _make_group()
        buf = StringIO()
        write_group_shell([group], file=buf)
        content = buf.getvalue()
        assert "Dry Run Summary" not in content


# ---------------------------------------------------------------------------
# JSON envelope tests
# ---------------------------------------------------------------------------


class TestJsonEnvelope:
    def _envelope(self):
        return {
            "version": "1.0.0",
            "generated_at": "2026-03-01T00:00:00+00:00",
            "args": {"directories": ["/videos"], "threshold": 50},
            "stats": {"files_scanned": 10, "total_time": 1.5},
        }

    def test_envelope_structure_keys(self):
        """Envelope wraps pairs with expected top-level keys."""
        import json

        pair = _make_pair()
        env = self._envelope()
        buf = StringIO()
        write_json([pair], file=buf, envelope=env)
        data = json.loads(buf.getvalue())
        assert "version" in data
        assert "generated_at" in data
        assert "args" in data
        assert "stats" in data
        assert "pairs" in data

    def test_envelope_version_matches(self):
        import json

        pair = _make_pair()
        env = self._envelope()
        buf = StringIO()
        write_json([pair], file=buf, envelope=env)
        data = json.loads(buf.getvalue())
        assert data["version"] == "1.0.0"

    def test_envelope_generated_at_is_iso(self):
        import json
        from datetime import datetime

        pair = _make_pair()
        env = self._envelope()
        buf = StringIO()
        write_json([pair], file=buf, envelope=env)
        data = json.loads(buf.getvalue())
        # Should parse as ISO 8601 without error
        datetime.fromisoformat(data["generated_at"])

    def test_envelope_pairs_content_matches_non_envelope(self):
        """Pairs content is identical with and without envelope."""
        import json

        pair = _make_pair()
        env = self._envelope()

        buf_env = StringIO()
        write_json([pair], file=buf_env, envelope=env)
        data_env = json.loads(buf_env.getvalue())

        buf_flat = StringIO()
        write_json([pair], file=buf_flat)
        data_flat = json.loads(buf_flat.getvalue())

        assert data_env["pairs"] == data_flat

    def test_envelope_dry_run_summary_as_sibling(self, tmp_path):
        """dry_run_summary appears as sibling key in envelope."""
        import json
        from duplicates_detector.advisor import DeletionSummary

        target = tmp_path / "movie.mp4"
        target.write_bytes(b"x" * 500)
        summary = DeletionSummary(deleted=[target], skipped=0, errors=[], bytes_freed=500)

        pair = _make_pair()
        env = self._envelope()
        buf = StringIO()
        write_json([pair], file=buf, envelope=env, keep_strategy="biggest", dry_run_summary=summary)
        data = json.loads(buf.getvalue())
        assert "dry_run_summary" in data
        assert "pairs" in data
        assert "version" in data

    def test_no_envelope_backward_compatible(self):
        """Without envelope, output is a flat JSON array."""
        import json

        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert isinstance(data, list)

    def test_envelope_dry_run_absent_when_no_summary(self):
        """dry_run_summary key is absent from envelope when not provided."""
        import json

        pair = _make_pair()
        env = self._envelope()
        buf = StringIO()
        write_json([pair], file=buf, envelope=env)
        data = json.loads(buf.getvalue())
        assert "dry_run_summary" not in data


class TestGroupJsonEnvelope:
    def _envelope(self):
        return {
            "version": "1.0.0",
            "generated_at": "2026-03-01T00:00:00+00:00",
            "args": {"directories": ["/videos"], "threshold": 50},
            "stats": {"files_scanned": 10, "total_time": 1.5},
        }

    def test_uses_groups_key(self):
        """Group envelope uses 'groups' key instead of 'pairs'."""
        import json

        group = _make_group()
        env = self._envelope()
        buf = StringIO()
        write_group_json([group], file=buf, envelope=env)
        data = json.loads(buf.getvalue())
        assert "groups" in data
        assert "pairs" not in data
        assert "version" in data

    def test_dry_run_summary_as_sibling(self, tmp_path):
        """dry_run_summary in group envelope is a sibling of groups."""
        import json
        from duplicates_detector.advisor import DeletionSummary

        target = tmp_path / "beta.mp4"
        target.write_bytes(b"x" * 1000)
        summary = DeletionSummary(deleted=[target], skipped=0, errors=[], bytes_freed=1000)

        group = _make_group()
        env = self._envelope()
        buf = StringIO()
        write_group_json([group], file=buf, envelope=env, keep_strategy="biggest", dry_run_summary=summary)
        data = json.loads(buf.getvalue())
        assert "dry_run_summary" in data
        assert "groups" in data

    def test_no_envelope_flat_array(self):
        """Without envelope, group JSON is a flat array."""
        import json

        group = _make_group()
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Truncation warning tests
# ---------------------------------------------------------------------------


class TestTruncationWarning:
    def _capture_with_stderr(self, pairs, max_rows=None):
        """Capture both stdout and stderr from print_table."""
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        stderr_console = RealConsole(file=stderr_buf, no_color=True, width=200)

        with patch(
            "duplicates_detector.reporter.Console",
            side_effect=lambda **kw: (
                stderr_console if kw.get("stderr") else RealConsole(file=stdout_buf, force_terminal=True, width=200)
            ),
        ):
            displayed = print_table(pairs, max_rows=max_rows)

        return stdout_buf.getvalue(), stderr_buf.getvalue(), displayed

    def test_print_table_truncation_warning(self):
        """600 pairs → warning about truncation on stderr."""
        pairs = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0) for i in range(600)]
        _, stderr, displayed = self._capture_with_stderr(pairs)
        assert "Showing top 500 of 600 pairs" in stderr
        assert "--limit or --min-score" in stderr
        assert displayed == 500

    def test_print_table_no_warning_under_limit(self):
        """100 pairs → no truncation warning."""
        pairs = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0) for i in range(100)]
        _, stderr, displayed = self._capture_with_stderr(pairs)
        assert "Showing top" not in stderr
        assert displayed == 100

    def test_print_table_returns_displayed_count(self):
        """Return value matches number of displayed rows."""
        pairs_large = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0) for i in range(600)]
        _, _, displayed_large = self._capture_with_stderr(pairs_large)
        assert displayed_large == 500

        pairs_small = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0) for i in range(100)]
        _, _, displayed_small = self._capture_with_stderr(pairs_small)
        assert displayed_small == 100

    def test_print_table_custom_max_rows(self):
        """max_rows=10 with 20 pairs → returns 10, warns about truncation."""
        pairs = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0) for i in range(20)]
        _, stderr, displayed = self._capture_with_stderr(pairs, max_rows=10)
        assert displayed == 10
        assert "Showing top 10 of 20 pairs" in stderr

    def test_print_table_empty_returns_zero(self):
        """Empty pairs returns 0."""
        _, _, displayed = self._capture_with_stderr([])
        assert displayed == 0

    def test_print_table_quiet_suppresses_truncation_warning(self):
        """quiet=True suppresses the truncation warning on stderr."""
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        pairs = [_make_pair(f"a{i}.mp4", f"b{i}.mp4", score=75.0) for i in range(600)]
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        stderr_console = RealConsole(file=stderr_buf, no_color=True, width=200)
        with patch(
            "duplicates_detector.reporter.Console",
            side_effect=lambda **kw: (
                stderr_console if kw.get("stderr") else RealConsole(file=stdout_buf, force_terminal=True, width=200)
            ),
        ):
            displayed = print_table(pairs, quiet=True)
        assert displayed == 500
        assert "Showing top" not in stderr_buf.getvalue()


class TestGroupTruncationWarning:
    def _capture_with_stderr(self, groups, max_rows=None):
        """Capture both stdout and stderr from print_group_table."""
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        stderr_console = RealConsole(file=stderr_buf, no_color=True, width=200)

        with patch(
            "duplicates_detector.reporter.Console",
            side_effect=lambda **kw: (
                stderr_console if kw.get("stderr") else RealConsole(file=stdout_buf, force_terminal=True, width=200)
            ),
        ):
            displayed = print_group_table(groups, max_rows=max_rows)

        return stdout_buf.getvalue(), stderr_buf.getvalue(), displayed

    def test_print_group_table_truncation_warning(self):
        """More groups than _MAX_TABLE_ROWS → warning."""
        groups = [_make_group(group_id=i) for i in range(600)]
        _, stderr, displayed = self._capture_with_stderr(groups)
        assert "Showing top 500 of 600 groups" in stderr
        assert "--limit or --min-score" in stderr
        assert displayed == 500

    def test_print_group_table_header_counts_all_groups(self):
        """Header reports total files from all groups, not just displayed ones."""
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        groups = [_make_group(group_id=i) for i in range(600)]
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        stderr_console = RealConsole(file=stderr_buf, no_color=True, width=200)
        with patch(
            "duplicates_detector.reporter.Console",
            side_effect=lambda **kw: (
                stderr_console if kw.get("stderr") else RealConsole(file=stdout_buf, no_color=True, width=200)
            ),
        ):
            print_group_table(groups)
        stdout = stdout_buf.getvalue()
        # Each default group has 2 members → 600 * 2 = 1200 total files
        assert "600 group(s)" in stdout
        assert "1200 file(s)" in stdout
        assert "showing top 500" in stdout

    def test_print_group_table_no_warning_under_limit(self):
        """Few groups → no warning."""
        groups = [_make_group(group_id=i) for i in range(5)]
        _, stderr, displayed = self._capture_with_stderr(groups)
        assert "Showing top" not in stderr
        assert displayed == 5

    def test_print_group_table_returns_displayed_count(self):
        """Return value matches number of displayed groups."""
        groups = [_make_group(group_id=i) for i in range(600)]
        _, _, displayed = self._capture_with_stderr(groups)
        assert displayed == 500

    def test_print_group_table_empty_returns_zero(self):
        """Empty groups returns 0."""
        _, _, displayed = self._capture_with_stderr([])
        assert displayed == 0

    def test_print_group_table_quiet_suppresses_truncation_warning(self):
        """quiet=True suppresses the truncation warning on stderr."""
        from unittest.mock import patch
        from rich.console import Console as RealConsole

        groups = [_make_group(group_id=i) for i in range(600)]
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        stderr_console = RealConsole(file=stderr_buf, no_color=True, width=200)
        with patch(
            "duplicates_detector.reporter.Console",
            side_effect=lambda **kw: (
                stderr_console if kw.get("stderr") else RealConsole(file=stdout_buf, force_terminal=True, width=200)
            ),
        ):
            displayed = print_group_table(groups, quiet=True)
        assert displayed == 500
        assert "Showing top" not in stderr_buf.getvalue()


# ---------------------------------------------------------------------------
# Per-comparator detail diagnostics
# ---------------------------------------------------------------------------


class TestFormatBreakdownVerbose:
    def test_contains_multiplication_sign(self):
        pair = _make_pair(
            breakdown={"filename": 25.5, "duration": 30.0},
            detail={"filename": (0.85, 30.0), "duration": (1.0, 30.0)},
        )
        result = _format_breakdown_verbose(pair)
        assert "\u00d7" in result

    def test_raw_scores_and_weights(self):
        pair = _make_pair(
            breakdown={"filename": 25.5, "duration": 25.0},
            detail={"filename": (0.85, 30.0), "duration": (1.0, 25.0)},
        )
        result = _format_breakdown_verbose(pair)
        assert "0.85" in result
        assert "30" in result
        assert "25.5" in result

    def test_none_shows_na(self):
        pair = _make_pair(
            breakdown={"filename": 25.0, "duration": None},
            detail={"filename": (0.83, 30.0)},
        )
        result = _format_breakdown_verbose(pair)
        assert "duration: n/a" in result
        assert "filename: 0.83" in result

    def test_zero_raw_score(self):
        pair = _make_pair(
            breakdown={"filename": 0.0},
            detail={"filename": (0.0, 30.0)},
        )
        result = _format_breakdown_verbose(pair)
        assert "0.00" in result


class TestByteIdenticalBreakdown:
    def test_byte_identical_renders_in_table(self):
        """A pair with byte_identical breakdown renders correctly in table output."""
        pair = _make_pair(
            score=100.0,
            breakdown={"byte_identical": 100.0},
            detail={"byte_identical": (1.0, 100.0)},
        )
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        count = print_table([pair], file=output)
        text = output.getvalue()
        assert count == 1
        assert "byte_identical" in text
        assert "100" in text

    def test_byte_identical_verbose_breakdown(self):
        """byte_identical shows raw score and weight in verbose mode."""
        pair = _make_pair(
            score=100.0,
            breakdown={"byte_identical": 100.0},
            detail={"byte_identical": (1.0, 100.0)},
        )
        result = _format_breakdown_verbose(pair)
        assert "byte_identical" in result
        assert "1.00" in result
        assert "100" in result

    def test_byte_identical_json_output(self):
        """byte_identical appears in JSON output."""
        pair = _make_pair(
            score=100.0,
            breakdown={"byte_identical": 100.0},
            detail={"byte_identical": (1.0, 100.0)},
        )
        output = StringIO()
        write_json([pair], file=output)
        data = json.loads(output.getvalue())
        assert len(data) == 1
        assert data[0]["breakdown"]["byte_identical"] == 100.0
        assert data[0]["detail"]["byte_identical"] == [1.0, 100.0]

    def test_byte_identical_csv_output(self):
        """byte_identical appears as a column in CSV output."""
        pair = _make_pair(
            score=100.0,
            breakdown={"byte_identical": 100.0},
            detail={"byte_identical": (1.0, 100.0)},
        )
        output = StringIO()
        write_csv([pair], file=output)
        text = output.getvalue()
        assert "byte_identical" in text
        assert "100.0" in text


class TestPrintTableVerboseDetail:
    def test_verbose_shows_detail(self):
        pair = _make_pair(
            breakdown={"filename": 25.5, "duration": 30.0},
            detail={"filename": (0.85, 30.0), "duration": (1.0, 30.0)},
        )
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=200)
        print_table([pair], verbose=True, file=buf)
        output = buf.getvalue()
        assert "\u00d7" in output

    def test_non_verbose_unchanged(self):
        pair = _make_pair(
            breakdown={"filename": 25.5, "duration": 30.0},
            detail={"filename": (0.85, 30.0), "duration": (1.0, 30.0)},
        )
        buf = StringIO()
        print_table([pair], verbose=False, file=buf)
        output = buf.getvalue()
        assert "\u00d7" not in output


class TestJsonDetailOutput:
    def test_json_output_includes_detail(self):
        import json

        pair = _make_pair(
            breakdown={"filename": 25.5, "duration": 30.0},
            detail={"filename": (0.85, 30.0), "duration": (1.0, 30.0)},
        )
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert "detail" in data[0]
        assert data[0]["detail"]["filename"] == [0.85, 30.0]
        assert data[0]["detail"]["duration"] == [1.0, 30.0]

    def test_group_json_output_includes_detail(self):
        import json

        group = _make_group()
        # Override the pair detail for testing
        members = list(group.members)
        pair_with_detail = ScoredPair(
            file_a=members[0],
            file_b=members[1],
            total_score=75.0,
            breakdown={"filename": 25.0},
            detail={"filename": (0.83, 30.0)},
        )
        group = DuplicateGroup(
            group_id=1,
            members=tuple(members),
            pairs=(pair_with_detail,),
            max_score=75.0,
            min_score=75.0,
            avg_score=75.0,
        )
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        pair_data = data[0]["pairs"][0]
        assert "detail" in pair_data
        assert pair_data["detail"]["filename"] == [0.83, 30.0]


# ---------------------------------------------------------------------------
# _metadata_dict — mtime field
# ---------------------------------------------------------------------------


class TestMetadataDictMtime:
    def test_metadata_dict_includes_mtime(self):
        meta = VideoMetadata(
            path=Path("/videos/test.mp4"),
            filename="test",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            mtime=1_700_000_000.0,
        )
        d = _metadata_dict(meta)
        assert "mtime" in d
        assert d["mtime"] == 1_700_000_000.0

    def test_metadata_dict_mtime_none(self):
        meta = VideoMetadata(
            path=Path("/videos/test.mp4"),
            filename="test",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        d = _metadata_dict(meta)
        assert "mtime" in d
        assert d["mtime"] is None


# ---------------------------------------------------------------------------
# load_replay_json
# ---------------------------------------------------------------------------


def _make_envelope_pair_mode(pairs_data: list[dict], **envelope_kwargs) -> dict:
    """Build a minimal JSON envelope with pairs."""
    envelope = {
        "version": "1.0.0",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "args": {},
        "stats": {},
        "pairs": pairs_data,
    }
    envelope.update(envelope_kwargs)
    return envelope


def _make_pair_record(
    file_a: str = "/videos/a.mp4",
    file_b: str = "/videos/b.mp4",
    score: float = 85.0,
    *,
    breakdown: dict | None = None,
    detail: dict | None = None,
    a_meta: dict | None = None,
    b_meta: dict | None = None,
    a_is_ref: bool = False,
    b_is_ref: bool = False,
) -> dict:
    return {
        "file_a": file_a,
        "file_b": file_b,
        "score": score,
        "breakdown": breakdown or {"filename": 25.0, "duration": 30.0},
        "detail": detail or {"filename": [0.83, 30.0], "duration": [1.0, 30.0]},
        "file_a_metadata": a_meta
        or {"duration": 120.0, "width": 1920, "height": 1080, "file_size": 1_000_000, "mtime": 1_700_000_000.0},
        "file_b_metadata": b_meta
        or {"duration": 120.0, "width": 1920, "height": 1080, "file_size": 1_000_000, "mtime": 1_700_000_000.0},
        "file_a_is_reference": a_is_ref,
        "file_b_is_reference": b_is_ref,
    }


class TestLoadReplayJson:
    def test_load_pair_mode_envelope(self, tmp_path):
        rec = _make_pair_record()
        envelope = _make_envelope_pair_mode([rec])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert len(pairs) == 1
        assert pairs[0].total_score == 85.0
        assert pairs[0].file_a.path == Path("/videos/a.mp4")
        assert pairs[0].file_b.path == Path("/videos/b.mp4")
        assert pairs[0].file_a.duration == 120.0
        assert pairs[0].file_a.file_size == 1_000_000

    def test_load_group_mode_envelope(self, tmp_path):
        group_data = {
            "group_id": 1,
            "file_count": 2,
            "max_score": 85.0,
            "min_score": 85.0,
            "avg_score": 85.0,
            "files": [
                {
                    "path": "/videos/a.mp4",
                    "duration": 120.0,
                    "width": 1920,
                    "height": 1080,
                    "file_size": 1_000_000,
                    "mtime": 1_700_000_000.0,
                    "is_reference": False,
                },
                {
                    "path": "/videos/b.mp4",
                    "duration": 120.0,
                    "width": 1920,
                    "height": 1080,
                    "file_size": 1_000_000,
                    "mtime": 1_700_000_000.0,
                    "is_reference": True,
                },
            ],
            "pairs": [
                {
                    "file_a": "/videos/a.mp4",
                    "file_b": "/videos/b.mp4",
                    "score": 85.0,
                    "breakdown": {"filename": 25.0},
                    "detail": {"filename": [0.83, 30.0]},
                }
            ],
        }
        envelope = {
            "version": "1.0.0",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "args": {},
            "stats": {},
            "groups": [group_data],
        }
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert len(pairs) == 1
        assert pairs[0].total_score == 85.0
        assert pairs[0].file_b.is_reference is True

    def test_bare_array_raises(self, tmp_path):
        f = tmp_path / "replay.json"
        f.write_text(json.dumps([{"file_a": "a", "file_b": "b", "score": 50}]))

        with pytest.raises(ValueError, match="envelope"):
            load_replay_json(f)

    def test_no_pairs_or_groups_raises(self, tmp_path):
        f = tmp_path / "replay.json"
        f.write_text(json.dumps({"version": "1.0.0"}))

        with pytest.raises(ValueError, match="pairs.*groups"):
            load_replay_json(f)

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "replay.json"
        f.write_text("not valid json{{{")

        with pytest.raises(json.JSONDecodeError):
            load_replay_json(f)

    def test_empty_pairs(self, tmp_path):
        envelope = _make_envelope_pair_mode([])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert pairs == []

    def test_mtime_preserved(self, tmp_path):
        rec = _make_pair_record(a_meta={"file_size": 100, "mtime": 1_700_000_000.0})
        envelope = _make_envelope_pair_mode([rec])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert pairs[0].file_a.mtime == 1_700_000_000.0

    def test_missing_mtime_defaults_none(self, tmp_path):
        rec = _make_pair_record(a_meta={"file_size": 100, "duration": 60.0, "width": 1920, "height": 1080})
        envelope = _make_envelope_pair_mode([rec])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert pairs[0].file_a.mtime is None

    def test_is_reference_preserved(self, tmp_path):
        rec = _make_pair_record(a_is_ref=True)
        envelope = _make_envelope_pair_mode([rec])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert pairs[0].file_a.is_reference is True
        assert pairs[0].file_b.is_reference is False

    def test_detail_tuple_conversion(self, tmp_path):
        rec = _make_pair_record(detail={"filename": [0.83, 30.0], "duration": [1.0, 25.0]})
        envelope = _make_envelope_pair_mode([rec])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert pairs[0].detail["filename"] == (0.83, 30.0)
        assert pairs[0].detail["duration"] == (1.0, 25.0)

    def test_breakdown_preserved(self, tmp_path):
        rec = _make_pair_record(breakdown={"filename": 25.0, "duration": None})
        envelope = _make_envelope_pair_mode([rec])
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert pairs[0].breakdown["filename"] == 25.0
        assert pairs[0].breakdown["duration"] is None

    def test_group_deduplicates_shared_pairs(self, tmp_path):
        """Same pair appearing in multiple groups is only returned once."""
        pair_rec = {
            "file_a": "/videos/a.mp4",
            "file_b": "/videos/b.mp4",
            "score": 80.0,
            "breakdown": {"filename": 20.0},
            "detail": {"filename": [0.67, 30.0]},
        }
        files = [
            {"path": "/videos/a.mp4", "file_size": 100, "is_reference": False},
            {"path": "/videos/b.mp4", "file_size": 100, "is_reference": False},
        ]
        group = {
            "group_id": 1,
            "file_count": 2,
            "max_score": 80.0,
            "min_score": 80.0,
            "avg_score": 80.0,
            "files": files,
            "pairs": [pair_rec],
        }
        envelope = {
            "version": "1.0.0",
            "groups": [group, group],  # duplicated group
        }
        f = tmp_path / "replay.json"
        f.write_text(json.dumps(envelope))

        pairs = load_replay_json(f)
        assert len(pairs) == 1


# ---------------------------------------------------------------------------
# _metadata_dict — thumbnail embedding
# ---------------------------------------------------------------------------


class TestMetadataDictThumbnail:
    def _meta(self):
        return VideoMetadata(
            path=Path("/videos/test.mp4"),
            filename="test",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )

    def test_metadata_dict_without_thumbnail(self):
        d = _metadata_dict(self._meta())
        assert "thumbnail" not in d

    def test_metadata_dict_with_thumbnail_data_uri(self):
        d = _metadata_dict(self._meta(), thumbnail="data:image/jpeg;base64,abc")
        assert d["thumbnail"] == "data:image/jpeg;base64,abc"

    def test_metadata_dict_with_thumbnail_none(self):
        d = _metadata_dict(self._meta(), thumbnail=None)
        assert "thumbnail" in d
        assert d["thumbnail"] is None

    def test_metadata_dict_sentinel_omits_key(self):
        d = _metadata_dict(self._meta(), thumbnail=_THUMBNAIL_ABSENT)
        assert "thumbnail" not in d


class TestWriteJsonThumbnails:
    def test_write_json_with_thumbnails(self):
        pair = _make_pair("a.mp4", "b.mp4")
        thumbnails: dict[Path, str | None] = {
            pair.file_a.path.resolve(): "data:image/jpeg;base64,AAA",
            pair.file_b.path.resolve(): "data:image/jpeg;base64,BBB",
        }
        buf = StringIO()
        write_json([pair], file=buf, thumbnails=thumbnails)
        data = json.loads(buf.getvalue())
        assert data[0]["file_a_metadata"]["thumbnail"] == "data:image/jpeg;base64,AAA"
        assert data[0]["file_b_metadata"]["thumbnail"] == "data:image/jpeg;base64,BBB"

    def test_write_json_without_thumbnails(self):
        pair = _make_pair()
        buf = StringIO()
        write_json([pair], file=buf)
        data = json.loads(buf.getvalue())
        assert "thumbnail" not in data[0]["file_a_metadata"]

    def test_write_json_missing_file_thumbnail_is_null(self):
        pair = _make_pair("a.mp4", "b.mp4")
        thumbnails: dict[Path, str | None] = {
            pair.file_a.path.resolve(): "data:image/jpeg;base64,AAA",
            # file_b missing → should be None
        }
        buf = StringIO()
        write_json([pair], file=buf, thumbnails=thumbnails)
        data = json.loads(buf.getvalue())
        assert data[0]["file_a_metadata"]["thumbnail"] == "data:image/jpeg;base64,AAA"
        assert data[0]["file_b_metadata"]["thumbnail"] is None

    def test_write_group_json_with_thumbnails(self):
        meta_a = VideoMetadata(
            path=Path("/videos/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        meta_b = VideoMetadata(
            path=Path("/videos/b.mp4"),
            filename="b",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        pair = ScoredPair(
            file_a=meta_a,
            file_b=meta_b,
            total_score=80.0,
            breakdown={"filename": 30.0},
            detail={"filename": (0.8, 30.0)},
        )
        group = DuplicateGroup(
            group_id=1,
            members=(meta_a, meta_b),
            pairs=(pair,),
            max_score=80.0,
            min_score=80.0,
            avg_score=80.0,
        )
        thumbnails: dict[Path, str | None] = {
            meta_a.path.resolve(): "data:a",
            meta_b.path.resolve(): "data:b",
        }
        buf = StringIO()
        write_group_json([group], file=buf, thumbnails=thumbnails)
        data = json.loads(buf.getvalue())
        files = data[0]["files"]
        assert files[0]["thumbnail"] == "data:a"
        assert files[1]["thumbnail"] == "data:b"

    def test_write_group_json_without_thumbnails_no_key(self):
        meta = VideoMetadata(
            path=Path("/videos/a.mp4"),
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        pair = ScoredPair(
            file_a=meta,
            file_b=meta,
            total_score=80.0,
            breakdown={},
            detail={},
        )
        group = DuplicateGroup(
            group_id=1,
            members=(meta,),
            pairs=(pair,),
            max_score=80.0,
            min_score=80.0,
            avg_score=80.0,
        )
        buf = StringIO()
        write_group_json([group], file=buf)
        data = json.loads(buf.getvalue())
        assert "thumbnail" not in data[0]["files"][0]


# ---------------------------------------------------------------------------
# Sidecar display in table
# ---------------------------------------------------------------------------


class TestSidecarDisplay:
    def test_verbose_shows_sidecars(self):
        """Verbose table rendering shows sidecar filenames."""
        pair = ScoredPair(
            file_a=VideoMetadata(
                path=Path("/videos/a.jpg"),
                filename="a",
                duration=None,
                width=1920,
                height=1080,
                file_size=1_000_000,
                sidecars=(Path("/videos/a.xmp"), Path("/videos/a.aae")),
            ),
            file_b=VideoMetadata(
                path=Path("/videos/b.jpg"),
                filename="b",
                duration=None,
                width=1920,
                height=1080,
                file_size=1_000_000,
            ),
            total_score=80.0,
            breakdown={"filename": 30.0},
            detail={},
        )
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=200)
        print_table([pair], verbose=True, file=buf)
        output = buf.getvalue()
        assert "Sidecars:" in output
        assert "a.xmp" in output
        assert "a.aae" in output

    def test_non_verbose_no_sidecars_shown(self):
        """Non-verbose table rendering does not show sidecars."""
        pair = ScoredPair(
            file_a=VideoMetadata(
                path=Path("/videos/a.jpg"),
                filename="a",
                duration=None,
                width=1920,
                height=1080,
                file_size=1_000_000,
                sidecars=(Path("/videos/a.xmp"),),
            ),
            file_b=VideoMetadata(
                path=Path("/videos/b.jpg"),
                filename="b",
                duration=None,
                width=1920,
                height=1080,
                file_size=1_000_000,
            ),
            total_score=80.0,
            breakdown={"filename": 30.0},
            detail={},
        )
        buf = StringIO()
        print_table([pair], verbose=False, file=buf)
        output = buf.getvalue()
        assert "Sidecars:" not in output


# ---------------------------------------------------------------------------
# _metadata_dict / _reconstruct_metadata — document fields
# ---------------------------------------------------------------------------


class TestDocumentMetadataDict:
    def test_metadata_dict_includes_document_fields_when_present(self):
        meta = VideoMetadata(
            path=Path("/docs/report.pdf"),
            filename="report",
            duration=None,
            width=None,
            height=None,
            file_size=500_000,
            page_count=42,
            doc_title="my report",
            doc_author="jane doe",
            doc_created="2024-01-15T10:30:00",
        )
        d = _metadata_dict(meta)
        assert d["page_count"] == 42
        assert d["doc_title"] == "my report"
        assert d["doc_author"] == "jane doe"
        assert d["doc_created"] == "2024-01-15T10:30:00"

    def test_metadata_dict_excludes_document_fields_when_none(self):
        meta = VideoMetadata(
            path=Path("/videos/movie.mp4"),
            filename="movie",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        d = _metadata_dict(meta)
        assert "page_count" not in d
        assert "doc_title" not in d
        assert "doc_author" not in d
        assert "doc_created" not in d

    def test_metadata_dict_partial_document_fields(self):
        """Only non-None document fields are included."""
        meta = VideoMetadata(
            path=Path("/docs/report.pdf"),
            filename="report",
            duration=None,
            width=None,
            height=None,
            file_size=500_000,
            page_count=10,
            doc_author="john",
        )
        d = _metadata_dict(meta)
        assert d["page_count"] == 10
        assert d["doc_author"] == "john"
        assert "doc_title" not in d
        assert "doc_created" not in d

    def test_reconstruct_metadata_with_document_fields(self):
        meta_dict = {
            "duration": None,
            "width": None,
            "height": None,
            "file_size": 500_000,
            "page_count": 42,
            "doc_title": "my report",
            "doc_author": "jane doe",
            "doc_created": "2024-01-15T10:30:00",
        }
        result = _reconstruct_metadata("/docs/report.pdf", meta_dict)
        assert result.page_count == 42
        assert result.doc_title == "my report"
        assert result.doc_author == "jane doe"
        assert result.doc_created == "2024-01-15T10:30:00"

    def test_reconstruct_metadata_without_document_fields(self):
        meta_dict = {
            "duration": 120.0,
            "width": 1920,
            "height": 1080,
            "file_size": 1_000_000,
        }
        result = _reconstruct_metadata("/videos/movie.mp4", meta_dict)
        assert result.page_count is None
        assert result.doc_title is None
        assert result.doc_author is None
        assert result.doc_created is None
