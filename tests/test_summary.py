from __future__ import annotations

from io import StringIO

from rich.console import Console

from duplicates_detector.summary import (
    PipelineStats,
    _cache_rate,
    _format_time,
    print_summary,
)


class TestFormatTime:
    def test_milliseconds(self):
        assert _format_time(0.05) == "50ms"

    def test_zero(self):
        assert _format_time(0.0) == "0ms"

    def test_sub_second(self):
        assert _format_time(0.999) == "999ms"

    def test_seconds(self):
        assert _format_time(1.0) == "1.0s"

    def test_seconds_decimal(self):
        assert _format_time(12.3) == "12.3s"

    def test_boundary_one_second(self):
        assert _format_time(1.0) == "1.0s"

    def test_minutes(self):
        assert _format_time(90.0) == "1m30s"

    def test_exact_minute(self):
        assert _format_time(60.0) == "1m0s"


class TestCacheRate:
    def test_all_hits(self):
        assert _cache_rate(10, 0) == "100%"

    def test_no_hits(self):
        assert _cache_rate(0, 10) == "0%"

    def test_mixed(self):
        assert _cache_rate(3, 7) == "30%"

    def test_no_total(self):
        assert _cache_rate(0, 0) == "n/a"


def _capture_summary(stats: PipelineStats) -> str:
    """Render summary and return the captured text."""
    buf = StringIO()
    console = Console(file=buf, highlight=False, width=120)
    print_summary(stats, console=console)
    return buf.getvalue()


