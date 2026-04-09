#!/usr/bin/env python3
"""Release tooling: stamp changelog, tag, push, extract notes.

Usage:
    python scripts/release.py 1.2.0           # execute release
    python scripts/release.py 1.2.0 --dry-run # preview without changes
    python scripts/release.py extract-notes 1.2.0  # print changelog section (used by CI)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PROJECT_YML = REPO_ROOT / "DuplicatesDetectorGUI" / "project.yml"
UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
MARKETING_VERSION_RE = re.compile(r'(MARKETING_VERSION:\s*")[\d.]+(")')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = argv if argv is not None else sys.argv[1:]

    # Backward compat: bare `release.py 1.2.0` (no subcommand) -> treat as release
    if raw and VERSION_RE.match(raw[0]):
        raw = ["release"] + raw

    parser = argparse.ArgumentParser(description="Release tooling: stamp changelog, tag, push.")
    sub = parser.add_subparsers(dest="command", required=True)

    release_parser = sub.add_parser("release", help="Stamp changelog, tag, and push")
    release_parser.add_argument("version", help="Version to release (X.Y.Z)")
    release_parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")

    notes_parser = sub.add_parser("extract-notes", help="Print changelog notes for a version")
    notes_parser.add_argument("version", help="Version to extract notes for (X.Y.Z)")

    return parser.parse_args(raw)


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _latest_tag_version() -> tuple[int, ...] | None:
    """Return the version tuple of the latest vX.Y.Z tag, or None."""
    result = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=-v:refname"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        m = re.match(r"^v(\d+\.\d+\.\d+)$", line)
        if m:
            return _version_tuple(m.group(1))
    return None


def fetch_remote_tags() -> None:
    """Fetch tags from the remote so local tag list is up to date."""
    result = subprocess.run(
        ["git", "fetch", "--tags"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"Warning: git fetch --tags failed: {result.stderr.strip()}")


def validate_version(version: str) -> None:
    if not VERSION_RE.match(version):
        sys.exit(f"Error: '{version}' is not valid semver (expected X.Y.Z)")

    tag_check = subprocess.run(
        ["git", "tag", "--list", f"v{version}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if tag_check.stdout.strip():
        sys.exit(f"Error: tag v{version} already exists")

    latest = _latest_tag_version()
    if latest is not None and _version_tuple(version) <= latest:
        latest_str = ".".join(str(x) for x in latest)
        sys.exit(f"Error: {version} is not greater than the latest tag ({latest_str})")


def check_clean_tree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.stdout.strip():
        sys.exit("Error: working tree is not clean — commit or stash changes first")


def stamp_changelog(version: str, *, dry_run: bool) -> None:
    text = CHANGELOG.read_text()

    m = UNRELEASED_RE.search(text)
    if m is None:
        sys.exit("Error: could not find '## [Unreleased]' header in CHANGELOG.md")

    # Check if there is content between [Unreleased] and the next version header
    after_header = text[m.end() :]
    next_version = re.search(r"^## \[", after_header, re.MULTILINE)
    content_between = after_header[: next_version.start()] if next_version else after_header
    if not content_between.strip():
        print("Warning: [Unreleased] section is empty")

    today = date.today().isoformat()
    new_header = f"## [Unreleased]\n\n## [{version}] - {today}"
    stamped = text[: m.start()] + new_header + text[m.end() :]

    if dry_run:
        print(f"Would stamp CHANGELOG.md: [Unreleased] -> [{version}] - {today}")
    else:
        CHANGELOG.write_text(stamped)
        print(f"Stamped CHANGELOG.md with [{version}] - {today}")


def extract_release_notes(version: str) -> str:
    """Extract the changelog section for the given version."""
    text = CHANGELOG.read_text()
    header_re = re.compile(rf"^## \[{re.escape(version)}\].*$", re.MULTILINE)
    m = header_re.search(text)
    if m is None:
        return ""
    after = text[m.end() :]
    next_section = re.search(r"^## \[", after, re.MULTILINE)
    body = after[: next_section.start()] if next_section else after
    return body.strip()


def stamp_project_yml(version: str, *, dry_run: bool) -> None:
    text = PROJECT_YML.read_text()
    if not MARKETING_VERSION_RE.search(text):
        print("Warning: could not find MARKETING_VERSION in project.yml — skipping")
        return
    if dry_run:
        print(f'Would stamp project.yml: MARKETING_VERSION -> "{version}"')
    else:
        stamped = MARKETING_VERSION_RE.sub(rf"\g<1>{version}\2", text)
        PROJECT_YML.write_text(stamped)
        print(f"Stamped project.yml MARKETING_VERSION with {version}")


def commit_and_push(version: str, *, dry_run: bool) -> None:
    if dry_run:
        print("Would run: git add CHANGELOG.md DuplicatesDetectorGUI/project.yml")
        print(f"Would run: git commit -m 'chore: release v{version}'")
        print("Would run: git push")
        return

    subprocess.run(["git", "add", "CHANGELOG.md", "DuplicatesDetectorGUI/project.yml"], check=True, cwd=REPO_ROOT)
    subprocess.run(
        ["git", "commit", "-m", f"chore: release v{version}"],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(["git", "push"], check=True, cwd=REPO_ROOT)
    print(f"Pushed release commit for v{version}")


def create_and_push_tag(version: str, *, dry_run: bool) -> None:
    tag = f"v{version}"
    if dry_run:
        print(f"Would run: git tag {tag}")
        print(f"Would run: git push origin {tag}")
        return

    subprocess.run(["git", "tag", "-a", tag, "-m", tag], check=True, cwd=REPO_ROOT)
    subprocess.run(["git", "push", "origin", tag], check=True, cwd=REPO_ROOT)
    print(f"Pushed tag {tag}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command == "extract-notes":
        notes = extract_release_notes(args.version)
        print(notes)
        return

    # Release flow
    version: str = args.version
    dry_run: bool = args.dry_run

    if dry_run:
        print(f"=== DRY RUN: release v{version} ===\n")

    fetch_remote_tags()
    validate_version(version)
    if not dry_run:
        check_clean_tree()
    stamp_changelog(version, dry_run=dry_run)
    stamp_project_yml(version, dry_run=dry_run)
    commit_and_push(version, dry_run=dry_run)
    create_and_push_tag(version, dry_run=dry_run)

    if not dry_run:
        print(f"\nRelease v{version} tagged and pushed. CI will build and publish the release.")


if __name__ == "__main__":
    main()
