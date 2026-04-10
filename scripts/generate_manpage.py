#!/usr/bin/env python3
"""Generate the duplicates-detector.1 man page from argparse.

Usage:
    python scripts/generate_manpage.py           # Regenerate man/duplicates-detector.1
    python scripts/generate_manpage.py --check   # Exit non-zero if committed file is stale
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "man" / "duplicates-detector.1"
INCLUDE_FILE = REPO_ROOT / "man" / "includes.1"

_TH_RE = re.compile(r"^\.TH .+$", re.MULTILINE)


def _normalize_th(content: str) -> str:
    """Strip the .TH header for version-insensitive comparison."""
    return _TH_RE.sub("", content, count=1)


def _render_manpage() -> str:
    """Render the man page content as a string."""
    # Import here so the script can be imported without these on sys.path
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from duplicates_detector import __version__
    from duplicates_detector.cli import _build_parser

    from argparse_manpage.manpage import Manpage

    parser = _build_parser()

    data = {
        "version": __version__,
        "project_name": "duplicates-detector",
        "description": "detect duplicate video, image, and audio files",
        "manual_title": "Duplicates Detector Manual",
        "manual_section": "1",
        "format": "pretty",
        "include": str(INCLUDE_FILE) if INCLUDE_FILE.exists() else None,
    }

    return str(Manpage(parser, _data=data, format="pretty"))


def generate(output_path: Path) -> None:
    """Generate the man page and write it to *output_path*."""
    content = _render_manpage()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)


def check(output_path: Path) -> bool:
    """Return True if the committed man page matches a fresh generation."""
    if not output_path.exists():
        return False
    return _normalize_th(_render_manpage()) == _normalize_th(output_path.read_text())


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    import argparse

    ap = argparse.ArgumentParser(description="Generate the duplicates-detector man page.")
    ap.add_argument("--check", action="store_true", help="Check if committed man page is up to date")
    args = ap.parse_args(argv)

    if args.check:
        if check(DEFAULT_OUTPUT):
            print("Man page is up to date.")
        else:
            print(
                "Man page is stale — run: python scripts/generate_manpage.py",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        generate(DEFAULT_OUTPUT)
        print(f"Generated {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
