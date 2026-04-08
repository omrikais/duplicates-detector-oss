from __future__ import annotations

from pathlib import Path

import pytest

from duplicates_detector.metadata import VideoMetadata
from duplicates_detector.scorer import ScoredPair
from duplicates_detector.keeper import (
    pick_keep,
    pick_delete,
    pick_keep_from_group,
    pick_deletes_from_group,
    STRATEGIES,
)


def _meta(
    name: str = "a.mp4",
    file_size: int = 1_000_000,
    duration: float | None = 120.0,
    width: int | None = 1920,
    height: int | None = 1080,
    mtime: float | None = 1_700_000_000.0,
    sidecars: tuple[Path, ...] | None = None,
) -> VideoMetadata:
    return VideoMetadata(
        path=Path(f"/videos/{name}"),
        filename=Path(name).stem,
        duration=duration,
        width=width,
        height=height,
        file_size=file_size,
        mtime=mtime,
        sidecars=sidecars,
    )


def _pair(a: VideoMetadata, b: VideoMetadata, score: float = 80.0) -> ScoredPair:
    return ScoredPair(
        file_a=a,
        file_b=b,
        total_score=score,
        breakdown={"filename": 30.0, "duration": 35.0},
        detail={},
    )


# ---------------------------------------------------------------------------
# STRATEGIES tuple
# ---------------------------------------------------------------------------


class TestStrategies:
    def test_contains_all_seven(self):
        assert set(STRATEGIES) == {
            "newest",
            "oldest",
            "biggest",
            "smallest",
            "longest",
            "highest-res",
            "edited",
        }

    def test_is_tuple(self):
        assert isinstance(STRATEGIES, tuple)


# ---------------------------------------------------------------------------
# pick_keep — biggest / smallest
# ---------------------------------------------------------------------------


class TestBiggest:
    def test_picks_larger_file(self):
        p = _pair(_meta(file_size=2_000_000), _meta(name="b.mp4", file_size=1_000_000))
        assert pick_keep(p, "biggest") == "a"

    def test_picks_b_when_b_is_larger(self):
        p = _pair(_meta(file_size=1_000_000), _meta(name="b.mp4", file_size=2_000_000))
        assert pick_keep(p, "biggest") == "b"

    def test_equal_sizes_returns_none(self):
        p = _pair(_meta(file_size=1_000_000), _meta(name="b.mp4", file_size=1_000_000))
        assert pick_keep(p, "biggest") is None


class TestSmallest:
    def test_picks_smaller_file(self):
        p = _pair(_meta(file_size=500_000), _meta(name="b.mp4", file_size=1_000_000))
        assert pick_keep(p, "smallest") == "a"

    def test_picks_b_when_b_is_smaller(self):
        p = _pair(_meta(file_size=1_000_000), _meta(name="b.mp4", file_size=500_000))
        assert pick_keep(p, "smallest") == "b"

    def test_equal_sizes_returns_none(self):
        p = _pair(_meta(file_size=1_000_000), _meta(name="b.mp4", file_size=1_000_000))
        assert pick_keep(p, "smallest") is None


# ---------------------------------------------------------------------------
# pick_keep — newest / oldest
# ---------------------------------------------------------------------------


class TestNewest:
    def test_picks_higher_mtime(self):
        p = _pair(
            _meta(mtime=1_700_000_000.0),
            _meta(name="b.mp4", mtime=1_700_001_000.0),
        )
        assert pick_keep(p, "newest") == "b"

    def test_picks_a_when_a_is_newer(self):
        p = _pair(
            _meta(mtime=1_700_001_000.0),
            _meta(name="b.mp4", mtime=1_700_000_000.0),
        )
        assert pick_keep(p, "newest") == "a"

    def test_both_none_returns_none(self):
        p = _pair(_meta(mtime=None), _meta(name="b.mp4", mtime=None))
        assert pick_keep(p, "newest") is None

    def test_one_none_picks_other(self):
        p = _pair(_meta(mtime=1_700_000_000.0), _meta(name="b.mp4", mtime=None))
        assert pick_keep(p, "newest") == "a"

    def test_tie_falls_back_to_file_size(self):
        p = _pair(
            _meta(mtime=1_700_000_000.0, file_size=2_000_000),
            _meta(name="b.mp4", mtime=1_700_000_000.0, file_size=1_000_000),
        )
        assert pick_keep(p, "newest") == "a"

    def test_exact_tie_returns_none(self):
        p = _pair(
            _meta(mtime=1_700_000_000.0, file_size=1_000_000),
            _meta(name="b.mp4", mtime=1_700_000_000.0, file_size=1_000_000),
        )
        assert pick_keep(p, "newest") is None


