from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from duplicates_detector.metadata import VideoMetadata


@pytest.fixture
def make_metadata():
    """Factory fixture that creates VideoMetadata with sensible defaults."""

    def _make(
        path: str = "video.mp4",
        filename: str | None = None,
        duration: float | None = 120.0,
        width: int | None = 1920,
        height: int | None = 1080,
        codec: str | None = "h264",
        bitrate: int | None = 8_000_000,
        framerate: float | None = 23.976,
        audio_channels: int | None = 2,
        file_size: int = 1_000_000,
        mtime: float | None = 1_700_000_000.0,
        is_reference: bool = False,
        content_hash: tuple[int, ...] | None = None,
        pre_hash: str | None = None,
        content_frames: tuple[bytes, ...] | None = None,
        exif_datetime: float | None = None,
        exif_camera: str | None = None,
        exif_lens: str | None = None,
        exif_gps_lat: float | None = None,
        exif_gps_lon: float | None = None,
        exif_width: int | None = None,
        exif_height: int | None = None,
        audio_fingerprint: tuple[int, ...] | None = None,
        tag_title: str | None = None,
        tag_artist: str | None = None,
        tag_album: str | None = None,
        sidecars: tuple[Path, ...] | None = None,
        clip_embedding: tuple[float, ...] | None = None,
        page_count: int | None = None,
        doc_title: str | None = None,
        doc_author: str | None = None,
        doc_created: str | None = None,
        text_content: str | None = None,
    ) -> VideoMetadata:
        if filename is None:
            filename = Path(path).stem
        return VideoMetadata(
            path=Path(path),
            filename=filename,
            duration=duration,
            width=width,
            height=height,
            codec=codec,
            bitrate=bitrate,
            framerate=framerate,
            audio_channels=audio_channels,
            file_size=file_size,
            mtime=mtime,
            is_reference=is_reference,
            content_hash=content_hash,
            pre_hash=pre_hash,
            content_frames=content_frames,
            exif_datetime=exif_datetime,
            exif_camera=exif_camera,
            exif_lens=exif_lens,
            exif_gps_lat=exif_gps_lat,
            exif_gps_lon=exif_gps_lon,
            exif_width=exif_width,
            exif_height=exif_height,
            audio_fingerprint=audio_fingerprint,
            tag_title=tag_title,
            tag_artist=tag_artist,
            tag_album=tag_album,
            sidecars=sidecars,
            clip_embedding=clip_embedding,
            page_count=page_count,
            doc_title=doc_title,
            doc_author=doc_author,
            doc_created=doc_created,
            text_content=text_content,
        )

    return _make


@pytest.fixture
def sample_videos(make_metadata):
    """Realistic set of ~20 VideoMetadata with varied properties."""
    return [
        # Near-duplicate pair (same movie, different rips)
        make_metadata(
            "movies/Movie_A.1080p.BluRay.mp4", duration=7200.0, width=1920, height=1080, file_size=4_000_000_000
        ),
        make_metadata(
            "movies/Movie_A.720p.WebRip.mkv", duration=7200.5, width=1280, height=720, file_size=2_000_000_000
        ),
        # Same content, very different size
        make_metadata(
            "movies/Movie_A.2160p.Remux.mkv", duration=7201.0, width=3840, height=2160, file_size=50_000_000_000
        ),
        # Completely different movie
        make_metadata(
            "movies/Totally_Different_Film.mp4", duration=5400.0, width=1920, height=1080, file_size=3_500_000_000
        ),
        # Short clips, near-duplicate
        make_metadata("clips/clip_funny_cat.mp4", duration=30.0, width=1280, height=720, file_size=15_000_000),
        make_metadata("clips/clip_funny_cat_reupload.mp4", duration=30.2, width=1280, height=720, file_size=14_500_000),
        # Short clip, different content
        make_metadata("clips/nature_scene.avi", duration=45.0, width=1920, height=1080, file_size=25_000_000),
        # TV episodes (different durations)
        make_metadata("tv/Show_S01E01.mp4", duration=2520.0, width=1920, height=1080, file_size=1_200_000_000),
        make_metadata("tv/Show_S01E02.mp4", duration=2580.0, width=1920, height=1080, file_size=1_250_000_000),
        make_metadata("tv/Show_S01E01.720p.mkv", duration=2520.5, width=1280, height=720, file_size=800_000_000),
        # Low-res content
        make_metadata("old/vhs_tape.avi", duration=3600.0, width=640, height=480, file_size=700_000_000),
        make_metadata("old/vhs_tape_digitized.mp4", duration=3600.1, width=640, height=480, file_size=500_000_000),
        # Missing metadata
        make_metadata("broken/corrupt_file.mp4", duration=None, width=None, height=None, file_size=1_000),
        make_metadata("broken/no_video_stream.mkv", duration=60.0, width=None, height=None, file_size=5_000_000),
        # Very large file
        make_metadata("raw/camera_raw.mov", duration=600.0, width=4096, height=2160, file_size=80_000_000_000),
        # Tiny mobile video
        make_metadata("mobile/phone_video.3gp", duration=10.0, width=320, height=240, file_size=500_000),
        # 4K content pair
        make_metadata("4k/documentary.mkv", duration=5400.0, width=3840, height=2160, file_size=25_000_000_000),
        make_metadata("4k/documentary_hdr.mkv", duration=5400.0, width=3840, height=2160, file_size=30_000_000_000),
        # Zero-byte file (edge case)
        make_metadata("empty/zero_bytes.mp4", duration=0.0, width=0, height=0, file_size=0),
        # Another None duration
        make_metadata("broken/partial_download.mkv", duration=None, width=1920, height=1080, file_size=100_000_000),
    ]


