#!/usr/bin/env bash
set -euo pipefail

# Create a DMG from the exported app bundle.
# Usage: ./scripts/create-dmg.sh [app-path] [output-dmg-path]
#
# Defaults:
#   app-path    = DuplicatesDetectorGUI/build/export/Duplicates Detector.app
#   output-dmg  = DuplicatesDetectorGUI/build/DuplicatesDetector.dmg

APP_PATH="${1:-DuplicatesDetectorGUI/build/export/Duplicates Detector.app}"
DMG_PATH="${2:-DuplicatesDetectorGUI/build/DuplicatesDetector.dmg}"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: App not found at: $APP_PATH" >&2
    exit 1
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT

cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

mkdir -p "$(dirname "$DMG_PATH")"

hdiutil create -volname "Duplicates Detector" \
    -srcfolder "$STAGING_DIR" \
    -ov -format UDZO \
    "$DMG_PATH"

echo "DMG created at: $DMG_PATH"