class TestOldest:
    def test_picks_lower_mtime(self):
        p = _pair(
            _meta(mtime=1_700_000_000.0),
            _meta(name="b.mp4", mtime=1_700_001_000.0),
        )
        assert pick_keep(p, "oldest") == "a"

    def test_picks_b_when_b_is_older(self):
        p = _pair(
            _meta(mtime=1_700_001_000.0),
            _meta(name="b.mp4", mtime=1_700_000_000.0),
        )
        assert pick_keep(p, "oldest") == "b"

    def test_both_none_returns_none(self):
        p = _pair(_meta(mtime=None), _meta(name="b.mp4", mtime=None))
        assert pick_keep(p, "oldest") is None

    def test_one_none_picks_other(self):
        p = _pair(_meta(mtime=None), _meta(name="b.mp4", mtime=1_700_000_000.0))
        assert pick_keep(p, "oldest") == "b"

    def test_tie_falls_back_to_file_size(self):
        p = _pair(
            _meta(mtime=1_700_000_000.0, file_size=1_000_000),
            _meta(name="b.mp4", mtime=1_700_000_000.0, file_size=2_000_000),
        )
        assert pick_keep(p, "oldest") == "b"


# ---------------------------------------------------------------------------
# pick_keep — longest
# ---------------------------------------------------------------------------


class TestLongest:
    def test_picks_longer_duration(self):
        p = _pair(_meta(duration=120.0), _meta(name="b.mp4", duration=90.0))
        assert pick_keep(p, "longest") == "a"

    def test_picks_b_when_b_is_longer(self):
        p = _pair(_meta(duration=90.0), _meta(name="b.mp4", duration=120.0))
        assert pick_keep(p, "longest") == "b"

    def test_both_none_returns_none(self):
        p = _pair(_meta(duration=None), _meta(name="b.mp4", duration=None))
        assert pick_keep(p, "longest") is None

    def test_one_none_picks_other(self):
        p = _pair(_meta(duration=120.0), _meta(name="b.mp4", duration=None))
        assert pick_keep(p, "longest") == "a"

    def test_tie_falls_back_to_file_size(self):
        p = _pair(
            _meta(duration=120.0, file_size=2_000_000),
            _meta(name="b.mp4", duration=120.0, file_size=1_000_000),
        )
        assert pick_keep(p, "longest") == "a"

    def test_exact_tie_returns_none(self):
        p = _pair(
            _meta(duration=120.0, file_size=1_000_000),
            _meta(name="b.mp4", duration=120.0, file_size=1_000_000),
        )
        assert pick_keep(p, "longest") is None


# ---------------------------------------------------------------------------
# pick_keep — highest-res
# ---------------------------------------------------------------------------


