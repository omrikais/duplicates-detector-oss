"""Integration tests for audio mode edge cases."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import _get_integ_generators, _require_integ_file

pytestmark = pytest.mark.slow

_gen = _get_integ_generators()

_has_mutagen = True
try:
    import mutagen  # noqa: F401
except ImportError:
    _has_mutagen = False


@pytest.fixture(scope="session")
def audio_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
    d = tmp_path_factory.mktemp("audio")
    files = _gen.generate_audio_edge_cases(d)
    if not any(files.values()):
        pytest.skip("No audio files could be generated")
    return files


@pytest.mark.skipif(not _has_mutagen, reason="mutagen not installed")
class TestAudioMetadata:
    def test_flac_metadata(self, audio_media: dict[str, Path | None]) -> None:
        from duplicates_detector.metadata import extract_one_audio

        path = _require_integ_file(audio_media, "flac_file")
        meta = extract_one_audio(path)
        assert meta is not None
        assert meta.duration is not None
        assert meta.duration > 0

    def test_opus_ogg_metadata(self, audio_media: dict[str, Path | None]) -> None:
        from duplicates_detector.metadata import extract_one_audio

        path = _require_integ_file(audio_media, "opus_ogg")
        meta = extract_one_audio(path)
        assert meta is not None
        assert meta.duration is not None

    def test_chaptered_m4a_duration(self, audio_media: dict[str, Path | None]) -> None:
        from duplicates_detector.metadata import extract_one_audio

        path = _require_integ_file(audio_media, "chaptered_m4a")
        meta = extract_one_audio(path)
        assert meta is not None
        assert meta.duration is not None
        # Should report full duration, not just first chapter
        assert meta.duration > 2.0

    def test_vbr_mp3_duration(self, audio_media: dict[str, Path | None]) -> None:
        from duplicates_detector.metadata import extract_one_audio

        path = _require_integ_file(audio_media, "vbr_mp3")
        meta = extract_one_audio(path)
        assert meta is not None
        assert meta.duration is not None
        # VBR duration should be approximately correct (~3s)
        assert 2.0 < meta.duration < 5.0

    def test_artwork_mp3_metadata(self, audio_media: dict[str, Path | None]) -> None:
        """Embedded artwork doesn't confuse metadata extraction."""
        from duplicates_detector.metadata import extract_one_audio

        path = _require_integ_file(audio_media, "artwork_mp3")
        meta = extract_one_audio(path)
        assert meta is not None
        assert meta.duration is not None
        assert meta.duration > 0


@pytest.mark.skipif(not _has_mutagen, reason="mutagen not installed")
class TestAudioCrossFormat:
    @pytest.fixture(scope="class")
    def cross_audio(self, audio_media: dict[str, Path | None]) -> dict[str, Path]:
        """Require FLAC and VBR MP3 for cross-format comparison."""
        flac = audio_media.get("flac_file")
        mp3 = audio_media.get("vbr_mp3")
        if flac is None or mp3 is None:
            pytest.skip("Need both FLAC and MP3 for cross-format test")
        return {"flac": flac, "mp3": mp3}

    def test_cross_format_fingerprint(self, cross_audio: dict[str, Path]) -> None:
        """FLAC vs MP3 of similar source — audio fingerprinting should report similarity."""
        if not shutil.which("fpcalc"):
            pytest.skip("fpcalc not available")

        from duplicates_detector.audio import compare_audio_fingerprints, compute_audio_fingerprint

        fp_flac = compute_audio_fingerprint(cross_audio["flac"])
        fp_mp3 = compute_audio_fingerprint(cross_audio["mp3"])
        if fp_flac is None or fp_mp3 is None:
            pytest.skip("Fingerprint extraction failed")

        similarity = compare_audio_fingerprints(fp_flac, fp_mp3)
        # Same sine wave source, different codec — should be somewhat similar
        assert similarity > 0.2, f"Cross-format audio similarity too low: {similarity}"


class TestAudioEndToEnd:
    @pytest.mark.skipif(not _has_mutagen, reason="mutagen not installed")
    def test_audio_mode_pipeline(self, audio_media: dict[str, Path | None], tmp_path: Path) -> None:
        """Full pipeline in audio mode with generated files."""
        scan_dir = tmp_path / "audio_scan"
        scan_dir.mkdir()

        copied = 0
        for key in ["flac_file", "vbr_mp3", "chaptered_m4a"]:
            src = audio_media.get(key)
            if src is not None:
                import shutil as sh

                sh.copy2(src, scan_dir / src.name)
                copied += 1

        if copied < 2:
            pytest.skip("Need at least 2 audio files for pipeline test")

        from duplicates_detector.cli import main

        # main() returns None on success, raises SystemExit on error
        main(["scan", str(scan_dir), "--mode", "audio", "--format", "json", "--quiet"])
