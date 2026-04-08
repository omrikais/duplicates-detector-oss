from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from duplicates_detector.scanner import find_video_files, find_media_files, MediaFile, DEFAULT_VIDEO_EXTENSIONS


class TestFindVideoFiles:
    def test_finds_video_files_recursively(self, video_dir):
        result = find_video_files(video_dir)
        names = [p.name for p in result]
        assert "movie_a.mp4" in names
        assert "movie_b.mkv" in names
        assert "clip.avi" in names
        assert "movie_c.mp4" in names

    def test_flat_scan_skips_subdirectories(self, video_dir):
        result = find_video_files(video_dir, recursive=False)
        names = [p.name for p in result]
        assert "movie_c.mp4" not in names
        assert "movie_a.mp4" in names

    def test_default_extensions_filter(self, video_dir):
        result = find_video_files(video_dir)
        names = [p.name for p in result]
        assert "not_video.txt" not in names
        assert "other.jpg" not in names

    def test_custom_extensions(self, tmp_path):
        (tmp_path / "video.mp4").touch()
        (tmp_path / "video.mkv").touch()
        (tmp_path / "video.xyz").touch()
        result = find_video_files(tmp_path, extensions=frozenset({".xyz"}))
        assert len(result) == 1
        assert result[0].name == "video.xyz"

    def test_case_insensitive_extensions(self, tmp_path):
        (tmp_path / "upper.MP4").touch()
        (tmp_path / "lower.mp4").touch()
        result = find_video_files(tmp_path)
        assert len(result) == 2

    def test_empty_directory_returns_empty(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert find_video_files(empty) == []

    def test_nonexistent_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_video_files(tmp_path / "nope")

    def test_path_is_file_raises(self, tmp_path):
        f = tmp_path / "file.mp4"
        f.touch()
        with pytest.raises(NotADirectoryError):
            find_video_files(f)

    def test_results_sorted_by_name(self, tmp_path):
        (tmp_path / "zebra.mp4").touch()
        (tmp_path / "alpha.mp4").touch()
        (tmp_path / "middle.mp4").touch()
        result = find_video_files(tmp_path)
        names = [p.name for p in result]
        assert names == ["alpha.mp4", "middle.mp4", "zebra.mp4"]

    def test_symlink_deduplication(self, tmp_path):
        original = tmp_path / "original.mp4"
        original.touch()
        link = tmp_path / "link.mp4"
        try:
            link.symlink_to(original)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")
        result = find_video_files(tmp_path)
        assert len(result) == 1

    def test_no_video_files_returns_empty(self, tmp_path):
        (tmp_path / "readme.txt").touch()
        (tmp_path / "image.png").touch()
        assert find_video_files(tmp_path) == []

    def test_multiple_directories(self, tmp_path):
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "movie_a.mp4").touch()
        (dir_b / "movie_b.mkv").touch()
        result = find_video_files([dir_a, dir_b])
        names = [p.name for p in result]
        assert "movie_a.mp4" in names
        assert "movie_b.mkv" in names
        assert len(result) == 2

    def test_multiple_directories_deduplicates(self, tmp_path):
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "movie.mp4").touch()
        try:
            (dir_b / "movie.mp4").symlink_to(dir_a / "movie.mp4")
        except OSError:
            pytest.skip("Symlinks not supported on this platform")
        result = find_video_files([dir_a, dir_b])
        assert len(result) == 1

    def test_multiple_directories_one_missing_raises(self, tmp_path):
        dir_a = tmp_path / "exists"
        dir_a.mkdir()
        with pytest.raises(FileNotFoundError):
            find_video_files([dir_a, tmp_path / "nope"])

    def test_single_path_string_still_works(self, tmp_path):
        (tmp_path / "video.mp4").touch()
        result = find_video_files(str(tmp_path))
        assert len(result) == 1

    def test_pause_waiter_called_during_scan(self, tmp_path):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        calls = 0

        def _pause_waiter() -> None:
            nonlocal calls
            calls += 1

        result = find_video_files(tmp_path, pause_waiter=_pause_waiter)

        assert len(result) == 2
        assert calls >= 2


