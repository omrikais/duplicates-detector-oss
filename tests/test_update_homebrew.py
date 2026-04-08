"""Tests for scripts/update_homebrew.py."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import update_homebrew  # noqa: E402


class TestRenderCask:
    def test_injects_version_and_sha256(self):
        result = update_homebrew.render_cask("2.1.0", "a" * 64)
        assert 'version "2.1.0"' in result
        assert f'sha256 "{"a" * 64}"' in result

    def test_contains_dmg_url_with_ruby_interpolation(self):
        result = update_homebrew.render_cask("2.1.0", "a" * 64)
        # The URL must use Ruby #{version} interpolation, not a literal version
        assert "v#{version}/DuplicatesDetector.dmg" in result

    def test_depends_on_cli_formula(self):
        result = update_homebrew.render_cask("2.1.0", "a" * 64)
        assert 'depends_on formula: "omrikais/duplicates-detector/duplicates-detector"' in result

    def test_depends_on_macos_tahoe(self):
        result = update_homebrew.render_cask("2.1.0", "a" * 64)
        assert 'depends_on macos: ">= :tahoe"' in result

    def test_zap_trash_paths(self):
        result = update_homebrew.render_cask("2.1.0", "a" * 64)
        assert "~/Library/Application Support/DuplicatesDetector" in result
        assert "~/.local/share/duplicates-detector" in result

    def test_app_stanza(self):
        result = update_homebrew.render_cask("2.1.0", "a" * 64)
        assert 'app "Duplicates Detector.app"' in result


class TestRenderFormula:
    @pytest.fixture()
    def sample_resources(self):
        return [
            update_homebrew.PyPIResource(
                name="rapidfuzz",
                version="3.6.1",
                url="https://files.pythonhosted.org/packages/source/r/rapidfuzz/rapidfuzz-3.6.1.tar.gz",
                sha256="b" * 64,
            ),
            update_homebrew.PyPIResource(
                name="rich",
                version="13.7.0",
                url="https://files.pythonhosted.org/packages/source/r/rich/rich-13.7.0.tar.gz",
                sha256="c" * 64,
            ),
        ]

    def test_includes_class_and_virtualenv(self, sample_resources):
        result = update_homebrew.render_formula("2.1.0", "a" * 64, sample_resources)
        assert "class DuplicatesDetector < Formula" in result
        assert "include Language::Python::Virtualenv" in result

    def test_injects_version_and_sha256(self, sample_resources):
        result = update_homebrew.render_formula("2.1.0", "a" * 64, sample_resources)
        assert "/archive/refs/tags/v2.1.0.tar.gz" in result
        assert f'sha256 "{"a" * 64}"' in result

    def test_system_dependencies(self, sample_resources):
        result = update_homebrew.render_formula("2.1.0", "a" * 64, sample_resources)
        assert 'depends_on "python@3.12"' in result
        assert 'depends_on "ffmpeg"' in result
        assert 'depends_on "chromaprint"' in result

    def test_resource_blocks(self, sample_resources):
        result = update_homebrew.render_formula("2.1.0", "a" * 64, sample_resources)
        assert 'resource "rapidfuzz" do' in result
        assert "rapidfuzz-3.6.1.tar.gz" in result
        assert f'sha256 "{"b" * 64}"' in result
        assert 'resource "rich" do' in result
        assert "rich-13.7.0.tar.gz" in result

    def test_install_and_test_stanzas(self, sample_resources):
        result = update_homebrew.render_formula("2.1.0", "a" * 64, sample_resources)
        assert "virtualenv_install_with_resources" in result
        assert "assert_match version.to_s" in result

    def test_empty_resources(self):
        result = update_homebrew.render_formula("1.0.0", "a" * 64, [])
        assert "class DuplicatesDetector < Formula" in result
        assert 'resource "' not in result


class TestComputeSha256:
    def test_computes_correct_hash(self, tmp_path):
        f = tmp_path / "test.bin"
        content = b"hello world"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert update_homebrew.compute_sha256(f) == expected

    def test_large_file_chunked(self, tmp_path):
        """Verify chunked reading produces correct hash for files > buffer size."""
        f = tmp_path / "large.bin"
        content = b"x" * (1024 * 1024)  # 1 MB
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert update_homebrew.compute_sha256(f) == expected


class TestFetchPypiSdist:
    @pytest.fixture()
    def pypi_response(self):
        """Minimal PyPI JSON API response with one sdist."""
        return {
            "urls": [
                {
                    "packagetype": "bdist_wheel",
                    "url": "https://files.pythonhosted.org/packages/wheel/rapidfuzz-3.6.1-cp312.whl",
                    "digests": {"sha256": "wheel_hash"},
                },
                {
                    "packagetype": "sdist",
                    "url": "https://files.pythonhosted.org/packages/source/r/rapidfuzz/rapidfuzz-3.6.1.tar.gz",
                    "digests": {"sha256": "d" * 64},
                },
            ]
        }

    @patch("update_homebrew._urlopen_with_retry")
    def test_returns_sdist_resource(self, mock_fetch, pypi_response):
        mock_fetch.return_value = json.dumps(pypi_response).encode()

        result = update_homebrew.fetch_pypi_sdist("rapidfuzz", "3.6.1")
        assert result.name == "rapidfuzz"
        assert result.version == "3.6.1"
        assert result.url.endswith("rapidfuzz-3.6.1.tar.gz")
        assert result.sha256 == "d" * 64

    @patch("update_homebrew._urlopen_with_retry")
    def test_raises_on_no_sdist(self, mock_fetch):
        response = {"urls": [{"packagetype": "bdist_wheel", "url": "x", "digests": {"sha256": "y"}}]}
        mock_fetch.return_value = json.dumps(response).encode()

        with pytest.raises(SystemExit, match="no sdist"):
            update_homebrew.fetch_pypi_sdist("somepkg", "1.0.0")


class TestResolveDeps:
    @patch("update_homebrew.subprocess.run")
    def test_returns_parsed_deps(self, mock_run):
        """resolve_deps creates a venv, pip installs, and parses pip freeze output."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="rapidfuzz==3.6.1\nrich==13.7.0\nduplicates-detector==2.1.0\n"
        )
        result = update_homebrew.resolve_deps(Path("/fake/source.tar.gz"))
        # Should exclude duplicates-detector itself
        assert ("rapidfuzz", "3.6.1") in result
        assert ("rich", "13.7.0") in result
        assert not any(name == "duplicates-detector" for name, _ in result)

    @patch("update_homebrew.subprocess.run")
    def test_excludes_self_package(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="duplicates-detector==2.1.0\nrich==13.7.0\n")
        result = update_homebrew.resolve_deps(Path("/fake/source.tar.gz"))
        names = [name for name, _ in result]
        assert "duplicates-detector" not in names
        assert "rich" in names

    @patch("update_homebrew.subprocess.run")
    def test_raises_on_pip_install_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="pip error")
        with pytest.raises(SystemExit, match="pip install failed"):
            update_homebrew.resolve_deps(Path("/fake/source.tar.gz"))

    @patch("update_homebrew.subprocess.run")
    def test_raises_on_pip_freeze_failure(self, mock_run):
        """pip install succeeds but pip freeze fails."""
        mock_run.side_effect = [
            MagicMock(returncode=0),  # venv creation
            MagicMock(returncode=0),  # pip install
            MagicMock(returncode=1, stderr="freeze error"),  # pip freeze
        ]
        with pytest.raises(SystemExit, match="pip freeze failed"):
            update_homebrew.resolve_deps(Path("/fake/source.tar.gz"))


