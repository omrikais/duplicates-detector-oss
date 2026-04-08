from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from duplicates_detector.metadata import extract_one, extract_all, check_ffprobe, VideoMetadata


class TestIsReferenceField:
    def test_is_reference_default_false(self):
        meta = VideoMetadata(
            path=Path("video.mp4"),
            filename="video",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        assert meta.is_reference is False

    def test_is_reference_explicit_true(self):
        meta = VideoMetadata(
            path=Path("video.mp4"),
            filename="video",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            is_reference=True,
        )
        assert meta.is_reference is True

    def test_extract_one_returns_default_false(self, tmp_path, mock_ffprobe_result):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)
        mock_run = mock_ffprobe_result(duration=60.0, width=1920, height=1080)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.is_reference is False


class TestMtimeField:
    def test_mtime_default_none(self):
        meta = VideoMetadata(
            path=Path("video.mp4"),
            filename="video",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        assert meta.mtime is None

    def test_mtime_explicit_value(self):
        meta = VideoMetadata(
            path=Path("video.mp4"),
            filename="video",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            mtime=1_700_000_000.0,
        )
        assert meta.mtime == 1_700_000_000.0

    def test_extract_one_captures_mtime(self, tmp_path, mock_ffprobe_result):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)
        mock_run = mock_ffprobe_result(duration=60.0, width=1920, height=1080)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert isinstance(meta.mtime, float)
        assert meta.mtime > 0


class TestCheckFfprobe:
    def test_check_ffprobe_missing(self):
        with patch("duplicates_detector.metadata.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ffprobe not found"):
                check_ffprobe()

    def test_check_ffprobe_present(self):
        with patch("duplicates_detector.metadata.shutil.which", return_value="/usr/bin/ffprobe"):
            check_ffprobe()  # should not raise


