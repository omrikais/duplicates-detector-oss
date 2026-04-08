from __future__ import annotations

import pytest

from duplicates_detector.comparators import (
    normalize_filename,
    _is_numeric_id,
    _haversine_meters,
    FileNameComparator,
    DurationComparator,
    ResolutionComparator,
    FileSizeComparator,
    ContentComparator,
    ExifComparator,
    get_default_comparators,
    get_content_comparators,
    parse_weights,
    get_weighted_comparators,
    get_weighted_content_comparators,
)


# ---------------------------------------------------------------------------
# _is_numeric_id
# ---------------------------------------------------------------------------


class TestIsNumericId:
    @pytest.mark.parametrize(
        "normalized, expected",
        [
            ("1 5181682535712686828", True),  # Telegram-style ID
            ("20230415 134522", True),  # timestamp-style ID
            ("s01e02", True),  # >50% digits
            ("movie part1", False),  # mostly letters
            ("the great movie 2024", False),  # mostly letters
            ("", False),  # empty
            ("abc", False),  # no digits
            ("123", True),  # all digits
        ],
    )
    def test_detection(self, normalized, expected):
        assert _is_numeric_id(normalized) is expected


# ---------------------------------------------------------------------------
# normalize_filename
# ---------------------------------------------------------------------------


class TestNormalizeFilename:
    @pytest.mark.parametrize(
        "input_name, expected",
        [
            ("Movie.1080p.BluRay.x264", "movie"),
            ("Movie.720p.WebRip.DTS.5.1", "movie"),
            ("movie_title-part1", "movie title part1"),
            ("Movie.DTS.5.1.AC3", "movie"),
            ("Clean_Name", "clean name"),
            ("already clean", "already clean"),
            ("The.Movie.Name.2024.PROPER.REPACK", "the movie name 2024"),
            ("show[s01e02]hdtv.h264.aac", "show s01e02"),
            ("movie.h.265.10bit.HDR", "movie"),
            ("Film_(2023)_HEVC_Atmos", "film 2023 hevc atmos"),
        ],
    )
    def test_strips_quality_markers(self, input_name, expected):
        assert normalize_filename(input_name) == expected

    def test_empty_after_stripping(self):
        # If the entire name is quality markers, result is empty
        result = normalize_filename("1080p.BluRay.x264.DTS")
        assert result == ""

    def test_preserves_meaningful_words(self):
        result = normalize_filename("My.Great.Movie.2023")
        assert "my" in result
        assert "great" in result
        assert "movie" in result
        assert "2023" in result


# ---------------------------------------------------------------------------
# FileNameComparator
# ---------------------------------------------------------------------------


class TestFileNameComparator:
    def setup_method(self):
        self.comp = FileNameComparator()

    def test_identical_names(self, make_metadata):
        a = make_metadata(path="movie.mp4")
        b = make_metadata(path="movie.mkv")
        assert self.comp.score(a, b) == pytest.approx(1.0)

    def test_completely_different(self, make_metadata):
        a = make_metadata(path="alpha_bravo.mp4")
        b = make_metadata(path="zulu_yankee.mp4")
        score = self.comp.score(a, b)
        assert score is not None
        assert score < 0.3

    def test_empty_after_normalization(self, make_metadata):
        a = make_metadata(filename="1080p")
        b = make_metadata(filename="BluRay")
        assert self.comp.score(a, b) == 0.0

    def test_similar_names_high_score(self, make_metadata):
        a = make_metadata(filename="The_Great_Movie")
        b = make_metadata(filename="The.Great.Movie.1080p")
        score = self.comp.score(a, b)
        assert score is not None
        assert score > 0.8

    def test_numeric_id_different_ids(self, make_metadata):
        """Numeric ID filenames with different IDs should score 0."""
        a = make_metadata(filename="1_5181682535712686828")
        b = make_metadata(filename="1_5181682535712686721")
        assert self.comp.score(a, b) == 0.0

    def test_numeric_id_same_ids(self, make_metadata):
        """Identical numeric ID filenames should score 1.0."""
        a = make_metadata(filename="1_5181682535712686828")
        b = make_metadata(filename="1_5181682535712686828")
        assert self.comp.score(a, b) == 1.0

    def test_numeric_id_vs_regular_name(self, make_metadata):
        """Mixed pair (one numeric, one not) uses normal fuzzy matching."""
        a = make_metadata(filename="1_5181682535712686828")
        b = make_metadata(filename="The_Great_Movie")
        score = self.comp.score(a, b)
        # Should use regular fuzzy matching, not the numeric ID path
        assert score is not None
        assert score < 0.3

    def test_numbered_series_different_numbers(self, make_metadata):
        """Same text skeleton with different numbers → 0 (different entries)."""
        a = make_metadata(filename="movie_part1")
        b = make_metadata(filename="movie_part2")
        assert self.comp.score(a, b) == 0.0

    def test_numbered_series_same_numbers(self, make_metadata):
        """Same text skeleton with same numbers → normal fuzzy score."""
        a = make_metadata(filename="movie_part1")
        b = make_metadata(filename="movie_part1")
        assert self.comp.score(a, b) == 1.0

    def test_numbered_series_hash_prefix(self, make_metadata):
        """Numbered travel videos with different IDs → 0."""
        a = make_metadata(filename="# 94 Russia Moscow")
        b = make_metadata(filename="# 423 Russia Moscow")
        assert self.comp.score(a, b) == 0.0

    def test_numbered_series_different_text(self, make_metadata):
        """Different text skeletons bypass numbered-series check → fuzzy match."""
        a = make_metadata(filename="movie_2024")
        b = make_metadata(filename="movie_2024_copy")
        score = self.comp.score(a, b)
        # Text skeletons differ ("movie" vs "movie copy") → normal fuzzy matching
        assert score is not None
        assert score > 0.5

    # --- Distinct content words heuristic ---

    def test_distinct_words_country_city(self, make_metadata):
        """Shared country prefix + different cities → 0 (different videos)."""
        a = make_metadata(filename="# 307 Mexico Guadalupe")
        b = make_metadata(filename="# 379 Mexico Izamal")
        assert self.comp.score(a, b) == 0.0

    def test_distinct_words_country_city_2(self, make_metadata):
        """Another country+city pair should also be rejected."""
        a = make_metadata(filename="# 505 Colombia Armenia")
        b = make_metadata(filename="# 356 Colombia Cartagena")
        assert self.comp.score(a, b) == 0.0

    def test_distinct_words_only_one_side(self, make_metadata):
        """Unique word only on one side → not rejected (could be a copy)."""
        a = make_metadata(filename="Movie Extended")
        b = make_metadata(filename="Movie Extended Edition")
        score = self.comp.score(a, b)
        assert score is not None
        assert score > 0.5

    def test_distinct_words_high_similarity_bypass(self, make_metadata):
        """High fuzzy score (≥85%) bypasses the distinct-word check."""
        a = make_metadata(filename="Avengers Endgame")
        b = make_metadata(filename="Avengers End Game")
        score = self.comp.score(a, b)
        assert score is not None
        assert score > 0.8

    def test_distinct_words_short_tokens_ignored(self, make_metadata):
        """Unique tokens shorter than 3 chars don't trigger rejection."""
        a = make_metadata(filename="Movie HD Version")
        b = make_metadata(filename="Movie SD Version")
        score = self.comp.score(a, b)
        # "hd" and "sd" are only 2 chars → heuristic doesn't apply
        assert score is not None
        assert score > 0.5

    # --- Normalized filename cache ---

    def test_uses_prepopulated_cache(self, make_metadata):
        """Scoring uses pre-populated cache instead of recomputing."""
        comp = FileNameComparator()
        comp.set_normalized_cache({"My Video": "my video", "My.Video": "my video"})
        a = make_metadata(filename="My Video")
        b = make_metadata(filename="My.Video")
        score = comp.score(a, b)
        assert score is not None
        assert score > 0.9

    def test_cache_miss_computes_on_demand(self, make_metadata):
        """Filenames not in the cache are computed on demand."""
        comp = FileNameComparator()
        # Pre-populate with one entry; the other is missing
        comp.set_normalized_cache({"The_Great_Movie": "the great movie"})
        a = make_metadata(filename="The_Great_Movie")
        b = make_metadata(filename="The.Great.Movie.1080p")
        score = comp.score(a, b)
        assert score is not None
        assert score > 0.8
        # The miss should now be in the cache
        assert "The.Great.Movie.1080p" in comp._normalized_cache

    def test_cache_not_shared_across_instances(self, make_metadata):
        """Each FileNameComparator instance has its own cache."""
        comp1 = FileNameComparator()
        comp2 = FileNameComparator()
        comp1.set_normalized_cache({"foo": "bar"})
        assert comp2._normalized_cache == {}


