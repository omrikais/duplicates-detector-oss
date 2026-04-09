from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from duplicates_detector.session import (
    EPHEMERAL_CONFIG_KEYS,
    RESUME_OVERRIDE_KEYS,
    ScanSession,
    SessionManager,
    _STAGE_WEIGHTS,
    build_session_config,
)


@pytest.fixture
def manager(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path)


class TestScanSession:
    def test_to_dict_and_from_dict(self) -> None:
        session = ScanSession(
            session_id="test123",
            directories=["/HD1/Videos"],
            config={"mode": "video", "content": True},
            completed_stages=["scan", "extract"],
            active_stage="content_hash",
            total_files=30000,
            elapsed_seconds=42.0,
            stage_timings={"scan": 0.6, "extract": 42.0},
        )
        d = session.to_dict()
        restored = ScanSession.from_dict(d)
        assert restored.session_id == "test123"
        assert restored.completed_stages == ["scan", "extract"]
        assert restored.total_files == 30000
        assert restored.stage_timings == {"scan": 0.6, "extract": 42.0}

    def test_from_dict_missing_stage_timings_defaults_to_empty_dict(self) -> None:
        data = {
            "session_id": "legacy123",
            "directories": ["/HD1/Videos"],
            "config": {"mode": "video"},
            "completed_stages": ["scan"],
            "active_stage": "extract",
            "total_files": 10,
            "elapsed_seconds": 3.0,
        }

        restored = ScanSession.from_dict(data)

        assert restored.stage_timings == {}

    def test_from_dict_null_stage_timings_defaults_to_empty_dict(self) -> None:
        data = {
            "session_id": "legacy-null",
            "directories": ["/HD1/Videos"],
            "config": {"mode": "video"},
            "completed_stages": ["scan"],
            "active_stage": "extract",
            "total_files": 10,
            "elapsed_seconds": 3.0,
            "stage_timings": None,
        }

        restored = ScanSession.from_dict(data)

        assert restored.stage_timings == {}

    def test_partial_scan_total_files_does_not_change_stage_progress(self) -> None:
        session = ScanSession(
            session_id="scan-partial",
            directories=["/HD1/Videos"],
            config={"mode": "video"},
            completed_stages=[],
            active_stage="scan",
            total_files=7,
            elapsed_seconds=3.0,
            stage_timings={},
        )

        assert session.progress_percent == 0
        restored = ScanSession.from_dict(session.to_dict())
        assert restored.total_files == 7


class TestSessionManager:
    def test_save_and_load(self, manager: SessionManager) -> None:
        session = ScanSession(
            session_id="test123",
            directories=["/HD1/Videos"],
            config={"mode": "video", "content": True},
            completed_stages=["scan", "extract"],
            active_stage="content_hash",
            total_files=30000,
            elapsed_seconds=42.0,
            stage_timings={"scan": 0.6, "extract": 42.0},
        )
        manager.save(session)
        loaded = manager.load("test123")
        assert loaded is not None
        assert loaded.session_id == "test123"
        assert loaded.completed_stages == ["scan", "extract"]

    def test_list_sessions(self, manager: SessionManager) -> None:
        for i in range(3):
            session = ScanSession(
                session_id=f"s{i}",
                directories=["/tmp"],
                config={},
                completed_stages=[],
                active_stage="scan",
                total_files=100,
                elapsed_seconds=0,
                stage_timings={},
            )
            manager.save(session)
        sessions = manager.list_sessions()
        assert len(sessions) == 3

    def test_delete(self, manager: SessionManager) -> None:
        session = ScanSession(
            session_id="del_me",
            directories=["/tmp"],
            config={},
            completed_stages=[],
            active_stage="scan",
            total_files=100,
            elapsed_seconds=0,
            stage_timings={},
        )
        manager.save(session)
        manager.delete("del_me")
        assert manager.load("del_me") is None

    def test_prune_old_sessions(self, manager: SessionManager) -> None:
        for i in range(7):
            session = ScanSession(
                session_id=f"s{i}",
                directories=["/tmp"],
                config={},
                completed_stages=[],
                active_stage="scan",
                total_files=100,
                elapsed_seconds=0,
                stage_timings={},
            )
            manager.save(session)
        manager.prune(max_sessions=5)
        assert len(manager.list_sessions()) == 5

    def test_prune_by_age(self, manager: SessionManager, tmp_path: Path) -> None:
        session = ScanSession(
            session_id="old_one",
            directories=["/tmp"],
            config={},
            completed_stages=[],
            active_stage="scan",
            total_files=100,
            elapsed_seconds=0,
            stage_timings={},
        )
        manager.save(session)
        # Backdate the file
        session_file = tmp_path / "old_one.json"
        old_time = time.time() - (31 * 86400)
        os.utime(session_file, (old_time, old_time))
        manager.prune(max_age_days=30)
        assert manager.load("old_one") is None

    def test_clear_all(self, manager: SessionManager) -> None:
        for i in range(3):
            session = ScanSession(
                session_id=f"s{i}",
                directories=["/tmp"],
                config={},
                completed_stages=[],
                active_stage="scan",
                total_files=100,
                elapsed_seconds=0,
                stage_timings={},
            )
            manager.save(session)
        manager.clear_all()
        assert len(manager.list_sessions()) == 0

    def test_load_nonexistent(self, manager: SessionManager) -> None:
        assert manager.load("nonexistent") is None

    def test_delete_nonexistent(self, manager: SessionManager) -> None:
        # Should not raise
        manager.delete("nonexistent")

    def test_corrupt_file_returns_none(self, manager: SessionManager, tmp_path: Path) -> None:
        (tmp_path / "corrupt.json").write_text("not valid json")
        assert manager.load("corrupt") is None


