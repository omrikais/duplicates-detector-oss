# duplicates-detector

A CLI tool that finds duplicate and similar video, image, or audio files by comparing filenames, duration, resolution, and file size — with optional content-based comparison to catch re-encodes, resolution changes, and watermarked copies. Content mode supports two methods: perceptual hashing (`phash`, default) for fast cacheable fingerprinting, or SSIM (Structural Similarity Index) for pixel-level comparison that is more robust for compressed, watermarked, or color-graded duplicates. The `--audio` flag enables Chromaprint audio fingerprinting via `fpcalc`, which catches re-encoded video duplicates that share identical audio tracks regardless of filename or visual differences. Image mode (`--mode image`) scores EXIF metadata — capture timestamp, camera make/model, lens, and GPS coordinates — for high-confidence photo deduplication without any extra flags. Audio mode (`--mode audio`) deduplicates music libraries by scoring filename, duration, and ID3/Vorbis/iTunes tag similarity (title, artist, album) via the `mutagen` library. Displays codec, bitrate, frame rate, and audio channels to help you decide which copy to keep. Designed for large libraries (1000+ files) with smart pre-filtering to stay fast.

## Prerequisites

- **Python 3.10+**
- **ffmpeg** (for `ffprobe`) — install via your package manager:
  ```bash
  # macOS
  brew install ffmpeg

  # Ubuntu/Debian
  sudo apt install ffmpeg
  ```
