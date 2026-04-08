from __future__ import annotations

import pytest

from duplicates_detector.filters import (
    filter_metadata,
    format_bitrate_value,
    format_size,
    format_size_human,
    parse_bitrate,
    parse_resolution,
    parse_size,
)


# ---------------------------------------------------------------------------
# parse_size
# ---------------------------------------------------------------------------


class TestParseSize:
    @pytest.mark.parametrize(
        "input_str,expected",
        [
            ("1024", 1024),
            ("0", 0),
            ("100B", 100),
            ("1KB", 1024),
            ("1MB", 1_048_576),
            ("1GB", 1_073_741_824),
            ("1TB", 1_099_511_627_776),
        ],
    )
    def test_basic_units(self, input_str, expected):
        assert parse_size(input_str) == expected

    @pytest.mark.parametrize(
        "input_str,expected",
        [
            ("1.5KB", 1536),
            ("1.5MB", 1_572_864),
            ("0.5GB", 536_870_912),
            ("2.5TB", 2_748_779_069_440),
        ],
    )
    def test_decimals(self, input_str, expected):
        assert parse_size(input_str) == expected

    @pytest.mark.parametrize("input_str", ["10mb", "10MB", "10Mb", "10mB"])
    def test_case_insensitive(self, input_str):
        assert parse_size(input_str) == 10 * 1024**2

    def test_whitespace_between_number_and_unit(self):
        assert parse_size("10 MB") == 10 * 1024**2

    def test_leading_trailing_whitespace(self):
        assert parse_size("  10MB  ") == 10 * 1024**2

    @pytest.mark.parametrize(
        "bad_input",
        [
            "",
            "MB",
            "abc",
            "10XB",
            "-5MB",
            "10 20",
            "10 MB GB",
        ],
    )
    def test_invalid_raises_value_error(self, bad_input):
        with pytest.raises(ValueError):
            parse_size(bad_input)


# ---------------------------------------------------------------------------
# format_size
# ---------------------------------------------------------------------------


class TestFormatSize:
    def test_bytes(self):
        """Small values use B."""
        assert format_size(500) == "500B"

    def test_kilobytes(self):
        """1024 → '1KB'."""
        assert format_size(1024) == "1KB"

    def test_megabytes(self):
        """1048576 → '1MB'."""
        assert format_size(1_048_576) == "1MB"

    def test_gigabytes(self):
        """1073741824 → '1GB'."""
        assert format_size(1_073_741_824) == "1GB"

    def test_terabytes(self):
        """1099511627776 → '1TB'."""
        assert format_size(1_099_511_627_776) == "1TB"

    def test_non_even_falls_to_bytes(self):
        """Values that don't divide evenly into any unit use bytes."""
        # 1023 doesn't divide into KB/MB/GB/TB but does into B
        assert format_size(1023) == "1023B"

    def test_zero(self):
        """0 → '0B'."""
        assert format_size(0) == "0B"

    def test_10_megabytes(self):
        """10485760 → '10MB'."""
        assert format_size(10 * 1024**2) == "10MB"

    def test_round_trip(self):
        """format_size(parse_size(s)) == s for clean values."""
        for s in ["1KB", "10MB", "4GB", "2TB", "500B"]:
            assert format_size(parse_size(s)) == s


# ---------------------------------------------------------------------------
# format_size_human
# ---------------------------------------------------------------------------


