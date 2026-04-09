from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import numpy as np
import pdqhash
from PIL import Image
from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.progress import make_progress

from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from duplicates_detector.cache_db import CacheDB
    from duplicates_detector.progress import ProgressEmitter

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Constants shared with SSIM code below
_SIG_LEN = len(_PNG_SIGNATURE)
_MIN_TIMEOUT = 60  # seconds — minimum wall-clock limit per video for frame extraction
_TIMEOUT_PER_MINUTE = 3  # additional seconds per minute of video duration
_MIN_SCENE_FRAMES = 3  # minimum frames from scene detection before falling back to interval

# PDQ hash constants
_NUM_FRAMES = 10  # frames per video
_FRAME_SIZE = 64  # px for extraction
_FRAME_BYTES = _FRAME_SIZE * _FRAME_SIZE * 3  # 12288 bytes (rgb24)
_HASH_UINT64S = 4  # uint64 values per 256-bit hash
_NUM_BITS = 256
_MIN_FRAME_TIMEOUT = 30  # seconds per frame extraction


def check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is not available on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH. Install ffmpeg: https://ffmpeg.org/download.html")


# ---------------------------------------------------------------------------
# PDQ hash extraction and comparison
# ---------------------------------------------------------------------------


def _pack_pdq_hash(hash_vector: np.ndarray) -> tuple[int, ...]:
    """Pack a 256-element boolean hash vector into 4 uint64 values."""
    packed = np.packbits(hash_vector.astype(np.uint8))  # 32 bytes
    uint64s = np.frombuffer(packed.tobytes(), dtype=np.uint64)  # 4 x uint64
    return tuple(int(v) for v in uint64s)


