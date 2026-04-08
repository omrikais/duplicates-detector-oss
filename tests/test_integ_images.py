"""Integration tests for exotic image formats: HEIC, AVIF, 50MP+, 16-bit, animated WebP."""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.content import compare_content_hashes, compute_image_content_hash
from duplicates_detector.metadata import extract_one_image

from conftest import _get_integ_generators, _require_integ_file

pytestmark = pytest.mark.slow

_gen = _get_integ_generators()


@pytest.fixture(scope="session")
def exotic_images(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
    d = tmp_path_factory.mktemp("exotic_images")
    files = _gen.generate_exotic_images(d)
    if not any(files.values()):
        pytest.skip("No exotic images could be generated")
    return files


class TestExoticImageMetadata:
    def test_heic_metadata(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "heic_image")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 256
        assert meta.height == 256

    def test_avif_metadata(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "avif_image")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 256

    def test_50mp_metadata(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "large_50mp_image")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 7072
        assert meta.height == 7072

    def test_16bit_png_metadata(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "16bit_png")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 256

    def test_animated_webp_metadata(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "webp_animated")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 128

    def test_tiff_metadata_and_exif(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "tiff_with_exif")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 256
        # Verify EXIF fields were extracted (may be None if PIL couldn't write EXIF)
        # exif_datetime is float (epoch seconds), not string
        if meta.exif_datetime is not None:
            import datetime

            dt = datetime.datetime.fromtimestamp(meta.exif_datetime, tz=datetime.timezone.utc)
            assert dt.year == 2025
        if meta.exif_camera is not None:
            assert "testcamera" in meta.exif_camera.lower()

    def test_bmp_metadata(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "bmp_uncompressed")
        meta = extract_one_image(path)
        assert meta is not None
        assert meta.width == 512
        assert meta.height == 512


class TestExoticImageContentHashing:
    def test_50mp_hash_no_oom(self, exotic_images: dict[str, Path | None]) -> None:
        """50MP image hashing completes without OOM, in reasonable time."""
        path = _require_integ_file(exotic_images, "large_50mp_image")
        h = compute_image_content_hash(path)
        assert h is not None
        assert len(h) > 0

    def test_16bit_png_hash(self, exotic_images: dict[str, Path | None]) -> None:
        """16-bit PNG should be converted to 8-bit for PDQ hashing."""
        path = _require_integ_file(exotic_images, "16bit_png")
        h = compute_image_content_hash(path)
        assert h is not None

    def test_animated_webp_hash(self, exotic_images: dict[str, Path | None]) -> None:
        """Animated WebP — first frame extracted for hashing."""
        path = _require_integ_file(exotic_images, "webp_animated")
        h = compute_image_content_hash(path)
        assert h is not None

    def test_bmp_hash(self, exotic_images: dict[str, Path | None]) -> None:
        path = _require_integ_file(exotic_images, "bmp_uncompressed")
        h = compute_image_content_hash(path)
        assert h is not None


class TestCrossFormatImageDuplicates:
    @pytest.fixture(scope="class")
    def cross_format_images(self, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
        """Generate same image content in JPEG, PNG, and WebP."""
        from PIL import Image

        d = tmp_path_factory.mktemp("cross_format_img")
        result: dict[str, Path | None] = {}

        img = Image.new("RGB", (256, 256))
        pixels = img.load()
        assert pixels is not None
        for y in range(256):
            for x in range(256):
                pixels[x, y] = ((x * 7 + y * 13) % 256, (x * 11 + y * 3) % 256, (x * 5 + y * 17) % 256)

        try:
            p = d / "source.jpg"
            img.save(str(p), "JPEG", quality=95)
            result["jpeg"] = p
        except Exception:
            result["jpeg"] = None

        try:
            p = d / "source.png"
            img.save(str(p), "PNG")
            result["png"] = p
        except Exception:
            result["png"] = None

        try:
            p = d / "source.webp"
            img.save(str(p), "WEBP", quality=95)
            result["webp"] = p
        except Exception:
            result["webp"] = None

        return result

    def test_jpeg_vs_png_high_similarity(self, cross_format_images: dict[str, Path | None]) -> None:
        jpeg = cross_format_images.get("jpeg")
        png = cross_format_images.get("png")
        if jpeg is None or png is None:
            pytest.skip("Need both JPEG and PNG")
        hash_a = compute_image_content_hash(jpeg)
        hash_b = compute_image_content_hash(png)
        assert hash_a is not None and hash_b is not None
        similarity = compare_content_hashes(hash_a, hash_b)
        assert similarity > 0.8, f"JPEG vs PNG similarity too low: {similarity}"

    def test_jpeg_vs_webp_high_similarity(self, cross_format_images: dict[str, Path | None]) -> None:
        jpeg = cross_format_images.get("jpeg")
        webp = cross_format_images.get("webp")
        if jpeg is None or webp is None:
            pytest.skip("Need both JPEG and WebP")
        hash_a = compute_image_content_hash(jpeg)
        hash_b = compute_image_content_hash(webp)
        assert hash_a is not None and hash_b is not None
        similarity = compare_content_hashes(hash_a, hash_b)
        assert similarity > 0.8, f"JPEG vs WebP similarity too low: {similarity}"