# ---------------------------------------------------------------------------
# DurationComparator
# ---------------------------------------------------------------------------


class TestDurationComparator:
    def setup_method(self):
        self.comp = DurationComparator()

    @pytest.mark.parametrize(
        "dur_a, dur_b, expected",
        [
            (120.0, 120.0, 1.0),  # identical
            (120.0, 122.5, 0.5),  # diff=2.5 → 0.5
            (120.0, 125.0, 0.0),  # diff=5.0 → 0.0
            (120.0, 130.0, 0.0),  # diff=10 → 0.0
            (100.0, 101.0, 0.8),  # diff=1.0 → 0.8
        ],
    )
    def test_duration_scores(self, make_metadata, dur_a, dur_b, expected):
        a = make_metadata(duration=dur_a)
        b = make_metadata(duration=dur_b)
        assert self.comp.score(a, b) == pytest.approx(expected)

    def test_none_duration_a(self, make_metadata):
        a = make_metadata(duration=None)
        b = make_metadata(duration=120.0)
        assert self.comp.score(a, b) is None

    def test_none_duration_b(self, make_metadata):
        a = make_metadata(duration=120.0)
        b = make_metadata(duration=None)
        assert self.comp.score(a, b) is None

    def test_both_none(self, make_metadata):
        a = make_metadata(duration=None)
        b = make_metadata(duration=None)
        assert self.comp.score(a, b) is None


# ---------------------------------------------------------------------------
# ResolutionComparator
# ---------------------------------------------------------------------------


class TestResolutionComparator:
    def setup_method(self):
        self.comp = ResolutionComparator()

    def test_same_resolution(self, make_metadata):
        a = make_metadata(width=1920, height=1080)
        b = make_metadata(width=1920, height=1080)
        assert self.comp.score(a, b) == pytest.approx(1.0)

    def test_1080p_vs_720p(self, make_metadata):
        a = make_metadata(width=1920, height=1080)
        b = make_metadata(width=1280, height=720)
        expected = (1280 * 720) / (1920 * 1080)
        assert self.comp.score(a, b) == pytest.approx(expected)

    def test_none_dimensions(self, make_metadata):
        a = make_metadata(width=None, height=None)
        b = make_metadata(width=1920, height=1080)
        assert self.comp.score(a, b) is None

    def test_zero_pixels(self, make_metadata):
        a = make_metadata(width=0, height=0)
        b = make_metadata(width=1920, height=1080)
        assert self.comp.score(a, b) == 0.0

    def test_one_none_width(self, make_metadata):
        a = make_metadata(width=None, height=1080)
        b = make_metadata(width=1920, height=1080)
        assert self.comp.score(a, b) is None


# ---------------------------------------------------------------------------
# FileSizeComparator
# ---------------------------------------------------------------------------


class TestFileSizeComparator:
    def setup_method(self):
        self.comp = FileSizeComparator()

    def test_same_size(self, make_metadata):
        a = make_metadata(file_size=1_000_000)
        b = make_metadata(file_size=1_000_000)
        assert self.comp.score(a, b) == pytest.approx(1.0)

    def test_two_to_one_ratio(self, make_metadata):
        a = make_metadata(file_size=1_000_000)
        b = make_metadata(file_size=2_000_000)
        assert self.comp.score(a, b) == pytest.approx(0.5)

    def test_zero_size(self, make_metadata):
        a = make_metadata(file_size=0)
        b = make_metadata(file_size=1_000_000)
        assert self.comp.score(a, b) == 0.0

    def test_both_zero(self, make_metadata):
        a = make_metadata(file_size=0)
        b = make_metadata(file_size=0)
        assert self.comp.score(a, b) == 0.0


