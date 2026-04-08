from __future__ import annotations

import hashlib
import threading
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from duplicates_detector.content import (
    _MIN_SCENE_FRAMES,
    _PNG_SIGNATURE,
    _compare_content_hashes_sliding,
    _compare_rotation_invariant,
    _extract_single_frame_hash,
    _extract_sparse_hashes,
    _hamming_distance_256,
    _HASH_UINT64S,
    _NUM_BITS,
    _NUM_FRAMES,
    _pack_pdq_hash,
    _pre_hash_one_with_cache,
    _synthetic_content_hash,
    check_ffmpeg,
    compare_content_hashes,
    compute_image_content_hash,
    compute_pre_hash,
)
from duplicates_detector.metadata import VideoMetadata


def _make_png_bytes(color: tuple[int, int, int] = (128, 128, 128), size: tuple[int, int] = (8, 8)) -> bytes:
    """Create a small PNG image in memory and return its bytes."""
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mock_popen(stdout_data: bytes):
    """Create a mock Popen that yields stdout_data from its stdout pipe."""
    mock_proc = MagicMock()
    mock_proc.stdout = BytesIO(stdout_data)
    mock_proc.wait.return_value = 0
    return mock_proc


class TestCheckFfmpeg:
    def test_raises_when_missing(self):
        with patch("duplicates_detector.content.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ffmpeg not found"):
                check_ffmpeg()

    def test_passes_when_available(self):
        with patch("duplicates_detector.content.shutil.which", return_value="/usr/bin/ffmpeg"):
            check_ffmpeg()  # Should not raise


# ---------------------------------------------------------------------------
# PDQ hash packing
# ---------------------------------------------------------------------------


class TestPackPdqHash:
    def test_all_zeros(self):
        """All-zero hash vector packs to four zero uint64 values."""
        vec = np.zeros(256, dtype=np.uint8)
        result = _pack_pdq_hash(vec)
        assert isinstance(result, tuple)
        assert len(result) == 4
        assert all(v == 0 for v in result)

    def test_all_ones(self):
        """All-one hash vector packs to four max uint64 values."""
        vec = np.ones(256, dtype=np.uint8)
        result = _pack_pdq_hash(vec)
        assert len(result) == 4
        assert all(v == 0xFFFFFFFFFFFFFFFF for v in result)

    def test_known_pattern(self):
        """First 64 bits set, rest zero -> first uint64 is max, rest zero."""
        vec = np.zeros(256, dtype=np.uint8)
        vec[:64] = 1
        result = _pack_pdq_hash(vec)
        assert result[0] == 0xFFFFFFFFFFFFFFFF
        assert result[1] == 0
        assert result[2] == 0
        assert result[3] == 0

    def test_returns_python_ints(self):
        """Values are plain Python ints, not numpy scalars."""
        vec = np.ones(256, dtype=np.uint8)
        result = _pack_pdq_hash(vec)
        for v in result:
            assert type(v) is int


# ---------------------------------------------------------------------------
# Single-frame extraction
# ---------------------------------------------------------------------------