class TestPausedAt:
    def test_paused_at_round_trips(self) -> None:
        session = ScanSession(
            session_id="p1",
            directories=["/tmp"],
            config={},
            completed_stages=["scan"],
            active_stage="extract",
            total_files=50,
            elapsed_seconds=1.5,
            stage_timings={"scan": 1.0},
            paused_at="2026-03-21T12:00:00.000+00:00",
        )
        d = session.to_dict()
        assert d["paused_at"] == "2026-03-21T12:00:00.000+00:00"
        restored = ScanSession.from_dict(d)
        assert restored.paused_at == "2026-03-21T12:00:00.000+00:00"

    def test_paused_at_none_omitted_from_dict(self) -> None:
        session = ScanSession(
            session_id="p2",
            directories=["/tmp"],
            config={},
            completed_stages=[],
            active_stage="scan",
            total_files=0,
            elapsed_seconds=0.0,
            stage_timings={},
            paused_at=None,
        )
        d = session.to_dict()
        assert "paused_at" not in d
        restored = ScanSession.from_dict(d)
        assert restored.paused_at is None


# ---------------------------------------------------------------------------
# EPHEMERAL_CONFIG_KEYS
# ---------------------------------------------------------------------------


class TestEphemeralConfigKeys:
    def test_is_frozenset(self) -> None:
        assert isinstance(EPHEMERAL_CONFIG_KEYS, frozenset)

    def test_contains_resume(self) -> None:
        assert "resume" in EPHEMERAL_CONFIG_KEYS

    def test_contains_pause_file(self) -> None:
        assert "pause_file" in EPHEMERAL_CONFIG_KEYS

    def test_contains_machine_progress(self) -> None:
        assert "machine_progress" in EPHEMERAL_CONFIG_KEYS

    def test_contains_session_control_keys(self) -> None:
        """Session-management flags should be ephemeral."""
        for key in ("list_sessions", "list_sessions_json", "clear_sessions", "delete_session"):
            assert key in EPHEMERAL_CONFIG_KEYS, f"{key} missing from EPHEMERAL_CONFIG_KEYS"

    def test_contains_save_and_show_config(self) -> None:
        """Config display/persist flags should be ephemeral."""
        for key in ("save_config", "show_config", "save_profile", "print_completion"):
            assert key in EPHEMERAL_CONFIG_KEYS, f"{key} missing from EPHEMERAL_CONFIG_KEYS"


# ---------------------------------------------------------------------------
# RESUME_OVERRIDE_KEYS
# ---------------------------------------------------------------------------


