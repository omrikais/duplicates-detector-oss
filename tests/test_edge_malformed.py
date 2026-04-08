"""Edge-case tests: malformed / truncated media files.

Validates that corrupt MP4 headers, truncated containers, zero-byte files,
and files with no video streams are handled gracefully across the pipeline.
"""

from __future__ import annotations

import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from duplicates_detector.audio import (
    _MIN_AUDIO_FP_LENGTH,
    compute_audio_fingerprint,
    extract_all_audio_fingerprints,
)
from duplicates_detector.content import (
    _extract_sparse_hashes,
    compute_image_content_hash,
)
from duplicates_detector.metadata import extract_all, extract_one


# ---------------------------------------------------------------------------
# Helpers (reused from test_content.py patterns)
# ---------------------------------------------------------------------------


def _mock_fpcalc_run(stdout: str, returncode: int = 0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = ""
    return mock


# ---------------------------------------------------------------------------
# (a.1) Malformed metadata extraction
# ---------------------------------------------------------------------------


class TestMalformedMetadataExtraction:
    def _make_file(self, tmp_path: Path, name: str = "video.mp4", size: int = 100) -> Path:
        f = tmp_path / name
        f.write_bytes(b"\x00" * size)
        return f

    def test_zero_byte_file_returns_none_fields(self, tmp_path: Path):
        """0-byte file → ffprobe fails → metadata fields are None."""
        f = self._make_file(tmp_path, size=0)
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = ""
        mock.stderr = ""
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration is None
        assert meta.width is None
        assert meta.height is None
        assert meta.file_size == 0

    def test_truncated_json_from_ffprobe(self, tmp_path: Path, mock_ffprobe_result):
        """ffprobe returns truncated JSON → fields are None, no crash."""
        f = self._make_file(tmp_path)
        mock = mock_ffprobe_result(corrupt_json=True)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration is None
        assert meta.width is None

    def test_no_video_stream_in_container(self, tmp_path: Path, mock_ffprobe_result):
        """Only audio streams → width/height/codec None, duration/audio populated."""
        f = self._make_file(tmp_path)
        mock = mock_ffprobe_result(width=None, height=None, codec_name=None, duration=60.0, audio_channels=6)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock):
            meta = extract_one(f)
        assert meta is not None
        assert meta.width is None
        assert meta.height is None
        assert meta.codec is None
        assert meta.duration == 60.0
        assert meta.audio_channels == 6

    def test_negative_duration_from_ffprobe(self, tmp_path: Path, mock_ffprobe_result):
        """ffprobe returns duration: -1 → stored as-is (ffprobe quirk)."""
        f = self._make_file(tmp_path)
        mock = mock_ffprobe_result(duration=-1.0)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration == -1.0

    def test_enormous_resolution_from_ffprobe(self, tmp_path: Path, mock_ffprobe_result):
        """ffprobe returns huge resolution → stored as-is, no overflow."""
        f = self._make_file(tmp_path)
        mock = mock_ffprobe_result(width=999999, height=999999)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock):
            meta = extract_one(f)
        assert meta is not None
        assert meta.width == 999999
        assert meta.height == 999999

    def test_extract_all_skips_failures_continues(self, tmp_path: Path, mock_ffprobe_result):
        """Batch of 5 files, 2 corrupt → 3 valid + 2 with None, no exception."""
        files = []
        for i in range(5):
            f = self._make_file(tmp_path, name=f"vid_{i}.mp4")
            files.append(f)

        good_mock = mock_ffprobe_result(duration=120.0)
        bad_mock = MagicMock()
        bad_mock.returncode = 1
        bad_mock.stdout = ""
        bad_mock.stderr = ""

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return bad_mock if idx in (1, 3) else good_mock

        with (
            patch("duplicates_detector.metadata.subprocess.run", side_effect=side_effect),
            patch("duplicates_detector.metadata.check_ffprobe"),
        ):
            results = extract_all(files, workers=1, quiet=True)

        # All 5 return VideoMetadata (extract_one returns metadata with None fields, not None)
        # But extract_all skips None results — corrupt files return all-None metadata which IS included
        assert len(results) >= 3


# ---------------------------------------------------------------------------
# (a.2) Malformed content hashing
# ---------------------------------------------------------------------------