class TestExtractSingleFrameHash:
    def test_correct_ffmpeg_command(self):
        """Verify the ffmpeg command includes -ss, rawvideo, and scale."""
        fake_hash = np.zeros(256, dtype=bool)
        with (
            patch("duplicates_detector.content.subprocess.run") as mock_run,
            patch("duplicates_detector.content.pdqhash.compute", return_value=(fake_hash, 100.0)),
        ):
            mock_run.return_value = MagicMock(stdout=b"\x00" * 12288)
            _extract_single_frame_hash(Path("test.mp4"), 5.0)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-ss" in cmd
        assert "5.0" in cmd
        assert "rawvideo" in cmd
        assert "rgb24" in cmd
        assert "scale=64:64" in " ".join(cmd)

    def test_returns_4tuple_on_success(self):
        """Successful extraction returns a 4-element tuple of ints."""
        fake_hash = np.zeros(256, dtype=bool)
        with (
            patch("duplicates_detector.content.subprocess.run") as mock_run,
            patch("duplicates_detector.content.pdqhash.compute", return_value=(fake_hash, 100.0)),
        ):
            mock_run.return_value = MagicMock(stdout=b"\x00" * 12288)
            result = _extract_single_frame_hash(Path("test.mp4"), 1.0)
        assert result is not None
        assert len(result) == 4

    def test_returns_none_on_oserror(self):
        """OSError from subprocess returns None."""
        with patch("duplicates_detector.content.subprocess.run", side_effect=OSError("not found")):
            result = _extract_single_frame_hash(Path("test.mp4"), 1.0)
        assert result is None

    def test_returns_none_on_timeout(self):
        """TimeoutExpired returns None."""
        import subprocess

        with patch(
            "duplicates_detector.content.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ffmpeg", 30),
        ):
            result = _extract_single_frame_hash(Path("test.mp4"), 1.0)
        assert result is None

    def test_returns_none_on_short_output(self):
        """Too little stdout data returns None."""
        with patch("duplicates_detector.content.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"\x00" * 100)
            result = _extract_single_frame_hash(Path("test.mp4"), 1.0)
        assert result is None


# ---------------------------------------------------------------------------
# Sparse hash extraction
# ---------------------------------------------------------------------------


class TestExtractSparseHashes:
    def test_returns_40_element_tuple(self):
        """10 frames x 4 uint64 = 40-element tuple."""
        fake_hash = (0, 0, 0, 0)
        with patch(
            "duplicates_detector.content._extract_single_frame_hash",
            return_value=fake_hash,
        ):
            result = _extract_sparse_hashes(Path("test.mp4"), duration=100.0)
        assert result is not None
        assert len(result) == 40

    def test_returns_none_on_zero_duration(self):
        """Duration <= 0 returns None."""
        assert _extract_sparse_hashes(Path("test.mp4"), duration=0.0) is None
        assert _extract_sparse_hashes(Path("test.mp4"), duration=-1.0) is None

    def test_returns_none_on_none_duration(self):
        """None duration returns None."""
        assert _extract_sparse_hashes(Path("test.mp4"), duration=None) is None

    def test_returns_none_when_all_fail(self):
        """All frame extractions failing returns None."""
        with patch("duplicates_detector.content._extract_single_frame_hash", return_value=None):
            result = _extract_sparse_hashes(Path("test.mp4"), duration=100.0)
        assert result is None

    def test_skipped_frames_reduce_tuple_length(self):
        """If some frames fail, the tuple is shorter (but not None)."""
        call_count = [0]

        def _sometimes_fail(path, ts):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return None
            return (1, 2, 3, 4)

        with patch(
            "duplicates_detector.content._extract_single_frame_hash",
            side_effect=_sometimes_fail,
        ):
            result = _extract_sparse_hashes(Path("test.mp4"), duration=100.0)
        assert result is not None
        # 5 successful frames x 4 = 20
        assert len(result) == 20

    def test_timestamps_are_correct(self):
        """Verify timestamps are at 5%, 15%, ..., 95% of duration."""
        timestamps_seen = []

        def _capture_ts(path, ts):
            timestamps_seen.append(ts)
            return (0, 0, 0, 0)

        with patch(
            "duplicates_detector.content._extract_single_frame_hash",
            side_effect=_capture_ts,
        ):
            _extract_sparse_hashes(Path("test.mp4"), duration=100.0)
        expected = [5.0, 15.0, 25.0, 35.0, 45.0, 55.0, 65.0, 75.0, 85.0, 95.0]
        assert sorted(timestamps_seen) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Image content hashing (PDQ)
# ---------------------------------------------------------------------------


class TestComputeImageContentHashPdq:
    def test_basic_4tuple(self, tmp_path):
        """A real PNG file returns a 4-element tuple."""
        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (64, 64), (128, 128, 128))
        img.save(str(img_path), format="PNG")
        result = compute_image_content_hash(img_path)
        assert result is not None
        assert len(result) == 4
        assert all(isinstance(v, int) for v in result)

    def test_rotation_invariant_32tuple(self, tmp_path):
        """rotation_invariant=True returns a 32-element tuple (8 x 4)."""
        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (64, 64), (128, 128, 128))
        img.save(str(img_path), format="PNG")
        result = compute_image_content_hash(img_path, rotation_invariant=True)
        assert result is not None
        assert len(result) == 32
        assert all(isinstance(v, int) for v in result)

    def test_corrupt_returns_none(self, tmp_path):
        """Corrupt image file returns None."""
        img_path = tmp_path / "bad.png"
        img_path.write_bytes(b"not an image")
        result = compute_image_content_hash(img_path)
        assert result is None

    def test_nonexistent_returns_none(self):
        """Nonexistent file returns None."""
        result = compute_image_content_hash(Path("/nonexistent/path.png"))
        assert result is None


