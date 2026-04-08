"""Integration tests for extreme durations, resolutions, and file sizes."""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.content import _extract_sparse_hashes
from duplicates_detector.metadata import extract_one

from conftest import _get_integ_generators, _require_integ_file

pytestmark = pytest.mark.slow

_gen = _get_integ_generators()


@pytest.fixture(scope="session")
def extreme_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
    d = tmp_path_factory.mktemp("extreme")
    files = _gen.generate_extreme_media(d)
    if not any(files.values()):
        pytest.skip("No extreme media could be generated")
    return files


class TestExtremeDurations:
    def test_ten_minute_metadata(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "ten_minute_video")
        meta = extract_one(path)
        assert meta is not None
        assert meta.duration is not None
        assert meta.duration > 500  # ~600s expected

    def test_ten_minute_content_hash(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "ten_minute_video")
        meta = extract_one(path)
        assert meta is not None and meta.duration is not None
        h = _extract_sparse_hashes(path, meta.duration)
        assert h is not None
        assert len(h) > 0

    def test_subsecond_metadata(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "subsecond_video")
        meta = extract_one(path)
        assert meta is not None
        assert meta.duration is not None
        assert meta.duration < 1.0

    def test_subsecond_content_hash(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "subsecond_video")
        meta = extract_one(path)
        assert meta is not None and meta.duration is not None
        h = _extract_sparse_hashes(path, meta.duration)
        # May return None for very short videos — that's acceptable
        # But should not crash

    def test_single_frame_metadata(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "single_frame_video")
        meta = extract_one(path)
        assert meta is not None
        assert meta.width == 320
        assert meta.height == 240

    def test_single_frame_content_hash(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "single_frame_video")
        meta = extract_one(path)
        assert meta is not None
        dur = meta.duration if meta.duration else 0.04
        h = _extract_sparse_hashes(path, dur)
        # Single frame — sparse extraction should still produce something or None


class TestExtremeResolutions:
    def test_8k_metadata(self, extreme_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(extreme_media, "huge_resolution")
        meta = extract_one(path)
        assert meta is not None
        assert meta.width == 7680
        assert meta.height == 4320

    def test_8k_content_hash_no_oom(self, extreme_media: dict[str, Path | None]) -> None:
        """8K content hashing should complete without OOM."""
        path = _require_integ_file(extreme_media, "huge_resolution")
        meta = extract_one(path)
        assert meta is not None
        dur = meta.duration if meta.duration else 0.04
        h = _extract_sparse_hashes(path, dur)
        # Should complete without memory error


class TestExtremeEndToEnd:
    def test_mixed_extremes_pipeline(self, extreme_media: dict[str, Path | None], tmp_path: Path) -> None:
        """Pipeline completes with mix of extreme and normal files."""
        import shutil

        from duplicates_detector.cli import main

        scan_dir = tmp_path / "mixed_extreme"
        scan_dir.mkdir()

        copied = 0
        for key in ["ten_minute_video", "subsecond_video", "single_frame_video"]:
            src = extreme_media.get(key)
            if src is not None:
                shutil.copy2(src, scan_dir / src.name)
                copied += 1

        if copied < 2:
            pytest.skip("Need at least 2 extreme files for pipeline test")

        # main() returns None on success, raises SystemExit on error
        main(["scan", str(scan_dir), "--format", "json", "--quiet"])