class TestMalformedContentHashing:
    def test_sparse_hashes_none_duration(self):
        """_extract_sparse_hashes with None duration → returns None."""
        result = _extract_sparse_hashes(Path("test.mp4"), duration=None)
        assert result is None

    def test_sparse_hashes_zero_duration(self):
        """_extract_sparse_hashes with zero duration → returns None."""
        result = _extract_sparse_hashes(Path("test.mp4"), duration=0.0)
        assert result is None

    def test_ffmpeg_fails_all_frames(self):
        """When ffmpeg subprocess fails for all frames → returns None."""
        with patch(
            "duplicates_detector.content.subprocess.run",
            side_effect=OSError("ffmpeg not found"),
        ):
            result = _extract_sparse_hashes(Path("test.mp4"), duration=60.0)
        assert result is None

    def test_ffmpeg_returns_short_output(self):
        """When ffmpeg returns fewer bytes than expected → individual frame returns None."""
        mock_result = MagicMock()
        mock_result.stdout = b"\x00" * 10  # Too short
        with patch("duplicates_detector.content.subprocess.run", return_value=mock_result):
            result = _extract_sparse_hashes(Path("test.mp4"), duration=60.0)
        # All frames fail → None
        assert result is None

    def test_image_content_hash_corrupt_file(self, tmp_path: Path):
        """PIL cannot open file → returns None."""
        f = tmp_path / "corrupt.jpg"
        f.write_bytes(b"\x00" * 100)
        result = compute_image_content_hash(f)
        assert result is None

    def test_image_content_hash_truncated_jpeg(self, tmp_path: Path):
        """Partial JPEG bytes → returns None."""
        # Create valid JPEG then truncate
        img = Image.new("RGB", (64, 64), (128, 128, 128))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        full = buf.getvalue()

        f = tmp_path / "truncated.jpg"
        f.write_bytes(full[: len(full) // 3])
        result = compute_image_content_hash(f)
        # PIL may or may not open a truncated JPEG — either None or a valid hash is acceptable
        # The key thing is no exception is raised
        assert result is None or isinstance(result, tuple)


# ---------------------------------------------------------------------------
# (a.3) Malformed audio fingerprinting
# ---------------------------------------------------------------------------


class TestMalformedAudioFingerprinting:
    def test_fpcalc_returns_empty_output(self):
        """fpcalc stdout is empty → returns None."""
        mock = _mock_fpcalc_run("")
        with patch("duplicates_detector.audio.subprocess.run", return_value=mock):
            result = compute_audio_fingerprint(Path("/video.mp4"), duration=120.0)
        assert result is None

    def test_fpcalc_returns_no_fingerprint_line(self):
        """stdout has DURATION but no FINGERPRINT → returns None."""
        mock = _mock_fpcalc_run("DURATION=10\n")
        with patch("duplicates_detector.audio.subprocess.run", return_value=mock):
            result = compute_audio_fingerprint(Path("/video.mp4"), duration=120.0)
        assert result is None

    def test_fpcalc_returns_short_fingerprint(self):
        """Fingerprint with fewer than _MIN_AUDIO_FP_LENGTH values → returns None."""
        short_fp = ",".join(str(i) for i in range(_MIN_AUDIO_FP_LENGTH - 1))
        mock = _mock_fpcalc_run(f"FINGERPRINT={short_fp}\n")
        with patch("duplicates_detector.audio.subprocess.run", return_value=mock):
            result = compute_audio_fingerprint(Path("/video.mp4"), duration=120.0)
        assert result is None

    def test_fpcalc_nonzero_exit(self):
        """fpcalc returncode=1 → returns None."""
        mock = _mock_fpcalc_run("FINGERPRINT=1,2,3,4,5,6,7,8,9,10\n", returncode=1)
        with patch("duplicates_detector.audio.subprocess.run", return_value=mock):
            result = compute_audio_fingerprint(Path("/video.mp4"), duration=120.0)
        assert result is None

    def test_fpcalc_timeout(self):
        """subprocess.TimeoutExpired → returns None."""
        with patch(
            "duplicates_detector.audio.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="fpcalc", timeout=60),
        ):
            result = compute_audio_fingerprint(Path("/video.mp4"), duration=120.0)
        assert result is None

    def test_extract_all_audio_skips_failures(self, make_metadata):
        """Batch with some failures → populated + None entries, no crash."""
        metas = [make_metadata(path=f"/v/{i}.mp4", duration=60.0) for i in range(4)]

        fp_values = ",".join(str(i) for i in range(20))
        good_mock = _mock_fpcalc_run(f"FINGERPRINT={fp_values}\n")
        bad_mock = _mock_fpcalc_run("", returncode=1)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return bad_mock if idx % 2 == 0 else good_mock

        with (
            patch("duplicates_detector.audio.subprocess.run", side_effect=side_effect),
            patch("duplicates_detector.audio.check_fpcalc"),
        ):
            results = extract_all_audio_fingerprints(metas, workers=1, quiet=True)

        assert len(results) == 4
        has_fp = [r for r in results if r.audio_fingerprint is not None]
        has_none = [r for r in results if r.audio_fingerprint is None]
        assert len(has_fp) >= 1
        assert len(has_none) >= 1