# ---------------------------------------------------------------------------
# Hamming distance
# ---------------------------------------------------------------------------


class TestHammingDistance256:
    def test_identical_is_zero(self):
        a = np.array([0, 0, 0, 0], dtype=np.uint64)
        assert _hamming_distance_256(a, a) == 0

    def test_all_bits_different(self):
        a = np.zeros(4, dtype=np.uint64)
        b = np.array([0xFFFFFFFFFFFFFFFF] * 4, dtype=np.uint64)
        assert _hamming_distance_256(a, b) == 256

    def test_single_bit(self):
        a = np.zeros(4, dtype=np.uint64)
        b = np.array([1, 0, 0, 0], dtype=np.uint64)
        assert _hamming_distance_256(a, b) == 1


# ---------------------------------------------------------------------------
# Content hash comparison (PDQ)
# ---------------------------------------------------------------------------


class TestCompareContentHashesPdq:
    def test_identical_returns_1(self):
        """Identical hashes produce similarity 1.0."""
        h = (0, 0, 0, 0) * 10  # 10 frames
        assert compare_content_hashes(h, h) == 1.0

    def test_empty_returns_zero(self):
        """Empty hash sequences return 0.0."""
        assert compare_content_hashes((), (0, 0, 0, 0)) == 0.0
        assert compare_content_hashes((0, 0, 0, 0), ()) == 0.0
        assert compare_content_hashes((), ()) == 0.0

    def test_completely_different(self):
        """All-zero vs all-max hashes produce similarity near 0.0."""
        a = (0, 0, 0, 0)
        b = (0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
        result = compare_content_hashes(a, b)
        assert result == 0.0

    def test_sliding_window(self):
        """Shorter sequence slides along longer one."""
        frame_a = (0, 0, 0, 0)
        frame_b = (0xFFFFFFFFFFFFFFFF,) * 4
        # short=1 frame, long=3 frames where middle matches
        short = frame_a
        long_hash = frame_b + frame_a + frame_b
        result = compare_content_hashes(short, long_hash)
        assert result == 1.0  # best offset finds perfect match

    def test_single_frame_each(self):
        """Single 4-element hash vs single 4-element hash."""
        a = (0, 0, 0, 0)
        b = (0, 0, 0, 0)
        assert compare_content_hashes(a, b) == 1.0


class TestCompareRotationInvariantPdq:
    def test_identical_hashes_score_1(self):
        h = (0,) * 32  # 8 orientations x 4 uint64
        result = _compare_rotation_invariant(h, h)
        assert result == 1.0

    def test_all_zero_vs_all_max(self):
        a = (0,) * 4
        b = (0xFFFFFFFFFFFFFFFF,) * 4
        result = _compare_rotation_invariant(a, b)
        assert result == 0.0

    def test_picks_best_orientation(self):
        """When one orientation matches, the min distance is used."""
        a = (0,) * 4  # canonical all-zero
        # B: 7 non-matching orientations, 8th matches A's canonical
        b_non = (0xFFFFFFFFFFFFFFFF,) * 4
        b = b_non * 7 + (0,) * 4  # 32 values total
        result = _compare_rotation_invariant(a, b)
        assert result == 1.0

    def test_symmetric(self):
        """compare(a, b) == compare(b, a)."""
        a = (1, 2, 3, 4) * 8
        b = (5, 6, 7, 8) * 8
        assert _compare_rotation_invariant(a, b) == _compare_rotation_invariant(b, a)

    def test_compare_content_hashes_rotation_flag(self):
        """rotation_invariant=True delegates to rotation comparison."""
        a = (0,) * 32
        b = (0xFFFFFFFFFFFFFFFF,) * 28 + (0,) * 4
        result = compare_content_hashes(a, b, rotation_invariant=True)
        assert result == 1.0


class TestSlidingWindowPdq:
    def test_prefix_match(self):
        """Match at the beginning (offset 0)."""
        frame = (0, 0, 0, 0)
        diff = (0xFFFFFFFFFFFFFFFF,) * 4
        short = np.array(frame, dtype=np.uint64).reshape(1, 4)
        long = np.array(frame + diff + diff, dtype=np.uint64).reshape(3, 4)
        result = _compare_content_hashes_sliding(short, long)
        assert result == 1.0

    def test_suffix_match(self):
        """Match at the end."""
        frame = (0, 0, 0, 0)
        diff = (0xFFFFFFFFFFFFFFFF,) * 4
        short = np.array(frame, dtype=np.uint64).reshape(1, 4)
        long = np.array(diff + diff + frame, dtype=np.uint64).reshape(3, 4)
        result = _compare_content_hashes_sliding(short, long)
        assert result == 1.0


# ---------------------------------------------------------------------------
# _hash_one_with_cache (PDQ)
# ---------------------------------------------------------------------------


class TestHashOneWithCachePdq:
    def test_cache_hit(self, make_metadata, tmp_path):
        """Cache hit returns metadata with cached hash, no extraction."""
        from duplicates_detector.content import _hash_one_with_cache

        m = make_metadata(path=str(tmp_path / "a.mp4"), duration=60.0)
        # Create the file so stat() works
        (tmp_path / "a.mp4").write_bytes(b"data")

        mock_cache = MagicMock()
        mock_cache.get_content_hash.return_value = (1, 2, 3, 4)

        result = _hash_one_with_cache(m, mock_cache)
        assert result.content_hash == (1, 2, 3, 4)
        mock_cache.get_content_hash.assert_called_once()

    def test_cache_miss_extracts(self, make_metadata, tmp_path):
        """Cache miss triggers extraction and stores result."""
        from duplicates_detector.content import _hash_one_with_cache

        m = make_metadata(path=str(tmp_path / "a.mp4"), duration=60.0)
        (tmp_path / "a.mp4").write_bytes(b"data")

        mock_cache = MagicMock()
        mock_cache.get_content_hash.return_value = None

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=(1, 2, 3, 4)):
            result = _hash_one_with_cache(m, mock_cache)
        assert result.content_hash == (1, 2, 3, 4)
        mock_cache.put_content_hash.assert_called_once()

    def test_no_cache(self, make_metadata, tmp_path):
        """Works without cache (cache_db=None)."""
        from duplicates_detector.content import _hash_one_with_cache

        m = make_metadata(path=str(tmp_path / "a.mp4"), duration=60.0)
        (tmp_path / "a.mp4").write_bytes(b"data")

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=(1, 2, 3, 4)):
            result = _hash_one_with_cache(m, None)
        assert result.content_hash == (1, 2, 3, 4)

    def test_is_image_uses_image_hash(self, make_metadata, tmp_path):
        """is_image=True uses compute_image_content_hash."""
        from duplicates_detector.content import _hash_one_with_cache

        m = make_metadata(path=str(tmp_path / "a.png"))
        (tmp_path / "a.png").write_bytes(b"data")

        with patch("duplicates_detector.content.compute_image_content_hash", return_value=(5, 6, 7, 8)):
            result = _hash_one_with_cache(m, None, is_image=True)
        assert result.content_hash == (5, 6, 7, 8)

    def test_oserror_returns_unchanged(self, make_metadata):
        """OSError from stat() returns metadata unchanged."""
        from duplicates_detector.content import _hash_one_with_cache

        m = make_metadata(path="/nonexistent/path.mp4")
        result = _hash_one_with_cache(m, None)
        assert result.content_hash is None

    def test_extraction_failure_no_cache_put(self, make_metadata, tmp_path):
        """When extraction returns None, cache.put is not called."""
        from duplicates_detector.content import _hash_one_with_cache

        m = make_metadata(path=str(tmp_path / "a.mp4"), duration=60.0)
        (tmp_path / "a.mp4").write_bytes(b"data")

        mock_cache = MagicMock()
        mock_cache.get_content_hash.return_value = None

        with patch("duplicates_detector.content._extract_sparse_hashes", return_value=None):
            result = _hash_one_with_cache(m, mock_cache)
        assert result.content_hash is None
        mock_cache.put_content_hash.assert_not_called()