class TestResumeOverrideKeys:
    def test_is_frozenset(self) -> None:
        assert isinstance(RESUME_OVERRIDE_KEYS, frozenset)

    def test_contains_presentation_keys(self) -> None:
        """Only presentation-only flags should be overridable on resume."""
        for key in ("verbose", "quiet", "no_color", "format", "json_envelope", "cache_stats"):
            assert key in RESUME_OVERRIDE_KEYS, f"{key} missing from RESUME_OVERRIDE_KEYS"

    def test_does_not_contain_result_altering_keys(self) -> None:
        """Keys that change pipeline results MUST NOT be in RESUME_OVERRIDE_KEYS."""
        forbidden = [
            "min_score",
            "limit",
            "sort",
            "log",
            "embed_thumbnails",
            "thumbnail_size",
            "content",
            "audio",
            "threshold",
            "mode",
            "weights",
        ]
        for key in forbidden:
            assert key not in RESUME_OVERRIDE_KEYS, f"{key} must NOT be in RESUME_OVERRIDE_KEYS"

    def test_disjoint_from_ephemeral(self) -> None:
        """Override keys and ephemeral keys should not overlap."""
        overlap = RESUME_OVERRIDE_KEYS & EPHEMERAL_CONFIG_KEYS
        assert overlap == frozenset(), f"Overlap between override and ephemeral: {overlap}"


# ---------------------------------------------------------------------------
# build_session_config
# ---------------------------------------------------------------------------


class TestBuildSessionConfig:
    def test_excludes_all_ephemeral_keys(self) -> None:
        """build_session_config must not include any EPHEMERAL_CONFIG_KEYS."""
        from duplicates_detector.config import DEFAULTS
        from types import SimpleNamespace

        args = SimpleNamespace(**DEFAULTS)
        config = build_session_config(args)
        for key in EPHEMERAL_CONFIG_KEYS:
            assert key not in config, f"Ephemeral key '{key}' found in session config"

    def test_includes_all_non_ephemeral_defaults(self) -> None:
        """build_session_config must include all DEFAULTS keys except ephemeral ones."""
        from duplicates_detector.config import DEFAULTS
        from types import SimpleNamespace

        args = SimpleNamespace(**DEFAULTS)
        config = build_session_config(args)
        expected_keys = set(DEFAULTS.keys()) - EPHEMERAL_CONFIG_KEYS
        assert set(config.keys()) == expected_keys

    def test_uses_arg_values_over_defaults(self) -> None:
        """build_session_config prefers args values over DEFAULTS."""
        from duplicates_detector.config import DEFAULTS
        from types import SimpleNamespace

        args = SimpleNamespace(**DEFAULTS)
        args.threshold = 75
        args.mode = "image"
        config = build_session_config(args)
        assert config["threshold"] == 75
        assert config["mode"] == "image"

    def test_falls_back_to_defaults_for_none(self) -> None:
        """When an arg value is None, build_session_config uses the DEFAULTS value."""
        from duplicates_detector.config import DEFAULTS
        from types import SimpleNamespace

        args = SimpleNamespace(**DEFAULTS)
        args.threshold = None  # explicitly set to None
        config = build_session_config(args)
        assert config["threshold"] == DEFAULTS["threshold"]

    def test_round_trip_save_load_restore(self, tmp_path: Path) -> None:
        """Build config -> save session -> load session -> verify config preserved."""
        from duplicates_detector.config import DEFAULTS
        from types import SimpleNamespace

        args = SimpleNamespace(**DEFAULTS)
        args.threshold = 80
        args.mode = "audio"
        args.content = True
        config = build_session_config(args)

        session = ScanSession(
            session_id="roundtrip",
            directories=["/test"],
            config=config,
            completed_stages=["scan"],
            active_stage="extract",
            total_files=100,
            elapsed_seconds=5.0,
            stage_timings={"scan": 1.0},
        )
        mgr = SessionManager(tmp_path)
        mgr.save(session)
        loaded = mgr.load("roundtrip")
        assert loaded is not None
        assert loaded.config["threshold"] == 80
        assert loaded.config["mode"] == "audio"
        assert loaded.config["content"] is True
        # Ephemeral keys should not be present
        for key in EPHEMERAL_CONFIG_KEYS:
            assert key not in loaded.config


# ---------------------------------------------------------------------------
# SessionManager degraded / disabled mode
# ---------------------------------------------------------------------------


