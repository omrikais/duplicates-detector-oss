# Duplicates Detector

Find and manage duplicate video, image, audio, and document files. Compares filenames, metadata, and optionally file content to catch re-encodes, resolution changes, and renamed copies.

Includes a **native macOS app** with side-by-side comparison and a **CLI tool** for automation and scripting.

## Features

- **Multi-format support** — video, image, audio, and document files
- **Smart scoring** — pairs are scored 0–100 based on weighted comparators (filename similarity, duration, resolution, file size, EXIF metadata, audio tags)
- **Content-based detection** — optional perceptual hashing (PDQ), SSIM, CLIP embeddings, or audio fingerprinting (Chromaprint) to catch visually/acoustically similar files regardless of filename
- **Image deduplication** — EXIF-aware scoring (capture date, camera, GPS) plus PDQ perceptual hashing with rotation/flip invariance
- **Audio deduplication** — ID3/Vorbis/iTunes tag comparison (title, artist, album) and Chromaprint fingerprinting
- **Document deduplication** — page-count bucketing, SimHash content hashing, TF-IDF text similarity
- **Safe actions** — trash (reversible), move, hardlink, symlink, reflink, with undo script generation
- **Interactive review** — step through pairs, keep A/B/skip, with an ignore list for false positives
- **Grouping** — transitive clustering groups related duplicates together
- **Configurable** — TOML config files, named profiles, custom weight tuning
- **Multiple output formats** — rich terminal tables, JSON, CSV, shell script, Markdown, self-contained HTML report with analytics dashboard
- **Large library ready** — smart pre-filtering (duration bucketing, filename gating) keeps performance manageable for 1000+ files
- **Pause & resume** — interrupt a scan and pick up where you left off
- **Watch mode** — monitor directories for new duplicates in real time

### macOS App

The companion macOS app provides:

- Side-by-side media comparison (synced video playback, image zoom/wipe)
- Visual score breakdown with per-comparator detail
- One-click keep/trash/move actions
- Photos Library scanning via PhotoKit (no export needed)
- Scan history, profiles, and Shortcuts/Siri integration
- Background watch mode with notifications

## Install

### macOS (Homebrew)

```bash
brew tap omrikais/duplicates-detector
brew install --cask duplicates-detector
```

This installs the macOS app and the `duplicates-detector` CLI. Both ffmpeg and Chromaprint are bundled — no extra dependencies needed.

### From source (CLI only)

Requires Python 3.10+ and ffmpeg.

```bash
pip install duplicates-detector
```

Optional extras:

```bash
pip install "duplicates-detector[trash]"    # trash action (send2trash)
pip install "duplicates-detector[audio]"    # audio mode (mutagen)
pip install "duplicates-detector[ssim]"     # SSIM content method (scikit-image)
```

System dependencies:

```bash
# macOS
brew install ffmpeg chromaprint

# Ubuntu/Debian
sudo apt install ffmpeg libchromaprint-tools
```

## Quick Start

```bash
# Scan a directory for duplicate videos
duplicates-detector scan /path/to/videos

# Image deduplication with EXIF scoring
duplicates-detector scan /path/to/photos --mode image

# Audio deduplication with tag matching
duplicates-detector scan /path/to/music --mode audio

# Content-based detection (catches re-encodes)
duplicates-detector scan /path/to/videos --content

# Interactive review — step through each pair
duplicates-detector scan /path/to/videos -i

# Output as JSON
duplicates-detector scan /path/to/videos --format json --json-envelope

# HTML report with analytics dashboard
duplicates-detector scan /path/to/videos --format html -o report.html
```

## How Scoring Works

Each pair of files is scored 0–100 by combining weighted comparators:

| Comparator | Video | Image | Audio | What it measures |
|---|---|---|---|---|
| Filename | 50 | 25 | 30 | Fuzzy string similarity (Levenshtein ratio) |
| Duration | 30 | — | 30 | How close the durations are (±2s bucketing) |
| Resolution | 10 | 20 | — | Resolution tier similarity |
| File size | 10 | 15 | — | How close the file sizes are |
| EXIF | — | 40 | — | Date, camera, lens, GPS, dimensions |
| Tags | — | — | 40 | Title, artist, album (ID3/Vorbis/iTunes) |

Content-based comparators (`--content`, `--audio`) add a separate scoring dimension that overrides metadata-only scoring when files are perceptually similar.

Weights are fully customizable via `--weights` or config profiles.

## Keep Strategies

When using `--keep` or interactive mode (`-i`), the tool decides which file to keep:

| Strategy | Keeps |
|---|---|
| `longest` | Longer duration |
| `shortest` | Shorter duration |
| `largest` | Larger file size |
| `smallest` | Smaller file size |
| `newest` | Most recently modified |
| `oldest` | Oldest modification time |
| `edited` | Most sidecar edits (.xmp, .aae, etc.) |

## Deletion Actions

| Action | Description |
|---|---|
| `trash` | Move to system trash (reversible) |
| `move` | Move to a specified directory |
| `delete` | Permanent deletion |
| `hardlink` | Replace duplicate with hardlink to kept file |
| `symlink` | Replace duplicate with symlink to kept file |
| `reflink` | Replace with copy-on-write clone (APFS/Btrfs) |

All actions are logged. Use `--generate-undo` to create a script that reverses deletions.

## Configuration

Create a config file at `~/.config/duplicates-detector/config.toml`:

```toml
[defaults]
verbose = true
content = true
min_score = 70
format = "json"

[profiles.photos]
mode = "image"
content = true
rotation_invariant = true

[profiles.music]
mode = "audio"
audio = true
min_score = 60
```

Use profiles with `--profile`:

```bash
duplicates-detector scan /path/to/photos --profile photos
```

## License

MIT