- **fpcalc** (optional, for `--audio`) — part of [Chromaprint](https://acoustid.org/chromaprint):
  ```bash
  # macOS
  brew install chromaprint

  # Ubuntu/Debian
  sudo apt install libchromaprint-tools
  ```
- **mutagen** (optional, for `--mode audio`) — install via the `audio` extra:
  ```bash
  pip install "duplicates-detector[audio]"
  ```
- **watchdog** (optional, for `watch` subcommand) — install via the `watch` extra:
  ```bash
  pip install "duplicates-detector[watch]"
  ```

## Installation

```bash
git clone https://github.com/omrikais/duplicates-detector.git
cd duplicates-detector
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

The tool has two subcommands: `scan` (the default, for one-shot scanning) and `watch` (daemon mode, for continuous monitoring). All existing commands continue to work unchanged — the `scan` subcommand is implicit when no subcommand is given:

```bash
duplicates-detector /path/to/videos           # implicit scan (unchanged)
duplicates-detector scan /path/to/videos       # explicit scan (same thing)
duplicates-detector watch /path/to/videos      # new watch mode
```

```bash
# Scan current directory recursively
duplicates-detector

# Scan a specific directory
duplicates-detector /path/to/videos

# Scan multiple directories — all files compared as one pool
duplicates-detector /path/to/videos /path/to/backups /mnt/external

# Verbose mode — progress bar + full paths
duplicates-detector /path/to/videos -v

# Only report high-confidence matches (score ≥ 70)
duplicates-detector /path/to/videos --threshold 70

# Only show pairs with similarity score ≥ 80 (post-scoring display filter)
duplicates-detector /path/to/videos --min-score 80

# Scan only the top-level directory (no subdirectories)
duplicates-detector /path/to/videos --no-recursive

# Custom video extensions
duplicates-detector /path/to/videos --extensions mp4,mkv,avi

# Exclude paths by glob pattern
duplicates-detector /path/to/videos --exclude "**/thumbnails/**"
duplicates-detector /path/to/videos --exclude "samples/*" --exclude "*.tmp"

# Compare against a reference library (reference files are never deleted)
duplicates-detector ~/Downloads --reference /media/library
duplicates-detector ~/Downloads --reference /media/library --reference /mnt/archive

# Only compare files larger than 100MB
duplicates-detector /path/to/videos --min-size 100MB

# Only compare files shorter than 10 minutes
duplicates-detector /path/to/videos --max-duration 600

# Only compare files with at least 720p resolution
duplicates-detector /path/to/videos --min-resolution 1280x720

# Only compare files up to 1080p
duplicates-detector /path/to/videos --max-resolution 1920x1080

# Only compare files with bitrate between 1 and 20 Mbps
duplicates-detector /path/to/videos --min-bitrate 1Mbps --max-bitrate 20Mbps

# Only compare H.264 and H.265 files
duplicates-detector /path/to/videos --codec h264,hevc

# Combine: large HD files, medium duration
duplicates-detector /path/to/videos --min-size 500MB --min-duration 60 --max-duration 7200 --min-resolution 1280x720

# Mixed media — scan videos and images together in a single run
duplicates-detector /path/to/media --mode auto

# Audio deduplication — find duplicate MP3/FLAC/AAC/M4A and other audio files
duplicates-detector /path/to/music --mode audio
duplicates-detector /path/to/music --mode audio -v
duplicates-detector /path/to/music --mode audio --keep longest
duplicates-detector /path/to/music --mode audio --audio              # add Chromaprint fingerprinting

# Watch mode — monitor a directory and emit JSON-lines whenever duplicates are found
duplicates-detector watch /path/to/videos                            # watch with defaults
duplicates-detector watch /path/to/videos -v                         # verbose output to stderr
duplicates-detector watch /path/to/music --mode audio                # watch audio files
duplicates-detector watch /path/to/photos --mode image               # watch images
duplicates-detector watch /path/to/videos --debounce 5.0             # slower debounce (5s)
duplicates-detector watch /path/to/videos --webhook https://hooks.example.com/...

# Override auto-detected worker count
duplicates-detector /path/to/videos --workers 16

# Log all actions to a file for audit trails and recovery
duplicates-detector /path/to/videos --keep biggest --log /tmp/actions.jsonl
duplicates-detector /path/to/videos -i --log /tmp/actions.jsonl

# Interactive mode — review each pair and delete files
duplicates-detector /path/to/videos -i

# Dry run — preview interactive deletions without removing files
duplicates-detector /path/to/videos -i --dry-run

# Auto-select which file to keep (auto-deletes the other)
duplicates-detector /path/to/videos --keep biggest
duplicates-detector /path/to/videos --keep longest
duplicates-detector /path/to/videos --keep newest

# Auto-select with interactive confirmation
duplicates-detector /path/to/videos --keep biggest -i

# Preview auto-deletions without removing files
duplicates-detector /path/to/videos --keep biggest --dry-run

# Safe deletion modes — move to trash instead of permanent deletion
duplicates-detector /path/to/videos --keep biggest --action trash

# Move duplicates to a staging directory for review
duplicates-detector /path/to/videos --keep biggest --action move-to --move-to-dir ~/staging

# Interactive staging with confirmation
duplicates-detector /path/to/videos --action move-to --move-to-dir ~/staging -i

# Group transitive duplicates into clusters
duplicates-detector /path/to/videos --group

# Grouped output in other formats
duplicates-detector /path/to/videos --group --format json
duplicates-detector /path/to/videos --group --format csv
duplicates-detector /path/to/videos --group --format html --output report.html

# Group mode with keep strategy — auto-delete all but the best file per group
duplicates-detector /path/to/videos --group --keep biggest

# Group mode interactive — pick which file to keep from each group
duplicates-detector /path/to/videos --group --keep biggest -i

# Content-based hashing — catches re-encodes, resolution changes, watermarks
duplicates-detector /path/to/videos --content
duplicates-detector /path/to/videos --content -v
duplicates-detector /path/to/videos --content --keep biggest
duplicates-detector /path/to/videos --content --group
duplicates-detector /path/to/videos --content --threshold 30

# Fine-tune frame extraction — extract a frame every second for higher accuracy
duplicates-detector /path/to/videos --content --content-interval 1.0

# Use a larger hash for finer content fingerprints (slower but more precise)
duplicates-detector /path/to/videos --content --hash-size 16

# Combine interval and hash size
duplicates-detector /path/to/videos --content --content-interval 1.0 --hash-size 16

# Choose a perceptual hashing algorithm (default: phash)
duplicates-detector /path/to/videos --content --hash-algo dhash    # faster, good for near-exact duplicates
duplicates-detector /path/to/videos --content --hash-algo whash    # robust against crops/resizes
duplicates-detector /path/to/videos --content --hash-algo ahash    # fastest, lowest accuracy
duplicates-detector /path/to/videos --content --hash-algo phash    # default, best general-purpose accuracy

# Combine hash algorithm with other content options
duplicates-detector /path/to/videos --content --hash-algo dhash --hash-size 12
duplicates-detector /path/to/videos --content --hash-algo whash --content-interval 1.0

# Rotation/flip-invariant image hashing — catches phone photos rotated or mirrored
duplicates-detector /path/to/photos --mode image --content --rotation-invariant
duplicates-detector /path/to/photos --mode image --content --rotation-invariant --hash-algo dhash
duplicates-detector /path/to/photos --mode image --content --rotation-invariant --hash-size 12
duplicates-detector /path/to/media --mode auto --content --rotation-invariant   # image sub-pipeline only

# SSIM content method — pixel-level comparison, more robust for watermarks/color grading (requires scikit-image)
duplicates-detector /path/to/videos --content --content-method ssim
duplicates-detector /path/to/photos --mode image --content --content-method ssim
duplicates-detector /path/to/media --mode auto --content --content-method ssim

# Scene-based keyframe extraction — adaptive, extracts only visually distinct frames
duplicates-detector /path/to/videos --content --content-strategy scene
duplicates-detector /path/to/videos --content --content-strategy scene --scene-threshold 0.4  # less sensitive
duplicates-detector /path/to/videos --content --content-strategy scene --scene-threshold 0.2  # more sensitive

# Audio fingerprinting — catch re-encoded duplicates sharing the same audio track
duplicates-detector /path/to/videos --audio
duplicates-detector /path/to/videos --audio -v
duplicates-detector /path/to/videos --audio --keep biggest
duplicates-detector /path/to/videos --audio --content              # combine audio + visual content

# Disable audio fingerprint caching (force re-extraction)
duplicates-detector /path/to/videos --audio --no-audio-cache

# Disable content hash caching (force re-extraction)
duplicates-detector /path/to/videos --content --no-content-cache

# Disable metadata caching (re-run ffprobe on every file)
duplicates-detector /path/to/videos --no-metadata-cache

# Sort results by different criteria
duplicates-detector /path/to/videos --sort size                          # Largest combined file size first
duplicates-detector /path/to/videos --sort mtime                         # Most recently modified first
duplicates-detector /path/to/videos --sort path                          # Alphabetical by file path

# Limit output to top N results
duplicates-detector /path/to/videos --limit 10
duplicates-detector /path/to/videos --sort size --limit 5                # Top 5 largest duplicates

# Filter to high-confidence matches only (post-scoring display filter)
duplicates-detector /path/to/videos --min-score 80
duplicates-detector /path/to/videos --min-score 60 --limit 50            # Filter first, then cap
duplicates-detector /path/to/videos --min-score 70 --format json         # Works with all output formats
duplicates-detector /path/to/videos --min-score 75 --group               # Filter before grouping
duplicates-detector /path/to/videos --min-score 80 --save-config         # Saveable to config

# Quiet mode — suppress progress bars and summary (machine-friendly)
duplicates-detector /path/to/videos -q --format json
duplicates-detector /path/to/videos -q --format csv > results.csv

# Machine-readable progress — emit JSON-lines progress events to stderr for GUI frontends
duplicates-detector scan /path/to/videos --machine-progress 2>progress.jsonl
duplicates-detector scan /path/to/videos --machine-progress --format json --output results.json
duplicates-detector scan /path/to/videos --machine-progress --quiet               # progress to stderr, no Rich summary

# Disable colored output
duplicates-detector /path/to/videos --no-color

# Replace duplicates with hardlinks (same inode, saves space)
duplicates-detector /path/to/videos --keep biggest --action hardlink
duplicates-detector /path/to/videos --keep biggest --action hardlink -i   # Interactive

# Replace duplicates with symlinks (pointer to kept file)
duplicates-detector /path/to/videos --keep biggest --action symlink

# Replace duplicates with CoW reflinks (zero extra disk usage, APFS/Btrfs/XFS only)
duplicates-detector /path/to/videos --keep biggest --action reflink
duplicates-detector /path/to/videos --keep biggest --action reflink -i   # Interactive

# Custom comparator weights (must sum to 100)
duplicates-detector /path/to/videos --weights 'filename=50,duration=30,resolution=10,filesize=10'
duplicates-detector /path/to/videos --weights 'filename=0,duration=50,resolution=25,filesize=25'
duplicates-detector /path/to/videos --content --weights 'filename=10,duration=10,resolution=10,filesize=10,content=60'
duplicates-detector /path/to/videos --audio --weights 'filename=25,duration=25,resolution=10,filesize=10,audio=30'
duplicates-detector /path/to/videos --audio --content --weights 'filename=15,duration=15,resolution=10,filesize=10,audio=10,content=40'

# Image mode custom weights — requires exif key (no duration key)
duplicates-detector /path/to/photos --mode image --weights 'filename=25,resolution=20,filesize=15,exif=40'
duplicates-detector /path/to/photos --mode image --content --weights 'filename=15,resolution=10,filesize=10,exif=25,content=40'

# Audio mode custom weights — requires tags key
duplicates-detector /path/to/music --mode audio --weights 'filename=30,duration=30,tags=40'
duplicates-detector /path/to/music --mode audio --audio --weights 'filename=15,duration=15,tags=20,audio=50'

# Shell tab completion
duplicates-detector --print-completion bash >> ~/.bashrc
duplicates-detector --print-completion zsh >> ~/.zshrc
duplicates-detector --print-completion fish > ~/.config/fish/completions/duplicates-detector.fish

# Structured dry-run report — JSON/shell/HTML include deletion summary
duplicates-detector /path/to/videos --keep biggest --dry-run --format json
duplicates-detector /path/to/videos --keep biggest --dry-run --format shell
duplicates-detector /path/to/videos --keep biggest --dry-run --format html --output dry-run.html

# Use a custom ignored-pairs file
duplicates-detector /path/to/videos -i --ignore-file /tmp/ignored.json

# Clear the ignored-pairs list and exit
duplicates-detector --clear-ignored

# Save current flags as persistent defaults
duplicates-detector /path/to/videos --threshold 30 --keep biggest --content --save-config

# Show the resolved config (after merging config file + CLI)
duplicates-detector --show-config

# Ignore the config file for this run
duplicates-detector /path/to/videos --no-config

# Output as JSON (machine-readable)
duplicates-detector /path/to/videos --format json

# Wrap JSON output in a rich envelope with version, args, and pipeline stats
duplicates-detector /path/to/videos --format json --json-envelope
duplicates-detector /path/to/videos --format json --json-envelope --output results.json

# Replay a saved JSON envelope — re-apply post-scoring flags without re-scanning
duplicates-detector --replay results.json --keep biggest --dry-run
duplicates-detector --replay results.json --min-score 80 --format csv
duplicates-detector --replay results.json --group --format html --output report.html
duplicates-detector --replay results.json -i

# Typical workflow: scan, act, then generate recovery script
duplicates-detector /path --keep biggest --action move-to --move-to-dir /tmp/dupes --log actions.jsonl
duplicates-detector --generate-undo actions.jsonl --output undo.sh
chmod +x undo.sh && ./undo.sh

# Review before executing
duplicates-detector --generate-undo actions.jsonl | less

# Works with hardlink, symlink, and reflink logs too
duplicates-detector /path --keep biggest --action hardlink --log actions.jsonl
duplicates-detector --generate-undo actions.jsonl

# Output as CSV
duplicates-detector /path/to/videos --format csv

# Generate a shell script with commented-out rm commands
duplicates-detector /path/to/videos --format shell

# Generate a self-contained HTML report (best used with --output)
duplicates-detector /path/to/videos --format html --output report.html
duplicates-detector /path/to/videos --format html --output report.html -v
duplicates-detector /path/to/videos --format html --output report.html --group
duplicates-detector /path/to/photos --mode image --format html --output report.html
duplicates-detector /path/to/videos --format html --output report.html --keep biggest --dry-run

# Write output to a file instead of stdout
duplicates-detector /path/to/videos --format json --output results.json

# Executable shell script for review-then-execute workflow
duplicates-detector /path/to/videos --format shell --output cleanup.sh
```

### All Options

| Option | Default | Description |
|---|---|---|
| `directories` | `.` | One or more directories to scan |
| `--replay FILE` | none | Load a previously saved JSON envelope (`--format json --json-envelope`) and re-enter the pipeline at the post-scoring stage. Applies `--keep`, `--min-score`, `--sort`, `--group`, `--limit`, `--format`, `-i`, `--dry-run`, `--reference`, `--json-envelope`, `--log`, and `--ignore-file` without re-scanning. Conflicts with scan-specific flags (`--content`, `--audio`, `--weights`, `--exclude`, `--codec`, size/duration/resolution/bitrate filters, cache flags, and explicit directories). |
| `--no-recursive` | off | Only scan the top-level directory |
| `--threshold N` | `50` | Minimum similarity score (0–100) to report |
| `--workers N` | auto | Parallel workers (auto-detects based on CPU cores) |
| `--extensions EXT,EXT` | all common formats | Comma-separated extensions to match |
| `--mode MODE` | `video` | Scanning and scoring mode: `video` (default), `image` (photo libraries — EXIF scoring via PIL), `auto` (mixed video+image in one pass), or `audio` (music libraries — tag scoring via mutagen). |
| `--exclude PATTERN` | none | Glob pattern to exclude paths (repeatable) |
| `--reference DIR` | none | Reference directory — files compared but never deleted (repeatable) |
| `--min-size SIZE` | none | Minimum file size (e.g., 10MB, 1.5GB, 500KB) |
| `--max-size SIZE` | none | Maximum file size (e.g., 10MB, 1.5GB, 500KB) |
| `--min-duration SECS` | none | Minimum duration in seconds |
| `--max-duration SECS` | none | Maximum duration in seconds |
| `--min-resolution WxH` | none | Minimum resolution by pixel count (e.g., 1280x720) |
| `--max-resolution WxH` | none | Maximum resolution by pixel count (e.g., 1920x1080) |
| `--min-bitrate RATE` | none | Minimum container bitrate (e.g., 5Mbps, 500kbps) |
| `--max-bitrate RATE` | none | Maximum container bitrate (e.g., 20Mbps) |
| `--codec CODEC,...` | none | Restrict to specific video codecs (comma-separated, case-insensitive) |
| `--sort FIELD` | `score` | Sort results by: `score`, `size`, `path`, or `mtime` |
| `--limit N` | none | Maximum number of pairs (or groups) to display |
| `--min-score N` | none | Post-scoring display filter: only show pairs with similarity score ≥ N (0–100). Applied before `--limit` and before grouping. |
| `-v, --verbose` | off | Show progress bar, skipped files, and full paths |
| `-q, --quiet` | off | Suppress progress bars and summary output (machine-friendly) |
| `--no-color` | off | Disable colored terminal output |
| `--machine-progress` | off | Emit structured JSON-lines progress events to stderr during pipeline execution. Replaces Rich progress bars with machine-parseable events (one JSON object per line) for consumption by GUI frontends. Three event types: `stage_start`, `progress`, and `stage_end`. Progress events are throttled to at most one per 100 ms; the final event for each stage always emits. Silently ignored in watch mode. Orthogonal to `--quiet` (both can be active simultaneously). Persistable via `--save-config`. See [Machine-Readable Progress Events](#machine-readable-progress-events). |
| `-i, --interactive` | off | Review each pair and choose files to delete |
| `--dry-run` | off | Preview interactive deletions without removing files |
| `--keep STRATEGY` | none | Auto-select which file to keep: `newest`, `oldest`, `biggest`, `smallest`, `longest`, `highest-res`. `--keep longest` and `--keep biggest` work in audio mode. `--keep highest-res` is not available in audio mode (audio files have no resolution). |
| `--action ACTION` | `delete` | Deletion method: `delete`, `trash`, `move-to`, `hardlink`, `symlink`, or `reflink` |
| `--log FILE` | none | Append JSON-lines action log to FILE (audit trail for every action) |
| `--move-to-dir DIR` | none | Staging directory for `--action move-to` — required when using `move-to` |
| `--weights SPEC` | none | Custom comparator weights as `key=value` pairs. Video mode keys: `filename`, `duration`, `resolution`, `filesize` (plus `audio` when `--audio` is active; plus `content` when `--content` is active). Image mode keys: `filename`, `resolution`, `filesize`, `exif` (plus `content` when `--content` is active). Audio mode keys: `filename`, `duration`, `tags` (plus `audio` when `--audio` is active). The `exif` key is rejected in video/audio mode; the `duration` key is rejected in image mode; the `tags` key is required in audio mode and rejected in all other modes; the `audio` key is rejected when `--audio` is not active. All weights must sum to 100. |
| `--group` | off | Group transitive duplicates into clusters instead of showing pairs |
| `--content` | off | Enable content-based comparison for more accurate detection (slower). Uses perceptual hashing by default; switch to pixel-level SSIM with `--content-method ssim`. |
| `--content-interval SECS` | `2.0` | Frame extraction interval in seconds for content hashing (only with `--content`). Lower = more frames, higher accuracy, slower. |
| `--hash-size N` | `8` | Perceptual hash grid size NxN for content hashing (only with `--content`). Larger = more precise, slower. Minimum: 2. |
| `--hash-algo ALGO` | `phash` | Perceptual hashing algorithm (only with `--content`): `phash` (default, best accuracy), `dhash` (2–3× faster, good for near-exact), `whash` (robust against crops/resizes), `ahash` (fastest, lowest accuracy). |
| `--rotation-invariant` | off | Rotation/flip-invariant image hashing (only with `--content` and `--mode image` or `--mode auto`). Computes hashes for all 8 orientations (4 rotations × 2 flips) per image and takes the minimum Hamming distance. Catches rotated phone photos, flipped scans, and mirrored re-saves. 4–8× slower content hashing; no impact on video or metadata-only mode. Silently ignored without `--content`. |
| `--content-method METHOD` | `phash` | Content comparison method (only with `--content`): `phash` (default, perceptual hashing — fast and cacheable) or `ssim` (structural similarity — pixel-level, more robust for watermarked/compressed/color-graded content, but pairwise and slower with no cache). Requires `pip install "duplicates-detector[ssim]"` when using `ssim`. Silently ignored without `--content`. |
| `--content-strategy STRATEGY` | `interval` | Frame extraction strategy (only with `--content` in video/auto mode): `interval` (default, fixed fps) or `scene` (adaptive keyframe detection via ffmpeg scene filter — extracts only visually distinct frames). Falls back to interval extraction when fewer than 3 scene frames are detected. Silently ignored without `--content`. |
| `--scene-threshold T` | `0.3` | Scene detection sensitivity for `--content-strategy scene` (exclusive range 0.0–1.0). Lower values detect more scene changes (more frames extracted); higher values detect fewer. Silently ignored without `--content-strategy scene`. |
| `--no-content-cache` | off | Disable disk cache for content hashes (re-extract every run) |
| `--audio` | off | Enable Chromaprint audio fingerprinting via `fpcalc`. In video mode (and the video sub-pipeline of `--mode auto`): computes an acoustic fingerprint for each video's audio track. In `--mode audio`: adds fingerprint similarity as a scoring criterion alongside filename, duration, and tags. Requires `fpcalc` on PATH. Produces an error in image mode. |
| `--no-audio-cache` | off | Disable disk cache for audio fingerprints (re-run `fpcalc` on every file). Only meaningful with `--audio`. |
| `--no-metadata-cache` | off | Disable disk cache for metadata (re-run ffprobe on every file) |
| `--format FORMAT` | `table` | Output format: `table`, `json`, `csv`, `shell`, or `html` |
| `--json-envelope` | off | Wrap `--format json` output in a rich envelope with version, args, stats, and results. Silently ignored without `--format json`. |
| `--embed-thumbnails` | off | Embed base64 JPEG thumbnails in JSON envelope output. Requires `--json-envelope` and `--format json`. |
| `--thumbnail-size WxH` | auto | Thumbnail dimensions (default: `160x90` for video, `160x160` for image). Only used with `--embed-thumbnails`. |
| `--output FILE` | stdout | Write output to a file instead of stdout |
| `--save-config` | off | Write current flags to config file and exit |
| `--no-config` | off | Ignore the config file for this run |
| `--show-config` | off | Print the resolved config (after merge) and exit |
| `--profile NAME` | none | Load a named profile from `~/.config/duplicates-detector/profiles/NAME.toml` |
| `--save-profile NAME` | none | Save current flags as a named profile and exit (does not run the scan) |
| `--ignore-file PATH` | XDG default | Custom ignored-pairs file location |
| `--clear-ignored` | off | Clear the ignored-pairs list and exit |
| `--generate-undo LOG_FILE` | none | Parse a `--log` action log and generate a bash script that reverses logged actions (move, hardlink, symlink, reflink reversal; warns for trash and permanent deletes). Standalone operation — skips the scan pipeline and exits. Only `--output`, `--quiet`, and `--no-color` are compatible. Not persistable to config. |
| `--print-completion SHELL` | none | Print shell completion script (`bash`, `zsh`, or `fish`) and exit |
| `--version` | — | Print version and exit |

## Output Formats

### Table (default)

Rich terminal table with color-coded scores. When writing to a file with `--output`, ANSI codes are stripped.

When the table exceeds 500 rows, output is truncated and a warning is printed to stderr:

```
Showing top 500 of 1,234 pairs. Use --limit or --min-score to refine.
```

For group mode the message reads "groups" instead of "pairs". The warning goes to stderr so it does not pollute piped output. JSON, CSV, shell, and HTML formats are never truncated — they always output the full result set.

### JSON

Array of objects with full paths, scores, breakdown, diagnostic detail, and per-file metadata:

```json
[
  {
    "file_a": "/full/path/a.mp4",
    "file_b": "/full/path/b.mp4",
    "score": 82.5,
    "breakdown": { "filename": 30.0, "duration": 35.0, "resolution": 10.0, "file_size": 7.5 },
    "detail": {
      "filename": [0.857, 35.0],
      "duration": [1.0, 35.0],
      "resolution": [0.667, 15.0],
      "file_size": [0.5, 15.0]
    },
    "file_a_metadata": {
      "duration": 120.0, "width": 1920, "height": 1080, "file_size": 1000000,
      "codec": "h264", "bitrate": 8000000, "framerate": 23.976, "audio_channels": 2,
      "mtime": 1740825600.0
    },
    "file_b_metadata": {
      "duration": 120.0, "width": 1280, "height": 720, "file_size": 500000,
      "codec": "hevc", "bitrate": 2000000, "framerate": 23.976, "audio_channels": 6,
      "mtime": 1740739200.0
    }
  }
]
```

The `detail` field provides the per-comparator scoring components for each pair:

- **key** — comparator name (same keys as `breakdown`)
- **value** — a two-element array `[raw_score, weight]`, where `raw_score × weight = breakdown[key]`

`detail` is always present in JSON output regardless of whether `-v` is active. It is omitted for comparators with missing data (those that show `n/a` in the table). This field enables downstream tools to reconstruct the full scoring arithmetic, audit weights, or highlight which comparator drove a high or low score.

Add `--json-envelope` to wrap the results in a richer top-level object:

```bash
duplicates-detector /path/to/videos --format json --json-envelope
```

```json
{
  "version": "1.3.0",
  "generated_at": "2026-03-01T14:30:00.123456+00:00",
  "args": {
    "directories": ["/path/to/videos"],
    "threshold": 50,
    "content": false,
    "group": false,
    "sort": "score",
    "limit": null,
    "keep": null,
    "action": "delete"
  },
  "stats": {
    "files_scanned": 120,
    "files_after_filter": 115,
    "total_pairs_scored": 430,
    "pairs_above_threshold": 7,
    "groups_count": null,
    "space_recoverable": 5368709120,
    "scan_time": 0.021,
    "extract_time": 1.842,
    "filter_time": 0.003,
    "content_hash_time": 0.0,
    "scoring_time": 0.154,
    "total_time": 2.041
  },
  "pairs": [ ... ]
}
```

In group mode (`--group`), the key is `"groups"` instead of `"pairs"`. When used with `--keep --dry-run`, the `dry_run_summary` field is also included. Without `--json-envelope`, JSON output remains a flat array for backward compatibility.

Add `--embed-thumbnails` to include base64 JPEG thumbnails in each file's metadata:

```bash
duplicates-detector /path/to/videos --format json --json-envelope --embed-thumbnails
duplicates-detector /path/to/photos --mode image --format json --json-envelope --embed-thumbnails --thumbnail-size 240x240
```

Each file object in the output gains a `"thumbnail"` key containing a `data:image/jpeg;base64,...` data URI (or `null` if extraction failed). This enables building custom review UIs and web dashboards on top of the JSON API without needing to re-read source files.

### CSV

RFC 4180 CSV with columns: `file_a`, `file_b`, `score`, `filename`, `duration`, `resolution`, `file_size`. Breakdown values that are unavailable appear as empty fields.

### Shell

Generates a bash script with commented-out `rm` commands for a review-then-execute workflow:

```bash
#!/usr/bin/env bash
# Generated by duplicates-detector
# Review carefully before uncommenting any lines.

# --- Score: 82.5 ---
# rm '/full/path/a.mp4'
# rm '/full/path/b.mp4'
```

When `--output` is used with shell format, the file is made executable (0755).

### HTML

Generates a self-contained HTML report — a single file with all CSS, JavaScript, and file thumbnails embedded inline. No external dependencies, no internet connection required. Open it in any browser.

```bash
# Basic HTML report
duplicates-detector /path/to/videos --format html --output report.html

# Verbose — includes per-comparator score breakdown
duplicates-detector /path/to/videos --format html --output report.html -v

# Group mode — pairs are clustered into collapsible group sections
duplicates-detector /path/to/videos --format html --output report.html --group

# Image mode — includes image thumbnails
duplicates-detector /path/to/photos --mode image --format html --output report.html

# Dry-run — adds a deletion summary section to the report
duplicates-detector /path/to/videos --format html --output report.html --keep biggest --dry-run
```

The report includes:

- **Summary dashboard** — scan statistics (files scanned, pairs found, space recoverable, scan time)
- **Sortable table** — click any column header to sort pairs or groups by that field
- **Color-coded score badges** — red (≥ 80), yellow (≥ 60), green (< 60) — matching the terminal output
- **File thumbnails** — 120×120 JPEG previews embedded as base64. PIL generates thumbnails for images; ffmpeg generates them for videos. Files where thumbnail generation fails are shown without a preview.
- **Collapsible group sections** — when `--group` is active, each cluster is shown as an expandable block
- **Dry-run summary section** — when `--keep --dry-run` is active, a summary of files that would be deleted is appended to the report

If you write to stdout instead of a file, a hint is printed to stderr:

```
Hint: use --output report.html to write the HTML report to a file
```

`--json-envelope` is silently ignored with `--format html`.

## How It Works

### Video mode (default)

Each pair of video files is scored from **0 to 100** based on four criteria:

| Criterion | Max Points | What It Compares |
|---|---|---|
| **Filename** | 35 | Fuzzy match after stripping quality markers (720p, x264, etc.). Numeric ID filenames (e.g. Telegram) require exact digit match. |
| **Duration** | 35 | How close the playback lengths are (within 5 seconds) |
| **Resolution** | 15 | Pixel count ratio (e.g., 1080p vs 720p) |
| **File size** | 15 | Byte size ratio |

Add `--audio` to include a fifth criterion: Chromaprint audio fingerprint similarity. See [Audio Fingerprinting](#audio-fingerprinting) below.

Additionally, **codec**, **bitrate**, **frame rate**, and **audio channels** are extracted and displayed in all output formats. These fields are purely informational — they help you decide which copy to keep but do not affect the similarity score.

### Image mode (`--mode image`)

In image mode, scoring replaces **duration** with **EXIF metadata** and adjusts the default weights to reflect the reliability of each signal for photos:

| Criterion | Max Points | What It Compares |
|---|---|---|
| **Filename** | 25 | Fuzzy filename match (same algorithm as video mode) |
| **EXIF** | 40 | Capture timestamp, camera make/model, lens model, GPS coordinates, and embedded dimensions |
| **Resolution** | 20 | Pixel count ratio |
| **File size** | 15 | Byte size ratio |

EXIF scoring is automatic — no extra flags are needed. Files without EXIF data (PNGs, stripped JPEGs) receive `None` for the EXIF comparator; its weight is redistributed proportionally among the remaining comparators so the total always sums to 100. See [Image Deduplication](#image-deduplication) for full details.

### Audio mode (`--mode audio`)

In audio mode, scoring replaces **resolution** and **EXIF** with **tag similarity** — comparing the ID3, Vorbis, or iTunes metadata tags embedded in each file:

| Criterion | Max Points | What It Compares |
|---|---|---|
| **Filename** | 30 | Fuzzy filename match (same algorithm as video mode) |
| **Duration** | 30 | How close the playback lengths are |
| **Tags** | 40 | Title, artist, and album — fuzzy-matched via rapidfuzz |

Tag scoring uses rapidfuzz fuzzy matching (not exact match), so minor differences in punctuation, featuring credits, or album edition names still produce high scores. Files with no embedded tags receive `None` for the tags comparator; its weight is redistributed proportionally among the other comparators so the total always sums to 100.

Add `--audio` to include a fourth criterion: Chromaprint fingerprint similarity. See [Audio Deduplication](#audio-deduplication) for full details.

### Custom Weights

Use `--weights` to override the default scoring weights. Weights are specified as comma-separated `key=value` pairs and must sum to 100:

```bash
# Emphasize filename matching (video mode)
duplicates-detector /path/to/videos --weights 'filename=50,duration=30,resolution=10,filesize=10'

# Disable filename matching entirely (useful for libraries with renamed files)
duplicates-detector /path/to/videos --weights 'filename=0,duration=50,resolution=25,filesize=25'

# With content mode — include the content key (video mode)
duplicates-detector /path/to/videos --content --weights 'filename=10,duration=10,resolution=10,filesize=10,content=60'

# With audio fingerprinting — include the audio key (video mode)
duplicates-detector /path/to/videos --audio --weights 'filename=25,duration=25,resolution=10,filesize=10,audio=30'

# With both audio and content
duplicates-detector /path/to/videos --audio --content --weights 'filename=15,duration=15,resolution=10,filesize=10,audio=10,content=40'

# Image mode — use exif key instead of duration
duplicates-detector /path/to/photos --mode image --weights 'filename=25,resolution=20,filesize=15,exif=40'

# Image mode with content
duplicates-detector /path/to/photos --mode image --content --weights 'filename=15,resolution=10,filesize=10,exif=25,content=40'

# Audio mode — use tags key
duplicates-detector /path/to/music --mode audio --weights 'filename=30,duration=30,tags=40'

# Audio mode with Chromaprint fingerprinting — include the audio key
duplicates-detector /path/to/music --mode audio --audio --weights 'filename=15,duration=15,tags=20,audio=50'
```

Available weight keys differ by mode:

- **Video mode**: `filename`, `duration`, `resolution`, `filesize` (or `file_size`). The `exif` and `tags` keys are rejected.
- **Image mode**: `filename`, `resolution`, `filesize` (or `file_size`), `exif`. The `duration` and `tags` keys are rejected.
- **Audio mode**: `filename`, `duration`, `tags`. The `resolution`, `filesize`, `exif`, and `content` keys are rejected.
- **With `--audio`** (video or audio mode): the `audio` key is also required. Rejected in image mode.
- **With `--content`** (video or image mode): the `content` key is also required.

Setting a weight to 0 disables that comparator entirely — including the filename gate that normally rejects pairs with dissimilar names.

Weights are persistable via `--save-config` and configurable in `config.toml` as a `[weights]` table:

```toml
[weights]
filename = 50.0
duration = 30.0
resolution = 10.0
filesize = 10.0
```

### Filename Normalization

Before comparing names, the tool strips common quality markers so that files like these are recognized as similar:

```
Movie.Name.2020.1080p.BluRay.x264.mp4
Movie.Name.2020.720p.WEB-DL.x265.mkv
```

Stripped markers include: resolution tags (720p, 1080p, 2160p), codecs (x264, x265, hevc), sources (BluRay, WEB-DL, DVDRip, HDTV, remux), audio codecs (AAC, DTS, Atmos), and others (HDR, 10bit, proper, repack).

### Performance on Large Libraries

Comparing every pair in a 1000-file library would mean ~500,000 comparisons. The tool uses several strategies to stay fast:

1. **Duration bucketing** — Files are grouped by similar duration (±2 seconds). Only files within the same bucket are compared pairwise, which dramatically reduces the number of comparisons.
2. **Cross-bucket filename pass** — A secondary pass uses `rapidfuzz.process.extract` with a score cutoff for efficient batch matching in C++, catching files with very similar names (≥80% match) that ended up in different duration buckets.
3. **Multi-core parallelism** — Optimized for Apple Silicon and other multi-core CPUs:
   - **Metadata extraction**: ffprobe runs in a `ThreadPoolExecutor` with `cpu_count * 8` workers (capped at 128). `subprocess.run` fully releases the GIL, so all workers run truly in parallel.
   - **Scoring**: Both bucket scoring and the filename cross-bucket pass are parallelized across CPU cores using `ProcessPoolExecutor`. Work is batched into chunks to amortize process startup cost.
   - **Filename normalization**: Pre-computed once per file to avoid redundant regex processing during comparisons.
4. **Smart fallback** — Serial execution is used for small inputs where multiprocessing overhead would negate the benefit.

### Score Colors

Results are color-coded in the terminal:

- **Red** (≥ 80) — very likely duplicates
- **Yellow** (60–79) — probable duplicates
- **Green** (< 60) — possible matches, worth checking

## Example Output

```
                     Potential Duplicate Videos
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━┓
┃  # ┃ File A              ┃ File B              ┃ Score ┃ Breakdown     ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━┩
│  1 │ Movie.1080p.x264.…  │ Movie.720p.x265.…   │  85.7 │ filename: 35… │
│    │                     │                     │       │ duration: 35… │
│    │                     │                     │       │ resolution: … │
│    │                     │                     │       │ file_size: 9… │
└────┴─────────────────────┴─────────────────────┴───────┴───────────────┘
                          1 pair(s) found
```

### Verbose score breakdown

Add `-v` to see exactly how each score was composed — the raw comparator value, the weight it was multiplied by, and the weighted contribution it produced:

```
duplicates-detector /path/to/videos -v
```

```
                          Potential Duplicate Videos
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  # ┃ File A                         ┃ File B                         ┃ Score ┃ Breakdown                                            ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│  1 │ /videos/Movie.1080p.BluRay.mp4 │ /videos/Movie.720p.WebRip.mkv  │  85.7 │ filename: 0.97 × 35 = 34.0 | duration: 1.00 × 35 = … │
└────┴────────────────────────────────┴────────────────────────────────┴───────┴──────────────────────────────────────────────────────┘
```

Each entry in the Breakdown column follows the format `name: raw × weight = weighted`:

- **raw** — the comparator's raw score from 0.00 to 1.00 (e.g., `0.97` for a near-perfect filename match)
- **weight** — the configured weight for that comparator (e.g., `35`)
- **weighted** — the contribution to the total score: `raw × weight` (e.g., `34.0`)

This makes it easy to see why a pair scored high and how to tune `--weights` to emphasize or de-emphasize specific criteria. Comparators with missing data (e.g., no duration for images) still show `name: n/a`.

In non-verbose mode the Breakdown column shows only the weighted contribution per comparator (`name: weighted_value`), unchanged from previous behaviour.

## Interactive Mode

With `-i` / `--interactive`, the tool shows the results table first, then walks you through each pair one at a time:

```
╭─ Pair 1/3 ──────────────────────────────────────────────────────────────╮
│  A: /videos/Movie.1080p.BluRay.mp4                                      │
│     3.7 GB  |  2:00:00  |  1920x1080  |  H.264  |  8.0 Mbps  |  Stereo │
│                                                                          │
│  B: /videos/Movie.720p.WebRip.mkv                                        │
│     1.9 GB  |  2:00:01  |  1280x720  |  H.265  |  2.0 Mbps  |  5.1     │
│                                                                          │
│  Score: 91.2  (filename: 33 | duration: 35 | ...)                        │
╰──────────────────────────────────────────────────────────────────────────╯
  Delete [a/b/s/s!/q] (s):
```

Add `-v` to see the full scoring decomposition in the panel as well:

```
│  Score: 91.2  (filename: 0.94 × 35 = 33.0 | duration: 1.00 × 35 = 35.0 | resolution: 0.56 × 15 = 8.4 | file_size: 0.98 × 15 = 14.8)  │
```

For each pair you can:
- **a** — delete file A
- **b** — delete file B
- **s** — skip (default)
- **s!** — skip and permanently ignore this pair (see [Ignore List](#ignore-list) below)
- **q** — quit and skip all remaining pairs

If a file was already deleted from an earlier pair, any subsequent pairs containing that file are automatically skipped. A summary is printed at the end showing files deleted, space freed, and any errors.

## Reference Directories

Use `--reference` to compare your files against a curated library without risking deletion of library files:

```bash
duplicates-detector ~/Downloads --reference /media/library -i
```

Reference files are scanned, their metadata extracted, and they participate fully in duplicate scoring. The **only** difference is they are protected from deletion:

- **Interactive mode**: If one file is from a reference directory, only the non-reference file is offered for deletion (e.g., `b/s/q` instead of `a/b/s/q`). If both files are reference, the pair is auto-skipped.
- **Table output**: Reference files are tagged with `[REF]`.
- **JSON output**: Each pair includes `file_a_is_reference` and `file_b_is_reference` boolean fields.
- **CSV output**: Two additional columns: `file_a_is_reference` and `file_b_is_reference`.
- **Shell output**: Reference files get a `# (reference — do not delete)` annotation instead of a commented `rm` line.

You can specify multiple reference directories:

```bash
duplicates-detector ~/Downloads --reference /media/library --reference /mnt/archive
```

## Keep Strategies

Use `--keep` to automatically decide which file to keep in each duplicate pair:

| Strategy | Keeps the file with… | Tie-breaking |
|---|---|---|
| `newest` | Most recent modification time | Largest file size |
| `oldest` | Earliest modification time | Largest file size |
| `biggest` | Largest file size | Undecidable (skipped) |
| `smallest` | Smallest file size | Undecidable (skipped) |
| `longest` | Longest duration | Largest file size |
| `highest-res` | Highest pixel count (width × height) | Largest file size |

### Behavior by mode

- **`--keep biggest`** (standalone): Auto-deletes the non-kept file in each pair. No prompting.
- **`--keep biggest -i`**: Shows a recommendation and sets it as the default, but prompts for confirmation. You can override by choosing a different option.
- **`--keep biggest --dry-run`**: Shows what would be deleted without touching the filesystem.
- **`--keep biggest --format json`**: Adds a `"keep"` field (`"a"`, `"b"`, or `null`) to each JSON record.

When the relevant metadata is missing for both files (e.g., both have unknown duration with `--keep longest`), the pair is **undecidable** — skipped in auto mode, prompted normally in interactive mode.

**Mode-specific restrictions:**

- `--keep longest` is not available in `--mode image` (images have no duration).
- `--keep highest-res` is not available in `--mode audio` (audio files have no resolution).
- All other strategies (`newest`, `oldest`, `biggest`, `smallest`, `longest`) work in audio mode.

Reference files are always protected: if the strategy recommends deleting a reference file, the pair is skipped in auto mode and falls back to normal prompting in interactive mode.

## Safe Deletion Modes

By default, duplicate files are permanently deleted with `Path.unlink()`. The `--action` flag offers two safer alternatives:

### Trash (Recoverable)

Move duplicate files to your operating system's trash instead of permanently deleting them:

```bash
duplicates-detector /path/to/videos --keep biggest --action trash
duplicates-detector /path/to/videos --action trash -i                # Interactive with trash
```

Requires the optional `send2trash` dependency:

```bash
pip install "duplicates-detector[trash]"
```

Trashed files can be restored from your OS trash bin within a grace period (varies by OS). Use this mode when you want a safety net before permanent deletion.

### Staging Directory

Move duplicate files to a temporary staging directory for manual review:

```bash
duplicates-detector /path/to/videos --action move-to --move-to-dir ~/staging
duplicates-detector /path/to/videos --action move-to --move-to-dir ~/staging --keep biggest
duplicates-detector /path/to/videos --action move-to --move-to-dir ~/staging -i
```

If a file with the same name already exists in the staging directory, the tool appends `_1`, `_2`, etc. before the extension to avoid collisions.

### Hardlink

Replace duplicates with hardlinks to the kept file. Both paths point to the same inode, so the space used by the duplicate is freed while the file remains accessible from its original location:

```bash
duplicates-detector /path/to/videos --keep biggest --action hardlink
duplicates-detector /path/to/videos --keep biggest --action hardlink -i
```

Hardlinks must be on the same filesystem. They are transparent — applications cannot tell the difference between the original and the hardlink.

### Symlink

Replace duplicates with symbolic links to the kept file:

```bash
duplicates-detector /path/to/videos --keep biggest --action symlink
duplicates-detector /path/to/videos --keep biggest --action symlink -i
```

Symlinks work across filesystems but break if the target file is moved or deleted. The tool uses absolute resolved paths for the link target.

Both `--action hardlink` and `--action symlink` require `--keep` or `-i` so there is always a kept file to link to.

### Reflink (Copy-on-Write)

Replace duplicates with a CoW (copy-on-write) reflink of the kept file. Both paths remain independently accessible and fully writable — they share the same physical disk blocks until one of them is modified. At action time the reflink is instantaneous and uses zero additional disk space:

```bash
duplicates-detector /path/to/videos --keep biggest --action reflink
duplicates-detector /path/to/videos --keep biggest --action reflink -i
duplicates-detector /path/to/videos --keep biggest --action reflink --dry-run  # preview
```

**Filesystem requirements:** Reflinks require a copy-on-write filesystem — **APFS** on macOS or **Btrfs** / **XFS** (with reflink enabled) on Linux. Both files must reside on the same filesystem. On unsupported filesystems (e.g., ext4, FAT32, exFAT) the action fails immediately with a descriptive error.

**How it differs from hardlink and symlink:**

| | Hardlink | Symlink | Reflink |
|---|---|---|---|
| Disk usage | Zero (same inode) | Negligible (pointer) | Zero until modified (CoW blocks) |
| Files are independent | No — one inode, always in sync | Conceptually yes, but symlink breaks if target moves | Yes — fully independent after any write |
| Cross-filesystem | No | Yes | No |
| Requires `--keep` or `-i` | Yes | Yes | Yes |

In practical terms: a reflink looks and behaves like a full independent copy, but until you modify one of the files, they share storage. Hardlinks always stay in sync (one inode); symlinks break if the target is moved or deleted. Reflinks have neither limitation.

`--action reflink` requires `--keep` or `-i` so there is always a kept file to clone from.

### Deletion Methods

| Method | Command | Behavior |
|---|---|---|
| Permanent (default) | `--action delete` | Immediately and permanently remove files via `Path.unlink()` |
| Trash (recoverable) | `--action trash` | Move files to OS trash (recoverable within OS grace period) |
| Staging directory | `--action move-to --move-to-dir DIR` | Move files to a staging directory for review before final deletion |
| Hardlink | `--action hardlink` | Replace duplicate with a hardlink to the kept file (same filesystem only) |
| Symlink | `--action symlink` | Replace duplicate with a symlink to the kept file (works cross-filesystem) |
| Reflink | `--action reflink` | Replace duplicate with a CoW clone of the kept file — zero extra disk usage, both paths independent (APFS/Btrfs/XFS only) |

All deletion methods work with `--keep` strategies, interactive mode (`-i`), and `--dry-run` for previewing without taking action.

## Action Log

Use `--log FILE` to keep an append-only audit trail of every action (deletion, move, link) performed by the tool. Each action is recorded as a single JSON object on its own line ([JSON Lines](https://jsonlines.org/) format):

```bash
# Log all deletions for later review or recovery
duplicates-detector /path/to/videos --keep biggest --log ~/actions.jsonl

# Log interactive session actions
duplicates-detector /path/to/videos -i --log ~/actions.jsonl

# Combine with staging — log what was moved and where
duplicates-detector /path/to/videos --keep biggest --action move-to --move-to-dir ~/staging --log ~/actions.jsonl

# Dry-run actions are also logged (marked with dry_run: true)
duplicates-detector /path/to/videos --keep biggest --dry-run --log ~/actions.jsonl
```

Each line in the log file contains:

```json
{
  "timestamp": "2026-03-01T14:30:00.123456",
  "action": "deleted",
  "path": "/path/to/duplicate.mp4",
  "score": 91.2,
  "strategy": "biggest",
  "kept": "/path/to/original.mp4",
  "bytes_freed": 1073741824,
  "destination": "/staging/duplicate.mp4",
  "dry_run": true
}
```

| Field | Always present | Description |
|---|---|---|
| `timestamp` | yes | ISO 8601 timestamp of the action |
| `action` | yes | Action verb: `deleted`, `trashed`, `moved`, `hardlinked`, `symlinked`, or `reflinked` |
| `path` | yes | Resolved path of the file that was acted on |
| `score` | yes | Similarity score of the pair (or max group score) |
| `strategy` | yes | Keep strategy used (`biggest`, `interactive`, etc.) |
| `kept` | yes | Resolved path of the file that was kept |
| `bytes_freed` | yes | Bytes freed by the action |
| `destination` | only for moves | Resolved destination path (for `--action move-to`) |
| `dry_run` | only when true | Present and `true` when `--dry-run` was active |

The log file is opened in append mode — multiple runs accumulate in the same file. Records are flushed immediately after each write for crash safety.

The `--log` flag is persistable via `--save-config`.

## Undo Script Generation

Use `--generate-undo LOG_FILE` to parse a `--log` action log and produce a bash script that reverses the recorded operations. This turns the action log into a recovery tool — if you regret a batch deletion or move, you have a clear, reviewable script to put things back.

### Typical workflow

```bash
# Step 1: scan and act — log every action to a file
duplicates-detector /path/to/videos --keep biggest --action move-to --move-to-dir ~/staging --log ~/actions.jsonl

# Step 2: generate the undo script
duplicates-detector --generate-undo ~/actions.jsonl --output undo.sh

# Step 3: review the script before running it
less undo.sh

# Step 4: execute the undo
chmod +x undo.sh && ./undo.sh
```

Works with all action types — move, hardlink, symlink, reflink, trash, and permanent delete:

```bash
# Undo a hardlink run
duplicates-detector /path/to/videos --keep biggest --action hardlink --log ~/actions.jsonl
duplicates-detector --generate-undo ~/actions.jsonl --output undo.sh

# Undo a symlink run
duplicates-detector /path/to/videos --keep biggest --action symlink --log ~/actions.jsonl
duplicates-detector --generate-undo ~/actions.jsonl

# Undo a reflink run
duplicates-detector /path/to/videos --keep biggest --action reflink --log ~/actions.jsonl
duplicates-detector --generate-undo ~/actions.jsonl --output undo.sh

# Pipe to stdout and review inline
duplicates-detector --generate-undo ~/actions.jsonl | less

# Quiet mode — suppress the stderr confirmation message
duplicates-detector --generate-undo ~/actions.jsonl --output undo.sh -q
```

### What each action type produces

| Action type | What the undo script does |
|---|---|
| `moved` | Moves the file back from the staging directory to its original location. Fully reversible. |
| `hardlinked` | Breaks the hardlink by copying the kept file to a standalone copy at the original path — restores the file as an independent file with its own inode. |
| `symlinked` | Replaces the symlink with a real copy of the kept file — restores a regular file at the original path. |
| `reflinked` | Copies the kept file to a standalone copy at the original path — breaks the CoW sharing and restores an independent file. Same mechanism as hardlink undo. |
| `trashed` | Cannot be reversed automatically. The script prints a `MANUAL:` hint to check the OS trash (`~/.Trash/` on macOS, `$XDG_DATA_HOME/Trash/` on Linux) and increments the warning counter. |
| `deleted` | Permanently gone. The script prints an `IRRECOVERABLE:` notice with the original path and size. |

### Safety features

- **Confirmation prompt** — the generated script asks `Continue? [y/N]` before doing anything. You can bypass it with `yes | ./undo.sh` if desired.
- **Existence checks** — each move operation checks that the source file still exists and that the destination does not, so the script will never clobber an existing file. A warning is printed and the counter incremented for any operation that cannot proceed.
- **`set -euo pipefail`** — the script aborts on the first unhandled error.
- **Idempotent** — safe to run multiple times. Operations that have already completed or cannot proceed are skipped with a warning.
- **Dry-run entries skipped** — records with `"dry_run": true` in the log are silently excluded from the generated script. The script header notes how many were skipped.
- **Malformed records skipped** — lines that fail JSON parsing or lack required fields emit a stderr warning and are excluded. The rest of the script is still generated.

### Generated script structure

```bash
#!/usr/bin/env bash
# Undo script generated by duplicates-detector
# Source log: /path/to/actions.jsonl
# Generated: 2026-03-03T12:00:00
# Actions: 15 total (10 reversible, 3 warnings, 2 skipped dry-run)

set -euo pipefail

echo "This script will attempt to undo 10 file operations."
echo "WARNING: Restoring files may overwrite newer versions."
read -r -p "Continue? [y/N] " response
case "$response" in
    [yY][eE][sS]|[yY]) ;;
    *) echo "Aborted."; exit 1 ;;
esac

restored=0
failed=0
warnings=0

# --- Action 1: moved (2026-03-03T10:30:00) ---
# Score: 92.5 | Strategy: biggest | Kept: /videos/original.mp4
if [ -f "/staging/duplicate.mp4" ]; then
    if [ -e "/videos/duplicate.mp4" ]; then
        echo "WARNING: /videos/duplicate.mp4 already exists, skipping"
        warnings=$((warnings + 1))
    else
        mkdir -p "/videos"
        mv "/staging/duplicate.mp4" "/videos/duplicate.mp4" && restored=$((restored + 1)) || failed=$((failed + 1))
    fi
else
    echo "WARNING: Source /staging/duplicate.mp4 not found, skipping"
    warnings=$((warnings + 1))
fi

# --- Action 2: hardlinked (2026-03-03T10:30:01) ---
# Score: 88.0 | Strategy: biggest | Kept: /videos/original.mp4
if [ -f "/videos/hardlinked.mp4" ] && [ -f "/videos/original.mp4" ]; then
    cp "/videos/original.mp4" "/videos/hardlinked.mp4.tmp" && mv "/videos/hardlinked.mp4.tmp" "/videos/hardlinked.mp4" \
        && restored=$((restored + 1)) || failed=$((failed + 1))
else
    echo "WARNING: Cannot undo hardlink — file(s) missing"
    warnings=$((warnings + 1))
fi

# --- Action 3: trashed (2026-03-03T10:30:02) ---
# WARNING: Cannot auto-restore trashed file.
# Original path: /videos/trashed.mp4
# Check OS trash: ~/.Trash/ (macOS) or $XDG_DATA_HOME/Trash/ (Linux)
echo "MANUAL: Restore /videos/trashed.mp4 from OS trash (47.7 MB)"
warnings=$((warnings + 1))

# --- Action 4: deleted (2026-03-03T10:30:03) ---
# WARNING: Permanently deleted — cannot restore.
# Original path: /videos/deleted.mp4
echo "IRRECOVERABLE: /videos/deleted.mp4 was permanently deleted (28.6 MB)"
warnings=$((warnings + 1))

echo ""
echo "Undo complete: $restored restored, $failed failed, $warnings warnings"
```

### Compatible flags

`--generate-undo` is a standalone operation — it skips the scan pipeline entirely and exits after writing the script. Only these flags are compatible:

| Flag | Effect |
|---|---|
| `--output FILE` | Write the script to FILE instead of stdout. The file is NOT automatically made executable — run `chmod +x` before executing. |
| `-q` / `--quiet` | Suppress the stderr confirmation message (`Wrote undo script to FILE`). |
| `--no-color` | Disable ANSI colors in stderr output. |

All other flags (`--keep`, `--content`, `--audio`, `--weights`, size/duration filters, `--action`, directory arguments, etc.) conflict with `--generate-undo` and produce an error.

`--generate-undo` is not persistable via `--save-config` (it is a one-off operation, like `--clear-ignored`).

## Ignore List

When reviewing duplicates interactively, you'll sometimes encounter pairs that look similar by the numbers but aren't actually duplicates (e.g., different episodes with similar metadata). The **ignore list** lets you permanently mark these false positives so they're filtered out on future runs.

### Using `s!` (skip & remember)

During interactive review (`-i`), choose `s!` instead of `s` to skip a pair **and** add it to the persistent ignore list:

```
  Delete [a/b/s/s!/q] (s): s!
```

In group mode, `s!` ignores all pairwise combinations of the group's members.

On subsequent runs, ignored pairs are automatically filtered out before results are displayed or acted on.

### Ignore list storage

The ignore list is stored as a JSON file at:

- `$XDG_DATA_HOME/duplicates-detector/ignored-pairs.json` (if `XDG_DATA_HOME` is set)
- `~/.local/share/duplicates-detector/ignored-pairs.json` (default)

Use `--ignore-file PATH` to specify a custom location:

```bash
duplicates-detector /path/to/videos -i --ignore-file ~/my-ignored.json
```

### Clearing the ignore list

To remove all ignored pairs and start fresh:

```bash
duplicates-detector --clear-ignored
```

This prints the number of pairs cleared and exits. Combine with `--ignore-file` to clear a specific file:

```bash
duplicates-detector --clear-ignored --ignore-file ~/my-ignored.json
```

The `--ignore-file` flag is persistable via `--save-config`.

## Pre-Scoring Filters

Filter files **before** scoring to focus on specific subsets of your library. Files with unknown metadata for a filtered field (e.g., no resolution detected) pass through — they are not excluded.

### Resolution filter

Filter by pixel count (width × height), so `1280x720` (921,600 pixels) and `960x960` (921,600 pixels) are treated equally:

```bash
# Only HD and above
duplicates-detector /path/to/videos --min-resolution 1280x720

# Only up to Full HD
duplicates-detector /path/to/videos --max-resolution 1920x1080

# Between 720p and 1080p
duplicates-detector /path/to/videos --min-resolution 1280x720 --max-resolution 1920x1080
```

### Bitrate filter

Filter by container bitrate. Supports raw bps or human-readable suffixes (`kbps`, `Mbps`, `Gbps`):

```bash
# Only files above 5 Mbps
duplicates-detector /path/to/videos --min-bitrate 5Mbps

# Only files below 20 Mbps
duplicates-detector /path/to/videos --max-bitrate 20Mbps

# Combine
duplicates-detector /path/to/videos --min-bitrate 1Mbps --max-bitrate 50Mbps
```

### Codec filter

Restrict comparison to specific video codecs (comma-separated, case-insensitive):

```bash
# Only H.264 files
duplicates-detector /path/to/videos --codec h264

# H.264 and H.265 files
duplicates-detector /path/to/videos --codec h264,hevc

# AV1 only
duplicates-detector /path/to/videos --codec av1
```

### Combining filters

All filters stack — a file must pass all active filters to be included:

```bash
# Large HD H.264 files between 1 and 10 minutes
duplicates-detector /path/to/videos \
  --min-size 100MB \
  --min-resolution 1280x720 \
  --min-bitrate 5Mbps \
  --codec h264 \
  --min-duration 60 --max-duration 600
```

All filter flags are persistable via `--save-config`.

## Duplicate Grouping

By default, results are shown as individual pairs (A↔B). When files are transitively related — A matches B and B matches C — you see 3 separate pairs. The `--group` flag clusters them into one group {A, B, C}:

```bash
duplicates-detector /path/to/videos --group
```

Groups are formed using union-find (transitive closure) on scored pairs. If any two files are connected by a chain of matches, they end up in the same group.

### Group output formats

**Table** — Each group is displayed as a numbered table listing all member files with their metadata and a score range:

```
      Group 1 (3 files) — Score: 75.0–92.0 (avg 83.5)
 #  File                      Duration  Resolution        Size    Codec  Bitrate   FPS     Audio
 1  movie_a.1080p.mp4         2:00:00   1920x1080      4.0 GB    H.264  8.0 Mbps  23.976  Stereo  KEEP
 2  movie_a.720p.mkv          2:00:01   1280x720       2.0 GB    H.265  2.0 Mbps  23.976  Stereo
 3  movie_a.2160p.remux.mkv   2:00:01   3840x2160     50.0 GB    H.265  20.0 Mbps 23.976  5.1     [REF]
```

**JSON** — Array of group objects:

```json
[
  {
    "group_id": 1,
    "file_count": 3,
    "max_score": 92.0,
    "min_score": 75.0,
    "avg_score": 83.5,
    "files": [
      {
        "path": "/path/to/movie_a.1080p.mp4", "duration": 7200.0,
        "width": 1920, "height": 1080, "file_size": 4000000000,
        "codec": "h264", "bitrate": 8000000, "framerate": 23.976, "audio_channels": 2,
        "is_reference": false
      }
    ],
    "pairs": [
      { "file_a": "/path/to/movie_a.1080p.mp4", "file_b": "/path/to/movie_a.720p.mkv", "score": 92.0, "breakdown": { "...": "..." } }
    ],
    "keep": "/path/to/movie_a.1080p.mp4"
  }
]
```

**CSV** — One row per member file with a `group_id` column linking members of the same group. Includes `codec`, `bitrate`, `framerate`, and `audio_channels` columns.

**Shell** — One comment block per group with `rm` lines for each non-keeper file.

**HTML** — Each group is rendered as a collapsible section with thumbnails, metadata, and score information for all member files.

### Group interactive mode

With `--group -i`, each group is presented as a panel listing all members by number. You pick which file to **keep** — all other non-reference files are deleted:

```
╭─ Group 1/5 (3 files) ──────────────────────────────────────────────────────╮
│  1. /videos/movie_a.1080p.mp4                                               │
│     4.0 GB  |  2:00:00  |  1920x1080  |  H.264  |  8.0 Mbps  |  Stereo    │
│                                                                              │
│  2. /videos/movie_a.720p.mkv                                                 │
│     2.0 GB  |  2:00:01  |  1280x720  |  H.265  |  2.0 Mbps  |  Stereo     │
│                                                                              │
│  3. (reference) /library/movie_a.2160p.remux.mkv                             │
│     50.0 GB  |  2:00:01  |  3840x2160  |  H.265  |  20.0 Mbps  |  5.1     │
│                                                                              │
│  Score range: 75.0–92.0                                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
  Strategy 'biggest' recommends keeping file 1
  Keep file [1/2/3/s/q] (1):
```

- **1, 2, 3, ...** — keep that file, delete all other non-reference files
- **s** — skip this group
- **s!** — skip and permanently ignore all pairs in this group (see [Ignore List](#ignore-list) below)
- **q** — quit

Reference files are never deleted regardless of which file you choose to keep. Groups where all non-reference files have already been deleted are auto-skipped.

### Group mode with `--keep`

- **`--group --keep biggest`**: Auto-deletes all non-keeper, non-reference files from each group.
- **`--group --keep biggest -i`**: Pre-selects the recommended keeper as default, user can override.
- **`--group --keep biggest --dry-run`**: Previews what would be deleted.
- **`--group --keep biggest --format json`**: Adds a `"keep"` field (path string or `null`) to each group.

## Content-Based Detection

The `--content` flag enables perceptual video hashing, which compares the actual visual content of videos rather than just their metadata. This catches duplicates that metadata alone cannot:

- **Re-encoded files** — same video in different codecs (H.264 vs H.265)
- **Resolution changes** — 1080p and 720p versions of the same content
- **Watermarked copies** — videos with overlaid logos or text
- **Different containers** — same content in .mp4, .mkv, .avi
- **Cropped variants** — slightly trimmed versions

### How it works

1. **Frame extraction** — ffmpeg extracts frames from each video as PNG images. The default strategy (`interval`) extracts one frame every 2 seconds. The `scene` strategy (`--content-strategy scene`) extracts only visually distinct keyframes.
2. **Content comparison** — The comparison method is selectable with `--content-method`:
   - **`phash`** (default) — Each frame is hashed using a perceptual hash algorithm via `imagehash` (selectable with `--hash-algo`), producing a compact fingerprint robust to minor visual changes.
   - **`ssim`** — Frames are compared directly at the pixel level using Structural Similarity Index (scikit-image), without hashing. More robust for watermarked, compressed, or color-graded duplicates.
3. **Sequence comparison** — Frame fingerprints (or raw frame data for SSIM) are compared using a sliding-window approach, handling videos of different lengths (intro/outro differences)

### Parameters

Optional flags let you trade off speed against accuracy when using `--content`:

| Flag | Default | Description |
|---|---|---|
| `--content-method METHOD` | `phash` | Content comparison method: `phash` (perceptual hashing, fast and cacheable) or `ssim` (pixel-level structural similarity, no cache). See [SSIM Content Method](#ssim-content-method) below. |
| `--content-interval SECS` | `2.0` | Frame extraction interval in seconds (interval strategy only). Lower values extract more frames and improve accuracy but increase processing time and cache size. |
| `--content-strategy STRATEGY` | `interval` | Frame extraction strategy: `interval` (fixed fps) or `scene` (adaptive keyframe detection). See [Scene-Based Extraction](#scene-based-extraction) below. |
| `--scene-threshold T` | `0.3` | Scene detection sensitivity for `--content-strategy scene` (0.0–1.0 exclusive). Lower = more frames. |
| `--hash-size N` | `8` | Perceptual hash grid size NxN (phash method only). Larger values produce finer-grained fingerprints. Minimum: 2. |
| `--hash-algo ALGO` | `phash` | Perceptual hashing algorithm (phash method only). See table below. |
| `--rotation-invariant` | off | Rotation/flip-invariant image hashing (image mode only). See [Rotation-Invariant Image Hashing](#rotation-invariant-image-hashing) below. |

**Hash algorithm comparison:**

| Algorithm | Speed | Accuracy | Best for |
|---|---|---|---|
| `phash` (default) | Baseline | High | General-purpose duplicate detection |
| `dhash` | 2–3× faster | Good for near-exact | Large collections, near-identical files |
| `whash` | ~1× (similar to phash) | Most robust | Cropped, resized, color-shifted duplicates |
| `ahash` | Fastest | Lowest | Quick first-pass screening |

`--hash-algo whash` requires `--hash-size` to be a power of 2 (8, 16, 32, …). The default of 8 satisfies this. `--hash-algo` without `--content` is silently ignored.

```bash
# Default — one frame every 2 seconds, 8x8 phash
duplicates-detector /path/to/videos --content

# Higher accuracy — one frame per second, 16x16 hash
duplicates-detector /path/to/videos --content --content-interval 1.0 --hash-size 16

# Faster scan — one frame every 5 seconds, smaller hash
duplicates-detector /path/to/videos --content --content-interval 5.0 --hash-size 4

# Fast near-exact duplicate detection on a large collection
duplicates-detector /path/to/videos --content --hash-algo dhash

# Robust detection for libraries with crops, resizes, or color shifts
duplicates-detector /path/to/videos --content --hash-algo whash

# Combine algorithm with size and interval options
duplicates-detector /path/to/videos --content --hash-algo dhash --hash-size 12
duplicates-detector /path/to/videos --content --hash-algo whash --content-interval 1.0

# SSIM — pixel-level comparison (more robust, slower, no cache)
duplicates-detector /path/to/videos --content --content-method ssim
duplicates-detector /path/to/photos --mode image --content --content-method ssim

# Scene-based extraction — adaptive keyframes instead of fixed interval
duplicates-detector /path/to/videos --content --content-strategy scene
duplicates-detector /path/to/videos --content --content-strategy scene --scene-threshold 0.4

# Works with image and auto modes
duplicates-detector /path/to/photos --mode image --content --hash-algo dhash
duplicates-detector /path/to/media --mode auto --content --hash-algo whash
```

Content hash cache entries (phash method only) are invalidated whenever `--content-interval`, `--hash-size`, `--hash-algo`, `--content-strategy`, `--scene-threshold`, or `--rotation-invariant` change, so switching parameters automatically forces re-extraction. SSIM has no content cache — frames are compared directly on every run.

All content hashing flags are persistable via `--save-config` and configurable in `config.toml`:

```toml
content = true
content_method = "phash"
content_interval = 1.0
hash_size = 16
hash_algo = "dhash"
rotation_invariant = true
content_strategy = "interval"
scene_threshold = 0.3
```

### Rotation-Invariant Image Hashing

Use `--rotation-invariant` with `--content` and `--mode image` (or `--mode auto`) to catch duplicates that differ only by rotation or reflection:

- **Phone photos saved in wrong EXIF orientation** — the same shot stored as portrait vs. landscape
- **Scanned documents flipped or rotated during digitization** — a page scanned at 90° or 180°
- **Images manually rotated/mirrored and re-saved** — an edited copy saved without the original EXIF
- **Thumbnails with stripped EXIF orientation metadata** — where a viewer would show the photo sideways

Without `--rotation-invariant`, a 90°-rotated copy of an image produces a completely different hash and is not detected as a duplicate. With `--rotation-invariant`, the tool computes hashes for all 8 orientations (4 rotations × 2 flips) per image and uses the minimum Hamming distance across all orientation pairs when comparing, so rotated and mirrored copies still match.

```bash
# Basic: catch rotated/flipped duplicates in a photo collection
duplicates-detector /photos --mode image --content --rotation-invariant

# Combine with a faster hash algorithm for large collections
duplicates-detector /photos --mode image --content --rotation-invariant --hash-algo dhash

# Use a larger hash for finer detail while still catching rotations
duplicates-detector /photos --mode image --content --rotation-invariant --hash-size 12

# Auto mode — rotation invariance applies to the image sub-pipeline only
duplicates-detector /media --mode auto --content --rotation-invariant

# Combine with all the usual flags
duplicates-detector /photos --mode image --content --rotation-invariant --keep biggest --dry-run
```

**Performance:** Computing 8 hashes per image instead of 1 makes content hashing 4–8× slower. Comparison cost is unchanged — for each pair, the tool picks the minimum distance across the 8×8 orientation combinations in O(1) time. Use `--rotation-invariant` when you specifically need orientation tolerance; omit it for routine deduplication where photos are already correctly oriented.

**Scope:** `--rotation-invariant` only affects image content hashing. It has no impact on video hashing or on metadata-only scoring. In `--mode auto`, only the image sub-pipeline is affected — video files are hashed normally.

`--rotation-invariant` without `--content` is silently ignored (like `--hash-algo` and `--hash-size`).

`--rotation-invariant` is persistable via `--save-config`:

```bash
duplicates-detector /photos --mode image --content --rotation-invariant --save-config
```

### SSIM Content Method

Use `--content-method ssim` to compare frames at the pixel level using Structural Similarity Index (SSIM) rather than perceptual hashing. SSIM is more robust for:

- **Watermarked or logo-overlaid copies** — hash-based methods may score these poorly; SSIM captures structural similarity underneath the overlay
- **Heavily compressed files** — blocking artefacts and quantisation noise that confuse perceptual hashes are handled naturally by SSIM
- **Color-graded variants** — differently colour-corrected masters of the same content (e.g., HDR vs SDR)
- **Slightly cropped or letter-boxed versions** — SSIM's structural comparison tolerates minor spatial changes

SSIM requires the `scikit-image` package, available as an optional extra:

```bash
pip install "duplicates-detector[ssim]"
```

```bash
# Video — SSIM pixel-level comparison
duplicates-detector /path/to/videos --content --content-method ssim

# Image — SSIM pixel-level comparison
duplicates-detector /path/to/photos --mode image --content --content-method ssim

# Auto mode — SSIM applies to both video and image sub-pipelines
duplicates-detector /path/to/media --mode auto --content --content-method ssim

# Combine with scene-based extraction for more targeted frame selection
duplicates-detector /path/to/videos --content --content-method ssim --content-strategy scene
```

**Differences from phash (`--content-method phash`):**

| | `phash` (default) | `ssim` |
|---|---|---|
| Comparison approach | Perceptual hash (Hamming distance) | Pixel-level structural similarity |
| Speed | Fast | Slower (pairwise frame comparison) |
| Content cache | Yes — hashes cached on disk | No — frames compared directly each run |
| Scoring path | Parallel (ProcessPoolExecutor) | Serial (avoids large IPC overhead) |
| `--hash-algo` / `--hash-size` | Respected | Silently ignored (with warning) |
| `--rotation-invariant` | Respected (image mode) | Silently ignored (with warning) |
| Corrupt/truncated frames | Skipped gracefully | Skipped gracefully |

Because SSIM is inherently pairwise — each pair of frames must be compared directly — there is no per-file hash to store, so the content cache is not used. If you regularly scan the same library with SSIM, expect full frame extraction on every run.

`--content-method` without `--content` is silently ignored. `--content-method` is persistable via `--save-config`.

### Scene-Based Extraction

Use `--content-strategy scene` to extract only visually distinct keyframes from each video rather than frames at a fixed interval. This uses ffmpeg's scene detection filter to identify significant visual transitions, which can be more efficient and representative for content-heavy videos.

```bash
# Scene-based extraction with default sensitivity
duplicates-detector /path/to/videos --content --content-strategy scene

# Less sensitive — fewer frames extracted (fewer scene changes detected)
duplicates-detector /path/to/videos --content --content-strategy scene --scene-threshold 0.4

# More sensitive — more frames extracted (more scene changes detected)
duplicates-detector /path/to/videos --content --content-strategy scene --scene-threshold 0.2

# Combine with SSIM for pixel-level comparison of scene keyframes
duplicates-detector /path/to/videos --content --content-method ssim --content-strategy scene
```

When scene detection yields fewer than 3 frames (e.g., for a static video or a very high threshold), the tool automatically falls back to interval-based extraction. This means `--content-strategy scene` is always safe to use — you get adaptive keyframes when the content has meaningful scene changes, and reliable coverage otherwise.

`--scene-threshold T` sets the scene change sensitivity in the exclusive range (0.0, 1.0), default `0.3`. Lower values are more sensitive (more frames), higher values are less sensitive (fewer frames).

**Scope:** `--content-strategy scene` and `--scene-threshold` apply only to video content hashing. Image mode uses direct PIL hashing regardless of strategy; setting `--content-strategy scene` in image mode prints a warning and is otherwise ignored. `--content-strategy` and `--scene-threshold` without `--content` are silently ignored.

Cache entries for phash include the strategy and scene threshold, so switching between `interval` and `scene` (or changing `--scene-threshold`) automatically invalidates cached hashes and forces re-extraction.

`--content-strategy` and `--scene-threshold` are persistable via `--save-config`.

### Weight redistribution

When `--content` is active, scoring weights are adjusted so the content signal has the most influence.

**Video mode:**

| Criterion | Default | With `--content` | With `--audio` + `--content` |
|---|---|---|---|
| Filename | 35 | 20 | 15 |
| Duration | 35 | 20 | 15 |
| Resolution | 15 | 10 | 10 |
| File size | 15 | 10 | 10 |
| **Audio** | — | — | 10 |
| **Content** | — | **40** | **40** |

**Image mode (`--mode image`):**

| Criterion | Default | With `--content` |
|---|---|---|
| Filename | 25 | 15 |
| EXIF | 40 | 25 |
| Resolution | 20 | 10 |
| File size | 15 | 10 |
| **Content** | — | **40** |

These defaults can be overridden with `--weights` (see [Custom Weights](#custom-weights) above). In image mode, the `exif` key replaces `duration` in weight specifications. See [Audio Fingerprinting](#audio-fingerprinting) for the `--audio`-only video mode weight defaults. See [Audio Deduplication](#audio-deduplication) for audio mode weight defaults.

### Performance

Content hashing is **10–100× slower** than metadata-only comparison because it requires decoding video frames. Use it when:

- You suspect re-encoded or transcoded duplicates
- Metadata-only scoring produces false negatives
- You have time for a thorough scan

For routine scans of well-organized libraries, metadata-only comparison (the default) is usually sufficient.

### Caching

**Metadata cache** (on by default): ffprobe results (duration, resolution, codec, bitrate, frame rate, audio channels) are cached on disk. In image mode, PIL metadata (resolution, file size, and EXIF fields) is cached the same way. In audio mode, mutagen tag data (duration, title, artist, album) is cached the same way. Subsequent runs skip extraction for files whose size and modification time haven't changed — this makes re-runs on large collections near-instant. Disable with `--no-metadata-cache`.

**Content hash cache** (when `--content` is used with `--content-method phash`): Perceptual hashes are cached similarly. A cached hash is invalidated when any of these change: file size, modification time, extraction interval, hash size, hash algorithm, content strategy, or scene threshold. Disable with `--no-content-cache`. Note: the SSIM method (`--content-method ssim`) does not use the content cache — frames are compared directly on every run, so `--no-content-cache` has no effect when SSIM is active.

**Audio fingerprint cache** (when `--audio` is active): Chromaprint fingerprints computed by `fpcalc` are cached on disk. A cached fingerprint is invalidated when the file size or modification time changes. Disable with `--no-audio-cache`.

Both caches are stored at:

- `$XDG_CACHE_HOME/duplicates-detector/` (if `XDG_CACHE_HOME` is set)
- `~/.cache/duplicates-detector/` (default)

To clear all caches:

```bash
rm -rf ~/.cache/duplicates-detector/
```

### Threshold recommendations

With `--content` enabled, the content signal (weight 40) makes scores more discriminating. Consider lowering the threshold:

- **`--threshold 30`** — catches most perceptual matches including partial overlaps
- **`--threshold 40`** — good balance of precision and recall (recommended with `--content`)
- **`--threshold 50`** (default) — conservative, may miss borderline cases

## Audio Fingerprinting

The `--audio` flag enables Chromaprint-based audio fingerprinting using the `fpcalc` CLI tool. In video mode, it computes an acoustic fingerprint of each video's audio track — two videos with the same audio content score very high regardless of filename, codec, resolution, or container, making this the most reliable way to detect re-encoded video duplicates. In audio mode (`--mode audio`), it adds fingerprint similarity as a fourth scoring criterion alongside filename, duration, and tags. See [Audio Deduplication](#audio-deduplication) for audio mode specifics.

Typical use cases:

- **Re-encoded videos** — same content transcoded to a different codec or bitrate while the audio is preserved
- **Format conversions** — the same film in `.mp4`, `.mkv`, or `.avi` with identical audio
- **Resolution variants** — a 1080p and a 720p copy with the same audio track
- **Renamed files** — a duplicate saved under a completely different filename

### Requirements

`fpcalc` must be available on your PATH. Install it via Chromaprint:

```bash
# macOS
brew install chromaprint

# Ubuntu/Debian
sudo apt install libchromaprint-tools
```

The tool performs a `check_fpcalc()` call at startup when `--audio` is active; if `fpcalc` is not found, it exits with a clear error.

### Basic usage

```bash
# Enable audio fingerprinting
duplicates-detector /path/to/videos --audio

# Combine with perceptual content hashing for maximum coverage
duplicates-detector /path/to/videos --audio --content

# Combine with group mode — useful when many re-encodes exist
duplicates-detector /path/to/videos --audio --group

# Verbose — shows audio score in the per-comparator breakdown
duplicates-detector /path/to/videos --audio -v
```

### Default weights with `--audio`

When `--audio` is active, weights are adjusted to give the audio signal significant influence:

| Criterion | Default | With `--audio` | With `--audio` + `--content` |
|---|---|---|---|
| Filename | 35 | 25 | 15 |
| Duration | 35 | 25 | 15 |
| Resolution | 15 | 10 | 10 |
| File size | 15 | 10 | 10 |
| **Audio** | — | **30** | 10 |
| **Content** | — | — | **40** |

These defaults can be overridden with `--weights`. When `--audio` is active, the `audio` key is required and must be included in any custom weight specification:

```bash
# Emphasize audio (video mode)
duplicates-detector /path/to/videos --audio --weights 'filename=10,duration=20,resolution=10,filesize=10,audio=50'

# Combine audio and content with custom weights
duplicates-detector /path/to/videos --audio --content --weights 'filename=10,duration=10,resolution=10,filesize=10,audio=20,content=40'
```

### Caching

Audio fingerprints are cached on disk alongside metadata and content hashes. A cached fingerprint is invalidated when the file size or modification time changes. Disable the audio fingerprint cache with `--no-audio-cache` (forces `fpcalc` to re-run on every file):

```bash
duplicates-detector /path/to/videos --audio --no-audio-cache
```

### Scope

`--audio` works in **video mode** and **audio mode** (`--mode audio`). It produces an error in `--mode image`. In `--mode auto`, audio fingerprinting applies only to the video sub-pipeline; image files are unaffected. See [Audio Deduplication](#audio-deduplication) for how `--audio` integrates with audio mode scoring.

`--no-audio-cache` without `--audio` is silently ignored.

### Configurable

`--audio` and `--no-audio-cache` are persistable via `--save-config`:

```bash
duplicates-detector /path/to/videos --audio --save-config
```

```toml
audio = true
```

## Image Deduplication

Use `--mode image` to deduplicate photo libraries. Image mode shares the same pipeline as video mode but substitutes PIL for ffprobe (no ffmpeg required) and scores EXIF metadata instead of duration.

```bash
# Basic image deduplication
duplicates-detector /path/to/photos --mode image

# Verbose — shows EXIF breakdown alongside other scores
duplicates-detector /path/to/photos --mode image -v

# Content-based comparison in addition to EXIF (perceptual hashing via PIL)
duplicates-detector /path/to/photos --mode image --content

# Mixed media — run video and image pipelines in a single pass
duplicates-detector /path/to/media --mode auto
```

Supported image formats: `.jpg`/`.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`/`.tif`, `.webp`, `.heic`/`.heif`. HEIC support requires the optional `pillow-heif` plugin; missing HEIC files are skipped gracefully rather than causing an error.

### EXIF Metadata Comparator

The EXIF comparator automatically activates in image mode and image sub-pipeline of auto mode. It scores five sub-fields, each contributing a portion of the overall EXIF score:

| Sub-field | Weight | Scoring |
|---|---|---|
| Capture timestamp (`DateTime`) | 35% | Linear falloff over 1 hour — photos taken at the same second score 1.0; photos taken more than 1 hour apart score 0.0 |
| Camera make + model | 20% | Exact match — same camera scores 1.0; different camera (or one missing) scores 0.0 |
| Lens model | 10% | Exact match |
| GPS coordinates | 25% | Haversine distance with linear falloff over 1 km — same location scores 1.0; locations more than 1 km apart score 0.0 |
| EXIF dimensions vs actual | 10% | Checks that the pixel dimensions stored in EXIF match the actual image dimensions (catches re-saved or stripped copies) |

**Graceful degradation:** Files without EXIF data — PNGs, stripped JPEGs, screenshots — receive `None` for the EXIF comparator. Its weight (40 by default) is redistributed proportionally among the other active comparators, so the total score still sums to 100. The tool never fails due to missing EXIF.

**Caching:** EXIF fields are stored in the metadata cache alongside resolution and file size. Subsequent runs on unchanged files skip EXIF extraction entirely. Disable with `--no-metadata-cache`.

**No new dependencies:** EXIF extraction uses PIL's built-in EXIF support (already a dependency for image content hashing). GPS haversine distance uses only `math` from the standard library.

### Default Weights for Image Mode

Image mode uses different default weights that reflect the reliability of each signal for photos:

| Criterion | Default | With `--content` |
|---|---|---|
| Filename | 25 | 15 |
| EXIF | 40 | 25 |
| Resolution | 20 | 10 |
| File size | 15 | 10 |
| Content | — | 40 |

### Custom Weights in Image Mode

The `--weights` flag in image mode requires an `exif` key and rejects the `duration` key:

```bash
# Default image mode weights
duplicates-detector /photos --mode image --weights 'filename=25,resolution=20,filesize=15,exif=40'

# Emphasize EXIF — useful when photos are consistently renamed
duplicates-detector /photos --mode image --weights 'filename=10,resolution=20,filesize=10,exif=60'

# Disable EXIF — useful for libraries of PNGs or screenshots with no EXIF data
duplicates-detector /photos --mode image --weights 'filename=40,resolution=35,filesize=25,exif=0'

# Image mode with content hashing
duplicates-detector /photos --mode image --content --weights 'filename=15,resolution=10,filesize=10,exif=25,content=40'
```

Setting `exif=0` effectively disables EXIF scoring for the entire run — useful when your library consists entirely of format-converted images that have had EXIF stripped.

### Flags not available in image mode

The following flags are not compatible with `--mode image` and produce an error if used:

- `--keep longest` — images have no duration
- `--min-duration` / `--max-duration` — images have no duration
- `--min-bitrate` / `--max-bitrate` — images have no bitrate
- `--audio` — audio fingerprinting is video-only; images have no audio track

`--content-interval` is accepted for config compatibility but has no effect in image mode (images are hashed directly from the file, not via frame extraction). A warning is printed if it is set.

## Audio Deduplication

Use `--mode audio` to deduplicate music libraries. Audio mode uses `mutagen` for metadata extraction (no ffprobe required) and scores filename, duration, and embedded tag similarity (title, artist, album).

```bash
# Basic audio deduplication
duplicates-detector /path/to/music --mode audio

# Verbose — shows tag breakdown alongside other scores
duplicates-detector /path/to/music --mode audio -v

# Keep the longest version of each duplicate
duplicates-detector /path/to/music --mode audio --keep longest

# Keep the biggest file (e.g., highest bitrate FLAC over lossy MP3)
duplicates-detector /path/to/music --mode audio --keep biggest

# Add Chromaprint fingerprinting for acoustic similarity (requires fpcalc)
duplicates-detector /path/to/music --mode audio --audio

# Group transitive duplicates into clusters
duplicates-detector /path/to/music --mode audio --group
```

Requires the optional `mutagen` dependency:

```bash
pip install "duplicates-detector[audio]"
```

Supported audio formats: `.mp3`, `.flac`, `.aac`, `.m4a`, `.wav`, `.ogg`, `.opus`, `.wma`, `.ape`, `.alac`, `.aiff`, `.wv`, `.dsf`, `.dff`.

### Tag Comparator

The tag comparator automatically activates in audio mode. It scores three sub-fields using rapidfuzz fuzzy matching:

| Sub-field | Weight | Scoring |
|---|---|---|
| Title | — | Fuzzy string similarity — tolerates minor punctuation and subtitle differences |
| Artist | — | Fuzzy string similarity — tolerates featuring credits and name variations |
| Album | — | Fuzzy string similarity — tolerates edition names and year suffixes |

All three sub-fields are weighted equally and averaged to produce the final tag score. Files with no embedded tags receive `None` for the tag comparator; its weight (40 by default) is redistributed proportionally among the remaining comparators so the total always sums to 100.

### Default Weights for Audio Mode

| Criterion | Default | With `--audio` |
|---|---|---|
| Filename | 30 | 15 |
| Duration | 30 | 15 |
| Tags | 40 | 20 |
| **Audio (Chromaprint)** | — | **50** |

### Custom Weights in Audio Mode

The `--weights` flag in audio mode requires a `tags` key and rejects `resolution`, `filesize`, `exif`, and `content` keys:

```bash
# Default audio mode weights
duplicates-detector /music --mode audio --weights 'filename=30,duration=30,tags=40'

# Emphasize tags — useful for libraries with consistently tagged files but varied filenames
duplicates-detector /music --mode audio --weights 'filename=10,duration=20,tags=70'

# Disable tags — useful for libraries with stripped or absent metadata
duplicates-detector /music --mode audio --weights 'filename=50,duration=50,tags=0'

# With Chromaprint fingerprinting
duplicates-detector /music --mode audio --audio --weights 'filename=15,duration=15,tags=20,audio=50'
```

Setting `tags=0` effectively disables tag scoring for the entire run — useful when your music library has no embedded metadata.

### Chromaprint fingerprinting in audio mode

Adding `--audio` to audio mode includes Chromaprint acoustic fingerprint similarity as a fourth scoring criterion. This is the most reliable signal for detecting re-encoded or re-tagged copies of the same recording:

```bash
# Audio deduplication with Chromaprint fingerprinting
duplicates-detector /path/to/music --mode audio --audio

# Combine with group mode for large libraries with many re-encodes
duplicates-detector /path/to/music --mode audio --audio --group

# Verbose — shows audio fingerprint score in the breakdown
duplicates-detector /path/to/music --mode audio --audio -v
```

Requires `fpcalc` on PATH — see [Audio Fingerprinting](#audio-fingerprinting) for installation instructions. Audio fingerprint results are cached on disk; disable with `--no-audio-cache`.

### Flags not available in audio mode

The following flags are not compatible with `--mode audio` and produce an error if used:

- `--keep highest-res` — audio files have no resolution
- `--min-resolution` / `--max-resolution` — audio files have no resolution
- `--content` — perceptual content hashing is not supported for audio files; use `--audio` for acoustic fingerprinting instead

`--min-duration`, `--max-duration`, `--min-bitrate`, `--max-bitrate`, and `--codec` work normally in audio mode.

## Watch Mode

Watch mode monitors one or more directories for filesystem events and emits a stream of JSON-lines to stdout whenever duplicates are detected. It performs a full scan on startup (identical to a regular scan run) and then watches for file creates, modifications, and deletions incrementally.

Watch mode is **observe-only** — it never deletes files, creates links, or prompts interactively. Use the scan subcommand (with `--keep`, `--action`, `-i`) to act on results.

### Installation

Watch mode requires the `watchdog` library, available as an optional extra:

```bash
pip install "duplicates-detector[watch]"
```

### Basic usage

```bash
# Watch a video directory with default settings
duplicates-detector watch /path/to/videos

# Verbose — progress and diagnostics go to stderr, JSON-lines to stdout
duplicates-detector watch /path/to/videos -v

# Watch a music library in audio mode
duplicates-detector watch /path/to/music --mode audio

# Watch a photo library in image mode
duplicates-detector watch /path/to/photos --mode image

# Log JSON-lines to a file, diagnostics to a separate log
duplicates-detector watch /path/to/videos > watch.jsonl 2>watch.log

# Filter only duplicate events with jq
duplicates-detector watch /path/to/videos | jq 'select(.event == "duplicate_found")'

# Pretty-print all events
duplicates-detector watch /path/to/videos | jq .
```

### Watch-specific flags

| Flag | Default | Description |
|---|---|---|
| `--debounce SECS` | `2.0` | Seconds to wait after a filesystem event before scanning the affected file. Prevents scanning partially-written or still-copying files. |
| `--webhook URL` | none | POST each JSON event payload to the given URL (best-effort, 5 s timeout). Useful for Slack, Discord, or custom webhook integrations. |
| `--heartbeat-interval SECS` | `60.0` | Interval between periodic `heartbeat` events. Set to `0` to disable heartbeats. |
| `--on-duplicate notify` | none | Send a desktop notification when a duplicate is found (macOS/Linux). |

### Shared flags

These flags work identically in both `scan` and `watch` subcommands:

`--mode`, `--content`, `--audio`, `--weights`, `--threshold`, `--min-score`, `--min-size`, `--max-size`, `--extensions`, `--exclude`, `--reference`, `--workers`, `--verbose`, `--quiet`, `--no-color`, `--cache-dir`, `--no-metadata-cache`, `--no-content-cache`, `--no-audio-cache`, `--profile`, `--no-config`

`--machine-progress` is accepted by the `watch` subcommand but is silently ignored — watch mode already emits JSON-lines to stdout via its own event stream and has no long-running batch stages that need progress tracking.

Flags specific to the scan pipeline — `--keep`, `--action`, `--interactive`, `--dry-run`, `--group`, `--sort`, `--limit`, `--format`, `--output`, `--log`, `--replay`, `--generate-undo` — are not available in watch mode and produce an error if used.

### JSON-lines output format

Each event is a single JSON object on its own line. All events have an `event` field (the event type) and a `timestamp` field (ISO 8601 with UTC offset).

**`watch_started`** — emitted once on startup after the initial scan completes:

```json
{"event": "watch_started", "timestamp": "2024-01-15T10:30:00+00:00", "directories": ["/videos"], "mode": "video", "file_count": 42, "options": {"content": false, "audio": false, "threshold": 50, "min_score": null, "debounce": 2.0, "heartbeat_interval": 60.0}}
```

**`duplicate_found`** — emitted for each pair that scores above the threshold. Includes the triggering filesystem event, the pair's file paths and score, and a per-comparator breakdown:

```json
{"event": "duplicate_found", "timestamp": "2024-01-15T10:30:05+00:00", "trigger": {"type": "created", "path": "/videos/copy.mp4"}, "pair": {"file_a": "/videos/original.mp4", "file_b": "/videos/copy.mp4", "score": 95.0, "breakdown": {"filename": 40.0, "duration": 30.0, "resolution": 10.0, "file_size": 10.0}, "detail": {"filename": {"raw": 0.8, "weight": 50.0}, "duration": {"raw": 1.0, "weight": 30.0}, "resolution": {"raw": 1.0, "weight": 10.0}, "file_size": {"raw": 1.0, "weight": 10.0}}}}
```

**`file_removed`** — emitted when a tracked file is deleted from a watched directory. Includes the number of pairs that were invalidated and removed from the active pair set:

```json
{"event": "file_removed", "timestamp": "2024-01-15T10:35:00+00:00", "path": "/videos/copy.mp4", "invalidated_pairs": 1}
```

**`heartbeat`** — periodic status pulse. Shows how many files are currently tracked and how many active duplicate pairs have been found since startup:

```json
{"event": "heartbeat", "timestamp": "2024-01-15T10:31:00+00:00", "tracked_files": 43, "active_pairs": 1}
```

**`error`** — emitted when metadata extraction fails for a file (e.g., corrupt file, permission denied):

```json
{"event": "error", "timestamp": "2024-01-15T10:30:03+00:00", "path": "/videos/bad.mp4", "message": "ffprobe failed: ..."}
```

**`watch_stopped`** — emitted on clean shutdown (SIGINT or SIGTERM):

```json
{"event": "watch_stopped", "timestamp": "2024-01-15T11:00:00+00:00", "tracked_files": 43, "total_pairs_emitted": 2}
```

### Integration examples

```bash
# Send duplicate alerts to a Slack webhook
duplicates-detector watch /videos --webhook https://hooks.slack.com/services/...

# Accumulate events for later batch review
duplicates-detector watch /videos > watch.jsonl 2>watch.log &

# Extract just the file paths from duplicate events
duplicates-detector watch /videos | jq -r 'select(.event == "duplicate_found") | .pair | "\(.file_a)\n\(.file_b)"'

# Monitor with a slower debounce (useful for slow network drives)
duplicates-detector watch /mnt/nas --debounce 10.0

# Watch with content-based comparison and no heartbeats
duplicates-detector watch /videos --content --heartbeat-interval 0

# Watch multiple directories
duplicates-detector watch /videos /backups --mode video
```

### Caching

Existing metadata, content, and audio fingerprint caches are reused by watch mode. This makes restarts near-instant — only new or modified files need extraction. Disable with the same cache flags as the scan subcommand (`--no-metadata-cache`, `--no-content-cache`, `--no-audio-cache`).

### Graceful shutdown

Send SIGINT (Ctrl-C) or SIGTERM to stop the watcher cleanly. A `watch_stopped` event is emitted before the process exits.

## Configuration

If you find yourself using the same flags every time, you can save them to a config file so they're applied automatically on every run.

### Saving defaults

```bash
# Save your preferred flags
duplicates-detector /path --threshold 30 --keep biggest --content --save-config
```

This writes the flags to a TOML config file and exits (the scan pipeline does not run). On subsequent runs, these values are used as defaults — no need to type them again.

### Config file location

The config file is stored at:

- `$XDG_CONFIG_HOME/duplicates-detector/config.toml` (if `XDG_CONFIG_HOME` is set)
- `~/.config/duplicates-detector/config.toml` (default)

### Merge order

The merge order is: **hardcoded defaults → config file → CLI flags**. CLI flags always win:

```bash
# Config has threshold=30, but this run uses 80
duplicates-detector /path --threshold 80
```

### Inspecting the config

```bash
# Show the resolved config (hardcoded defaults + config file + any CLI flags)
duplicates-detector --show-config
```

### Ignoring the config

```bash
# Use only hardcoded defaults + CLI flags for this run
duplicates-detector /path --no-config
```

### Config file format

The config file uses [TOML](https://toml.io/) format. Only non-default values are written by `--save-config`:

```toml
# duplicates-detector configuration
# Generated by: duplicates-detector --save-config

threshold = 30
keep = "biggest"
content = true

exclude = [
    "**/thumbnails/**",
]
```

### Configurable fields

All flags that represent reusable preferences can be saved. Session-specific flags (`directories`, `--reference`, `--output`, `--interactive`, `--dry-run`) are never stored.

| TOML key | CLI flag | Type |
|---|---|---|
| `threshold` | `--threshold` | integer (0–100) |
| `min_score` | `--min-score` | integer (0–100) |
| `mode` | `--mode` | string (`video`, `image`, `auto`, or `audio`) |
| `extensions` | `--extensions` | string (comma-separated) |
| `workers` | `--workers` | integer |
| `keep` | `--keep` | string |
| `action` | `--action` | string (`delete`, `trash`, `move-to`, `hardlink`, `symlink`, or `reflink`) |
| `move_to_dir` | `--move-to-dir` | string (directory path) |
| `format` | `--format` | string |
| `sort` | `--sort` | string (`score`, `size`, `path`, or `mtime`) |
| `limit` | `--limit` | integer (> 0) |
| `verbose` | `-v` / `--verbose` | boolean |
| `quiet` | `-q` / `--quiet` | boolean |
| `no_color` | `--no-color` | boolean |
| `machine_progress` | `--machine-progress` | boolean |
| `content` | `--content` | boolean |
| `content_method` | `--content-method` | string (`phash` or `ssim`) |
| `content_interval` | `--content-interval` | number (seconds, > 0) |
| `content_strategy` | `--content-strategy` | string (`interval` or `scene`) |
| `scene_threshold` | `--scene-threshold` | number (0.0–1.0 exclusive) |
| `hash_size` | `--hash-size` | integer (>= 2) |
| `hash_algo` | `--hash-algo` | string (`phash`, `dhash`, `whash`, or `ahash`) |
| `rotation_invariant` | `--rotation-invariant` | boolean |
| `json_envelope` | `--json-envelope` | boolean |
| `embed_thumbnails` | `--embed-thumbnails` | boolean |
| `thumbnail_size` | `--thumbnail-size` | string (e.g. `"160x90"`) |
| `group` | `--group` | boolean |
| `no_recursive` | `--no-recursive` | boolean |
| `no_content_cache` | `--no-content-cache` | boolean |
| `audio` | `--audio` | boolean |
| `no_audio_cache` | `--no-audio-cache` | boolean |
| `no_metadata_cache` | `--no-metadata-cache` | boolean |
| `min_size` | `--min-size` | string (e.g. `"10MB"`) |
| `max_size` | `--max-size` | string (e.g. `"4GB"`) |
| `min_duration` | `--min-duration` | number (seconds) |
| `max_duration` | `--max-duration` | number (seconds) |
| `min_resolution` | `--min-resolution` | string (e.g. `"1280x720"`) |
| `max_resolution` | `--max-resolution` | string (e.g. `"1920x1080"`) |
| `min_bitrate` | `--min-bitrate` | string (e.g. `"5Mbps"`) |
| `max_bitrate` | `--max-bitrate` | string (e.g. `"20Mbps"`) |
| `codec` | `--codec` | string (comma-separated) |
| `log` | `--log` | string (file path) |
| `ignore_file` | `--ignore-file` | string (file path) |
| `exclude` | `--exclude` | array of strings |
| `[weights]` | `--weights` | table of key = number pairs |

### Exclude pattern merging

The `exclude` field is the one field where CLI **appends** rather than replaces. If your config has `exclude = ["**/thumbnails/**"]` and you run `--exclude "*.tmp"`, the effective list is `["**/thumbnails/**", "*.tmp"]`. To run without config excludes, use `--no-config`.

### Error handling

Missing, corrupt, or invalid config files produce warnings but never prevent the tool from running. Invalid values for individual fields are skipped with a warning — the rest of the config is still applied.

## Scan Profiles

Profiles let you save a named collection of flags that can be loaded with a single `--profile` flag. They are useful when you regularly scan different libraries with different settings — for example, one profile for video deduplication with content hashing and another for quick photo deduplication.

### Saving a profile

```bash
# Save a profile for photo deduplication
duplicates-detector /photos --mode image --content --save-profile photos

# Save a profile for mixed media (camera roll with photos and videos)
duplicates-detector /camera-roll --mode auto --content --save-profile camera-roll

# Save a profile for music library deduplication
duplicates-detector /music --mode audio --audio --save-profile music

# Save a profile for a fast video pre-scan
duplicates-detector /videos --threshold 70 --min-size 100MB --save-profile fast-scan
```

`--save-profile NAME` writes the current effective configuration (after merging the global config file and any CLI flags) to a TOML file and exits — the scan pipeline does not run. The profile is saved to:

- `$XDG_CONFIG_HOME/duplicates-detector/profiles/NAME.toml` (if `XDG_CONFIG_HOME` is set)
- `~/.config/duplicates-detector/profiles/NAME.toml` (default)

Profile names may contain letters, digits, `_`, `-`, and `.`. Empty names, names with whitespace, path traversal segments (`..`), and slashes are rejected with an error.

### Loading a profile

```bash
# Use the saved profile
duplicates-detector /photos --profile photos

# Override a profile setting via CLI
duplicates-detector /camera-roll --profile photos --content-interval 1.0
```

`--profile NAME` loads the named profile and applies it as defaults. CLI flags still take precedence over any profile value.

### Merge order

The full merge order, from lowest to highest precedence, is:

**hardcoded defaults → global config file → profile → CLI flags**

This means a profile can override the global config, and a CLI flag can override the profile:

```bash
# Global config has threshold=50; profile has threshold=30; CLI wins with 80
duplicates-detector /path --profile fast-scan --threshold 80
```

### Combining with `--no-config`

`--no-config` skips the global config file but still honors `--profile`:

```bash
# Skip global config, use profile only
duplicates-detector /videos --no-config --profile fast-scan
```

This is useful when you want a clean baseline that only contains the profile settings, with no influence from your global config.

### `exclude` patterns are additive

Like with the global config, `exclude` patterns accumulate across all layers. If the global config has `exclude = ["**/thumbnails/**"]` and the profile adds `exclude = ["**/samples/**"]`, the effective list is both patterns combined. CLI `--exclude` appends on top of that.

### Profile file format

Profile files use the same TOML format as the global config. Only non-default values are written:

```toml
# duplicates-detector profile
# Generated by: duplicates-detector --save-profile photos

mode = "image"
content = true
min_size = "500KB"

exclude = [
    "**/thumbnails/**",
]
```

### Error handling

Missing or corrupt profiles that were explicitly requested with `--profile` are always fatal — the tool exits with an error rather than silently ignoring them. This is intentional: if you asked for a specific profile, running with different settings than expected is worse than failing clearly.

```
Error: profile 'fast-scan' not found: ~/.config/duplicates-detector/profiles/fast-scan.toml
```

## Sorting and Limiting

By default, results are sorted by similarity score (highest first). Use `--sort` to change the sort order and `--limit` to cap the number of results:

```bash
# Top 10 largest duplicate pairs
duplicates-detector /path/to/videos --sort size --limit 10

# Most recently modified duplicates
duplicates-detector /path/to/videos --sort mtime

# Alphabetical by file path
duplicates-detector /path/to/videos --sort path
```

| Sort Field | Order | What It Sorts By |
|---|---|---|
| `score` (default) | Descending | Similarity score |
| `size` | Descending | Combined file size of both files (or all group members) |
| `path` | Ascending | File path of the first file |
| `mtime` | Descending | Most recent modification time across both files |

Sorting is applied before limiting, so `--sort size --limit 5` gives you the 5 largest duplicate pairs. Both flags work with `--group` mode and are persistable via `--save-config`.

## Filtering Results by Score

Use `--min-score N` to hide pairs below a given similarity threshold from the output. This is a post-scoring display filter — all pairs are still scored internally, but only pairs meeting the minimum score are shown:

```bash
# Only show pairs with score ≥ 80
duplicates-detector /path/to/videos --min-score 80

# Combine with --limit: filter first, then cap output
duplicates-detector /path/to/videos --min-score 60 --limit 50

# Works with all output formats
duplicates-detector /path/to/videos --min-score 70 --format json
duplicates-detector /path/to/videos --min-score 70 --format csv

# Works with grouping — pairs below the threshold are excluded before groups are formed
duplicates-detector /path/to/videos --min-score 75 --group

# Save as a persistent default
duplicates-detector /path/to/videos --min-score 80 --save-config
```

### `--min-score` vs `--threshold`

These two flags serve different purposes:

| Flag | Stage | Effect |
|---|---|---|
| `--threshold N` | Scoring | Controls which pairs the scorer generates. Pairs below this score are never produced. Default: 50. |
| `--min-score N` | Display | Hides pairs from output after scoring. Pairs are still scored but filtered before reporting. |

Because `--threshold` acts at the scorer level, setting `--min-score` lower than `--threshold` has no effect — the scorer has already filtered those pairs out. A typical use case is to keep a low `--threshold` for comprehensive scoring while setting `--min-score` higher to focus the displayed results:

```bash
# Score all pairs above 30, but only display those scoring ≥ 80
duplicates-detector /path/to/videos --threshold 30 --min-score 80
```

### Pipeline order

`score → ignore-list filter → min-score filter → group → sort → limit → report`

This means `--min-score` narrows the pool before grouping (transitive clusters only include high-confidence links) and before `--limit` (so you get the top N results from the filtered set, not from the full set).

The summary panel reflects the filtering:

```
45,321 pairs scored → 423 duplicates → 312 above min-score 80
```

`--min-score` is persistable via `--save-config` and configurable in `config.toml`:

```toml
min_score = 80
```

## Quiet Mode and Color Control

Use `-q` / `--quiet` to suppress progress bars and the summary panel, producing only the requested output. This is ideal for scripting and piping:

```bash
# Machine-readable JSON with no progress noise
duplicates-detector /path/to/videos -q --format json > results.json

# CSV for spreadsheet import
duplicates-detector /path/to/videos -q --format csv > results.csv
```

`--quiet` is mutually exclusive with `--interactive` (you can't suppress output and prompt at the same time).

Use `--no-color` to disable all ANSI color codes in terminal output:

```bash
duplicates-detector /path/to/videos --no-color
```

## Machine-Readable Progress Events

Use `--machine-progress` to emit structured JSON-lines progress events to **stderr** during pipeline execution. This replaces Rich progress bars with a machine-parseable stream that GUI frontends — such as a macOS SwiftUI companion app — can consume for real-time progress display.

```bash
# Capture progress events on stderr while results go to stdout
duplicates-detector scan /path/to/videos --machine-progress 2>progress.jsonl

# Combine with JSON output — progress on stderr, structured results on stdout
duplicates-detector scan /path/to/videos --machine-progress --format json --json-envelope --output results.json

# Combine with --quiet to suppress the Rich summary panel while still emitting progress
duplicates-detector scan /path/to/videos --machine-progress --quiet --format json

# Save as a persistent default
duplicates-detector scan --machine-progress --save-config
```

`--machine-progress` is **orthogonal to `--quiet`**: `--quiet` suppresses the summary panel and Rich output; `--machine-progress` emits JSON progress events. Both flags can be active at the same time. When `--machine-progress` is active, Rich progress bars are suppressed regardless of `--quiet`, because mixing Rich ANSI escape codes and JSON on the same stderr stream would corrupt both.

### Event types

Every event is a single JSON object followed by a newline, written to stderr.

#### `stage_start` — emitted when a pipeline stage begins

```json
{"type":"stage_start","stage":"scan","timestamp":"2025-01-15T10:30:00.123+00:00"}
{"type":"stage_start","stage":"extract","total":42,"timestamp":"2025-01-15T10:30:01.000+00:00"}
{"type":"stage_start","stage":"score","total":500,"timestamp":"2025-01-15T10:30:02.000+00:00"}
```

The `total` field is included when the total item count is known at stage start. It is omitted for the `scan` stage, where the total is not known until scanning completes.

#### `progress` — emitted periodically during a stage

```json
{"type":"progress","stage":"extract","current":5,"total":42,"file":"/path/to/video.mp4","timestamp":"2025-01-15T10:30:01.050+00:00"}
{"type":"progress","stage":"score","current":100,"total":500,"timestamp":"2025-01-15T10:30:02.200+00:00"}
{"type":"progress","stage":"scan","current":30,"timestamp":"2025-01-15T10:30:00.250+00:00"}
```

- `current` — number of items processed so far
- `total` — total item count (omitted for the `scan` stage)
- `file` — path of the file just processed; present for per-file stages (`extract`, `content_hash`, `ssim_extract`, `audio_fingerprint`), omitted for `scan` and `score`

**Throttling:** Progress events are emitted at most once every 100 ms to avoid flooding stderr. The final event for each stage (where `current == total`) always emits, ensuring 100% completion is always reported.

#### `stage_end` — emitted when a pipeline stage completes

```json
{"type":"stage_end","stage":"extract","total":42,"elapsed":3.141,"timestamp":"2025-01-15T10:30:04.141+00:00"}
{"type":"stage_end","stage":"score","total":500,"pairs_found":15,"elapsed":12.500,"timestamp":"2025-01-15T10:30:14.500+00:00"}
{"type":"stage_end","stage":"filter","total":38,"elapsed":0.002,"timestamp":"2025-01-15T10:30:01.003+00:00"}
```

- `elapsed` — wall-clock seconds for this stage, rounded to 3 decimal places
- `total` — final item count for the stage
- `pairs_found` — only present for the `score` stage; the number of pairs above the threshold

### Pipeline stages

| Stage | Description | `total` at start | `file` in events |
|---|---|---|---|
| `scan` | File discovery | No | No |
| `extract` | Metadata extraction (ffprobe / PIL / mutagen) | Yes | Yes |
| `filter` | Size / duration / resolution / bitrate filtering — instant, no `progress` events | No | No |
| `content_hash` | Perceptual hash computation (when `--content` is used) | Yes | Yes |
| `ssim_extract` | SSIM frame extraction (when `--content-method ssim` is used) | Yes | Yes |
| `audio_fingerprint` | Chromaprint fingerprint extraction (when `--audio` is used) | Yes | Yes |
| `score` | Duplicate pair scoring | Yes | No |
| `thumbnail` | Thumbnail generation (when `--embed-thumbnails` is used) | Yes | No |

The `filter` stage emits only `stage_start` and `stage_end` — no intermediate `progress` events — because filtering completes in a single pass with no meaningful per-item loop. The `report` stage produces no events.

### Full example output

A scan of 200 files producing progress events on stderr:

```jsonl
{"type":"stage_start","stage":"scan","timestamp":"2025-01-15T10:30:00.000+00:00"}
{"type":"progress","stage":"scan","current":50,"timestamp":"2025-01-15T10:30:00.150+00:00"}
{"type":"progress","stage":"scan","current":200,"timestamp":"2025-01-15T10:30:00.340+00:00"}
{"type":"stage_end","stage":"scan","total":200,"elapsed":0.340,"timestamp":"2025-01-15T10:30:00.340+00:00"}
{"type":"stage_start","stage":"extract","total":200,"timestamp":"2025-01-15T10:30:00.341+00:00"}
{"type":"progress","stage":"extract","current":1,"total":200,"file":"/videos/clip1.mp4","timestamp":"2025-01-15T10:30:00.450+00:00"}
{"type":"progress","stage":"extract","current":100,"total":200,"timestamp":"2025-01-15T10:30:01.000+00:00"}
{"type":"progress","stage":"extract","current":200,"total":200,"timestamp":"2025-01-15T10:30:01.560+00:00"}
{"type":"stage_end","stage":"extract","total":200,"elapsed":1.220,"timestamp":"2025-01-15T10:30:01.561+00:00"}
{"type":"stage_start","stage":"filter","timestamp":"2025-01-15T10:30:01.562+00:00"}
{"type":"stage_end","stage":"filter","total":185,"elapsed":0.010,"timestamp":"2025-01-15T10:30:01.572+00:00"}
{"type":"stage_start","stage":"score","total":1247,"timestamp":"2025-01-15T10:30:01.573+00:00"}
{"type":"progress","stage":"score","current":500,"total":1247,"timestamp":"2025-01-15T10:30:01.800+00:00"}
{"type":"progress","stage":"score","current":1247,"total":1247,"timestamp":"2025-01-15T10:30:02.020+00:00"}
{"type":"stage_end","stage":"score","total":1247,"pairs_found":23,"elapsed":0.450,"timestamp":"2025-01-15T10:30:02.023+00:00"}
```

### Timestamps

All timestamps are UTC ISO 8601, formatted to millisecond precision (e.g., `2025-01-15T10:30:00.123+00:00`).

### Watch mode

`--machine-progress` is silently ignored in `watch` mode. Watch mode already emits a JSON-lines event stream to stdout via its own `EventEmitter` and has no long-running batch stages that need progress tracking.

### Persistable

`--machine-progress` is persistable via `--save-config` and configurable in `config.toml`:

```toml
machine_progress = true
```

## Replay Mode

Use `--replay FILE` to load a previously saved JSON envelope and re-enter the pipeline at the post-scoring stage. This lets you experiment with different `--keep` strategies, output formats, or filtering options without re-scanning your library or waiting for metadata extraction and scoring to run again.

```bash
# Initial scan — save the envelope
duplicates-detector /path/to/videos --format json --json-envelope --output scan.json

# Try different strategies from the same scan
duplicates-detector --replay scan.json --keep biggest --dry-run
duplicates-detector --replay scan.json --keep longest --dry-run

# Raise the minimum score threshold
duplicates-detector --replay scan.json --min-score 80

# Cluster into groups and produce an HTML report
duplicates-detector --replay scan.json --group --format html --output report.html

# Interactive review of high-confidence matches
duplicates-detector --replay scan.json --min-score 75 -i

# Re-export as CSV for spreadsheet review
duplicates-detector --replay scan.json --format csv --output scan.csv
```

### Requirements

- The input file must be a JSON envelope produced with `--format json --json-envelope`. Bare JSON arrays (output without `--json-envelope`) are rejected with a descriptive error.
- Replay output with `--json-envelope` produces another valid envelope that can itself be replayed.

### Compatible flags

Post-scoring flags work normally in replay mode:

`--keep`, `--min-score`, `--sort`, `--group`, `--limit`, `--format`, `--output`, `-i` / `--interactive`, `--dry-run`, `--reference`, `--json-envelope`, `--embed-thumbnails`, `--thumbnail-size`, `--log`, `--ignore-file`, `-v`, `-q`, `--no-color`

`--reference` re-tagging works: directories listed with `--reference` are matched against the paths in the envelope and marked as reference accordingly.

### Conflicting flags

Scan-specific flags conflict with `--replay` and produce an error:

- `--content`, `--audio`, `--weights`
- `--exclude`, `--codec`
- `--min-size`, `--max-size`, `--min-duration`, `--max-duration`, `--min-resolution`, `--max-resolution`, `--min-bitrate`, `--max-bitrate`
- Cache flags (`--no-metadata-cache`, `--no-content-cache`, `--no-audio-cache`, `--cache-dir`)
- Explicit directory arguments

### Summary panel

In replay mode the summary panel shows simplified stats: source file, number of pairs loaded, and elapsed time. It does not show scan timing, cache hits, or extraction counts from the original run.

## Structured Dry-Run Reports

When using `--keep` with `--dry-run` and a machine-readable format (`json`, `shell`, or `html`), the output includes a structured summary of what would be deleted:

### JSON dry-run

```json
{
  "pairs": [ ... ],
  "dry_run_summary": {
    "files_to_delete": [
      { "path": "/path/to/duplicate.mp4", "size": 1073741824, "size_human": "1.0 GB" }
    ],
    "total_files": 3,
    "total_bytes": 3221225472,
    "total_bytes_human": "3.0 GB",
    "strategy": "biggest"
  }
}
```

When no files would be deleted (e.g., all pairs are undecidable), the output remains a flat JSON array for backward compatibility.

### Shell dry-run

The shell format appends summary comments at the end:

```bash
#!/usr/bin/env bash
# ...rm commands...

# --- Dry Run Summary ---
# Files to delete: 3
# Space to recover: 3.0 GB
# Strategy: biggest
# To execute, re-run without --dry-run
```

CSV and table formats are unaffected — CSV users can derive deletion decisions from the `keep` column. HTML dry-run reports include a dedicated summary section listing all files that would be deleted and the total space that would be recovered.

## Supported Formats

**Video** (default mode): `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.ts`, `.vob`, `.3gp`, `.ogv`.

**Image** (`--mode image`): `.jpg`/`.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`/`.tif`, `.webp`, `.heic`/`.heif`. HEIC support requires the optional `pillow-heif` plugin.

**Auto** (`--mode auto`): scans for both video and image extensions in one pass, runs independent pipelines for each type, and merges results.

**Audio** (`--mode audio`): `.mp3`, `.flac`, `.aac`, `.m4a`, `.wav`, `.ogg`, `.opus`, `.wma`, `.ape`, `.alac`, `.aiff`, `.wv`, `.dsf`, `.dff`. Requires the optional `mutagen` dependency (`pip install "duplicates-detector[audio]"`).

Override with `--extensions` if needed.

## Shell Completion

Tab completion is available for bash, zsh, and fish. Generate the completion script and add it to your shell profile:

```bash
# Bash
duplicates-detector --print-completion bash >> ~/.bashrc

# Zsh
duplicates-detector --print-completion zsh >> ~/.zshrc

# Fish
duplicates-detector --print-completion fish > ~/.config/fish/completions/duplicates-detector.fish
```

After sourcing your profile (or opening a new terminal), pressing Tab will auto-complete flags, choices (e.g., `--action` → `delete`, `trash`, `move-to`, `hardlink`, `symlink`, `reflink`), and directory arguments.

## Adding Custom Comparators

The scoring system is extensible. To add a new criterion:

1. Subclass `Comparator` in `duplicates_detector/comparators.py`
2. Implement `score(a, b) -> float` returning 0.0–1.0
3. Set `name` and `weight`
4. Add it to `get_default_comparators()`

```python
class BitrateComparator(Comparator):
    name = "bitrate"
    weight = 10.0

    def score(self, a: VideoMetadata, b: VideoMetadata) -> float:
        # your comparison logic here
        ...
```
