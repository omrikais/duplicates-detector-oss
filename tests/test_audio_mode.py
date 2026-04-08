from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.pipeline import PipelineResult


# ---------------------------------------------------------------------------
# 1. Scanner — DEFAULT_AUDIO_EXTENSIONS
# ---------------------------------------------------------------------------


class TestDefaultAudioExtensions:
    def test_extensions_exist(self):
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS

        assert isinstance(DEFAULT_AUDIO_EXTENSIONS, frozenset)
        assert len(DEFAULT_AUDIO_EXTENSIONS) > 0

    def test_all_start_with_dot(self):
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS

        for ext in DEFAULT_AUDIO_EXTENSIONS:
            assert ext.startswith("."), f"Extension {ext!r} does not start with '.'"

    def test_all_lowercase(self):
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS

        for ext in DEFAULT_AUDIO_EXTENSIONS:
            assert ext == ext.lower(), f"Extension {ext!r} is not lowercase"

    @pytest.mark.parametrize(
        "ext",
        [
            ".mp3",
            ".flac",
            ".aac",
            ".m4a",
            ".wav",
            ".ogg",
            ".opus",
            ".wma",
            ".ape",
            ".alac",
            ".aiff",
            ".aif",
            ".wv",
            ".dsf",
            ".dff",
        ],
    )
    def test_expected_extensions_present(self, ext):
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS

        assert ext in DEFAULT_AUDIO_EXTENSIONS

    def test_no_overlap_with_video_extensions(self):
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS, DEFAULT_VIDEO_EXTENSIONS

        overlap = DEFAULT_AUDIO_EXTENSIONS & DEFAULT_VIDEO_EXTENSIONS
        assert overlap == frozenset(), f"Audio and video extensions overlap: {overlap}"

    def test_no_overlap_with_image_extensions(self):
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS, DEFAULT_IMAGE_EXTENSIONS

        overlap = DEFAULT_AUDIO_EXTENSIONS & DEFAULT_IMAGE_EXTENSIONS
        assert overlap == frozenset(), f"Audio and image extensions overlap: {overlap}"


# ---------------------------------------------------------------------------
# 2. Metadata — _extract_tags
# ---------------------------------------------------------------------------


class TestExtractTags:
    def test_all_tags_present(self, tmp_path):
        """All tags (title, artist, album) and info (duration, bitrate, channels) are extracted."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = MagicMock()
        mock_audio.info.length = 240.5
        mock_audio.info.bitrate = 320_000
        mock_audio.info.channels = 2
        mock_audio.tags = MagicMock()
        mock_audio.get.side_effect = lambda key: {
            "title": ["  Bohemian Rhapsody  "],
            "artist": ["Queen"],
            "album": ["A Night at the Opera"],
        }.get(key)
        type(mock_audio).__name__ = "MP3"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "song.mp3")

        assert result["tag_title"] == "bohemian rhapsody"
        assert result["tag_artist"] == "queen"
        assert result["tag_album"] == "a night at the opera"
        assert result["duration"] == 240.5
        assert result["bitrate"] == 320_000
        assert result["audio_channels"] == 2
        assert result["codec"] == "mp3"

    def test_partial_tags(self, tmp_path):
        """Only title and artist present, album missing."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = MagicMock()
        mock_audio.info.length = 180.0
        mock_audio.info.bitrate = None
        mock_audio.info.channels = None
        mock_audio.tags = MagicMock()
        mock_audio.get.side_effect = lambda key: {
            "title": ["Song Title"],
            "artist": ["Artist Name"],
        }.get(key)
        type(mock_audio).__name__ = "FLAC"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "song.flac")

        assert result["tag_title"] == "song title"
        assert result["tag_artist"] == "artist name"
        assert result["tag_album"] is None
        assert result["codec"] == "flac"

    def test_no_tags(self, tmp_path):
        """File recognized by mutagen but with no tags returns all None tag values."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = MagicMock()
        mock_audio.info.length = 60.0
        mock_audio.info.bitrate = 128_000
        mock_audio.info.channels = 1
        mock_audio.tags = None
        type(mock_audio).__name__ = "OggVorbis"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "audio.ogg")

        assert result["tag_title"] is None
        assert result["tag_artist"] is None
        assert result["tag_album"] is None
        assert result["duration"] == 60.0
        assert result["codec"] == "vorbis"

    def test_mutagen_returns_none(self, tmp_path):
        """mutagen.File returns None (unrecognized format) — all values None."""
        from duplicates_detector.metadata import _extract_tags

        with patch("mutagen.File", return_value=None):
            result = _extract_tags(tmp_path / "mystery.xyz")

        assert result["tag_title"] is None
        assert result["tag_artist"] is None
        assert result["tag_album"] is None
        assert result["duration"] is None
        assert result["codec"] is None

    def test_mutagen_exception(self, tmp_path):
        """mutagen.File raises exception — all values None, no crash."""
        from duplicates_detector.metadata import _extract_tags

        with patch("mutagen.File", side_effect=Exception("corrupt file")):
            result = _extract_tags(tmp_path / "corrupt.mp3")

        assert all(v is None for v in result.values())

    def test_empty_string_tags_ignored(self, tmp_path):
        """Tags that are empty strings after strip+lower are treated as None."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = MagicMock()
        mock_audio.info.length = 10.0
        mock_audio.info.bitrate = None
        mock_audio.info.channels = None
        mock_audio.tags = MagicMock()
        mock_audio.get.side_effect = lambda key: {
            "title": ["   "],  # whitespace only
            "artist": [""],  # empty
            "album": ["Real Album"],
        }.get(key)
        type(mock_audio).__name__ = "MP3"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "song.mp3")

        assert result["tag_title"] is None
        assert result["tag_artist"] is None
        assert result["tag_album"] == "real album"

    def test_codec_map_mp4(self, tmp_path):
        """MP4/AAC type name maps to 'aac'."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = MagicMock()
        mock_audio.info.length = 200.0
        mock_audio.info.bitrate = 256_000
        mock_audio.info.channels = 2
        mock_audio.tags = MagicMock()
        mock_audio.get.return_value = None
        type(mock_audio).__name__ = "MP4"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "song.m4a")

        assert result["codec"] == "aac"

    def test_codec_map_wavpack(self, tmp_path):
        """WavPack type name maps to 'wavpack'."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = MagicMock()
        mock_audio.info.length = 100.0
        mock_audio.info.bitrate = None
        mock_audio.info.channels = 2
        mock_audio.tags = MagicMock()
        mock_audio.get.return_value = None
        type(mock_audio).__name__ = "WavPack"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "song.wv")

        assert result["codec"] == "wavpack"

    def test_no_info_attribute(self, tmp_path):
        """mutagen file object with no .info attribute — duration/bitrate/channels None."""
        from duplicates_detector.metadata import _extract_tags

        mock_audio = MagicMock()
        mock_audio.info = None
        mock_audio.tags = MagicMock()
        mock_audio.get.side_effect = lambda key: {"title": ["Test"]}.get(key)
        type(mock_audio).__name__ = "Unknown"

        with patch("mutagen.File", return_value=mock_audio):
            result = _extract_tags(tmp_path / "unknown.dat")

        assert result["duration"] is None
        assert result["bitrate"] is None
        assert result["audio_channels"] is None
        assert result["tag_title"] == "test"


