from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.html_report import (
    _escape,
    _generate_all_thumbnails,
    _html_analytics_dashboard,
    _html_foot,
    _html_head,
    _html_summary_dashboard,
    _load_resource,
    _score_css_class,
    _thumbnail_placeholder,
    write_group_html,
    write_html,
)
from duplicates_detector.thumbnails import (
    generate_image_thumbnail as _generate_image_thumbnail,
    generate_video_thumbnail as _generate_video_thumbnail,
)
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.summary import PipelineStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(
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
) -> ScoredPair:
    if breakdown is None:
        breakdown = {"filename": 25.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}
    if detail is None:
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
        ),
        file_b=VideoMetadata(
            path=Path(f"/videos/{path_b}"),
            filename=Path(path_b).stem,
            duration=b_duration,
            width=1920,
            height=1080,
            file_size=b_file_size,
            is_reference=b_is_ref,
        ),
        total_score=score,
        breakdown=breakdown,
        detail=detail,
    )


def _make_group(
    members: list[VideoMetadata] | None = None,
    pairs: list[ScoredPair] | None = None,
    group_id: int = 1,
) -> DuplicateGroup:
    if members is None:
        members = [
            _make_meta("alpha.mp4", file_size=2_000_000),
            _make_meta("beta.mp4", file_size=1_000_000),
        ]
    if pairs is None:
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
# _score_css_class
# ---------------------------------------------------------------------------


class TestScoreCssClass:
    def test_high_score(self):
        assert _score_css_class(90.0) == "score-high"

    def test_boundary_80(self):
        assert _score_css_class(80.0) == "score-high"

    def test_medium_score(self):
        assert _score_css_class(70.0) == "score-med"

    def test_boundary_60(self):
        assert _score_css_class(60.0) == "score-med"

    def test_low_score(self):
        assert _score_css_class(50.0) == "score-low"


# ---------------------------------------------------------------------------
# _escape
# ---------------------------------------------------------------------------


class TestEscape:
    def test_html_entities(self):
        assert "&lt;script&gt;" in _escape("<script>")

    def test_quotes(self):
        result = _escape('a "quoted" value')
        assert "&quot;" in result

    def test_ampersand(self):
        assert "&amp;" in _escape("a & b")

    def test_path_with_special_chars(self):
        result = _escape('/path/<dir>&"file".mp4')
        assert "<" not in result
        assert ">" not in result
        assert "&lt;" in result


# ---------------------------------------------------------------------------
# Thumbnail generation
# ---------------------------------------------------------------------------


class TestGenerateImageThumbnail:
    def test_generates_jpeg_thumbnail(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (200, 200), color="red")
        path = tmp_path / "test.jpg"
        img.save(path)

        result = _generate_image_thumbnail(path)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_thumbnail_max_dimensions(self, tmp_path):
        import base64
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (500, 300), color="blue")
        path = tmp_path / "wide.png"
        img.save(path)

        result = _generate_image_thumbnail(path)
        assert result is not None
        b64_data = result.split(",", 1)[1]
        thumb = Image.open(BytesIO(base64.b64decode(b64_data)))
        assert thumb.width <= 160
        assert thumb.height <= 160

    def test_rgba_image_converts_to_rgb(self, tmp_path):
        from PIL import Image

        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        path = tmp_path / "rgba.png"
        img.save(path)

        result = _generate_image_thumbnail(path)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_corrupt_image_returns_none(self, tmp_path):
        path = tmp_path / "corrupt.jpg"
        path.write_bytes(b"not an image")

        result = _generate_image_thumbnail(path)
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        result = _generate_image_thumbnail(tmp_path / "nonexistent.jpg")
        assert result is None