class TestPrintSummary:
    def test_basic(self):
        stats = PipelineStats(
            files_scanned=100,
            files_after_filter=100,
            pairs_above_threshold=5,
            total_pairs_scored=200,
            total_time=1.5,
        )
        output = _capture_summary(stats)
        assert "100 files scanned" in output
        assert "200 pairs scored" in output
        assert "5 duplicates" in output

    def test_filtered_and_failed(self):
        stats = PipelineStats(
            files_scanned=100,
            files_after_filter=80,
            extraction_failures=5,
            total_pairs_scored=50,
        )
        output = _capture_summary(stats)
        assert "15 filtered" in output
        assert "5 failed" in output

    def test_no_filtered_no_failed(self):
        stats = PipelineStats(
            files_scanned=50,
            files_after_filter=50,
            extraction_failures=0,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "filtered" not in output
        assert "failed" not in output

    def test_groups_shown(self):
        stats = PipelineStats(
            files_scanned=50,
            files_after_filter=50,
            groups_count=3,
            pairs_above_threshold=5,
            total_pairs_scored=100,
        )
        output = _capture_summary(stats)
        assert "3 groups" in output

    def test_groups_hidden_when_none(self):
        stats = PipelineStats(
            files_scanned=50,
            files_after_filter=50,
            groups_count=None,
            total_pairs_scored=100,
        )
        output = _capture_summary(stats)
        assert "groups" not in output

    def test_space_recoverable_shown(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            space_recoverable=5 * 1024 * 1024,
            pairs_above_threshold=2,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "5.0 MB" in output
        assert "recoverable" in output

    def test_space_recoverable_hidden_when_zero(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            space_recoverable=0,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "recoverable" not in output

    def test_content_mode_cache(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            content_mode=True,
            content_cache_enabled=True,
            content_cache_hits=8,
            content_cache_misses=2,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "80% content" in output

    def test_content_mode_hidden_when_disabled(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            content_mode=False,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "content" not in output.split("Time:")[0]  # "content" may appear in timing line

    def test_metadata_cache_disabled(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            metadata_cache_enabled=False,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "Cache" not in output

    def test_timing_shown(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            scan_time=0.3,
            extract_time=1.2,
            scoring_time=0.4,
            total_time=2.0,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "scan 300ms" in output
        assert "metadata 1.2s" in output
        assert "scoring 400ms" in output
        assert "2.0s total" in output

    def test_content_timing_shown_in_content_mode(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            content_mode=True,
            content_hash_time=5.0,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        assert "content 5.0s" in output

    def test_content_timing_hidden_without_content_mode(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            content_mode=False,
            total_pairs_scored=10,
        )
        output = _capture_summary(stats)
        # "content" should not appear in the timing line
        time_line = [line for line in output.split("\n") if "Time:" in line]
        assert time_line
        assert "content" not in time_line[0]

    def test_summary_title(self):
        stats = PipelineStats(files_scanned=10, files_after_filter=10, total_pairs_scored=10)
        output = _capture_summary(stats)
        assert "Summary" in output

    def test_display_limit_shown(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=100,
            pairs_above_threshold=20,
            display_limit=5,
        )
        output = _capture_summary(stats)
        assert "showing 5" in output

    def test_display_limit_hidden_when_none(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=100,
            pairs_above_threshold=5,
            display_limit=None,
        )
        output = _capture_summary(stats)
        assert "showing" not in output

    def test_display_limit_hidden_when_larger_than_actual(self):
        """No 'showing' notice when limit >= actual count."""
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=100,
            pairs_above_threshold=5,
            display_limit=10,
        )
        output = _capture_summary(stats)
        assert "showing" not in output

    def test_display_limit_with_groups(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=100,
            pairs_above_threshold=20,
            groups_count=10,
            display_limit=3,
        )
        output = _capture_summary(stats)
        assert "showing 3" in output

    def test_min_score_shown_in_summary(self):
        stats = PipelineStats(
            files_scanned=100,
            files_after_filter=100,
            total_pairs_scored=1000,
            pairs_above_threshold=50,
            pairs_after_min_score=20,
        )
        output = _capture_summary(stats)
        assert "50 duplicates" in output
        assert "20 above min-score" in output

    def test_min_score_not_shown_when_none(self):
        stats = PipelineStats(
            files_scanned=100,
            files_after_filter=100,
            total_pairs_scored=1000,
            pairs_above_threshold=50,
            pairs_after_min_score=None,
        )
        output = _capture_summary(stats)
        assert "above min-score" not in output

    def test_min_score_not_shown_when_same_as_threshold(self):
        stats = PipelineStats(
            files_scanned=100,
            files_after_filter=100,
            total_pairs_scored=1000,
            pairs_above_threshold=50,
            pairs_after_min_score=50,
        )
        output = _capture_summary(stats)
        assert "above min-score" not in output

    def test_summary_shows_truncation_with_total(self):
        stats = PipelineStats(
            files_scanned=100,
            files_after_filter=100,
            total_pairs_scored=10000,
            pairs_above_threshold=1234,
            display_limit=500,
            total_result_count=1234,
        )
        output = _capture_summary(stats)
        assert "showing 500 of 1,234" in output

    def test_summary_no_total_result_count(self):
        """display_limit without total_result_count uses existing format."""
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=100,
            pairs_above_threshold=20,
            display_limit=5,
            total_result_count=None,
        )
        output = _capture_summary(stats)
        assert "showing 5)" in output
        assert " of " not in output.split("showing")[1].split(")")[0]


# ---------------------------------------------------------------------------
# Sidecar stats
# ---------------------------------------------------------------------------


class TestSidecarStats:
    def test_sidecar_fields_default_zero(self):
        stats = PipelineStats()
        assert stats.sidecars_deleted == 0
        assert stats.sidecar_bytes_freed == 0

    def test_sidecars_shown_when_nonzero(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=5,
            pairs_above_threshold=3,
            sidecars_deleted=4,
            sidecar_bytes_freed=1024,
        )
        output = _capture_summary(stats)
        assert "4 sidecar(s) deleted" in output
        assert "1.0 KB" in output

    def test_sidecars_hidden_when_zero(self):
        stats = PipelineStats(
            files_scanned=10,
            files_after_filter=10,
            total_pairs_scored=5,
            pairs_above_threshold=3,
        )
        output = _capture_summary(stats)
        assert "sidecar" not in output