class TestHighestRes:
    def test_picks_more_pixels(self):
        p = _pair(
            _meta(width=1920, height=1080),  # 2,073,600
            _meta(name="b.mp4", width=1280, height=720),  # 921,600
        )
        assert pick_keep(p, "highest-res") == "a"

    def test_picks_b_when_b_has_more_pixels(self):
        p = _pair(
            _meta(width=1280, height=720),
            _meta(name="b.mp4", width=3840, height=2160),
        )
        assert pick_keep(p, "highest-res") == "b"

    def test_both_none_returns_none(self):
        p = _pair(
            _meta(width=None, height=None),
            _meta(name="b.mp4", width=None, height=None),
        )
        assert pick_keep(p, "highest-res") is None

    def test_one_none_picks_other(self):
        p = _pair(
            _meta(width=1920, height=1080),
            _meta(name="b.mp4", width=None, height=None),
        )
        assert pick_keep(p, "highest-res") == "a"

    def test_one_none_b_has_value(self):
        p = _pair(
            _meta(width=None, height=None),
            _meta(name="b.mp4", width=1280, height=720),
        )
        assert pick_keep(p, "highest-res") == "b"

    def test_tie_falls_back_to_file_size(self):
        p = _pair(
            _meta(width=1920, height=1080, file_size=2_000_000),
            _meta(name="b.mp4", width=1920, height=1080, file_size=1_000_000),
        )
        assert pick_keep(p, "highest-res") == "a"

    def test_exact_tie_returns_none(self):
        p = _pair(
            _meta(width=1920, height=1080, file_size=1_000_000),
            _meta(name="b.mp4", width=1920, height=1080, file_size=1_000_000),
        )
        assert pick_keep(p, "highest-res") is None

    def test_partial_none_width(self):
        """If only width is None, treat as no resolution data."""
        p = _pair(
            _meta(width=None, height=1080),
            _meta(name="b.mp4", width=1920, height=1080),
        )
        assert pick_keep(p, "highest-res") == "b"


# ---------------------------------------------------------------------------
# pick_delete
# ---------------------------------------------------------------------------


class TestPickDelete:
    def test_returns_opposite_of_pick_keep(self):
        p = _pair(_meta(file_size=2_000_000), _meta(name="b.mp4", file_size=1_000_000))
        assert pick_keep(p, "biggest") == "a"
        assert pick_delete(p, "biggest") == "b"

    def test_returns_b_when_pick_keep_is_a(self):
        p = _pair(_meta(duration=120.0), _meta(name="b.mp4", duration=90.0))
        assert pick_delete(p, "longest") == "b"

    def test_returns_a_when_pick_keep_is_b(self):
        p = _pair(_meta(duration=90.0), _meta(name="b.mp4", duration=120.0))
        assert pick_delete(p, "longest") == "a"

    def test_none_when_undecidable(self):
        p = _pair(_meta(file_size=1_000_000), _meta(name="b.mp4", file_size=1_000_000))
        assert pick_delete(p, "biggest") is None


# ---------------------------------------------------------------------------
# Invalid strategy
# ---------------------------------------------------------------------------


class TestInvalidStrategy:
    def test_pick_keep_raises_on_unknown(self):
        p = _pair(_meta(), _meta(name="b.mp4"))
        with pytest.raises(ValueError, match="Unknown strategy"):
            pick_keep(p, "random")

    def test_pick_delete_raises_on_unknown(self):
        p = _pair(_meta(), _meta(name="b.mp4"))
        with pytest.raises(ValueError, match="Unknown strategy"):
            pick_delete(p, "random")


# ---------------------------------------------------------------------------
# pick_keep_from_group — N-member selection
# ---------------------------------------------------------------------------


