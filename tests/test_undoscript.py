"""Tests for undoscript.py — undo shell script generation from action logs."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from duplicates_detector.undoscript import (
    _shell_quote,
    generate_undo_script,
    parse_action_log,
    run_generate_undo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    action: str = "moved",
    path: str = "/data/dup.mp4",
    score: float = 90.0,
    strategy: str = "biggest",
    kept: str = "/data/kept.mp4",
    bytes_freed: int = 50_000_000,
    destination: str | None = None,
    dry_run: bool = False,
    timestamp: str = "2026-03-03T10:30:00",
) -> dict:
    record: dict = {
        "timestamp": timestamp,
        "action": action,
        "path": path,
        "score": score,
        "strategy": strategy,
        "kept": kept,
        "bytes_freed": bytes_freed,
    }
    if destination is not None:
        record["destination"] = destination
    if dry_run:
        record["dry_run"] = True
    return record


def _write_log(tmp_path: Path, records: list[dict]) -> Path:
    """Write records as JSON-lines to a temp file and return the path."""
    log = tmp_path / "actions.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return log


# ---------------------------------------------------------------------------
# TestShellQuote
# ---------------------------------------------------------------------------


class TestShellQuote:
    def test_plain_string(self) -> None:
        assert _shell_quote("hello") == "hello"

    def test_spaces_preserved(self) -> None:
        assert _shell_quote("hello world") == "hello world"

    def test_double_quotes_escaped(self) -> None:
        assert _shell_quote('say "hi"') == 'say \\"hi\\"'

    def test_dollar_sign_escaped(self) -> None:
        assert _shell_quote("$HOME") == "\\$HOME"

    def test_backtick_escaped(self) -> None:
        assert _shell_quote("run `cmd`") == "run \\`cmd\\`"

    def test_backslash_escaped(self) -> None:
        assert _shell_quote("a\\b") == "a\\\\b"

    def test_newline_preserved(self) -> None:
        """Literal newlines must be preserved so shell commands reference correct paths."""
        assert _shell_quote("a\nb") == "a\nb"

    def test_combined_special_chars(self) -> None:
        result = _shell_quote('say "$(`echo hi`)"')
        assert result == 'say \\"\\$(\\`echo hi\\`)\\"'


# ---------------------------------------------------------------------------
# TestParseActionLog
# ---------------------------------------------------------------------------


class TestParseActionLog:
    def test_parses_valid_records(self, tmp_path: Path) -> None:
        records_in = [
            _make_record(action="moved", destination="/tmp/dup.mp4"),
            _make_record(action="deleted"),
        ]
        log = _write_log(tmp_path, records_in)
        records, total, dry, malformed = parse_action_log(log)
        assert len(records) == 2
        assert total == 2
        assert dry == 0
        assert malformed == 0

    def test_skips_dry_run_entries(self, tmp_path: Path) -> None:
        records_in = [
            _make_record(action="moved", destination="/tmp/dup.mp4"),
            _make_record(action="deleted", dry_run=True),
        ]
        log = _write_log(tmp_path, records_in)
        records, total, dry, malformed = parse_action_log(log)
        assert len(records) == 1
        assert total == 2
        assert dry == 1
        assert malformed == 0

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text('{"action":"moved","path":"/a"}\n{bad json}\n{"action":"deleted","path":"/b"}\n')
        records, total, _dry, malformed = parse_action_log(log)
        assert len(records) == 2
        assert total == 3
        assert malformed == 1

    def test_skips_records_missing_action(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text('{"path":"/a","score":50}\n')
        records, _total, _dry, malformed = parse_action_log(log)
        assert len(records) == 0
        assert malformed == 1

    def test_skips_records_missing_path(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text('{"action":"deleted","score":50}\n')
        records, _total, _dry, malformed = parse_action_log(log)
        assert len(records) == 0
        assert malformed == 1

    def test_skips_records_with_non_string_action(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text('{"action":123,"path":"/a"}\n')
        records, _total, _dry, malformed = parse_action_log(log)
        assert len(records) == 0
        assert malformed == 1

    def test_skips_records_with_non_string_path(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text('{"action":"deleted","path":456}\n')
        records, _total, _dry, malformed = parse_action_log(log)
        assert len(records) == 0
        assert malformed == 1

    def test_empty_file(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text("")
        records, total, _dry, _malformed = parse_action_log(log)
        assert records == []
        assert total == 0

    def test_returns_counts(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        log.write_text(
            json.dumps(_make_record(action="moved", destination="/tmp/a"))
            + "\n"
            + json.dumps(_make_record(action="deleted", dry_run=True))
            + "\n"
            + "{bad}\n"
            + json.dumps(_make_record(action="trashed"))
            + "\n"
        )
        records, total, dry, malformed = parse_action_log(log)
        assert len(records) == 2
        assert total == 4
        assert dry == 1
        assert malformed == 1

    def test_non_utf8_bytes_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "actions.jsonl"
        valid = json.dumps(_make_record(action="deleted")).encode()
        log.write_bytes(valid + b"\n" + b'\xff\xfe{"action":"bad"}\n' + valid + b"\n")
        records, total, _dry, malformed = parse_action_log(log)
        assert len(records) == 2
        assert malformed == 1
        assert total == 3

    def test_nonexistent_file_error(self, tmp_path: Path) -> None:
        log = tmp_path / "nope.jsonl"
        with pytest.raises(SystemExit):
            parse_action_log(log)


# ---------------------------------------------------------------------------
# TestGenerateUndoScript
# ---------------------------------------------------------------------------


class TestGenerateUndoScript:
    def _gen(self, records: list[dict], **kwargs) -> str:  # type: ignore[no-untyped-def]
        buf = io.StringIO()
        generate_undo_script(
            records,
            log_path=kwargs.get("log_path", Path("/tmp/actions.jsonl")),
            total_records=kwargs.get("total_records", len(records)),
            skipped_dry_run=kwargs.get("skipped_dry_run", 0),
            skipped_malformed=kwargs.get("skipped_malformed", 0),
            output=buf,
        )
        return buf.getvalue()

    def test_moved_action(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert 'mv "/staging/dup.mp4" "/data/dup.mp4"' in script

    def test_moved_checks_destination_exists(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert '[ -e "/staging/dup.mp4" ]' in script

    def test_moved_checks_path_not_exists(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert '[ -e "/data/dup.mp4" ]' in script

    def test_moved_creates_parent_dir(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert 'mkdir -p "/data"' in script

    def test_hardlinked_action(self) -> None:
        script = self._gen([_make_record(action="hardlinked")])
        assert 'cp "/data/kept.mp4" "/data/dup.mp4.tmp"' in script
        assert 'mv "/data/dup.mp4.tmp" "/data/dup.mp4"' in script

    def test_hardlinked_checks_both_files_exist(self) -> None:
        script = self._gen([_make_record(action="hardlinked")])
        assert '[ -f "/data/dup.mp4" ]' in script
        assert '[ -f "/data/kept.mp4" ]' in script

    def test_symlinked_action(self) -> None:
        script = self._gen([_make_record(action="symlinked")])
        assert 'cp "/data/kept.mp4" "/data/dup.mp4.tmp"' in script
        assert 'mv "/data/dup.mp4.tmp" "/data/dup.mp4"' in script

    def test_symlinked_checks_symlink(self) -> None:
        script = self._gen([_make_record(action="symlinked")])
        assert '[ -L "/data/dup.mp4" ]' in script

    def test_reflinked_action(self) -> None:
        script = self._gen([_make_record(action="reflinked")])
        assert 'cp "/data/kept.mp4" "/data/dup.mp4.tmp"' in script
        assert 'mv "/data/dup.mp4.tmp" "/data/dup.mp4"' in script

    def test_reflinked_checks_both_files_exist(self) -> None:
        script = self._gen([_make_record(action="reflinked")])
        assert '[ -f "/data/dup.mp4" ]' in script
        assert '[ -f "/data/kept.mp4" ]' in script

    def test_reflinked_without_kept_warns(self) -> None:
        record = _make_record(action="reflinked", kept="")
        script = self._gen([record])
        assert "Cannot undo reflink" in script
        assert "no kept file recorded" in script

    def test_reflinked_counted_as_reversible(self) -> None:
        records = [_make_record(action="reflinked")]
        script = self._gen(records)
        assert "1 reversible" in script

    def test_deleted_action(self) -> None:
        script = self._gen([_make_record(action="deleted")])
        assert "IRRECOVERABLE" in script
        assert "/data/dup.mp4" in script

    def test_trashed_action(self) -> None:
        script = self._gen([_make_record(action="trashed")])
        assert "MANUAL" in script
        assert "/data/dup.mp4" in script
        assert "OS trash" in script

    def test_script_header(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert script.startswith("#!/usr/bin/env bash\n")
        assert "set -euo pipefail" in script
        assert "Source log:" in script
        assert "Generated:" in script

    def test_confirmation_prompt(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert 'read -r -p "Continue? [y/N] "' in script

    def test_summary_counters(self) -> None:
        script = self._gen([_make_record(action="moved", destination="/staging/dup.mp4")])
        assert "restored=0" in script
        assert "failed=0" in script
        assert "warnings=0" in script
        assert "$restored restored" in script

    def test_paths_with_special_chars(self) -> None:
        script = self._gen(
            [
                _make_record(
                    action="moved",
                    path='/data/my "file" $HOME.mp4',
                    destination='/staging/my "file" $HOME.mp4',
                )
            ]
        )
        # Dollar signs and quotes should be escaped in the script
        assert "\\$HOME" in script
        assert '\\"file\\"' in script

    def test_newline_in_path_sanitized_in_comments(self) -> None:
        """Newlines in paths must be escaped in comment lines (injection prevention)."""
        record = _make_record(action="deleted", path="/tmp/evil\nrm -rf /")
        script = self._gen([record])
        # Comment lines must have the newline escaped (via _sanitize_comment)
        for line in script.splitlines():
            if line.startswith("#") and "Original path:" in line:
                assert "\\n" in line, "Newline not escaped in comment"
                break

    def test_newline_in_kept_sanitized_in_comments(self) -> None:
        """Newlines in kept paths must be escaped in comment lines."""
        record = _make_record(action="hardlinked", kept="/tmp/evil\nrm -rf /")
        script = self._gen([record])
        # Comment header must have the newline escaped
        for line in script.splitlines():
            if line.startswith("#") and "Kept:" in line:
                assert "\\n" in line, "Newline not escaped in comment"
                break

    def test_newline_in_path_preserved_in_shell_strings(self) -> None:
        """Literal newlines must be preserved in double-quoted shell strings for correct paths."""
        record = _make_record(action="deleted", path="/tmp/file\nname.mp4")
        script = self._gen([record])
        # The echo line should contain the literal newline inside double quotes
        assert 'echo "IRRECOVERABLE: /tmp/file\nname.mp4' in script

    def test_newline_in_score_does_not_inject(self) -> None:
        record = {"action": "deleted", "path": "/tmp/a", "score": "90\nrm -rf /", "bytes_freed": 100}
        script = self._gen([record])
        for line in script.splitlines():
            assert not line.strip().startswith("rm"), f"Injected line found: {line!r}"

    def test_multiple_actions_in_order(self) -> None:
        records = [
            _make_record(
                action="moved", destination="/staging/a.mp4", path="/data/a.mp4", timestamp="2026-01-01T01:00:00"
            ),
            _make_record(action="deleted", path="/data/b.mp4", timestamp="2026-01-01T02:00:00"),
            _make_record(action="hardlinked", path="/data/c.mp4", timestamp="2026-01-01T03:00:00"),
        ]
        script = self._gen(records)
        # Actions should appear in log order
        pos_moved = script.index("Action 1: moved")
        pos_deleted = script.index("Action 2: deleted")
        pos_hardlinked = script.index("Action 3: hardlinked")
        assert pos_moved < pos_deleted < pos_hardlinked

    def test_empty_records_no_output(self) -> None:
        """Empty records still produce a valid script (header + counters)."""
        script = self._gen([])
        assert "#!/usr/bin/env bash" in script
        assert "0 reversible" in script

    def test_header_skipped_counts(self) -> None:
        script = self._gen(
            [_make_record(action="moved", destination="/staging/a.mp4")],
            total_records=5,
            skipped_dry_run=2,
            skipped_malformed=1,
        )
        assert "2 skipped dry-run" in script
        assert "1 skipped malformed" in script

    def test_moved_without_destination(self) -> None:
        """A moved record with no destination field emits a warning."""
        script = self._gen([_make_record(action="moved")])
        assert "No destination recorded" in script

    def test_non_string_optional_fields_coerced(self) -> None:
        """Non-string kept/destination and non-int bytes_freed don't crash."""
        record = {"action": "hardlinked", "path": "/tmp/a", "kept": 123, "bytes_freed": "not_a_number"}
        script = self._gen([record])
        # Should produce a valid script without crashing
        assert "Action 1: hardlinked" in script

    def test_non_string_destination_coerced(self) -> None:
        record = {"action": "moved", "path": "/tmp/a", "destination": 456}
        script = self._gen([record])
        assert "Action 1: moved" in script


