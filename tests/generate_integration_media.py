from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _run_ffmpeg(args: list[str], timeout: int = 60) -> bool:
    """Run ffmpeg with given args. Returns True on success, False on failure."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _has_encoder(encoder: str) -> bool:
    """Check if ffmpeg has a specific encoder available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Match against first column (encoder name) to avoid substring false positives
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == encoder:
                return True
        return False
    except (subprocess.TimeoutExpired, OSError):
        return False


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def generate_corrupt_media(directory: Path) -> dict[str, Path | None]:
    """Generate corrupt/malformed media files for testing graceful error handling."""
    result: dict[str, Path | None] = {}

    if not _has_ffmpeg():
        return {
            k: None
            for k in [
                "truncated_mp4",
                "truncated_mkv",
                "zero_audio_stream",
                "corrupt_moov",
                "valid_header_corrupt_frames",
                "mismatched_extension",
            ]
        }

    # Generate a valid base video first
    base = directory / "_base.mp4"
    if not _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
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
            str(base),
        ]
    ):
        return {
            k: None
            for k in [
                "truncated_mp4",
                "truncated_mkv",
                "zero_audio_stream",
                "corrupt_moov",
                "valid_header_corrupt_frames",
                "mismatched_extension",
            ]
        }

    base_bytes = base.read_bytes()

    # truncated_mp4: cut at 50%
    trunc_mp4 = directory / "truncated.mp4"
    trunc_mp4.write_bytes(base_bytes[: len(base_bytes) // 2])
    result["truncated_mp4"] = trunc_mp4

    # truncated_mkv: remux to mkv then truncate
    mkv_full = directory / "_full.mkv"
    if _run_ffmpeg(["-i", str(base), "-c", "copy", str(mkv_full)]):
        mkv_bytes = mkv_full.read_bytes()
        trunc_mkv = directory / "truncated.mkv"
        trunc_mkv.write_bytes(mkv_bytes[: len(mkv_bytes) // 2])
        result["truncated_mkv"] = trunc_mkv
    else:
        result["truncated_mkv"] = None

    # zero_audio_stream: video with a silent audio track of 0 samples
    zero_audio = directory / "zero_audio.mp4"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(zero_audio),
        ]
    ):
        result["zero_audio_stream"] = zero_audio
    else:
        result["zero_audio_stream"] = None

    # corrupt_moov: zero out bytes after the ftyp box (moov atom area)
    corrupt_moov = directory / "corrupt_moov.mp4"
    moov_bytes = bytearray(base_bytes)
    # Zero out from byte 64 onward (past ftyp, into moov)
    for i in range(min(64, len(moov_bytes)), min(512, len(moov_bytes))):
        moov_bytes[i] = 0
    corrupt_moov.write_bytes(bytes(moov_bytes))
    result["corrupt_moov"] = corrupt_moov

    # valid_header_corrupt_frames: keep first 2KB intact, corrupt the rest
    corrupt_frames = directory / "corrupt_frames.mp4"
    cf_bytes = bytearray(base_bytes)
    for i in range(min(2048, len(cf_bytes)), len(cf_bytes)):
        cf_bytes[i] = (cf_bytes[i] + 128) % 256
    corrupt_frames.write_bytes(bytes(cf_bytes))
    result["valid_header_corrupt_frames"] = corrupt_frames

    # mismatched_extension: MKV saved as .mp4
    if mkv_full.exists():
        mismatch = directory / "mismatch.mp4"
        mismatch.write_bytes(mkv_full.read_bytes())
        result["mismatched_extension"] = mismatch
    else:
        result["mismatched_extension"] = None

    return result


def generate_codec_variants(directory: Path) -> dict[str, Path | None]:
    """Generate videos encoded with different codecs. Skips codecs not available in ffmpeg."""
    result: dict[str, Path | None] = {}

    if not _has_ffmpeg():
        return {k: None for k in ["hevc_10bit", "vp9_webm", "av1_mp4", "prores_mov", "mjpeg_avi", "pcm_wav_video"]}

    src_args = [
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
    ]

    # hevc_10bit
    if _has_encoder("libx265"):
        p = directory / "hevc_10bit.mp4"
        if _run_ffmpeg(
            [*src_args, "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-preset", "ultrafast", "-c:a", "aac", str(p)]
        ):
            result["hevc_10bit"] = p
        else:
            result["hevc_10bit"] = None
    else:
        result["hevc_10bit"] = None

    # vp9_webm
    if _has_encoder("libvpx-vp9"):
        p = directory / "vp9.webm"
        if _run_ffmpeg([*src_args, "-c:v", "libvpx-vp9", "-b:v", "1M", "-c:a", "libvorbis", str(p)]):
            result["vp9_webm"] = p
        else:
            result["vp9_webm"] = None
    else:
        result["vp9_webm"] = None

    # av1_mp4
    av1_encoder = "libsvtav1" if _has_encoder("libsvtav1") else ("libaom-av1" if _has_encoder("libaom-av1") else None)
    if av1_encoder:
        p = directory / "av1.mp4"
        extra = ["-preset", "12"] if av1_encoder == "libsvtav1" else ["-cpu-used", "8"]
        if _run_ffmpeg([*src_args, "-c:v", av1_encoder, *extra, "-c:a", "aac", str(p)], timeout=120):
            result["av1_mp4"] = p
        else:
            result["av1_mp4"] = None
    else:
        result["av1_mp4"] = None

    # prores_mov
    if _has_encoder("prores_ks"):
        p = directory / "prores.mov"
        if _run_ffmpeg([*src_args, "-c:v", "prores_ks", "-profile:v", "0", "-c:a", "pcm_s16le", str(p)]):
            result["prores_mov"] = p
        else:
            result["prores_mov"] = None
    else:
        result["prores_mov"] = None

    # mjpeg_avi (always available — mjpeg is built-in)
    p = directory / "mjpeg.avi"
    if _run_ffmpeg([*src_args, "-c:v", "mjpeg", "-q:v", "5", "-c:a", "pcm_s16le", str(p)]):
        result["mjpeg_avi"] = p
    else:
        result["mjpeg_avi"] = None

    # pcm_wav_video (AVI with PCM audio + video)
    p = directory / "pcm_video.avi"
    if _run_ffmpeg([*src_args, "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(p)]):
        result["pcm_wav_video"] = p
    else:
        result["pcm_wav_video"] = None

    return result


def generate_extreme_media(directory: Path) -> dict[str, Path | None]:
    """Generate media with extreme durations and resolutions."""
    result: dict[str, Path | None] = {}

    if not _has_ffmpeg():
        return {k: None for k in ["ten_minute_video", "subsecond_video", "single_frame_video", "huge_resolution"]}

    # ten_minute_video: 10 min, 1fps to keep file small
    p = directory / "ten_minute.mp4"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=600:size=160x120:rate=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(p),
        ],
        timeout=300,
    ):
        result["ten_minute_video"] = p
    else:
        result["ten_minute_video"] = None

    # subsecond_video: 0.1s
    p = directory / "subsecond.mp4"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.1:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(p),
        ]
    ):
        result["subsecond_video"] = p
    else:
        result["subsecond_video"] = None

    # single_frame_video: exactly 1 frame
    p = directory / "single_frame.mp4"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.04:size=320x240:rate=25",
            "-frames:v",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(p),
        ]
    ):
        result["single_frame_video"] = p
    else:
        result["single_frame_video"] = None

    # huge_resolution: 8K single frame
    p = directory / "huge_8k.mp4"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.04:size=7680x4320:rate=25",
            "-frames:v",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(p),
        ],
        timeout=120,
    ):
        result["huge_resolution"] = p
    else:
        result["huge_resolution"] = None

    return result


