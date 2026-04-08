"""Integration tests for codec edge cases.

Each test skips if its codec isn't compiled into the system ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.content import _extract_sparse_hashes, compare_content_hashes
from duplicates_detector.metadata import extract_one

from conftest import _get_integ_generators, _require_integ_file

pytestmark = pytest.mark.slow

_gen = _get_integ_generators()


@pytest.fixture(scope="session")
def codec_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
    d = tmp_path_factory.mktemp("codecs")
    files = _gen.generate_codec_variants(d)
    if not any(files.values()):
        pytest.skip("No codec variants could be generated")
    return files


class TestCodecExtraction:
    def test_hevc_10bit_metadata(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "hevc_10bit")
        meta = extract_one(path)
        assert meta is not None
        assert meta.width == 320
        assert meta.height == 240
        assert meta.duration is not None and meta.duration > 0

    def test_hevc_10bit_content_hash(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "hevc_10bit")
        meta = extract_one(path)
        assert meta is not None and meta.duration is not None
        h = _extract_sparse_hashes(path, meta.duration)
        assert h is not None
        assert len(h) > 0

    def test_vp9_webm_metadata(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "vp9_webm")
        meta = extract_one(path)
        assert meta is not None
        assert meta.width == 320
        assert meta.height == 240

    def test_vp9_webm_content_hash(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "vp9_webm")
        meta = extract_one(path)
        assert meta is not None and meta.duration is not None
        h = _extract_sparse_hashes(path, meta.duration)
        assert h is not None

    def test_av1_mp4_metadata(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "av1_mp4")
        meta = extract_one(path)
        assert meta is not None
        assert meta.width == 320

    def test_prores_mov_metadata(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "prores_mov")
        meta = extract_one(path)
        assert meta is not None
        assert meta.duration is not None and meta.duration > 0

    def test_mjpeg_avi_metadata(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "mjpeg_avi")
        meta = extract_one(path)
        assert meta is not None
        assert meta.width == 320

    def test_mjpeg_avi_content_hash(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "mjpeg_avi")
        meta = extract_one(path)
        assert meta is not None and meta.duration is not None
        h = _extract_sparse_hashes(path, meta.duration)
        assert h is not None

    def test_pcm_wav_video_metadata(self, codec_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(codec_media, "pcm_wav_video")
        meta = extract_one(path)
        assert meta is not None
        assert meta.duration is not None and meta.duration > 0


class TestCrossCodecDuplicateDetection:
    """Verify that same-content files encoded with different codecs
    produce high content similarity scores."""

    @pytest.fixture(scope="class")
    def cross_codec_media(self, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
        """Generate a base H.264 video and re-encode it with available codecs."""
        _has_encoder = _gen._has_encoder
        _has_ffmpeg = _gen._has_ffmpeg
        _run_ffmpeg = _gen._run_ffmpeg

        if not _has_ffmpeg():
            pytest.skip("ffmpeg unavailable")

        d = tmp_path_factory.mktemp("cross_codec")
        result: dict[str, Path | None] = {}

        # Base H.264
        base = d / "base_h264.mp4"
        if not _run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=3:size=320x240:rate=24",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "18",
                str(base),
            ]
        ):
            pytest.skip("Cannot create base video")
        result["h264"] = base

        # Re-encode to HEVC
        if _has_encoder("libx265"):
            p = d / "reenc_hevc.mp4"
            if _run_ffmpeg(["-i", str(base), "-c:v", "libx265", "-preset", "ultrafast", str(p)]):
                result["hevc"] = p
            else:
                result["hevc"] = None
        else:
            result["hevc"] = None

        # Re-encode to VP9
        if _has_encoder("libvpx-vp9"):
            p = d / "reenc_vp9.webm"
            if _run_ffmpeg(["-i", str(base), "-c:v", "libvpx-vp9", "-b:v", "1M", str(p)]):
                result["vp9"] = p
            else:
                result["vp9"] = None
        else:
            result["vp9"] = None

        return result

    def test_hevc_vs_h264_high_similarity(self, cross_codec_media: dict[str, Path | None]) -> None:
        h264_path = cross_codec_media.get("h264")
        hevc_path = cross_codec_media.get("hevc")
        if h264_path is None or hevc_path is None:
            pytest.skip("Need both h264 and hevc for cross-codec test")

        meta_a = extract_one(h264_path)
        meta_b = extract_one(hevc_path)
        assert meta_a is not None and meta_a.duration is not None
        assert meta_b is not None and meta_b.duration is not None

        hash_a = _extract_sparse_hashes(h264_path, meta_a.duration)
        hash_b = _extract_sparse_hashes(hevc_path, meta_b.duration)
        assert hash_a is not None and hash_b is not None

        similarity = compare_content_hashes(hash_a, hash_b)
        assert similarity > 0.5, f"Cross-codec similarity too low: {similarity}"

    def test_vp9_vs_h264_high_similarity(self, cross_codec_media: dict[str, Path | None]) -> None:
        h264_path = cross_codec_media.get("h264")
        vp9_path = cross_codec_media.get("vp9")
        if h264_path is None or vp9_path is None:
            pytest.skip("Need both h264 and vp9 for cross-codec test")

        meta_a = extract_one(h264_path)
        meta_b = extract_one(vp9_path)
        assert meta_a is not None and meta_a.duration is not None
        assert meta_b is not None and meta_b.duration is not None

        hash_a = _extract_sparse_hashes(h264_path, meta_a.duration)
        hash_b = _extract_sparse_hashes(vp9_path, meta_b.duration)
        assert hash_a is not None and hash_b is not None

        similarity = compare_content_hashes(hash_a, hash_b)
        assert similarity > 0.5, f"Cross-codec similarity too low: {similarity}"
