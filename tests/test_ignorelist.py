from __future__ import annotations

import json
from pathlib import Path

import pytest

from duplicates_detector.ignorelist import IgnoreList, get_default_ignore_path


class TestGetDefaultIgnorePath:
    def test_uses_xdg_data_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        path = get_default_ignore_path()
        assert path == tmp_path / "duplicates-detector" / "ignored-pairs.json"

    def test_fallback_to_local_share(self, monkeypatch):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        path = get_default_ignore_path()
        assert "duplicates-detector" in str(path)
        assert "ignored-pairs.json" in str(path)
        assert ".local/share" in str(path)


class TestIgnoreList:
    def test_add_and_contains(self, tmp_path):
        il = IgnoreList(tmp_path / "ignored.json")
        a, b = Path("/video/a.mp4"), Path("/video/b.mp4")
        assert not il.contains(a, b)
        il.add(a, b)
        assert il.contains(a, b)

    def test_order_independent(self, tmp_path):
        il = IgnoreList(tmp_path / "ignored.json")
        a, b = Path("/video/a.mp4"), Path("/video/b.mp4")
        il.add(a, b)
        assert il.contains(b, a)

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "ignored.json"
        il = IgnoreList(path)
        a, b = Path("/video/a.mp4"), Path("/video/b.mp4")
        il.add(a, b)
        il.save()

        il2 = IgnoreList(path)
        assert il2.contains(a, b)
        assert len(il2) == 1

    def test_clear(self, tmp_path):
        il = IgnoreList(tmp_path / "ignored.json")
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        assert len(il) == 1
        il.clear()
        assert len(il) == 0

    def test_missing_file_starts_empty(self, tmp_path):
        il = IgnoreList(tmp_path / "nonexistent.json")
        assert len(il) == 0

    def test_corrupt_file_starts_empty(self, tmp_path):
        path = tmp_path / "ignored.json"
        path.write_text("not valid json {{{")
        il = IgnoreList(path)
        assert len(il) == 0

    def test_non_string_entries_ignored(self, tmp_path):
        """Entries with non-string values degrade gracefully."""
        path = tmp_path / "ignored.json"
        path.write_text(json.dumps([[1, 2]]))
        il = IgnoreList(path)
        assert len(il) == 0

    def test_load_canonicalizes_reversed_entries(self, tmp_path):
        """Hand-edited JSON with reversed pair order should still match."""
        path = tmp_path / "ignored.json"
        # Write entries in reverse lexicographic order
        path.write_text(json.dumps([["/video/z.mp4", "/video/a.mp4"]]))
        il = IgnoreList(path)
        assert len(il) == 1
        assert il.contains(Path("/video/a.mp4"), Path("/video/z.mp4"))
        assert il.contains(Path("/video/z.mp4"), Path("/video/a.mp4"))

    def test_len(self, tmp_path):
        il = IgnoreList(tmp_path / "ignored.json")
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        il.add(Path("/c.mp4"), Path("/d.mp4"))
        assert len(il) == 2

    def test_duplicate_add_no_effect(self, tmp_path):
        il = IgnoreList(tmp_path / "ignored.json")
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        assert len(il) == 1

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "ignored.json"
        il = IgnoreList(path)
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        il.save()
        assert path.exists()

    def test_save_format_is_json_array(self, tmp_path):
        path = tmp_path / "ignored.json"
        il = IgnoreList(path)
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        il.save()
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert isinstance(data[0], list)
        assert len(data[0]) == 2

    def test_clear_and_save(self, tmp_path):
        path = tmp_path / "ignored.json"
        il = IgnoreList(path)
        il.add(Path("/a.mp4"), Path("/b.mp4"))
        il.save()
        il.clear()
        il.save()
        il2 = IgnoreList(path)
        assert len(il2) == 0


class TestIgnoreListFiltering:
    """Test ignore list integration with pair filtering."""

    def _make_pair(self, make_metadata, path_a, path_b, score=85.0):
        from duplicates_detector.scorer import ScoredPair

        a = make_metadata(path_a)
        b = make_metadata(path_b)
        return ScoredPair(file_a=a, file_b=b, total_score=score, breakdown={}, detail={})

    def test_filter_ignored_pairs(self, tmp_path, make_metadata):
        il = IgnoreList(tmp_path / "ignored.json")
        pair = self._make_pair(make_metadata, "a.mp4", "b.mp4")
        il.add(pair.file_a.path, pair.file_b.path)

        pairs = [pair, self._make_pair(make_metadata, "c.mp4", "d.mp4")]
        filtered = [p for p in pairs if not il.contains(p.file_a.path, p.file_b.path)]
        assert len(filtered) == 1
        assert filtered[0].file_a.filename == "c"

    def test_filter_before_grouping(self, tmp_path, make_metadata):
        """Ignoring A-B edge prevents A and C from grouping via B."""
        from duplicates_detector.grouper import group_duplicates

        ab = self._make_pair(make_metadata, "a.mp4", "b.mp4")
        bc = self._make_pair(make_metadata, "b.mp4", "c.mp4")

        il = IgnoreList(tmp_path / "ignored.json")
        il.add(ab.file_a.path, ab.file_b.path)

        pairs = [ab, bc]
        filtered = [p for p in pairs if not il.contains(p.file_a.path, p.file_b.path)]
        groups = group_duplicates(filtered)
        # Only B-C pair remains — one group with 2 members
        assert len(groups) == 1
        assert len(groups[0].members) == 2