# ---------------------------------------------------------------------------
# get_default_comparators
# ---------------------------------------------------------------------------


class TestGetDefaultComparators:
    def test_returns_five(self):
        comps = get_default_comparators()
        assert len(comps) == 5

    def test_weights_sum_to_100(self):
        comps = get_default_comparators()
        assert sum(c.weight for c in comps) == pytest.approx(100.0)

    def test_fresh_instances(self):
        a = get_default_comparators()
        b = get_default_comparators()
        for ca, cb in zip(a, b):
            assert ca is not cb


# ---------------------------------------------------------------------------
# ContentComparator
# ---------------------------------------------------------------------------


class TestContentComparator:
    def setup_method(self):
        self.comp = ContentComparator()

    def test_name(self):
        assert self.comp.name == "content"

    def test_weight(self):
        assert self.comp.weight == 40.0

    def test_identical_hashes(self, make_metadata):
        h = (0xABCD, 0x1234, 0x5678, 0x9ABC)
        a = make_metadata(path="a.mp4", content_hash=h)
        b = make_metadata(path="b.mp4", content_hash=h)
        assert self.comp.score(a, b) == pytest.approx(1.0)

    def test_no_hash_returns_none(self, make_metadata):
        a = make_metadata(path="a.mp4", content_hash=(0xABCD, 0x1234, 0x5678, 0x9ABC))
        b = make_metadata(path="b.mp4", content_hash=None)
        assert self.comp.score(a, b) is None

        a = make_metadata(path="a.mp4", content_hash=None)
        b = make_metadata(path="b.mp4", content_hash=None)
        assert self.comp.score(a, b) is None

    def test_different_hashes_returns_low_score(self, make_metadata):
        a = make_metadata(path="a.mp4", content_hash=(0, 0, 0, 0))
        b = make_metadata(path="b.mp4", content_hash=((1 << 64) - 1, (1 << 64) - 1, (1 << 64) - 1, (1 << 64) - 1))
        score = self.comp.score(a, b)
        assert score is not None
        assert score < 0.1


