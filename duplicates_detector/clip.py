"""CLIP ViT-B/32 embedding extraction and comparison.

Provides image preprocessing, embedding extraction via ONNX Runtime, and
cosine-similarity comparison with sliding-window support for video
(multi-frame) embeddings.

The ONNX model is downloaded on first use and cached under
``XDG_CACHE_HOME/duplicates-detector/models/``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
from pathlib import Path

import numpy as np

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

    from duplicates_detector.cache_db import CacheDB
    from duplicates_detector.metadata import VideoMetadata

# ---------------------------------------------------------------------------
# CLIP constants
# ---------------------------------------------------------------------------

_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_EMBED_DIM = 512
_INPUT_SIZE = 224

# Model download configuration
_MODEL_URL = "https://huggingface.co/jmzzomg/clip-vit-base-patch32-vision-onnx/resolve/main/model.onnx"
_MODEL_SHA256 = "c68d3d9a200ddd2a8c8a5510b576d4c94d1ae383bf8b36dd8c084f94e1fb4d63"
_MODEL_FILENAME = "clip-vit-b32-visual.onnx"

# Video frame extraction
_NUM_FRAMES = 10
_MIN_FRAME_TIMEOUT = 30  # seconds per frame extraction

# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------


def _preprocess_image(img: PILImage.Image) -> np.ndarray:
    """Resize, center-crop, and normalize an image for CLIP.

    Returns a ``(1, 3, 224, 224)`` float32 array ready for ONNX inference.

    Steps:
    1. Convert to RGB.
    2. Resize so the shortest side is 224 pixels.
    3. Center-crop to 224x224.
    4. Convert to float32 in [0, 1].
    5. Normalize with CLIP mean/std.
    6. Transpose HWC -> CHW, add batch dimension.
    """
    img = img.convert("RGB")

    # Resize shortest side to 224
    w, h = img.size
    if w < h:
        new_w = _INPUT_SIZE
        new_h = int(h * _INPUT_SIZE / w)
    else:
        new_h = _INPUT_SIZE
        new_w = int(w * _INPUT_SIZE / h)
    img = img.resize((new_w, new_h), resample=3)  # LANCZOS = 3

    # Center crop to 224x224
    w, h = img.size
    left = (w - _INPUT_SIZE) // 2
    top = (h - _INPUT_SIZE) // 2
    img = img.crop((left, top, left + _INPUT_SIZE, top + _INPUT_SIZE))

    # To float32 array, normalize
    arr = np.array(img, dtype=np.float32) / 255.0
    arr = (arr - _CLIP_MEAN) / _CLIP_STD

    # HWC -> CHW, add batch dim
    arr = arr.transpose(2, 0, 1)
    return arr[np.newaxis, :, :, :]


# ---------------------------------------------------------------------------
# Embedding comparison
# ---------------------------------------------------------------------------


def compare_clip_embeddings(
    emb_a: tuple[float, ...],
    emb_b: tuple[float, ...],
) -> float:
    """Compare two CLIP embeddings via cosine similarity.

    Supports multi-frame (video) embeddings: reshapes to ``(N, 512)``,
    L2-normalizes rows, slides the shorter embedding along the longer,
    computes per-frame dot products, averages over windows, and returns
    the maximum window average.  Same sliding-window structure as
    PDQ/audio fingerprint comparison.

    Single-frame (image) embeddings (512 floats) produce a single
    dot-product similarity score.

    Returns similarity in ``[0.0, 1.0]``.
    """
    a = np.array(emb_a, dtype=np.float32).reshape(-1, _EMBED_DIM)
    b = np.array(emb_b, dtype=np.float32).reshape(-1, _EMBED_DIM)

    # L2 normalize each row
    a = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-8)
    b = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-8)

    # Ensure a is the shorter
    if len(a) > len(b):
        a, b = b, a

    n = len(a)
    offsets = len(b) - n + 1

    if offsets == 1:
        # Same length: per-frame dot products, average
        sims = np.sum(a * b[:n], axis=1)
        return float(np.clip(sims.mean(), 0.0, 1.0))

    # Sliding window: compute average similarity for each offset
    best = -1.0
    for offset in range(offsets):
        window = b[offset : offset + n]
        sims = np.sum(a * window, axis=1)
        avg = float(sims.mean())
        if avg > best:
            best = avg

    return float(np.clip(best, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Model management (lazy singleton)
# ---------------------------------------------------------------------------

_session_lock = threading.Lock()
_session_instance: object | None = None


def _get_models_dir() -> Path:
    """Return the directory for storing ONNX models."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "duplicates-detector" / "models"


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file by streaming in 64KB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _ensure_model(*, quiet: bool = False) -> Path:
    """Download the CLIP ViT-B/32 visual encoder ONNX model if not present.

    Stores under ``XDG_CACHE_HOME/duplicates-detector/models/``.
    Validates SHA-256 when ``_MODEL_SHA256`` is set.
    Shows Rich progress during download unless *quiet* is True
    (used when ``--machine-progress`` is active to keep stderr JSONL-clean).
    """
    models_dir = _get_models_dir()
    model_path = models_dir / _MODEL_FILENAME

    if model_path.exists():
        if _MODEL_SHA256:
            digest = _sha256_file(model_path)
            if digest == _MODEL_SHA256:
                return model_path
            # Hash mismatch — re-download
        else:
            return model_path

    models_dir.mkdir(parents=True, exist_ok=True)

    import urllib.request

    from rich.console import Console
    from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn

    if quiet:
        console = None
    else:
        console = Console(stderr=True)
        console.print(f"[dim]Downloading CLIP model to {model_path}...[/dim]")

    tmp_path = model_path.with_suffix(".tmp")
    try:
        if quiet:
            # Silent download — no Rich output to stderr
            with urllib.request.urlopen(_MODEL_URL) as response:  # noqa: S310
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
        else:
            with (
                urllib.request.urlopen(_MODEL_URL) as response,  # noqa: S310
                Progress(
                    "[progress.description]{task.description}",
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    console=console,
                    transient=True,
                ) as progress,
            ):
                total = int(response.headers.get("Content-Length", 0))
                task = progress.add_task("CLIP ViT-B/32", total=total or None)
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        progress.advance(task, len(chunk))
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise RuntimeError(
            f"Failed to download CLIP model from {_MODEL_URL}\n"
            f"Error: {exc}\n"
            f"You can download it manually and place it at: {model_path}"
        ) from exc

    # Validate hash if configured
    if _MODEL_SHA256:
        digest = _sha256_file(tmp_path)
        if digest != _MODEL_SHA256:
            tmp_path.unlink()
            raise RuntimeError(f"CLIP model hash mismatch: expected {_MODEL_SHA256}, got {digest}")

    os.replace(str(tmp_path), str(model_path))
    return model_path


