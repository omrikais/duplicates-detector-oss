from __future__ import annotations

import json
import sys
import time
from io import StringIO

import pytest

from rich.progress import Progress

from duplicates_detector.progress import ProgressEmitter, ThroughputColumn, make_progress


# ---------------------------------------------------------------------------
# stage_start
# ---------------------------------------------------------------------------


class TestStageStart:
    def test_writes_valid_json_line(self, monkeypatch):
        """stage_start emits a single valid JSON object followed by newline."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scanning")

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert isinstance(event, dict)

    def test_event_type_is_stage_start(self, monkeypatch):
        """Event type field is 'stage_start'."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("metadata")

        event = json.loads(buf.getvalue().strip())
        assert event["type"] == "stage_start"

    def test_stage_field_matches_argument(self, monkeypatch):
        """Stage field matches the stage argument."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scoring")

        event = json.loads(buf.getvalue().strip())
        assert event["stage"] == "scoring"

    def test_timestamp_is_iso8601(self, monkeypatch):
        """Timestamp is a valid ISO 8601 string."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scanning")

        event = json.loads(buf.getvalue().strip())
        ts = event["timestamp"]
        # ISO 8601 UTC timestamps end with +00:00
        assert "T" in ts
        assert "+" in ts or "Z" in ts

    def test_total_included_when_provided(self, monkeypatch):
        """When total is passed, it appears in the event."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scanning", total=42)

        event = json.loads(buf.getvalue().strip())
        assert event["total"] == 42

    def test_total_omitted_when_not_provided(self, monkeypatch):
        """When total is not passed, the key is absent from the event."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scanning")

        event = json.loads(buf.getvalue().strip())
        assert "total" not in event


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


class TestProgress:
    def test_writes_valid_json_line(self, monkeypatch):
        """progress emits a single valid JSON object."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=5)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert isinstance(event, dict)

    def test_event_type_is_progress(self, monkeypatch):
        """Event type field is 'progress'."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1)

        event = json.loads(buf.getvalue().strip())
        assert event["type"] == "progress"

    def test_stage_and_current_fields(self, monkeypatch):
        """stage and current fields match the arguments."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=7)

        event = json.loads(buf.getvalue().strip())
        assert event["stage"] == "metadata"
        assert event["current"] == 7

    def test_timestamp_present(self, monkeypatch):
        """Timestamp is present and is ISO 8601."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1)

        event = json.loads(buf.getvalue().strip())
        assert "timestamp" in event
        assert "T" in event["timestamp"]

    def test_total_included_when_provided(self, monkeypatch):
        """When total is passed, it appears in the event."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=3, total=10)

        event = json.loads(buf.getvalue().strip())
        assert event["total"] == 10

    def test_total_omitted_when_not_provided(self, monkeypatch):
        """When total is not passed, the key is absent."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=3)

        event = json.loads(buf.getvalue().strip())
        assert "total" not in event

    def test_file_included_when_provided(self, monkeypatch):
        """When file is passed, it appears in the event."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1, file="/path/to/video.mp4")

        event = json.loads(buf.getvalue().strip())
        assert event["file"] == "/path/to/video.mp4"

    def test_file_omitted_when_not_provided(self, monkeypatch):
        """When file is not passed, the key is absent."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1)

        event = json.loads(buf.getvalue().strip())
        assert "file" not in event


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------


class TestThrottling:
    def test_rapid_calls_suppressed(self, monkeypatch):
        """Second call within 100ms throttle window is suppressed."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1)
        # Immediately call again — should be suppressed
        emitter.progress("metadata", current=2)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["current"] == 1

    def test_force_bypasses_throttle(self, monkeypatch):
        """force=True emits even within the throttle window."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1)
        emitter.progress("metadata", current=2, force=True)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["current"] == 1
        assert json.loads(lines[1])["current"] == 2

    def test_different_stages_not_throttled(self, monkeypatch):
        """Throttle is per-stage — different stages emit independently."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("scanning", current=1)
        emitter.progress("metadata", current=1)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 2

    def test_emits_after_throttle_window(self, monkeypatch):
        """After the throttle interval has elapsed, the next call emits."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.progress("metadata", current=1)
        # Wait longer than the 100ms throttle interval
        time.sleep(0.15)
        emitter.progress("metadata", current=2)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["current"] == 1
        assert json.loads(lines[1])["current"] == 2


# ---------------------------------------------------------------------------
# stage_end
# ---------------------------------------------------------------------------