# ---------------------------------------------------------------------------
# _haversine_meters
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_same_point(self):
        assert _haversine_meters(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_nyc_london(self):
        # NYC (40.7128, -74.0060) → London (51.5074, -0.1278) ≈ 5,570 km
        dist = _haversine_meters(40.7128, -74.0060, 51.5074, -0.1278)
        assert 5_500_000 < dist < 5_700_000

    def test_antipodal(self):
        # North pole to south pole ≈ 20,015 km (half circumference)
        dist = _haversine_meters(90.0, 0.0, -90.0, 0.0)
        assert 20_000_000 < dist < 20_100_000


# ---------------------------------------------------------------------------
# ExifComparator
# ---------------------------------------------------------------------------


class TestExifComparator:
    def setup_method(self):
        self.comp = ExifComparator()

    def test_name_and_weight(self):
        assert self.comp.name == "exif"
        assert self.comp.weight == 40.0

    def test_no_exif_returns_none(self, make_metadata):
        """Both files with no EXIF data → None."""
        a = make_metadata(path="a.jpg", duration=None)
        b = make_metadata(path="b.jpg", duration=None)
        assert self.comp.score(a, b) is None

    def test_perfect_datetime_match(self, make_metadata):
        """Identical timestamps → sub-score 1.0."""
        t = 1_700_000_000.0
        a = make_metadata(path="a.jpg", duration=None, exif_datetime=t)
        b = make_metadata(path="b.jpg", duration=None, exif_datetime=t)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_datetime_30min_apart(self, make_metadata):
        """30 minutes apart → half falloff on datetime sub-score."""
        t = 1_700_000_000.0
        a = make_metadata(path="a.jpg", duration=None, exif_datetime=t)
        b = make_metadata(path="b.jpg", duration=None, exif_datetime=t + 1800)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(0.5)

    def test_datetime_over_1h_apart(self, make_metadata):
        """Over 1 hour apart → datetime sub-score clamped to 0."""
        t = 1_700_000_000.0
        a = make_metadata(path="a.jpg", duration=None, exif_datetime=t)
        b = make_metadata(path="b.jpg", duration=None, exif_datetime=t + 7200)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(0.0)

    def test_camera_match(self, make_metadata):
        """Same camera → sub-score 1.0."""
        a = make_metadata(path="a.jpg", duration=None, exif_camera="canon eos r5")
        b = make_metadata(path="b.jpg", duration=None, exif_camera="canon eos r5")
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_camera_mismatch(self, make_metadata):
        """Different cameras → sub-score 0.0."""
        a = make_metadata(path="a.jpg", duration=None, exif_camera="canon eos r5")
        b = make_metadata(path="b.jpg", duration=None, exif_camera="nikon z6")
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(0.0)

    def test_gps_same_location(self, make_metadata):
        """Same GPS → sub-score 1.0."""
        a = make_metadata(path="a.jpg", duration=None, exif_gps_lat=40.7128, exif_gps_lon=-74.0060)
        b = make_metadata(path="b.jpg", duration=None, exif_gps_lat=40.7128, exif_gps_lon=-74.0060)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_gps_far_apart(self, make_metadata):
        """GPS locations > 1km apart → GPS sub-score 0.0."""
        a = make_metadata(path="a.jpg", duration=None, exif_gps_lat=40.7128, exif_gps_lon=-74.0060)
        b = make_metadata(path="b.jpg", duration=None, exif_gps_lat=51.5074, exif_gps_lon=-0.1278)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(0.0)

    def test_partial_data_redistribution(self, make_metadata):
        """Only datetime + camera available → weights redistributed to sum 1.0."""
        t = 1_700_000_000.0
        a = make_metadata(path="a.jpg", duration=None, exif_datetime=t, exif_camera="canon eos r5")
        b = make_metadata(path="b.jpg", duration=None, exif_datetime=t, exif_camera="canon eos r5")
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_one_sided_datetime_skipped(self, make_metadata):
        """Datetime on only one file → datetime sub-field not used."""
        t = 1_700_000_000.0
        a = make_metadata(path="a.jpg", duration=None, exif_datetime=t, exif_camera="canon eos r5")
        b = make_metadata(path="b.jpg", duration=None, exif_datetime=None, exif_camera="canon eos r5")
        score = self.comp.score(a, b)
        assert score is not None
        # Only camera available, perfect match
        assert score == pytest.approx(1.0)

    def test_dimensions_match(self, make_metadata):
        """EXIF dims matching actual dims → dimensions sub-score 1.0."""
        a = make_metadata(path="a.jpg", duration=None, width=4000, height=3000, exif_width=4000, exif_height=3000)
        b = make_metadata(path="b.jpg", duration=None, width=4000, height=3000, exif_width=4000, exif_height=3000)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_dimensions_mismatch(self, make_metadata):
        """EXIF dims not matching actual dims → dimensions sub-score 0.0."""
        a = make_metadata(path="a.jpg", duration=None, width=4000, height=3000, exif_width=4000, exif_height=3000)
        b = make_metadata(path="b.jpg", duration=None, width=2000, height=1500, exif_width=4000, exif_height=3000)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(0.0)

    def test_dimensions_cross_file_mismatch(self, make_metadata):
        """Each file's EXIF matches its own actuals but differ across files → 0.0."""
        a = make_metadata(path="a.jpg", duration=None, width=4000, height=3000, exif_width=4000, exif_height=3000)
        b = make_metadata(path="b.jpg", duration=None, width=640, height=480, exif_width=640, exif_height=480)
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(0.0)

    def test_lens_match(self, make_metadata):
        """Same lens → sub-score 1.0."""
        a = make_metadata(path="a.jpg", duration=None, exif_lens="rf 24-70mm f2.8l")
        b = make_metadata(path="b.jpg", duration=None, exif_lens="rf 24-70mm f2.8l")
        score = self.comp.score(a, b)
        assert score is not None
        assert score == pytest.approx(1.0)

    def test_all_fields_perfect(self, make_metadata):
        """All EXIF sub-fields present and identical → 1.0."""
        t = 1_700_000_000.0
        a = make_metadata(
            path="a.jpg",
            duration=None,
            width=4000,
            height=3000,
            exif_datetime=t,
            exif_camera="canon eos r5",
            exif_lens="rf 24-70mm f2.8l",
            exif_gps_lat=40.7128,
            exif_gps_lon=-74.0060,
            exif_width=4000,
            exif_height=3000,
        )
        b = make_metadata(
            path="b.jpg",
            duration=None,
            width=4000,
            height=3000,
            exif_datetime=t,
            exif_camera="canon eos r5",
            exif_lens="rf 24-70mm f2.8l",
            exif_gps_lat=40.7128,
            exif_gps_lon=-74.0060,
            exif_width=4000,
            exif_height=3000,
        )
        assert self.comp.score(a, b) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_content_comparators
# ---------------------------------------------------------------------------


class TestGetContentComparators:
    def test_includes_six_comparators(self):
        comps = get_content_comparators()
        assert len(comps) == 6

    def test_includes_content(self):
        comps = get_content_comparators()
        names = [c.name for c in comps]
        assert "content" in names

    def test_weights_sum_to_100(self):
        comps = get_content_comparators()
        assert sum(c.weight for c in comps) == pytest.approx(100.0)

    def test_default_unchanged(self):
        defaults = get_default_comparators()
        assert len(defaults) == 5
        assert sum(c.weight for c in defaults) == pytest.approx(100.0)
        names = [c.name for c in defaults]
        assert "content" not in names


# ---------------------------------------------------------------------------
# parse_weights
# ---------------------------------------------------------------------------


class TestParseWeights:
    def test_basic_parse(self):
        w = parse_weights("filename=50,duration=30,resolution=10,filesize=10")
        assert w == {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}

    def test_zero_values(self):
        w = parse_weights("filename=0,duration=0,resolution=0,filesize=100")
        assert w["filename"] == 0.0
        assert w["file_size"] == 100.0

    def test_float_values(self):
        w = parse_weights("filename=33.3,duration=33.3,resolution=16.7,filesize=16.7")
        assert w["filename"] == pytest.approx(33.3)

    def test_file_size_alias(self):
        w = parse_weights("filename=50,duration=30,resolution=10,file_size=10")
        assert w["file_size"] == 10.0

    def test_case_insensitive(self):
        w = parse_weights("FileName=50,Duration=30,Resolution=10,FileSize=10")
        assert "filename" in w
        assert "duration" in w

    def test_content_key(self):
        w = parse_weights("filename=20,duration=20,resolution=10,filesize=10,content=40")
        assert w["content"] == 40.0

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="unknown weight key"):
            parse_weights("filename=50,bogus=50")

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            parse_weights("filename=-10,duration=110")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="invalid weight format"):
            parse_weights("filename:50")

    def test_duplicate_key_raises(self):
        with pytest.raises(ValueError, match="duplicate"):
            parse_weights("filename=50,filename=50")

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="invalid weight value"):
            parse_weights("filename=abc")

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="finite number"):
            parse_weights("filename=nan,duration=50,resolution=25,filesize=25")

    def test_inf_raises(self):
        with pytest.raises(ValueError, match="finite number"):
            parse_weights("filename=inf,duration=50,resolution=25,filesize=25")


# ---------------------------------------------------------------------------
# get_weighted_comparators
# ---------------------------------------------------------------------------


class TestGetWeightedComparators:
    def test_applies_weights(self):
        weights = {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}
        comps = get_weighted_comparators(weights)
        assert len(comps) == 5
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 50.0
        assert by_name["duration"] == 30.0

    def test_sum_preserved(self):
        weights = {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}
        comps = get_weighted_comparators(weights)
        assert sum(c.weight for c in comps) == pytest.approx(100.0)


