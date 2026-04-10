"""Tests for scripts/release.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import sys
from pathlib import Path

# Add scripts/ to path so we can import release
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import release  # noqa: E402


class TestExtractReleaseNotes:
    """extract_release_notes() is kept and used by the workflow."""

    def test_extracts_version_section(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "## [2.0.0] - 2026-03-25\n\n"
            "### Added\n- Bundled CLI\n\n"
            "## [1.2.0] - 2026-03-01\n\n"
            "### Fixed\n- Bug\n"
        )
        with patch.object(release, "CHANGELOG", changelog):
            notes = release.extract_release_notes("2.0.0")
        assert "Bundled CLI" in notes
        assert "Bug" not in notes

    def test_returns_empty_for_missing_version(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [Unreleased]\n\n")
        with patch.object(release, "CHANGELOG", changelog):
            assert release.extract_release_notes("9.9.9") == ""


class TestCommitTagAndPush:
    """commit_tag_and_push() commits, tags, and pushes in one call."""

    def test_dry_run_prints_without_executing(self, capsys: pytest.CaptureFixture[str]):
        release.commit_tag_and_push("2.0.0", dry_run=True)
        output = capsys.readouterr().out
        assert "Would run" in output
        assert "v2.0.0" in output

    @patch("release.subprocess.run")
    def test_commits_tags_and_pushes(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(returncode=0)
        release.commit_tag_and_push("2.0.0", dry_run=False)
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["git", "tag", "-a", "v2.0.0", "-m", "v2.0.0"] in calls
        # Branch and tag pushed together in one call
        assert ["git", "push", "origin", "HEAD", "v2.0.0"] in calls


class TestMainFlow:
    """main() calls the unified commit_tag_and_push."""

    @patch("release.commit_tag_and_push")
    @patch("release.stamp_changelog")
    @patch("release.stamp_project_yml")
    @patch("release.check_clean_tree")
    @patch("release.validate_version")
    @patch("release.fetch_remote_tags")
    def test_main_calls_commit_tag_and_push(
        self,
        mock_fetch: MagicMock,
        mock_validate: MagicMock,
        mock_clean: MagicMock,
        mock_stamp_yml: MagicMock,
        mock_stamp: MagicMock,
        mock_commit_tag: MagicMock,
    ):
        release.main(["2.0.0"])
        mock_commit_tag.assert_called_once_with("2.0.0", dry_run=False)


class TestExtractNotesSubcommand:
    """extract-notes subcommand prints changelog section to stdout."""

    def test_prints_notes_to_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## [Unreleased]\n\n## [2.0.0] - 2026-03-25\n\n### Added\n- Feature\n\n## [1.0.0] - 2026-01-01\n"
        )
        with patch.object(release, "CHANGELOG", changelog):
            release.main(["extract-notes", "2.0.0"])
        output = capsys.readouterr().out
        assert "Feature" in output

    def test_exits_zero_when_no_notes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [Unreleased]\n\n")
        with patch.object(release, "CHANGELOG", changelog):
            release.main(["extract-notes", "9.9.9"])
        assert capsys.readouterr().out.strip() == ""
