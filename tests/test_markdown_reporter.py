"""Tests for Markdown report format."""

from __future__ import annotations

import io
from pathlib import Path

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.reporter import write_group_markdown, write_markdown
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.summary import PipelineStats


def _meta(
    path: str,
    *,
    size: int = 1000,
    duration: float | None = 120.0,
    width: int | None = 1920,
    height: int | None = 1080,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(path),
        filename=Path(path).stem,
        duration=duration,
        width=width,
        height=height,
        file_size=size,
        codec="h264",
        bitrate=None,
        framerate=None,
        audio_channels=None,
        mtime=None,
    )


def _scored_pair(path_a: str, path_b: str, score: float) -> ScoredPair:
    return ScoredPair(
        file_a=_meta(path_a),
        file_b=_meta(path_b),
        total_score=score,
        breakdown={"filename": score * 0.5, "duration": score * 0.3},
        detail={"filename": (score / 100.0, 50), "duration": (score / 100.0, 30)},
    )


class TestWriteMarkdown:
    def test_header_contains_stats(self):
        pairs = [_scored_pair("/a/clip.mp4", "/b/clip.mp4", 85.0)]
        stats = PipelineStats(files_scanned=100, space_recoverable=1024000)
        buf = io.StringIO()
        write_markdown(pairs, file=buf, stats=stats, mode="video")
        output = buf.getvalue()
        assert "# Duplicate Scan Report" in output
        assert "**Files scanned:** 100" in output

    def test_pair_table_present(self):
        pairs = [_scored_pair("/a/clip.mp4", "/b/clip.mp4", 85.0)]
        buf = io.StringIO()
        write_markdown(pairs, file=buf, mode="video")
        output = buf.getvalue()
        assert "| # | File A | File B | Score | Top Factor |" in output
        assert "clip.mp4" in output

    def test_details_block_per_pair(self):
        pairs = [_scored_pair("/a/clip.mp4", "/b/clip.mp4", 85.0)]
        buf = io.StringIO()
        write_markdown(pairs, file=buf, mode="video")
        output = buf.getvalue()
        assert "<details>" in output
        assert "Score breakdown:" in output

    def test_truncation_note(self):
        pairs = [_scored_pair(f"/a/{i}.mp4", f"/b/{i}.mp4", 80.0) for i in range(600)]
        buf = io.StringIO()
        write_markdown(pairs, file=buf, mode="video")
        output = buf.getvalue()
        assert "Showing 500 of 600" in output

    def test_paths_shortened(self):
        home = str(Path.home())
        pairs = [_scored_pair(f"{home}/Downloads/clip.mp4", f"{home}/Backup/clip.mp4", 85.0)]
        buf = io.StringIO()
        write_markdown(pairs, file=buf, mode="video")
        output = buf.getvalue()
        assert "~/Downloads/clip.mp4" in output

    def test_pipe_in_filename_escaped(self):
        pairs = [_scored_pair("/a/file|one.mp4", "/b/file|two.mp4", 85.0)]
        buf = io.StringIO()
        write_markdown(pairs, file=buf, mode="video")
        output = buf.getvalue()
        # Pipes in filenames must be escaped so they don't break GFM table cells
        assert "file\\|one.mp4" in output
        assert "file\\|two.mp4" in output
        # Unescaped bare pipes inside cell content must not appear
        assert "| file|one" not in output

    def test_dry_run_summary(self):
        from duplicates_detector.advisor import DeletionSummary

        pairs = [_scored_pair("/a/clip.mp4", "/b/clip.mp4", 85.0)]
        dry_run = DeletionSummary(deleted=[Path("/b/clip.mp4")], skipped=0, errors=[], bytes_freed=1000)
        buf = io.StringIO()
        write_markdown(pairs, file=buf, mode="video", dry_run_summary=dry_run)
        output = buf.getvalue()
        assert "Dry Run" in output


class TestWriteGroupMarkdown:
    def test_group_header(self):
        from duplicates_detector.grouper import DuplicateGroup

        pair = _scored_pair("/a/clip.mp4", "/b/clip.mp4", 85.0)
        group = DuplicateGroup(
            group_id=1,
            members=(pair.file_a, pair.file_b),
            pairs=(pair,),
            max_score=85.0,
            min_score=85.0,
            avg_score=85.0,
        )
        buf = io.StringIO()
        write_group_markdown([group], file=buf, mode="video")
        output = buf.getvalue()
        assert "## Group 1" in output
        assert "2 files" in output

    def test_pipe_in_filename_escaped(self):
        from duplicates_detector.grouper import DuplicateGroup

        pair = _scored_pair("/a/file|pipe.mp4", "/b/file|pipe.mp4", 85.0)
        group = DuplicateGroup(
            group_id=1,
            members=(pair.file_a, pair.file_b),
            pairs=(pair,),
            max_score=85.0,
            min_score=85.0,
            avg_score=85.0,
        )
        buf = io.StringIO()
        write_group_markdown([group], file=buf, mode="video")
        output = buf.getvalue()
        assert "file\\|pipe.mp4" in output
        assert "| file|pipe" not in output

    def test_group_pair_scores_in_details(self):
        from duplicates_detector.grouper import DuplicateGroup

        pair = _scored_pair("/a/clip.mp4", "/b/clip.mp4", 85.0)
        group = DuplicateGroup(
            group_id=1,
            members=(pair.file_a, pair.file_b),
            pairs=(pair,),
            max_score=85.0,
            min_score=85.0,
            avg_score=85.0,
        )
        buf = io.StringIO()
        write_group_markdown([group], file=buf, mode="video")
        output = buf.getvalue()
        assert "<details>" in output
        assert "Pair scores" in output