# ---------------------------------------------------------------------------
# SSIM frame extraction and comparison
# ---------------------------------------------------------------------------


class TestExtractFramesFromFfmpeg:
    def test_returns_tuple_of_bytes(self):
        """Two concatenated PNG frames in stdout produce a 2-element tuple[bytes, ...]."""
        from duplicates_detector.content import _extract_frames_from_ffmpeg

        frame1 = _make_png_bytes((255, 0, 0))
        frame2 = _make_png_bytes((0, 255, 0))
        fake_stdout = frame1 + frame2

        mock_proc = _mock_popen(fake_stdout)
        with patch("duplicates_detector.content.subprocess.Popen", return_value=mock_proc):
            result = _extract_frames_from_ffmpeg(["ffmpeg", "-i", "test.mp4"], timeout=60)

        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(f, bytes) for f in result)

    def test_returns_none_on_failure(self):
        """OSError from Popen returns None."""
        from duplicates_detector.content import _extract_frames_from_ffmpeg

        with patch("duplicates_detector.content.subprocess.Popen", side_effect=OSError("not found")):
            result = _extract_frames_from_ffmpeg(["ffmpeg"], timeout=60)

        assert result is None

    def test_returns_none_on_timeout(self):
        """When the timeout fires, returns None."""
        from duplicates_detector.content import _extract_frames_from_ffmpeg

        frame = _make_png_bytes((128, 128, 128))
        mock_proc = _mock_popen(frame)

        real_timer_cls = threading.Timer

        def fake_timer(_interval, fn):
            fn()  # Fire immediately — sets timed_out and calls proc.kill()
            timer = real_timer_cls(0, lambda: None)
            timer.cancel()
            return timer

        with (
            patch("duplicates_detector.content.subprocess.Popen", return_value=mock_proc),
            patch("duplicates_detector.content.threading.Timer", side_effect=fake_timer),
        ):
            result = _extract_frames_from_ffmpeg(["ffmpeg"], timeout=60)

        assert result is None

    def test_returns_none_on_empty_output(self):
        """Empty ffmpeg output returns None."""
        from duplicates_detector.content import _extract_frames_from_ffmpeg

        mock_proc = _mock_popen(b"")
        with patch("duplicates_detector.content.subprocess.Popen", return_value=mock_proc):
            result = _extract_frames_from_ffmpeg(["ffmpeg"], timeout=60)

        assert result is None


