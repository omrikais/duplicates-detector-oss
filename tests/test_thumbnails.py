"""Tests for the shared thumbnail generation module."""

from __future__ import annotations

import base64
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.grouper import DuplicateGroup
from duplicates_detector.thumbnails import (
    _PROGRESS_THRESHOLD,
    collect_group_metadata,
    collect_pair_metadata,
    generate_image_thumbnail,
    generate_thumbnails_batch,
    generate_video_thumbnail,
)


def _make_meta(
    name: str = "file.mp4",
    duration: float | None = 120.0,
    file_size: int = 1_000_000,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/videos/{name}"),
        filename=Path(name).stem,
        duration=duration,
        width=1920,
        height=1080,
        file_size=file_size,
    )


def _make_pair(
    a: str = "a.mp4",
    b: str = "b.mp4",
) -> ScoredPair:
    return ScoredPair(
        file_a=_make_meta(a),
        file_b=_make_meta(b),
        total_score=80.0,
        breakdown={},
        detail={},
    )


# ---------------------------------------------------------------------------
# generate_image_thumbnail
# ---------------------------------------------------------------------------


class TestGenerateImageThumbnail:
    def test_generates_jpeg_data_uri(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (200, 200), color="red")
        path = tmp_path / "test.jpg"
        img.save(path)

        result = generate_image_thumbnail(path)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_respects_max_size(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (500, 500), color="blue")
        path = tmp_path / "big.png"
        img.save(path)

        result = generate_image_thumbnail(path, max_size=(50, 50))
        assert result is not None
        # Decode and check actual dimensions
        b64_data = result.split(",", 1)[1]
        raw = base64.b64decode(b64_data)
        thumb = Image.open(BytesIO(raw))
        assert thumb.width <= 50
        assert thumb.height <= 50

    def test_custom_size(self, tmp_path):
        from PIL import Image

        img = Image.new("RGB", (500, 500), color="green")
        path = tmp_path / "custom.png"
        img.save(path)

        result_small = generate_image_thumbnail(path, max_size=(50, 50))
        result_large = generate_image_thumbnail(path, max_size=(240, 240))
        assert result_small is not None
        assert result_large is not None
        # Larger max_size → larger base64 payload
        assert len(result_large) > len(result_small)

    def test_rgba_converts_to_rgb(self, tmp_path):
        from PIL import Image

        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        path = tmp_path / "alpha.png"
        img.save(path)

        result = generate_image_thumbnail(path)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_corrupt_image_returns_none(self, tmp_path):
        path = tmp_path / "corrupt.jpg"
        path.write_bytes(b"not an image")
        assert generate_image_thumbnail(path) is None

    def test_missing_file_returns_none(self, tmp_path):
        path = tmp_path / "nonexistent.jpg"
        assert generate_image_thumbnail(path) is None


# ---------------------------------------------------------------------------
# generate_video_thumbnail
# ---------------------------------------------------------------------------