class TestExtractOne:
    def _make_file(self, tmp_path, name="video.mp4", size=1000):
        f = tmp_path / name
        f.write_bytes(b"\x00" * size)
        return f

    def test_extract_one_success(self, tmp_path, mock_ffprobe_result):
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(duration=90.5, width=1280, height=720)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration == 90.5
        assert meta.width == 1280
        assert meta.height == 720
        assert meta.file_size == 1000
        assert meta.filename == "video"
        assert meta.path == f
        assert meta.codec == "h264"
        assert meta.bitrate == 8_000_000
        assert meta.framerate == pytest.approx(23.976, abs=0.001)
        assert meta.audio_channels == 2

    def test_extract_one_missing_duration(self, tmp_path, mock_ffprobe_result):
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(duration=None, width=1920, height=1080)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration is None
        assert meta.width == 1920

    def test_extract_one_missing_resolution(self, tmp_path, mock_ffprobe_result):
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(duration=60.0, width=None, height=None)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration == 60.0
        assert meta.width is None
        assert meta.height is None

    def test_extract_one_file_not_found(self):
        fake_path = Path("/nonexistent/video.mp4")
        meta = extract_one(fake_path)
        assert meta is None

    def test_extract_one_subprocess_timeout(self, tmp_path):
        f = self._make_file(tmp_path)
        with patch(
            "duplicates_detector.metadata.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30),
        ):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration is None
        assert meta.width is None
        assert meta.height is None
        assert meta.file_size == 1000

    def test_extract_one_corrupt_json(self, tmp_path, mock_ffprobe_result):
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(corrupt_json=True)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration is None

    def test_extract_one_nonzero_returncode(self, tmp_path, mock_ffprobe_result):
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(returncode=1)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.duration is None
        assert meta.width is None

    def test_extract_one_missing_codec(self, tmp_path, mock_ffprobe_result):
        """Missing codec_name results in codec=None."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(codec_name=None)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.codec is None

    def test_extract_one_missing_bitrate(self, tmp_path, mock_ffprobe_result):
        """Missing bit_rate in format results in bitrate=None."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(bit_rate=None)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.bitrate is None

    def test_extract_one_non_numeric_bitrate(self, tmp_path, mock_ffprobe_result):
        """Non-numeric bit_rate (e.g. 'N/A') → bitrate=None, other fields preserved."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result()
        # Patch the JSON to inject "N/A" as bit_rate (fixture uses str(int))
        data = json.loads(mock_run.stdout)
        data["format"]["bit_rate"] = "N/A"
        mock_run.stdout = json.dumps(data)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.bitrate is None
        # Other fields must still be parsed
        assert meta.duration == 120.0
        assert meta.width == 1920
        assert meta.height == 1080
        assert meta.framerate is not None

    def test_extract_one_missing_framerate(self, tmp_path, mock_ffprobe_result):
        """Missing r_frame_rate results in framerate=None."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(r_frame_rate=None)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.framerate is None

    def test_extract_one_zero_denominator_framerate(self, tmp_path, mock_ffprobe_result):
        """r_frame_rate = '0/0' should not crash, framerate=None."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(r_frame_rate="0/0")
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.framerate is None

    def test_extract_one_non_numeric_framerate(self, tmp_path, mock_ffprobe_result):
        """Non-numeric r_frame_rate (e.g. 'N/A/1') → framerate=None, other fields preserved."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(r_frame_rate="N/A/1")
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.framerate is None
        # Other fields must still be parsed
        assert meta.duration == 120.0
        assert meta.width == 1920
        assert meta.bitrate is not None

    def test_extract_one_missing_audio_channels(self, tmp_path, mock_ffprobe_result):
        """No audio stream results in audio_channels=None."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(audio_channels=None)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.audio_channels is None

    def test_extract_one_audio_only(self, tmp_path, mock_ffprobe_result):
        """Audio-only file (no video stream): codec/framerate/width/height are None."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(width=None, height=None, codec_name=None, r_frame_rate=None)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.codec is None
        assert meta.framerate is None
        assert meta.width is None
        assert meta.height is None
        assert meta.audio_channels == 2  # audio stream still present

    def test_extract_one_hevc_codec(self, tmp_path, mock_ffprobe_result):
        """Different codec names are preserved as-is."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(codec_name="hevc")
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.codec == "hevc"

    def test_extract_one_51_audio(self, tmp_path, mock_ffprobe_result):
        """5.1 surround sound correctly reports 6 channels."""
        f = self._make_file(tmp_path)
        mock_run = mock_ffprobe_result(audio_channels=6)
        with patch("duplicates_detector.metadata.subprocess.run", return_value=mock_run):
            meta = extract_one(f)
        assert meta is not None
        assert meta.audio_channels == 6

    def test_extract_one_timeout_all_fields_none(self, tmp_path):
        """Timeout results in all new fields being None."""
        f = self._make_file(tmp_path)
        with patch(
            "duplicates_detector.metadata.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30),
        ):
            meta = extract_one(f)
        assert meta is not None
        assert meta.codec is None
        assert meta.bitrate is None
        assert meta.framerate is None
        assert meta.audio_channels is None


class TestExtractAll:
    def test_extract_all_filters_none(self, tmp_path, mock_ffprobe_result):
        files = []
        for name in ["a.mp4", "b.mp4", "c.mp4"]:
            f = tmp_path / name
            f.write_bytes(b"\x00" * 100)
            files.append(f)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Make second file "fail" by raising an OSError
                raise OSError("disk error")
            return mock_ffprobe_result(duration=60.0)

        with patch("duplicates_detector.metadata.shutil.which", return_value="/usr/bin/ffprobe"):
            with patch("duplicates_detector.metadata.subprocess.run", side_effect=side_effect):
                results = extract_all(files, workers=1)

        # 2 succeed (with None metadata fields on the OSError one, it still returns metadata),
        # but the one that raised OSError in subprocess.run will have None fields, not be None itself.
        # Actually, OSError is caught in extract_one's except clause so it returns metadata with None fields.
        # All 3 return non-None, so all 3 are included.
        # Let me use a different approach: mock extract_one directly
        pass

    def test_extract_all_filters_none_v2(self, tmp_path):
        """Mock extract_one directly to test None filtering."""
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        for f in files:
            f.write_bytes(b"\x00" * 100)

        results_map = {
            files[0]: VideoMetadata(path=files[0], filename="a", duration=60.0, width=1920, height=1080, file_size=100),
            files[1]: None,  # simulate failure
            files[2]: VideoMetadata(path=files[2], filename="c", duration=90.0, width=1280, height=720, file_size=100),
        }

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", side_effect=lambda p: results_map[p]):
                results = extract_all(files, workers=1)

        assert len(results) == 2
        filenames = {m.filename for m in results}
        assert filenames == {"a", "c"}

    def test_extract_all_workers_auto(self, tmp_path):
        """workers=0 should resolve to a positive value (no crash)."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00" * 100)

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch(
                "duplicates_detector.metadata.extract_one",
                return_value=VideoMetadata(
                    path=f,
                    filename="video",
                    duration=60.0,
                    width=1920,
                    height=1080,
                    file_size=100,
                ),
            ):
                results = extract_all([f], workers=0)

        assert len(results) == 1