class TestGetWeightedContentComparators:
    def test_applies_weights(self):
        weights = {"filename": 10.0, "duration": 10.0, "resolution": 10.0, "file_size": 10.0, "content": 60.0}
        comps = get_weighted_content_comparators(weights)
        assert len(comps) == 6
        by_name = {c.name: c.weight for c in comps}
        assert by_name["content"] == 60.0

    def test_sum_preserved(self):
        weights = {"filename": 10.0, "duration": 10.0, "resolution": 10.0, "file_size": 10.0, "content": 60.0}
        comps = get_weighted_content_comparators(weights)
        assert sum(c.weight for c in comps) == pytest.approx(100.0)

    def test_rotation_invariant_forwarded(self):
        weights = {"filename": 10.0, "duration": 10.0, "resolution": 10.0, "file_size": 10.0, "content": 60.0}
        comps = get_weighted_content_comparators(weights, rotation_invariant=True)
        content_comp = [c for c in comps if c.name == "content"][0]
        assert isinstance(content_comp, ContentComparator)
        assert content_comp._rotation_invariant is True


# ---------------------------------------------------------------------------
# ContentComparator score forwarding
# ---------------------------------------------------------------------------


class TestContentComparatorScore:
    def test_score_forwards_to_compare_content_hashes(self, make_metadata):
        """score() passes rotation_invariant to compare_content_hashes."""
        from unittest.mock import patch

        a = make_metadata(path="a.mp4", content_hash=(0xABCD,))
        b = make_metadata(path="b.mp4", content_hash=(0xABCE,))
        comp = ContentComparator()

        with patch("duplicates_detector.content.compare_content_hashes", return_value=0.95) as mock_cmp:
            result = comp.score(a, b)

        mock_cmp.assert_called_once_with(a.content_hash, b.content_hash, rotation_invariant=False)
        assert result == 0.95


# ---------------------------------------------------------------------------
# Image mode comparators
# ---------------------------------------------------------------------------


class TestImageComparators:
    def test_get_image_comparators_count(self):
        from duplicates_detector.comparators import get_image_comparators

        comps = get_image_comparators()
        assert len(comps) == 5
        names = {c.name for c in comps}
        assert names == {"filename", "resolution", "file_size", "exif", "directory"}
        assert "duration" not in names

    def test_image_comparators_weights_sum(self):
        from duplicates_detector.comparators import get_image_comparators

        comps = get_image_comparators()
        assert sum(c.weight for c in comps) == 100.0

    def test_get_image_content_comparators(self):
        from duplicates_detector.comparators import get_image_content_comparators

        comps = get_image_content_comparators()
        assert len(comps) == 6
        names = {c.name for c in comps}
        assert "content" in names
        assert "exif" in names
        assert "directory" in names
        assert "duration" not in names
        assert sum(c.weight for c in comps) == 100.0

    def test_get_weighted_image_comparators(self):
        from duplicates_detector.comparators import get_weighted_image_comparators

        weights = {"filename": 30.0, "resolution": 20.0, "file_size": 10.0, "exif": 40.0}
        comps = get_weighted_image_comparators(weights)
        assert len(comps) == 5
        for c in comps:
            if c.name == "directory":
                assert c.weight == 0.0  # not in weights, stays at default
            else:
                assert c.weight == weights[c.name]

    def test_get_weighted_image_content_comparators(self):
        from duplicates_detector.comparators import get_weighted_image_content_comparators

        weights = {"filename": 10.0, "resolution": 10.0, "file_size": 10.0, "exif": 20.0, "content": 50.0}
        comps = get_weighted_image_content_comparators(weights)
        assert len(comps) == 6
        for c in comps:
            if c.name == "directory":
                assert c.weight == 0.0
            else:
                assert c.weight == weights[c.name]

    def test_image_key_sets(self):
        from duplicates_detector.comparators import _IMAGE_DEFAULT_KEYS, _IMAGE_CONTENT_KEYS

        assert {"filename", "resolution", "filesize", "exif", "directory"} == _IMAGE_DEFAULT_KEYS
        assert {"filename", "resolution", "filesize", "exif", "content", "directory"} == _IMAGE_CONTENT_KEYS


# ---------------------------------------------------------------------------
# ContentComparator rotation_invariant threading
# ---------------------------------------------------------------------------


class TestContentComparatorRotationInvariant:
    def test_default_no_rotation(self):
        comp = ContentComparator()
        assert comp._rotation_invariant is False

    def test_rotation_invariant_stored(self):
        comp = ContentComparator(rotation_invariant=True)
        assert comp._rotation_invariant is True

    def test_score_forwards_rotation_invariant(self, make_metadata):
        """score() passes rotation_invariant to compare_content_hashes."""
        from unittest.mock import patch

        a = make_metadata(path="a.png", content_hash=(0xABCD,) * 8)
        b = make_metadata(path="b.png", content_hash=(0xABCE,) * 8)
        comp = ContentComparator(rotation_invariant=True)

        with patch("duplicates_detector.content.compare_content_hashes", return_value=0.95) as mock_cmp:
            result = comp.score(a, b)

        mock_cmp.assert_called_once_with(a.content_hash, b.content_hash, rotation_invariant=True)
        assert result == 0.95

    def test_get_content_comparators_forwards_rotation_invariant(self):
        comps = get_content_comparators(rotation_invariant=True)
        content_comp = [c for c in comps if c.name == "content"][0]
        assert isinstance(content_comp, ContentComparator)
        assert content_comp._rotation_invariant is True

    def test_get_image_content_comparators_forwards_rotation_invariant(self):
        from duplicates_detector.comparators import get_image_content_comparators

        comps = get_image_content_comparators(rotation_invariant=True)
        content_comp = [c for c in comps if c.name == "content"][0]
        assert isinstance(content_comp, ContentComparator)
        assert content_comp._rotation_invariant is True

    def test_get_weighted_content_comparators_forwards_rotation_invariant(self):
        from duplicates_detector.comparators import get_weighted_content_comparators

        weights = {"filename": 10.0, "duration": 10.0, "resolution": 10.0, "file_size": 10.0, "content": 60.0}
        comps = get_weighted_content_comparators(weights, rotation_invariant=True)
        content_comp = [c for c in comps if c.name == "content"][0]
        assert isinstance(content_comp, ContentComparator)
        assert content_comp._rotation_invariant is True

    def test_get_weighted_image_content_comparators_forwards_rotation_invariant(self):
        from duplicates_detector.comparators import get_weighted_image_content_comparators

        weights = {"filename": 10.0, "resolution": 10.0, "file_size": 10.0, "content": 70.0}
        comps = get_weighted_image_content_comparators(weights, rotation_invariant=True)
        content_comp = [c for c in comps if c.name == "content"][0]
        assert isinstance(content_comp, ContentComparator)
        assert content_comp._rotation_invariant is True