class TestExtractFrames:
    def test_builds_correct_ffmpeg_command(self):
        """Verify the ffmpeg command includes fps=1/{interval}."""
        from duplicates_detector.content import extract_frames

        with patch("duplicates_detector.content._extract_frames_from_ffmpeg", return_value=None) as mock_extract:
            extract_frames(Path("test.mp4"), interval=3.0)

        cmd = mock_extract.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "fps=1/3.0" in cmd_str

    def test_returns_none_when_no_frames(self):
        """Returns None when _extract_frames_from_ffmpeg returns None."""
        from duplicates_detector.content import extract_frames

        with patch("duplicates_detector.content._extract_frames_from_ffmpeg", return_value=None):
            result = extract_frames(Path("test.mp4"))

        assert result is None


class TestExtractFramesScene:
    def test_scene_ffmpeg_command(self):
        """Scene extraction builds command with scene filter."""
        from duplicates_detector.content import extract_frames_scene

        frame = _make_png_bytes((128, 128, 128))
        frames_5 = (frame,) * 5

        with patch("duplicates_detector.content._extract_frames_from_ffmpeg", return_value=frames_5) as mock_extract:
            extract_frames_scene(Path("test.mp4"), threshold=0.4)

        cmd = mock_extract.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "gt(scene,0.4)" in cmd_str
        assert "-vsync" in cmd
        assert "vfr" in cmd

    def test_fallback_on_fewer_than_min_frames(self):
        """Falls back to extract_frames when scene yields < _MIN_SCENE_FRAMES frames."""
        from duplicates_detector.content import extract_frames_scene

        frame = _make_png_bytes((128, 128, 128))
        # Scene returns only 2 frames (< _MIN_SCENE_FRAMES = 3)
        scene_frames = (frame,) * 2
        fallback_frames = (frame,) * 5

        with (
            patch("duplicates_detector.content._extract_frames_from_ffmpeg", return_value=scene_frames),
            patch("duplicates_detector.content.extract_frames", return_value=fallback_frames) as mock_fallback,
        ):
            result = extract_frames_scene(Path("test.mp4"))

        mock_fallback.assert_called_once()
        assert result == fallback_frames

    def test_no_fallback_when_enough_frames(self):
        """Does not fall back when scene detection produces >= _MIN_SCENE_FRAMES frames."""
        from duplicates_detector.content import extract_frames_scene

        frame = _make_png_bytes((128, 128, 128))
        scene_frames = (frame,) * 5

        with (
            patch("duplicates_detector.content._extract_frames_from_ffmpeg", return_value=scene_frames),
            patch("duplicates_detector.content.extract_frames") as mock_fallback,
        ):
            result = extract_frames_scene(Path("test.mp4"))

        mock_fallback.assert_not_called()
        assert result == scene_frames


