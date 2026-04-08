"""Integration tests for multi-stream containers."""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.metadata import extract_one

from conftest import _get_integ_generators, _require_integ_file

pytestmark = pytest.mark.slow

_gen = _get_integ_generators()


@pytest.fixture(scope="session")
def multistream_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | None]:
    d = tmp_path_factory.mktemp("multistream")
    files = _gen.generate_multistream_media(d)
    if not any(files.values()):
        pytest.skip("No multistream media could be generated")
    return files


class TestMultiStreamExtraction:
    def test_dual_audio_tracks(self, multistream_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(multistream_media, "dual_audio_tracks")
        meta = extract_one(path)
        assert meta is not None
        assert meta.duration is not None and meta.duration > 0
        assert meta.width == 320

    def test_triple_video_streams(self, multistream_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(multistream_media, "triple_video_streams")
        meta = extract_one(path)
        assert meta is not None
        # Should extract the first video stream correctly
        assert meta.width == 320
        assert meta.height == 240

    def test_video_subtitle_data(self, multistream_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(multistream_media, "video_subtitle_data")
        meta = extract_one(path)
        assert meta is not None
        # Non-AV streams should not confuse extraction
        assert meta.duration is not None and meta.duration > 0
        assert meta.width == 320

    def test_audio_only_container_in_video_mode(self, multistream_media: dict[str, Path | None]) -> None:
        path = _require_integ_file(multistream_media, "audio_only_container")
        meta = extract_one(path)
        # Audio-only file: extract_one may return metadata with no video dimensions
        # or return None — either is acceptable, but should not crash
        if meta is not None:
            # If extracted, width/height should be None (no video stream)
            assert meta.width is None or meta.width == 0