# ---------------------------------------------------------------------------
# ContentComparator SSIM dispatching
# ---------------------------------------------------------------------------


class TestContentComparatorSsim:
    """Test ContentComparator dispatching to SSIM when content_frames is present."""

    def test_both_have_frames_calls_ssim(self, make_metadata):
        """When both files have content_frames, SSIM is used."""
        from io import BytesIO
        from unittest.mock import patch

        from PIL import Image

        def _png(color):
            buf = BytesIO()
            Image.new("RGB", (8, 8), color).save(buf, format="PNG")
            return buf.getvalue()

        frame = _png((128, 128, 128))
        a = make_metadata(path="a.mp4", content_frames=(frame,))
        b = make_metadata(path="b.mp4", content_frames=(frame,))
        comp = ContentComparator()
        with patch("duplicates_detector.content.compare_ssim_frames", return_value=0.95) as mock_ssim:
            result = comp.score(a, b)
        mock_ssim.assert_called_once()
        assert result == pytest.approx(0.95)

    def test_one_missing_frames_returns_none(self, make_metadata):
        """When one file lacks content_frames (and both lack content_hash), returns None."""
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()
        a = make_metadata(path="a.mp4", content_frames=(frame,))
        b = make_metadata(path="b.mp4")
        comp = ContentComparator()
        assert comp.score(a, b) is None

    def test_mixed_hash_and_frames_returns_none(self, make_metadata):
        """When one has content_hash and other has content_frames, returns None."""
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()
        a = make_metadata(path="a.mp4", content_hash=(0xABCD,))
        b = make_metadata(path="b.mp4", content_frames=(frame,))
        comp = ContentComparator()
        assert comp.score(a, b) is None

    def test_frames_preferred_over_hash(self, make_metadata):
        """When both have content_frames AND content_hash, SSIM (frames) is used."""
        from io import BytesIO
        from unittest.mock import patch

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (128, 128, 128)).save(buf, format="PNG")
        frame = buf.getvalue()
        a = make_metadata(path="a.mp4", content_hash=(0xABCD,), content_frames=(frame,))
        b = make_metadata(path="b.mp4", content_hash=(0xABCD,), content_frames=(frame,))
        comp = ContentComparator()
        with patch("duplicates_detector.content.compare_ssim_frames", return_value=0.8) as mock_ssim:
            result = comp.score(a, b)
        mock_ssim.assert_called_once()
        assert result == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# ContentComparator CLIP dispatch
# ---------------------------------------------------------------------------


class TestContentComparatorClip:
    """Test ContentComparator dispatching to CLIP when clip_embedding is present."""

    def test_both_have_clip_calls_compare(self, make_metadata):
        """When both files have clip_embedding, CLIP comparison is used."""
        from unittest.mock import patch

        emb_a = tuple(float(i) * 0.01 for i in range(512))
        emb_b = tuple(float(i) * 0.01 for i in range(512))
        a = make_metadata(path="a.jpg", clip_embedding=emb_a)
        b = make_metadata(path="b.jpg", clip_embedding=emb_b)
        comp = ContentComparator()
        with patch("duplicates_detector.clip.compare_clip_embeddings", return_value=0.92) as mock_clip:
            result = comp.score(a, b)
        mock_clip.assert_called_once_with(emb_a, emb_b)
        assert result == pytest.approx(0.92)

    def test_one_missing_clip_falls_through(self, make_metadata):
        """When one file lacks clip_embedding, falls through to other branches."""
        emb = tuple(float(i) * 0.01 for i in range(512))
        a = make_metadata(path="a.jpg", clip_embedding=emb)
        b = make_metadata(path="b.jpg")
        comp = ContentComparator()
        # Should return None since neither content_hash nor content_frames are set
        assert comp.score(a, b) is None

    def test_clip_preferred_over_content_hash(self, make_metadata):
        """When both have clip_embedding AND content_hash, CLIP is used."""
        from unittest.mock import patch

        emb = tuple(float(i) * 0.01 for i in range(512))
        a = make_metadata(path="a.jpg", clip_embedding=emb, content_hash=(0xABCD, 0, 0, 0))
        b = make_metadata(path="b.jpg", clip_embedding=emb, content_hash=(0xABCD, 0, 0, 0))
        comp = ContentComparator()
        with patch("duplicates_detector.clip.compare_clip_embeddings", return_value=0.88) as mock_clip:
            result = comp.score(a, b)
        mock_clip.assert_called_once()
        assert result == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# AudioComparator
# ---------------------------------------------------------------------------


class TestAudioComparator:
    def test_name_and_weight(self):
        from duplicates_detector.comparators import AudioComparator

        comp = AudioComparator()
        assert comp.name == "audio"
        assert comp.weight == 30.0

    def test_none_returns_none(self, make_metadata):
        from duplicates_detector.comparators import AudioComparator

        a = make_metadata(path="a.mp4")
        b = make_metadata(path="b.mp4")
        comp = AudioComparator()
        assert comp.score(a, b) is None

    def test_one_none_returns_none(self, make_metadata):
        from duplicates_detector.comparators import AudioComparator

        a = make_metadata(path="a.mp4", audio_fingerprint=(1, 2, 3))
        b = make_metadata(path="b.mp4")
        comp = AudioComparator()
        assert comp.score(a, b) is None

    def test_identical_score(self, make_metadata):
        from unittest.mock import patch

        from duplicates_detector.comparators import AudioComparator

        fp = tuple(range(20))
        a = make_metadata(path="a.mp4", audio_fingerprint=fp)
        b = make_metadata(path="b.mp4", audio_fingerprint=fp)
        comp = AudioComparator()
        with patch("duplicates_detector.audio.compare_audio_fingerprints", return_value=1.0) as mock:
            result = comp.score(a, b)
        mock.assert_called_once_with(fp, fp)
        assert result == 1.0


