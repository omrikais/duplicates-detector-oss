"""Shared thumbnail generation for video and image files."""

from __future__ import annotations

import base64
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from duplicates_detector.config import Mode
from duplicates_detector.scanner import DEFAULT_IMAGE_EXTENSIONS

if TYPE_CHECKING:
    from duplicates_detector.grouper import DuplicateGroup
    from duplicates_detector.metadata import VideoMetadata
    from duplicates_detector.pipeline import PipelineController
    from duplicates_detector.progress import ProgressEmitter
    from duplicates_detector.scorer import ScoredPair

_DEFAULT_VIDEO_SIZE = (160, 90)
_DEFAULT_IMAGE_SIZE = (160, 160)
_JPEG_QUALITY = 60
_FFMPEG_TIMEOUT = 15
_PROGRESS_THRESHOLD = 10


def generate_image_thumbnail(
    path: Path,
    *,
    max_size: tuple[int, int] = _DEFAULT_IMAGE_SIZE,
    quality: int = _JPEG_QUALITY,
) -> str | None:
    """Generate a base64 JPEG thumbnail for an image file.

    Returns a ``data:image/jpeg;base64,...`` data URI, or ``None`` on failure.
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.thumbnail(max_size)
            if img.mode in ("RGBA", "P", "LA", "PA"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:  # noqa: BLE001
        return None


def generate_video_thumbnail(
    path: Path,
    duration: float | None = None,
    *,
    max_size: tuple[int, int] = _DEFAULT_VIDEO_SIZE,
) -> str | None:
    """Generate a base64 JPEG thumbnail from a video frame at ~10% duration.

    Returns a ``data:image/jpeg;base64,...`` data URI, or ``None`` on failure.
    """
    try:
        seek = max(0, (duration or 0) * 0.1)
        w, h = max_size
        result = subprocess.run(
            [
                "ffmpeg",
                "-ss",
                str(seek),
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({w},iw)':'min({h},ih)':force_original_aspect_ratio=decrease",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "-q:v",
                "8",
                "pipe:1",
            ],
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        b64 = base64.b64encode(result.stdout).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:  # noqa: BLE001
        return None


def collect_pair_metadata(pairs: list[ScoredPair]) -> list[VideoMetadata]:
    """Collect unique VideoMetadata from pairs."""
    seen: set[Path] = set()
    result: list[VideoMetadata] = []
    for pair in pairs:
        for meta in (pair.file_a, pair.file_b):
            if meta.path not in seen:
                seen.add(meta.path)
                result.append(meta)
    return result


def collect_group_metadata(groups: list[DuplicateGroup]) -> list[VideoMetadata]:
    """Collect unique VideoMetadata from groups."""
    seen: set[Path] = set()
    result: list[VideoMetadata] = []
    for group in groups:
        for meta in group.members:
            if meta.path not in seen:
                seen.add(meta.path)
                result.append(meta)
    return result


def generate_thumbnails_batch(
    metadata_list: list[VideoMetadata],
    *,
    mode: str = Mode.VIDEO,
    max_size: tuple[int, int] | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
    controller: PipelineController | None = None,
) -> dict[Path, str | None]:
    """Generate thumbnails for unique files.

    Returns a dict mapping resolved paths to data URI strings or ``None``
    on failure.  When *max_size* is ``None``, per-type defaults are used
    (video: 160x90, image: 160x160).
    """
    seen: dict[Path, VideoMetadata] = {}
    for meta in metadata_list:
        resolved = meta.path.resolve()
        if resolved not in seen:
            seen[resolved] = meta

    if not seen:
        return {}

    results: dict[Path, str | None] = {}

    def _wait_if_paused() -> None:
        if controller is not None:
            controller.wait_if_paused_blocking()

    def _gen(meta: VideoMetadata) -> tuple[Path, str | None]:
        _wait_if_paused()
        resolved = meta.path.resolve()
        if mode == Mode.AUDIO:
            return resolved, None
        is_image = mode == Mode.IMAGE or (mode == Mode.AUTO and meta.path.suffix.lower() in DEFAULT_IMAGE_EXTENSIONS)
        if is_image:
            size = max_size if max_size is not None else _DEFAULT_IMAGE_SIZE
            return resolved, generate_image_thumbnail(meta.path, max_size=size)
        size = max_size if max_size is not None else _DEFAULT_VIDEO_SIZE
        return resolved, generate_video_thumbnail(meta.path, meta.duration, max_size=size)

    show_progress = len(seen) > _PROGRESS_THRESHOLD and not quiet and progress_emitter is None
    items = list(seen.values())

    if progress_emitter is not None:
        progress_emitter.stage_start("thumbnail", total=len(items))
    thumb_start = time.monotonic()
    completed = 0

    if show_progress:
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True),
            transient=True,
        )
        with progress:
            task_id = progress.add_task("Generating thumbnails", total=len(items))
            with ThreadPoolExecutor() as executor:
                futures = {executor.submit(_gen, m): m for m in items}
                for future in as_completed(futures):
                    _wait_if_paused()
                    resolved, uri = future.result()
                    results[resolved] = uri
                    progress.advance(task_id)
    else:
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(_gen, m): m for m in items}
            for future in as_completed(futures):
                _wait_if_paused()
                resolved, uri = future.result()
                results[resolved] = uri
                completed += 1
                if progress_emitter is not None:
                    progress_emitter.progress(
                        "thumbnail",
                        current=completed,
                        total=len(items),
                    )

    if progress_emitter is not None:
        _wait_if_paused()
        progress_emitter.progress("thumbnail", current=len(items), total=len(items), force=True)
        progress_emitter.stage_end("thumbnail", total=len(items), elapsed=time.monotonic() - thumb_start)

    return results