class TestGenerateVideoThumbnail:
    def test_generates_thumbnail(self):
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_jpeg

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result):
            result = generate_video_thumbnail(Path("/test/video.mp4"), duration=100.0)
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_custom_size_in_ffmpeg_args(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"\xff\xd8\xff\xe0"

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            generate_video_thumbnail(Path("/test.mp4"), duration=100.0, max_size=(320, 180))
            args = mock_run.call_args[0][0]
            vf_idx = args.index("-vf")
            vf_val = args[vf_idx + 1]
            assert "320" in vf_val
            assert "180" in vf_val

    def test_seek_at_10_percent(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"\xff\xd8"

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            generate_video_thumbnail(Path("/test.mp4"), duration=200.0)
            args = mock_run.call_args[0][0]
            ss_idx = args.index("-ss")
            seek_val = float(args[ss_idx + 1])
            assert seek_val == pytest.approx(20.0)

    def test_zero_duration(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"\xff\xd8"

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            generate_video_thumbnail(Path("/test.mp4"), duration=0.0)
            args = mock_run.call_args[0][0]
            ss_idx = args.index("-ss")
            assert float(args[ss_idx + 1]) == 0.0

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result) as mock_run:
            generate_video_thumbnail(Path("/test.mp4"), duration=None)
            args = mock_run.call_args[0][0]
            ss_idx = args.index("-ss")
            assert float(args[ss_idx + 1]) == 0.0

    def test_ffmpeg_failure_returns_none(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = b""

        with patch("duplicates_detector.thumbnails.subprocess.run", return_value=mock_result):
            assert generate_video_thumbnail(Path("/test.mp4")) is None

    def test_timeout_returns_none(self):
        with patch(
            "duplicates_detector.thumbnails.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ffmpeg", 15),
        ):
            assert generate_video_thumbnail(Path("/test.mp4")) is None


# ---------------------------------------------------------------------------
# collect_pair_metadata / collect_group_metadata
# ---------------------------------------------------------------------------


class TestCollectMetadata:
    def test_collect_pair_metadata_unique(self):
        pair = _make_pair("a.mp4", "b.mp4")
        result = collect_pair_metadata([pair])
        paths = [m.path for m in result]
        assert len(paths) == 2

    def test_collect_pair_metadata_deduplicates(self):
        meta_a = _make_meta("a.mp4")
        pair1 = ScoredPair(file_a=meta_a, file_b=_make_meta("b.mp4"), total_score=80, breakdown={}, detail={})
        pair2 = ScoredPair(file_a=meta_a, file_b=_make_meta("c.mp4"), total_score=70, breakdown={}, detail={})
        result = collect_pair_metadata([pair1, pair2])
        paths = [m.path for m in result]
        assert paths.count(meta_a.path) == 1

    def test_collect_group_metadata_unique(self):
        members = (_make_meta("a.mp4"), _make_meta("b.mp4"))
        group = DuplicateGroup(group_id=1, members=members, pairs=(), max_score=80, min_score=70, avg_score=75)
        result = collect_group_metadata([group])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# generate_thumbnails_batch
# ---------------------------------------------------------------------------


class TestGenerateThumbnailsBatch:
    def test_deduplicates_by_resolved_path(self, tmp_path):
        meta1 = VideoMetadata(
            path=tmp_path / "a.mp4", filename="a", duration=10.0, width=1920, height=1080, file_size=1000
        )
        meta2 = VideoMetadata(
            path=tmp_path / "a.mp4", filename="a", duration=10.0, width=1920, height=1080, file_size=1000
        )
        with patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:...") as mock_gen:
            result = generate_thumbnails_batch([meta1, meta2], mode="video")
        assert mock_gen.call_count == 1
        assert len(result) == 1

    def test_video_mode_uses_video_generator(self, tmp_path):
        meta = VideoMetadata(
            path=tmp_path / "v.mp4", filename="v", duration=60.0, width=1920, height=1080, file_size=5000
        )
        with (
            patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:v") as mock_vid,
            patch("duplicates_detector.thumbnails.generate_image_thumbnail") as mock_img,
        ):
            generate_thumbnails_batch([meta], mode="video")
        mock_vid.assert_called_once()
        mock_img.assert_not_called()

    def test_image_mode_uses_image_generator(self, tmp_path):
        meta = VideoMetadata(
            path=tmp_path / "i.jpg", filename="i", duration=None, width=1920, height=1080, file_size=5000
        )
        with (
            patch("duplicates_detector.thumbnails.generate_video_thumbnail") as mock_vid,
            patch("duplicates_detector.thumbnails.generate_image_thumbnail", return_value="data:i") as mock_img,
        ):
            generate_thumbnails_batch([meta], mode="image")
        mock_img.assert_called_once()
        mock_vid.assert_not_called()

    def test_returns_dict_keyed_by_resolved_path(self, tmp_path):
        meta = VideoMetadata(
            path=tmp_path / "f.mp4", filename="f", duration=10.0, width=1920, height=1080, file_size=1000
        )
        with patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:ok"):
            result = generate_thumbnails_batch([meta], mode="video")
        assert (tmp_path / "f.mp4").resolve() in result

    def test_failed_thumbnails_are_none(self, tmp_path):
        meta = VideoMetadata(
            path=tmp_path / "bad.mp4", filename="bad", duration=10.0, width=1920, height=1080, file_size=1000
        )
        with patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value=None):
            result = generate_thumbnails_batch([meta], mode="video")
        resolved = (tmp_path / "bad.mp4").resolve()
        assert resolved in result
        assert result[resolved] is None

    def test_progress_bar_shown_above_threshold(self, tmp_path):
        items = []
        for i in range(_PROGRESS_THRESHOLD + 1):
            items.append(
                VideoMetadata(
                    path=tmp_path / f"f{i}.mp4",
                    filename=f"f{i}",
                    duration=10.0,
                    width=1920,
                    height=1080,
                    file_size=1000,
                )
            )
        with (
            patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:ok"),
            patch("duplicates_detector.thumbnails.Progress") as mock_progress,
        ):
            generate_thumbnails_batch(items, mode="video", quiet=False)
        mock_progress.assert_called_once()

    def test_progress_bar_suppressed_with_quiet(self, tmp_path):
        items = []
        for i in range(_PROGRESS_THRESHOLD + 1):
            items.append(
                VideoMetadata(
                    path=tmp_path / f"f{i}.mp4",
                    filename=f"f{i}",
                    duration=10.0,
                    width=1920,
                    height=1080,
                    file_size=1000,
                )
            )
        with (
            patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:ok"),
            patch("duplicates_detector.thumbnails.Progress") as mock_progress,
        ):
            generate_thumbnails_batch(items, mode="video", quiet=True)
        mock_progress.assert_not_called()

    def test_empty_list_returns_empty_dict(self):
        result = generate_thumbnails_batch([], mode="video")
        assert result == {}

    def test_auto_mode_dispatches_by_extension(self, tmp_path):
        vid = VideoMetadata(
            path=tmp_path / "v.mp4", filename="v", duration=60.0, width=1920, height=1080, file_size=5000
        )
        img = VideoMetadata(
            path=tmp_path / "i.jpg", filename="i", duration=None, width=1920, height=1080, file_size=5000
        )
        with (
            patch("duplicates_detector.thumbnails.generate_video_thumbnail", return_value="data:v") as mock_vid,
            patch("duplicates_detector.thumbnails.generate_image_thumbnail", return_value="data:i") as mock_img,
        ):
            generate_thumbnails_batch([vid, img], mode="auto")
        mock_vid.assert_called_once()
        mock_img.assert_called_once()
