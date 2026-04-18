#!/usr/bin/env bash
# Rasterize DuplicatesDetectorGUI/assets/app-icon.svg into the 10 PNG
# variants expected by Assets.xcassets/AppIcon.appiconset/Contents.json.
#
# Requires rsvg-convert (brew install librsvg).
#
# Run from the repository root:
#
#   ./DuplicatesDetectorGUI/assets/rasterize-app-icon.sh
#
set -euo pipefail

command -v rsvg-convert >/dev/null || {
    echo "rsvg-convert not found. Install with: brew install librsvg" >&2
    exit 1
}

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
svg="$here/app-icon.svg"
out="$here/../Sources/Assets.xcassets/AppIcon.appiconset"

[ -f "$svg" ] || { echo "Missing SVG: $svg" >&2; exit 1; }
[ -d "$out" ] || { echo "Missing appiconset: $out" >&2; exit 1; }

# name:size pairs — name matches the filename stem expected by Contents.json.
for spec in \
    "16x16@1x:16" "16x16@2x:32" \
    "32x32@1x:32" "32x32@2x:64" \
    "128x128@1x:128" "128x128@2x:256" \
    "256x256@1x:256" "256x256@2x:512" \
    "512x512@1x:512" "512x512@2x:1024"; do
    name="${spec%:*}"
    size="${spec##*:}"
    rsvg-convert -w "$size" -h "$size" "$svg" -o "$out/icon_${name}.png"
done

echo "Rasterized 10 PNG variants into $out"