class TestPickKeepFromGroup:
    def test_biggest_picks_largest(self):
        members = [
            _meta("a.mp4", file_size=1_000_000),
            _meta("b.mp4", file_size=3_000_000),
            _meta("c.mp4", file_size=2_000_000),
        ]
        result = pick_keep_from_group(members, "biggest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_smallest_picks_smallest(self):
        members = [
            _meta("a.mp4", file_size=3_000_000),
            _meta("b.mp4", file_size=1_000_000),
            _meta("c.mp4", file_size=2_000_000),
        ]
        result = pick_keep_from_group(members, "smallest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_newest_picks_most_recent(self):
        members = [
            _meta("a.mp4", mtime=1_700_000_000.0),
            _meta("b.mp4", mtime=1_700_002_000.0),
            _meta("c.mp4", mtime=1_700_001_000.0),
        ]
        result = pick_keep_from_group(members, "newest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_oldest_picks_least_recent(self):
        members = [
            _meta("a.mp4", mtime=1_700_001_000.0),
            _meta("b.mp4", mtime=1_700_000_000.0),
            _meta("c.mp4", mtime=1_700_002_000.0),
        ]
        result = pick_keep_from_group(members, "oldest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_longest_picks_longest_duration(self):
        members = [
            _meta("a.mp4", duration=60.0),
            _meta("b.mp4", duration=180.0),
            _meta("c.mp4", duration=120.0),
        ]
        result = pick_keep_from_group(members, "longest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_highest_res_picks_most_pixels(self):
        members = [
            _meta("a.mp4", width=1280, height=720),
            _meta("b.mp4", width=3840, height=2160),
            _meta("c.mp4", width=1920, height=1080),
        ]
        result = pick_keep_from_group(members, "highest-res")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_all_none_returns_none(self):
        members = [
            _meta("a.mp4", mtime=None),
            _meta("b.mp4", mtime=None),
        ]
        assert pick_keep_from_group(members, "newest") is None

    def test_one_none_excluded(self):
        members = [
            _meta("a.mp4", duration=None),
            _meta("b.mp4", duration=120.0),
            _meta("c.mp4", duration=60.0),
        ]
        result = pick_keep_from_group(members, "longest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_tie_falls_back_to_file_size(self):
        members = [
            _meta("a.mp4", duration=120.0, file_size=1_000_000),
            _meta("b.mp4", duration=120.0, file_size=3_000_000),
            _meta("c.mp4", duration=120.0, file_size=2_000_000),
        ]
        result = pick_keep_from_group(members, "longest")
        assert result is not None
        assert result.path == Path("/videos/b.mp4")

    def test_exact_tie_returns_none(self):
        members = [
            _meta("a.mp4", file_size=1_000_000),
            _meta("b.mp4", file_size=1_000_000),
        ]
        assert pick_keep_from_group(members, "biggest") is None

    def test_single_member(self):
        members = [_meta("a.mp4", file_size=1_000_000)]
        result = pick_keep_from_group(members, "biggest")
        assert result is not None
        assert result.path == Path("/videos/a.mp4")

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            pick_keep_from_group([_meta()], "random")


# ---------------------------------------------------------------------------
# pick_deletes_from_group
# ---------------------------------------------------------------------------


class TestPickDeletesFromGroup:
    def test_returns_all_except_keeper(self):
        members = [
            _meta("a.mp4", file_size=3_000_000),
            _meta("b.mp4", file_size=1_000_000),
            _meta("c.mp4", file_size=2_000_000),
        ]
        deletes = pick_deletes_from_group(members, "biggest")
        delete_paths = {m.path for m in deletes}
        assert Path("/videos/b.mp4") in delete_paths
        assert Path("/videos/c.mp4") in delete_paths
        assert Path("/videos/a.mp4") not in delete_paths

    def test_empty_when_undecidable(self):
        members = [
            _meta("a.mp4", file_size=1_000_000),
            _meta("b.mp4", file_size=1_000_000),
        ]
        assert pick_deletes_from_group(members, "biggest") == []

    def test_single_member_empty_list(self):
        members = [_meta("a.mp4")]
        deletes = pick_deletes_from_group(members, "biggest")
        assert deletes == []


# ---------------------------------------------------------------------------
# pick_keep — longest with None duration (image mode)
# ---------------------------------------------------------------------------


class TestPickKeepLongestNoDuration:
    def test_both_none_returns_none(self):
        a = _meta("a.png", duration=None)
        b = _meta("b.png", duration=None)
        pair = _pair(a, b, score=80.0)
        result = pick_keep(pair, "longest")
        assert result is None


# ---------------------------------------------------------------------------
# pick_keep — edited strategy
# ---------------------------------------------------------------------------


class TestEdited:
    def test_picks_file_with_sidecars(self):
        a = _meta("a.jpg", sidecars=(Path("/videos/a.xmp"),))
        b = _meta("b.jpg")
        p = _pair(a, b)
        assert pick_keep(p, "edited") == "a"

    def test_picks_file_with_more_sidecars(self):
        a = _meta("a.jpg", sidecars=(Path("/videos/a.xmp"),))
        b = _meta("b.jpg", sidecars=(Path("/videos/b.xmp"), Path("/videos/b.aae")))
        p = _pair(a, b)
        assert pick_keep(p, "edited") == "b"

    def test_equal_sidecars_falls_back_to_newest(self):
        a = _meta("a.jpg", mtime=1_700_001_000.0, sidecars=(Path("/videos/a.xmp"),))
        b = _meta("b.jpg", mtime=1_700_000_000.0, sidecars=(Path("/videos/b.xmp"),))
        p = _pair(a, b)
        assert pick_keep(p, "edited") == "a"

    def test_no_sidecars_falls_back_to_newest(self):
        a = _meta("a.jpg", mtime=1_700_000_000.0)
        b = _meta("b.jpg", mtime=1_700_001_000.0)
        p = _pair(a, b)
        assert pick_keep(p, "edited") == "b"


# ---------------------------------------------------------------------------
# Sidecar tie-breaker in _compare (cross-strategy)
# ---------------------------------------------------------------------------


class TestSidecarTieBreaker:
    def test_newest_tie_on_size_prefers_sidecars(self):
        """When newest ties on mtime AND file_size, prefer more sidecars."""
        a = _meta("a.mp4", mtime=1_700_000_000.0, file_size=1_000_000, sidecars=(Path("/x/a.xmp"),))
        b = _meta("b.mp4", mtime=1_700_000_000.0, file_size=1_000_000)
        p = _pair(a, b)
        assert pick_keep(p, "newest") == "a"

    def test_oldest_tie_on_size_prefers_sidecars(self):
        a = _meta("a.mp4", mtime=1_700_000_000.0, file_size=1_000_000)
        b = _meta("b.mp4", mtime=1_700_000_000.0, file_size=1_000_000, sidecars=(Path("/x/b.xmp"),))
        p = _pair(a, b)
        assert pick_keep(p, "oldest") == "b"


# ---------------------------------------------------------------------------
# Group-level edited strategy
# ---------------------------------------------------------------------------


class TestPickKeepFromGroupEdited:
    def test_picks_member_with_most_sidecars(self):
        members = [
            _meta("a.jpg", sidecars=None),
            _meta("b.jpg", sidecars=(Path("/x/b.xmp"), Path("/x/b.aae"))),
            _meta("c.jpg", sidecars=(Path("/x/c.xmp"),)),
        ]
        result = pick_keep_from_group(members, "edited")
        assert result is not None
        assert result.path == Path("/videos/b.jpg")

    def test_all_no_sidecars_ties_on_file_size(self):
        members = [
            _meta("a.jpg", file_size=2_000_000),
            _meta("b.jpg", file_size=1_000_000),
        ]
        result = pick_keep_from_group(members, "edited")
        # All have 0 sidecars, so tied on primary; file_size breaks tie
        assert result is not None
        assert result.path == Path("/videos/a.jpg")

    def test_tied_sidecars_falls_back_to_file_size(self):
        members = [
            _meta("a.jpg", file_size=1_000_000, sidecars=(Path("/x/a.xmp"),)),
            _meta("b.jpg", file_size=3_000_000, sidecars=(Path("/x/b.xmp"),)),
        ]
        result = pick_keep_from_group(members, "edited")
        assert result is not None
        assert result.path == Path("/videos/b.jpg")

    def test_tied_sidecars_and_size_returns_none(self):
        members = [
            _meta("a.jpg", file_size=1_000_000, sidecars=(Path("/x/a.xmp"),)),
            _meta("b.jpg", file_size=1_000_000, sidecars=(Path("/x/b.xmp"),)),
        ]
        result = pick_keep_from_group(members, "edited")
        assert result is None