class TestSessionManagerDegraded:
    """When the sessions directory cannot be created, SessionManager enters
    a disabled mode where all operations become safe no-ops rather than
    crashing the scan."""

    @pytest.fixture
    def disabled_manager(self, tmp_path: Path) -> SessionManager:
        """Create a SessionManager whose directory cannot be mkdir'd.

        We place a regular file at the target path so that mkdir on a child
        of that file raises OSError on every platform.
        """
        blocker = tmp_path / "blocked"
        blocker.write_text("occupied")
        unwritable = blocker / "sessions"
        with pytest.warns(UserWarning, match="Cannot create sessions directory"):
            mgr = SessionManager(unwritable)
        return mgr

    @pytest.fixture
    def _sample_session(self) -> ScanSession:
        return ScanSession(
            session_id="degraded_test",
            directories=["/tmp"],
            config={"mode": "video"},
            completed_stages=["scan"],
            active_stage="extract",
            total_files=10,
            elapsed_seconds=1.0,
            stage_timings={"scan": 0.5},
        )

    def test_init_failure_sets_disabled_flag(self, disabled_manager: SessionManager) -> None:
        """Initialization failure must set _disabled=True without raising."""
        assert disabled_manager._disabled is True

    def test_init_failure_emits_warning(self, tmp_path: Path) -> None:
        """A UserWarning with a descriptive message must be emitted on mkdir failure."""
        blocker = tmp_path / "blocker_warn"
        blocker.write_text("occupied")
        unwritable = blocker / "sessions"
        with pytest.warns(UserWarning, match="Session checkpointing is disabled"):
            SessionManager(unwritable)

    def test_save_is_noop_when_disabled(self, disabled_manager: SessionManager, _sample_session: ScanSession) -> None:
        """save() must not raise when disabled."""
        disabled_manager.save(_sample_session)  # should not raise

    def test_load_returns_none_when_disabled(self, disabled_manager: SessionManager) -> None:
        """load() must return None when disabled, regardless of session_id."""
        assert disabled_manager.load("any_id") is None

    def test_list_sessions_returns_empty_when_disabled(self, disabled_manager: SessionManager) -> None:
        """list_sessions() must return an empty list when disabled."""
        assert disabled_manager.list_sessions() == []

    def test_delete_is_noop_when_disabled(self, disabled_manager: SessionManager) -> None:
        """delete() must not raise when disabled."""
        disabled_manager.delete("any_id")  # should not raise

    def test_prune_is_noop_when_disabled(self, disabled_manager: SessionManager) -> None:
        """prune() must not raise when disabled."""
        disabled_manager.prune()  # should not raise

    def test_clear_all_is_noop_when_disabled(self, disabled_manager: SessionManager) -> None:
        """clear_all() must not raise when disabled."""
        disabled_manager.clear_all()  # should not raise

    def test_happy_path_not_disabled(self, manager: SessionManager) -> None:
        """A SessionManager created with a writable path must NOT be disabled,
        and save/load must work normally."""
        assert manager._disabled is False
        session = ScanSession(
            session_id="happy",
            directories=["/tmp"],
            config={"mode": "video"},
            completed_stages=["scan"],
            active_stage="extract",
            total_files=5,
            elapsed_seconds=0.5,
            stage_timings={"scan": 0.3},
        )
        manager.save(session)
        loaded = manager.load("happy")
        assert loaded is not None
        assert loaded.session_id == "happy"


# ---------------------------------------------------------------------------
# progress_percent
# ---------------------------------------------------------------------------


def _make_session(**overrides: object) -> ScanSession:
    """Factory for ScanSession with sensible defaults for progress_percent tests."""
    defaults: dict = dict(
        session_id="test",
        directories=["/tmp"],
        config={"mode": "video", "content": False, "audio": False, "embed_thumbnails": False, "content_method": None},
        completed_stages=[],
        active_stage="scan",
        total_files=100,
        elapsed_seconds=1.0,
        stage_timings={},
    )
    defaults.update(overrides)
    return ScanSession(**defaults)