class TestStageEnd:
    def test_writes_valid_json_line(self, monkeypatch):
        """stage_end emits a single valid JSON object."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scanning", total=100, elapsed=1.234)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert isinstance(event, dict)

    def test_event_type_is_stage_end(self, monkeypatch):
        """Event type field is 'stage_end'."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scanning", total=100, elapsed=1.234)

        event = json.loads(buf.getvalue().strip())
        assert event["type"] == "stage_end"

    def test_required_fields_present(self, monkeypatch):
        """stage, total, elapsed, and timestamp are all present."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scoring", total=50, elapsed=2.567)

        event = json.loads(buf.getvalue().strip())
        assert event["stage"] == "scoring"
        assert event["total"] == 50
        assert event["elapsed"] == 2.567
        assert "timestamp" in event

    def test_elapsed_rounded_to_3_decimals(self, monkeypatch):
        """elapsed is rounded to 3 decimal places."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scoring", total=10, elapsed=1.23456789)

        event = json.loads(buf.getvalue().strip())
        assert event["elapsed"] == 1.235

    def test_extra_kwargs_included(self, monkeypatch):
        """Extra keyword arguments are included in the event."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scoring", total=50, elapsed=3.0, pairs_found=5)

        event = json.loads(buf.getvalue().strip())
        assert event["pairs_found"] == 5

    def test_multiple_extra_kwargs(self, monkeypatch):
        """Multiple extra keyword arguments all appear in the event."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scoring", total=50, elapsed=3.0, pairs_found=5, skipped=2)

        event = json.loads(buf.getvalue().strip())
        assert event["pairs_found"] == 5
        assert event["skipped"] == 2

    def test_timestamp_is_iso8601(self, monkeypatch):
        """Timestamp is ISO 8601 format."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_end("scanning", total=10, elapsed=0.5)

        event = json.loads(buf.getvalue().strip())
        ts = event["timestamp"]
        assert "T" in ts
        assert "+" in ts or "Z" in ts

    def test_clears_throttle_state(self, monkeypatch):
        """stage_end clears the throttle state so next progress call emits immediately."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        # Emit a progress event to populate throttle state
        emitter.progress("scanning", current=1)
        # End the stage — should clear throttle state
        emitter.stage_end("scanning", total=10, elapsed=1.0)
        # Immediately emit another progress for the same stage
        emitter.progress("scanning", current=1)

        lines = buf.getvalue().strip().splitlines()
        # Should be 3 events: progress, stage_end, progress
        assert len(lines) == 3
        assert json.loads(lines[0])["type"] == "progress"
        assert json.loads(lines[1])["type"] == "stage_end"
        assert json.loads(lines[2])["type"] == "progress"


# ---------------------------------------------------------------------------
# JSON output format
# ---------------------------------------------------------------------------


class TestJsonFormat:
    def test_compact_json_no_spaces(self, monkeypatch):
        """JSON output uses compact separators (no spaces after : or ,)."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scanning", total=5)

        line = buf.getvalue().strip()
        # Compact JSON: no space after colon or comma
        assert ": " not in line
        assert ", " not in line

    def test_each_event_on_separate_line(self, monkeypatch):
        """Multiple events are emitted on separate lines (JSON-lines format)."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        emitter = ProgressEmitter()
        emitter.stage_start("scanning", total=5)
        emitter.progress("scanning", current=1, force=True)
        emitter.stage_end("scanning", total=5, elapsed=1.0)

        lines = buf.getvalue().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            event = json.loads(line)
            assert isinstance(event, dict)


# ---------------------------------------------------------------------------
# ThroughputColumn
# ---------------------------------------------------------------------------


class TestThroughputColumn:
    def test_no_speed_returns_empty(self):
        """When task has no speed data, render returns empty Text."""
        from unittest.mock import MagicMock

        col = ThroughputColumn()
        task = MagicMock()
        task.finished_speed = None
        task.speed = None
        result = col.render(task)
        assert result.plain == ""

    def test_default_unit_is_files(self):
        """Default unit is 'files'."""
        from unittest.mock import MagicMock

        col = ThroughputColumn()
        task = MagicMock()
        task.finished_speed = None
        task.speed = 42.567
        result = col.render(task)
        assert result.plain == "42.6 files/s"

    def test_custom_unit(self):
        """Custom unit is used in output."""
        from unittest.mock import MagicMock

        col = ThroughputColumn(unit="pairs")
        task = MagicMock()
        task.finished_speed = None
        task.speed = 3.14
        result = col.render(task)
        assert result.plain == "3.1 pairs/s"

    def test_finished_speed_takes_precedence(self):
        """finished_speed is preferred over speed when both are set."""
        from unittest.mock import MagicMock

        col = ThroughputColumn()
        task = MagicMock()
        task.finished_speed = 10.0
        task.speed = 5.0
        result = col.render(task)
        assert result.plain == "10.0 files/s"


# ---------------------------------------------------------------------------
# make_progress
# ---------------------------------------------------------------------------


class TestMakeProgress:
    def test_returns_progress_instance(self):
        """make_progress returns a rich Progress instance."""
        p = make_progress()
        assert isinstance(p, Progress)

    def test_disabled_when_quiet(self):
        """Progress is disabled when quiet=True."""
        p = make_progress(quiet=True)
        assert p.disable is True

    def test_disabled_when_progress_emitter(self):
        """Progress is disabled when a ProgressEmitter is provided."""
        emitter = ProgressEmitter()
        p = make_progress(progress_emitter=emitter)
        assert p.disable is True

    def test_enabled_by_default(self):
        """Progress is enabled when both quiet and progress_emitter are default."""
        p = make_progress()
        assert p.disable is False

    def test_custom_unit_propagated(self):
        """Custom unit is passed through to ThroughputColumn."""
        p = make_progress(unit="pairs")
        # The last column should be a ThroughputColumn with the custom unit
        throughput_cols = [c for c in p.columns if isinstance(c, ThroughputColumn)]
        assert len(throughput_cols) == 1
        assert throughput_cols[0]._unit == "pairs"