# ---------------------------------------------------------------------------
# 2b. Metadata — extract_one_audio
# ---------------------------------------------------------------------------


class TestExtractOneAudio:
    def test_basic_extraction(self, tmp_path):
        """Successful extraction returns VideoMetadata with tag fields populated."""
        from duplicates_detector.metadata import extract_one_audio

        audio_file = tmp_path / "song.mp3"
        audio_file.write_bytes(b"\x00" * 500)

        tags = {
            "tag_title": "my song",
            "tag_artist": "my artist",
            "tag_album": "my album",
            "duration": 200.0,
            "codec": "mp3",
            "bitrate": 320_000,
            "audio_channels": 2,
        }

        with patch("duplicates_detector.metadata._extract_tags", return_value=tags):
            result = extract_one_audio(audio_file)

        assert result is not None
        assert result.tag_title == "my song"
        assert result.tag_artist == "my artist"
        assert result.tag_album == "my album"
        assert result.duration == 200.0
        assert result.codec == "mp3"
        assert result.bitrate == 320_000
        assert result.audio_channels == 2
        assert result.width is None
        assert result.height is None
        assert result.framerate is None
        assert result.file_size == 500
        assert result.filename == "song"
        assert result.path == audio_file
        assert isinstance(result.mtime, float)

    def test_stat_failure_returns_none(self):
        """File not found returns None."""
        from duplicates_detector.metadata import extract_one_audio

        result = extract_one_audio(Path("/nonexistent/song.mp3"))
        assert result is None

    def test_permission_error_returns_none(self, tmp_path):
        """Permission error on stat returns None."""
        from duplicates_detector.metadata import extract_one_audio

        f = tmp_path / "noperm.mp3"
        f.write_bytes(b"\x00" * 100)

        with patch.object(Path, "stat", side_effect=PermissionError("denied")):
            result = extract_one_audio(f)

        assert result is None

    def test_tags_with_no_data(self, tmp_path):
        """When _extract_tags returns all None, metadata still has file_size and mtime."""
        from duplicates_detector.metadata import extract_one_audio

        audio_file = tmp_path / "empty.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        tags = {
            "tag_title": None,
            "tag_artist": None,
            "tag_album": None,
            "duration": None,
            "codec": None,
            "bitrate": None,
            "audio_channels": None,
        }

        with patch("duplicates_detector.metadata._extract_tags", return_value=tags):
            result = extract_one_audio(audio_file)

        assert result is not None
        assert result.file_size == 100
        assert result.tag_title is None
        assert result.duration is None


# ---------------------------------------------------------------------------
# 2c. Metadata — extract_all_audio
# ---------------------------------------------------------------------------


