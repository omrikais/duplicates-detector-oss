"""Tests for scripts/generate_manpage.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import generate_manpage  # noqa: E402


class TestGenerate:
    def test_generates_valid_groff(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        assert content.startswith(".TH ")
        assert "DUPLICATES" in content

    def test_includes_examples_section(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        assert ".SH EXAMPLES" in content or "EXAMPLES" in content

    def test_includes_files_section(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        assert "config.toml" in content

    def test_includes_see_also(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        assert "ffprobe" in content

    def test_includes_exit_status(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        assert "EXIT STATUS" in content

    def test_includes_scan_options(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        # groff escapes hyphens as \-, so check for the option names
        assert "threshold" in content
        assert "content" in content
        assert "mode" in content

    def test_version_in_header(self, tmp_path):
        out = tmp_path / "test.1"
        generate_manpage.generate(str(out))
        content = out.read_text()
        # groff escapes hyphens as \-, so check for the escaped form
        assert "duplicates\\-detector" in content.lower()


class TestCheck:
    def test_check_passes_when_fresh(self, tmp_path):
        out = tmp_path / "duplicates-detector.1"
        generate_manpage.generate(str(out))
        # Check against the file we just generated should pass
        assert generate_manpage.check(str(out)) is True

    def test_check_fails_when_stale(self, tmp_path):
        out = tmp_path / "duplicates-detector.1"
        out.write_text("stale content")
        assert generate_manpage.check(str(out)) is False

    def test_check_fails_when_missing(self, tmp_path):
        out = tmp_path / "duplicates-detector.1"
        assert generate_manpage.check(str(out)) is False

    def test_check_passes_despite_version_drift(self, tmp_path):
        """check() ignores .TH header differences (version drift from hatch-vcs)."""
        out = tmp_path / "duplicates-detector.1"
        generate_manpage.generate(str(out))
        # Tamper with the .TH line (simulate version change)
        content = out.read_text()
        lines = content.splitlines(keepends=True)
        lines[0] = (
            '.TH DUPLICATES\\-DETECTOR "1" "2099\\-01\\-01" "duplicates\\-detector 99.0.0" "Duplicates Detector Manual"\n'
        )
        out.write_text("".join(lines))
        assert generate_manpage.check(str(out)) is True


class TestPackaging:
    def test_shared_data_in_pyproject(self):
        """Verify pyproject.toml declares the man page for wheel installation."""
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[reportMissingImports]

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            config = tomllib.load(f)

        shared_data = config["tool"]["hatch"]["build"]["targets"]["wheel"].get("shared-data", {})
        assert "man/duplicates-detector.1" in shared_data
        assert shared_data["man/duplicates-detector.1"] == "share/man/man1/duplicates-detector.1"


class TestMain:
    def test_generate_default(self, tmp_path, monkeypatch):
        out = tmp_path / "man" / "duplicates-detector.1"
        out.parent.mkdir()
        monkeypatch.setattr(generate_manpage, "DEFAULT_OUTPUT", str(out))
        generate_manpage.main([])
        assert out.exists()
        assert out.read_text().startswith(".TH ")

    def test_check_mode_stale(self, tmp_path, monkeypatch):
        out = tmp_path / "man" / "duplicates-detector.1"
        out.parent.mkdir()
        out.write_text("stale")
        monkeypatch.setattr(generate_manpage, "DEFAULT_OUTPUT", str(out))
        with pytest.raises(SystemExit, match="1"):
            generate_manpage.main(["--check"])