class TestProgressPercent:
    """Tests for ScanSession.progress_percent — a conservative completion percentage
    based on completed pipeline stages and their weights."""

    def test_progress_percent_in_to_dict(self) -> None:
        """to_dict() must include a 'progress_percent' key with the correct int value."""
        # Basic pipeline: scan, extract, filter, score, report
        # Complete scan + extract: (0.05 + 0.20) / (0.05 + 0.20 + 0.01 + 0.12 + 0.04) = 0.25 / 0.42
        session = _make_session(completed_stages=["scan", "extract"], active_stage="filter")
        d = session.to_dict()
        assert "progress_percent" in d
        expected = int(0.25 / 0.42 * 100)  # 59
        assert d["progress_percent"] == expected

    def test_progress_percent_zero_no_completed_stages(self) -> None:
        """No completed stages must produce 0%."""
        session = _make_session(completed_stages=[], active_stage="scan")
        assert session.progress_percent == 0

    def test_progress_percent_all_stages_completed(self) -> None:
        """All stages for a basic pipeline completed must produce 100%."""
        # Basic video pipeline (no content, no audio): scan, extract, filter, score, report
        session = _make_session(
            completed_stages=["scan", "extract", "filter", "score", "report"],
            active_stage="",
        )
        assert session.progress_percent == 100

    def test_progress_percent_conservative_active_not_counted(self) -> None:
        """The active stage must NOT contribute to progress — only completed stages count."""
        # completed: scan + extract = 0.05 + 0.20 = 0.25
        # active: filter (0.01) — must NOT be counted
        # denominator: basic pipeline = 0.05 + 0.20 + 0.01 + 0.12 + 0.04 = 0.42
        session = _make_session(
            completed_stages=["scan", "extract"],
            active_stage="filter",
        )
        expected = int(0.25 / 0.42 * 100)  # 59
        assert session.progress_percent == expected

        # Verify the active stage really makes no difference vs omitting it
        session_same = _make_session(
            completed_stages=["scan", "extract"],
            active_stage="score",
        )
        assert session_same.progress_percent == expected

    def test_progress_percent_content_hash_pipeline(self) -> None:
        """With content=True, the denominator includes content_hash weight."""
        # Pipeline: scan, extract, filter, content_hash, score, report
        # completed: scan + extract + filter = 0.05 + 0.20 + 0.01 = 0.26
        # denominator: 0.05 + 0.20 + 0.01 + 0.30 + 0.12 + 0.04 = 0.72
        session = _make_session(
            config={
                "mode": "video",
                "content": True,
                "audio": False,
                "embed_thumbnails": False,
                "content_method": None,
            },
            completed_stages=["scan", "extract", "filter"],
            active_stage="content_hash",
        )
        expected = int(0.26 / 0.72 * 100)  # 36
        assert session.progress_percent == expected

    def test_progress_percent_from_dict_round_trip(self) -> None:
        """from_dict(to_dict(session)) must still work — extra progress_percent key is ignored."""
        session = _make_session(completed_stages=["scan"], active_stage="extract")
        d = session.to_dict()
        assert "progress_percent" in d

        restored = ScanSession.from_dict(d)
        assert restored.session_id == session.session_id
        assert restored.completed_stages == session.completed_stages
        # progress_percent is recomputed from state, not stored
        assert restored.progress_percent == session.progress_percent

    def test_progress_percent_empty_config(self) -> None:
        """An empty config dict must still return a reasonable value (0 when no stages completed)."""
        session = _make_session(config={}, completed_stages=[])
        # compute_stage_list with all flags False => basic pipeline
        assert session.progress_percent == 0

    def test_progress_percent_audio_pipeline(self) -> None:
        """With audio=True, the denominator includes audio_fingerprint weight."""
        # Pipeline: scan, extract, filter, audio_fingerprint, score, report
        # completed: scan + extract + filter + audio_fingerprint = 0.05 + 0.20 + 0.01 + 0.18 = 0.44
        # denominator: 0.05 + 0.20 + 0.01 + 0.18 + 0.12 + 0.04 = 0.60
        session = _make_session(
            config={
                "mode": "video",
                "content": False,
                "audio": True,
                "embed_thumbnails": False,
                "content_method": None,
            },
            completed_stages=["scan", "extract", "filter", "audio_fingerprint"],
            active_stage="score",
        )
        expected = int(0.44 / 0.60 * 100)  # 73
        assert session.progress_percent == expected

    def test_progress_percent_clamped_to_100(self) -> None:
        """progress_percent must never exceed 100, even with unexpected completed_stages."""
        # Force all known stages into completed_stages regardless of pipeline config
        all_stages = list(_STAGE_WEIGHTS.keys())
        session = _make_session(completed_stages=all_stages, active_stage="")
        assert session.progress_percent <= 100

    def test_progress_percent_is_int(self) -> None:
        """progress_percent must return an int, not a float."""
        session = _make_session(completed_stages=["scan"], active_stage="extract")
        result = session.progress_percent
        assert isinstance(result, int)
