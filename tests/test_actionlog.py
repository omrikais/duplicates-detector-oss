from __future__ import annotations

import json
from pathlib import Path

import pytest

from duplicates_detector.actionlog import ActionLog


class TestActionLog:
    def test_log_creates_file(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="deleted",
                path=Path("/a.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=1000,
            )
        assert log_path.exists()

    def test_log_appends(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="deleted",
                path=Path("/a.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=1000,
            )
            log.log(
                action="trashed",
                path=Path("/c.mp4"),
                score=90.0,
                strategy="longest",
                kept=Path("/d.mp4"),
                bytes_freed=2000,
            )
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["action"] == "deleted"
        assert json.loads(lines[1])["action"] == "trashed"

    def test_log_record_fields(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="deleted",
                path=Path("/a.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=1000,
            )
        record = json.loads(log_path.read_text().strip())
        assert "timestamp" in record
        assert record["action"] == "deleted"
        assert record["score"] == 85.0
        assert record["strategy"] == "biggest"
        assert record["bytes_freed"] == 1000
        assert "path" in record
        assert "kept" in record

    def test_log_destination_field(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="moved",
                path=Path("/a.mp4"),
                score=80.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=500,
                destination=Path("/staging/a.mp4"),
            )
            log.log(
                action="deleted",
                path=Path("/c.mp4"),
                score=80.0,
                strategy="biggest",
                kept=Path("/d.mp4"),
                bytes_freed=500,
            )
        lines = log_path.read_text().strip().split("\n")
        assert "destination" in json.loads(lines[0])
        assert "destination" not in json.loads(lines[1])

    def test_log_dry_run_field(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="deleted",
                path=Path("/a.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=1000,
                dry_run=True,
            )
            log.log(
                action="deleted",
                path=Path("/c.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/d.mp4"),
                bytes_freed=1000,
                dry_run=False,
            )
        lines = log_path.read_text().strip().split("\n")
        assert json.loads(lines[0])["dry_run"] is True
        assert "dry_run" not in json.loads(lines[1])

    def test_log_flush(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        log = ActionLog(log_path)
        log.open()
        log.log(
            action="deleted",
            path=Path("/a.mp4"),
            score=85.0,
            strategy="biggest",
            kept=Path("/b.mp4"),
            bytes_freed=1000,
        )
        # Record should be visible without closing
        content = log_path.read_text()
        assert "deleted" in content
        log.close()

    def test_log_none_noop(self):
        """When file is not opened, log() is a silent no-op."""
        log = ActionLog(Path("/nonexistent/path.jsonl"))
        # Should not raise
        log.log(
            action="deleted",
            path=Path("/a.mp4"),
            score=85.0,
            strategy="biggest",
            kept=Path("/b.mp4"),
            bytes_freed=1000,
        )

    def test_log_context_manager(self, tmp_path):
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            assert log._file is not None
        assert log._file is None

    def test_log_creates_parent_dirs(self, tmp_path):
        log_path = tmp_path / "nested" / "dir" / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="deleted",
                path=Path("/a.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=1000,
            )
        assert log_path.exists()

    def test_log_across_sessions(self, tmp_path):
        """Subsequent opens append to the same file."""
        log_path = tmp_path / "actions.jsonl"
        with ActionLog(log_path) as log:
            log.log(
                action="deleted",
                path=Path("/a.mp4"),
                score=85.0,
                strategy="biggest",
                kept=Path("/b.mp4"),
                bytes_freed=1000,
            )
        with ActionLog(log_path) as log:
            log.log(
                action="trashed",
                path=Path("/c.mp4"),
                score=90.0,
                strategy="longest",
                kept=Path("/d.mp4"),
                bytes_freed=2000,
            )
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