class TestExtractAllAudio:
    def _make_files(self, tmp_path, names=("a.mp3", "b.flac")):
        files = []
        for name in names:
            f = tmp_path / name
            f.write_bytes(b"\x00" * 100)
            files.append(f)
        return files

    def test_parallel_extraction(self, tmp_path):
        """extract_all_audio runs extraction in parallel and returns results."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path)

        with patch("duplicates_detector.metadata.extract_one_audio") as mock_extract:
            mock_extract.return_value = VideoMetadata(
                path=files[0],
                filename="a",
                duration=180.0,
                width=None,
                height=None,
                file_size=100,
                mtime=0.0,
                tag_title="test song",
                tag_artist="test artist",
            )
            result = extract_all_audio(files, workers=1, quiet=True)

        assert len(result) == 2

    def test_no_ffprobe_required(self, tmp_path):
        """extract_all_audio should NOT call check_ffprobe."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path, ["a.mp3"])
        with (
            patch("duplicates_detector.metadata.extract_one_audio") as mock_extract,
            patch("duplicates_detector.metadata.check_ffprobe") as mock_check,
        ):
            mock_extract.return_value = VideoMetadata(
                path=files[0],
                filename="a",
                duration=180.0,
                width=None,
                height=None,
                file_size=100,
                mtime=0.0,
            )
            extract_all_audio(files, workers=1, quiet=True)
        mock_check.assert_not_called()

    def test_cache_hit_skips_extraction(self, tmp_path):
        """Files with cache hits do not trigger mutagen extraction."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path, ["a.mp3"])

        cache = MagicMock()
        cache.get.return_value = {
            "duration": 180.0,
            "width": None,
            "height": None,
            "codec": "mp3",
            "bitrate": 320_000,
            "framerate": None,
            "audio_channels": 2,
            "tag_title": "cached song",
            "tag_artist": "cached artist",
            "tag_album": "cached album",
        }
        cache.hits = 1
        cache.misses = 0

        with patch("duplicates_detector.metadata.extract_one_audio") as mock_extract:
            result = extract_all_audio(files, workers=1, cache=cache, quiet=True)

        mock_extract.assert_not_called()
        assert len(result) == 1
        assert result[0].tag_title == "cached song"
        assert result[0].tag_artist == "cached artist"
        assert result[0].tag_album == "cached album"

    def test_cache_miss_extracts_and_stores(self, tmp_path):
        """Files with cache misses go through extraction and are stored in cache."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path, ["a.mp3"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=180.0,
            width=None,
            height=None,
            file_size=100,
            mtime=1.0,
            tag_title="new song",
            tag_artist="new artist",
            tag_album=None,
        )

        with patch("duplicates_detector.metadata.extract_one_audio", return_value=extracted):
            extract_all_audio(files, workers=1, cache=cache, quiet=True)

        cache.put.assert_called_once()
        call_kwargs = cache.put.call_args[1]
        assert call_kwargs["tag_title"] == "new song"
        assert call_kwargs["tag_artist"] == "new artist"
        assert call_kwargs["tag_album"] is None
        cache.save.assert_called_once()

    def test_skip_condition_no_duration_no_tags(self, tmp_path):
        """Entries with no duration AND no title AND no artist are not cached (transient failure)."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path, ["a.mp3"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=None,
            width=None,
            height=None,
            file_size=100,
            mtime=1.0,
            tag_title=None,
            tag_artist=None,
            tag_album=None,
        )

        with patch("duplicates_detector.metadata.extract_one_audio", return_value=extracted):
            extract_all_audio(files, workers=1, cache=cache, quiet=True)

        cache.put.assert_not_called()
        cache.save.assert_called_once()

    def test_skip_condition_has_title_still_cached(self, tmp_path):
        """Entries with title (even without duration) are still cached."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path, ["a.mp3"])

        cache = MagicMock()
        cache.get.return_value = None
        cache.hits = 0
        cache.misses = 1

        extracted = VideoMetadata(
            path=files[0],
            filename="a",
            duration=None,
            width=None,
            height=None,
            file_size=100,
            mtime=1.0,
            tag_title="some title",
            tag_artist=None,
        )

        with patch("duplicates_detector.metadata.extract_one_audio", return_value=extracted):
            extract_all_audio(files, workers=1, cache=cache, quiet=True)

        cache.put.assert_called_once()

    def test_filters_none_results(self, tmp_path):
        """None results from extract_one_audio are filtered out."""
        from duplicates_detector.metadata import extract_all_audio

        files = self._make_files(tmp_path, ["a.mp3", "b.mp3"])

        call_count = 0

        def mock_extract(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            return VideoMetadata(
                path=path,
                filename="b",
                duration=100.0,
                width=None,
                height=None,
                file_size=100,
                mtime=0.0,
            )

        with patch("duplicates_detector.metadata.extract_one_audio", side_effect=mock_extract):
            result = extract_all_audio(files, workers=1, quiet=True)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# 3. Comparators — TagComparator
# ---------------------------------------------------------------------------


class TestTagComparator:
    def setup_method(self):
        from duplicates_detector.comparators import TagComparator

        self.comp = TagComparator()

    def test_name_and_weight(self):
        assert self.comp.name == "tags"
        assert self.comp.weight == 40.0

    def test_identical_tags_perfect_score(self, make_metadata):
        """Identical title, artist, album produce score 1.0."""
        a = make_metadata(
            path="a.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="bohemian rhapsody",
            tag_artist="queen",
            tag_album="a night at the opera",
        )
        b = make_metadata(
            path="b.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="bohemian rhapsody",
            tag_artist="queen",
            tag_album="a night at the opera",
        )
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_completely_different_tags(self, make_metadata):
        """Completely different tags produce low score."""
        a = make_metadata(
            path="a.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="bohemian rhapsody",
            tag_artist="queen",
            tag_album="a night at the opera",
        )
        b = make_metadata(
            path="b.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="stairway to heaven",
            tag_artist="led zeppelin",
            tag_album="led zeppelin iv",
        )
        score = self.comp.score(a, b)
        assert score is not None
        assert score < 0.3

    def test_no_common_fields_returns_none(self, make_metadata):
        """When no tag sub-fields have data on both sides, returns None."""
        a = make_metadata(
            path="a.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="some title",
            tag_artist=None,
            tag_album=None,
        )
        b = make_metadata(
            path="b.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title=None,
            tag_artist="some artist",
            tag_album=None,
        )
        assert self.comp.score(a, b) is None

    def test_both_none_returns_none(self, make_metadata):
        """Both files with no tags returns None."""
        a = make_metadata(path="a.mp3", duration=None, width=None, height=None)
        b = make_metadata(path="b.mp3", duration=None, width=None, height=None)
        assert self.comp.score(a, b) is None

    def test_partial_data_redistribution(self, make_metadata):
        """Only title and artist available — weights redistributed to sum 1.0."""
        a = make_metadata(
            path="a.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="same title",
            tag_artist="same artist",
            tag_album=None,
        )
        b = make_metadata(
            path="b.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="same title",
            tag_artist="same artist",
            tag_album=None,
        )
        score = self.comp.score(a, b)
        assert score is not None
        # Both available sub-fields are perfect matches, so redistribution yields 1.0
        assert score == pytest.approx(1.0)

    def test_only_album_available(self, make_metadata):
        """Only album available on both sides — still returns a score."""
        a = make_metadata(
            path="a.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title=None,
            tag_artist=None,
            tag_album="same album",
        )
        b = make_metadata(
            path="b.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title=None,
            tag_artist=None,
            tag_album="same album",
        )
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_fuzzy_matching_similar_titles(self, make_metadata):
        """Similar but not identical titles produce a moderate-to-high score."""
        a = make_metadata(
            path="a.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="bohemian rhapsody",
            tag_artist=None,
            tag_album=None,
        )
        b = make_metadata(
            path="b.mp3",
            duration=None,
            width=None,
            height=None,
            tag_title="bohemian rhapsody (remastered)",
            tag_artist=None,
            tag_album=None,
        )
        score = self.comp.score(a, b)
        assert score is not None
        assert score > 0.5

    def test_sub_weights_sum_to_one(self):
        """Sub-weights must sum to 1.0."""
        from duplicates_detector.comparators import TagComparator

        total = sum(TagComparator._SUB_WEIGHTS.values())
        assert total == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3b. Comparators — Audio mode factory functions
# ---------------------------------------------------------------------------


class TestAudioModeComparatorFactories:
    def test_get_audio_mode_comparators(self):
        from duplicates_detector.comparators import get_audio_mode_comparators

        comps = get_audio_mode_comparators()
        names = {c.name for c in comps}
        assert names == {"filename", "duration", "tags", "directory"}
        assert sum(c.weight for c in comps) == pytest.approx(100.0)

    def test_get_audio_mode_fingerprint_comparators(self):
        from duplicates_detector.comparators import get_audio_mode_fingerprint_comparators

        comps = get_audio_mode_fingerprint_comparators()
        names = {c.name for c in comps}
        assert names == {"filename", "duration", "tags", "audio", "directory"}
        assert sum(c.weight for c in comps) == pytest.approx(100.0)

    def test_fingerprint_specific_weights(self):
        """Verify specific weight values for fingerprint mode."""
        from duplicates_detector.comparators import get_audio_mode_fingerprint_comparators

        comps = get_audio_mode_fingerprint_comparators()
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 15.0
        assert by_name["duration"] == 15.0
        assert by_name["tags"] == 20.0
        assert by_name["audio"] == 50.0

    def test_get_weighted_audio_mode_comparators(self):
        from duplicates_detector.comparators import get_weighted_audio_mode_comparators

        weights = {"filename": 40.0, "duration": 20.0, "tags": 40.0}
        comps = get_weighted_audio_mode_comparators(weights)
        for c in comps:
            if c.name == "directory":
                assert c.weight == 0.0
            else:
                assert c.weight == weights[c.name]

    def test_get_weighted_audio_mode_fingerprint_comparators(self):
        from duplicates_detector.comparators import get_weighted_audio_mode_fingerprint_comparators

        weights = {"filename": 10.0, "duration": 10.0, "tags": 20.0, "audio": 60.0}
        comps = get_weighted_audio_mode_fingerprint_comparators(weights)
        for c in comps:
            if c.name == "directory":
                assert c.weight == 0.0
            else:
                assert c.weight == weights[c.name]

    def test_audio_mode_key_sets(self):
        from duplicates_detector.comparators import _AUDIO_MODE_DEFAULT_KEYS, _AUDIO_MODE_FINGERPRINT_KEYS

        assert {"filename", "duration", "tags", "directory"} == _AUDIO_MODE_DEFAULT_KEYS
        assert {"filename", "duration", "tags", "audio", "directory"} == _AUDIO_MODE_FINGERPRINT_KEYS

    def test_parse_weights_accepts_tags_key(self):
        from duplicates_detector.comparators import parse_weights

        result = parse_weights("filename=30,duration=30,tags=40")
        assert result["tags"] == 40.0

    def test_fresh_instances(self):
        """Each call returns fresh comparator instances."""
        from duplicates_detector.comparators import get_audio_mode_comparators

        a = get_audio_mode_comparators()
        b = get_audio_mode_comparators()
        for ca, cb in zip(a, b):
            assert ca is not cb


# ---------------------------------------------------------------------------
# 4. Scorer — Audio mode defaults
# ---------------------------------------------------------------------------


class TestScorerAudioMode:
    def test_audio_mode_uses_correct_default_comparators(self, make_metadata):
        """When mode='audio' and comparators=None, scorer uses get_audio_mode_comparators."""
        from duplicates_detector.scorer import find_duplicates

        # Use similar filenames so the filename gate (0.6 threshold) does not reject the pair
        items = [
            make_metadata(
                path="my_song.mp3",
                duration=180.0,
                width=None,
                height=None,
                file_size=5_000_000,
                tag_title="same song",
                tag_artist="same artist",
            ),
            make_metadata(
                path="my_song_copy.mp3",
                duration=180.0,
                width=None,
                height=None,
                file_size=5_000_000,
                tag_title="same song",
                tag_artist="same artist",
            ),
        ]
        results = find_duplicates(items, threshold=0.0, workers=1, quiet=True, mode="audio")
        # Should find the pair (similar filenames, same duration, same tags)
        assert len(results) >= 1

    def test_audio_mode_comparator_names(self, make_metadata):
        """Audio mode default comparators are filename, duration, tags."""
        from duplicates_detector.scorer import find_duplicates

        items = [
            make_metadata(
                path="a.mp3",
                duration=100.0,
                width=None,
                height=None,
                file_size=1_000_000,
                tag_title="song a",
            ),
            make_metadata(
                path="b.mp3",
                duration=100.0,
                width=None,
                height=None,
                file_size=1_000_000,
                tag_title="song b",
            ),
        ]

        results = find_duplicates(items, threshold=0.0, workers=1, quiet=True, mode="audio")
        if results:
            breakdown_keys = set(results[0].breakdown.keys())
            assert "tags" in breakdown_keys
            assert "filename" in breakdown_keys
            assert "duration" in breakdown_keys
            # Should NOT have resolution or file_size
            assert "resolution" not in breakdown_keys
            assert "file_size" not in breakdown_keys


# ---------------------------------------------------------------------------
# 5. Cache — tag field round-trip
# ---------------------------------------------------------------------------


class TestMetadataCacheTagFields:
    def test_round_trip_with_tags(self, tmp_path):
        """Tag fields stored via put() are retrievable via get()."""
        from duplicates_detector.cache import MetadataCache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/audio/song.mp3")
        cache.put(
            path=p,
            file_size=5_000_000,
            mtime=1_700_000_000.0,
            duration=240.0,
            width=None,
            height=None,
            codec="mp3",
            bitrate=320_000,
            audio_channels=2,
            tag_title="bohemian rhapsody",
            tag_artist="queen",
            tag_album="a night at the opera",
        )
        cache.save()

        # Reload from disk
        cache2 = MetadataCache(cache_dir=cache_dir)
        hit = cache2.get(p, file_size=5_000_000, mtime=1_700_000_000.0)
        assert hit is not None
        assert hit["tag_title"] == "bohemian rhapsody"
        assert hit["tag_artist"] == "queen"
        assert hit["tag_album"] == "a night at the opera"
        assert hit["duration"] == 240.0

    def test_backward_compat_missing_tag_fields(self, tmp_path):
        """Cache entries without tag fields return None for them (backward compat)."""
        from duplicates_detector.cache import MetadataCache, _METADATA_CACHE_VERSION

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Write a v2 cache entry WITHOUT tag fields (old format)
        p = Path("/videos/movie.mp4")
        data = {
            "version": _METADATA_CACHE_VERSION,
            "metadata": {
                str(p.resolve()): {
                    "file_size": 1_000_000,
                    "mtime": 1_700_000_000.0,
                    "duration": 120.0,
                    "width": 1920,
                    "height": 1080,
                    "codec": "h264",
                    "bitrate": 8_000_000,
                    "framerate": 23.976,
                    "audio_channels": 2,
                    # No tag_title, tag_artist, tag_album
                }
            },
        }
        (cache_dir / "metadata.json").write_text(json.dumps(data))

        cache = MetadataCache(cache_dir=cache_dir)
        hit = cache.get(p, file_size=1_000_000, mtime=1_700_000_000.0)
        assert hit is not None
        assert hit["tag_title"] is None
        assert hit["tag_artist"] is None
        assert hit["tag_album"] is None
        assert hit["duration"] == 120.0

    def test_tag_fields_none_when_not_set(self, tmp_path):
        """put() with default None tag fields stores None values correctly."""
        from duplicates_detector.cache import MetadataCache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cache = MetadataCache(cache_dir=cache_dir)
        p = Path("/audio/instrumental.flac")
        cache.put(
            path=p,
            file_size=10_000_000,
            mtime=1_700_000_000.0,
            duration=300.0,
            width=None,
            height=None,
        )
        cache.save()

        cache2 = MetadataCache(cache_dir=cache_dir)
        hit = cache2.get(p, file_size=10_000_000, mtime=1_700_000_000.0)
        assert hit is not None
        assert hit["tag_title"] is None
        assert hit["tag_artist"] is None
        assert hit["tag_album"] is None


# ---------------------------------------------------------------------------
# 6. Reporter — tag fields in serialization
# ---------------------------------------------------------------------------


class TestReporterTagFields:
    def test_metadata_dict_includes_tags_when_present(self):
        from duplicates_detector.reporter import _metadata_dict

        meta = VideoMetadata(
            path=Path("/audio/song.mp3"),
            filename="song",
            duration=200.0,
            width=None,
            height=None,
            file_size=5_000_000,
            tag_title="my song",
            tag_artist="my artist",
            tag_album="my album",
        )
        d = _metadata_dict(meta)
        assert d["tag_title"] == "my song"
        assert d["tag_artist"] == "my artist"
        assert d["tag_album"] == "my album"

    def test_metadata_dict_excludes_tags_when_none(self):
        from duplicates_detector.reporter import _metadata_dict

        meta = VideoMetadata(
            path=Path("/videos/movie.mp4"),
            filename="movie",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        d = _metadata_dict(meta)
        assert "tag_title" not in d
        assert "tag_artist" not in d
        assert "tag_album" not in d

    def test_metadata_dict_partial_tags(self):
        """Only non-None tag fields are included."""
        from duplicates_detector.reporter import _metadata_dict

        meta = VideoMetadata(
            path=Path("/audio/song.mp3"),
            filename="song",
            duration=200.0,
            width=None,
            height=None,
            file_size=5_000_000,
            tag_title="my song",
            tag_artist=None,
            tag_album=None,
        )
        d = _metadata_dict(meta)
        assert d["tag_title"] == "my song"
        assert "tag_artist" not in d
        assert "tag_album" not in d

    def test_reconstruct_metadata_with_tags(self):
        from duplicates_detector.reporter import _reconstruct_metadata

        meta_dict = {
            "duration": 200.0,
            "width": None,
            "height": None,
            "file_size": 5_000_000,
            "tag_title": "my song",
            "tag_artist": "my artist",
            "tag_album": "my album",
        }
        result = _reconstruct_metadata("/audio/song.mp3", meta_dict)
        assert result.tag_title == "my song"
        assert result.tag_artist == "my artist"
        assert result.tag_album == "my album"

    def test_reconstruct_metadata_without_tags(self):
        """Missing tag fields in dict default to None."""
        from duplicates_detector.reporter import _reconstruct_metadata

        meta_dict = {
            "duration": 120.0,
            "width": 1920,
            "height": 1080,
            "file_size": 1_000_000,
        }
        result = _reconstruct_metadata("/videos/movie.mp4", meta_dict)
        assert result.tag_title is None
        assert result.tag_artist is None
        assert result.tag_album is None

    def test_format_details_with_tags(self):
        from duplicates_detector.reporter import _format_details

        meta = VideoMetadata(
            path=Path("/audio/song.mp3"),
            filename="song",
            duration=200.0,
            width=None,
            height=None,
            file_size=5_000_000,
            tag_title="my song",
            tag_artist="my artist",
            tag_album="my album",
            codec="mp3",
        )
        result = _format_details(meta)
        assert "my artist" in result
        assert '"my song"' in result
        assert "[my album]" in result
        assert "MP3" in result

    def test_format_details_without_tags(self):
        """No tags means tag fields do not appear in details."""
        from duplicates_detector.reporter import _format_details

        meta = VideoMetadata(
            path=Path("/videos/movie.mp4"),
            filename="movie",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
            codec="h264",
            bitrate=8_000_000,
            framerate=23.976,
            audio_channels=2,
        )
        result = _format_details(meta)
        assert "tag_" not in result

    def test_json_round_trip_with_tags(self):
        """Tags survive JSON serialization and reconstruction."""
        from duplicates_detector.reporter import _metadata_dict, _reconstruct_metadata

        meta = VideoMetadata(
            path=Path("/audio/song.mp3"),
            filename="song",
            duration=200.0,
            width=None,
            height=None,
            file_size=5_000_000,
            tag_title="my song",
            tag_artist="my artist",
            tag_album="my album",
        )
        d = _metadata_dict(meta)
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        reconstructed = _reconstruct_metadata("/audio/song.mp3", parsed)
        assert reconstructed.tag_title == "my song"
        assert reconstructed.tag_artist == "my artist"
        assert reconstructed.tag_album == "my album"


# ---------------------------------------------------------------------------
# 7. Config — mode validation
# ---------------------------------------------------------------------------


class TestConfigAudioMode:
    def test_audio_mode_accepted(self):
        """'audio' is a valid mode in config validation."""
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", "audio") is True

    def test_video_mode_accepted(self):
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", "video") is True

    def test_image_mode_accepted(self):
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", "image") is True

    def test_auto_mode_accepted(self):
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", "auto") is True

    def test_invalid_mode_rejected(self):
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", "invalid_mode") is False

    def test_mode_must_be_string(self):
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", 42) is False

    def test_tags_weight_key_accepted(self):
        """'tags' is a valid key in the weight key map."""
        from duplicates_detector.config import _WEIGHT_KEYS

        assert "tags" in _WEIGHT_KEYS


# ---------------------------------------------------------------------------
# 8. CLI — Audio mode validation
# ---------------------------------------------------------------------------


def _make_audio_meta(path: str, file_size: int = 1_000_000, duration: float = 200.0) -> VideoMetadata:
    """Helper to create audio-mode metadata."""
    return VideoMetadata(
        path=Path(path),
        filename=Path(path).stem,
        duration=duration,
        width=None,
        height=None,
        file_size=file_size,
        tag_title="test song",
        tag_artist="test artist",
        tag_album="test album",
    )


class TestCliAudioModeValidation:
    def test_audio_mode_parses(self):
        from duplicates_detector.cli import parse_args

        args = parse_args([".", "--mode", "audio"])
        assert args.mode == "audio"

    def test_audio_mode_content_error(self, tmp_path):
        """--mode audio --content should error (use --audio for fingerprinting)."""
        from duplicates_detector.cli import main

        with patch("duplicates_detector.cli.Console"):
            with pytest.raises(SystemExit):
                main([str(tmp_path), "--mode", "audio", "--content"])

    def test_audio_mode_highest_res_error(self, tmp_path):
        """--mode audio --keep highest-res should error (no resolution for audio)."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "audio", "--keep", "highest-res"])

    def test_audio_mode_min_resolution_error(self, tmp_path):
        """--mode audio --min-resolution should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "audio", "--min-resolution", "1920x1080"])

    def test_audio_mode_max_resolution_error(self, tmp_path):
        """--mode audio --max-resolution should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main([str(tmp_path), "--mode", "audio", "--max-resolution", "3840x2160"])

    def test_audio_mode_keep_longest_ok(self, tmp_path):
        """--mode audio --keep longest should be valid (audio has duration)."""
        from duplicates_detector.cli import main

        files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
        for f in files:
            f.touch()
        metadata = [_make_audio_meta("a.mp3"), _make_audio_meta("b.mp3")]
        with (
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline", new_callable=AsyncMock, return_value=PipelineResult(pairs=[])
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary"),
            patch("duplicates_detector.cli.Console"),
            patch("duplicates_detector.metadata.Console"),
            patch("duplicates_detector.scanner.Console"),
            patch("duplicates_detector.scorer.Console"),
            patch("builtins.__import__", wraps=__import__),  # let mutagen import check pass
        ):
            # Mock mutagen import check
            with patch.dict("sys.modules", {"mutagen": MagicMock()}):
                main([str(tmp_path), "--mode", "audio", "--keep", "longest"])
        # Should not raise

    def test_audio_mode_keep_biggest_ok(self, tmp_path):
        """--mode audio --keep biggest should be valid."""
        from duplicates_detector.cli import main

        files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
        for f in files:
            f.touch()
        metadata = [_make_audio_meta("a.mp3"), _make_audio_meta("b.mp3")]
        with (
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline", new_callable=AsyncMock, return_value=PipelineResult(pairs=[])
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary"),
            patch("duplicates_detector.cli.Console"),
            patch("duplicates_detector.metadata.Console"),
            patch("duplicates_detector.scanner.Console"),
            patch("duplicates_detector.scorer.Console"),
        ):
            with patch.dict("sys.modules", {"mutagen": MagicMock()}):
                main([str(tmp_path), "--mode", "audio", "--keep", "biggest"])

    def test_audio_mode_with_audio_flag_ok(self, tmp_path):
        """--mode audio --audio should be valid (Chromaprint fingerprinting)."""
        from duplicates_detector.cli import main

        files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
        for f in files:
            f.touch()
        metadata = [_make_audio_meta("a.mp3"), _make_audio_meta("b.mp3")]
        with (
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline", new_callable=AsyncMock, return_value=PipelineResult(pairs=[])
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary"),
            patch("duplicates_detector.cli.Console"),
            patch("duplicates_detector.metadata.Console"),
            patch("duplicates_detector.scanner.Console"),
            patch("duplicates_detector.scorer.Console"),
            # Mock audio fingerprint extraction
            patch("duplicates_detector.audio.check_fpcalc"),
            patch("duplicates_detector.audio.extract_all_audio_fingerprints", return_value=metadata),
        ):
            with patch.dict("sys.modules", {"mutagen": MagicMock()}):
                main([str(tmp_path), "--mode", "audio", "--audio"])

    def test_audio_mode_uses_audio_extensions(self, tmp_path):
        """Audio mode should use DEFAULT_AUDIO_EXTENSIONS for scanning."""
        from duplicates_detector.cli import main

        with (
            patch(
                "duplicates_detector.scanner._scan_files_iter",
                side_effect=lambda *a, **kw: iter([Path("a.mp3"), Path("b.mp3")]),
            ),
            patch(
                "duplicates_detector.cli.run_pipeline",
                new_callable=AsyncMock,
                return_value=PipelineResult(pairs=[], files_scanned=2),
            ) as mock_pipeline,
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary"),
        ):
            with patch.dict("sys.modules", {"mutagen": MagicMock()}):
                main([str(tmp_path), "--mode", "audio"])

        # Verify run_pipeline was called with audio extensions
        from duplicates_detector.scanner import DEFAULT_AUDIO_EXTENSIONS

        assert mock_pipeline.call_args.kwargs.get("extensions") == DEFAULT_AUDIO_EXTENSIONS


# ---------------------------------------------------------------------------
# 8b. CLI — Audio mode weight validation
# ---------------------------------------------------------------------------


class TestCliAudioModeWeights:
    def test_audio_mode_rejects_resolution_weight(self, tmp_path):
        """Audio mode --weights with 'resolution' key should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "audio",
                    "--weights",
                    "filename=30,duration=30,resolution=10,tags=30",
                ]
            )

    def test_audio_mode_rejects_filesize_weight(self, tmp_path):
        """Audio mode --weights with 'filesize' key should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "audio",
                    "--weights",
                    "filename=30,duration=30,filesize=10,tags=30",
                ]
            )

    def test_audio_mode_rejects_exif_weight(self, tmp_path):
        """Audio mode --weights with 'exif' key should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "audio",
                    "--weights",
                    "filename=30,duration=20,exif=10,tags=40",
                ]
            )

    def test_audio_mode_rejects_content_weight(self, tmp_path):
        """Audio mode --weights with 'content' key should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "audio",
                    "--weights",
                    "filename=30,duration=20,content=10,tags=40",
                ]
            )

    def test_audio_mode_valid_weights(self, tmp_path):
        """Audio mode --weights with correct keys should work."""
        from duplicates_detector.cli import main

        files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
        for f in files:
            f.touch()
        metadata = [_make_audio_meta("a.mp3"), _make_audio_meta("b.mp3")]
        with (
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline", new_callable=AsyncMock, return_value=PipelineResult(pairs=[])
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary"),
        ):
            with patch.dict("sys.modules", {"mutagen": MagicMock()}):
                main(
                    [
                        str(tmp_path),
                        "--mode",
                        "audio",
                        "--weights",
                        "filename=30,duration=30,tags=40",
                    ]
                )

    def test_audio_mode_with_audio_flag_weights(self, tmp_path):
        """Audio mode + --audio + weights must include 'audio' key."""
        from duplicates_detector.cli import main

        files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
        for f in files:
            f.touch()
        metadata = [_make_audio_meta("a.mp3"), _make_audio_meta("b.mp3")]
        with (
            patch("duplicates_detector.cli.find_video_files", return_value=files),
            patch(
                "duplicates_detector.cli.run_pipeline", new_callable=AsyncMock, return_value=PipelineResult(pairs=[])
            ),
            patch("duplicates_detector.cli.print_table"),
            patch("duplicates_detector.cli.print_summary"),
            patch("duplicates_detector.audio.check_fpcalc"),
            patch("duplicates_detector.audio.extract_all_audio_fingerprints", return_value=metadata),
        ):
            with patch.dict("sys.modules", {"mutagen": MagicMock()}):
                main(
                    [
                        str(tmp_path),
                        "--mode",
                        "audio",
                        "--audio",
                        "--weights",
                        "filename=10,duration=10,tags=20,audio=60",
                    ]
                )

    def test_audio_mode_missing_tags_key_errors(self, tmp_path):
        """Audio mode weights without 'tags' key should error (missing required key)."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "audio",
                    "--weights",
                    "filename=50,duration=50",
                ]
            )

    def test_video_mode_rejects_tags_weight(self, tmp_path):
        """Video mode --weights with 'tags' key should error."""
        from duplicates_detector.cli import main

        with pytest.raises(SystemExit):
            main(
                [
                    str(tmp_path),
                    "--mode",
                    "video",
                    "--weights",
                    "filename=30,duration=20,resolution=10,filesize=10,tags=30",
                ]
            )