class TestExclude:
    def test_single_pattern_excludes_matching_files(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        (thumbs / "thumb.mp4").touch()

        result = find_video_files(tmp_path, exclude=["thumbnails/*"])
        names = [p.name for p in result]
        assert "movie.mp4" in names
        assert "thumb.mp4" not in names

    def test_double_star_matches_nested_dirs(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        deep = tmp_path / "a" / "b" / "deep"
        deep.mkdir(parents=True)
        (deep / "nested.mp4").touch()

        result = find_video_files(tmp_path, exclude=["**/deep/**"])
        names = [p.name for p in result]
        assert "movie.mp4" in names
        assert "nested.mp4" not in names

    def test_double_star_matches_top_level_dir(self, tmp_path):
        """**/thumbnails/** must also match thumbnails/ directly under root."""
        (tmp_path / "movie.mp4").touch()
        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        (thumbs / "thumb.mp4").touch()

        result = find_video_files(tmp_path, exclude=["**/thumbnails/**"])
        names = [p.name for p in result]
        assert "movie.mp4" in names
        assert "thumb.mp4" not in names

    def test_multiple_patterns_or_logic(self, tmp_path):
        (tmp_path / "keep.mp4").touch()
        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        (thumbs / "thumb.mp4").touch()
        samples = tmp_path / "samples"
        samples.mkdir()
        (samples / "sample.mp4").touch()

        result = find_video_files(
            tmp_path,
            exclude=["thumbnails/*", "samples/*"],
        )
        names = [p.name for p in result]
        assert "keep.mp4" in names
        assert "thumb.mp4" not in names
        assert "sample.mp4" not in names

    def test_no_match_pattern_changes_nothing(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        (tmp_path / "clip.avi").touch()

        result = find_video_files(tmp_path, exclude=["nonexistent/*"])
        assert len(result) == 2

    def test_none_exclude_returns_all(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "clip.avi").touch()

        result_none = find_video_files(tmp_path, exclude=None)
        result_default = find_video_files(tmp_path)
        assert len(result_none) == len(result_default) == 2

    def test_exclude_directory_name(self, tmp_path):
        (tmp_path / "good.mp4").touch()
        samples = tmp_path / "samples"
        samples.mkdir()
        (samples / "demo.mp4").touch()

        result = find_video_files(tmp_path, exclude=["samples/*"])
        names = [p.name for p in result]
        assert "good.mp4" in names
        assert "demo.mp4" not in names

    def test_exclude_combined_with_extensions(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        (tmp_path / "movie.xyz").touch()
        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        (thumbs / "thumb.mp4").touch()

        result = find_video_files(
            tmp_path,
            extensions=frozenset({".mp4"}),
            exclude=["thumbnails/*"],
        )
        names = [p.name for p in result]
        assert names == ["movie.mp4"]

    def test_exclude_combined_with_non_recursive(self, tmp_path):
        (tmp_path / "keep.mp4").touch()
        (tmp_path / "skip.mp4").touch()

        # With recursive=False, exclude on a file pattern
        result = find_video_files(
            tmp_path,
            recursive=False,
            exclude=["skip.mp4"],
        )
        names = [p.name for p in result]
        assert "keep.mp4" in names
        assert "skip.mp4" not in names


# ---------------------------------------------------------------------------
# PermissionError handling
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
class TestPermissionHandling:
    def test_unreadable_subdirectory_skipped(self, tmp_path):
        """Files in readable dirs are returned; unreadable subdirs are skipped."""
        (tmp_path / "good.mp4").touch()
        bad = tmp_path / "noperm"
        bad.mkdir()
        (bad / "hidden.mp4").touch()
        bad.chmod(0o000)
        try:
            result = find_video_files(tmp_path)
            names = [p.name for p in result]
            assert "good.mp4" in names
            assert "hidden.mp4" not in names
        finally:
            bad.chmod(0o755)

    def test_permission_error_in_loop_body_skipped(self, tmp_path):
        """PermissionError from entry.is_file() is caught and skipped."""
        (tmp_path / "good.mp4").touch()
        (tmp_path / "bad.mp4").touch()

        original_is_file = Path.is_file

        def patched_is_file(self):
            if self.name == "bad.mp4":
                raise PermissionError(f"Permission denied: {self}")
            return original_is_file(self)

        with patch.object(Path, "is_file", patched_is_file):
            result = find_video_files(tmp_path)

        names = [p.name for p in result]
        assert "good.mp4" in names
        assert "bad.mp4" not in names

    def test_permission_warning_emitted(self, tmp_path):
        """A warning is emitted when a PermissionError occurs."""
        (tmp_path / "good.mp4").touch()
        (tmp_path / "bad.mp4").touch()

        original_is_file = Path.is_file

        def patched_is_file(self):
            if self.name == "bad.mp4":
                raise PermissionError(f"Permission denied: {self}")
            return original_is_file(self)

        with patch.object(Path, "is_file", patched_is_file):
            with pytest.warns(UserWarning, match="Permission denied"):
                find_video_files(tmp_path)

    def test_all_inaccessible_returns_empty(self, tmp_path):
        """When all content is in inaccessible subdirs, return empty list."""
        sub = tmp_path / "only_dir"
        sub.mkdir()
        (sub / "video.mp4").touch()
        sub.chmod(0o000)
        try:
            result = find_video_files(tmp_path)
            assert result == []
        finally:
            sub.chmod(0o755)

    def test_root_validation_errors_still_raised(self, tmp_path):
        """PermissionError handling doesn't affect root-level validation."""
        with pytest.raises(FileNotFoundError):
            find_video_files(tmp_path / "nonexistent")
        f = tmp_path / "afile"
        f.touch()
        with pytest.raises(NotADirectoryError):
            find_video_files(f)


# ---------------------------------------------------------------------------
# DEFAULT_IMAGE_EXTENSIONS
# ---------------------------------------------------------------------------


class TestDefaultImageExtensions:
    def test_exists(self):
        from duplicates_detector.scanner import DEFAULT_IMAGE_EXTENSIONS

        assert isinstance(DEFAULT_IMAGE_EXTENSIONS, frozenset)
        assert len(DEFAULT_IMAGE_EXTENSIONS) > 0

    def test_lowercase_with_dots(self):
        from duplicates_detector.scanner import DEFAULT_IMAGE_EXTENSIONS

        for ext in DEFAULT_IMAGE_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ext.lower()

    def test_common_formats_included(self):
        from duplicates_detector.scanner import DEFAULT_IMAGE_EXTENSIONS

        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".avif"):
            assert ext in DEFAULT_IMAGE_EXTENSIONS

    def test_find_with_image_extensions(self, tmp_path):
        from duplicates_detector.scanner import DEFAULT_IMAGE_EXTENSIONS

        (tmp_path / "photo.jpg").touch()
        (tmp_path / "pic.png").touch()
        (tmp_path / "video.mp4").touch()
        result = find_video_files(tmp_path, extensions=DEFAULT_IMAGE_EXTENSIONS, quiet=True)
        names = {f.name for f in result}
        assert "photo.jpg" in names
        assert "pic.png" in names
        assert "video.mp4" not in names


# ---------------------------------------------------------------------------
# find_media_files (auto mode)
# ---------------------------------------------------------------------------


class TestFindMediaFiles:
    def test_finds_video_and_image_files(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        (tmp_path / "photo.jpg").touch()
        (tmp_path / "readme.txt").touch()
        result = find_media_files(tmp_path, quiet=True)
        assert len(result) == 2
        types = {mf.media_type for mf in result}
        assert types == {"video", "image"}

    def test_classification_correct(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        (tmp_path / "photo.jpg").touch()
        result = find_media_files(tmp_path, quiet=True)
        by_name = {mf.path.name: mf.media_type for mf in result}
        assert by_name["movie.mp4"] == "video"
        assert by_name["photo.jpg"] == "image"

    def test_classification_case_insensitive(self, tmp_path):
        (tmp_path / "MOVIE.MP4").touch()
        (tmp_path / "PHOTO.JPG").touch()
        result = find_media_files(tmp_path, quiet=True)
        assert len(result) == 2
        types = {mf.media_type for mf in result}
        assert types == {"video", "image"}

    def test_excludes_unknown_extensions(self, tmp_path):
        (tmp_path / "readme.txt").touch()
        (tmp_path / "data.pdf").touch()
        (tmp_path / "movie.mp4").touch()
        result = find_media_files(tmp_path, quiet=True)
        assert len(result) == 1
        assert result[0].path.name == "movie.mp4"

    def test_dedup_by_resolved_path(self, tmp_path):
        original = tmp_path / "original.mp4"
        original.touch()
        link = tmp_path / "link.mp4"
        try:
            link.symlink_to(original)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")
        result = find_media_files(tmp_path, quiet=True)
        assert len(result) == 1

    def test_exclude_patterns(self, tmp_path):
        (tmp_path / "keep.mp4").touch()
        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        (thumbs / "thumb.jpg").touch()
        result = find_media_files(tmp_path, exclude=["thumbnails/*"], quiet=True)
        names = [mf.path.name for mf in result]
        assert "keep.mp4" in names
        assert "thumb.jpg" not in names

    def test_sorted_by_name(self, tmp_path):
        (tmp_path / "zebra.mp4").touch()
        (tmp_path / "alpha.jpg").touch()
        (tmp_path / "middle.png").touch()
        result = find_media_files(tmp_path, quiet=True)
        names = [mf.path.name for mf in result]
        assert names == ["alpha.jpg", "middle.png", "zebra.mp4"]

    def test_empty_directory(self, tmp_path):
        result = find_media_files(tmp_path, quiet=True)
        assert result == []

    def test_nonexistent_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_media_files(tmp_path / "nope", quiet=True)

    def test_returns_media_file_namedtuples(self, tmp_path):
        (tmp_path / "movie.mp4").touch()
        result = find_media_files(tmp_path, quiet=True)
        assert isinstance(result[0], MediaFile)
        assert hasattr(result[0], "path")
        assert hasattr(result[0], "media_type")


# ---------------------------------------------------------------------------
# DEFAULT_DOCUMENT_EXTENSIONS
# ---------------------------------------------------------------------------


class TestDefaultDocumentExtensions:
    def test_exists(self):
        from duplicates_detector.scanner import DEFAULT_DOCUMENT_EXTENSIONS

        assert isinstance(DEFAULT_DOCUMENT_EXTENSIONS, frozenset)
        assert len(DEFAULT_DOCUMENT_EXTENSIONS) == 4

    def test_expected_formats(self):
        from duplicates_detector.scanner import DEFAULT_DOCUMENT_EXTENSIONS

        for ext in (".pdf", ".docx", ".txt", ".md"):
            assert ext in DEFAULT_DOCUMENT_EXTENSIONS

    def test_lowercase_with_dots(self):
        from duplicates_detector.scanner import DEFAULT_DOCUMENT_EXTENSIONS

        for ext in DEFAULT_DOCUMENT_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ext.lower()
