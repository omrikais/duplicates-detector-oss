from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.audio import (
    _MIN_AUDIO_FP_LENGTH,
    check_fpcalc,
    compare_audio_fingerprints,
    compute_audio_fingerprint,
    extract_all_audio_fingerprints,
)


# ---------------------------------------------------------------------------
# check_fpcalc
# ---------------------------------------------------------------------------


class TestCheckFpcalc:
    def test_available(self):
        with patch("duplicates_detector.audio.shutil.which", return_value="/usr/bin/fpcalc"):
            check_fpcalc()  # should not raise

    def test_missing(self):
        with patch("duplicates_detector.audio.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="fpcalc not found"):
                check_fpcalc()


# ---------------------------------------------------------------------------
# compute_audio_fingerprint
# ---------------------------------------------------------------------------


class TestComputeAudioFingerprint:
    def _mock_run(self, stdout: str, returncode: int = 0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_parse_output(self):
        fp_values = ",".join(str(i) for i in range(20))
        stdout = f"DURATION=120\nFINGERPRINT={fp_values}\n"
        with patch("duplicates_detector.audio.subprocess.run", return_value=self._mock_run(stdout)):
            result = compute_audio_fingerprint(Path("/video.mp4"), duration=120.0)
        assert result is not None
        assert len(result) == 20
        assert result == tuple(range(20))

    def test_timeout(self):
        with patch(
            "duplicates_detector.audio.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="fpcalc", timeout=60),
        ):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_error_returncode(self):
        with patch("duplicates_detector.audio.subprocess.run", return_value=self._mock_run("", returncode=1)):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_malformed_output(self):
        with patch("duplicates_detector.audio.subprocess.run", return_value=self._mock_run("NO FINGERPRINT LINE\n")):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_empty_fingerprint(self):
        with patch("duplicates_detector.audio.subprocess.run", return_value=self._mock_run("FINGERPRINT=\n")):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_short_fingerprint(self):
        """Fingerprints shorter than _MIN_AUDIO_FP_LENGTH are rejected."""
        fp_values = ",".join(str(i) for i in range(_MIN_AUDIO_FP_LENGTH - 1))
        with patch(
            "duplicates_detector.audio.subprocess.run",
            return_value=self._mock_run(f"FINGERPRINT={fp_values}\n"),
        ):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_non_numeric_values(self):
        with patch(
            "duplicates_detector.audio.subprocess.run",
            return_value=self._mock_run("FINGERPRINT=abc,def,ghi\n"),
        ):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_oserror(self):
        with patch("duplicates_detector.audio.subprocess.run", side_effect=OSError):
            result = compute_audio_fingerprint(Path("/video.mp4"))
        assert result is None

    def test_timeout_scaling(self):
        """Duration-based timeout: max(60, duration * 0.5)."""
        fp_values = ",".join(str(i) for i in range(20))
        with patch("duplicates_detector.audio.subprocess.run") as mock_run:
            mock_run.return_value = self._mock_run(f"FINGERPRINT={fp_values}\n")
            compute_audio_fingerprint(Path("/video.mp4"), duration=300.0)
            _, kwargs = mock_run.call_args
            assert kwargs["timeout"] == 150  # 300 * 0.5 = 150 > 60

    def test_default_timeout(self):
        """No duration → 120s default timeout."""
        fp_values = ",".join(str(i) for i in range(20))
        with patch("duplicates_detector.audio.subprocess.run") as mock_run:
            mock_run.return_value = self._mock_run(f"FINGERPRINT={fp_values}\n")
            compute_audio_fingerprint(Path("/video.mp4"), duration=None)
            _, kwargs = mock_run.call_args
            assert kwargs["timeout"] == 120


# ---------------------------------------------------------------------------
# compare_audio_fingerprints
# ---------------------------------------------------------------------------


class TestCompareAudioFingerprints:
    def test_identical(self):
        fp = tuple(range(100))
        assert compare_audio_fingerprints(fp, fp) == 1.0

    def test_empty(self):
        assert compare_audio_fingerprints((), ()) == 0.0
        assert compare_audio_fingerprints((1, 2, 3), ()) == 0.0
        assert compare_audio_fingerprints((), (1, 2, 3)) == 0.0

    def test_completely_different(self):
        # All bits flipped: XOR = 0xFFFFFFFF for uint32
        fp_a = (0,) * 50
        fp_b = (0xFFFFFFFF,) * 50
        score = compare_audio_fingerprints(fp_a, fp_b)
        assert score == pytest.approx(0.0)

    def test_similar(self):
        """Fingerprints that differ by a few bits should score high."""
        fp_a = tuple(range(50))
        # Flip one bit in each value
        fp_b = tuple(v ^ 1 for v in fp_a)
        score = compare_audio_fingerprints(fp_a, fp_b)
        # 1 bit out of 32 flipped → similarity ≈ 31/32 ≈ 0.969
        assert score > 0.9

    def test_sliding_window(self):
        """Shorter fp slides along longer one."""
        short = (100, 200, 300)
        long = (0, 0, 100, 200, 300, 0, 0)
        score = compare_audio_fingerprints(short, long)
        # Best window should be exact match at offset 2
        assert score == 1.0

    def test_symmetry(self):
        fp_a = tuple(range(20))
        fp_b = tuple(range(10, 30))
        assert compare_audio_fingerprints(fp_a, fp_b) == compare_audio_fingerprints(fp_b, fp_a)


# ---------------------------------------------------------------------------
# extract_all_audio_fingerprints
# ---------------------------------------------------------------------------


class TestExtractAllAudioFingerprints:
    def test_populates_field(self, make_metadata):
        meta = [
            make_metadata("a.mp4", duration=60.0),
            make_metadata("b.mp4", duration=60.0),
        ]
        fp = tuple(range(20))
        with (
            patch("duplicates_detector.audio.check_fpcalc"),
            patch("duplicates_detector.audio.compute_audio_fingerprint", return_value=fp),
        ):
            result = extract_all_audio_fingerprints(meta, workers=1, quiet=True)
        assert len(result) == 2
        assert result[0].audio_fingerprint == fp
        assert result[1].audio_fingerprint == fp

    def test_skips_failures(self, make_metadata):
        meta = [
            make_metadata("a.mp4", duration=60.0),
            make_metadata("b.mp4", duration=60.0),
        ]
        with (
            patch("duplicates_detector.audio.check_fpcalc"),
            patch("duplicates_detector.audio.compute_audio_fingerprint", return_value=None),
        ):
            result = extract_all_audio_fingerprints(meta, workers=1, quiet=True)
        assert len(result) == 2
        assert result[0].audio_fingerprint is None
        assert result[1].audio_fingerprint is None

    def test_cache_hit(self, make_metadata, tmp_path):
        from duplicates_detector.cache import AudioFingerprintCache

        fp = tuple(range(20))
        p = Path(tmp_path / "a.mp4")
        p.touch()
        meta = [make_metadata(str(p), file_size=100, mtime=1000.0)]

        cache = AudioFingerprintCache(cache_dir=tmp_path)
        cache.put(p, 100, 1000.0, fp)
        cache.save()

        # Reload cache
        cache2 = AudioFingerprintCache(cache_dir=tmp_path)
        with (
            patch("duplicates_detector.audio.check_fpcalc"),
            patch("duplicates_detector.audio.compute_audio_fingerprint") as mock_compute,
        ):
            result = extract_all_audio_fingerprints(meta, workers=1, cache=cache2, quiet=True)
        assert result[0].audio_fingerprint == fp
        mock_compute.assert_not_called()
        assert cache2.hits == 1

    def test_cache_miss(self, make_metadata, tmp_path):
        from duplicates_detector.cache import AudioFingerprintCache

        fp = tuple(range(20))
        p = Path(tmp_path / "a.mp4")
        p.touch()
        meta = [make_metadata(str(p), file_size=100, mtime=1000.0)]

        cache = AudioFingerprintCache(cache_dir=tmp_path)
        with (
            patch("duplicates_detector.audio.check_fpcalc"),
            patch("duplicates_detector.audio.compute_audio_fingerprint", return_value=fp),
        ):
            result = extract_all_audio_fingerprints(meta, workers=1, cache=cache, quiet=True)
        assert result[0].audio_fingerprint == fp
        assert cache.misses == 1
