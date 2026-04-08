from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TextIO


class ActionLog:
    """Append-only JSON-lines log for deletion/move/link actions.

    Each call to :meth:`log` writes one self-contained JSON object per line
    and flushes immediately for crash safety.  When the log file is not open
    (or was never opened), :meth:`log` is a silent no-op.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: TextIO | None = None

    def open(self) -> None:
        """Open the log file for appending.  Creates parent dirs if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a", encoding="utf-8")

    def close(self) -> None:
        """Close the log file."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> ActionLog:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def log(
        self,
        *,
        action: str,
        path: Path,
        score: float,
        strategy: str,
        kept: Path,
        bytes_freed: int,
        destination: Path | None = None,
        dry_run: bool = False,
        sidecar_of: Path | None = None,
    ) -> None:
        """Append a single action record as one JSON line."""
        if self._file is None:
            return
        record: dict = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "path": str(path.resolve()),
            "score": score,
            "strategy": strategy,
            "kept": str(kept.resolve()),
            "bytes_freed": bytes_freed,
        }
        if destination is not None:
            record["destination"] = str(destination.resolve())
        if dry_run:
            record["dry_run"] = True
        if sidecar_of is not None:
            record["sidecar_of"] = str(sidecar_of.resolve())
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()