class TestExtractImageFrame:
    def test_real_png_file(self, tmp_path):
        """A real tiny PNG file returns a 1-tuple of bytes."""
        from duplicates_detector.content import extract_image_frame

        img_path = tmp_path / "tiny.png"
        img = Image.new("RGB", (4, 4), (100, 150, 200))
        img.save(str(img_path), format="PNG")

        result = extract_image_frame(img_path)

        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 1
        assert isinstance(result[0], bytes)
        # Verify it starts with PNG signature
        assert result[0][:8] == _PNG_SIGNATURE

    def test_missing_file(self):
        """Nonexistent path returns None."""
        from duplicates_detector.content import extract_image_frame

        result = extract_image_frame(Path("/nonexistent/path/to/image.png"))

        assert result is None


class TestCompareSsimFrames:
    def test_identical_returns_high_score(self):
        """Two identical PNG images produce a score close to 1.0."""
        pytest.importorskip("skimage")
        from duplicates_detector.content import compare_ssim_frames

        frame = _make_png_bytes((128, 128, 128), size=(64, 64))
        result = compare_ssim_frames((frame,), (frame,))
        assert result == pytest.approx(1.0, abs=0.05)

    def test_different_returns_low_score(self):
        """White vs black images produce a low score."""
        pytest.importorskip("skimage")
        from duplicates_detector.content import compare_ssim_frames

        white = _make_png_bytes((255, 255, 255), size=(64, 64))
        black = _make_png_bytes((0, 0, 0), size=(64, 64))
        result = compare_ssim_frames((white,), (black,))
        assert result < 0.5

    def test_empty_returns_zero(self):
        """Empty tuples return 0.0."""
        pytest.importorskip("skimage")
        from duplicates_detector.content import compare_ssim_frames

        assert compare_ssim_frames((), ()) == 0.0
        assert compare_ssim_frames((), (_make_png_bytes(),)) == 0.0
        assert compare_ssim_frames((_make_png_bytes(),), ()) == 0.0

    def test_sliding_window(self):
        """Short=(1 frame), long=(3 frames, middle matching) produces score > 0."""
        pytest.importorskip("skimage")
        from duplicates_detector.content import compare_ssim_frames

        matching = _make_png_bytes((128, 128, 128), size=(64, 64))
        different1 = _make_png_bytes((0, 0, 0), size=(64, 64))
        different2 = _make_png_bytes((255, 255, 255), size=(64, 64))

        short = (matching,)
        long = (different1, matching, different2)

        result = compare_ssim_frames(short, long)
        assert result > 0

    def test_scikit_image_missing(self):
        """When skimage is not importable, compare_ssim_frames raises an error."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "skimage.metrics" or name == "skimage":
                raise ImportError("No module named 'skimage'")
            return real_import(name, *args, **kwargs)

        from duplicates_detector.content import compare_ssim_frames

        frame = _make_png_bytes((128, 128, 128), size=(64, 64))

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                compare_ssim_frames((frame,), (frame,))

    def test_corrupt_frame_skipped(self):
        """Malformed PNG bytes are skipped rather than crashing."""
        pytest.importorskip("skimage")
        from duplicates_detector.content import compare_ssim_frames

        good = _make_png_bytes((128, 128, 128), size=(64, 64))
        corrupt = b"\x89PNG\r\n\x1a\nGARBAGE"
        # Mixed good + corrupt should still produce a score from the good frames
        result = compare_ssim_frames((good, corrupt), (good,))
        assert result > 0.5

    def test_all_corrupt_returns_zero(self):
        """If all frames are corrupt, returns 0.0 instead of crashing."""
        pytest.importorskip("skimage")
        from duplicates_detector.content import compare_ssim_frames

        corrupt = b"\x89PNG\r\n\x1a\nGARBAGE"
        result = compare_ssim_frames((corrupt,), (corrupt,))
        assert result == 0.0


class TestExtractAllSsimFrames:
    def test_populates_content_frames(self, make_metadata):
        """content_frames is populated on returned metadata."""
        from duplicates_detector.content import extract_all_ssim_frames

        m = make_metadata(path="a.mp4", duration=60.0)
        frame = _make_png_bytes((128, 128, 128))
        mock_frames = (frame, frame, frame)

        with (
            patch("duplicates_detector.content.check_ffmpeg"),
            patch("duplicates_detector.content.extract_frames", return_value=mock_frames),
        ):
            results = extract_all_ssim_frames([m], workers=1, quiet=True)

        assert len(results) == 1
        assert results[0].content_frames == mock_frames


class TestExtractAllImageSsimFrames:
    def test_populates_content_frames(self, make_metadata):
        """content_frames is populated on returned metadata."""
        from duplicates_detector.content import extract_all_image_ssim_frames

        m = make_metadata(path="a.png")
        frame = _make_png_bytes((128, 128, 128))
        mock_frames = (frame,)

        with patch("duplicates_detector.content.extract_image_frame", return_value=mock_frames):
            results = extract_all_image_ssim_frames([m], workers=1, quiet=True)

        assert len(results) == 1
        assert results[0].content_frames == mock_frames


class TestComputePreHash:
    def test_normal_file(self, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        data = b"x" * 8192
        p.write_bytes(data)
        result = compute_pre_hash(p)
        assert result == hashlib.md5(data[:4096]).hexdigest()

    def test_file_smaller_than_4kb(self, tmp_path: Path) -> None:
        p = tmp_path / "tiny.mp4"
        data = b"tiny content"
        p.write_bytes(data)
        result = compute_pre_hash(p)
        assert result == hashlib.md5(data).hexdigest()

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.mp4"
        p.write_bytes(b"")
        result = compute_pre_hash(p)
        assert result == hashlib.md5(b"").hexdigest()

    def test_unreadable_file(self, tmp_path: Path) -> None:
        p = tmp_path / "nope.mp4"
        result = compute_pre_hash(p)
        assert result is None


class TestSyntheticContentHash:
    def test_returns_4_element_tuple(self) -> None:
        result = _synthetic_content_hash("d41d8cd98f00b204e9800998ecf8427e")
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_all_elements_are_ints(self) -> None:
        result = _synthetic_content_hash("d41d8cd98f00b204e9800998ecf8427e")
        assert all(isinstance(x, int) for x in result)

    def test_deterministic(self) -> None:
        hex_str = "d41d8cd98f00b204e9800998ecf8427e"
        assert _synthetic_content_hash(hex_str) == _synthetic_content_hash(hex_str)

    def test_different_inputs_produce_different_hashes(self) -> None:
        a = _synthetic_content_hash("d41d8cd98f00b204e9800998ecf8427e")
        b = _synthetic_content_hash("098f6bcd4621d373cade4e832627b4f6")
        assert a != b

    def test_repeated_halves(self) -> None:
        result = _synthetic_content_hash("d41d8cd98f00b204e9800998ecf8427e")
        assert result[0] == result[2]
        assert result[1] == result[3]


class TestPreHashOneWithCache:
    def test_cache_miss_computes_and_stores(self, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"x" * 8192)
        st = p.stat()
        meta = VideoMetadata(
            path=p,
            filename="video",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st.st_size,
            mtime=st.st_mtime,
        )
        cache = MagicMock()
        cache.get_pre_hash.return_value = None
        result = _pre_hash_one_with_cache(meta, cache)
        assert result.pre_hash is not None
        cache.put_pre_hash.assert_called_once()

    def test_cache_hit_skips_computation(self, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"x" * 8192)
        st = p.stat()
        meta = VideoMetadata(
            path=p,
            filename="video",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st.st_size,
            mtime=st.st_mtime,
        )
        cache = MagicMock()
        cache.get_pre_hash.return_value = "cached_hash"
        with patch("duplicates_detector.content.compute_pre_hash") as mock_compute:
            result = _pre_hash_one_with_cache(meta, cache)
        assert result.pre_hash == "cached_hash"
        mock_compute.assert_not_called()
        cache.put_pre_hash.assert_not_called()

    def test_no_cache_db(self, tmp_path: Path) -> None:
        p = tmp_path / "video.mp4"
        p.write_bytes(b"data")
        st = p.stat()
        meta = VideoMetadata(
            path=p,
            filename="video",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=st.st_size,
            mtime=st.st_mtime,
        )
        result = _pre_hash_one_with_cache(meta, None)
        assert result.pre_hash is not None

    def test_stat_failure_returns_unchanged(self, tmp_path: Path) -> None:
        p = tmp_path / "gone.mp4"
        meta = VideoMetadata(
            path=p,
            filename="gone",
            duration=10.0,
            width=1920,
            height=1080,
            file_size=0,
            mtime=0.0,
        )
        result = _pre_hash_one_with_cache(meta, None)
        assert result.pre_hash is None