class TestDownloadSourceTarball:
    @patch("update_homebrew._urlopen_with_retry")
    def test_downloads_and_returns_sha256(self, mock_fetch, tmp_path):
        content = b"fake tarball content"
        expected_sha256 = hashlib.sha256(content).hexdigest()
        mock_fetch.return_value = content

        dest = tmp_path / "source.tar.gz"
        sha = update_homebrew.download_source_tarball("2.1.0", dest)
        assert sha == expected_sha256
        assert dest.read_bytes() == content

    @patch("update_homebrew._urlopen_with_retry")
    def test_constructs_correct_url(self, mock_fetch, tmp_path):
        mock_fetch.return_value = b"data"

        update_homebrew.download_source_tarball("3.0.0", tmp_path / "out.tar.gz")
        url_arg = mock_fetch.call_args[0][0]
        assert url_arg == "https://github.com/omrikais/duplicates-detector-oss/archive/refs/tags/v3.0.0.tar.gz"


class TestUpdateTap:
    @patch("update_homebrew.fetch_pypi_sdist")
    @patch("update_homebrew.resolve_deps")
    @patch("update_homebrew.download_source_tarball")
    def test_writes_formula_and_cask(self, mock_download, mock_resolve, mock_fetch, tmp_path):
        # Setup: mock download returns a sha256
        mock_download.return_value = "a" * 64

        # Setup: mock resolve returns two deps
        mock_resolve.return_value = [("rapidfuzz", "3.6.1"), ("rich", "13.7.0")]

        # Setup: mock fetch returns PyPIResource for each dep
        mock_fetch.side_effect = [
            update_homebrew.PyPIResource("rapidfuzz", "3.6.1", "https://pypi.org/rapidfuzz.tar.gz", "b" * 64),
            update_homebrew.PyPIResource("rich", "13.7.0", "https://pypi.org/rich.tar.gz", "c" * 64),
        ]

        # Create a fake DMG
        dmg = tmp_path / "DuplicatesDetector.dmg"
        dmg.write_bytes(b"fake dmg content")

        tap_dir = tmp_path / "tap"
        tap_dir.mkdir()

        update_homebrew.update_tap("2.1.0", dmg, tap_dir)

        # Verify formula was written
        formula = tap_dir / "Formula" / "duplicates-detector.rb"
        assert formula.exists()
        formula_text = formula.read_text()
        assert "class DuplicatesDetector < Formula" in formula_text
        assert 'resource "rapidfuzz" do' in formula_text
        assert 'resource "rich" do' in formula_text
        assert "/archive/refs/tags/v2.1.0.tar.gz" in formula_text

        # Verify cask was written
        cask = tap_dir / "Casks" / "duplicates-detector-gui.rb"
        assert cask.exists()
        cask_text = cask.read_text()
        assert 'version "2.1.0"' in cask_text
        # SHA256 should be of the fake DMG
        assert update_homebrew.compute_sha256(dmg) in cask_text

    def test_rejects_invalid_version(self, tmp_path):
        dmg = tmp_path / "test.dmg"
        dmg.write_bytes(b"x")
        with pytest.raises(SystemExit, match="not valid semver"):
            update_homebrew.update_tap("v2.1.0", dmg, tmp_path)

    def test_rejects_missing_dmg(self, tmp_path):
        with pytest.raises(SystemExit, match="DMG not found"):
            update_homebrew.update_tap("2.1.0", tmp_path / "missing.dmg", tmp_path)


class TestMain:
    @patch("update_homebrew.update_tap")
    def test_parses_args_and_calls_update(self, mock_update, tmp_path):
        dmg = tmp_path / "test.dmg"
        dmg.write_bytes(b"x")
        tap_dir = tmp_path / "tap"
        tap_dir.mkdir()

        update_homebrew.main(
            [
                "--version",
                "2.1.0",
                "--dmg",
                str(dmg),
                "--tap-dir",
                str(tap_dir),
            ]
        )

        mock_update.assert_called_once_with("2.1.0", dmg, tap_dir)

    def test_missing_required_args(self):
        with pytest.raises(SystemExit):
            update_homebrew.main([])
