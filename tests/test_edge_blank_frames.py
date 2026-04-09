"""Edge-case tests: black/blank frames (all-zero hashes).

Validates that videos consisting entirely of black, white, or solid-color
frames produce consistent hashes and score correctly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from duplicates_detector.content import (
    _pack_pdq_hash,
    compare_content_hashes,
    compute_image_content_hash,
    _HASH_UINT64S,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdq_hash_from_color(color: tuple[int, int, int], size: int = 64) -> tuple[int, ...]:
    """Compute a PDQ hash for a solid-color image."""
    import pdqhash

    arr = np.full((size, size, 3), color, dtype=np.uint8)
    hv, _quality = pdqhash.compute(arr)
    return _pack_pdq_hash(hv)


def _make_multi_frame_hash(*hashes: tuple[int, ...]) -> tuple[int, ...]:
    """Concatenate per-frame hashes into a multi-frame hash tuple."""
    return tuple(v for h in hashes for v in h)


# ---------------------------------------------------------------------------
# Blank frame content hashing
# ---------------------------------------------------------------------------


class TestBlankFrameContentHashing:
    def test_all_black_frames_produce_consistent_hash(self):
        """All-black (0,0,0) → consistent hash across calls."""
        h1 = _make_pdq_hash_from_color((0, 0, 0))
        h2 = _make_pdq_hash_from_color((0, 0, 0))
        assert h1 is not None
        assert len(h1) == _HASH_UINT64S
        assert h1 == h2

    def test_all_white_frames_produce_consistent_hash(self):
        """All-white (255,255,255) → consistent hash."""
        h1 = _make_pdq_hash_from_color((255, 255, 255))
        h2 = _make_pdq_hash_from_color((255, 255, 255))
        assert h1 is not None
        assert h1 == h2

    def test_all_black_vs_all_white_different_hash(self):
        """Black hash != white hash."""
        h_black = _make_pdq_hash_from_color((0, 0, 0))
        h_white = _make_pdq_hash_from_color((255, 255, 255))
        assert h_black is not None
        assert h_white is not None
        assert h_black != h_white

    def test_two_all_black_videos_score_identical(self):
        """Both all-black → content similarity = 1.0."""
        black_hash = _make_pdq_hash_from_color((0, 0, 0))
        hash_a = _make_multi_frame_hash(black_hash, black_hash, black_hash)
        hash_b = _make_multi_frame_hash(black_hash, black_hash, black_hash)

        similarity = compare_content_hashes(hash_a, hash_b)
        assert similarity == 1.0

    def test_all_black_vs_normal_video_scores_low(self):
        """All-black vs complex frames → content similarity low."""
        black_hash = _make_pdq_hash_from_color((0, 0, 0))
        # Create a complex image hash
        import pdqhash

        complex_arr = np.zeros((64, 64, 3), dtype=np.uint8)
        for x in range(64):
            for y in range(64):
                complex_arr[y, x] = (x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256)
        complex_hv, _ = pdqhash.compute(complex_arr)
        complex_hash = _pack_pdq_hash(complex_hv)

        hash_black = _make_multi_frame_hash(black_hash, black_hash, black_hash)
        hash_complex = _make_multi_frame_hash(complex_hash, complex_hash, complex_hash)

        similarity = compare_content_hashes(hash_black, hash_complex)
        assert similarity < 1.0

    def test_mixed_black_and_normal_frames(self):
        """Video with black + normal frames → hash differs from pure black."""
        black_hash = _make_pdq_hash_from_color((0, 0, 0))
        import pdqhash

        complex_arr = np.zeros((64, 64, 3), dtype=np.uint8)
        for x in range(64):
            for y in range(64):
                complex_arr[y, x] = (x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256)
        complex_hv, _ = pdqhash.compute(complex_arr)
        complex_hash = _pack_pdq_hash(complex_hv)

        hash_mixed = _make_multi_frame_hash(black_hash, complex_hash, black_hash)
        hash_black = _make_multi_frame_hash(black_hash, black_hash, black_hash)

        assert hash_mixed != hash_black

    def test_single_black_frame_hash(self):
        """1-frame all-black → valid 4-tuple hash (not None)."""
        result = _make_pdq_hash_from_color((0, 0, 0))
        assert result is not None
        assert len(result) == _HASH_UINT64S


# ---------------------------------------------------------------------------
# Blank frame SSIM
# ---------------------------------------------------------------------------


def _make_png_bytes(color: tuple[int, int, int] = (128, 128, 128), size: tuple[int, int] = (64, 64)) -> bytes:
    from io import BytesIO

    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_complex_png(size: tuple[int, int] = (64, 64)) -> bytes:
    """Create a complex image with gradients for distinct hashes."""
    from io import BytesIO

    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestBlankFrameSSIM:
    @pytest.fixture(autouse=True)
    def _require_skimage(self):
        pytest.importorskip("skimage")

    def test_identical_black_frames_ssim_one(self):
        """Two sets of all-black PNG frames → SSIM ~ 1.0."""
        from duplicates_detector.content import compare_ssim_frames

        black = _make_png_bytes((0, 0, 0), size=(64, 64))
        frames_a = (black, black, black)
        frames_b = (black, black, black)
        score = compare_ssim_frames(frames_a, frames_b)
        assert score >= 0.99

    def test_identical_white_frames_ssim_one(self):
        """Two sets of all-white → SSIM ~ 1.0."""
        from duplicates_detector.content import compare_ssim_frames

        white = _make_png_bytes((255, 255, 255), size=(64, 64))
        frames_a = (white, white, white)
        frames_b = (white, white, white)
        score = compare_ssim_frames(frames_a, frames_b)
        assert score >= 0.99

    def test_black_vs_white_ssim_low(self):
        """All-black vs all-white → SSIM low."""
        from duplicates_detector.content import compare_ssim_frames

        black = _make_png_bytes((0, 0, 0), size=(64, 64))
        white = _make_png_bytes((255, 255, 255), size=(64, 64))
        frames_a = (black, black)
        frames_b = (white, white)
        score = compare_ssim_frames(frames_a, frames_b)
        assert score < 0.5

    def test_black_vs_normal_ssim_low(self):
        """All-black vs complex frames → SSIM low."""
        from duplicates_detector.content import compare_ssim_frames

        black = _make_png_bytes((0, 0, 0), size=(64, 64))
        complex_frame = _make_complex_png(size=(64, 64))
        frames_a = (black, black)
        frames_b = (complex_frame, complex_frame)
        score = compare_ssim_frames(frames_a, frames_b)
        assert score < 0.5

    def test_single_pixel_difference_ssim_high(self):
        """Nearly-black (1 pixel differs) vs all-black → SSIM > 0.95."""
        from duplicates_detector.content import compare_ssim_frames
        from io import BytesIO

        # Create all-black 64x64 image
        black_img = Image.new("RGB", (64, 64), (0, 0, 0))
        buf1 = BytesIO()
        black_img.save(buf1, format="PNG")
        black = buf1.getvalue()

        # Create nearly-black (1 pixel is white)
        near_black_img = Image.new("RGB", (64, 64), (0, 0, 0))
        near_black_img.putpixel((32, 32), (255, 255, 255))
        buf2 = BytesIO()
        near_black_img.save(buf2, format="PNG")
        near_black = buf2.getvalue()

        frames_a = (black, black)
        frames_b = (near_black, near_black)
        score = compare_ssim_frames(frames_a, frames_b)
        assert score > 0.95


# ---------------------------------------------------------------------------
# Blank frame image mode
# ---------------------------------------------------------------------------


class TestBlankFrameImageMode:
    def test_solid_color_image_hash_consistent(self, tmp_path: Path):
        """Solid red image → consistent hash."""
        f = tmp_path / "red.png"
        img = Image.new("RGB", (64, 64), (255, 0, 0))
        img.save(f)
        h1 = compute_image_content_hash(f)
        h2 = compute_image_content_hash(f)
        assert h1 is not None
        assert h1 == h2

    def test_two_solid_same_color_score_identical(self, tmp_path: Path):
        """Two solid red images → content similarity = 1.0."""
        f1 = tmp_path / "red1.png"
        f2 = tmp_path / "red2.png"
        img = Image.new("RGB", (64, 64), (255, 0, 0))
        img.save(f1)
        img.save(f2)
        h1 = compute_image_content_hash(f1)
        h2 = compute_image_content_hash(f2)
        assert h1 is not None
        assert h2 is not None
        similarity = compare_content_hashes(h1, h2)
        assert similarity == 1.0

    def test_solid_vs_complex_image_scores_low(self, tmp_path: Path):
        """Solid red vs complex image → low similarity."""
        f_solid = tmp_path / "solid.png"
        f_complex = tmp_path / "complex.png"
        Image.new("RGB", (64, 64), (255, 0, 0)).save(f_solid)

        # Create complex image
        complex_img = Image.new("RGB", (64, 64))
        for x in range(64):
            for y in range(64):
                complex_img.putpixel((x, y), (x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256))
        complex_img.save(f_complex)

        h_solid = compute_image_content_hash(f_solid)
        h_complex = compute_image_content_hash(f_complex)
        assert h_solid is not None
        assert h_complex is not None
        similarity = compare_content_hashes(h_solid, h_complex)
        assert similarity < 1.0

    def test_rotation_invariant_solid_color(self, tmp_path: Path):
        """Solid color image → rotation-invariant hash has 32 uint64 values (8 orientations x 4)."""
        f = tmp_path / "solid.png"
        Image.new("RGB", (64, 64), (0, 255, 0)).save(f)
        result = compute_image_content_hash(f, rotation_invariant=True)
        assert result is not None
        # 8 orientations x 4 uint64 = 32
        assert len(result) == 32
        # All values should be integers
        assert all(isinstance(v, int) for v in result)