class TestFormatSizeHuman:
    def test_bytes(self):
        assert format_size_human(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_size_human(2048) == "2.0 KB"

    def test_megabytes(self):
        assert format_size_human(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert format_size_human(3 * 1024**3) == "3.0 GB"

    def test_zero(self):
        assert format_size_human(0) == "0.0 B"

    def test_non_even_division(self):
        """Non-even sizes display with one decimal place."""
        assert format_size_human(1500) == "1.5 KB"

    def test_large_value(self):
        """Petabyte-scale values use PB."""
        assert format_size_human(2 * 1024**5) == "2.0 PB"


# ---------------------------------------------------------------------------
# filter_metadata
# ---------------------------------------------------------------------------


class TestFilterMetadata:
    def test_min_size_only(self, make_metadata):
        items = [
            make_metadata("small.mp4", file_size=500),
            make_metadata("big.mp4", file_size=2000),
        ]
        result = filter_metadata(items, min_size=1000)
        assert len(result) == 1
        assert result[0].filename == "big"

    def test_max_size_only(self, make_metadata):
        items = [
            make_metadata("small.mp4", file_size=500),
            make_metadata("big.mp4", file_size=2000),
        ]
        result = filter_metadata(items, max_size=1000)
        assert len(result) == 1
        assert result[0].filename == "small"

    def test_min_and_max_size(self, make_metadata):
        items = [
            make_metadata("a.mp4", file_size=100),
            make_metadata("b.mp4", file_size=500),
            make_metadata("c.mp4", file_size=2000),
        ]
        result = filter_metadata(items, min_size=200, max_size=1000)
        assert len(result) == 1
        assert result[0].filename == "b"

    def test_min_duration_only(self, make_metadata):
        items = [
            make_metadata("short.mp4", duration=10.0),
            make_metadata("long.mp4", duration=120.0),
        ]
        result = filter_metadata(items, min_duration=60.0)
        assert len(result) == 1
        assert result[0].filename == "long"

    def test_max_duration_only(self, make_metadata):
        items = [
            make_metadata("short.mp4", duration=10.0),
            make_metadata("long.mp4", duration=120.0),
        ]
        result = filter_metadata(items, max_duration=60.0)
        assert len(result) == 1
        assert result[0].filename == "short"

    def test_min_and_max_duration(self, make_metadata):
        items = [
            make_metadata("a.mp4", duration=10.0),
            make_metadata("b.mp4", duration=90.0),
            make_metadata("c.mp4", duration=200.0),
        ]
        result = filter_metadata(items, min_duration=30.0, max_duration=150.0)
        assert len(result) == 1
        assert result[0].filename == "b"

    def test_none_duration_passes_min_filter(self, make_metadata):
        items = [
            make_metadata("known.mp4", duration=5.0),
            make_metadata("unknown.mp4", duration=None),
        ]
        result = filter_metadata(items, min_duration=10.0)
        assert len(result) == 1
        assert result[0].filename == "unknown"

    def test_none_duration_passes_max_filter(self, make_metadata):
        items = [
            make_metadata("known.mp4", duration=200.0),
            make_metadata("unknown.mp4", duration=None),
        ]
        result = filter_metadata(items, max_duration=100.0)
        assert len(result) == 1
        assert result[0].filename == "unknown"

    def test_exact_boundary_inclusive(self, make_metadata):
        items = [make_metadata("exact.mp4", file_size=1000, duration=60.0)]
        result = filter_metadata(
            items,
            min_size=1000,
            max_size=1000,
            min_duration=60.0,
            max_duration=60.0,
        )
        assert len(result) == 1

    def test_no_filters_returns_all(self, make_metadata):
        items = [make_metadata("a.mp4"), make_metadata("b.mp4")]
        result = filter_metadata(items)
        assert len(result) == 2

    def test_all_filters_combined(self, make_metadata):
        items = [
            make_metadata("a.mp4", file_size=500, duration=30.0),
            make_metadata("b.mp4", file_size=1500, duration=90.0),
            make_metadata("c.mp4", file_size=1500, duration=30.0),
            make_metadata("d.mp4", file_size=500, duration=90.0),
        ]
        result = filter_metadata(
            items,
            min_size=1000,
            max_size=2000,
            min_duration=60.0,
            max_duration=120.0,
        )
        assert len(result) == 1
        assert result[0].filename == "b"

    def test_empty_list(self):
        assert filter_metadata([], min_size=100) == []

    def test_min_resolution(self, make_metadata):
        items = [
            make_metadata("low.mp4", width=640, height=480),
            make_metadata("high.mp4", width=1920, height=1080),
        ]
        result = filter_metadata(items, min_resolution=(1280, 720))
        assert len(result) == 1
        assert result[0].filename == "high"

    def test_max_resolution(self, make_metadata):
        items = [
            make_metadata("low.mp4", width=640, height=480),
            make_metadata("high.mp4", width=1920, height=1080),
        ]
        result = filter_metadata(items, max_resolution=(1280, 720))
        assert len(result) == 1
        assert result[0].filename == "low"

    def test_none_resolution_passes_min_filter(self, make_metadata):
        items = [
            make_metadata("known.mp4", width=640, height=480),
            make_metadata("unknown.mp4", width=None, height=None),
        ]
        result = filter_metadata(items, min_resolution=(1920, 1080))
        assert len(result) == 1
        assert result[0].filename == "unknown"

    def test_none_resolution_passes_max_filter(self, make_metadata):
        items = [
            make_metadata("known.mp4", width=3840, height=2160),
            make_metadata("unknown.mp4", width=None, height=None),
        ]
        result = filter_metadata(items, max_resolution=(1920, 1080))
        assert len(result) == 1
        assert result[0].filename == "unknown"

    def test_resolution_uses_pixel_count(self, make_metadata):
        """A 1080x854 file (922,320 pixels) passes --min-resolution 1280x720 (921,600 pixels)."""
        items = [make_metadata("odd.mp4", width=1080, height=854)]
        result = filter_metadata(items, min_resolution=(1280, 720))
        assert len(result) == 1

    def test_min_bitrate(self, make_metadata):
        items = [
            make_metadata("low.mp4", bitrate=1_000_000),
            make_metadata("high.mp4", bitrate=10_000_000),
        ]
        result = filter_metadata(items, min_bitrate=5_000_000)
        assert len(result) == 1
        assert result[0].filename == "high"

    def test_max_bitrate(self, make_metadata):
        items = [
            make_metadata("low.mp4", bitrate=1_000_000),
            make_metadata("high.mp4", bitrate=10_000_000),
        ]
        result = filter_metadata(items, max_bitrate=5_000_000)
        assert len(result) == 1
        assert result[0].filename == "low"

    def test_none_bitrate_passes_filter(self, make_metadata):
        items = [
            make_metadata("known.mp4", bitrate=500_000),
            make_metadata("unknown.mp4", bitrate=None),
        ]
        result = filter_metadata(items, min_bitrate=1_000_000)
        assert len(result) == 1
        assert result[0].filename == "unknown"

    def test_codecs_filter(self, make_metadata):
        items = [
            make_metadata("a.mp4", codec="h264"),
            make_metadata("b.mp4", codec="hevc"),
            make_metadata("c.mp4", codec="av1"),
        ]
        result = filter_metadata(items, codecs=frozenset({"h264", "hevc"}))
        assert len(result) == 2
        assert {r.filename for r in result} == {"a", "b"}

    def test_codecs_case_insensitive(self, make_metadata):
        items = [make_metadata("a.mp4", codec="H264")]
        result = filter_metadata(items, codecs=frozenset({"h264"}))
        assert len(result) == 1

    def test_none_codec_passes_filter(self, make_metadata):
        items = [
            make_metadata("known.mp4", codec="vp9"),
            make_metadata("unknown.mp4", codec=None),
        ]
        result = filter_metadata(items, codecs=frozenset({"h264"}))
        assert len(result) == 1
        assert result[0].filename == "unknown"

    def test_combined_resolution_bitrate_codec(self, make_metadata):
        items = [
            make_metadata("a.mp4", width=1920, height=1080, bitrate=5_000_000, codec="h264"),
            make_metadata("b.mp4", width=640, height=480, bitrate=5_000_000, codec="h264"),
            make_metadata("c.mp4", width=1920, height=1080, bitrate=500_000, codec="h264"),
            make_metadata("d.mp4", width=1920, height=1080, bitrate=5_000_000, codec="vp9"),
        ]
        result = filter_metadata(
            items,
            min_resolution=(1280, 720),
            min_bitrate=1_000_000,
            codecs=frozenset({"h264"}),
        )
        assert len(result) == 1
        assert result[0].filename == "a"


# ---------------------------------------------------------------------------
# parse_resolution
# ---------------------------------------------------------------------------


class TestParseResolution:
    @pytest.mark.parametrize(
        "input_str,expected",
        [
            ("1920x1080", (1920, 1080)),
            ("1280X720", (1280, 720)),
            ("3840x2160", (3840, 2160)),
            ("640x480", (640, 480)),
        ],
    )
    def test_valid_formats(self, input_str, expected):
        assert parse_resolution(input_str) == expected

    def test_whitespace_handling(self):
        assert parse_resolution("  1920 x 1080  ") == (1920, 1080)

    @pytest.mark.parametrize(
        "bad_input",
        [
            "1920",
            "x1080",
            "1920x",
            "abc",
            "",
            "1920*1080",
            "1920 1080",
        ],
    )
    def test_invalid_raises_value_error(self, bad_input):
        with pytest.raises(ValueError):
            parse_resolution(bad_input)


# ---------------------------------------------------------------------------
# parse_bitrate
# ---------------------------------------------------------------------------


class TestParseBitrate:
    def test_raw_bps(self):
        assert parse_bitrate("5000000") == 5_000_000

    def test_kbps(self):
        assert parse_bitrate("5000kbps") == 5_000_000

    def test_mbps(self):
        assert parse_bitrate("5Mbps") == 5_000_000

    def test_gbps(self):
        assert parse_bitrate("1Gbps") == 1_000_000_000

    def test_case_insensitive(self):
        assert parse_bitrate("5MBPS") == 5_000_000
        assert parse_bitrate("5mbps") == 5_000_000

    def test_decimal(self):
        assert parse_bitrate("1.5Mbps") == 1_500_000

    def test_whitespace(self):
        assert parse_bitrate("  5 Mbps  ") == 5_000_000

    def test_bps_suffix(self):
        assert parse_bitrate("1000bps") == 1000

    @pytest.mark.parametrize("bad_input", ["abc", "", "Mbps", "-5Mbps"])
    def test_invalid_raises_value_error(self, bad_input):
        with pytest.raises(ValueError):
            parse_bitrate(bad_input)


# ---------------------------------------------------------------------------
# format_bitrate_value
# ---------------------------------------------------------------------------


class TestFormatBitrateValue:
    def test_gbps(self):
        assert format_bitrate_value(1_000_000_000) == "1Gbps"

    def test_mbps(self):
        assert format_bitrate_value(5_000_000) == "5Mbps"

    def test_kbps(self):
        assert format_bitrate_value(5_000) == "5kbps"

    def test_bps(self):
        assert format_bitrate_value(1500) == "1500bps"

    def test_zero(self):
        assert format_bitrate_value(0) == "0bps"

    def test_round_trip(self):
        for v in [1_000_000, 5_000_000, 500_000, 1_000_000_000, 1500]:
            assert parse_bitrate(format_bitrate_value(v)) == v