# ---------------------------------------------------------------------------
# 8c. CLI — _validate_weights for audio mode
# ---------------------------------------------------------------------------


class TestValidateWeightsAudioMode:
    def test_audio_mode_basic(self):
        from duplicates_detector.cli import _validate_weights

        console = Console(file=StringIO(), force_terminal=False)
        result = _validate_weights(
            "filename=30,duration=30,tags=40",
            content=False,
            console=console,
            mode="audio",
            audio=False,
        )
        assert result is not None
        assert result["tags"] == 40.0

    def test_audio_mode_with_audio_flag(self):
        from duplicates_detector.cli import _validate_weights

        console = Console(file=StringIO(), force_terminal=False)
        result = _validate_weights(
            "filename=10,duration=10,tags=20,audio=60",
            content=False,
            console=console,
            mode="audio",
            audio=True,
        )
        assert result is not None
        assert result["audio"] == 60.0

    def test_audio_mode_resolution_rejected(self):
        from duplicates_detector.cli import _validate_weights

        console = Console(file=StringIO(), force_terminal=False)
        with pytest.raises(SystemExit):
            _validate_weights(
                "filename=20,duration=20,resolution=20,tags=40",
                content=False,
                console=console,
                mode="audio",
            )

    def test_audio_mode_must_sum_to_100(self):
        from duplicates_detector.cli import _validate_weights

        console = Console(file=StringIO(), force_terminal=False)
        with pytest.raises(SystemExit):
            _validate_weights(
                "filename=30,duration=30,tags=30",  # sums to 90
                content=False,
                console=console,
                mode="audio",
            )