# ---------------------------------------------------------------------------
# Audio comparator factories and weights
# ---------------------------------------------------------------------------


class TestAudioComparatorFactories:
    def test_get_audio_comparators(self):
        from duplicates_detector.comparators import get_audio_comparators

        comps = get_audio_comparators()
        names = {c.name for c in comps}
        assert names == {"filename", "duration", "resolution", "file_size", "audio", "directory"}
        assert sum(c.weight for c in comps) == 100.0

    def test_get_audio_content_comparators(self):
        from duplicates_detector.comparators import get_audio_content_comparators

        comps = get_audio_content_comparators()
        names = {c.name for c in comps}
        assert names == {"filename", "duration", "resolution", "file_size", "audio", "content", "directory"}
        assert sum(c.weight for c in comps) == 100.0

    def test_get_weighted_audio_comparators(self):
        from duplicates_detector.comparators import get_weighted_audio_comparators

        weights = {
            "filename": 20.0,
            "duration": 20.0,
            "resolution": 10.0,
            "file_size": 10.0,
            "audio": 40.0,
        }
        comps = get_weighted_audio_comparators(weights)
        for c in comps:
            if c.name == "directory":
                assert c.weight == 0.0
            else:
                assert c.weight == weights[c.name]

    def test_get_weighted_audio_content_comparators(self):
        from duplicates_detector.comparators import get_weighted_audio_content_comparators

        weights = {
            "filename": 10.0,
            "duration": 10.0,
            "resolution": 10.0,
            "file_size": 10.0,
            "audio": 20.0,
            "content": 40.0,
        }
        comps = get_weighted_audio_content_comparators(weights)
        for c in comps:
            if c.name == "directory":
                assert c.weight == 0.0
            else:
                assert c.weight == weights[c.name]

    def test_audio_key_sets(self):
        from duplicates_detector.comparators import _AUDIO_DEFAULT_KEYS, _AUDIO_CONTENT_KEYS

        assert {"filename", "duration", "resolution", "filesize", "audio", "directory"} == _AUDIO_DEFAULT_KEYS
        assert {
            "filename",
            "duration",
            "resolution",
            "filesize",
            "audio",
            "content",
            "directory",
        } == _AUDIO_CONTENT_KEYS

    def test_parse_weights_with_audio(self):
        result = parse_weights("filename=20,duration=20,resolution=10,filesize=10,audio=40")
        assert result["audio"] == 40.0


# ---------------------------------------------------------------------------
# DirectoryComparator
# ---------------------------------------------------------------------------


class TestDirectoryComparator:
    def setup_method(self):
        from duplicates_detector.comparators import DirectoryComparator

        self.comp = DirectoryComparator()

    def test_name_and_weight(self):
        assert self.comp.name == "directory"
        assert self.comp.weight == 0.0

    def test_same_directory(self, make_metadata):
        """Files in the same directory → 1.0."""
        a = make_metadata(path="/videos/movie_a.mp4")
        b = make_metadata(path="/videos/movie_b.mp4")
        assert self.comp.score(a, b) == pytest.approx(1.0)

    def test_one_level_apart(self, make_metadata):
        """One directory level apart → 0.8."""
        a = make_metadata(path="/videos/movie_a.mp4")
        b = make_metadata(path="/videos/sub/movie_b.mp4")
        assert self.comp.score(a, b) == pytest.approx(0.8)

    def test_two_levels_apart(self, make_metadata):
        """Two directory levels apart → 0.6."""
        a = make_metadata(path="/videos/movie_a.mp4")
        b = make_metadata(path="/videos/sub1/sub2/movie_b.mp4")
        assert self.comp.score(a, b) == pytest.approx(0.6)

    def test_five_levels_apart(self, make_metadata):
        """Five+ directory levels apart → 0.0."""
        a = make_metadata(path="/videos/movie_a.mp4")
        b = make_metadata(path="/videos/a/b/c/d/e/movie_b.mp4")
        assert self.comp.score(a, b) == pytest.approx(0.0)

    def test_more_than_five_levels(self, make_metadata):
        """More than five levels apart → still 0.0 (clamped)."""
        a = make_metadata(path="/videos/movie_a.mp4")
        b = make_metadata(path="/videos/a/b/c/d/e/f/g/movie_b.mp4")
        assert self.comp.score(a, b) == pytest.approx(0.0)

    def test_deeply_nested_same_parent(self, make_metadata):
        """Deeply nested but same parent → 1.0."""
        a = make_metadata(path="/a/b/c/d/e/movie_a.mp4")
        b = make_metadata(path="/a/b/c/d/e/movie_b.mp4")
        assert self.comp.score(a, b) == pytest.approx(1.0)

    def test_cross_drive_returns_zero(self, make_metadata):
        """os.path.commonpath raises ValueError for different drives → 0.0."""
        from unittest.mock import patch

        a = make_metadata(path="/mnt/drive1/movie_a.mp4")
        b = make_metadata(path="/mnt/drive2/movie_b.mp4")
        with patch("os.path.commonpath", side_effect=ValueError("different drives")):
            assert self.comp.score(a, b) == 0.0

    def test_siblings_at_depth(self, make_metadata):
        """Sibling directories at depth → one level apart each side."""
        a = make_metadata(path="/root/left/movie_a.mp4")
        b = make_metadata(path="/root/right/movie_b.mp4")
        # common = /root, depth_a = 1, depth_b = 1, max_depth = 1
        assert self.comp.score(a, b) == pytest.approx(0.8)

    def test_returns_float_not_none(self, make_metadata):
        """DirectoryComparator always returns a float, never None."""
        a = make_metadata(path="/a/movie.mp4")
        b = make_metadata(path="/b/movie.mp4")
        result = self.comp.score(a, b)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# DirectoryComparator registration
