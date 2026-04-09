from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.sidecar import (
    _DEFAULT_SIDECAR_EXTENSIONS,
    _LRDATA_SUFFIX,
    find_sidecars,
)


# ---------------------------------------------------------------------------
# find_sidecars — discovery patterns
# ---------------------------------------------------------------------------


class TestFindSidecars:
    def test_no_sidecars(self, tmp_path: Path):
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        assert find_sidecars(media) == []

    def test_stem_pattern(self, tmp_path: Path):
        """stem + ext: IMG_1234.xmp alongside IMG_1234.jpg."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        xmp = tmp_path / "IMG_1234.xmp"
        xmp.touch()
        result = find_sidecars(media)
        assert result == [xmp]

    def test_fullname_pattern(self, tmp_path: Path):
        """full_name + ext: IMG_1234.jpg.xmp alongside IMG_1234.jpg."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        xmp = tmp_path / "IMG_1234.jpg.xmp"
        xmp.touch()
        result = find_sidecars(media)
        assert result == [xmp]

    def test_both_patterns_deduplicated(self, tmp_path: Path):
        """Both stem and fullname sidecars found, deduplicated."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        xmp_stem = tmp_path / "IMG_1234.xmp"
        xmp_stem.touch()
        xmp_full = tmp_path / "IMG_1234.jpg.xmp"
        xmp_full.touch()
        result = find_sidecars(media)
        assert len(result) == 2
        assert xmp_stem in result
        assert xmp_full in result

    def test_multiple_extensions(self, tmp_path: Path):
        """Multiple sidecar types detected."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        xmp = tmp_path / "IMG_1234.xmp"
        xmp.touch()
        aae = tmp_path / "IMG_1234.aae"
        aae.touch()
        json_sc = tmp_path / "IMG_1234.json"
        json_sc.touch()
        result = find_sidecars(media)
        assert len(result) == 3
        assert xmp in result
        assert aae in result
        assert json_sc in result

    def test_lrdata_directory(self, tmp_path: Path):
        """stem.lrdata/ directory detected as sidecar."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        lrdata = tmp_path / "IMG_1234.lrdata"
        lrdata.mkdir()
        result = find_sidecars(media)
        assert result == [lrdata]

    def test_lrdata_file_not_directory(self, tmp_path: Path):
        """stem.lrdata as a regular file is NOT a sidecar."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        lrdata = tmp_path / "IMG_1234.lrdata"
        lrdata.touch()  # file, not directory
        result = find_sidecars(media)
        assert result == []

    def test_custom_extensions(self, tmp_path: Path):
        """Custom extensions override defaults."""
        media = tmp_path / "video.mp4"
        media.touch()
        srt = tmp_path / "video.srt"
        srt.touch()
        xmp = tmp_path / "video.xmp"
        xmp.touch()
        result = find_sidecars(media, extensions=frozenset({".srt"}))
        assert result == [srt]
        assert xmp not in result

    def test_sorted_output(self, tmp_path: Path):
        """Results are sorted by path."""
        media = tmp_path / "IMG_1234.jpg"
        media.touch()
        thm = tmp_path / "IMG_1234.thm"
        thm.touch()
        aae = tmp_path / "IMG_1234.aae"
        aae.touch()
        xmp = tmp_path / "IMG_1234.xmp"
        xmp.touch()
        result = find_sidecars(media)
        assert result == sorted(result)

    def test_nonexistent_media_no_crash(self, tmp_path: Path):
        """Media file doesn't need to exist; sidecars are checked independently."""
        media = tmp_path / "ghost.jpg"
        # media does not exist, but a sidecar does
        xmp = tmp_path / "ghost.xmp"
        xmp.touch()
        result = find_sidecars(media)
        assert result == [xmp]

    def test_media_with_same_extension_as_sidecar(self, tmp_path: Path):
        """Media file with .json extension should not list itself as sidecar."""
        media = tmp_path / "data.json"
        media.touch()
        # stem + .json == data.json == media itself  -> excluded
        result = find_sidecars(media)
        assert media not in result

    def test_default_extensions_constant(self):
        """Verify default extensions are the documented set."""
        assert frozenset({".xmp", ".aae", ".thm", ".json"}) == _DEFAULT_SIDECAR_EXTENSIONS

    def test_lrdata_suffix_constant(self):
        assert _LRDATA_SUFFIX == ".lrdata"


