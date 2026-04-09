from __future__ import annotations

import argparse
import os
import re
import sys
import warnings
from enum import Enum
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]  # stdlib 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w
from rich.console import Console
from rich.table import Table

from duplicates_detector.filters import format_size, parse_bitrate, parse_resolution, parse_size


class Mode(str, Enum):
    """Scanning mode — values compare equal to plain strings."""

    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    AUTO = "auto"
    DOCUMENT = "document"

    def __str__(self) -> str:
        return self.value


_CONFIG_FILENAME = "config.toml"
_PROFILES_DIRNAME = "profiles"
_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")

DEFAULTS: dict = {
    "threshold": 50,
    "extensions": None,
    "workers": 0,
    "keep": None,
    "action": "delete",
    "move_to_dir": None,
    "cache_dir": None,
    "format": "table",
    "verbose": False,
    "quiet": False,
    "no_color": False,
    "content": False,
    "group": False,
    "no_recursive": False,
    "no_content_cache": False,
    "no_metadata_cache": False,
    "min_size": None,
    "max_size": None,
    "min_duration": None,
    "max_duration": None,
    "min_resolution": None,
    "max_resolution": None,
    "min_bitrate": None,
    "max_bitrate": None,
    "codec": None,
    "ignore_file": None,
    "log": None,
    "sort": "score",
    "limit": None,
    "min_score": None,
    "weights": None,
    "exclude": [],
    "rotation_invariant": None,
    "content_method": None,
    "json_envelope": False,
    "mode": Mode.VIDEO,
    "audio": False,
    "no_audio_cache": False,
    "embed_thumbnails": False,
    "thumbnail_size": None,
    "machine_progress": False,
    "resume": None,
    "list_sessions": False,
    "list_sessions_json": False,
    "clear_sessions": False,
    "delete_session": None,
    "pause_file": None,
    "cache_stats": False,
    "no_pre_hash": False,
    "sidecar_extensions": ".xmp,.aae,.thm,.json",
    "no_sidecars": False,
}

_MODE_VALUES = tuple(Mode)
_KEEP_CHOICES = {"newest", "oldest", "biggest", "smallest", "longest", "highest-res", "edited"}
_ACTION_CHOICES = {"delete", "trash", "move-to", "hardlink", "symlink", "reflink"}
_FORMAT_CHOICES = {"table", "json", "csv", "shell", "html", "markdown"}
_SORT_CHOICES = {"score", "size", "path", "mtime"}
_CONTENT_METHOD_CHOICES = {"phash", "ssim", "clip", "simhash", "tfidf"}
_WEIGHT_KEYS = {
    "filename",
    "duration",
    "resolution",
    "filesize",
    "file_size",
    "content",
    "exif",
    "audio",
    "tags",
    "directory",
    "page_count",
    "doc_meta",
}
_WEIGHT_CANONICAL: dict[str, str] = {
    "filename": "filename",
    "duration": "duration",
    "resolution": "resolution",
    "filesize": "file_size",
    "file_size": "file_size",
    "content": "content",
    "exif": "exif",
    "audio": "audio",
    "tags": "tags",
    "directory": "directory",
    "page_count": "page_count",
    "doc_meta": "doc_meta",
}

_BOOL_FIELDS = {
    "verbose",
    "quiet",
    "no_color",
    "content",
    "group",
    "no_recursive",
    "no_content_cache",
    "no_metadata_cache",
    "json_envelope",
    "rotation_invariant",
    "audio",
    "no_audio_cache",
    "embed_thumbnails",
    "machine_progress",
    "list_sessions",
    "list_sessions_json",
    "clear_sessions",
    "cache_stats",
    "no_pre_hash",
    "no_sidecars",
}

_SIZE_FIELDS = {"min_size", "max_size"}
_RESOLUTION_FIELDS = {"min_resolution", "max_resolution"}
_BITRATE_FIELDS = {"min_bitrate", "max_bitrate"}