def _extract_single_frame_hash(path: Path, timestamp: float) -> tuple[int, ...] | None:
    """Seek to a timestamp and extract one frame's PDQ hash via ffmpeg rawvideo."""
    cmd = [
        "ffmpeg",
        "-ss",
        str(timestamp),
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={_FRAME_SIZE}:{_FRAME_SIZE}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=_MIN_FRAME_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(proc.stdout) < _FRAME_BYTES:
        return None
    pixels = np.frombuffer(proc.stdout[:_FRAME_BYTES], dtype=np.uint8).reshape(_FRAME_SIZE, _FRAME_SIZE, 3)
    try:
        hash_vector, _quality = pdqhash.compute(pixels)
    except Exception:
        return None
    return _pack_pdq_hash(hash_vector)


def _extract_sparse_hashes(path: Path, duration: float | None = None) -> tuple[int, ...] | None:
    """Extract 10 frames at 5%,15%,...,95% of duration via parallel ffmpeg seeks."""
    if duration is None or duration <= 0:
        return None
    timestamps = [duration * (i * 10 + 5) / 100 for i in range(_NUM_FRAMES)]
    with ThreadPoolExecutor(max_workers=_NUM_FRAMES) as pool:
        futures = {pool.submit(_extract_single_frame_hash, path, ts): ts for ts in timestamps}
        hashes: list[tuple[int, ...]] = []
        for fut in futures:
            h = fut.result()
            if h is not None:
                hashes.append(h)
    if not hashes:
        return None
    return tuple(v for h in hashes for v in h)


def compute_image_content_hash(path: Path, rotation_invariant: bool = False) -> tuple[int, ...] | None:
    """Compute PDQ hash for a single image.

    Returns a 4-tuple of uint64 values (or 32-tuple if rotation_invariant).
    Returns None if the image cannot be opened or hashed.
    """
    try:
        with Image.open(path) as img:
            img_array = np.array(img.convert("RGB"))
    except Exception:
        return None
    if rotation_invariant:
        hash_vectors, _qualities = pdqhash.compute_dihedral(img_array)
        result: list[int] = []
        for hv in hash_vectors:
            result.extend(_pack_pdq_hash(hv))
        return tuple(result)
    hash_vector, _quality = pdqhash.compute(img_array)
    return _pack_pdq_hash(hash_vector)


def _hamming_distance_256(a_chunk: np.ndarray, b_chunk: np.ndarray) -> int:
    """Hamming distance between two 256-bit hashes (each 4 x uint64)."""
    xor = a_chunk ^ b_chunk
    return int(np.unpackbits(xor.view(np.uint8)).sum())


def _compare_content_hashes_sliding(short: np.ndarray, long: np.ndarray) -> float:
    """Sliding-window comparison. Arrays are (num_frames, 4) uint64."""
    n = len(short)
    offsets = len(long) - n + 1
    if offsets == 1:
        xor = short ^ long[:n]
        bits = np.unpackbits(xor.view(np.uint8)).reshape(n, -1).sum(axis=1)
        return float((1.0 - bits / _NUM_BITS).mean())
    # All windows: shape (offsets, n, 4)
    windows = np.lib.stride_tricks.sliding_window_view(long, (n, long.shape[1]))[:, 0, :, :]
    # XOR each window with short: (offsets, n, 4)
    xor = windows ^ short[np.newaxis, :, :]
    # Bit count per frame per window: (offsets, n)
    bits = np.unpackbits(xor.view(np.uint8)).reshape(offsets, n, -1).sum(axis=2)
    # Average similarity per window: (offsets,)
    avg_sim = (1.0 - bits / _NUM_BITS).mean(axis=1)
    return float(avg_sim.max())


def _compare_rotation_invariant(hash_a: tuple[int, ...], hash_b: tuple[int, ...]) -> float:
    """Compare rotation-invariant hashes (8 orientations x 4 uint64 each).

    Checks both directions -- A's canonical hash (index 0) against all of B's
    orientation hashes, then B's canonical against all of A's -- and takes the
    minimum Hamming distance.  Returns similarity in [0.0, 1.0].
    """
    a_arr = np.array(hash_a, dtype=np.uint64).reshape(-1, _HASH_UINT64S)
    b_arr = np.array(hash_b, dtype=np.uint64).reshape(-1, _HASH_UINT64S)
    min_dist = _NUM_BITS
    for i in range(len(b_arr)):
        dist = _hamming_distance_256(a_arr[0], b_arr[i])
        if dist < min_dist:
            min_dist = dist
            if dist == 0:
                return 1.0
    for i in range(len(a_arr)):
        dist = _hamming_distance_256(b_arr[0], a_arr[i])
        if dist < min_dist:
            min_dist = dist
            if dist == 0:
                return 1.0
    return 1.0 - min_dist / _NUM_BITS


def compare_content_hashes(
    hash_a: tuple[int, ...],
    hash_b: tuple[int, ...],
    rotation_invariant: bool = False,
) -> float:
    """Compare two PDQ hash sequences. Returns similarity in [0.0, 1.0].

    For video hashes (multi-frame), uses sliding-window comparison.
    For rotation-invariant image hashes, uses minimum-Hamming across orientations.
    """
    if not hash_a or not hash_b:
        return 0.0
    if rotation_invariant:
        return _compare_rotation_invariant(hash_a, hash_b)
    a_arr = np.array(hash_a, dtype=np.uint64).reshape(-1, _HASH_UINT64S)
    b_arr = np.array(hash_b, dtype=np.uint64).reshape(-1, _HASH_UINT64S)
    if len(a_arr) <= len(b_arr):
        short, long = a_arr, b_arr
    else:
        short, long = b_arr, a_arr
    return _compare_content_hashes_sliding(short, long)


# ---------------------------------------------------------------------------
# SSIM frame extraction and comparison
# ---------------------------------------------------------------------------

_SSIM_RESIZE = 256  # comparison resolution for SSIM


def _extract_frames_from_ffmpeg(
    cmd: list[str],
    timeout: int,
) -> tuple[bytes, ...] | None:
    """Run an ffmpeg command and collect the raw PNG frame bytes.

    Same Popen + buffer + PNG-split logic as ``_extract_hashes_from_ffmpeg()``,
    but collects raw bytes instead of hashing.  Returns None if no frames could
    be extracted or the process timed out.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None

    if proc.stdout is None:
        raise ValueError("ffmpeg process stdout is None despite stdout=PIPE")
    frames: list[bytes] = []

    timed_out = threading.Event()

    def _kill_on_timeout() -> None:
        try:
            proc.kill()
        except OSError:
            return
        timed_out.set()

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.start()

    try:
        buf = bytearray()
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buf.extend(chunk)

            while True:
                next_sig = buf.find(_PNG_SIGNATURE, _SIG_LEN)
                if next_sig == -1:
                    break
                frame_data = bytes(buf[:next_sig])
                del buf[:next_sig]
                frames.append(frame_data)

        if buf and buf[:_SIG_LEN] == _PNG_SIGNATURE:
            frames.append(bytes(buf))
    finally:
        timer.cancel()
        proc.stdout.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    if timed_out.is_set():
        return None

    return tuple(frames) if frames else None


def _compute_timeout(duration: float | None) -> int:
    """Wall-clock timeout for frame extraction, scaling with video duration."""
    if duration is not None and duration > 0:
        return max(_MIN_TIMEOUT, int(duration / 60 * _TIMEOUT_PER_MINUTE) + _MIN_TIMEOUT)
    return _MIN_TIMEOUT


def extract_frames(
    path: Path,
    interval: float = 2.0,
    duration: float | None = None,
) -> tuple[bytes, ...] | None:
    """Extract raw PNG frames from a video at fixed intervals.

    Used by the SSIM comparison path.
    """
    cmd = [
        "ffmpeg",
        "-i",
        str(path),
        "-vf",
        f"fps=1/{interval}",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    return _extract_frames_from_ffmpeg(cmd, _compute_timeout(duration))


def extract_frames_scene(
    path: Path,
    threshold: float = 0.3,
    duration: float | None = None,
    fallback_interval: float = 2.0,
) -> tuple[bytes, ...] | None:
    """Extract raw PNG frames at scene changes, with interval fallback.

    Falls back to interval-based extraction when scene detection yields
    fewer than ``_MIN_SCENE_FRAMES`` frames.
    """
    cmd = [
        "ffmpeg",
        "-i",
        str(path),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-vsync",
        "vfr",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    result = _extract_frames_from_ffmpeg(cmd, _compute_timeout(duration))

    if result is None or len(result) < _MIN_SCENE_FRAMES:
        return extract_frames(path, interval=fallback_interval, duration=duration)

    return result


def extract_image_frame(path: Path) -> tuple[bytes, ...] | None:
    """Open an image with PIL and return its raw PNG data as a 1-tuple.

    Returns None if the image cannot be opened.
    """
    try:
        buf = BytesIO()
        with Image.open(path) as img:
            img.convert("RGB").save(buf, format="PNG")
        return (buf.getvalue(),)
    except Exception:
        return None


def compare_ssim_frames(
    frames_a: tuple[bytes, ...],
    frames_b: tuple[bytes, ...],
) -> float:
    """Compare two frame sequences using SSIM with sliding window.

    Pre-decodes all frames to grayscale numpy arrays at ``_SSIM_RESIZE`` resolution,
    then slides the shorter sequence along the longer one, returning the best
    average SSIM score across all offsets.

    Returns 0.0 for empty inputs.
    """
    if not frames_a or not frames_b:
        return 0.0

    from skimage.metrics import structural_similarity

    def _decode(data: bytes) -> np.ndarray | None:
        try:
            img = Image.open(BytesIO(data)).convert("L").resize((_SSIM_RESIZE, _SSIM_RESIZE))
            return np.asarray(img)
        except Exception:
            return None

    arr_a = [a for f in frames_a if (a := _decode(f)) is not None]
    arr_b = [a for f in frames_b if (a := _decode(f)) is not None]

    if not arr_a or not arr_b:
        return 0.0

    if len(arr_a) <= len(arr_b):
        short, long = arr_a, arr_b
    else:
        short, long = arr_b, arr_a

    best = 0.0
    offsets = len(long) - len(short) + 1
    for offset in range(offsets):
        total_sim = 0.0
        for i, s_frame in enumerate(short):
            sim = structural_similarity(s_frame, long[offset + i])
            total_sim += sim  # type: ignore[assignment]  # skimage returns float
        avg = total_sim / len(short)
        if avg > best:
            best = avg
        if best >= 1.0:
            break
    return best


def _extract_all_frames(
    metadata: list[VideoMetadata],
    submit_fn: Callable,
    *,
    workers: int = 0,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Core SSIM frame extraction loop shared by video and image paths.

    *submit_fn(executor, idx, meta)* submits a single extraction job and
    returns a Future. The rest (progress, stage lifecycle, result assembly)
    is handled here.
    """
    if workers <= 0:
        workers = min((os.cpu_count() or 4) * 2, 32)

    if progress_emitter is not None:
        progress_emitter.stage_start("ssim_extract", total=len(metadata))
    ssim_start = time.monotonic()

    results: list[VideoMetadata] = [None] * len(metadata)  # type: ignore[list-item]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {submit_fn(executor, idx, m): idx for idx, m in enumerate(metadata)}

        with make_progress(quiet=quiet, progress_emitter=progress_emitter) as progress:
            task = progress.add_task("Extracting frames (SSIM)", total=len(metadata))

            for completed, future in enumerate(as_completed(future_to_idx), 1):
                idx = future_to_idx[future]
                content_frames = future.result()
                results[idx] = replace(metadata[idx], content_frames=content_frames)
                progress.advance(task)
                if progress_emitter is not None:
                    progress_emitter.progress(
                        "ssim_extract",
                        current=completed,
                        total=len(metadata),
                        file=str(metadata[idx].path),
                    )

    if progress_emitter is not None:
        progress_emitter.progress("ssim_extract", current=len(metadata), total=len(metadata), force=True)
        progress_emitter.stage_end("ssim_extract", total=len(metadata), elapsed=time.monotonic() - ssim_start)

    return results


def extract_all_ssim_frames(
    metadata: list[VideoMetadata],
    *,
    workers: int = 0,
    verbose: bool = False,
    quiet: bool = False,
    interval: float = 2.0,
    strategy: str = "interval",
    scene_threshold: float = 0.3,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract raw frames for SSIM comparison from all videos in parallel."""
    check_ffmpeg()

    if strategy == "scene":

        def _submit(ex: ThreadPoolExecutor, _idx: int, m: VideoMetadata) -> Any:
            return ex.submit(
                extract_frames_scene,
                m.path,
                threshold=scene_threshold,
                duration=m.duration,
                fallback_interval=interval,
            )
    else:

        def _submit(ex: ThreadPoolExecutor, _idx: int, m: VideoMetadata) -> Any:
            return ex.submit(extract_frames, m.path, interval=interval, duration=m.duration)

    return _extract_all_frames(metadata, _submit, workers=workers, quiet=quiet, progress_emitter=progress_emitter)


def extract_all_image_ssim_frames(
    metadata: list[VideoMetadata],
    *,
    workers: int = 0,
    verbose: bool = False,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract raw frames for SSIM comparison from all images in parallel."""
    return _extract_all_frames(
        metadata,
        lambda ex, _idx, m: ex.submit(extract_image_frame, m.path),
        workers=workers,
        quiet=quiet,
        progress_emitter=progress_emitter,
    )


# ---------------------------------------------------------------------------
# SimHash: document content fingerprinting
# ---------------------------------------------------------------------------

_SIMHASH_BITS = 64


def compute_document_simhash(
    path: Path, mode_ext: str, *, pre_extracted_text: str | None = None
) -> tuple[int, ...] | None:
    """Compute a 64-bit SimHash fingerprint for a document file.

    When *pre_extracted_text* is provided, uses it directly instead of
    re-reading the file from disk (avoids double extraction when the
    metadata stage already extracted the text).

    Dispatches on *mode_ext* (lowercased file extension including dot):
    - ``.pdf`` → pdfminer ``extract_text``
    - ``.docx`` → python-docx paragraph text
    - ``.txt`` / ``.md`` → plain ``read_text``

    Returns a 4-element uint64 tuple ``(fingerprint, 0, 0, 0)`` to fit
    the existing ``(num_frames, 4)`` content-hash schema, or None when
    the file cannot be read or contains fewer than 2 words.
    """
    if pre_extracted_text is not None:
        text = pre_extracted_text
    else:
        text = ""
        try:
            if mode_ext == ".pdf":
                from pdfminer.high_level import extract_text  # lazy

                text = extract_text(str(path))
            elif mode_ext == ".docx":
                import docx  # lazy  (python-docx)

                doc = docx.Document(str(path))
                text = "\n".join(p.text for p in doc.paragraphs)
            elif mode_ext in {".txt", ".md"}:
                text = path.read_text(errors="replace")
            else:
                return None
        except Exception:
            return None

    words = text.split()
    if len(words) < 2:
        return None

    # Build word bigrams
    bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]

    # Accumulate bit-weight vector
    weights = [0] * _SIMHASH_BITS
    for bigram in bigrams:
        h = hashlib.md5(bigram.encode("utf-8")).digest()  # noqa: S324
        val = int.from_bytes(h[:8], "big")  # lower 64 bits
        for bit in range(_SIMHASH_BITS):
            if val & (1 << bit):
                weights[bit] += 1
            else:
                weights[bit] -= 1

    # Threshold
    fingerprint = 0
    for bit in range(_SIMHASH_BITS):
        if weights[bit] > 0:
            fingerprint |= 1 << bit

    return (fingerprint, 0, 0, 0)


def compare_simhash(hash_a: tuple[int, ...], hash_b: tuple[int, ...]) -> float:
    """Compare two SimHash fingerprints. Returns similarity in [0.0, 1.0].

    Extracts the first element from each tuple, computes Hamming distance,
    and returns ``1.0 - hamming / 64``.  Returns 0.0 if either tuple is empty.
    """
    if not hash_a or not hash_b:
        return 0.0
    a = hash_a[0]
    b = hash_b[0]
    xor = a ^ b
    hamming = bin(xor).count("1")
    return 1.0 - hamming / _SIMHASH_BITS


# ---------------------------------------------------------------------------
# Pre-hash: fast byte-level identity check before perceptual hashing
# ---------------------------------------------------------------------------

_PRE_HASH_BYTES = 4096


def compute_pre_hash(path: Path) -> str | None:
    """Return MD5 hex digest of the first 4KB of *path*, or None on error."""
    try:
        with open(path, "rb") as f:
            data = f.read(_PRE_HASH_BYTES)
        return hashlib.md5(data).hexdigest()  # noqa: S324
    except OSError:
        return None


def _synthetic_content_hash(pre_hash_hex: str) -> tuple[int, ...]:
    """Convert a 32-char MD5 hex digest to a 4-element uint64 tuple.

    Packs the 128-bit MD5 into two uint64 values, then repeats them
    to form a valid 256-bit PDQ-shaped hash: ``(a, b, a, b)``.
    """
    raw = bytes.fromhex(pre_hash_hex)  # 16 bytes
    a = int.from_bytes(raw[:8], "big")
    b = int.from_bytes(raw[8:], "big")
    return (a, b, a, b)


def _pre_hash_one_with_cache(
    meta: VideoMetadata,
    cache_db: CacheDB | None,
) -> VideoMetadata:
    """Compute pre-hash for one file, using CacheDB if available.

    Returns a new VideoMetadata with ``pre_hash`` populated, or
    unchanged if the file cannot be stat'd.
    """
    try:
        st = meta.path.stat()
    except OSError:
        return meta

    file_size = st.st_size
    mtime = st.st_mtime

    if cache_db is not None:
        cached = cache_db.get_pre_hash(meta.path, file_size=file_size, mtime=mtime)
        if cached is not None:
            return replace(meta, pre_hash=cached)

    pre_hash = compute_pre_hash(meta.path)
    if pre_hash is not None and cache_db is not None:
        cache_db.put_pre_hash(meta.path, file_size=file_size, mtime=mtime, pre_hash=pre_hash)

    return replace(meta, pre_hash=pre_hash)


# ---------------------------------------------------------------------------
# Per-file cache-aware worker (for async pipeline / ThreadPoolExecutor)
# ---------------------------------------------------------------------------


def _hash_one_with_cache(
    meta: VideoMetadata,
    cache_db: CacheDB | None,
    *,
    rotation_invariant: bool = False,
    is_image: bool = False,
    is_document: bool = False,
) -> VideoMetadata:
    """Compute content hash for one file, using CacheDB if available.

    Combines stat() + cache lookup + hash computation + cache store in one
    call, suitable for ThreadPoolExecutor workers.

    When *is_document* is True, uses ``compute_document_simhash`` (text extraction).
    When *is_image* is True, uses ``compute_image_content_hash`` (PIL, no
    ffmpeg).  Otherwise uses ``_extract_sparse_hashes`` (ffmpeg rawvideo).
    """
    path = meta.path
    try:
        st = path.stat()
    except OSError:
        return meta  # Return unchanged

    file_size = st.st_size
    mtime = st.st_mtime

    # Try cache
    if cache_db is not None:
        cached = cache_db.get_content_hash(
            path,
            file_size=file_size,
            mtime=mtime,
            rotation_invariant=rotation_invariant,
        )
        if cached is not None:
            return replace(meta, content_hash=cached)

    # Cache miss -- compute hash
    content_hash: tuple[int, ...] | None
    if is_document:
        content_hash = compute_document_simhash(path, path.suffix.lower(), pre_extracted_text=meta.text_content)
    elif is_image:
        content_hash = compute_image_content_hash(path, rotation_invariant=rotation_invariant)
    else:
        content_hash = _extract_sparse_hashes(path, duration=meta.duration)

    new_meta = replace(meta, content_hash=content_hash)

    # Store in cache if computed
    if cache_db is not None and content_hash is not None:
        cache_db.put_content_hash(
            path,
            file_size=file_size,
            mtime=mtime,
            hashes=content_hash,
            rotation_invariant=rotation_invariant,
        )

    return new_meta