# ---------------------------------------------------------------------------
# 9. VideoMetadata tag field defaults
# ---------------------------------------------------------------------------


class TestVideoMetadataTagFields:
    def test_default_none(self):
        """Tag fields default to None."""
        meta = VideoMetadata(
            path=Path("video.mp4"),
            filename="video",
            duration=120.0,
            width=1920,
            height=1080,
            file_size=1_000_000,
        )
        assert meta.tag_title is None
        assert meta.tag_artist is None
        assert meta.tag_album is None

    def test_explicit_values(self):
        """Tag fields can be set explicitly."""
        meta = VideoMetadata(
            path=Path("song.mp3"),
            filename="song",
            duration=200.0,
            width=None,
            height=None,
            file_size=5_000_000,
            tag_title="my song",
            tag_artist="my artist",
            tag_album="my album",
        )
        assert meta.tag_title == "my song"
        assert meta.tag_artist == "my artist"
        assert meta.tag_album == "my album"

    def test_make_metadata_fixture(self, make_metadata):
        """The make_metadata fixture supports tag fields."""
        meta = make_metadata(
            path="song.mp3",
            tag_title="test",
            tag_artist="artist",
            tag_album="album",
        )
        assert meta.tag_title == "test"
        assert meta.tag_artist == "artist"
        assert meta.tag_album == "album"

    def test_make_metadata_default_none(self, make_metadata):
        """make_metadata without tag fields produces None."""
        meta = make_metadata(path="video.mp4")
        assert meta.tag_title is None
        assert meta.tag_artist is None
        assert meta.tag_album is None
