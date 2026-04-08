from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def get_default_ignore_path() -> Path:
    """Return the default ignore-list path ($XDG_DATA_HOME or ~/.local/share fallback)."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "duplicates-detector" / "ignored-pairs.json"


class IgnoreList:
    """Persistent set of ignored file-pair keys.

    Pairs are stored with paths sorted lexicographically so lookup is
    order-independent — ``add(A, B)`` followed by ``contains(B, A)``
    returns ``True``.  Resolved paths are used to handle symlinks and
    relative path differences.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_default_ignore_path()
        self._pairs: set[tuple[str, str]] = set()
        self._load()

    def _load(self) -> None:
        """Load from disk.  Missing or corrupt files start empty."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, list) and len(entry) == 2:
                        self._pairs.add(self._key(Path(entry[0]), Path(entry[1])))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass  # Corrupt file — start fresh

    def save(self) -> None:
        """Write the ignore list to disk.  Creates parent dirs.

        Uses atomic write (tempfile + rename) to avoid corruption.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = sorted([list(p) for p in self._pairs])
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, self._path)

    @staticmethod
    def _key(path_a: Path, path_b: Path) -> tuple[str, str]:
        """Canonical sorted key for a pair."""
        a, b = str(path_a.resolve()), str(path_b.resolve())
        return (a, b) if a <= b else (b, a)

    def add(self, path_a: Path, path_b: Path) -> None:
        """Add a pair to the ignore list."""
        self._pairs.add(self._key(path_a, path_b))

    def contains(self, path_a: Path, path_b: Path) -> bool:
        """Check if a pair is in the ignore list."""
        return self._key(path_a, path_b) in self._pairs

    def clear(self) -> None:
        """Remove all entries."""
        self._pairs.clear()

    def __len__(self) -> int:
        return len(self._pairs)
