"""Generate real test media files for integration tests.

Video files are created via ffmpeg; image files via PIL.
Each generation function is fault-tolerant: if a specific encoder
is unavailable, that file is skipped rather than aborting all generation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image


def _run_ffmpeg(args: list[str]) -> bool:
    """Run an ffmpeg command, returning True on success, False on failure."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def generate_video_files(directory: Path) -> None:
    """Generate test video files into the given directory.

    Each file is wrapped in try/except so a missing encoder (e.g., libx265)
    skips that file rather than aborting all generation.
    """
    d = directory

    # 1. simple.mp4 — H.264/AAC baseline (3 seconds, 320x240, 24fps)
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=3:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(d / "simple.mp4"),
        ]
    )

    # 2. simple.mkv — re-mux of simple.mp4 (same content, different container)
    if (d / "simple.mp4").exists():
        _run_ffmpeg(
            [
                "-i",
                str(d / "simple.mp4"),
                "-c",
                "copy",
                str(d / "simple.mkv"),
            ]
        )

    # 3. audio_first.mkv — audio stream before video stream
    if (d / "simple.mp4").exists():
        _run_ffmpeg(
            [
                "-i",
                str(d / "simple.mp4"),
                "-map",
                "0:a",
                "-map",
                "0:v",
                "-c",
                "copy",
                str(d / "audio_first.mkv"),
            ]
        )

    # 4. hevc_no_audio.mp4 — H.265 video only (may fail if libx265 unavailable)
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=3:size=320x240:rate=24",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-an",
            str(d / "hevc_no_audio.mp4"),
        ]
    )

    # 5. variable_fps.mkv — VFR-like content by concatenating segments at different rates
    seg_a = d / "_seg_24fps.mkv"
    seg_b = d / "_seg_30fps.mkv"
    concat_list = d / "_concat.txt"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=320x240:rate=24",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(seg_a),
        ]
    )
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(seg_b),
        ]
    )
    if seg_a.exists() and seg_b.exists():
        concat_list.write_text(f"file '{seg_a}'\nfile '{seg_b}'\n")
        _run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(d / "variable_fps.mkv"),
            ]
        )
    # Clean up temp segments
    for tmp in (seg_a, seg_b, concat_list):
        tmp.unlink(missing_ok=True)

    # 6. no_format_duration.mkv — MKV with stream-level duration
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-f",
            "matroska",
            str(d / "no_format_duration.mkv"),
        ]
    )

    # 7. avi_container.avi — legacy AVI container
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=3:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-c:a",
            "mp3",
            "-b:a",
            "64k",
            "-f",
            "avi",
            str(d / "avi_container.avi"),
        ]
    )

    # 8. multichannel.mp4 — 5.1 surround audio
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=3:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-ac",
            "6",
            "-b:a",
            "128k",
            str(d / "multichannel.mp4"),
        ]
    )

    # 9. data_stream.mkv — video + audio + subtitle stream
    srt_file = d / "_subtitle.srt"
    srt_file.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nTest subtitle\n\n2\n00:00:02,000 --> 00:00:03,000\nSecond line\n"
    )
    if (d / "simple.mp4").exists():
        _run_ffmpeg(
            [
                "-i",
                str(d / "simple.mp4"),
                "-i",
                str(srt_file),
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-c:s",
                "srt",
                str(d / "data_stream.mkv"),
            ]
        )
    srt_file.unlink(missing_ok=True)

    # 10. near_duplicate.mp4 — re-encode of simple.mp4 at different quality
    if (d / "simple.mp4").exists():
        _run_ffmpeg(
            [
                "-i",
                str(d / "simple.mp4"),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "48k",
                str(d / "near_duplicate.mp4"),
            ]
        )


def generate_image_files(directory: Path) -> None:
    """Generate test image files using PIL."""
    d = directory

    # Deterministic color pattern (not random) for reproducible pHash values
    def _make_test_image(width: int, height: int) -> Image.Image:
        img = Image.new("RGB", (width, height))
        for x in range(width):
            for y in range(height):
                r = (x * 7 + y * 3) % 256
                g = (x * 3 + y * 7) % 256
                b = (x * 5 + y * 5) % 256
                img.putpixel((x, y), (r, g, b))
        return img

    # 1. photo.jpg — 256x256 JPEG
    img = _make_test_image(256, 256)
    img.save(d / "photo.jpg", "JPEG", quality=90)

    # 2. photo.png — same visual content as JPEG
    img.save(d / "photo.png", "PNG")

    # 3. small_image.jpg — tiny 64x64
    small = _make_test_image(64, 64)
    small.save(d / "small_image.jpg", "JPEG", quality=85)

    # 4. large_image.jpg — 1920x1080 (resized from 256x256 to avoid slow per-pixel loop)
    large = img.resize((1920, 1080))
    large.save(d / "large_image.jpg", "JPEG", quality=85)

    # 5. photo_resized.jpg — resized version of photo.jpg for content hash similarity test
    resized = img.resize((128, 128))
    resized.save(d / "photo_resized.jpg", "JPEG", quality=85)


def generate_scene_change_video(directory: Path) -> None:
    """Generate a video with distinct scene changes for scene detection tests.

    Creates 3 segments of 2 seconds each with very different visuals
    (red, green, blue backgrounds) concatenated into one video. Scene
    detection should find the transitions between segments.
    """
    d = directory
    seg_r = d / "_scene_red.mp4"
    seg_g = d / "_scene_green.mp4"
    seg_b = d / "_scene_blue.mp4"
    concat_list = d / "_scene_concat.txt"

    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=2:r=24",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(seg_r),
        ]
    )
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x240:d=2:r=24",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(seg_g),
        ]
    )
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2:r=24",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(seg_b),
        ]
    )

    if seg_r.exists() and seg_g.exists() and seg_b.exists():
        concat_list.write_text(f"file '{seg_r}'\nfile '{seg_g}'\nfile '{seg_b}'\n")
        _run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(d / "scene_changes.mp4"),
            ]
        )

    for tmp in (seg_r, seg_g, seg_b, concat_list):
        tmp.unlink(missing_ok=True)
