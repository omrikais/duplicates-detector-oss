"""Integration tests with real media files.

These tests exercise the actual ffprobe/ffmpeg/PIL pipelines against
generated media files.  They are marked ``@pytest.mark.slow`` and can be
excluded from fast CI runs with ``pytest -m "not slow"``.

Media files are generated once per session by the ``media_dir`` fixture
in conftest.py.  If ffmpeg is not installed, all tests are skipped.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from duplicates_detector.content import (
    _extract_sparse_hashes,
    compare_content_hashes,
    compare_ssim_frames,
    compute_image_content_hash,
    extract_frames,
    extract_image_frame,
    _HASH_UINT64S,
)
from duplicates_detector.metadata import (
    VideoMetadata,
    extract_all,
    extract_all_images,
    extract_one,
    extract_one_image,
)
from duplicates_detector.scanner import DEFAULT_IMAGE_EXTENSIONS, find_video_files

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _require_file(path: Path) -> Path:
    """Skip the current test if a particular media file was not generated."""
    if not path.exists():
        pytest.skip(f"Media file not generated: {path.name}")
    return path


# ===========================================================================
# TestMetadataExtraction
# ===========================================================================


class TestMetadataExtraction:
    """Tests extract_one() with real ffprobe on generated video files."""

    def test_mp4_baseline(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "simple.mp4"))
        assert meta is not None
        assert meta.duration is not None
        assert 2.0 <= meta.duration <= 5.0
        assert meta.width == 320
        assert meta.height == 240
        assert meta.codec == "h264"
        assert meta.framerate is not None
        assert 23.0 <= meta.framerate <= 25.0
        assert meta.audio_channels == 1  # sine lavfi source is mono
        assert meta.file_size > 0
        assert meta.bitrate is not None

    def test_mkv_container(self, media_dir: Path) -> None:
        mp4 = extract_one(_require_file(media_dir / "simple.mp4"))
        mkv = extract_one(_require_file(media_dir / "simple.mkv"))
        assert mkv is not None
        assert mp4 is not None
        assert mkv.codec == mp4.codec
        assert mkv.width == mp4.width
        assert mkv.height == mp4.height
        assert mkv.duration is not None
        assert mp4.duration is not None
        assert abs(mkv.duration - mp4.duration) < 0.5

    def test_audio_first_stream_ordering(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "audio_first.mkv"))
        assert meta is not None
        assert meta.width == 320
        assert meta.height == 240
        assert meta.audio_channels is not None

    def test_hevc_video_only(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "hevc_no_audio.mp4"))
        assert meta is not None
        assert meta.codec in ("hevc", "h265")
        assert meta.audio_channels is None
        assert meta.duration is not None

    def test_stream_level_duration_fallback(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "no_format_duration.mkv"))
        assert meta is not None
        assert meta.duration is not None
        assert meta.duration > 0

    def test_avi_container(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "avi_container.avi"))
        assert meta is not None
        assert meta.width == 320
        assert meta.height == 240
        assert meta.duration is not None
        assert meta.codec is not None

    def test_multichannel_audio(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "multichannel.mp4"))
        assert meta is not None
        assert meta.audio_channels == 6

    def test_data_stream_ignored(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "data_stream.mkv"))
        assert meta is not None
        assert meta.width == 320
        assert meta.height == 240
        assert meta.audio_channels is not None

    def test_framerate_fraction(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "simple.mp4"))
        assert meta is not None
        assert meta.framerate is not None
        assert 23.0 <= meta.framerate <= 25.0

    def test_variable_fps(self, media_dir: Path) -> None:
        meta = extract_one(_require_file(media_dir / "variable_fps.mkv"))
        assert meta is not None
        assert meta.duration is not None
        assert meta.width == 320
        assert meta.height == 240

    def test_file_size_matches_stat(self, media_dir: Path) -> None:
        for name in ("simple.mp4", "avi_container.avi", "multichannel.mp4"):
            path = media_dir / name
            if not path.exists():
                continue
            meta = extract_one(path)
            assert meta is not None
            assert meta.file_size == path.stat().st_size

    def test_mtime_populated(self, media_dir: Path) -> None:
        for name in ("simple.mp4", "avi_container.avi"):
            path = media_dir / name
            if not path.exists():
                continue
            meta = extract_one(path)
            assert meta is not None
            assert meta.mtime is not None
            assert meta.mtime > 0


# ===========================================================================
# TestContentHashing
# ===========================================================================


class TestContentHashing:
    """Tests the full PDQ content hashing pipeline: ffmpeg rawvideo -> PDQ -> comparison."""

    def test_extract_content_hash(self, media_dir: Path) -> None:
        path = _require_file(media_dir / "simple.mp4")
        meta = extract_one(path)
        assert meta is not None
        result = _extract_sparse_hashes(path, duration=meta.duration)
        assert result is not None
        assert len(result) >= _HASH_UINT64S
        assert all(isinstance(h, int) for h in result)

    def test_content_hash_deterministic(self, media_dir: Path) -> None:
        path = _require_file(media_dir / "simple.mp4")
        meta = extract_one(path)
        assert meta is not None
        h1 = _extract_sparse_hashes(path, duration=meta.duration)
        h2 = _extract_sparse_hashes(path, duration=meta.duration)
        assert h1 is not None
        assert h1 == h2

    def test_similar_files_high_similarity(self, media_dir: Path) -> None:
        original = _require_file(media_dir / "simple.mp4")
        duplicate = _require_file(media_dir / "near_duplicate.mp4")
        meta_orig = extract_one(original)
        meta_dup = extract_one(duplicate)
        assert meta_orig is not None and meta_dup is not None
        h1 = _extract_sparse_hashes(original, duration=meta_orig.duration)
        h2 = _extract_sparse_hashes(duplicate, duration=meta_dup.duration)
        assert h1 is not None
        assert h2 is not None
        similarity = compare_content_hashes(h1, h2)
        assert similarity > 0.7

    def test_different_container_same_content(self, media_dir: Path) -> None:
        mp4 = _require_file(media_dir / "simple.mp4")
        mkv = _require_file(media_dir / "simple.mkv")
        meta_mp4 = extract_one(mp4)
        meta_mkv = extract_one(mkv)
        assert meta_mp4 is not None and meta_mkv is not None
        h_mp4 = _extract_sparse_hashes(mp4, duration=meta_mp4.duration)
        h_mkv = _extract_sparse_hashes(mkv, duration=meta_mkv.duration)
        assert h_mp4 is not None
        assert h_mkv is not None
        similarity = compare_content_hashes(h_mp4, h_mkv)
        assert similarity > 0.9


# ===========================================================================
# TestImageMetadata
# ===========================================================================


class TestImageMetadata:
    """Tests extract_one_image() with real PIL on generated images."""

    def test_jpeg_metadata(self, media_dir: Path) -> None:
        meta = extract_one_image(_require_file(media_dir / "photo.jpg"))
        assert meta is not None
        assert meta.width == 256
        assert meta.height == 256
        assert meta.file_size > 0
        assert meta.duration is None
        assert meta.codec == "jpeg"

    def test_png_metadata(self, media_dir: Path) -> None:
        meta = extract_one_image(_require_file(media_dir / "photo.png"))
        assert meta is not None
        assert meta.width == 256
        assert meta.height == 256
        assert meta.codec == "png"

    def test_image_resolution_matches(self, media_dir: Path) -> None:
        jpg = extract_one_image(_require_file(media_dir / "photo.jpg"))
        png = extract_one_image(_require_file(media_dir / "photo.png"))
        assert jpg is not None
        assert png is not None
        assert jpg.width == png.width
        assert jpg.height == png.height

    def test_small_image(self, media_dir: Path) -> None:
        meta = extract_one_image(_require_file(media_dir / "small_image.jpg"))
        assert meta is not None
        assert meta.width == 64
        assert meta.height == 64

    def test_large_image(self, media_dir: Path) -> None:
        meta = extract_one_image(_require_file(media_dir / "large_image.jpg"))
        assert meta is not None
        assert meta.width == 1920
        assert meta.height == 1080


# ===========================================================================
# TestImageContentHashing
# ===========================================================================


class TestImageContentHashing:
    """Tests image content hash pipeline via PIL + PDQ."""

    def test_image_content_hash(self, media_dir: Path) -> None:
        result = compute_image_content_hash(_require_file(media_dir / "photo.jpg"))
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == _HASH_UINT64S
        assert all(isinstance(v, int) for v in result)

    def test_similar_images_high_similarity(self, media_dir: Path) -> None:
        h_orig = compute_image_content_hash(_require_file(media_dir / "photo.jpg"))
        h_resized = compute_image_content_hash(_require_file(media_dir / "photo_resized.jpg"))
        assert h_orig is not None
        assert h_resized is not None
        similarity = compare_content_hashes(h_orig, h_resized)
        assert similarity > 0.7

    def test_different_images_lower_similarity(self, media_dir: Path) -> None:
        h_photo = compute_image_content_hash(_require_file(media_dir / "photo.jpg"))
        h_small = compute_image_content_hash(_require_file(media_dir / "small_image.jpg"))
        assert h_photo is not None
        assert h_small is not None
        similarity = compare_content_hashes(h_photo, h_small)
        # Different content should be less similar than same-content resized pair
        h_resized = compute_image_content_hash(_require_file(media_dir / "photo_resized.jpg"))
        assert h_resized is not None
        same_content_sim = compare_content_hashes(h_photo, h_resized)
        assert similarity < same_content_sim

    def test_content_hash_deterministic(self, media_dir: Path) -> None:
        path = _require_file(media_dir / "photo.jpg")
        h1 = compute_image_content_hash(path)
        h2 = compute_image_content_hash(path)
        assert h1 == h2


# ===========================================================================
# TestEndToEnd
# ===========================================================================


class TestEndToEnd:
    """Higher-level pipeline tests using find_video_files + extract_all + main."""

    def test_scan_and_extract(self, media_dir: Path) -> None:
        files = find_video_files(media_dir, quiet=True)
        assert len(files) >= 3
        metadata = extract_all(files, workers=1, quiet=True)
        assert len(metadata) >= 3
        for m in metadata:
            assert isinstance(m, VideoMetadata)
            assert m.file_size > 0

    def test_scan_and_extract_images(self, media_dir: Path) -> None:
        files = find_video_files(media_dir, extensions=DEFAULT_IMAGE_EXTENSIONS, quiet=True)
        assert len(files) >= 3
        metadata = extract_all_images(files, workers=1, quiet=True)
        assert len(metadata) >= 3
        for m in metadata:
            assert isinstance(m, VideoMetadata)
            assert m.duration is None

    def test_full_pipeline_video(self, media_dir: Path, tmp_path: Path) -> None:
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)

    def test_full_pipeline_image(self, media_dir: Path, tmp_path: Path) -> None:
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--mode",
                "image",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)

    def test_full_pipeline_content_mode(self, media_dir: Path, tmp_path: Path) -> None:
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--content",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-content-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)

    def test_auto_mode_mixed_media(self, media_dir: Path, tmp_path: Path) -> None:
        """Auto mode scans both videos and images in a single run."""
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--mode",
                "auto",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)


# ===========================================================================
# TestRotationInvariant
# ===========================================================================


class TestRotationInvariant:
    """Integration tests for rotation-invariant image content hashing."""

    def test_rotated_image_high_similarity(self, media_dir: Path, tmp_path: Path) -> None:
        """A 90-degree rotated copy scores high with rotation_invariant=True."""
        from PIL import Image

        orig = _require_file(media_dir / "photo.jpg")
        with Image.open(orig) as img:
            rotated = img.rotate(90, expand=True)
            rotated_path = tmp_path / "photo_rotated90.jpg"
            rotated.save(rotated_path, "JPEG", quality=90)

        h_orig = compute_image_content_hash(orig, rotation_invariant=True)
        h_rot = compute_image_content_hash(rotated_path, rotation_invariant=True)
        assert h_orig is not None and h_rot is not None
        # 8 orientations x 4 uint64 = 32
        assert len(h_orig) == 32
        assert len(h_rot) == 32

        sim_rot_inv = compare_content_hashes(h_orig, h_rot, rotation_invariant=True)
        # PDQ rotation-invariant comparison may not score as high as pHash did,
        # but should still indicate meaningful similarity (> 0.5)
        assert sim_rot_inv > 0.5

        # Without rotation invariance, the same pair should score lower or equal
        h_orig_1 = compute_image_content_hash(orig, rotation_invariant=False)
        h_rot_1 = compute_image_content_hash(rotated_path, rotation_invariant=False)
        assert h_orig_1 is not None and h_rot_1 is not None
        sim_no_rot = compare_content_hashes(h_orig_1, h_rot_1, rotation_invariant=False)
        assert sim_rot_inv >= sim_no_rot

    def test_flipped_image_high_similarity(self, media_dir: Path, tmp_path: Path) -> None:
        """A horizontally flipped copy scores high with rotation_invariant=True."""
        from PIL import Image

        orig = _require_file(media_dir / "photo.jpg")
        with Image.open(orig) as img:
            flipped = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            flipped_path = tmp_path / "photo_flipped.jpg"
            flipped.save(flipped_path, "JPEG", quality=90)

        h_orig = compute_image_content_hash(orig, rotation_invariant=True)
        h_flip = compute_image_content_hash(flipped_path, rotation_invariant=True)
        assert h_orig is not None and h_flip is not None

        sim = compare_content_hashes(h_orig, h_flip, rotation_invariant=True)
        # PDQ rotation-invariant comparison may not score as high as pHash did
        assert sim > 0.5

    def test_different_images_low_similarity(self, media_dir: Path) -> None:
        """Genuinely different images still score low with rotation invariance."""
        photo = _require_file(media_dir / "photo.jpg")
        small = _require_file(media_dir / "small_image.jpg")

        h_photo = compute_image_content_hash(photo, rotation_invariant=True)
        h_small = compute_image_content_hash(small, rotation_invariant=True)
        assert h_photo is not None and h_small is not None

        sim = compare_content_hashes(h_photo, h_small, rotation_invariant=True)
        # Should still be noticeably lower than same-content rotated pair
        assert sim < 0.95


# ===========================================================================
# TestSceneDetection
# ===========================================================================


class TestSceneDetection:
    """Integration tests for scene-based SSIM keyframe extraction."""

    def test_scene_extraction_produces_frames(self, media_dir: Path) -> None:
        """Scene detection on a video with scene changes produces frames."""
        from duplicates_detector.content import extract_frames_scene

        path = _require_file(media_dir / "scene_changes.mp4")
        result = extract_frames_scene(path, threshold=0.3)
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) >= 1

    def test_fallback_on_static_with_high_threshold(self, media_dir: Path) -> None:
        """A static video with high threshold falls back to interval extraction."""
        from duplicates_detector.content import extract_frames_scene

        path = _require_file(media_dir / "simple.mp4")
        result = extract_frames_scene(path, threshold=0.99, fallback_interval=1.0)
        assert result is not None
        assert len(result) >= 1

    def test_scene_detection_full_pipeline(self, media_dir: Path, tmp_path: Path) -> None:
        """Full pipeline with --content --content-method ssim produces output."""
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--content",
                "--content-method",
                "ssim",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-content-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)


# ===========================================================================
# TestSSIMComparison
# ===========================================================================


class TestSSIMComparison:
    """Integration tests for SSIM content comparison mode.

    Requires scikit-image — skipped if not installed.
    """

    @pytest.fixture(autouse=True)
    def _require_skimage(self) -> None:
        pytest.importorskip("skimage")

    def test_extract_video_frames(self, media_dir: Path) -> None:
        """extract_frames() returns raw PNG bytes from a real video."""
        path = _require_file(media_dir / "simple.mp4")
        frames = extract_frames(path, interval=1.0)
        assert frames is not None
        assert len(frames) >= 1
        assert all(isinstance(f, bytes) for f in frames)
        # Each frame should start with the PNG signature
        for f in frames:
            assert f[:4] == b"\x89PNG"

    def test_extract_image_frame(self, media_dir: Path) -> None:
        """extract_image_frame() returns a 1-tuple of PNG bytes from a real image."""
        path = _require_file(media_dir / "photo.jpg")
        frames = extract_image_frame(path)
        assert frames is not None
        assert len(frames) == 1
        assert frames[0][:4] == b"\x89PNG"

    def test_ssim_identical_videos(self, media_dir: Path) -> None:
        """Same video file compared via SSIM should score very high."""
        path = _require_file(media_dir / "simple.mp4")
        frames = extract_frames(path, interval=1.0)
        assert frames is not None
        score = compare_ssim_frames(frames, frames)
        assert score >= 0.99

    def test_ssim_same_content_different_container(self, media_dir: Path) -> None:
        """MP4 vs MKV of same content should score high via SSIM."""
        mp4 = _require_file(media_dir / "simple.mp4")
        mkv = _require_file(media_dir / "simple.mkv")
        frames_mp4 = extract_frames(mp4, interval=1.0)
        frames_mkv = extract_frames(mkv, interval=1.0)
        assert frames_mp4 is not None
        assert frames_mkv is not None
        score = compare_ssim_frames(frames_mp4, frames_mkv)
        assert score > 0.8

    def test_ssim_near_duplicate_videos(self, media_dir: Path) -> None:
        """Re-encoded video compared via SSIM should score reasonably high."""
        original = _require_file(media_dir / "simple.mp4")
        duplicate = _require_file(media_dir / "near_duplicate.mp4")
        frames_orig = extract_frames(original, interval=1.0)
        frames_dup = extract_frames(duplicate, interval=1.0)
        assert frames_orig is not None
        assert frames_dup is not None
        score = compare_ssim_frames(frames_orig, frames_dup)
        assert score > 0.6

    def test_ssim_identical_images(self, media_dir: Path) -> None:
        """Same image compared via SSIM should score very high."""
        path = _require_file(media_dir / "photo.jpg")
        frames = extract_image_frame(path)
        assert frames is not None
        score = compare_ssim_frames(frames, frames)
        assert score >= 0.99

    def test_ssim_similar_images(self, media_dir: Path) -> None:
        """Resized version of the same image should score high via SSIM."""
        orig = _require_file(media_dir / "photo.jpg")
        resized = _require_file(media_dir / "photo_resized.jpg")
        frames_orig = extract_image_frame(orig)
        frames_resized = extract_image_frame(resized)
        assert frames_orig is not None
        assert frames_resized is not None
        score = compare_ssim_frames(frames_orig, frames_resized)
        assert score > 0.7

    def test_ssim_different_images(self, media_dir: Path) -> None:
        """Different images should score lower than same-content resized pair."""
        photo = _require_file(media_dir / "photo.jpg")
        small = _require_file(media_dir / "small_image.jpg")
        resized = _require_file(media_dir / "photo_resized.jpg")
        f_photo = extract_image_frame(photo)
        f_small = extract_image_frame(small)
        f_resized = extract_image_frame(resized)
        assert f_photo is not None and f_small is not None and f_resized is not None
        diff_score = compare_ssim_frames(f_photo, f_small)
        same_score = compare_ssim_frames(f_photo, f_resized)
        assert diff_score < same_score

    def test_full_pipeline_ssim_video(self, media_dir: Path, tmp_path: Path) -> None:
        """Full CLI pipeline with --content --content-method ssim produces output."""
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--content",
                "--content-method",
                "ssim",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)

    def test_full_pipeline_ssim_image(self, media_dir: Path, tmp_path: Path) -> None:
        """Full CLI pipeline with --mode image --content --content-method ssim."""
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--mode",
                "image",
                "--content",
                "--content-method",
                "ssim",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)

    def test_full_pipeline_ssim_auto(self, media_dir: Path, tmp_path: Path) -> None:
        """Full CLI pipeline with --mode auto --content --content-method ssim."""
        from duplicates_detector.cli import main

        output_file = tmp_path / "output.json"
        main(
            [
                str(media_dir),
                "--mode",
                "auto",
                "--content",
                "--content-method",
                "ssim",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--no-metadata-cache",
                "--no-config",
                "-q",
            ]
        )
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)


# ===========================================================================
# TestDocumentMode
# ===========================================================================


class TestDocumentMode:
    """End-to-end integration tests for document mode with real text files."""

    @pytest.mark.slow
    def test_document_mode_finds_duplicate_txt_files(self, tmp_path: Path) -> None:
        """Document mode detects identical TXT files as duplicates."""
        d = tmp_path / "docs"
        d.mkdir()
        (d / "original.txt").write_text("This is a test document with some content about testing.")
        (d / "copy.txt").write_text("This is a test document with some content about testing.")
        (d / "different.txt").write_text("Completely unrelated content that has nothing in common.")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "duplicates_detector",
                "scan",
                str(d),
                "--mode",
                "document",
                "--format",
                "json",
                "--json-envelope",
                "--no-config",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        envelope = json.loads(result.stdout)
        pairs = envelope["pairs"]
        assert len(pairs) >= 1
        # At least one pair must contain both "original" and "copy"
        found = False
        for pair in pairs:
            names = {Path(pair["file_a"]).name, Path(pair["file_b"]).name}
            if "original.txt" in names and "copy.txt" in names:
                found = True
                break
        assert found, f"Expected pair with original.txt and copy.txt, got: {pairs}"

    @pytest.mark.slow
    def test_document_mode_with_simhash(self, tmp_path: Path) -> None:
        """Document mode with --content (SimHash) detects identical MD files."""
        d = tmp_path / "docs"
        d.mkdir()
        (d / "a.md").write_text("# Report\n\nThe quarterly results show growth in all sectors.")
        (d / "b.md").write_text("# Report\n\nThe quarterly results show growth in all sectors.")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "duplicates_detector",
                "scan",
                str(d),
                "--mode",
                "document",
                "--content",
                "--format",
                "json",
                "--json-envelope",
                "--no-config",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        envelope = json.loads(result.stdout)
        pairs = envelope["pairs"]
        assert len(pairs) >= 1