# ---------------------------------------------------------------------------
# End-to-end: auto_delete with sidecars
# ---------------------------------------------------------------------------


class TestSidecarIntegration:
    """Integration test: auto_delete with sidecars verifies both media and
    sidecar files are deleted.
    """

    def test_auto_delete_deletes_media_and_sidecars(self, tmp_path: Path):
        """auto_delete with a pair where file_a has sidecars:
        media + sidecars all deleted, kept file remains.
        """
        from io import StringIO

        from rich.console import Console

        from duplicates_detector.advisor import auto_delete
        from duplicates_detector.deleter import PermanentDeleter
        from duplicates_detector.metadata import VideoMetadata
        from duplicates_detector.scorer import ScoredPair

        # Create media files
        media_a = tmp_path / "photo_a.jpg"
        media_a.write_bytes(b"A" * 500)
        media_b = tmp_path / "photo_b.jpg"
        media_b.write_bytes(b"B" * 2000)

        # Create sidecars for file_a
        xmp = tmp_path / "photo_a.xmp"
        xmp.write_bytes(b"<xmp>metadata</xmp>")
        aae = tmp_path / "photo_a.aae"
        aae.write_bytes(b"aae-data")

        # Discover sidecars (using the function under test)
        sidecars = find_sidecars(media_a)
        assert len(sidecars) == 2

        meta_a = VideoMetadata(
            path=media_a,
            filename="photo_a",
            duration=None,
            width=1920,
            height=1080,
            file_size=500,
            sidecars=tuple(sidecars),
        )
        meta_b = VideoMetadata(
            path=media_b,
            filename="photo_b",
            duration=None,
            width=1920,
            height=1080,
            file_size=2000,
        )
        pair = ScoredPair(
            file_a=meta_a,
            file_b=meta_b,
            total_score=85.0,
            breakdown={"filename": 40.0},
            detail={},
        )

        buf = StringIO()
        con = Console(file=buf, highlight=False, width=200)
        result = auto_delete(
            [pair],
            strategy="biggest",
            console=con,
            deleter=PermanentDeleter(),
        )

        # Verify media_a (smaller) was deleted
        assert not media_a.exists()
        # Verify sidecars were also deleted
        assert not xmp.exists()
        assert not aae.exists()
        # Verify kept file remains
        assert media_b.exists()

        # Verify summary counts
        assert len(result.deleted) == 1
        assert result.sidecars_deleted == 2
        assert result.sidecar_bytes_freed > 0

    def test_auto_delete_no_sidecars_still_works(self, tmp_path: Path):
        """auto_delete works normally when files have no sidecars."""
        from io import StringIO

        from rich.console import Console

        from duplicates_detector.advisor import auto_delete
        from duplicates_detector.deleter import PermanentDeleter
        from duplicates_detector.metadata import VideoMetadata
        from duplicates_detector.scorer import ScoredPair

        media_a = tmp_path / "a.mp4"
        media_a.write_bytes(b"A" * 500)
        media_b = tmp_path / "b.mp4"
        media_b.write_bytes(b"B" * 2000)

        meta_a = VideoMetadata(
            path=media_a,
            filename="a",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=500,
        )
        meta_b = VideoMetadata(
            path=media_b,
            filename="b",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=2000,
        )
        pair = ScoredPair(
            file_a=meta_a,
            file_b=meta_b,
            total_score=85.0,
            breakdown={"filename": 40.0},
            detail={},
        )

        buf = StringIO()
        con = Console(file=buf, highlight=False, width=200)
        result = auto_delete(
            [pair],
            strategy="biggest",
            console=con,
            deleter=PermanentDeleter(),
        )

        assert not media_a.exists()
        assert media_b.exists()
        assert result.sidecars_deleted == 0
        assert result.sidecar_bytes_freed == 0