# ---------------------------------------------------------------------------
# TestRunGenerateUndo
# ---------------------------------------------------------------------------


class TestRunGenerateUndo:
    def test_writes_to_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        run_generate_undo(str(log))
        captured = capsys.readouterr()
        assert "#!/usr/bin/env bash" in captured.out

    def test_writes_to_file(self, tmp_path: Path) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        out = tmp_path / "undo.sh"
        run_generate_undo(str(log), output_file=str(out))
        content = out.read_text()
        assert "#!/usr/bin/env bash" in content

    def test_stderr_hint_with_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        out = tmp_path / "undo.sh"
        run_generate_undo(str(log), output_file=str(out))
        captured = capsys.readouterr()
        assert "Wrote undo script to" in captured.err

    def test_stderr_hint_suppressed_quiet(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        out = tmp_path / "undo.sh"
        run_generate_undo(str(log), output_file=str(out), quiet=True)
        captured = capsys.readouterr()
        assert "Wrote undo script to" not in captured.err

    def test_nonexistent_log_exits_1(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_generate_undo(str(tmp_path / "nope.jsonl"))
        assert exc_info.value.code == 1

    def test_output_same_as_log_exits_1(self, tmp_path: Path) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        with pytest.raises(SystemExit) as exc_info:
            run_generate_undo(str(log), output_file=str(log))
        assert exc_info.value.code == 1
        # Log file must not be truncated
        assert log.read_text().strip() != ""

    def test_output_hardlink_to_log_exits_1(self, tmp_path: Path) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        hardlink = tmp_path / "alias.jsonl"
        hardlink.hardlink_to(log)
        with pytest.raises(SystemExit) as exc_info:
            run_generate_undo(str(log), output_file=str(hardlink))
        assert exc_info.value.code == 1
        # Log file must not be truncated
        assert log.read_text().strip() != ""

    def test_unwritable_output_exits_1(self, tmp_path: Path) -> None:
        log = _write_log(tmp_path, [_make_record(action="moved", destination="/staging/a.mp4")])
        bad_output = str(tmp_path / "no" / "such" / "dir" / "undo.sh")
        with pytest.raises(SystemExit) as exc_info:
            run_generate_undo(str(log), output_file=bad_output)
        assert exc_info.value.code == 1

    def test_empty_log_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        log = tmp_path / "empty.jsonl"
        log.write_text("")
        # Should return normally (no SystemExit), no script output
        run_generate_undo(str(log))
        captured = capsys.readouterr()
        assert "#!/usr/bin/env bash" not in captured.out
