from __future__ import annotations

import argparse
import warnings
from typing import Any

import pytest

from duplicates_detector.config import (
    DEFAULTS,
    Mode,
    _BOOL_FIELDS,
    get_config_path,
    get_profile_path,
    get_profiles_dir,
    load_config,
    load_profile,
    merge_config,
    namespace_to_config,
    save_config,
    save_profile,
    show_config,
    validate_profile_name,
)


# ---------------------------------------------------------------------------
# get_config_path
# ---------------------------------------------------------------------------


class TestGetConfigPath:
    def test_xdg_config_home(self, monkeypatch, tmp_path):
        """XDG_CONFIG_HOME is respected."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = get_config_path()
        assert path == tmp_path / "duplicates-detector" / "config.toml"

    def test_default_fallback(self, monkeypatch):
        """Falls back to ~/.config/duplicates-detector/config.toml."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        path = get_config_path()
        assert path.name == "config.toml"
        assert "duplicates-detector" in str(path)
        assert ".config" in str(path)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_empty(self, tmp_path):
        """Non-existent config file returns {}."""
        result = load_config(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_valid_toml(self, tmp_path):
        """Valid TOML is loaded correctly."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('threshold = 30\nkeep = "biggest"\n')
        result = load_config(config_file)
        assert result == {"threshold": 30, "keep": "biggest"}

    def test_non_utf8_bytes_warns(self, tmp_path):
        """Non-UTF-8 bytes trigger warning and return {}."""
        config_file = tmp_path / "config.toml"
        config_file.write_bytes(b"\xff\xfe threshold = 30\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert result == {}
        assert len(w) == 1
        assert "corrupt" in str(w[0].message).lower()

    def test_corrupt_toml_warns(self, tmp_path):
        """Corrupt TOML triggers warning and returns {}."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("this is not valid [[[ toml ===")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert result == {}
        assert len(w) == 1
        assert "corrupt" in str(w[0].message).lower()

    def test_unknown_keys_warned(self, tmp_path):
        """Unknown keys trigger warnings and are skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('threshold = 30\nunknown_key = "value"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "unknown_key" not in result
        assert result == {"threshold": 30}
        assert any("unknown" in str(warning.message).lower() for warning in w)

    def test_invalid_threshold_type(self, tmp_path):
        """Non-integer threshold is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('threshold = "high"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "threshold" not in result
        assert len(w) == 1

    def test_invalid_threshold_range(self, tmp_path):
        """Threshold outside 0-100 is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("threshold = 200\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "threshold" not in result
        assert len(w) == 1

    def test_invalid_keep_value(self, tmp_path):
        """Invalid keep strategy is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('keep = "random"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "keep" not in result
        assert len(w) == 1

    def test_invalid_format_value(self, tmp_path):
        """Invalid format choice is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('format = "xml"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "format" not in result
        assert len(w) == 1

    def test_format_html_in_config(self, tmp_path):
        """'html' is a valid format choice in config."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('format = "html"\n')
        result = load_config(config_file)
        assert result["format"] == "html"

    def test_invalid_bool_type(self, tmp_path):
        """Non-boolean for boolean field is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('verbose = "yes"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "verbose" not in result
        assert len(w) == 1

    def test_invalid_exclude_type(self, tmp_path):
        """Non-array exclude is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('exclude = "*.tmp"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "exclude" not in result
        assert len(w) == 1

    def test_invalid_size_string(self, tmp_path):
        """Unparseable size string is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('min_size = "banana"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "min_size" not in result
        assert len(w) == 1

    def test_invalid_size_type(self, tmp_path):
        """Non-string size field is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("min_size = 1024\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "min_size" not in result
        assert len(w) == 1

    def test_invalid_duration_type(self, tmp_path):
        """Non-numeric duration is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('min_duration = "long"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "min_duration" not in result
        assert len(w) == 1

    def test_negative_duration(self, tmp_path):
        """Negative duration is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("min_duration = -10\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "min_duration" not in result
        assert len(w) == 1

    def test_invalid_workers_negative(self, tmp_path):
        """Negative workers is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("workers = -1\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "workers" not in result
        assert len(w) == 1

    def test_invalid_extensions_type(self, tmp_path):
        """Non-string extensions is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('extensions = ["mp4", "mkv"]\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "extensions" not in result
        assert len(w) == 1

    def test_bool_as_threshold_rejected(self, tmp_path):
        """Boolean value for threshold is rejected (bool is subclass of int)."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("threshold = true\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(config_file)
        assert "threshold" not in result
        assert len(w) == 1

    def test_all_valid_fields(self, tmp_path):
        """All configurable fields load correctly when valid."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "threshold = 30\n"
            'extensions = "mp4,mkv"\n'
            "workers = 4\n"
            'keep = "biggest"\n'
            'format = "json"\n'
            "verbose = true\n"
            "content = true\n"
            "group = true\n"
            "no_recursive = true\n"
            "no_content_cache = true\n"
            "no_metadata_cache = true\n"
            'min_size = "10MB"\n'
            'max_size = "4GB"\n'
            "min_duration = 60\n"
            "max_duration = 3600\n"
            'exclude = ["**/thumbnails/**", "*.tmp"]\n'
            'cache_dir = "/tmp/my-cache"\n'
        )
        result = load_config(config_file)
        assert result["threshold"] == 30
        assert result["extensions"] == "mp4,mkv"
        assert result["workers"] == 4
        assert result["keep"] == "biggest"
        assert result["format"] == "json"
        assert result["verbose"] is True
        assert result["content"] is True
        assert result["group"] is True
        assert result["no_recursive"] is True
        assert result["no_content_cache"] is True
        assert result["no_metadata_cache"] is True
        assert result["min_size"] == "10MB"
        assert result["max_size"] == "4GB"
        assert result["min_duration"] == 60
        assert result["max_duration"] == 3600
        assert result["exclude"] == ["**/thumbnails/**", "*.tmp"]
        assert result["cache_dir"] == "/tmp/my-cache"


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_creates_directory(self, tmp_path):
        """Parent directory is created if missing."""
        config_file = tmp_path / "subdir" / "config.toml"
        save_config({"threshold": 30}, config_file)
        assert config_file.exists()

    def test_writes_valid_toml(self, tmp_path):
        """Written file is valid TOML and round-trips correctly."""
        config_file = tmp_path / "config.toml"
        save_config({"threshold": 30, "keep": "biggest"}, config_file)
        result = load_config(config_file)
        assert result == {"threshold": 30, "keep": "biggest"}

    def test_only_non_default_values(self, tmp_path):
        """Only values differing from defaults are written."""
        config_file = tmp_path / "config.toml"
        # threshold=30 differs from default 50, verbose=False matches default
        save_config({"threshold": 30}, config_file)
        result = load_config(config_file)
        assert "threshold" in result
        # Verify defaults are not written
        content = config_file.read_text()
        assert "verbose" not in content
        assert "workers" not in content

    def test_header_comment(self, tmp_path):
        """File starts with descriptive comment."""
        config_file = tmp_path / "config.toml"
        save_config({"threshold": 30}, config_file)
        content = config_file.read_text()
        assert content.startswith("# duplicates-detector configuration")
        assert "--save-config" in content

    def test_empty_config(self, tmp_path):
        """Empty config (all defaults) writes minimal file."""
        config_file = tmp_path / "config.toml"
        save_config({}, config_file)
        assert config_file.exists()
        result = load_config(config_file)
        assert result == {}

    def test_exclude_array(self, tmp_path):
        """Exclude patterns are written as TOML array."""
        config_file = tmp_path / "config.toml"
        save_config({"exclude": ["**/thumbnails/**", "*.tmp"]}, config_file)
        result = load_config(config_file)
        assert result["exclude"] == ["**/thumbnails/**", "*.tmp"]


# ---------------------------------------------------------------------------
# merge_config
# ---------------------------------------------------------------------------


class TestMergeConfig:
    def _make_args(self, **overrides: Any) -> argparse.Namespace:
        """Create a Namespace with all configurable fields set to None."""
        defaults: dict[str, Any] = {key: None for key in DEFAULTS}
        # Session-specific fields
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_cli_overrides_config(self):
        """CLI-set values take precedence over config."""
        args = self._make_args(threshold=80)
        config = {"threshold": 30}
        merged = merge_config(args, config)
        assert merged.threshold == 80

    def test_config_fills_unset_cli(self):
        """Config values fill in for unset CLI flags."""
        args = self._make_args()
        config = {"threshold": 30}
        merged = merge_config(args, config)
        assert merged.threshold == 30

    def test_hardcoded_defaults_fill_rest(self):
        """Hardcoded defaults fill in when neither CLI nor config sets a value."""
        args = self._make_args()
        merged = merge_config(args, {})
        assert merged.threshold == 50
        assert merged.workers == 0
        assert merged.format == "table"
        assert merged.verbose is False

    def test_exclude_merge(self):
        """Exclude patterns from config and CLI are merged (not replaced)."""
        args = self._make_args(exclude=["*.tmp"])
        config = {"exclude": ["**/thumbnails/**"]}
        merged = merge_config(args, config)
        assert merged.exclude == ["**/thumbnails/**", "*.tmp"]

    def test_exclude_cli_only(self):
        """CLI exclude patterns work when config has none."""
        args = self._make_args(exclude=["*.tmp"])
        merged = merge_config(args, {})
        assert merged.exclude == ["*.tmp"]

    def test_exclude_config_only(self):
        """Config exclude patterns work when CLI has none."""
        args = self._make_args()
        config = {"exclude": ["**/thumbnails/**"]}
        merged = merge_config(args, config)
        assert merged.exclude == ["**/thumbnails/**"]

    def test_exclude_neither(self):
        """No excludes from either source gives None."""
        args = self._make_args()
        merged = merge_config(args, {})
        assert merged.exclude is None

    def test_returns_new_namespace(self):
        """Original namespace is not mutated."""
        args = self._make_args()
        config = {"threshold": 30}
        original_threshold = args.threshold
        merge_config(args, config)
        assert args.threshold == original_threshold

    def test_size_fields_parsed(self):
        """String size values from config are parsed to int via parse_size()."""
        args = self._make_args()
        config = {"min_size": "10MB", "max_size": "4GB"}
        merged = merge_config(args, config)
        assert merged.min_size == 10 * 1024**2
        assert merged.max_size == 4 * 1024**3

    def test_boolean_none_means_unset(self):
        """None boolean from CLI means 'not set', uses config or default."""
        args = self._make_args()  # verbose=None
        config = {"verbose": True}
        merged = merge_config(args, config)
        assert merged.verbose is True

    def test_boolean_true_means_set(self):
        """True boolean from CLI means 'explicitly set', overrides config."""
        args = self._make_args(verbose=True)
        config = {"verbose": False}
        merged = merge_config(args, config)
        assert merged.verbose is True

    def test_all_defaults_applied(self):
        """All hardcoded defaults are applied when config is empty."""
        args = self._make_args()
        merged = merge_config(args, {})
        for key, default in DEFAULTS.items():
            if key == "exclude":
                assert merged.exclude is None
            else:
                assert getattr(merged, key) == default, f"Mismatch for {key}"

    def test_session_fields_preserved(self):
        """Session-specific fields are not touched by merge."""
        args = self._make_args(interactive=True, dry_run=True, output="out.json")
        merged = merge_config(args, {})
        assert merged.interactive is True
        assert merged.dry_run is True
        assert merged.output == "out.json"


# ---------------------------------------------------------------------------
# namespace_to_config
# ---------------------------------------------------------------------------


class TestNamespaceToConfig:
    def test_extracts_configurable_fields(self):
        """Only configurable fields are included."""
        args = argparse.Namespace(
            threshold=30,
            verbose=True,
            keep="biggest",
            # Non-default values
            directories=["."],
            interactive=False,
            dry_run=False,
            # Remaining defaults
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            exclude=[],
            reference=None,
            output=None,
            action="delete",
            move_to_dir=None,
            cache_dir=None,
            sort="score",
            limit=None,
            quiet=False,
            no_color=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert "threshold" in config
        assert "verbose" in config
        assert "keep" in config

    def test_skips_session_fields(self):
        """directories, reference, output, interactive, dry_run are excluded."""
        args = argparse.Namespace(
            threshold=30,
            directories=["/some/path"],
            interactive=True,
            dry_run=True,
            reference=["/ref"],
            output="out.json",
            # Remaining with defaults
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            exclude=[],
            action="delete",
            move_to_dir=None,
            cache_dir=None,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert "directories" not in config
        assert "interactive" not in config
        assert "dry_run" not in config
        assert "reference" not in config
        assert "output" not in config

    def test_size_to_string(self):
        """Integer size values are converted back to human-readable strings."""
        args = argparse.Namespace(
            threshold=50,
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=10 * 1024**2,
            max_size=4 * 1024**3,
            min_duration=None,
            max_duration=None,
            exclude=[],
            action="delete",
            move_to_dir=None,
            cache_dir=None,
            sort="score",
            limit=None,
            quiet=False,
            no_color=False,
            directories=["."],
            interactive=False,
            dry_run=False,
            reference=None,
            output=None,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert config["min_size"] == "10MB"
        assert config["max_size"] == "4GB"

    def test_omits_defaults(self):
        """Values matching hardcoded defaults are omitted."""
        args = argparse.Namespace(
            threshold=50,
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            min_resolution=None,
            max_resolution=None,
            min_bitrate=None,
            max_bitrate=None,
            codec=None,
            exclude=[],
            action="delete",
            move_to_dir=None,
            cache_dir=None,
            sort="score",
            limit=None,
            weights=None,
            quiet=False,
            no_color=False,
            ignore_file=None,
            log=None,
            json_envelope=False,
            mode="video",
            directories=["."],
            interactive=False,
            dry_run=False,
            reference=None,
            output=None,
            save_config=False,
            no_config=False,
            show_config=False,
            audio=False,
            no_audio_cache=False,
            embed_thumbnails=False,
            thumbnail_size=None,
            machine_progress=False,
            resume=None,
            list_sessions=False,
            clear_sessions=False,
            pause_file=None,
            cache_stats=False,
            delete_session=None,
            list_sessions_json=False,
            no_pre_hash=False,
            sidecar_extensions=".xmp,.aae,.thm,.json",
            no_sidecars=False,
        )
        config = namespace_to_config(args)
        assert config == {}


# ---------------------------------------------------------------------------
# no_pre_hash config
# ---------------------------------------------------------------------------


class TestNoPreHashConfig:
    def test_no_pre_hash_in_defaults(self):
        """no_pre_hash exists in DEFAULTS and defaults to False."""
        assert "no_pre_hash" in DEFAULTS
        assert DEFAULTS["no_pre_hash"] is False

    def test_no_pre_hash_in_bool_fields(self):
        """no_pre_hash is registered as a boolean field."""
        assert "no_pre_hash" in _BOOL_FIELDS


# ---------------------------------------------------------------------------
# show_config
# ---------------------------------------------------------------------------


class TestShowConfig:
    def test_prints_to_stdout(self, capsys):
        """Config is printed in readable format."""
        show_config({"threshold": 30, "keep": "biggest"})
        captured = capsys.readouterr()
        assert "threshold" in captured.out
        assert "30" in captured.out
        assert "biggest" in captured.out


# ---------------------------------------------------------------------------
# action / move_to_dir config fields
# ---------------------------------------------------------------------------


class TestActionConfig:
    def test_action_in_defaults(self):
        assert DEFAULTS["action"] == "delete"

    def test_move_to_dir_in_defaults(self):
        assert DEFAULTS["move_to_dir"] is None

    def test_load_config_validates_action(self, tmp_path):
        """Invalid action value is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('action = "nuke"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "action" not in cfg
        assert any("action" in str(warning.message) for warning in w)

    def test_load_config_validates_action_type(self, tmp_path):
        """Non-string action is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("action = 42\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "action" not in cfg
        assert any("action" in str(warning.message) for warning in w)

    def test_load_config_validates_move_to_dir_type(self, tmp_path):
        """Non-string move_to_dir is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("move_to_dir = 123\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "move_to_dir" not in cfg
        assert any("move_to_dir" in str(warning.message) for warning in w)

    def test_load_config_accepts_valid_action(self, tmp_path):
        """Valid action values are accepted."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('action = "trash"\n')
        cfg = load_config(config_file)
        assert cfg["action"] == "trash"

    def test_load_config_accepts_move_to_dir(self, tmp_path):
        """Valid move_to_dir string is accepted."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('move_to_dir = "/tmp/staging"\n')
        cfg = load_config(config_file)
        assert cfg["move_to_dir"] == "/tmp/staging"

    def test_merge_config_applies_action(self):
        """Config action is used when CLI doesn't set it."""
        defaults = dict(DEFAULTS)
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        # Simulate CLI not setting action (sentinel None)
        defaults["action"] = None
        defaults["move_to_dir"] = None
        args = argparse.Namespace(**defaults)
        config = {"action": "trash"}
        merged = merge_config(args, config)
        assert merged.action == "trash"

    def test_merge_config_cli_overrides_action(self):
        """CLI --action overrides config value."""
        defaults = dict(DEFAULTS)
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        defaults["action"] = "delete"  # CLI explicitly set
        defaults["move_to_dir"] = None
        args = argparse.Namespace(**defaults)
        config = {"action": "trash"}
        merged = merge_config(args, config)
        assert merged.action == "delete"

    def test_save_config_includes_action(self, tmp_path):
        """Non-default action is written to TOML."""
        config_file = tmp_path / "config.toml"
        save_config({"action": "trash"}, config_file)
        cfg = load_config(config_file)
        assert cfg["action"] == "trash"

    def test_save_config_omits_default_action(self, tmp_path):
        """Default action value is not written."""
        config_file = tmp_path / "config.toml"
        save_config({}, config_file)
        cfg = load_config(config_file)
        assert "action" not in cfg

    def test_namespace_to_config_includes_non_default_action(self):
        """Non-default action is included in config dict."""
        args = argparse.Namespace(
            threshold=50,
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            exclude=[],
            action="trash",
            move_to_dir="/tmp/staging",
            cache_dir=None,
            sort="score",
            limit=None,
            quiet=False,
            no_color=False,
            directories=["."],
            interactive=False,
            dry_run=False,
            reference=None,
            output=None,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert config["action"] == "trash"
        assert config["move_to_dir"] == "/tmp/staging"

    def test_namespace_to_config_omits_default_action(self):
        """Default action and None move_to_dir are omitted."""
        args = argparse.Namespace(
            threshold=50,
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            exclude=[],
            action="delete",
            move_to_dir=None,
            cache_dir=None,
            sort="score",
            limit=None,
            quiet=False,
            no_color=False,
            directories=["."],
            interactive=False,
            dry_run=False,
            reference=None,
            output=None,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert "action" not in config
        assert "move_to_dir" not in config


# ---------------------------------------------------------------------------
# cache_dir config field
# ---------------------------------------------------------------------------


class TestCacheDirConfig:
    def test_cache_dir_in_defaults(self):
        assert DEFAULTS["cache_dir"] is None

    def test_load_config_validates_cache_dir_type(self, tmp_path):
        """Non-string cache_dir is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("cache_dir = 123\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "cache_dir" not in cfg
        assert any("cache_dir" in str(warning.message) for warning in w)

    def test_load_config_accepts_valid_cache_dir(self, tmp_path):
        """Valid cache_dir string is accepted."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('cache_dir = "/tmp/my-cache"\n')
        cfg = load_config(config_file)
        assert cfg["cache_dir"] == "/tmp/my-cache"

    def test_merge_config_applies_cache_dir(self):
        """Config cache_dir is used when CLI doesn't set it."""
        defaults: dict[str, Any] = {key: None for key in DEFAULTS}
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        args = argparse.Namespace(**defaults)
        config = {"cache_dir": "/tmp/my-cache"}
        merged = merge_config(args, config)
        assert merged.cache_dir == "/tmp/my-cache"

    def test_merge_config_cli_overrides_cache_dir(self):
        """CLI --cache-dir overrides config value."""
        defaults: dict[str, Any] = {key: None for key in DEFAULTS}
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        defaults["cache_dir"] = "/cli/cache"
        args = argparse.Namespace(**defaults)
        config = {"cache_dir": "/config/cache"}
        merged = merge_config(args, config)
        assert merged.cache_dir == "/cli/cache"

    def test_save_config_includes_cache_dir(self, tmp_path):
        """Non-default cache_dir is written to TOML."""
        config_file = tmp_path / "config.toml"
        save_config({"cache_dir": "/tmp/my-cache"}, config_file)
        cfg = load_config(config_file)
        assert cfg["cache_dir"] == "/tmp/my-cache"

    def test_namespace_to_config_includes_non_default_cache_dir(self):
        """Non-default cache_dir is included in config dict."""
        args = argparse.Namespace(
            threshold=50,
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            exclude=[],
            action="delete",
            move_to_dir=None,
            cache_dir="/tmp/my-cache",
            directories=["."],
            interactive=False,
            dry_run=False,
            reference=None,
            output=None,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert config["cache_dir"] == "/tmp/my-cache"

    def test_namespace_to_config_omits_default_cache_dir(self):
        """None cache_dir (default) is omitted."""
        args = argparse.Namespace(
            threshold=50,
            verbose=False,
            keep=None,
            extensions=None,
            workers=0,
            format="table",
            content=False,
            group=False,
            no_recursive=False,
            no_content_cache=False,
            no_metadata_cache=False,
            min_size=None,
            max_size=None,
            min_duration=None,
            max_duration=None,
            exclude=[],
            action="delete",
            move_to_dir=None,
            cache_dir=None,
            sort="score",
            limit=None,
            quiet=False,
            no_color=False,
            directories=["."],
            interactive=False,
            dry_run=False,
            reference=None,
            output=None,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        config = namespace_to_config(args)
        assert "cache_dir" not in config

    def test_show_config_includes_cache_dir(self, capsys):
        """cache_dir appears in show_config output."""
        show_config({"cache_dir": "/tmp/my-cache"})
        captured = capsys.readouterr()
        assert "cache_dir" in captured.out
        assert "/tmp/my-cache" in captured.out


# ---------------------------------------------------------------------------
# sort config field
# ---------------------------------------------------------------------------


class TestSortConfig:
    def test_sort_in_defaults(self):
        assert DEFAULTS["sort"] == "score"

    def test_load_config_validates_sort_value(self, tmp_path):
        """Invalid sort value is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('sort = "invalid"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "sort" not in cfg
        assert any("sort" in str(warning.message) for warning in w)

    def test_load_config_validates_sort_type(self, tmp_path):
        """Non-string sort is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("sort = 42\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "sort" not in cfg
        assert any("sort" in str(warning.message) for warning in w)

    def test_load_config_accepts_valid_sort(self, tmp_path):
        """Valid sort values are accepted."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('sort = "size"\n')
        cfg = load_config(config_file)
        assert cfg["sort"] == "size"

    def test_merge_config_applies_sort(self):
        """Config sort is used when CLI doesn't set it."""
        defaults: dict[str, Any] = {key: None for key in DEFAULTS}
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        args = argparse.Namespace(**defaults)
        config = {"sort": "mtime"}
        merged = merge_config(args, config)
        assert merged.sort == "mtime"


# ---------------------------------------------------------------------------
# limit config field
# ---------------------------------------------------------------------------


class TestLimitConfig:
    def test_limit_in_defaults(self):
        assert DEFAULTS["limit"] is None

    def test_load_config_validates_limit_type(self, tmp_path):
        """Non-integer limit is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('limit = "ten"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "limit" not in cfg
        assert any("limit" in str(warning.message) for warning in w)

    def test_load_config_validates_limit_range(self, tmp_path):
        """Zero or negative limit is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("limit = 0\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "limit" not in cfg
        assert any("limit" in str(warning.message) for warning in w)

    def test_load_config_validates_limit_negative(self, tmp_path):
        """Negative limit is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("limit = -5\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "limit" not in cfg

    def test_load_config_validates_limit_bool(self, tmp_path):
        """Boolean value for limit is rejected."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("limit = true\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "limit" not in cfg

    def test_load_config_accepts_valid_limit(self, tmp_path):
        """Valid positive limit is accepted."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("limit = 10\n")
        cfg = load_config(config_file)
        assert cfg["limit"] == 10

    def test_merge_config_applies_limit(self):
        """Config limit is used when CLI doesn't set it."""
        defaults: dict[str, Any] = {key: None for key in DEFAULTS}
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        args = argparse.Namespace(**defaults)
        config = {"limit": 5}
        merged = merge_config(args, config)
        assert merged.limit == 5


# ---------------------------------------------------------------------------
# quiet / no_color config fields
# ---------------------------------------------------------------------------


class TestQuietNoColorConfig:
    def test_quiet_in_defaults(self):
        assert DEFAULTS["quiet"] is False

    def test_no_color_in_defaults(self):
        assert DEFAULTS["no_color"] is False

    def test_load_config_validates_quiet_type(self, tmp_path):
        """Non-boolean quiet is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('quiet = "yes"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "quiet" not in cfg
        assert any("quiet" in str(warning.message) for warning in w)

    def test_load_config_accepts_valid_quiet(self, tmp_path):
        """Valid boolean quiet is accepted."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("quiet = true\n")
        cfg = load_config(config_file)
        assert cfg["quiet"] is True

    def test_load_config_validates_no_color_type(self, tmp_path):
        """Non-boolean no_color is warned and skipped."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("no_color = 1\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(config_file)
        assert "no_color" not in cfg

    def test_merge_config_applies_quiet(self):
        """Config quiet is used when CLI doesn't set it."""
        defaults: dict[str, Any] = {key: None for key in DEFAULTS}
        defaults.update(
            directories=["."],
            reference=None,
            output=None,
            interactive=False,
            dry_run=False,
            save_config=False,
            no_config=False,
            show_config=False,
        )
        args = argparse.Namespace(**defaults)
        config = {"quiet": True}
        merged = merge_config(args, config)
        assert merged.quiet is True


# ---------------------------------------------------------------------------
# weights in config
# ---------------------------------------------------------------------------


class TestWeightsConfig:
    def test_weights_in_defaults(self):
        assert "weights" in DEFAULTS
        assert DEFAULTS["weights"] is None

    def test_load_valid_weights(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[weights]\nfilename = 50.0\nduration = 30.0\nresolution = 10.0\nfilesize = 10.0\n")
        config = load_config(cfg)
        assert "weights" in config
        assert config["weights"]["filename"] == 50.0

    def test_load_invalid_weights_type(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('weights = "not a table"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "weights" not in config
        assert any("must be a table" in str(warning.message) for warning in w)

    def test_load_negative_weight_value(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[weights]\nfilename = -5.0\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "weights" not in config
        assert any("non-negative" in str(warning.message) for warning in w)

    def test_load_bool_weight_value(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[weights]\nfilename = true\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "weights" not in config

    def test_load_unknown_weight_key(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[weights]\nfilname = 50.0\nduration = 50.0\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "weights" not in config
        assert any("unknown weight key" in str(warning.message) for warning in w)

    def test_load_alias_collision(self, tmp_path):
        """Both 'filesize' and 'file_size' map to the same canonical key."""
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            "[weights]\nfilename = 25.0\nduration = 25.0\nresolution = 10.0\nfilesize = 20.0\nfile_size = 20.0\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "weights" not in config
        assert any("alias collision" in str(warning.message) for warning in w)

    def test_load_exif_weight_key(self, tmp_path):
        """'exif' weight key should be accepted in config (image mode weights)."""
        cfg = tmp_path / "config.toml"
        cfg.write_text("[weights]\nfilename = 25.0\nresolution = 20.0\nfilesize = 15.0\nexif = 40.0\n")
        config = load_config(cfg)
        assert "weights" in config
        assert config["weights"]["exif"] == 40.0

    def test_load_directory_weight_key(self, tmp_path):
        """'directory' weight key should be accepted in config."""
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            "[weights]\nfilename = 40.0\nduration = 30.0\nresolution = 10.0\nfilesize = 10.0\ndirectory = 10.0\n"
        )
        config = load_config(cfg)
        assert "weights" in config
        assert config["weights"]["directory"] == 10.0

    def test_directory_in_weight_keys(self):
        """'directory' is in _WEIGHT_KEYS."""
        from duplicates_detector.config import _WEIGHT_KEYS

        assert "directory" in _WEIGHT_KEYS

    def test_directory_in_weight_canonical(self):
        """'directory' is in _WEIGHT_CANONICAL."""
        from duplicates_detector.config import _WEIGHT_CANONICAL

        assert "directory" in _WEIGHT_CANONICAL
        assert _WEIGHT_CANONICAL["directory"] == "directory"


# ---------------------------------------------------------------------------
# hardlink / symlink action in config
# ---------------------------------------------------------------------------


class TestActionConfigLinkTypes:
    def test_load_hardlink_action(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('action = "hardlink"\n')
        config = load_config(cfg)
        assert config["action"] == "hardlink"

    def test_load_symlink_action(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('action = "symlink"\n')
        config = load_config(cfg)
        assert config["action"] == "symlink"

    def test_load_reflink_action(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('action = "reflink"\n')
        config = load_config(cfg)
        assert config["action"] == "reflink"


# ---------------------------------------------------------------------------
# resolution / bitrate / codec config fields
# ---------------------------------------------------------------------------


class TestResolutionBitrateCodecConfig:
    def test_resolution_fields_in_defaults(self):
        assert DEFAULTS["min_resolution"] is None
        assert DEFAULTS["max_resolution"] is None

    def test_bitrate_fields_in_defaults(self):
        assert DEFAULTS["min_bitrate"] is None
        assert DEFAULTS["max_bitrate"] is None

    def test_codec_in_defaults(self):
        assert DEFAULTS["codec"] is None

    def test_load_valid_resolution(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('min_resolution = "1920x1080"\nmax_resolution = "3840x2160"\n')
        config = load_config(cfg)
        assert config["min_resolution"] == "1920x1080"
        assert config["max_resolution"] == "3840x2160"

    def test_load_invalid_resolution_warns(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('min_resolution = "bad"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "min_resolution" not in config
        assert any("not a valid resolution" in str(warning.message) for warning in w)

    def test_load_resolution_wrong_type_warns(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("min_resolution = 1920\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "min_resolution" not in config

    def test_load_valid_bitrate(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('min_bitrate = "5Mbps"\nmax_bitrate = "20Mbps"\n')
        config = load_config(cfg)
        assert config["min_bitrate"] == "5Mbps"
        assert config["max_bitrate"] == "20Mbps"

    def test_load_invalid_bitrate_warns(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('min_bitrate = "bad"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "min_bitrate" not in config
        assert any("not a valid bitrate" in str(warning.message) for warning in w)

    def test_load_valid_codec(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('codec = "h264,hevc"\n')
        config = load_config(cfg)
        assert config["codec"] == "h264,hevc"

    def test_load_codec_wrong_type_warns(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("codec = 264\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "codec" not in config

    def test_merge_resolution_from_config(self):
        args = argparse.Namespace(**{k: v for k, v in DEFAULTS.items()})
        args.directories = ["."]
        args.reference = None
        args.output = None
        args.interactive = False
        args.dry_run = False
        args.save_config = False
        args.no_config = False
        args.show_config = False
        args.print_completion = None
        config = {"min_resolution": "1920x1080"}
        merged = merge_config(args, config)
        assert merged.min_resolution == "1920x1080"

    def test_merge_cli_overrides_config_resolution(self):
        args = argparse.Namespace(**{k: v for k, v in DEFAULTS.items()})
        args.directories = ["."]
        args.reference = None
        args.output = None
        args.interactive = False
        args.dry_run = False
        args.save_config = False
        args.no_config = False
        args.show_config = False
        args.print_completion = None
        args.min_resolution = "3840x2160"
        config = {"min_resolution": "1920x1080"}
        merged = merge_config(args, config)
        assert merged.min_resolution == "3840x2160"

    def test_save_config_includes_new_fields(self, tmp_path):
        config = {
            "min_resolution": "1920x1080",
            "min_bitrate": "5Mbps",
            "codec": "h264,hevc",
        }
        cfg_path = tmp_path / "config.toml"
        save_config(config, cfg_path)
        loaded = load_config(cfg_path)
        assert loaded["min_resolution"] == "1920x1080"
        assert loaded["min_bitrate"] == "5Mbps"
        assert loaded["codec"] == "h264,hevc"


# ---------------------------------------------------------------------------
# ignore_file and log config fields
# ---------------------------------------------------------------------------


class TestIgnoreFileLogConfig:
    def test_ignore_file_default_none(self):
        assert DEFAULTS["ignore_file"] is None

    def test_log_default_none(self):
        assert DEFAULTS["log"] is None

    def test_load_valid_ignore_file(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('ignore_file = "/tmp/my-ignored.json"\n')
        config = load_config(cfg)
        assert config["ignore_file"] == "/tmp/my-ignored.json"

    def test_load_valid_log(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('log = "/tmp/actions.jsonl"\n')
        config = load_config(cfg)
        assert config["log"] == "/tmp/actions.jsonl"

    def test_load_ignore_file_wrong_type_warns(self, tmp_path):
        import warnings

        cfg = tmp_path / "config.toml"
        cfg.write_text("ignore_file = 42\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "ignore_file" not in config
        assert any("ignore_file" in str(warning.message) for warning in w)

    def test_load_log_wrong_type_warns(self, tmp_path):
        import warnings

        cfg = tmp_path / "config.toml"
        cfg.write_text("log = true\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(cfg)
        assert "log" not in config
        assert any("log" in str(warning.message) for warning in w)

    def test_merge_ignore_file_from_config(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.directories = ["."]
        args.reference = None
        args.output = None
        args.interactive = False
        args.dry_run = False
        args.save_config = False
        args.no_config = False
        args.show_config = False
        args.print_completion = None
        config = {"ignore_file": "/custom/ignored.json"}
        merged = merge_config(args, config)
        assert merged.ignore_file == "/custom/ignored.json"

    def test_merge_log_from_config(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.directories = ["."]
        args.reference = None
        args.output = None
        args.interactive = False
        args.dry_run = False
        args.save_config = False
        args.no_config = False
        args.show_config = False
        args.print_completion = None
        config = {"log": "/custom/actions.jsonl"}
        merged = merge_config(args, config)
        assert merged.log == "/custom/actions.jsonl"

    def test_merge_cli_overrides_config_ignore_file(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.directories = ["."]
        args.reference = None
        args.output = None
        args.interactive = False
        args.dry_run = False
        args.save_config = False
        args.no_config = False
        args.show_config = False
        args.print_completion = None
        args.ignore_file = "/cli/ignored.json"
        config = {"ignore_file": "/config/ignored.json"}
        merged = merge_config(args, config)
        assert merged.ignore_file == "/cli/ignored.json"

    def test_save_and_load_ignore_file(self, tmp_path):
        config = {"ignore_file": "/my/ignored.json"}
        cfg_path = tmp_path / "config.toml"
        save_config(config, cfg_path)
        loaded = load_config(cfg_path)
        assert loaded["ignore_file"] == "/my/ignored.json"

    def test_save_and_load_log(self, tmp_path):
        config = {"log": "/my/actions.jsonl"}
        cfg_path = tmp_path / "config.toml"
        save_config(config, cfg_path)
        loaded = load_config(cfg_path)
        assert loaded["log"] == "/my/actions.jsonl"


# ---------------------------------------------------------------------------
# json_envelope validation
# ---------------------------------------------------------------------------


class TestJsonEnvelopeValidation:
    def test_valid_true(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("json_envelope = true\n")
        loaded = load_config(cfg_path)
        assert loaded["json_envelope"] is True

    def test_invalid_type_rejected(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text('json_envelope = "yes"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loaded = load_config(cfg_path)
        assert "json_envelope" not in loaded
        assert any("must be a boolean" in str(warning.message) for warning in w)

    def test_cli_overrides_config(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.json_envelope = True
        config = {"json_envelope": False}
        merged = merge_config(args, config)
        assert merged.json_envelope is True

    def test_save_and_load_round_trip(self, tmp_path):
        config = {"json_envelope": True}
        cfg_path = tmp_path / "config.toml"
        save_config(config, cfg_path)
        loaded = load_config(cfg_path)
        assert loaded["json_envelope"] is True


# ---------------------------------------------------------------------------
# rotation_invariant config validation
# ---------------------------------------------------------------------------


class TestRotationInvariantConfig:
    def test_default_is_none(self):
        assert DEFAULTS["rotation_invariant"] is None

    def test_load_true(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("rotation_invariant = true\n")
        loaded = load_config(cfg_path)
        assert loaded["rotation_invariant"] is True

    def test_load_false(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("rotation_invariant = false\n")
        loaded = load_config(cfg_path)
        assert loaded["rotation_invariant"] is False

    def test_invalid_type_rejected(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text('rotation_invariant = "yes"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loaded = load_config(cfg_path)
        assert "rotation_invariant" not in loaded
        assert any("must be a boolean" in str(warning.message) for warning in w)

    def test_cli_overrides_config(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.rotation_invariant = True
        config = {"rotation_invariant": False}
        merged = merge_config(args, config)
        assert merged.rotation_invariant is True

    def test_config_fallback(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"rotation_invariant": True}
        merged = merge_config(args, config)
        assert merged.rotation_invariant is True

    def test_save_and_load_round_trip(self, tmp_path):
        config = {"rotation_invariant": True}
        cfg_path = tmp_path / "config.toml"
        save_config(config, cfg_path)
        loaded = load_config(cfg_path)
        assert loaded["rotation_invariant"] is True


# ---------------------------------------------------------------------------
# mode config validation
# ---------------------------------------------------------------------------


class TestModeConfig:
    def test_mode_in_defaults(self):
        assert "mode" in DEFAULTS
        assert DEFAULTS["mode"] == "video"

    def test_load_valid_mode(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('mode = "image"\n')
        config = load_config(config_file)
        assert config["mode"] == "image"

    def test_load_invalid_mode(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('mode = "podcast"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(config_file)
        assert "mode" not in config
        assert any("mode" in str(warning.message) for warning in w)

    def test_merge_mode_override(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"mode": "image"}
        merged = merge_config(args, config)
        assert merged.mode == "image"

    def test_load_valid_mode_auto(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('mode = "auto"\n')
        config = load_config(config_file)
        assert config["mode"] == "auto"

    def test_merge_mode_auto_from_profile(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        profile = {"mode": "auto"}
        merged = merge_config(args, {}, profile)
        assert merged.mode == "auto"


# ---------------------------------------------------------------------------
# min_score config validation
# ---------------------------------------------------------------------------


class TestMinScoreConfig:
    def test_min_score_in_defaults(self):
        assert "min_score" in DEFAULTS
        assert DEFAULTS["min_score"] is None

    def test_load_config_min_score(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("min_score = 80\n")
        config = load_config(config_file)
        assert config["min_score"] == 80

    def test_load_config_min_score_invalid(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('min_score = "high"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(config_file)
        assert "min_score" not in config
        assert len(w) == 1

    def test_load_config_min_score_out_of_range(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("min_score = 150\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(config_file)
        assert "min_score" not in config
        assert len(w) == 1

    def test_load_config_min_score_bool_rejected(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("min_score = true\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(config_file)
        assert "min_score" not in config
        assert len(w) == 1

    def test_save_config_min_score(self, tmp_path):
        config_file = tmp_path / "config.toml"
        save_config({"min_score": 80}, config_file)
        result = load_config(config_file)
        assert result["min_score"] == 80

    def test_merge_config_min_score_cli_overrides(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.min_score = 80
        config = {"min_score": 60}
        merged = merge_config(args, config)
        assert merged.min_score == 80

    def test_merge_config_min_score_from_config(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"min_score": 60}
        merged = merge_config(args, config)
        assert merged.min_score == 60


# ---------------------------------------------------------------------------
# validate_profile_name
# ---------------------------------------------------------------------------


class TestValidateProfileName:
    def test_valid_simple(self):
        validate_profile_name("photos")

    def test_valid_with_digits(self):
        validate_profile_name("camera-roll-2024")

    def test_valid_with_dots_underscores(self):
        validate_profile_name("my_profile.v2")

    def test_valid_all_chars(self):
        validate_profile_name("a-b_c.d0")

    def test_reject_empty(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("")

    def test_reject_leading_whitespace(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name(" photos")

    def test_reject_trailing_whitespace(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("photos ")

    def test_reject_slash(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("foo/bar")

    def test_reject_backslash(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("foo\\bar")

    def test_reject_path_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_profile_name("..")

    def test_reject_path_traversal_prefix(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_profile_name("..hidden")

    def test_reject_special_chars(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("hello world")


# ---------------------------------------------------------------------------
# get_profiles_dir / get_profile_path
# ---------------------------------------------------------------------------


class TestGetProfilesDir:
    def test_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = get_profiles_dir()
        assert path == tmp_path / "duplicates-detector" / "profiles"

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        path = get_profiles_dir()
        assert path.name == "profiles"
        assert "duplicates-detector" in str(path)
        assert ".config" in str(path)


class TestGetProfilePath:
    def test_returns_toml(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = get_profile_path("photos")
        assert path == tmp_path / "duplicates-detector" / "profiles" / "photos.toml"

    def test_raises_on_invalid_name(self):
        with pytest.raises(ValueError):
            get_profile_path("foo/bar")


# ---------------------------------------------------------------------------
# load_profile
# ---------------------------------------------------------------------------


class TestLoadProfile:
    def test_valid_profile(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "photos.toml").write_text('mode = "image"\ncontent = true\n')
        result = load_profile("photos")
        assert result == {"mode": "image", "content": True}

    def test_unknown_keys_warned_and_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text('mode = "image"\nunknown_key = 42\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_profile("test")
        assert "unknown_key" not in result
        assert result == {"mode": "image"}
        assert any("unknown key" in str(warning.message).lower() for warning in w)

    def test_invalid_field_warned_and_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "test.toml").write_text('mode = "image"\nthreshold = "not_an_int"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_profile("test")
        assert "threshold" not in result
        assert result == {"mode": "image"}
        assert len(w) >= 1

    def test_missing_file_exits(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with pytest.raises(SystemExit):
            load_profile("nonexistent")

    def test_corrupt_toml_exits(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile_dir = tmp_path / "duplicates-detector" / "profiles"
        profile_dir.mkdir(parents=True)
        (profile_dir / "bad.toml").write_text("this is not valid toml [[[")
        with pytest.raises(SystemExit):
            load_profile("bad")

    def test_invalid_name_exits(self):
        with pytest.raises(SystemExit):
            load_profile("foo/bar")


# ---------------------------------------------------------------------------
# save_profile
# ---------------------------------------------------------------------------


class TestSaveProfile:
    def test_writes_toml(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = save_profile("photos", {"mode": "image", "content": True})
        assert path.exists()
        content = path.read_text()
        assert "mode" in content
        assert "image" in content
        assert "--save-profile photos" in content

    def test_creates_parent_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_profile("new-profile", {"threshold": 80})
        assert (tmp_path / "duplicates-detector" / "profiles" / "new-profile.toml").exists()

    def test_round_trip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        original = {"mode": "image", "content": True, "threshold": 80}
        save_profile("roundtrip", original)
        loaded = load_profile("roundtrip")
        assert loaded == original

    def test_empty_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = save_profile("empty", {})
        assert path.exists()
        loaded = load_profile("empty")
        assert loaded == {}


# ---------------------------------------------------------------------------
# merge_config with profile
# ---------------------------------------------------------------------------


class TestMergeConfigWithProfile:
    def test_profile_overrides_config(self):
        """Profile values override global config values."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"threshold": 60}
        profile = {"threshold": 80}
        merged = merge_config(args, config, profile)
        assert merged.threshold == 80

    def test_cli_overrides_profile(self):
        """CLI values override profile values."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.threshold = 90
        config = {"threshold": 60}
        profile = {"threshold": 80}
        merged = merge_config(args, config, profile)
        assert merged.threshold == 90

    def test_profile_fills_gap(self):
        """Profile provides a value when neither CLI nor config has it."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {}
        profile = {"threshold": 75}
        merged = merge_config(args, config, profile)
        assert merged.threshold == 75

    def test_exclude_additive_all_layers(self):
        """Exclude patterns are additive across config, profile, and CLI."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.exclude = ["*.tmp"]
        config = {"exclude": ["*.log"]}
        profile = {"exclude": ["*.bak"]}
        merged = merge_config(args, config, profile)
        assert merged.exclude == ["*.log", "*.bak", "*.tmp"]

    def test_weights_cli_over_profile_over_config(self):
        """Weights priority: CLI > profile > config."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"weights": {"filename": 50, "duration": 30, "resolution": 10, "file_size": 10}}
        profile = {"weights": {"filename": 40, "duration": 20, "resolution": 20, "file_size": 20}}
        merged = merge_config(args, config, profile)
        assert "filename=40" in merged.weights

    def test_weights_cli_wins(self):
        """CLI weights override profile weights."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.weights = "filename=60,duration=20,resolution=10,filesize=10"
        profile = {"weights": {"filename": 40, "duration": 20, "resolution": 20, "file_size": 20}}
        merged = merge_config(args, {}, profile)
        assert merged.weights == "filename=60,duration=20,resolution=10,filesize=10"

    def test_size_fields_parsed_from_profile(self):
        """Size fields in profile are parsed via parse_size()."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        profile = {"min_size": "10MB"}
        merged = merge_config(args, {}, profile)
        assert merged.min_size == 10 * 1024 * 1024

    def test_no_profile_backward_compat(self):
        """Passing no profile gives identical behavior to old merge_config."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"threshold": 60}
        merged_without = merge_config(args, config)
        merged_with_none = merge_config(args, config, None)
        merged_with_empty = merge_config(args, config, {})
        assert vars(merged_without) == vars(merged_with_none) == vars(merged_with_empty)


# ---------------------------------------------------------------------------
# content_method config
# ---------------------------------------------------------------------------


class TestContentMethodConfig:
    """Tests for content_method in config/profile validation."""

    def test_defaults_entry(self):
        assert "content_method" in DEFAULTS
        assert DEFAULTS["content_method"] is None

    def test_valid_phash(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('content_method = "phash"\n')
        config = load_config(config_file)
        assert config["content_method"] == "phash"

    def test_valid_ssim(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('content_method = "ssim"\n')
        config = load_config(config_file)
        assert config["content_method"] == "ssim"

    def test_valid_clip(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('content_method = "clip"\n')
        config = load_config(config_file)
        assert config["content_method"] == "clip"

    def test_invalid_value_warns_and_skips(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('content_method = "invalid"\n')
        with pytest.warns(UserWarning, match="content_method"):
            config = load_config(config_file)
        assert "content_method" not in config

    def test_non_string_warns_and_skips(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("content_method = 42\n")
        with pytest.warns(UserWarning, match="content_method"):
            config = load_config(config_file)
        assert "content_method" not in config

    def test_cli_overrides_config(self):
        """CLI content_method overrides config file."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.content_method = "ssim"
        config = {"content_method": "phash"}
        merged = merge_config(args, config)
        assert merged.content_method == "ssim"

    def test_config_used_when_cli_none(self):
        """Config content_method used when CLI is None."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"content_method": "ssim"}
        merged = merge_config(args, config)
        assert merged.content_method == "ssim"

    def test_save_load_roundtrip(self, tmp_path):
        """content_method survives save/load."""
        config_path = tmp_path / "config.toml"
        save_config({"content_method": "ssim"}, config_path=config_path)
        loaded = load_config(config_path=config_path)
        assert loaded["content_method"] == "ssim"


# ---------------------------------------------------------------------------
# audio / no_audio_cache config fields
# ---------------------------------------------------------------------------


class TestAudioConfig:
    def test_defaults_contain_audio_fields(self):
        """DEFAULTS includes audio and no_audio_cache."""
        assert "audio" in DEFAULTS
        assert DEFAULTS["audio"] is False
        assert "no_audio_cache" in DEFAULTS
        assert DEFAULTS["no_audio_cache"] is False

    def test_cli_overrides_config(self):
        """CLI audio=True overrides config audio=False."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.audio = True
        config = {"audio": False}
        merged = merge_config(args, config)
        assert merged.audio is True

    def test_config_used_when_cli_none(self):
        """Config audio=True used when CLI is None."""
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"audio": True}
        merged = merge_config(args, config)
        assert merged.audio is True

    def test_save_load_roundtrip(self, tmp_path):
        """audio and no_audio_cache survive save/load."""
        config_path = tmp_path / "config.toml"
        save_config({"audio": True, "no_audio_cache": True}, config_path=config_path)
        loaded = load_config(config_path=config_path)
        assert loaded["audio"] is True
        assert loaded["no_audio_cache"] is True


# ---------------------------------------------------------------------------
# embed_thumbnails / thumbnail_size config fields
# ---------------------------------------------------------------------------


class TestEmbedThumbnailsConfig:
    def test_embed_thumbnails_in_defaults(self):
        assert "embed_thumbnails" in DEFAULTS
        assert DEFAULTS["embed_thumbnails"] is False

    def test_embed_thumbnails_in_bool_fields(self):
        assert "embed_thumbnails" in _BOOL_FIELDS

    def test_thumbnail_size_in_defaults(self):
        assert "thumbnail_size" in DEFAULTS
        assert DEFAULTS["thumbnail_size"] is None

    def test_save_config_embed_thumbnails(self, tmp_path):
        config_path = tmp_path / "config.toml"
        save_config({"embed_thumbnails": True}, config_path=config_path)
        loaded = load_config(config_path=config_path)
        assert loaded["embed_thumbnails"] is True

    def test_save_config_thumbnail_size(self, tmp_path):
        config_path = tmp_path / "config.toml"
        save_config({"thumbnail_size": "320x180"}, config_path=config_path)
        loaded = load_config(config_path=config_path)
        assert loaded["thumbnail_size"] == "320x180"

    def test_load_config_embed_thumbnails(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("embed_thumbnails = true\n")
        loaded = load_config(config_path=config_path)
        assert loaded["embed_thumbnails"] is True

    def test_load_config_thumbnail_size(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text('thumbnail_size = "320x180"\n')
        loaded = load_config(config_path=config_path)
        assert loaded["thumbnail_size"] == "320x180"

    def test_merge_config_cli_overrides_thumbnail_size(self):
        defaults: dict[str, Any] = {k: None for k in DEFAULTS}
        defaults["thumbnail_size"] = "160x90"
        args = argparse.Namespace(**defaults)
        config: dict[str, Any] = {"thumbnail_size": "320x180"}
        merged = merge_config(args, config)
        assert merged.thumbnail_size == "160x90"

    def test_invalid_thumbnail_size_rejected(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text('thumbnail_size = "invalid"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loaded = load_config(config_path=config_path)
        assert "thumbnail_size" not in loaded
        assert any("thumbnail_size" in str(warning.message) for warning in w)

    def test_thumbnail_size_non_string_rejected(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("thumbnail_size = 160\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loaded = load_config(config_path=config_path)
        assert "thumbnail_size" not in loaded
        assert any("thumbnail_size" in str(warning.message) for warning in w)

    def test_thumbnail_size_zero_dimensions_rejected(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text('thumbnail_size = "0x0"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loaded = load_config(config_path=config_path)
        assert "thumbnail_size" not in loaded
        assert any("thumbnail_size" in str(warning.message) for warning in w)


# ---------------------------------------------------------------------------
# machine_progress config field
# ---------------------------------------------------------------------------


class TestMachineProgressConfig:
    def test_machine_progress_in_defaults(self):
        """DEFAULTS includes machine_progress with value False."""
        assert "machine_progress" in DEFAULTS
        assert DEFAULTS["machine_progress"] is False

    def test_machine_progress_in_bool_fields(self):
        """machine_progress is in _BOOL_FIELDS for proper type validation."""
        assert "machine_progress" in _BOOL_FIELDS

    def test_load_config_machine_progress_true(self, tmp_path):
        """machine_progress = true is loaded correctly from TOML."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("machine_progress = true\n")
        loaded = load_config(config_path=config_path)
        assert loaded["machine_progress"] is True

    def test_load_config_machine_progress_non_bool_rejected(self, tmp_path):
        """Non-boolean machine_progress value is warned and skipped."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('machine_progress = "yes"\n')
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loaded = load_config(config_path=config_path)
        assert "machine_progress" not in loaded
        assert any("machine_progress" in str(warning.message) for warning in w)

    def test_save_config_machine_progress(self, tmp_path):
        """machine_progress round-trips through save_config/load_config."""
        config_path = tmp_path / "config.toml"
        save_config({"machine_progress": True}, config_path=config_path)
        loaded = load_config(config_path=config_path)
        assert loaded["machine_progress"] is True

    def test_merge_config_cli_overrides_machine_progress(self):
        """CLI machine_progress=True overrides config value."""
        defaults: dict[str, Any] = {k: None for k in DEFAULTS}
        defaults["machine_progress"] = True
        args = argparse.Namespace(**defaults)
        config: dict[str, Any] = {"machine_progress": False}
        merged = merge_config(args, config)
        assert merged.machine_progress is True


# ---------------------------------------------------------------------------
# Mode StrEnum
# ---------------------------------------------------------------------------


class TestModeEnum:
    """Tests for the Mode StrEnum."""

    def test_mode_values_are_strings(self):
        """Mode members are strings (StrEnum)."""
        assert isinstance(Mode.VIDEO, str)
        assert isinstance(Mode.IMAGE, str)
        assert isinstance(Mode.AUDIO, str)
        assert isinstance(Mode.AUTO, str)
        assert isinstance(Mode.DOCUMENT, str)

    def test_mode_string_equality(self):
        """Mode members compare equal to plain strings."""
        assert Mode.VIDEO == "video"
        assert Mode.IMAGE == "image"
        assert Mode.AUDIO == "audio"
        assert Mode.AUTO == "auto"
        assert Mode.DOCUMENT == "document"

    def test_mode_string_inequality(self):
        """Mode members are not equal to unrelated strings."""
        assert Mode.VIDEO != "image"
        assert Mode.IMAGE != "video"
        assert Mode.AUDIO != "auto"
        assert Mode.AUTO != "audio"
        assert Mode.DOCUMENT != "video"

    def test_mode_in_membership(self):
        """Mode members work with 'in' on plain-string collections."""
        choices = ["video", "image", "audio", "auto", "document"]
        assert Mode.VIDEO in choices
        assert Mode.IMAGE in choices
        assert Mode.AUDIO in choices
        assert Mode.AUTO in choices
        assert Mode.DOCUMENT in choices

    def test_mode_members_count(self):
        """Exactly five modes defined."""
        assert len(Mode) == 5

    def test_mode_from_string(self):
        """Mode can be constructed from a plain string."""
        assert Mode("video") is Mode.VIDEO
        assert Mode("image") is Mode.IMAGE
        assert Mode("audio") is Mode.AUDIO
        assert Mode("auto") is Mode.AUTO
        assert Mode("document") is Mode.DOCUMENT

    def test_mode_invalid_raises(self):
        """Creating Mode from an unknown string raises ValueError."""
        with pytest.raises(ValueError):
            Mode("invalid")

    def test_defaults_mode_is_mode_video(self):
        """DEFAULTS['mode'] is Mode.VIDEO."""
        assert DEFAULTS["mode"] is Mode.VIDEO
        assert DEFAULTS["mode"] == "video"

    def test_mode_usable_as_dict_key(self):
        """Mode members can be used as dict keys and retrieved via strings."""
        d: dict[str, int] = {Mode.VIDEO: 1, Mode.IMAGE: 2}
        assert d["video"] == 1
        assert d[Mode.IMAGE] == 2

    def test_mode_validate_field_accepts_enum(self):
        """Config validation accepts Mode enum values for the mode field."""
        config_file = None  # not needed — we test _validate_field indirectly via load_config
        # Mode values should pass validation in load_config
        from duplicates_detector.config import _validate_field

        assert _validate_field("mode", "video") is True
        assert _validate_field("mode", "image") is True
        assert _validate_field("mode", "audio") is True
        assert _validate_field("mode", "auto") is True
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert _validate_field("mode", "invalid") is False
            assert len(w) == 1


# ---------------------------------------------------------------------------
# Sidecar config
# ---------------------------------------------------------------------------


class TestSidecarConfig:
    def test_sidecar_extensions_in_defaults(self):
        assert "sidecar_extensions" in DEFAULTS
        assert DEFAULTS["sidecar_extensions"] == ".xmp,.aae,.thm,.json"

    def test_no_sidecars_in_defaults(self):
        assert "no_sidecars" in DEFAULTS
        assert DEFAULTS["no_sidecars"] is False

    def test_no_sidecars_in_bool_fields(self):
        from duplicates_detector.config import _BOOL_FIELDS

        assert "no_sidecars" in _BOOL_FIELDS

    def test_load_config_sidecar_extensions(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('sidecar_extensions = ".xmp,.srt"\n')
        result = load_config(cfg_file)
        assert result["sidecar_extensions"] == ".xmp,.srt"

    def test_load_config_sidecar_extensions_wrong_type(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("sidecar_extensions = 42\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = load_config(cfg_file)
        assert "sidecar_extensions" not in result
        assert len(w) == 1

    def test_load_config_no_sidecars(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("no_sidecars = true\n")
        result = load_config(cfg_file)
        assert result["no_sidecars"] is True

    def test_merge_config_applies_sidecar_extensions(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        config = {"sidecar_extensions": ".xmp,.srt"}
        merged = merge_config(args, config)
        assert merged.sidecar_extensions == ".xmp,.srt"

    def test_merge_config_cli_overrides_sidecar_extensions(self):
        args = argparse.Namespace(**{k: None for k in DEFAULTS})
        args.sidecar_extensions = ".xmp"
        config = {"sidecar_extensions": ".xmp,.srt,.aae"}
        merged = merge_config(args, config)
        assert merged.sidecar_extensions == ".xmp"


# ---------------------------------------------------------------------------
# Mode.DOCUMENT
# ---------------------------------------------------------------------------


class TestModeDocument:
    def test_document_value(self):
        """Mode.DOCUMENT has the string value 'document'."""
        assert Mode.DOCUMENT == "document"

    def test_document_str(self):
        """str(Mode.DOCUMENT) returns 'document'."""
        assert str(Mode.DOCUMENT) == "document"

    def test_document_in_tuple(self):
        """'document' is in tuple(Mode)."""
        assert "document" in tuple(Mode)
