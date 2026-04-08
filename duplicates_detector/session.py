from __future__ import annotations

import json
import logging
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Stage weights matching the spec's overall-progress table.
# Used to compute a conservative progress percentage from completed stages.
# Must stay in sync with ScanProgressModel.stageWeights on the Swift side.
_STAGE_WEIGHTS: dict[str, float] = {
    "scan": 0.05,
    "extract": 0.20,
    "filter": 0.01,
    "content_hash": 0.30,
    "ssim_extract": 0.05,
    "audio_fingerprint": 0.18,
    "score": 0.12,
    "thumbnail": 0.05,
    "report": 0.04,
}

# Ephemeral/control flags excluded from session config snapshots.
EPHEMERAL_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "resume",
        "pause_file",
        "list_sessions",
        "list_sessions_json",
        "clear_sessions",
        "delete_session",
        "machine_progress",
        "save_config",
        "show_config",
        "save_profile",
        "print_completion",
    }
)

# Config keys that may be overridden when resuming a session.
# ONLY truly presentation-only flags belong here. Keys that change
# the result set, result ordering, persisted side effects, pipeline
# work, or stage list MUST NOT be listed.
#
# Justification for each key:
#   verbose      — controls Rich console verbosity only
#   quiet        — suppresses Rich summary panel only
#   no_color     — disables ANSI color output only
#   format       — output format (table/json/csv/shell/html); same pairs produced
#   json_envelope — JSON wrapping detail; same pairs produced
#   cache_stats  — post-scan cache hit display only
RESUME_OVERRIDE_KEYS: frozenset[str] = frozenset(
    {
        "verbose",
        "quiet",
        "no_color",
        "format",
        "json_envelope",
        "cache_stats",
    }
)


def build_session_config(args: object) -> dict:
    """Build a full config snapshot from resolved args, excluding ephemeral keys.

    Iterates ``DEFAULTS`` keys (the canonical set of all config fields),
    skips ephemeral keys, and snapshots the resolved value.
    """
    from duplicates_detector.config import DEFAULTS

    config: dict = {}
    for key in DEFAULTS:
        if key in EPHEMERAL_CONFIG_KEYS:
            continue
        val = getattr(args, key, None)
        config[key] = val if val is not None else DEFAULTS[key]
    return config


@dataclass
class ScanSession:
    """Snapshot of a scan's state for pause/resume."""

    session_id: str
    directories: list[str]
    config: dict
    completed_stages: list[str]
    active_stage: str
    total_files: int
    elapsed_seconds: float
    stage_timings: dict[str, float]
    created_at: float = field(default_factory=time.time)
    paused_at: str | None = None

    @property
    def progress_percent(self) -> int:
        """Conservative progress percentage based on completed stages only.

        Uses ``compute_stage_list()`` from ``pipeline.py`` to determine which
        stages are present for this session's config, then sums the normalized
        weights of fully-completed stages.  The active stage at pause time
        contributes 0% — this is intentionally conservative so the resume card
        never overstates progress.
        """
        from duplicates_detector.pipeline import compute_stage_list

        try:
            stages = compute_stage_list(
                is_replay=False,
                is_ssim=self.config.get("content_method") == "ssim",
                embed_thumbnails=bool(self.config.get("embed_thumbnails")),
                has_content=bool(self.config.get("content")),
                has_audio=bool(self.config.get("audio")),
            )
        except Exception:
            return 0

        if not stages:
            return 0

        # Build normalized weights for only the stages in this pipeline.
        total_weight = sum(_STAGE_WEIGHTS.get(s, 0.0) for s in stages)
        if total_weight <= 0:
            return 0

        completed_weight = sum(_STAGE_WEIGHTS.get(s, 0.0) for s in self.completed_stages if s in stages)
        return min(100, int(completed_weight / total_weight * 100))

    def to_dict(self) -> dict:
        d: dict = {
            "session_id": self.session_id,
            "directories": self.directories,
            "config": self.config,
            "completed_stages": self.completed_stages,
            "active_stage": self.active_stage,
            "total_files": self.total_files,
            "elapsed_seconds": self.elapsed_seconds,
            "stage_timings": self.stage_timings,
            "created_at": self.created_at,
            "progress_percent": self.progress_percent,
        }
        if self.paused_at is not None:
            d["paused_at"] = self.paused_at
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ScanSession:
        stage_timings = data.get("stage_timings")
        if not isinstance(stage_timings, dict):
            stage_timings = {}
        return cls(
            session_id=data["session_id"],
            directories=data["directories"],
            config=data["config"],
            completed_stages=data["completed_stages"],
            active_stage=data["active_stage"],
            total_files=data["total_files"],
            elapsed_seconds=data["elapsed_seconds"],
            stage_timings=stage_timings,
            created_at=data.get("created_at", 0.0),
            paused_at=data.get("paused_at"),
        )


