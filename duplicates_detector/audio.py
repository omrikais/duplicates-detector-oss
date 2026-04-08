from __future__ import annotations

import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from rich.console import Console

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.progress import make_progress

if TYPE_CHECKING:
    from duplicates_detector.cache import AudioFingerprintCache
    from duplicates_detector.cache_db import CacheDB
    from duplicates_detector.progress import ProgressEmitter

_MIN_AUDIO_FP_LENGTH = 10


def check_fpcalc() -> None:
    """Raise RuntimeError if fpcalc is not available on PATH."""
    if shutil.which("fpcalc") is None:
        raise RuntimeError("fpcalc not found on PATH. Install Chromaprint: https://acoustid.org/chromaprint")


def compute_audio_fingerprint(
    path: Path,
    *,
    duration: float | None = None,
) -> tuple[int, ...] | None:
    """Run fpcalc on a single file and return the raw Chromaprint fingerprint.

    Returns a tuple of int32 values, or None on any failure (no audio stream,
    corrupt file, timeout, etc.).  Rejects fingerprints shorter than
    ``_MIN_AUDIO_FP_LENGTH`` values.
    """
    if duration is not None and duration > 0:
        timeout = max(60, int(duration * 0.5))
    else:
        timeout = 120

    try:
        result = subprocess.run(
            ["fpcalc", "-raw", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if line.startswith("FINGERPRINT="):
            raw = line[len("FINGERPRINT=") :]
            if not raw.strip():
                return None
            try:
                values = tuple(int(v) for v in raw.split(","))
            except ValueError:
                return None
            if len(values) < _MIN_AUDIO_FP_LENGTH:
                return None
            return values

    return None


def compare_audio_fingerprints(
    fp_a: tuple[int, ...],
    fp_b: tuple[int, ...],
) -> float:
    """Compare two Chromaprint fingerprints and return similarity in [0.0, 1.0].

    Uses a sliding-window approach: the shorter fingerprint is slid along the
    longer one, computing the average per-element bit similarity (32-bit XOR +
    popcount) at each offset.  Returns the best average across all offsets.
    """
    if not fp_a or not fp_b:
        return 0.0

    if len(fp_a) <= len(fp_b):
        short, long = fp_a, fp_b
    else:
        short, long = fp_b, fp_a

    num_bits = 32  # Chromaprint uses 32-bit integers

    short_arr = np.array(short, dtype=np.uint32)
    long_arr = np.array(long, dtype=np.uint32)
    n = len(short_arr)

    offsets = len(long_arr) - n + 1
    if offsets == 1:
        xor = short_arr ^ long_arr[:n]
        hamming = np.unpackbits(xor.view(np.uint8)).reshape(n, -1).sum(axis=1)
        return float((1.0 - hamming / num_bits).mean())
    # All windows: shape (offsets, n)
    windows = np.lib.stride_tricks.sliding_window_view(long_arr, n)
    # XOR: (offsets, n)
    xor = windows ^ short_arr[np.newaxis, :]
    # Hamming: (offsets, n)
    hamming = np.unpackbits(xor.view(np.uint8)).reshape(offsets, n, -1).sum(axis=2)
    avg_sim = (1.0 - hamming / num_bits).mean(axis=1)
    return float(avg_sim.max())


def extract_all_audio_fingerprints(
    metadata: list[VideoMetadata],
    *,
    workers: int = 0,
    verbose: bool = False,
    cache: AudioFingerprintCache | None = None,
    quiet: bool = False,
    progress_emitter: ProgressEmitter | None = None,
) -> list[VideoMetadata]:
    """Extract audio fingerprints for all videos in parallel.

    Uses ThreadPoolExecutor because fpcalc is subprocess-based and
    releases the GIL.  Returns a new list of VideoMetadata with the
    ``audio_fingerprint`` field populated (or None for failures).

    When *cache* is provided, previously computed fingerprints are read
    from disk and only cache-miss files are submitted to the executor.
    """
    _console = Console(stderr=True)

    check_fpcalc()

    if workers <= 0:
        workers = min((os.cpu_count() or 4) * 2, 32)

    results: list[VideoMetadata] = [None] * len(metadata)  # type: ignore[list-item]
    to_extract: dict[int, VideoMetadata] = {}

    for idx, m in enumerate(metadata):
        if cache is not None:
            cached = cache.get(m.path, m.file_size, m.mtime)
            if cached is not None:
                results[idx] = replace(m, audio_fingerprint=cached)
                continue
        to_extract[idx] = m

    if progress_emitter is not None:
        progress_emitter.stage_start("audio_fingerprint", total=len(metadata))
    fp_start = time.monotonic()
    cache_hit_count = len(metadata) - len(to_extract)

    if to_extract:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(
                    compute_audio_fingerprint,
                    m.path,
                    duration=m.duration,
                ): idx
                for idx, m in to_extract.items()
            }

            with make_progress(console=_console, quiet=quiet, progress_emitter=progress_emitter) as progress:
                task = progress.add_task("Extracting audio fingerprints", total=len(to_extract))

                for completed, future in enumerate(as_completed(future_to_idx), 1):
                    idx = future_to_idx[future]
                    fingerprint = future.result()
                    results[idx] = replace(metadata[idx], audio_fingerprint=fingerprint)
                    if cache is not None and fingerprint is not None:
                        m = metadata[idx]
                        cache.put(m.path, m.file_size, m.mtime, fingerprint)
                    progress.advance(task)
                    if progress_emitter is not None:
                        progress_emitter.progress(
                            "audio_fingerprint",
                            current=cache_hit_count + completed,
                            total=len(metadata),
                            file=str(metadata[idx].path),
                        )

    if progress_emitter is not None:
        progress_emitter.progress("audio_fingerprint", current=len(metadata), total=len(metadata), force=True)
        progress_emitter.stage_end(
            "audio_fingerprint",
            total=len(metadata),
            elapsed=time.monotonic() - fp_start,
        )

    if cache is not None:
        cache.save()
        if verbose:
            total = cache.hits + cache.misses
            rate = (cache.hits / total * 100) if total else 0
            _console.print(
                f"Audio fingerprints: {total} total, {cache.hits} cached, "
                f"{cache.misses} extracted (cache hit rate: {rate:.0f}%)"
            )

    return results


# ---------------------------------------------------------------------------
# Per-file cache-aware worker (for async pipeline / ThreadPoolExecutor)
# ---------------------------------------------------------------------------


def _fingerprint_one_with_cache(
    meta: VideoMetadata,
    cache_db: CacheDB | None,
) -> VideoMetadata:
    """Compute audio fingerprint for one file, using CacheDB if available.

    Combines stat() + cache lookup + fpcalc + cache store in one call,
    suitable for ThreadPoolExecutor workers.
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
        cached = cache_db.get_audio_fingerprint(path, file_size=file_size, mtime=mtime)
        if cached is not None:
            return replace(meta, audio_fingerprint=cached)

    # Cache miss — compute fingerprint
    fingerprint = compute_audio_fingerprint(path, duration=meta.duration)
    new_meta = replace(meta, audio_fingerprint=fingerprint)

    # Store in cache
    if cache_db is not None and fingerprint is not None:
        cache_db.put_audio_fingerprint(
            path,
            file_size=file_size,
            mtime=mtime,
            fingerprint=fingerprint,
        )

    return new_meta