class TestGenerateVideoThumbnail:
    def test_generates_thumbnail_from_video(self):
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_jpeg

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result):
            result = _generate_video_thumbnail(Path("/test/video.mp4"), duration=100.0)

        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_ffmpeg_failure_returns_none(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = b""

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result):
            result = _generate_video_thumbnail(Path("/test/video.mp4"), duration=100.0)

        assert result is None

    def test_timeout_returns_none(self):
        with patch(
            "duplicates_detector.thumbnails.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=15),
        ):
            result = _generate_video_thumbnail(Path("/test/video.mp4"), duration=100.0)

        assert result is None

    def test_seek_position_at_10_percent(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"\xff\xd8\xff\xe0"

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            _generate_video_thumbnail(Path("/test/video.mp4"), duration=200.0)

        call_args = mock_run.call_args[0][0]
        ss_idx = call_args.index("-ss")
        assert float(call_args[ss_idx + 1]) == pytest.approx(20.0)

    def test_zero_duration_seeks_to_zero(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"\xff\xd8\xff\xe0"

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            _generate_video_thumbnail(Path("/test/video.mp4"), duration=0.0)

        call_args = mock_run.call_args[0][0]
        ss_idx = call_args.index("-ss")
        assert float(call_args[ss_idx + 1]) == 0.0

    def test_none_duration_seeks_to_zero(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"\xff\xd8\xff\xe0"

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            _generate_video_thumbnail(Path("/test/video.mp4"), duration=None)

        call_args = mock_run.call_args[0][0]
        ss_idx = call_args.index("-ss")
        assert float(call_args[ss_idx + 1]) == 0.0


class TestThumbnailPlaceholder:
    def test_returns_data_uri_with_extension(self):
        result = _thumbnail_placeholder(".mp4")
        assert result.startswith("data:image/svg+xml;base64,")

    def test_html_escapes_extension(self):
        import base64

        result = _thumbnail_placeholder('.<script>"')
        b64 = result.split(",", 1)[1]
        svg = base64.b64decode(b64).decode("utf-8")
        assert "<script>" not in svg
        assert "&lt;SCRIPT&gt;" in svg or "&lt;SCRIPT&gt;&quot;" in svg


class TestGenerateAllThumbnails:
    def test_deduplicates_paths(self):
        meta_a = _make_meta("same.mp4")
        meta_b = _make_meta("same.mp4")

        with patch(
            "duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:image/jpeg;base64,fake"
        ) as mock_gen:
            _generate_all_thumbnails([meta_a, meta_b], mode="video", quiet=True)

        assert mock_gen.call_count == 1

    def test_image_mode_uses_pil(self):
        meta = _make_meta("photo.jpg")

        with (
            patch("duplicates_detector.thumbnails.generate_image_thumbnail", return_value="data:ok") as mock_img,
            patch("duplicates_detector.thumbnails.generate_video_thumbnail") as mock_vid,
        ):
            _generate_all_thumbnails([meta], mode="image", quiet=True)

        mock_img.assert_called_once()
        mock_vid.assert_not_called()

    def test_video_mode_uses_ffmpeg(self):
        meta = _make_meta("clip.mp4")

        with (
            patch("duplicates_detector.thumbnails.generate_image_thumbnail") as mock_img,
            patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:ok") as mock_vid,
        ):
            _generate_all_thumbnails([meta], mode="video", quiet=True)

        mock_vid.assert_called_once()
        mock_img.assert_not_called()


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


class TestHtmlHead:
    def test_contains_doctype(self):
        result = _html_head("Test Title")
        assert "<!DOCTYPE html>" in result

    def test_contains_title(self):
        result = _html_head("My Report")
        assert "<title>My Report</title>" in result

    def test_contains_style(self):
        result = _html_head("Test")
        assert "<style>" in result

    def test_title_is_escaped(self):
        result = _html_head('<script>alert("xss")</script>')
        assert "<script>alert" not in result
        assert "&lt;script&gt;" in result


class TestHtmlFoot:
    def test_contains_script(self):
        result = _html_foot()
        assert "<script>" in result

    def test_contains_closing_tags(self):
        result = _html_foot()
        assert "</body>" in result
        assert "</html>" in result

    def test_contains_footer(self):
        result = _html_foot()
        assert "duplicates-detector" in result


class TestHtmlSummaryDashboard:
    def test_with_stats(self):
        stats = PipelineStats(files_scanned=100, space_recoverable=5_000_000)
        result = _html_summary_dashboard(stats, pair_count=10, mode="video")
        assert "100" in result
        assert "10" in result
        assert "video" in result

    def test_without_stats(self):
        result = _html_summary_dashboard(None, pair_count=5, mode="image")
        assert "5" in result
        assert "image" in result

    def test_with_groups(self):
        result = _html_summary_dashboard(None, pair_count=0, group_count=3, mode="video")
        assert "Groups" in result
        assert "3" in result

    def test_space_recoverable(self):
        stats = PipelineStats(space_recoverable=1_073_741_824)
        result = _html_summary_dashboard(stats, pair_count=1, mode="video")
        assert "recoverable" in result.lower() or "Space" in result


# ---------------------------------------------------------------------------
# write_html (pair mode)
# ---------------------------------------------------------------------------


class TestWriteHtml:
    def _render(self, pairs=None, **kwargs):
        if pairs is None:
            pairs = [_make_pair()]
        buf = StringIO()
        # Patch thumbnail generation to avoid real I/O
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            write_html(pairs, file=buf, quiet=True, **kwargs)
        return buf.getvalue()

    def test_output_is_valid_html(self):
        html_str = self._render()
        assert html_str.startswith("<!DOCTYPE html>")
        assert "</html>" in html_str

    def test_empty_pairs_generates_valid_html(self):
        html_str = self._render(pairs=[])
        assert "<!DOCTYPE html>" in html_str
        assert "No duplicates found" in html_str
        assert "</html>" in html_str

    def test_contains_pair_table(self):
        html_str = self._render()
        assert "<table>" in html_str
        assert "<tbody>" in html_str

    def test_score_color_coding_high(self):
        pair = _make_pair(score=90.0)
        html_str = self._render(pairs=[pair])
        assert "score-high" in html_str

    def test_score_color_coding_medium(self):
        pair = _make_pair(score=65.0)
        html_str = self._render(pairs=[pair])
        assert "score-med" in html_str

    def test_score_color_coding_low(self):
        pair = _make_pair(score=40.0)
        html_str = self._render(pairs=[pair])
        assert "score-low" in html_str

    def test_file_paths_are_escaped(self):
        pair = _make_pair(path_a='<script>alert("xss")</script>.mp4')
        html_str = self._render(pairs=[pair])
        assert "<script>alert" not in html_str
        assert "&lt;script&gt;" in html_str

    def test_metadata_columns_present(self):
        html_str = self._render()
        assert "Size A" in html_str
        assert "Resolution A" in html_str

    def test_duration_hidden_in_image_mode(self):
        html_str = self._render(mode="image")
        assert "Duration A" not in html_str
        assert "Duration B" not in html_str

    def test_duration_shown_in_video_mode(self):
        html_str = self._render(mode="video")
        assert "Duration A" in html_str

    def test_keep_recommendation_shown(self):
        pair = _make_pair(a_file_size=2_000_000, b_file_size=1_000_000)
        html_str = self._render(pairs=[pair], keep_strategy="biggest")
        assert "KEEP" in html_str

    def test_reference_badge_shown(self):
        pair = _make_pair(a_is_ref=True)
        html_str = self._render(pairs=[pair])
        assert "REF" in html_str

    def test_breakdown_shown_in_verbose(self):
        html_str = self._render(verbose=True)
        assert "filename" in html_str.lower()

    def test_inline_css(self):
        html_str = self._render()
        assert "<style>" in html_str
        assert "score-high" in html_str

    def test_inline_js(self):
        html_str = self._render()
        assert "<script>" in html_str
        assert "sortable" in html_str

    def test_no_external_references(self):
        html_str = self._render()
        assert 'href="http' not in html_str
        assert 'src="http' not in html_str

    def test_writes_to_file(self, tmp_path):
        outfile = tmp_path / "report.html"
        with open(outfile, "w") as f:
            with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
                write_html([_make_pair()], file=f, quiet=True)
        content = outfile.read_text()
        assert "<!DOCTYPE html>" in content
        assert "</html>" in content

    def test_writes_to_stdout(self):
        buf = StringIO()
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            with patch("duplicates_detector.html_report.sys.stdout", buf):
                write_html([_make_pair()], quiet=True)
        assert "<!DOCTYPE html>" in buf.getvalue()

    def test_dry_run_summary_section(self):
        from duplicates_detector.advisor import DeletionSummary

        summary = DeletionSummary(
            deleted=[Path("/videos/movie_b.mp4")],
            skipped=0,
            errors=[],
            bytes_freed=1_000_000,
        )
        html_str = self._render(dry_run_summary=summary)
        assert "dry-run" in html_str.lower() or "Dry-run" in html_str

    def test_stats_dashboard(self):
        stats = PipelineStats(files_scanned=50, pairs_above_threshold=5)
        html_str = self._render(stats=stats)
        assert "50" in html_str

    def test_sortable_data_attributes(self):
        html_str = self._render()
        assert "data-sort-value" in html_str


# ---------------------------------------------------------------------------
# write_group_html
# ---------------------------------------------------------------------------


class TestWriteGroupHtml:
    def _render(self, groups=None, **kwargs):
        if groups is None:
            groups = [_make_group()]
        buf = StringIO()
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            write_group_html(groups, file=buf, quiet=True, **kwargs)
        return buf.getvalue()

    def test_output_is_valid_html(self):
        html_str = self._render()
        assert html_str.startswith("<!DOCTYPE html>")
        assert "</html>" in html_str

    def test_empty_groups_generates_valid_html(self):
        html_str = self._render(groups=[])
        assert "No duplicates found" in html_str
        assert "</html>" in html_str

    def test_groups_as_collapsible_sections(self):
        html_str = self._render()
        assert "<details" in html_str
        assert "<summary>" in html_str

    def test_group_header_info(self):
        html_str = self._render()
        assert "Group 1" in html_str
        assert "2 files" in html_str

    def test_group_member_data(self):
        html_str = self._render()
        assert "alpha" in html_str
        assert "beta" in html_str

    def test_keep_recommendation_in_group(self):
        members = [
            _make_meta("big.mp4", file_size=3_000_000),
            _make_meta("small.mp4", file_size=1_000_000),
        ]
        group = _make_group(members=members)
        html_str = self._render(groups=[group], keep_strategy="biggest")
        assert "KEEP" in html_str

    def test_multiple_groups(self):
        g1 = _make_group(group_id=1)
        g2 = _make_group(
            members=[
                _make_meta("gamma.mp4", file_size=1_500_000),
                _make_meta("delta.mp4", file_size=1_200_000),
            ],
            group_id=2,
        )
        html_str = self._render(groups=[g1, g2])
        assert "Group 1" in html_str
        assert "Group 2" in html_str
        assert html_str.count("<details") == 2

    def test_first_group_open_by_default(self):
        html_str = self._render()
        assert "<details open>" in html_str

    def test_pair_scores_shown(self):
        html_str = self._render()
        assert "75.0" in html_str

    def test_duration_hidden_in_image_mode(self):
        html_str = self._render(mode="image")
        assert "Duration" not in html_str


# ---------------------------------------------------------------------------
# Sorting JS
# ---------------------------------------------------------------------------


class TestHtmlSorting:
    def test_sort_script_present(self):
        buf = StringIO()
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            write_html([_make_pair()], file=buf, quiet=True)
        html_str = buf.getvalue()
        assert "sortable" in html_str
        assert "sort-asc" in html_str

    def test_th_elements_have_sortable_class(self):
        buf = StringIO()
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            write_html([_make_pair()], file=buf, quiet=True)
        html_str = buf.getvalue()
        assert 'class="sortable"' in html_str


# ---------------------------------------------------------------------------
# Resource loading
# ---------------------------------------------------------------------------


class TestLoadResource:
    def test_loads_chartjs(self):
        js = _load_resource("chartjs.min.js")
        assert len(js) > 1000
        assert "Chart" in js

    def test_loads_treemap_plugin(self):
        js = _load_resource("chartjs-chart-treemap.min.js")
        assert len(js) > 1000
        assert "treemap" in js.lower() or "TreemapController" in js


# ---------------------------------------------------------------------------
# Analytics dashboard
# ---------------------------------------------------------------------------


def _make_analytics(
    *,
    directory_stats=True,
    score_distribution=True,
    filetype_breakdown=True,
    creation_timeline=True,
):
    """Build an AnalyticsResult with optional empty sections."""
    from duplicates_detector.analytics import (
        AnalyticsResult,
        DirectoryStats,
        FiletypeEntry,
        ScoreBucket,
        TimelineEntry,
    )

    ds = (
        (
            DirectoryStats(
                path="/videos",
                total_files=10,
                duplicate_files=4,
                total_size=5_000_000,
                recoverable_size=2_000_000,
                duplicate_density=0.4,
            ),
        )
        if directory_stats
        else ()
    )

    sd = (
        (
            ScoreBucket(range="70-75", min=70, max=75, count=3),
            ScoreBucket(range="75-80", min=75, max=80, count=5),
        )
        if score_distribution
        else ()
    )

    fb = (
        (
            FiletypeEntry(extension=".mp4", count=6, size=3_000_000),
            FiletypeEntry(extension=".avi", count=2, size=1_000_000),
        )
        if filetype_breakdown
        else ()
    )

    ct = (
        (
            TimelineEntry(date="2024-01-15", total_files=5, duplicate_files=3),
            TimelineEntry(date="2024-01-16", total_files=7, duplicate_files=4),
        )
        if creation_timeline
        else ()
    )

    return AnalyticsResult(
        directory_stats=ds,
        score_distribution=sd,
        filetype_breakdown=fb,
        creation_timeline=ct,
    )


class TestHtmlAnalyticsDashboard:
    def test_contains_chartjs_script(self):
        analytics = _make_analytics()
        result = _html_analytics_dashboard(analytics)
        # Chart.js is inlined as a <script> block
        assert "Chart" in result

    def test_contains_canvas_elements(self):
        analytics = _make_analytics()
        result = _html_analytics_dashboard(analytics)
        assert 'id="chart-treemap"' in result
        assert 'id="chart-scores"' in result
        assert 'id="chart-filetypes"' in result
        assert 'id="chart-timeline"' in result

    def test_contains_analytics_data_json(self):
        analytics = _make_analytics()
        result = _html_analytics_dashboard(analytics)
        assert "analyticsData" in result
        assert "/videos" in result

    def test_single_quote_in_path_does_not_break_html(self):
        """Paths with single quotes must not break the JSON data embedding."""
        from duplicates_detector.analytics import (
            AnalyticsResult,
            DirectoryStats,
        )

        analytics = AnalyticsResult(
            directory_stats=(
                DirectoryStats(
                    path="/home/user/it's a test",
                    total_files=5,
                    duplicate_files=2,
                    total_size=1_000_000,
                    recoverable_size=500_000,
                    duplicate_density=0.4,
                ),
            ),
            score_distribution=(),
            filetype_breakdown=(),
            creation_timeline=(),
        )
        result = _html_analytics_dashboard(analytics)
        # The single quote must appear literally in the JSON data tag
        assert "it's a test" in result
        # Data lives in a <script type="application/json"> tag, not a JS string literal
        assert 'type="application/json" id="analytics-data"' in result
        # No JS-level var assignment with single-quoted string wrapper
        assert "var analyticsData=JSON.parse('" not in result

    def test_details_wrapper(self):
        analytics = _make_analytics()
        result = _html_analytics_dashboard(analytics)
        assert "<details open" in result
        assert "Analytics Dashboard" in result

    def test_empty_directory_stats_shows_fallback(self):
        analytics = _make_analytics(directory_stats=False)
        result = _html_analytics_dashboard(analytics)
        assert 'id="chart-treemap"' not in result
        assert "No directory data available" in result

    def test_empty_score_distribution_shows_fallback(self):
        analytics = _make_analytics(score_distribution=False)
        result = _html_analytics_dashboard(analytics)
        assert 'id="chart-scores"' not in result
        assert "No score data available" in result

    def test_empty_filetype_shows_fallback(self):
        analytics = _make_analytics(filetype_breakdown=False)
        result = _html_analytics_dashboard(analytics)
        assert 'id="chart-filetypes"' not in result
        assert "No file-type data available" in result

    def test_empty_timeline_shows_fallback(self):
        analytics = _make_analytics(creation_timeline=False)
        result = _html_analytics_dashboard(analytics)
        assert 'id="chart-timeline"' not in result
        assert "No timeline data available" in result

    def test_filetype_toggle_button(self):
        analytics = _make_analytics()
        result = _html_analytics_dashboard(analytics)
        assert 'id="ft-toggle"' in result
        assert "by size" in result

    def test_no_toggle_button_when_empty(self):
        analytics = _make_analytics(filetype_breakdown=False)
        result = _html_analytics_dashboard(analytics)
        assert 'id="ft-toggle"' not in result


class TestWriteHtmlWithAnalytics:
    def _render(self, pairs=None, analytics=None, **kwargs):
        if pairs is None:
            pairs = [_make_pair()]
        buf = StringIO()
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            write_html(pairs, file=buf, quiet=True, analytics=analytics, **kwargs)
        return buf.getvalue()

    def test_analytics_present_when_provided(self):
        analytics = _make_analytics()
        html_str = self._render(analytics=analytics)
        assert "Analytics Dashboard" in html_str
        assert 'id="chart-treemap"' in html_str

    def test_analytics_absent_by_default(self):
        html_str = self._render()
        assert "Analytics Dashboard" not in html_str
        assert 'id="chart-treemap"' not in html_str

    def test_analytics_none_no_dashboard(self):
        html_str = self._render(analytics=None)
        assert "Analytics Dashboard" not in html_str

    def test_dashboard_before_pair_table(self):
        analytics = _make_analytics()
        html_str = self._render(analytics=analytics)
        dashboard_pos = html_str.index("Analytics Dashboard")
        table_pos = html_str.index("<table>")
        assert dashboard_pos < table_pos


class TestWriteGroupHtmlWithAnalytics:
    def _render(self, groups=None, analytics=None, **kwargs):
        if groups is None:
            groups = [_make_group()]
        buf = StringIO()
        with patch("duplicates_detector.html_report._generate_all_thumbnails", return_value={}):
            write_group_html(groups, file=buf, quiet=True, analytics=analytics, **kwargs)
        return buf.getvalue()

    def test_analytics_present_when_provided(self):
        analytics = _make_analytics()
        html_str = self._render(analytics=analytics)
        assert "Analytics Dashboard" in html_str
        assert 'id="chart-scores"' in html_str

    def test_analytics_absent_by_default(self):
        html_str = self._render()
        assert "Analytics Dashboard" not in html_str
