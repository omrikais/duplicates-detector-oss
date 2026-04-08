"""Edge-case tests: ultra-short videos (< 1 second).

Validates that very short videos produce valid hashes via PDQ,
don't cause division-by-zero, and score correctly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from duplicates_detector.comparators import DurationComparator
from duplicates_detector.content import (
    _extract_sparse_hashes,
    _FRAME_BYTES,
    _FRAME_SIZE,
    _HASH_UINT64S,
    _NUM_FRAMES,
)
from duplicates_detector.scorer import _bucket_by_duration


# ---------------------------------------------------------------------------
# Ultra-short video content hashing
# ---------------------------------------------------------------------------


class TestUltraShortVideoContentHash:
    def test_zero_duration_returns_none(self):
        """duration=0.0 → _extract_sparse_hashes returns None (no timestamps)."""
        result = _extract_sparse_hashes(Path("zero.mp4"), duration=0.0)
        assert result is None

    def test_none_duration_returns_none(self):
        """duration=None → _extract_sparse_hashes returns None."""
        result = _extract_sparse_hashes(Path("nodur.mp4"), duration=None)
        assert result is None

    def test_negative_duration_returns_none(self):
        """duration=-1.0 → _extract_sparse_hashes returns None."""
        result = _extract_sparse_hashes(Path("neg.mp4"), duration=-1.0)
        assert result is None

    def test_short_video_produces_hash_when_ffmpeg_succeeds(self):
        """0.5s video → ffmpeg returns valid rawvideo data → valid hash."""
        # Generate valid 64x64 RGB rawvideo bytes
        raw_frame = np.random.randint(0, 255, (_FRAME_SIZE, _FRAME_SIZE, 3), dtype=np.uint8).tobytes()
        mock_result = MagicMock()
        mock_result.stdout = raw_frame

        with patch("duplicates_detector.content.subprocess.run", return_value=mock_result):
            result = _extract_sparse_hashes(Path("short.mp4"), duration=0.5)

        assert result is not None
        # 10 frames × 4 uint64 per frame = 40 values
        assert len(result) == _NUM_FRAMES * _HASH_UINT64S

    def test_single_frame_hash_is_four_tuple(self):
        """One successful frame → hash contains 4 uint64 values for that frame."""
        from duplicates_detector.content import _extract_single_frame_hash

        raw_frame = np.random.randint(0, 255, (_FRAME_SIZE, _FRAME_SIZE, 3), dtype=np.uint8).tobytes()
        mock_result = MagicMock()
        mock_result.stdout = raw_frame

        with patch("duplicates_detector.content.subprocess.run", return_value=mock_result):
            result = _extract_single_frame_hash(Path("single.mp4"), 0.5)

        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == _HASH_UINT64S
        assert all(isinstance(v, int) for v in result)


# ---------------------------------------------------------------------------
# Ultra-short video scoring
# ---------------------------------------------------------------------------


class TestUltraShortVideoScoring:
    def test_duration_bucket_for_sub_second(self, make_metadata):
        """duration=0.1 and 0.2 → both in same bucket (within ±2s tolerance)."""
        items = [
            make_metadata(path="a.mp4", duration=0.1),
            make_metadata(path="b.mp4", duration=0.2),
        ]
        buckets = _bucket_by_duration(items, tolerance=2.0)
        assert len(buckets) == 1
        assert len(buckets[0]) == 2

    def test_duration_comparator_both_zero(self, make_metadata):
        """Both videos duration=0.0 → duration score = 1.0 (identical)."""
        a = make_metadata(path="a.mp4", duration=0.0)
        b = make_metadata(path="b.mp4", duration=0.0)
        comp = DurationComparator()
        score = comp.score(a, b)
        assert score == 1.0

    def test_duration_comparator_zero_vs_nonzero(self, make_metadata):
        """0.0 vs 60.0 → duration score = 0.0 (diff >= MAX_DIFF)."""
        a = make_metadata(path="a.mp4", duration=0.0)
        b = make_metadata(path="b.mp4", duration=60.0)
        comp = DurationComparator()
        score = comp.score(a, b)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Ultra-short scene detection (SSIM path)
# ---------------------------------------------------------------------------


class TestUltraShortSceneDetection:
    def test_scene_detection_short_video_falls_back(self):
        """Scene detection finds < 3 frames → falls back to interval-based."""
        from io import BytesIO

        from PIL import Image

        from duplicates_detector.content import extract_frames_scene

        single_frame = Image.new("RGB", (8, 8), (128, 128, 128))
        buf = BytesIO()
        single_frame.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        call_count = 0

        def mock_popen_factory(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = MagicMock()
            mock_proc.stdout = BytesIO(png_bytes if call_count == 1 else png_bytes + png_bytes + png_bytes)
            mock_proc.wait.return_value = 0
            return mock_proc

        with patch("duplicates_detector.content.subprocess.Popen", side_effect=mock_popen_factory):
            result = extract_frames_scene(
                Path("short.mp4"),
                threshold=0.3,
                duration=1.0,
            )

        assert call_count == 2  # Scene detection + interval fallback
        assert result is not None