@pytest.fixture
def video_dir(tmp_path):
    """Create a directory tree with dummy video/non-video files."""
    root = tmp_path / "videos"
    root.mkdir()

    (root / "movie_a.mp4").touch()
    (root / "movie_b.mkv").touch()
    (root / "clip.avi").touch()

    sub = root / "sub"
    sub.mkdir()
    (sub / "movie_c.mp4").touch()
    (sub / "not_video.txt").touch()

    (root / "other.jpg").touch()

    return root


@pytest.fixture
def mock_ffprobe_result():
    """Return a callable that creates a mock subprocess.run result for ffprobe."""

    def _make(
        duration: float | None = 120.0,
        width: int | None = 1920,
        height: int | None = 1080,
        codec_name: str | None = "h264",
        bit_rate: int | None = 8_000_000,
        r_frame_rate: str | None = "24000/1001",
        audio_channels: int | None = 2,
        returncode: int = 0,
        raise_timeout: bool = False,
        corrupt_json: bool = False,
    ) -> MagicMock:
        if raise_timeout:
            import subprocess

            mock = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30))
            return mock

        data: dict = {"format": {}}
        if duration is not None:
            data["format"]["duration"] = str(duration)
        if bit_rate is not None:
            data["format"]["bit_rate"] = str(bit_rate)

        streams: list[dict] = []
        if width is not None and height is not None:
            video_stream: dict = {
                "width": width,
                "height": height,
                "codec_type": "video",
            }
            if codec_name is not None:
                video_stream["codec_name"] = codec_name
            if r_frame_rate is not None:
                video_stream["r_frame_rate"] = r_frame_rate
            streams.append(video_stream)
        if audio_channels is not None:
            streams.append({"codec_type": "audio", "channels": audio_channels})
        data["streams"] = streams

        stdout = "NOT VALID JSON" if corrupt_json else json.dumps(data)

        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        mock.stderr = ""
        return mock

    return _make


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    """Generate real test media files for integration tests.

    Session-scoped: files are generated once per test run.
    Skips all dependent tests if ffmpeg or ffprobe is not installed.
    """
    import shutil

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed — skipping integration tests")

    d = tmp_path_factory.mktemp("media")

    import importlib.util

    spec = importlib.util.spec_from_file_location("generate_media", Path(__file__).parent / "generate_media.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.generate_video_files(d)
    mod.generate_image_files(d)
    if hasattr(mod, "generate_scene_change_video"):
        mod.generate_scene_change_video(d)

    return d


# --- Integration test helpers ---


def _require_integ_file(media: dict[str, Path | None], key: str) -> Path:
    """Skip a test if a specific generated media file is not available."""
    path = media.get(key)
    if path is None:
        pytest.skip(f"{key} not generated")
    return path


def _load_integ_generators():
    """Load generate_integration_media.py via importlib (tests/ is not a package)."""
    import importlib.util

    gen_path = Path(__file__).parent / "generate_integration_media.py"
    spec = importlib.util.spec_from_file_location("generate_integration_media", gen_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_integ_gen = None


def _get_integ_generators():
    global _integ_gen
    if _integ_gen is None:
        _integ_gen = _load_integ_generators()
    return _integ_gen