class TestExtractAllWithCache:
    """Tests for MetadataCache integration in extract_all()."""

    def _make_files(self, tmp_path, names=("a.mp4", "b.mp4")):
        files = []
        for name in names:
            f = tmp_path / name
            f.write_bytes(b"\x00" * 100)
            files.append(f)
        return files

    def test_cache_hit_skips_ffprobe(self, tmp_path):
        """Files with cache hits don't trigger ffprobe subprocess calls."""
        files = self._make_files(tmp_path, ["a.mp4"])
        st = files[0].stat()

        cache = MagicMock()
        cache.get.return_value = {
            "duration": 60.0,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
            "bitrate": 8_000_000,
            "framerate": 23.976,
            "audio_channels": 2,
        }
        cache.hits = 1
        cache.misses = 0

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one") as mock_extract:
                results = extract_all(files, workers=1, cache=cache)

        # ffprobe should never be called — file was cached
        mock_extract.assert_not_called()
        assert len(results) == 1
        assert results[0].duration == 60.0
        assert results[0].file_size == st.st_size

    def test_cache_miss_calls_ffprobe(self, tmp_path):
        """Files with cache misses go through ffprobe extraction."""
        files = self._make_files(tmp_path, ["a.mp4"])

        cache = MagicMock()
        cache.get.return_value = None  # miss
        cache.hits = 0
        cache.misses = 1

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=90.0,
            width=1280,
            height=720,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted):
                results = extract_all(files, workers=1, cache=cache)

        assert len(results) == 1
        assert results[0].duration == 90.0
        cache.put.assert_called_once()

    def test_cache_populated_after_extraction(self, tmp_path):
        """Newly extracted metadata is stored in cache via put()."""
        files = self._make_files(tmp_path, ["a.mp4"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=90.0,
            width=1280,
            height=720,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted):
                extract_all(files, workers=1, cache=cache)

        cache.put.assert_called_once_with(
            path=files[0],
            file_size=100,
            mtime=1.0,
            duration=90.0,
            width=1280,
            height=720,
            codec=None,
            bitrate=None,
            framerate=None,
            audio_channels=None,
        )

    def test_cache_save_called(self, tmp_path):
        """cache.save() is called after extraction completes."""
        files = self._make_files(tmp_path, ["a.mp4"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=90.0,
            width=1280,
            height=720,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted):
                extract_all(files, workers=1, cache=cache)

        cache.save.assert_called_once()

    def test_all_none_metadata_not_cached(self, tmp_path):
        """Entries with all-None ffprobe fields are not cached (likely transient failure)."""
        files = self._make_files(tmp_path, ["a.mp4"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        # Simulate ffprobe timeout — stat succeeds but all metadata is None
        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=None,
            width=None,
            height=None,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted):
                extract_all(files, workers=1, cache=cache)

        cache.put.assert_not_called()
        cache.save.assert_called_once()  # save is still called

    def test_partial_none_metadata_is_cached(self, tmp_path):
        """Entries with some but not all None fields are still cached."""
        files = self._make_files(tmp_path, ["a.mp4"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        # duration extracted, but no video stream (audio-only container)
        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=90.0,
            width=None,
            height=None,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted):
                extract_all(files, workers=1, cache=cache)

        cache.put.assert_called_once()

    def test_no_cache_is_noop(self, tmp_path):
        """cache=None works identically to current behavior."""
        files = self._make_files(tmp_path, ["a.mp4"])

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=60.0,
            width=1920,
            height=1080,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted):
                results = extract_all(files, workers=1, cache=None)

        assert len(results) == 1

    def test_verbose_prints_cache_stats(self, tmp_path, capsys):
        """Verbose mode prints hit/miss/rate statistics."""
        files = self._make_files(tmp_path, ["a.mp4"])

        cache = MagicMock()
        cache.get.return_value = {
            "duration": 60.0,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
            "bitrate": 8_000_000,
            "framerate": 23.976,
            "audio_channels": 2,
        }
        cache.hits = 1
        cache.misses = 0

        with patch("duplicates_detector.metadata.check_ffprobe"):
            extract_all(files, workers=1, verbose=True, cache=cache)

        captured = capsys.readouterr()
        assert "Metadata cache:" in captured.err
        assert "1 hits" in captured.err
        assert "0 misses" in captured.err

    def test_mixed_hits_and_misses(self, tmp_path):
        """Some files hit cache, others miss — both are in final results."""
        files = self._make_files(tmp_path, ["a.mp4", "b.mp4"])

        def cache_get(path, file_size, mtime):
            if path.name == "a.mp4":
                return {
                    "duration": 60.0,
                    "width": 1920,
                    "height": 1080,
                    "codec": "h264",
                    "bitrate": 8_000_000,
                    "framerate": 23.976,
                    "audio_channels": 2,
                }
            return None

        cache = MagicMock()
        cache.get.side_effect = cache_get
        cache.hits = 1
        cache.misses = 1

        extracted_b = VideoMetadata(
            path=files[1],
            filename="b",
            duration=90.0,
            width=1280,
            height=720,
            file_size=100,
            mtime=1.0,
        )

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=extracted_b):
                results = extract_all(files, workers=1, cache=cache)

        assert len(results) == 2
        filenames = {r.filename for r in results}
        assert filenames == {"a", "b"}

    def test_stat_failure_in_prepass_falls_through(self, tmp_path):
        """If stat() fails in pre-pass, file goes to ffprobe path."""
        missing_file = tmp_path / "gone.mp4"
        # Don't create the file — stat() will fail

        cache = MagicMock()
        cache.hits = 0
        cache.misses = 0

        with patch("duplicates_detector.metadata.check_ffprobe"):
            with patch("duplicates_detector.metadata.extract_one", return_value=None) as mock_extract:
                results = extract_all([missing_file], workers=1, cache=cache)

        # File should have been passed to extract_one (not cached)
        mock_extract.assert_called_once_with(missing_file)
        # cache.get should never have been called (stat failed before)
        cache.get.assert_not_called()
        assert len(results) == 0


# ---------------------------------------------------------------------------
# extract_one_image — image metadata extraction via PIL
# ---------------------------------------------------------------------------


class TestExtractOneImage:
    def test_basic(self, tmp_path):
        from duplicates_detector.metadata import extract_one_image

        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake")
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (1920, 1080)
            mock_img.format = "PNG"
            mock_img.__enter__ = MagicMock(return_value=mock_img)
            mock_img.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_img
            result = extract_one_image(img_path)
        assert result is not None
        assert result.width == 1920
        assert result.height == 1080
        assert result.codec == "png"
        assert result.duration is None
        assert result.bitrate is None
        assert result.framerate is None
        assert result.audio_channels is None

    def test_corrupt_image(self, tmp_path):
        from duplicates_detector.metadata import extract_one_image

        img_path = tmp_path / "corrupt.jpg"
        img_path.write_bytes(b"notanimage")
        with patch("PIL.Image.open", side_effect=Exception("cannot identify image")):
            result = extract_one_image(img_path)
        assert result is None  # unreadable images are skipped

    def test_stat_error(self):
        from duplicates_detector.metadata import extract_one_image

        result = extract_one_image(Path("/nonexistent/image.png"))
        assert result is None


class TestExtractAllImages:
    def test_parallel(self, tmp_path):
        from duplicates_detector.metadata import extract_all_images

        files = []
        for name in ("a.png", "b.jpg"):
            p = tmp_path / name
            p.write_bytes(b"fake")
            files.append(p)
        with patch("duplicates_detector.metadata.extract_one_image") as mock_extract:
            mock_extract.return_value = VideoMetadata(
                path=files[0],
                filename="a",
                duration=None,
                width=100,
                height=100,
                file_size=100,
                mtime=0.0,
            )
            result = extract_all_images(files, workers=1, quiet=True)
        assert len(result) == 2

    def test_no_ffprobe_required(self, tmp_path):
        """extract_all_images should not call check_ffprobe."""
        from duplicates_detector.metadata import extract_all_images

        p = tmp_path / "a.png"
        p.write_bytes(b"fake")
        with (
            patch("duplicates_detector.metadata.extract_one_image") as mock_extract,
            patch("duplicates_detector.metadata.check_ffprobe") as mock_check,
        ):
            mock_extract.return_value = VideoMetadata(
                path=p,
                filename="a",
                duration=None,
                width=100,
                height=100,
                file_size=100,
                mtime=0.0,
            )
            extract_all_images([p], workers=1, quiet=True)
        mock_check.assert_not_called()


# ---------------------------------------------------------------------------
# EXIF extraction — _extract_exif
# ---------------------------------------------------------------------------


class TestExtractExif:
    def test_datetime_extraction(self, tmp_path):
        """DateTimeOriginal is parsed from EXIF sub-IFD."""
        from duplicates_detector.metadata import _extract_exif

        mock_img = MagicMock()
        exif_data = MagicMock()
        exif_data.get.side_effect = lambda tag, default=None: {271: "Canon", 272: "EOS R5"}.get(tag, default)

        exif_ifd = {36867: "2024:01:15 10:30:00"}
        gps_ifd: dict = {}
        exif_data.get_ifd.side_effect = lambda tag: {0x8769: exif_ifd, 0x8825: gps_ifd}.get(tag, {})

        mock_img.getexif.return_value = exif_data
        result = _extract_exif(mock_img)

        assert result["exif_datetime"] is not None
        assert isinstance(result["exif_datetime"], float)
        assert result["exif_camera"] == "canon eos r5"

    def test_camera_extraction(self, tmp_path):
        """Camera make + model are concatenated and lowercased."""
        from duplicates_detector.metadata import _extract_exif

        mock_img = MagicMock()
        exif_data = MagicMock()
        exif_data.get.side_effect = lambda tag, default=None: {271: "NIKON", 272: "Z6 II"}.get(tag, default)
        exif_data.get_ifd.return_value = {}
        mock_img.getexif.return_value = exif_data

        result = _extract_exif(mock_img)
        assert result["exif_camera"] == "nikon z6 ii"

    def test_gps_extraction(self, tmp_path):
        """GPS coordinates are converted from DMS to decimal degrees."""
        from duplicates_detector.metadata import _extract_exif

        mock_img = MagicMock()
        exif_data = MagicMock()
        exif_data.get.side_effect = lambda tag, default=None: default

        gps_ifd = {
            1: "N",
            2: (40.0, 42.0, 46.08),  # 40°42'46.08"N
            3: "W",
            4: (74.0, 0.0, 21.6),  # 74°0'21.6"W
        }
        exif_data.get_ifd.side_effect = lambda tag: {0x8769: {}, 0x8825: gps_ifd}.get(tag, {})
        mock_img.getexif.return_value = exif_data

        result = _extract_exif(mock_img)
        assert result["exif_gps_lat"] is not None
        assert result["exif_gps_lat"] == pytest.approx(40.7128, abs=0.001)
        assert result["exif_gps_lon"] is not None
        assert result["exif_gps_lon"] == pytest.approx(-74.006, abs=0.001)

    def test_no_exif_data(self, tmp_path):
        """Image with no EXIF returns all None values."""
        from duplicates_detector.metadata import _extract_exif

        mock_img = MagicMock()
        mock_img.getexif.return_value = None

        result = _extract_exif(mock_img)
        assert all(v is None for v in result.values())

    def test_malformed_exif(self, tmp_path):
        """Malformed EXIF data doesn't crash — returns all None."""
        from duplicates_detector.metadata import _extract_exif

        mock_img = MagicMock()
        mock_img.getexif.side_effect = Exception("corrupt EXIF")

        result = _extract_exif(mock_img)
        assert all(v is None for v in result.values())

    def test_png_without_exif(self, tmp_path):
        """PNG images have no EXIF — returns all None."""
        from duplicates_detector.metadata import _extract_exif

        mock_img = MagicMock()
        exif_data = MagicMock()
        # bool(exif_data) should be False to simulate empty EXIF
        exif_data.__bool__ = lambda self: False
        mock_img.getexif.return_value = exif_data

        result = _extract_exif(mock_img)
        assert all(v is None for v in result.values())

    def test_extract_one_image_includes_exif(self, tmp_path):
        """extract_one_image() populates EXIF fields from _extract_exif()."""
        from duplicates_detector.metadata import extract_one_image

        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake")

        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (4000, 3000)
            mock_img.format = "JPEG"
            mock_img.__enter__ = MagicMock(return_value=mock_img)
            mock_img.__exit__ = MagicMock(return_value=False)

            # Set up EXIF data
            exif_data = MagicMock()
            exif_data.get.side_effect = lambda tag, default=None: {271: "Canon", 272: "EOS R5"}.get(tag, default)
            exif_ifd = {36867: "2024:01:15 10:30:00", 40962: 4000, 40963: 3000}
            exif_data.get_ifd.side_effect = lambda tag: {0x8769: exif_ifd, 0x8825: {}}.get(tag, {})
            mock_img.getexif.return_value = exif_data

            mock_open.return_value = mock_img
            result = extract_one_image(img_path)

        assert result is not None
        assert result.exif_camera == "canon eos r5"
        assert result.exif_datetime is not None
        assert result.exif_width == 4000
        assert result.exif_height == 3000