def _config_base_dir() -> Path:
    """Return the XDG_CONFIG_HOME base (``~/.config`` fallback)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def get_config_path() -> Path:
    """Return the config file path (XDG_CONFIG_HOME or ~/.config fallback)."""
    return _config_base_dir() / "duplicates-detector" / _CONFIG_FILENAME


def validate_profile_name(name: str) -> None:
    """Raise ``ValueError`` if *name* is not a safe profile name.

    Accepts letters, digits, ``_``, ``-``, and ``.``.
    Rejects empty names, leading/trailing whitespace, path traversal
    segments (``..``), and any ``/`` or ``\\``.
    """
    if not name or name != name.strip():
        raise ValueError(f"Invalid profile name: {name!r}")
    if ".." in name:
        raise ValueError(f"Invalid profile name (path traversal): {name!r}")
    if not _PROFILE_NAME_RE.match(name):
        raise ValueError(f"Invalid profile name: {name!r}")


def get_profiles_dir() -> Path:
    """Return the profiles directory (XDG_CONFIG_HOME or ~/.config fallback)."""
    return _config_base_dir() / "duplicates-detector" / _PROFILES_DIRNAME


def get_profile_path(name: str) -> Path:
    """Return the validated path for a named profile."""
    validate_profile_name(name)
    return get_profiles_dir() / f"{name}.toml"


def load_profile(name: str) -> dict:
    """Load a named profile TOML file.

    Unlike :func:`load_config`, missing or corrupt profiles are **fatal**
    (``SystemExit(1)``) because the user explicitly requested ``--profile``.
    Per-field validation reuses :func:`_validate_field` (warn + skip).
    """
    try:
        profile_path = get_profile_path(name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    if not profile_path.exists():
        print(f"Error: profile {name!r} not found: {profile_path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        raw = profile_path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"Error: profile {name!r} is corrupt: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    validated: dict = {}
    for key, value in data.items():
        if key not in DEFAULTS:
            warnings.warn(
                f"Profile {name!r}: unknown key {key!r}, skipping",
                stacklevel=2,
            )
            continue
        if not _validate_field(key, value):
            continue
        validated[key] = value
    return validated


def save_profile(name: str, config: dict) -> Path:
    """Write *config* as a named profile TOML file.

    Creates the profiles directory if needed.  Returns the written path.
    """
    profile_path = get_profile_path(name)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# duplicates-detector profile\n"
        f"# Generated by: duplicates-detector --save-profile {name}\n"
        f"# Location: {profile_path}\n\n"
    )

    toml_bytes = tomli_w.dumps(config).encode("utf-8") if config else b""
    profile_path.write_bytes(header.encode("utf-8") + toml_bytes)
    return profile_path


def load_config(config_path: Path | None = None) -> dict:
    """Load and validate the config file.

    Returns ``{}`` if the file doesn't exist.  Corrupt TOML or invalid
    values produce warnings and are skipped (never fatal).
    """
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        return {}

    try:
        raw = config_path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        warnings.warn(
            f"Config file is corrupt, ignoring: {exc}",
            stacklevel=2,
        )
        return {}

    validated: dict = {}
    for key, value in data.items():
        if key not in DEFAULTS:
            warnings.warn(
                f"Unknown config key {key!r}, skipping",
                stacklevel=2,
            )
            continue
        if not _validate_field(key, value):
            continue
        validated[key] = value
    return validated


def _validate_field(key: str, value: object) -> bool:
    """Validate a single config field, returning True if valid."""
    if key == "threshold":
        if not isinstance(value, int) or isinstance(value, bool):
            warnings.warn(
                f"Config: 'threshold' must be an integer, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        if not (0 <= value <= 100):
            warnings.warn(
                f"Config: 'threshold' must be 0-100, got {value}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "limit":
        if not isinstance(value, int) or isinstance(value, bool):
            warnings.warn(
                f"Config: 'limit' must be an integer, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        if value <= 0:
            warnings.warn(
                f"Config: 'limit' must be > 0, got {value}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "min_score":
        if not isinstance(value, int) or isinstance(value, bool):
            warnings.warn(
                f"Config: 'min_score' must be an integer, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        if not (0 <= value <= 100):
            warnings.warn(
                f"Config: 'min_score' must be 0-100, got {value}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "workers":
        if not isinstance(value, int) or isinstance(value, bool):
            warnings.warn(
                f"Config: 'workers' must be an integer, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        if value < 0:
            warnings.warn(
                f"Config: 'workers' must be >= 0, got {value}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "keep":
        if not isinstance(value, str) or value not in _KEEP_CHOICES:
            warnings.warn(
                f"Config: 'keep' must be one of {sorted(_KEEP_CHOICES)}, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "action":
        if not isinstance(value, str) or value not in _ACTION_CHOICES:
            warnings.warn(
                f"Config: 'action' must be one of {sorted(_ACTION_CHOICES)}, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "move_to_dir":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'move_to_dir' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "cache_dir":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'cache_dir' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "sort":
        if not isinstance(value, str) or value not in _SORT_CHOICES:
            warnings.warn(
                f"Config: 'sort' must be one of {sorted(_SORT_CHOICES)}, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "format":
        if not isinstance(value, str) or value not in _FORMAT_CHOICES:
            warnings.warn(
                f"Config: 'format' must be one of {sorted(_FORMAT_CHOICES)}, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    elif key in _BOOL_FIELDS:
        if not isinstance(value, bool):
            warnings.warn(
                f"Config: {key!r} must be a boolean, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "extensions":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'extensions' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key in _SIZE_FIELDS:
        if not isinstance(value, str):
            warnings.warn(
                f"Config: {key!r} must be a string (e.g. '10MB'), got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        try:
            parse_size(value)
        except ValueError:
            warnings.warn(
                f"Config: {key!r} value {value!r} is not a valid size, skipping",
                stacklevel=2,
            )
            return False
    elif key in ("min_duration", "max_duration"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            warnings.warn(
                f"Config: {key!r} must be a number, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        if value < 0:
            warnings.warn(
                f"Config: {key!r} must be >= 0, got {value}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "content_method":
        if not isinstance(value, str) or value not in _CONTENT_METHOD_CHOICES:
            choices = sorted(_CONTENT_METHOD_CHOICES)
            warnings.warn(
                f"Config: 'content_method' must be one of {choices}, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "weights":
        if not isinstance(value, dict):
            warnings.warn(
                f"Config: 'weights' must be a table, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        for k, v in value.items():
            if not isinstance(k, str):
                warnings.warn(
                    f"Config: 'weights' keys must be strings, got {type(k).__name__}, skipping",
                    stacklevel=2,
                )
                return False
            if k not in _WEIGHT_KEYS:
                warnings.warn(
                    f"Config: unknown weight key {k!r}, skipping 'weights'",
                    stacklevel=2,
                )
                return False
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                warnings.warn(
                    f"Config: 'weights' values must be numbers, got {type(v).__name__} for key {k!r}, skipping",
                    stacklevel=2,
                )
                return False
            if v < 0:
                warnings.warn(
                    f"Config: 'weights' values must be non-negative, got {v} for key {k!r}, skipping",
                    stacklevel=2,
                )
                return False
        # Detect alias collisions (e.g. both "filesize" and "file_size")
        canonical_seen: set[str] = set()
        for k in value:
            canon = _WEIGHT_CANONICAL[k]
            if canon in canonical_seen:
                warnings.warn(
                    f"Config: duplicate weight key {k!r} (alias collision), skipping 'weights'",
                    stacklevel=2,
                )
                return False
            canonical_seen.add(canon)
    elif key == "exclude":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            warnings.warn(
                "Config: 'exclude' must be an array of strings, skipping",
                stacklevel=2,
            )
            return False
    elif key in _RESOLUTION_FIELDS:
        if not isinstance(value, str):
            warnings.warn(
                f"Config: {key!r} must be a string (e.g. '1920x1080'), got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        try:
            parse_resolution(value)
        except ValueError:
            warnings.warn(
                f"Config: {key!r} value {value!r} is not a valid resolution, skipping",
                stacklevel=2,
            )
            return False
    elif key in _BITRATE_FIELDS:
        if not isinstance(value, str):
            warnings.warn(
                f"Config: {key!r} must be a string (e.g. '5Mbps'), got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        try:
            parse_bitrate(value)
        except ValueError:
            warnings.warn(
                f"Config: {key!r} value {value!r} is not a valid bitrate, skipping",
                stacklevel=2,
            )
            return False
    elif key == "sidecar_extensions":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'sidecar_extensions' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "codec":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'codec' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "log":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'log' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "ignore_file":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'ignore_file' must be a string, got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "mode":
        if not isinstance(value, str) or value not in _MODE_VALUES:
            warnings.warn(
                f"Config: 'mode' must be 'video', 'image', 'audio', 'auto', or 'document', got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    elif key == "thumbnail_size":
        if not isinstance(value, str):
            warnings.warn(
                f"Config: 'thumbnail_size' must be a string (WxH), got {type(value).__name__}, skipping",
                stacklevel=2,
            )
            return False
        parts = value.lower().split("x")
        if len(parts) != 2:
            warnings.warn(
                f"Config: 'thumbnail_size' must be WxH (e.g. 160x90), got {value!r}, skipping",
                stacklevel=2,
            )
            return False
        try:
            w, h = int(parts[0]), int(parts[1])
        except ValueError:
            warnings.warn(
                f"Config: 'thumbnail_size' must be WxH with integer dimensions, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
        if w <= 0 or h <= 0:
            warnings.warn(
                f"Config: 'thumbnail_size' dimensions must be positive, got {value!r}, skipping",
                stacklevel=2,
            )
            return False
    return True


def save_config(config: dict, config_path: Path | None = None) -> None:
    """Write config dict to TOML file.

    Creates the parent directory if needed.  Only writes keys that
    differ from hardcoded defaults.
    """
    if config_path is None:
        config_path = get_config_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# duplicates-detector configuration\n"
        "# Generated by: duplicates-detector --save-config\n"
        f"# Location: {config_path}\n\n"
    )

    toml_bytes = tomli_w.dumps(config).encode("utf-8") if config else b""
    config_path.write_bytes(header.encode("utf-8") + toml_bytes)


def merge_config(
    args: argparse.Namespace,
    config: dict,
    profile: dict | None = None,
) -> argparse.Namespace:
    """Apply config and profile values as defaults under CLI flags.

    Merge order (later wins): hardcoded defaults → *config* → *profile* → CLI.

    For each configurable field:
    - If CLI explicitly set the value (not None) → keep CLI value
    - Else if profile has the field → use profile value
    - Else if config has the field → use config value
    - Else → keep hardcoded default

    Special: ``exclude`` patterns are merged additively across all layers.
    Size fields from config/profile (strings) are parsed via ``parse_size()``.

    Returns a new Namespace (does not mutate the input).
    """
    if profile is None:
        profile = {}

    merged = argparse.Namespace(**vars(args))

    for key, default in DEFAULTS.items():
        cli_value = getattr(args, key, None)

        if key == "exclude":
            config_excludes = config.get("exclude", [])
            profile_excludes = profile.get("exclude", [])
            cli_excludes = cli_value if cli_value is not None else []
            combined = config_excludes + profile_excludes + cli_excludes
            setattr(merged, key, combined if combined else None)
            continue

        if key == "weights":
            # CLI string takes priority; then profile dict; then config dict
            if cli_value is not None:
                setattr(merged, key, cli_value)
            elif key in profile:
                value = profile[key]
                if isinstance(value, dict):
                    setattr(merged, key, ",".join(f"{k}={v}" for k, v in value.items()))
                else:
                    setattr(merged, key, value)
            elif key in config:
                value = config[key]
                if isinstance(value, dict):
                    setattr(merged, key, ",".join(f"{k}={v}" for k, v in value.items()))
                else:
                    setattr(merged, key, value)
            else:
                setattr(merged, key, default)
            continue

        # CLI explicitly set (not sentinel None) → keep CLI value
        if cli_value is not None:
            setattr(merged, key, cli_value)
            continue

        # Profile has a value → use it (with parsing for size fields)
        if key in profile:
            value = profile[key]
            if key in _SIZE_FIELDS and isinstance(value, str):
                value = parse_size(value)
            setattr(merged, key, value)
            continue

        # Config has a value → use it (with parsing for size fields)
        if key in config:
            value = config[key]
            if key in _SIZE_FIELDS and isinstance(value, str):
                value = parse_size(value)
            setattr(merged, key, value)
            continue

        # Neither CLI nor config nor profile → use hardcoded default
        setattr(merged, key, default)

    return merged


def namespace_to_config(args: argparse.Namespace) -> dict:
    """Extract configurable fields from parsed args into a config dict.

    Only includes fields that differ from hardcoded defaults.
    Converts parsed size values back to human-readable strings.
    """
    config: dict = {}
    for key, default in DEFAULTS.items():
        value = getattr(args, key, None)

        # Convert size int back to string for storage
        if key in _SIZE_FIELDS and isinstance(value, int):
            value = format_size(value)

        # Convert None exclude to empty list for comparison
        if key == "exclude" and value is None:
            value = []

        # Convert weights CLI string to dict for TOML storage
        if key == "weights" and isinstance(value, str):
            from duplicates_detector.comparators import parse_weights

            try:
                value = parse_weights(value)
            except ValueError:
                continue  # Skip unparseable weights — caller should validate first

        if value != default:
            config[key] = value
    return config


def show_config(config: dict) -> None:
    """Pretty-print the resolved config to stdout using Rich."""
    console = Console()
    table = Table(title="duplicates-detector configuration")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    all_keys = sorted(DEFAULTS.keys())
    for key in all_keys:
        if key in config:
            value = config[key]
        else:
            value = DEFAULTS[key]
        table.add_row(key, repr(value))
    console.print(table)