# ---------------------------------------------------------------------------


class TestDirectoryComparatorRegistration:
    def test_directory_in_default_comparators_with_zero_weight(self):
        """DirectoryComparator is present in defaults with weight=0."""
        comps = get_default_comparators()
        dir_comp = [c for c in comps if c.name == "directory"]
        assert len(dir_comp) == 1
        assert dir_comp[0].weight == 0.0

    def test_parse_weights_directory(self):
        """parse_weights accepts 'directory' key."""
        w = parse_weights("directory=10")
        assert w == {"directory": 10.0}

    def test_directory_in_weight_key_map(self):
        from duplicates_detector.comparators import _WEIGHT_KEY_MAP

        assert "directory" in _WEIGHT_KEY_MAP
        assert _WEIGHT_KEY_MAP["directory"] == "directory"

    def test_directory_in_all_key_sets(self):
        from duplicates_detector.comparators import (
            _AUDIO_CONTENT_KEYS,
            _AUDIO_DEFAULT_KEYS,
            _AUDIO_MODE_DEFAULT_KEYS,
            _AUDIO_MODE_FINGERPRINT_KEYS,
            _CONTENT_KEYS,
            _DEFAULT_KEYS,
            _IMAGE_CONTENT_KEYS,
            _IMAGE_DEFAULT_KEYS,
        )

        for key_set in [
            _DEFAULT_KEYS,
            _CONTENT_KEYS,
            _IMAGE_DEFAULT_KEYS,
            _IMAGE_CONTENT_KEYS,
            _AUDIO_DEFAULT_KEYS,
            _AUDIO_CONTENT_KEYS,
            _AUDIO_MODE_DEFAULT_KEYS,
            _AUDIO_MODE_FINGERPRINT_KEYS,
        ]:
            assert "directory" in key_set

    def test_directory_in_all_factory_functions(self):
        """DirectoryComparator is returned by all 8 base factory functions."""
        from duplicates_detector.comparators import (
            get_audio_comparators,
            get_audio_content_comparators,
            get_audio_mode_comparators,
            get_audio_mode_fingerprint_comparators,
            get_image_comparators,
            get_image_content_comparators,
        )

        factories = [
            get_default_comparators,
            get_content_comparators,
            get_image_comparators,
            get_image_content_comparators,
            get_audio_comparators,
            get_audio_content_comparators,
            get_audio_mode_comparators,
            get_audio_mode_fingerprint_comparators,
        ]
        for factory in factories:
            comps = factory() if "rotation" not in factory.__name__ else factory()
            names = {c.name for c in comps}
            assert "directory" in names, f"directory missing from {factory.__name__}"


# ---------------------------------------------------------------------------
# Weight normalization with DirectoryComparator
# ---------------------------------------------------------------------------


class TestWeightNormalization:
    def test_directory_active_normalizes_to_100(self):
        """When directory weight > 0, total weights are normalized to 100."""
        weights = {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0, "directory": 10.0}
        comps = get_weighted_comparators(weights)
        total = sum(c.weight for c in comps)
        assert total == pytest.approx(100.0)

    def test_directory_active_preserves_ratios(self):
        """Normalization preserves relative ratios between comparators."""
        weights = {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0, "directory": 10.0}
        comps = get_weighted_comparators(weights)
        by_name = {c.name: c.weight for c in comps}
        # filename / duration ratio should be preserved (50/30 = 5/3)
        assert by_name["filename"] / by_name["duration"] == pytest.approx(50.0 / 30.0)

    def test_directory_zero_no_normalization(self):
        """When directory weight is 0, no normalization occurs."""
        weights = {"filename": 50.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}
        comps = get_weighted_comparators(weights)
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 50.0
        assert by_name["duration"] == 30.0
        assert by_name["resolution"] == 10.0
        assert by_name["file_size"] == 10.0
        assert by_name["directory"] == 0.0

    def test_without_directory_weights_unchanged(self):
        """Without directory in weights, existing weights are NOT normalized (no breaking change)."""
        weights = {"filename": 40.0, "duration": 40.0, "resolution": 10.0, "file_size": 10.0}
        comps = get_weighted_comparators(weights)
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 40.0
        assert by_name["duration"] == 40.0
        assert by_name["resolution"] == 10.0
        assert by_name["file_size"] == 10.0

    def test_default_comparators_sum_to_100(self):
        """Default comparators still sum to 100 (directory=0 does not break)."""
        comps = get_default_comparators()
        total = sum(c.weight for c in comps)
        assert total == pytest.approx(100.0)

    def test_content_comparators_sum_to_100(self):
        """Content comparators still sum to 100."""
        comps = get_content_comparators()
        total = sum(c.weight for c in comps)
        assert total == pytest.approx(100.0)

    def test_normalization_with_content_mode(self):
        """Directory active in content mode still normalizes to 100."""
        weights = {
            "filename": 20.0,
            "duration": 20.0,
            "resolution": 10.0,
            "file_size": 10.0,
            "content": 40.0,
            "directory": 10.0,
        }
        comps = get_weighted_content_comparators(weights)
        total = sum(c.weight for c in comps)
        assert total == pytest.approx(100.0)

    def test_normalization_with_image_mode(self):
        """Directory active in image mode normalizes to 100."""
        from duplicates_detector.comparators import get_weighted_image_comparators

        weights = {"filename": 25.0, "resolution": 20.0, "file_size": 15.0, "exif": 40.0, "directory": 10.0}
        comps = get_weighted_image_comparators(weights)
        total = sum(c.weight for c in comps)
        assert total == pytest.approx(100.0)

    def test_normalization_exact_100_no_change(self):
        """When weights already sum to 100 with directory active, no adjustment needed."""
        weights = {"filename": 40.0, "duration": 20.0, "resolution": 10.0, "file_size": 10.0, "directory": 20.0}
        comps = get_weighted_comparators(weights)
        by_name = {c.name: c.weight for c in comps}
        assert by_name["filename"] == 40.0
        assert by_name["directory"] == 20.0
        total = sum(c.weight for c in comps)
        assert total == pytest.approx(100.0)