def generate_multistream_media(directory: Path) -> dict[str, Path | None]:
    """Generate containers with multiple streams."""
    result: dict[str, Path | None] = {}

    if not _has_ffmpeg():
        return {
            k: None
            for k in ["dual_audio_tracks", "triple_video_streams", "video_subtitle_data", "audio_only_container"]
        }

    # dual_audio_tracks: video with 2 audio streams
    p = directory / "dual_audio.mkv"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(p),
        ]
    ):
        result["dual_audio_tracks"] = p
    else:
        result["dual_audio_tracks"] = None

    # triple_video_streams: 3 video streams in MKV
    p = directory / "triple_video.mkv"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=320x240:duration=2:rate=24",
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-map",
            "2:v",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(p),
        ]
    ):
        result["triple_video_streams"] = p
    else:
        result["triple_video_streams"] = None

    # video_subtitle_data: video + audio + subtitle
    srt = directory / "_subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nTest subtitle\n")
    p = directory / "with_subs.mkv"
    if _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-i",
            str(srt),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:s",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-c:s",
            "srt",
            str(p),
        ]
    ):
        result["video_subtitle_data"] = p
    else:
        result["video_subtitle_data"] = None

    # audio_only_container: audio-only file with .mp4 extension
    p = directory / "audio_only.mp4"
    if _run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(p)]):
        result["audio_only_container"] = p
    else:
        result["audio_only_container"] = None

    return result