def _get_session(*, quiet: bool = False) -> object:
    """Return a lazily-initialized ONNX InferenceSession (thread-safe singleton)."""
    global _session_instance  # noqa: PLW0603
    if _session_instance is not None:
        return _session_instance
    with _session_lock:
        if _session_instance is not None:
            return _session_instance
        import onnxruntime as ort  # type: ignore[import-untyped]

        model_path = _ensure_model(quiet=quiet)
        _session_instance = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        return _session_instance


# ---------------------------------------------------------------------------
# Video frame extraction
# ---------------------------------------------------------------------------


def _extract_video_frames(path: Path, duration: float) -> list[PILImage.Image]:
    """Extract 10 sparse keyframes at 5%, 15%, ..., 95% of duration.

    Uses the same ffmpeg seek strategy as PDQ hashing in content.py.
    Returns a list of PIL Images. Frames that fail to extract are skipped.
    """
    from PIL import Image

    if duration <= 0:
        return []

    timestamps = [duration * (i * 10 + 5) / 100 for i in range(_NUM_FRAMES)]
    frames: list[PILImage.Image] = []

    import io

    for ts in timestamps:
        cmd = [
            "ffmpeg",
            "-ss",
            str(ts),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "bmp",
            "-",
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=_MIN_FRAME_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0 or not proc.stdout:
            continue
        frames.append(Image.open(io.BytesIO(proc.stdout)))

    return frames


# ---------------------------------------------------------------------------
# Embedding computation
# ---------------------------------------------------------------------------


def compute_clip_embedding(
    path: Path,
    *,
    is_video: bool = False,
    duration: float | None = None,
    quiet: bool = False,
    required: bool = False,
) -> tuple[float, ...] | None:
    """Compute CLIP embedding for a file.

    For images: returns 512 floats (single frame).
    For videos: returns 5120 floats (10 frames x 512 dims).

    Uses ONNX Runtime for inference. Returns None on failure.

    Parameters
    ----------
    quiet:
        Suppress Rich download progress on stderr (for ``--machine-progress``).
    required:
        If True, raise instead of returning None when the CLIP session
        cannot be initialised.  Used when the user explicitly requested
        ``--content-method clip``.
    """
    from PIL import Image

    try:
        session = _get_session(quiet=quiet)
    except (RuntimeError, ImportError, OSError) as exc:
        if required:
            raise RuntimeError(
                f"CLIP model failed to initialise and --content-method clip was requested. Cannot continue.\n{exc}"
            ) from exc
        import sys

        print(f"Warning: CLIP unavailable: {exc}", file=sys.stderr)
        return None

    if is_video:
        if duration is None or duration <= 0:
            return None
        images = _extract_video_frames(path, duration)
        if not images:
            return None
    else:
        try:
            img = Image.open(path)
            img.load()
            images = [img]
        except Exception:
            return None

    embeddings: list[np.ndarray] = []
    input_name = session.get_inputs()[0].name  # type: ignore[union-attr]
    output_name = session.get_outputs()[0].name  # type: ignore[union-attr]

    for img in images:
        preprocessed = _preprocess_image(img)
        result = session.run([output_name], {input_name: preprocessed})  # type: ignore[union-attr]
        emb = result[0].flatten().astype(np.float32)
        # L2 normalize
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        embeddings.append(emb)

    if not embeddings:
        return None

    combined = np.concatenate(embeddings)
    return tuple(float(v) for v in combined)


# ---------------------------------------------------------------------------
# Per-file cache-aware worker (for async pipeline / ThreadPoolExecutor)
# ---------------------------------------------------------------------------


def _clip_one_with_cache(
    meta: VideoMetadata,
    cache_db: CacheDB | None,
    *,
    is_image: bool = False,
    quiet: bool = False,
    required: bool = False,
) -> VideoMetadata:
    """Compute CLIP embedding for one file, using CacheDB if available.

    Combines stat() + cache lookup + embedding computation + cache store
    in one call, suitable for ThreadPoolExecutor workers.

    Module-level function for compatibility with executor patterns.
    """
    from dataclasses import replace

    path = meta.path
    try:
        st = path.stat()
    except OSError:
        return meta  # Return unchanged

    file_size = st.st_size
    mtime = st.st_mtime

    # Try cache
    if cache_db is not None:
        cached = cache_db.get_clip_embedding(path, file_size=file_size, mtime=mtime)
        if cached is not None:
            return replace(meta, clip_embedding=cached)

    # Cache miss -- compute embedding
    is_video = not is_image and meta.duration is not None and meta.duration > 0
    embedding = compute_clip_embedding(
        path,
        is_video=is_video,
        duration=meta.duration,
        quiet=quiet,
        required=required,
    )

    new_meta = replace(meta, clip_embedding=embedding)

    # Store in cache if computed
    if cache_db is not None and embedding is not None:
        cache_db.put_clip_embedding(path, file_size=file_size, mtime=mtime, embedding=embedding)

    return new_meta
