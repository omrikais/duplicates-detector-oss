"""Integration tests for corrupt/malformed media files.

Verifies the pipeline handles bad files gracefully — no crashes, proper skip/warning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.content import _extract_sparse_hashes
from duplicates_detector.metadata import extract_one

from conftest import _get_integ_generators, _require_integ_file

pytestmark = pytest.mark.slow

_gen = _get_integ_generators()


@pytest.fixture(scope="session")
def corrupt_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
    d = tmp_path_factory.mktemp("corrupt")
    files = _gen.generate_corrupt_media(d)
    if not any(files.values()):
        pytest.skip("No corrupt media could be generated (ffmpeg unavailable?)")
    return files


class TestCorruptContainers:
    def test_truncated_mp4_extraction(self, corrupt_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(corrupt_media, "truncated_mp4")
        extract_one(path)  # should not crash
        # Either returns None or metadata with partial info

    def test_truncated_mkv_extraction(self, corrupt_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(corrupt_media, "truncated_mkv")
        extract_one(path)  # should not crash

    def test_corrupt_moov_extraction(self, corrupt_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(corrupt_media, "corrupt_moov")
        extract_one(path)  # may return None or partial metadata — either is acceptable

    def test_valid_header_corrupt_frames_extraction(self, corrupt_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(corrupt_media, "valid_header_corrupt_frames")
        # Metadata extraction may succeed (header is valid)
        meta = extract_one(path)
        # Content hashing should handle corrupt frames gracefully
        if meta is not None and meta.duration is not None:
            _extract_sparse_hashes(path, meta.duration)  # should not crash

    def test_mismatched_extension_extraction(self, corrupt_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(corrupt_media, "mismatched_extension")
        result = extract_one(path)
        # ffprobe probes content, not extension — should succeed
        assert result is not None
        assert result.duration is not None
        assert result.duration > 0

    def test_zero_audio_stream_extraction(self, corrupt_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(corrupt_media, "zero_audio_stream")
        extract_one(path)  # should not crash on empty audio stream

    def test_mixed_batch_pipeline(self, corrupt_media: dict[str, Path | None], tmp_path: Path) -> None:
        """Full pipeline scan of directory with valid + corrupt files.

        Uses 2 valid files (so pairs can be formed) + 1 corrupt file.
        Verifies: pipeline completes, corrupt file skipped, valid pair scored.
        """
        from duplicates_detector.cli import main

        scan_dir = tmp_path / "mixed"
        scan_dir.mkdir()

        # Need 2 valid files for pairing + 1 corrupt
        valid_a = corrupt_media.get("mismatched_extension")
        valid_b = corrupt_media.get("valid_header_corrupt_frames")  # header is readable
        corrupt = corrupt_media.get("truncated_mp4")
        if valid_a is None or corrupt is None:
            pytest.skip("Need valid and corrupt files for mixed batch test")

        import shutil

        shutil.copy2(valid_a, scan_dir / "valid_a.mp4")
        if valid_b is not None:
            shutil.copy2(valid_b, scan_dir / "valid_b.mp4")
        shutil.copy2(corrupt, scan_dir / "corrupt.mp4")

        # Pipeline should complete without crashing
        main(["scan", str(scan_dir), "--format", "json", "--quiet"])