def generate_exotic_images(directory: Path) -> dict[str, Path | None]:
    """Generate images in exotic formats. Requires PIL."""
    from PIL import Image

    result: dict[str, Path | None] = {}

    def _make_pattern(width: int, height: int) -> Image.Image:
        """Deterministic color pattern."""
        img = Image.new("RGB", (width, height))
        pixels = img.load()
        assert pixels is not None
        for y in range(height):
            for x in range(width):
                pixels[x, y] = ((x * 7 + y * 13) % 256, (x * 11 + y * 3) % 256, (x * 5 + y * 17) % 256)
        return img

    # heic_image — requires pillow-heif or similar
    try:
        p = directory / "test.heic"
        img = _make_pattern(256, 256)
        img.save(str(p), format="HEIF")
        result["heic_image"] = p
    except Exception:
        result["heic_image"] = None

    # avif_image
    try:
        p = directory / "test.avif"
        img = _make_pattern(256, 256)
        img.save(str(p), format="AVIF")
        result["avif_image"] = p
    except Exception:
        result["avif_image"] = None

    # large_50mp_image: 7072x7072 (~50MP)
    try:
        p = directory / "large_50mp.jpg"
        img = Image.new("RGB", (7072, 7072), color=(128, 64, 32))
        # Add some variation to avoid trivial hash
        pixels = img.load()
        assert pixels is not None
        for i in range(0, 7072, 100):
            for j in range(0, 7072, 100):
                pixels[i, j] = ((i * 3) % 256, (j * 7) % 256, ((i + j) * 5) % 256)
        img.save(str(p), "JPEG", quality=85)
        result["large_50mp_image"] = p
    except Exception:
        result["large_50mp_image"] = None

    # 16bit_png
    try:
        import numpy as np

        p = directory / "16bit.png"
        arr = np.zeros((256, 256), dtype=np.uint16)
        for y in range(256):
            for x in range(256):
                arr[y, x] = (x * 257 + y * 131) % 65536
        img = Image.fromarray(arr, mode="I;16")
        img.save(str(p))
        result["16bit_png"] = p
    except Exception:
        result["16bit_png"] = None

    # webp_animated
    try:
        p = directory / "animated.webp"
        frames = [
            _make_pattern(128, 128),
            Image.new("RGB", (128, 128), (255, 0, 0)),
            Image.new("RGB", (128, 128), (0, 255, 0)),
        ]
        frames[0].save(str(p), "WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0)
        result["webp_animated"] = p
    except Exception:
        result["webp_animated"] = None

    # tiff_with_exif — use PIL's built-in Exif support (Pillow 9.2+)
    try:
        from PIL.ExifTags import Base as ExifBase
        from PIL.ExifTags import GPS as GPSTags
        from PIL.TiffImagePlugin import IFDRational

        p = directory / "with_exif.tiff"
        img = _make_pattern(256, 256)
        exif = img.getexif()
        exif[ExifBase.Make] = "TestCamera"
        exif[ExifBase.Model] = "Model X"
        exif[ExifBase.DateTime] = "2025:01:15 10:30:00"
        # GPS data via IFD — use IFDRational for Pillow compatibility
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[GPSTags.GPSLatitudeRef] = "N"
        gps_ifd[GPSTags.GPSLatitude] = (IFDRational(40, 1), IFDRational(44, 1), IFDRational(0, 1))
        gps_ifd[GPSTags.GPSLongitudeRef] = "W"
        gps_ifd[GPSTags.GPSLongitude] = (IFDRational(73, 1), IFDRational(59, 1), IFDRational(0, 1))
        img.save(str(p), "TIFF", exif=exif.tobytes())
        result["tiff_with_exif"] = p
    except Exception:
        result["tiff_with_exif"] = None

    # bmp_uncompressed
    try:
        p = directory / "uncompressed.bmp"
        img = _make_pattern(512, 512)
        img.save(str(p), "BMP")
        result["bmp_uncompressed"] = p
    except Exception:
        result["bmp_uncompressed"] = None

    return result


def generate_audio_edge_cases(directory: Path) -> dict[str, Path | None]:
    """Generate audio files with edge-case formats and features."""
    result: dict[str, Path | None] = {}

    if not _has_ffmpeg():
        return {
            k: None for k in ["flac_file", "opus_ogg", "chaptered_m4a", "vbr_mp3", "zero_duration_audio", "artwork_mp3"]
        }

    src_args = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]

    # flac_file
    if _has_encoder("flac"):
        p = directory / "test.flac"
        if _run_ffmpeg([*src_args, "-c:a", "flac", str(p)]):
            result["flac_file"] = p
        else:
            result["flac_file"] = None
    else:
        result["flac_file"] = None

    # opus_ogg
    if _has_encoder("libopus"):
        p = directory / "test.ogg"
        if _run_ffmpeg([*src_args, "-c:a", "libopus", "-b:a", "128k", str(p)]):
            result["opus_ogg"] = p
        else:
            result["opus_ogg"] = None
    else:
        result["opus_ogg"] = None

    # chaptered_m4a
    chapters_file = directory / "_chapters.txt"
    chapters_file.write_text(
        ";FFMETADATA1\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Chapter 1\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Chapter 2\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=3000\ntitle=Chapter 3\n"
    )
    p = directory / "chaptered.m4a"
    if _run_ffmpeg([*src_args, "-i", str(chapters_file), "-map_metadata", "1", "-c:a", "aac", "-b:a", "128k", str(p)]):
        result["chaptered_m4a"] = p
    else:
        result["chaptered_m4a"] = None

    # vbr_mp3
    p = directory / "vbr.mp3"
    if _run_ffmpeg([*src_args, "-c:a", "libmp3lame", "-q:a", "4", str(p)]):
        result["vbr_mp3"] = p
    else:
        result["vbr_mp3"] = None

    # zero_duration_audio: create then truncate to make duration unreadable
    p = directory / "zero_duration.mp3"
    full = directory / "_full_audio.mp3"
    if _run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.01", "-c:a", "libmp3lame", str(full)]):
        # Truncate to just the header
        data = full.read_bytes()
        p.write_bytes(data[: min(256, len(data))])
        result["zero_duration_audio"] = p
    else:
        result["zero_duration_audio"] = None

    # artwork_mp3: MP3 with embedded album art
    try:
        from PIL import Image

        art_path = directory / "_artwork.jpg"
        img = Image.new("RGB", (200, 200), color=(255, 0, 0))
        img.save(str(art_path), "JPEG")

        p = directory / "with_artwork.mp3"
        base_mp3 = directory / "_base_art.mp3"
        if _run_ffmpeg([*src_args, "-c:a", "libmp3lame", "-q:a", "4", str(base_mp3)]):
            if _run_ffmpeg(
                [
                    "-i",
                    str(base_mp3),
                    "-i",
                    str(art_path),
                    "-map",
                    "0:a",
                    "-map",
                    "1:v",
                    "-c:a",
                    "copy",
                    "-c:v:0",
                    "mjpeg",
                    "-id3v2_version",
                    "3",
                    "-metadata:s:v",
                    "title=Album cover",
                    "-metadata:s:v",
                    "comment=Cover (front)",
                    str(p),
                ]
            ):
                result["artwork_mp3"] = p
            else:
                result["artwork_mp3"] = None
        else:
            result["artwork_mp3"] = None
    except Exception:
        result["artwork_mp3"] = None

    return result