class SessionManager:
    """Manages scan session files for pause/resume across app restarts.

    If the sessions directory cannot be created (permissions, disk full, etc.),
    the manager enters a disabled/degraded mode where all operations become
    safe no-ops. This allows normal scans to continue without checkpointing.
    """

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = sessions_dir
        self._disabled = False
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._disabled = True
            warnings.warn(
                f"Cannot create sessions directory {sessions_dir}: {exc}. "
                "Session checkpointing is disabled for this scan.",
                stacklevel=2,
            )

    def save(self, session: ScanSession) -> None:
        """Save session to a JSON file. Failures log a warning, don't crash."""
        if self._disabled:
            logger.debug("Session save skipped (sessions directory unavailable)")
            return
        path = self._dir / f"{session.session_id}.json"
        try:
            data = json.dumps(session.to_dict(), indent=2)
            path.write_text(data, encoding="utf-8")
        except OSError as exc:
            warnings.warn(f"Failed to save session {session.session_id}: {exc}", stacklevel=2)

    def load(self, session_id: str) -> ScanSession | None:
        """Load session by ID. Returns None if missing, corrupt, or disabled."""
        if self._disabled:
            return None
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ScanSession.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return None

    def list_sessions(self) -> list[ScanSession]:
        """List all sessions, sorted by creation time (newest first)."""
        if self._disabled:
            return []
        sessions = []
        for f in self._dir.glob("*.json"):
            session = self.load(f.stem)
            if session is not None:
                sessions.append(session)
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def delete(self, session_id: str) -> None:
        """Delete a session file. No error if missing or disabled."""
        if self._disabled:
            return
        path = self._dir / f"{session_id}.json"
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def prune(self, *, max_sessions: int = 5, max_age_days: int = 30) -> None:
        """Remove old sessions beyond count or age limits.

        Uses file stats (mtime) instead of loading session contents —
        avoids parsing potentially large session files during startup.
        """
        if self._disabled:
            return
        now = time.time()
        max_age_seconds = max_age_days * 86400

        # Collect (mtime, path) for all session files without reading contents.
        # Skip corrupt files (e.g. from interrupted writes) so they don't
        # occupy a slot and cause valid sessions to be pruned.
        entries: list[tuple[float, Path]] = []
        for f in self._dir.glob("*.json"):
            try:
                st = f.stat()
                # A valid session JSON must be at least a few bytes ("{}")
                if st.st_size < 2:
                    f.unlink(missing_ok=True)
                    continue
                # Quick check: valid JSON starts with '{'
                with f.open("rb") as fh:
                    if fh.read(1) != b"{":
                        f.unlink(missing_ok=True)
                        continue
                entries.append((st.st_mtime, f))
            except OSError:
                pass

        # Remove by age first
        surviving: list[tuple[float, Path]] = []
        for mtime, path in entries:
            if now - mtime > max_age_seconds:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                surviving.append((mtime, path))

        # Then enforce count limit (newest first)
        if len(surviving) > max_sessions:
            surviving.sort(key=lambda e: e[0], reverse=True)
            for _, path in surviving[max_sessions:]:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def clear_all(self) -> None:
        """Delete all session files."""
        if self._disabled:
            return
        for f in self._dir.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass
