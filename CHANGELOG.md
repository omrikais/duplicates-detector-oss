# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [3.0.3] - 2026-04-08
### Added
- Add macOS app icon to the GUI application

## [3.0.2] - 2026-04-08
### Fixed
- CLI wrapper resolves symlinks so it works when called via Homebrew symlink
- CLI wrapper script now included in app bundle (was missing from DMG)

## [3.0.1] - 2026-04-08
### Changed
- Homebrew tap now distributes a pre-built DMG cask instead of building from source
- CLI binary is symlinked to PATH via Homebrew `binary` stanza for standalone use

### Fixed
- Homebrew install no longer requires compiling scipy/numpy from source
- CLI wrapper script uses bundled Python so it works outside the app

## [3.0.0] - 2026-04-08
### Added
- Add `--mode document` for document deduplication (PDF, DOCX, TXT, etc.) with page-count bucketing, SimHash content hashing, and TF-IDF text similarity
- Add `--content-method clip` for CLIP ViT-B/32 semantic content comparison via ONNX Runtime
- Add `--content-method tfidf` for TF-IDF cosine similarity in document mode
- Add sidecar file detection and co-deletion (`.xmp`, `.aae`, `.thm`, `.json`, `.lrdata`) with `--sidecar`/`--no-sidecar` flags
- Add `--keep edited` strategy that prefers the file with more sidecar edits
- Add `DirectoryComparator` for directory-aware scoring boost when files share a parent directory
- Add byte-identical fast path — files with matching size and first-4KB hash skip expensive PDQ computation
- Add `--no-pre-hash` flag to disable the pre-hash short-circuit
- Add `--format markdown` output format
- Add Chart.js analytics dashboard to `--format html` reports with score distribution, directory heatmap, filetype breakdown, and creation timeline
- Add `analytics` module with per-directory stats, score distribution, and creation timeline computation
- Add `photos_trash` action type in undo script generation
- **GUI**: Add Photos Library scanning via PhotoKit — scan your Photos Library directly without exporting
- **GUI**: Add native scoring engine (`PhotosScorer`) with 5 comparators matching CLI parity (filename, duration, file size, resolution, EXIF)
- **GUI**: Add `PhotosCacheDB` SQLite cache for Photos metadata, scored pairs, and thumbnails
- **GUI**: Add App Intents / Shortcuts integration — Scan Directory, Get Duplicate Count, Get Last Scan Results, Open Scan Results
- **GUI**: Add document mode support in configuration, comparison, and metadata views
- **GUI**: Add InsightsTab with directory heatmap, trend chart, and score distribution
- **GUI**: Add WCAG 2.1 AA accessibility — high-contrast adaptive colors, keyboard navigation, VoiceOver hints and labels, Dynamic Type scaling, focus rings
- **GUI**: Add unified state management via `SessionStore`/`SessionReducer` architecture replacing scattered `@Observable` state
- **GUI**: Add `SessionRegistry` for persistent session storage with legacy history migration
- **GUI**: Add `FileStatusMonitor` for real-time tracking of file deletions and renames
- **GUI**: Add `ObservableDefaults` for direct SwiftUI bindings to `UserDefaults` without `@State` mirrors
- **GUI**: Add `DDStatCapsule` shared component and `DDPillSize` enum for consistent pill sizing
- **GUI**: Add `FileBadges` and `SheetHeader` extracted components reducing view duplication
- **GUI**: Add `FileAction` enum replacing stringly-typed action matching
- **GUI**: Add XCUITest infrastructure with E2E replay tests, scan/review/error flow tests, and screenshot snapshots

### Changed
- **BREAKING**: Migrate content hashing from imagehash to pdqhash with sparse keyframe extraction — faster and more accurate perceptual hashing
- Replace image scoring resolution-tier bucketing with 30-minute date-window bucketing for better duplicate grouping
- Refactor `Mode` from raw strings to `StrEnum` for type safety
- Vectorize sliding-window hash comparison with numpy for faster audio/content scoring
- Cache `normalize_filename()` results to avoid redundant per-pair calls
- **GUI**: Settings tabs use `ObservableDefaults` instead of `@State` mirrors for preferences
- **GUI**: Split Xcode schemes — `DuplicatesDetector` for unit tests, `DuplicatesDetector-UITests` for UI tests

### Removed
- **BREAKING**: Remove `watch` subcommand and `[watch]` pip extra (watchdog dependency) from CLI
- **BREAKING**: Remove legacy content hashing parameters (`--hash-algo`, `--hash-size`, `--content-strategy`, `--content-interval`, `--scene-threshold`) — replaced by pdqhash
- **GUI**: Remove watch mode UI — WatchScreen, WatchSetupView, WatchFeedModel, NotificationManager, MenuBarManager

### Fixed
- Fix CLI crash when encountering GUI session files in the sessions directory
- Fix date proximity gate missing from cross-bucket image scoring pass
- Fix filename gate missing from `PhotosScorer`, preventing false-positive explosion on large libraries
- Serialize SQLite writes in `cache_db` to prevent "database locked" errors
- **GUI**: Fix Photos Library scan cancellation hanging during scoring phase
- **GUI**: Fix Photos cache never producing hits due to key mismatch
- **GUI**: Fix EXIF comparator double-counting resolution in Photos scoring
- **GUI**: Fix scored-pair cache miss for Photos assets with nil `modificationDate`
- **GUI**: Fix iCloud availability checked during extraction instead of post-scoring
- **GUI**: Fix configuration card geometry instability when switching between Directories and Photos source tabs
- **GUI**: Fix Mode label wrapping and wipe image sizing in comparison views
- **GUI**: Fix auto-advance triggering on non-destructive inspector actions (Reveal, Copy Path)
- **GUI**: Fix Photos images not loading in comparison panel — now uses PhotoKit asset request
- **GUI**: Fix "Reveal in Finder" for Photos assets — uses AppleScript to spotlight specific photo
- **GUI**: Fix scoring throughput rate computed from all groups instead of current group only
- **GUI**: Fix progress screen always showing "Calculating..." for remaining time estimate
- **GUI**: ProgressScreen stat capsules now use Liquid Glass pills instead of flat colored backgrounds
- **GUI**: Preset chips use pill (capsule) shape instead of rounded rectangles for visual consistency
- **GUI**: Remove Custom chip from preset area — customization accessible via Summary card only
- **GUI**: Prevent preset chip text wrapping ("Standard" splitting across lines)
- **GUI**: Consolidate ad-hoc `.monospacedDigit()` calls into DDTypography tokens (`sliderReadout`, `displayStat`)
- **GUI**: Delete dead `GlassEffectContainer` code (zero production call sites)
- **GUI**: Enlarge ProgressScreen control buttons (Pause/Resume/Cancel) from caption to body size
- **GUI**: Paused state replaces floating text with inline info icon and hover popover
- **GUI**: Remove slider `step:` parameters that produce tick mark dots on macOS 26
- **GUI**: Add fade-in animation to Customize panel

## [2.0.0] - 2026-03-25
### Changed
- **GUI**: Progress screen: Add linear progress bar (`ProgressView(value:)`, tinted `DDColors.accent`, `maxWidth` 280pt) below percentage text in `PrimaryProgressDisplay`; `accessibilityHidden(true)`
- **GUI**: Progress screen: Navigation title dynamically reflects the active pipeline stage (e.g., "Extracting metadata…", "Scoring pairs…"), falls back to "Scanning…" when no stage is active, and shows "Cancelling…" when cancellation is in progress; `nonisolated static func navigationTitleText(isCancelling:activeStageDisplayName:)` for testability
- **GUI**: Progress screen: `PipelineConnector` fill color now animates smoothly with `.animation(reduceMotion ? nil : DDMotion.smooth, value: leftDone)` instead of switching instantly; gated by `@Environment(\.accessibilityReduceMotion)`
- **GUI**: Progress screen: `ScanContextHeader.directoryLabels(for:)` disambiguates directories that share the same name by prepending the parent directory (e.g., `"a/Videos"` vs `"b/Videos"`); used in both the rendered labels and `accessibilityText`
- **GUI**: Progress screen: `ScanCoordinator.minimumDisplayDuration` (0.8s) — `driveStream` delays the `phase = .results` transition with `Task.sleep` when the scan completes in under 0.8s, then checks `Task.isCancelled` before advancing; prevents the progress screen from flashing on fast scans; `nonisolated static func minimumDisplayDelay(start:now:minimumDuration:)` for testability
- **GUI**: Progress screen: Cancel is now cooperative — `cancelScan()` sets `isCancelling = true` and cancels the task without immediately changing the phase; `driveStream`'s `CancellationError` handler transitions to `.configuration` and clears the flag; `ProgressScreen` takes `isCancelling: Bool` and shows a `ProgressView` spinner with "Cancelling…" text in place of the cancel button while waiting for subprocess termination
- **GUI**: Progress screen: `ScanProgressModel.estimatedTimeRemaining` is now the single ETA source — primary path uses the stage-specific wall-clock rate (requires `stageElapsed > 1.0`), fallback uses the overall progress rate (requires `progress > 0.05` and `elapsedTime > 0.5`); `ProgressScreen.computeETA()` removed entirely
- **GUI**: Progress screen: `ActiveFileDetail.displayLabel(for:)` shows `parentDir/fileName` instead of just `fileName` for context; VoiceOver accessibility label retains bare `fileName`
- **GUI**: `InspectorPane` removed the segmented File A/File B picker — `PairInspectorPane` now shows both files stacked vertically with no `@Binding var side`; `GroupInspectorPane` takes a `hasKeepStrategy: Bool` parameter
- **GUI**: Score breakdown simplified — `ComparatorRow` displays `Name  87%  43.5 pts` format; `×`, weight column, and `=` removed; `ComparatorRow` no longer takes a `weight` parameter
- **GUI**: Queue breakdown bar height increased to 8pt (`breakdownBarCompact` token)
- **GUI**: `CommandMenu("Review")` now enabled in both pair and group modes; `isReviewActive` focused value is no longer gated by `effectivePairMode`
- Removed redundant per-pair cache writes from `score_stage` — `find_duplicates` handles bulk caching via `put_scored_pairs_bulk()`
- `SessionEndEvent` now includes optional `timestamp` field
- **GUI**: Resume card shows directories, mode, and relative timestamp
- Parallel score progress now polls shared `multiprocessing.Value` counters at 100ms intervals via `concurrent.futures.wait(timeout=0.1)` instead of blocking on `as_completed` — progress callbacks fire between future completions in `_score_buckets_parallel`, `_filename_pass_parallel`, and `_content_pass_parallel`
- Paused sessions now persist a full resolved config snapshot (all non-ephemeral `DEFAULTS` keys) instead of only mode/content/audio/threshold/weights; resume restores all config fields and rejects ALL config-altering overrides, not just 5 hardcoded fields
- `_run_auto_pipeline` now runs video and image sub-pipelines concurrently via `asyncio.gather()` in a single event loop (was two sequential `asyncio.run()` calls); live unified progress via `AggregatingProgressEmitter`
- `run_pipeline()` now returns `PipelineResult` dataclass with real per-stage counts and timings instead of a bare `list[ScoredPair]`; CLI summary and JSON envelope use real stats
- `score` `stage_end` now reports actual comparisons evaluated (`total`) distinct from pairs found (`pairs_found`)
- Non-replay `session_start` now emitted after outer file discovery with actual file count in `total_files` (replay still uses 0)

### Fixed
- **GUI**: Progress screen cache-efficiency row now derives overall hit/miss totals from the four stage-family counters, so later stages no longer overwrite earlier cache wins and the headline hit-rate/mini bar reflect scan-wide efficiency
- Eliminate redundant normal-scan discovery walks by seeding the pipeline from the single pause-aware CLI discovery pass
- **GUI**: Progress screen cancel bar replaced with compact `.ddGlassPill()` button overlaid bottom-trailing (was full-width `.ddGlassChrome()` bar)
- **GUI**: Progress screen directory overflow now shows 3 directories before collapsing with "+N more" (was 2) for 4+ directories
- **GUI**: Progress screen active pipeline stages show "Starting..." placeholder instead of empty detail area when `current == 0` and `total` is nil
- **GUI**: `formatElapsed` boundary changed from `< 1` to `< 0.9995` to prevent "1000ms" output at the 1-second boundary
- **GUI**: `StageStatCounters.completedStats` now includes `.extract` stage, displaying "N metadata extracted" stat capsule after extract completes
- **GUI**: Error screen now shows a category-specific SF Symbol icon, human-readable title, and a `.ddGlassCard()` recovery suggestion block instead of a generic `ContentUnavailableView` with raw CLI error text; raw details are available via a `DisclosureGroup("Details")`; two action buttons provided: "Back to Configuration" and "Try Again"
- **GUI**: Active pipeline node pulse animation now works — replaced the no-op `.symbolEffect(.pulse)` (ineffective on non-symbol `Circle` views) with `.scaleEffect` + `withAnimation(.repeatForever)`, gated by `reduceMotion`
- **GUI**: Progress metric labels (elapsed, throughput, ETA) in `ProgressScreen` no longer cause layout shifts as they appear or disappear — rendered at all times using `.opacity()` show/hide instead of conditional `if` insertion
- **GUI**: `ScanProgressModel.overallProgress` is now monotonically non-decreasing — a `_progressHighWater` clamp prevents the percentage from going backwards when stage totals become known; unknown-total active stages contribute `0.0` instead of `0.5`
- **GUI**: Pin `ComparisonActionBar` outside the `ScrollView` in `ComparisonPanel` so action buttons remain visible while scrolling through metadata and score details
- **GUI**: Remove redundant score label alongside `ScoreRing` — score now appears exactly once, inside the ring
- **GUI**: Show both file paths in the `ComparisonPanel` scoreHeader using `DDTypography.metadata`; `fileLabels(a:b:)` helper substitutes the parent directory when both filenames are identical, preventing ambiguous same-name display
- **GUI**: Reorder `ComparisonPanel` scroll content to: scoreHeader → media → `MetadataDiffTable` → `ScoreBreakdownDetail`; remove `DisclosureGroup` wrapper around the media area
- **GUI**: `ImageComparisonView` and `VideoComparisonView` now accept `labelA`/`labelB` properties so actual filenames replace hardcoded "File A" / "File B" labels
- **GUI**: `VideoComparisonView` now shows a `ProgressView` during AVPlayer item setup (`isSettingUpA`/`isSettingUpB`) and a `ContentUnavailableView` on load failure, matching `ImageComparisonView`'s loading-state pattern
- **GUI**: `VideoComparisonView.resetTransportState()` now resets `muteA`/`muteB` to `false` so mute state does not carry over to the next pair
- **GUI**: Add `.labelsHidden()` to the video speed picker to prevent "Speed" from rendering vertically beside the control
- **GUI**: All destructive actions (trash, permanent delete, move) now show a confirmation dialog before executing — trash: "Move \"filename\" to Trash?" / "You can undo this from Finder.", permanent delete: "Permanently Delete \"filename\"?" / "This action cannot be undone.", move: "Move \"filename\"?" / "The original will be removed."; `ResultsScreen.confirmationCopy(for:)` centralizes copy for all three action types; non-destructive actions (reveal, copy path, ignore) execute immediately; `ResultsSingleDeleteConfirmationState` carries the target filename and full path; updated in `routeInspectorAction`, `dispatchAction`, and `dispatchGroupMemberAction`
- **GUI**: `ScanCoordinator.configureResults()` overrides CLI's default `.delete` action to `.trash` — permanent delete requires explicit user selection in the GUI
- **GUI**: Fix `GroupActionBar` using non-existent SF Symbol `"xmark.bin"` — replaced with `"trash.slash"`
- **GUI**: Add missing `bookmarks.app-scope` and `automation.apple-events` entitlements to `DuplicatesDetector.entitlements` — required for scan history replay directory access and Finder reveal respectively
- **GUI**: Fix WatchScreen pulse animation never firing — replace broken `.animation(value:)` (value already `true` on entry) with `phaseAnimator` that cycles opacity and scale
- **GUI**: Fix `BreakdownBar` VoiceOver reading "Score breakdown:" with no content when all values are nil/zero — now reads "No score breakdown"
- **GUI**: Fix `GroupQueueRow` VoiceOver reading "1 files" — now correctly uses singular "file" when count is 1
- **GUI**: Disable Review menu items (Keep A/B, Skip, Previous, Ignore, Return to Queue) when not on the results screen — previously always enabled, clicking had no effect outside results
- **GUI**: Fix `StatCapsule` accessibility label using inline string instead of the static `accessibilityText(value:label:)` method — prevents future divergence between runtime and test paths
- **GUI**: Remove `gui-release.yml` from `gui-ci.yml` trigger paths — release workflow YAML changes don't affect build or test results
- **GUI**: Exclude ignored pairs from bulk action candidates — after clicking Ignore Pair, the file is no longer included in "Trash All"/"Delete All"/"Move All" operations
- **GUI**: Carry configured move destination from setup screen into results — `--move-to-dir` chosen on the configuration screen is now forwarded to `ScanResultsModel`, preventing "No move destination set" errors on first action
- **GUI**: Persist ignored pairs to the scan's configured `--ignore-file` path instead of always writing to the default XDG location
- **GUI**: Resolve symlinks in ignore-list paths using `resolvingSymlinksInPath()` to match the CLI's `Path.resolve()` behavior
- **GUI**: Remove unsupported link actions (hardlink, symlink, reflink) from the Action picker — previously selectable but caused CLI validation errors or non-functional review desk states
- **GUI**: Expand `~` in move-to and ignore-file paths at config build time so the CLI subprocess and review desk use the same resolved path
- **GUI**: Reset delete confirmation state when selected pair or group member changes — prevents armed confirmation from carrying over to a different file
- **GUI**: Validate Move To action requires a destination directory before allowing scan start
- **GUI**: Validate keep strategy compatibility with scan mode — reject `longest` in image/auto mode and `highest-res` in audio mode
- **GUI**: Stop sending `--action` and `--move-to-dir` to the CLI subprocess — the GUI handles all file operations locally via `FileManager`, avoiding `send2trash` dependency gate and move-to-dir validation in the CLI
- **GUI**: Image wipe mode pan gesture removed — only the magnify gesture remains, eliminating contention with the wipe handle drag
- **GUI**: `.reviewFocusQueue` notification handler now respects the `hasActiveModal` guard, matching all other review notification handlers
- **GUI**: `CommandMenu("Review")` now enabled in group mode — previously menu items had no effect outside pair review
- **GUI**: Both-reference pair auto-skip delay corrected to 1500ms (was documented as 500ms)
- `--resume` now validates mutual exclusivity with directory args and config flags
- Session pruning (30-day / max-5) now runs at scan start
- Cancel/interrupt now deletes session file
- `put_scored_pairs_bulk` now tracks `score_misses`
- **GUI**: `discardSession()` now deletes only the targeted session, not all sessions
- **GUI**: "Calculating..." ETA label now shows for at least 3 seconds per stage

### Added
- **GUI**: `ErrorInfo.Category` enum with cases `binaryNotFound`, `dependencyMissing`, `permissionDenied`, `directoryNotFound`, `noFilesFound`, `invalidConfiguration`, `cliCrash(code:)`, and `unknown`; `ErrorInfo` gains `category` and `recoverySuggestion` properties; `nonisolated static func classify(_ error:)` classifies `CLIBridgeError` cases; `nonisolated static func classifyStderr(_:code:)` pattern-matches known CLI stderr strings — both `driveStream` and `driveWatchStream` catch blocks now use `ErrorInfo.classify(error)`
- **GUI**: `ScanCoordinator.retryScan()` re-runs the most recent failed scan from error state using `lastScanConfig` and `lastOriginalEnvelope`, preserving replay refinement chain; "Try Again" button on error screen now retries instead of resetting to configuration
- **GUI**: VoiceOver accessibility labels for `ProgressScreen` — `StageStatCounters.statCapsule` (`accessibilityElement(children: .ignore)` + label), `ScanContextHeader` (`accessibilityElement(children: .combine)` + label via `nonisolated static accessibilityText(mode:entries:contentEnabled:contentMethod:audioEnabled:)`), `PrimaryProgressDisplay` (`accessibilityElement(children: .ignore)` + label via `nonisolated static accessibilityText(progress:elapsed:throughput:eta:)`), and `ActiveFileDetail` (`accessibilityLabel("Processing \(file.fileName)")`)
- **GUI**: Previous button in `ComparisonActionBar` (`onPrevious` callback, `isAtFirstPair` property) — layout is now: pair counter | Keep A | Keep B | divider | Previous | Skip | Ignore
- **GUI**: Previous Group button in `GroupActionBar` (`onPrevious` optional callback) — disabled at first group
- **GUI**: Review progress bar below the pinned action bar in pair mode showing current position within the queue
- **GUI**: Audio tag fields (Title, Artist, Album) in `MetadataDiffTable` for audio-mode file pairs
- **GUI**: "Candidate for removal" label in `GroupInspectorPane` when a file is not the kept member (requires `hasKeepStrategy: Bool` parameter)
- **GUI**: Confirmation dialog before "Execute for Real" in `DryRunBanner` — user must confirm before `startScanWithConfig()` is called
- **GUI**: Limit field validation in `RefineResultsSheet` — non-numeric input shows a red border and disables the Refine button
- **GUI**: Dynamic `CommandMenu("Review")` labels in group mode — menu items update via `@FocusedValue(\.isGroupMode)` (e.g., "Previous Member", "Next Member"); key defined in `NotificationManager.swift`
- **GUI**: Liquid Glass design applied across all major surfaces — `.ddGlassCard()` on sidebar (ContentView), ScanContextHeader (ProgressScreen), queueToolbar (QueuePane), ComparisonActionBar, GroupReviewView pairRelationships, ResultsScreen bulkProgressOverlay, DependencyCheckView capabilityCards + toolDetails, InstallProgressView stepList + logArea, and DryRunBanner background; `.ddGlassPill()` on WatchScreen duplicateRow and feed triggerBadge; `.ddGlassChrome()` on ContentView sidebar chrome and QueuePane toolbar; `.presentationBackground(.ultraThinMaterial)` on all modal sheets (UndoScript, ActionLog, IgnoreList, RefineResults, DuplicateDetail, History, SaveProfile, EditProfile)
- **GUI**: VoiceOver accessibility — `accessibilityElement` + `accessibilityLabel` (and `accessibilityValue` where applicable) added to ScoreRing, BreakdownBar, PairQueueRow, GroupQueueRow, StatCapsule, WatchScreen statCard, PipelineNode, capabilityCard, ComparisonPanel scoreHeader, and ComparisonActionBar pairCounter; `ScanHistoryView` rows converted from `.onTapGesture` to `Button` for full VoiceOver activation
- **GUI**: `CommandMenu("Review")` in menu bar — exposes Keep A, Keep B, Skip, Previous, and Ignore keyboard shortcuts as discoverable menu items (defined in `DuplicatesDetectorApp.swift`)
- **GUI**: Reduced Motion support — `@Environment(\.accessibilityReduceMotion)` gates all looping and pulsing animations in WatchScreen, ProgressScreen PipelineNode, InstallProgressView header, ScanFlowView phase transitions, and DependencyCheckView install overlay
- **GUI**: `AVPlayerPool` (`Sources/Views/Components/`) — `@MainActor` singleton capping active `AVPlayer` instances at 2; `acquire(for:)` reuses a pooled player via `replaceCurrentItem`, `release(_:)` pauses and clears before returning to pool; eliminates repeated allocation/deallocation during rapid pair navigation in `VideoComparisonView`
- **GUI**: `ThumbnailProvider.prefetch(pairs:startingAt:)` API for pre-loading upcoming pair thumbnails; memory cache fast path uses a time-agnostic key to avoid `mtime` syscall on cache hits; both quick and full cache keys stored per entry
- **GUI**: Image comparison downsampling — `CGImageSource` caps loaded images at 4096px max dimension in `ImageComparisonView`, preventing multi-megapixel originals from filling memory
- **GUI**: `DDTypography.statValue` token added for numeric stat labels; `DDTypography.headerIcon` token added for large decorative icon glyphs — replaces hardcoded `.system(size: 48)` in WatchScreen empty state and all similar sites
- **GUI**: Self-hosted GitHub Actions CI pipeline (`gui-ci.yml`) — builds and tests the Xcode project on push and pull requests that touch `DuplicatesDetectorGUI/**`; runs on the `macos-local-runner` self-hosted runner (192.168.0.9, labels: self-hosted/macOS/ARM64/macos-local)
- **GUI**: Automated release pipeline (`gui-release.yml`) — triggered on `gui/v*` tags; archives the app, signs and notarizes with Developer ID, packages a DMG via `scripts/create-dmg.sh`, and publishes a GitHub release with the DMG as a release asset
- **GUI**: `scripts/create-dmg.sh` — DMG packaging script using `hdiutil`; adds background image and symlink to `/Applications`
- **GUI**: `scripts/export-options.plist` — Xcode export options for developer-id distribution (used by the release workflow)
- **GUI**: Hardened Runtime enabled (`ENABLE_HARDENED_RUNTIME=YES` in `project.yml`); `DuplicatesDetector.entitlements` populated with `user-selected.read-write`, `bookmarks.app-scope`, and `automation.apple-events` entitlements required for notarization
- **GUI**: `App-Info.plist` updated with `CFBundleShortVersionString`, `CFBundleVersion`, `NSHumanReadableCopyright`, and `CFBundleDocumentTypes` for proper macOS App Store / notarization metadata
- **GUI**: Preferences window (Cmd+,) with four tabs — General (CLI paths, default mode/keep/action, profiles, CLI config sync), Scanning (threshold, content hashing, audio, output settings), Cache (location, sizes, clear buttons, toggles), and Advanced (extensions, exclude patterns, log, ignore list, debug, reset); implemented as a native SwiftUI `Settings` scene using standard macOS Forms
- **GUI**: CLI profile management — create, load, rename, and delete named scan profiles with full TOML read/write interop via `ProfileManager` actor; profile name validation matches CLI's `_PROFILE_NAME_RE`; XDG path resolution mirrors `config.py` exactly
- **GUI**: Persistent scan defaults via `AppDefaults` — `public enum` backed by `UserDefaults.standard` with `dd.defaults.*` key prefix; `ScanSetupModel.init()` applies stored defaults before resetting weights; lazy `ensureRegistered()` ensures factory defaults are available before first read
- **GUI**: Cache size display and clear functionality in Preferences — `CacheManager` stateless `enum` resolves XDG cache paths matching CLI's `cache.py`; reports sizes for `metadata.json`, `content-hashes.json`, and `audio-fingerprints.json`; individual and bulk clear operations
- **GUI**: CLI configuration import/export — General tab can read from and write to the CLI's `config.toml` via `ProfileManager`
- **GUI**: Profile picker in scan configuration screen — bottom bar "Profile" menu (between History and validation summary) loads profiles from `ProfileManager.shared.listProfiles()`; "Save as Profile..." sheet with name validation; selected profile applies via `ScanSetupModel.applyProfile()`
- **GUI**: Ignore list count badge — `.badge(model.ignoredPairs.count)` on the "Ignored Pairs" toolbar button in `ResultsScreen`
- **GUI**: TOMLKit dependency added to `project.yml` packages and `DuplicatesDetectorKit` target for native TOML read/write in profile and config management
- **GUI**: Replay from file — "Open Scan..." button in the `ConfigurationScreen` bottom bar opens a `fileImporter` for `.json` files and calls `ScanCoordinator.startReplay(url:)` to re-enter the pipeline from a saved JSON envelope
- **GUI**: Replay from history — completed non-replay scans with at least one result are auto-saved to `~/Library/Application Support/DuplicatesDetector/scans/` (fire-and-forget `Task.detached`) via `ScanHistoryManager`; `ScanHistoryView` sheet (opened via "History" bottom-bar button in `ConfigurationScreen`) lists past scans with tap-to-replay and swipe-to-delete; pruned to 50 entries on sheet appear
- **GUI**: Refine Results — "Refine Results" toolbar button in `ResultsScreen` opens `RefineResultsSheet`, which writes `rawEnvelopeData` to a temp file and re-runs the CLI with `--replay` via `ScanCoordinator.startScanWithConfig()` so the user can adjust output settings without re-scanning
- **GUI**: App-level file open handler — `DuplicatesDetectorApp.onOpenURL` intercepts `.json` files opened from Finder, stores the URL in `AppState.pendingReplayURL`, and `ScanFlowView` observes the change to call `coordinator.startReplay(url:)` when in `.configuration` phase
- **GUI**: Ignore list management view — `IgnoreListView` sheet (opened via "Ignored Pairs" toolbar button in `ResultsScreen`) displays all pairs from the CLI ignore list with path-substring search, swipe-to-delete (`IgnoreListManager.removePair`), and a "Clear All" button with confirmation dialog
- **GUI**: Full export panel — expanded Export menu in `ResultsScreen` toolbar exposes four formats: "Save as JSON" (raw `rawEnvelopeData` bytes write), "Export as CSV" (existing path), "Export as HTML Report" (CLI replay via `CLIBridge.exportAsFormat` with `--format html`), and "Export as Shell Script" (CLI replay with `--format shell`); HTML and shell buttons are disabled when `rawEnvelopeData` is nil
- **GUI**: Scan history persistence — `ScanHistoryManager` actor stores each scan as a `<timestamp>-<mode>.json` envelope and a `<timestamp>-<mode>.meta.json` sidecar; `ScanHistoryEntry` (`Identifiable, Sendable, Codable`) is the persisted sidecar model; `HistoryMetadata` (`Sendable`) is the ephemeral cross-actor transfer type extracted from `ScanEnvelope` before crossing into the `ScanHistoryManager` actor
- **GUI**: Raw envelope data preservation — `CLIOutput.result(ScanEnvelope, Data)` now carries raw stdout bytes; `ScanCoordinator` stores them in `ScanResultsModel.rawEnvelopeData: Data?` for lossless export (`writeEnvelopeToTempFile()`) and replay; `CLIBridge.exportAsFormat(envelopePath:format:outputPath:keep:embedThumbnails:)` performs export via `duplicates-detector scan --no-config --replay <path> --format <fmt>`
- **GUI**: Watch mode — unified scan/watch architecture: `ScanCoordinator` gains a `.watching` phase, `startWatch()`/`stopWatch()`/`driveWatchStream()` methods, and direct ownership of `WatchFeedModel` and `MenuBarManager`; `ScanSetupModel` gains watch-specific properties (`debounce`, `heartbeatInterval`, `notificationPreference`, `notificationThreshold`, `webhookURL`), `buildWatchConfig()`, `watchValidationErrors`, and `isValidForWatch`; `ConfigurationScreen` gains a "Watch Options" disclosure group and a "Start Watching" button alongside "Start Scan"; `ScanFlowView` handles the `.watching` phase by showing `WatchScreen`
- **GUI**: Desktop notifications for watch mode duplicate detection via native `UNUserNotificationCenter` (`NotificationManager` actor); notification deep-link via Foundation `NotificationCenter` posting
- **GUI**: Menu bar status item during active watch sessions — shows directory count, duplicate count, and stop/show actions; created on watch start, destroyed on watch stop (`MenuBarManager` using `NSStatusBar.system.statusItem()`)
- **GUI**: Watch configuration: debounce interval, heartbeat interval, notification preferences, and webhook URL; `FlagAssembler.assembleWatchFlags` emits `--webhook <url>` when `WatchConfig.webhookURL` is set
- **GUI**: GUI-side action logging compatible with CLI JSON-lines schema — `ActionLogWriter` actor writes trash/delete/move records matching `actionlog.py` format; `ActionContext` carries score, keep strategy, and kept-file path for each entry; all per-file and bulk action methods log on success
- **GUI**: Undo script generation — "Generate Undo Script" toolbar button in `ResultsScreen` invokes `duplicates-detector --generate-undo` via `CLIBridge.generateUndoScript(logPath:)` and presents the shell script in a sheet with Copy and Save buttons
- **GUI**: Action log viewer sheet — `ActionLogView` displays log records in reverse-chronological order with action-type icons, expandable detail rows, and Clear/Refresh buttons; accessible from the results toolbar Log menu
- **GUI**: Dry-run mode toggle — `ScanConfig.dryRun` wired through `FlagAssembler` (`--dry-run`), `ScanSetupModel`, and `ConfigurationScreen`; `DryRunBanner` gains an "Execute for Real" button that calls `ScanCoordinator.startScanWithConfig()` to re-run without `--dry-run`
- **GUI**: Both-reference pair auto-skip — `ComparisonActionBar` shows an explanatory banner and hides Keep A / Keep B buttons when both files are reference files; `ResultsScreen` auto-advances to the next pair after 1500ms
- **GUI**: Async bulk action execution — `ScanResultsModel.executeBulkActionAsync()` runs bulk file operations off the main actor with `bulkProgress: Double` tracking and `bulkCancelled` cooperative cancellation; progress overlay displayed in `ResultsScreen` while operation is in flight
- **GUI**: Wipe-slider File A/B labels — `ImageComparisonView` renders "File A" / "File B" pill labels in wipe-slider mode positioned to avoid the divider handle; shared `labelPill()` helper extracted for reuse
- **GUI**: Side-by-side image comparison with synchronized zoom/pan and wipe-slider overlay mode (`ImageComparisonView`)
- **GUI**: Synchronized dual-video playback with frame stepping, speed control (0.25×–2×), and per-player mute (`VideoComparisonView`)
- **GUI**: Comparison action bar (Keep A / Keep B / Skip / Skip & Ignore) with auto-advance and pair counter (`ComparisonActionBar`)
- **GUI**: Keyboard shortcuts for comparison review: `←` Keep A, `→` Keep B, `↓` Skip, `↑` Previous pair, `Esc` return focus to queue, `i` Ignore — gated by `focusedPane == .comparison`
- **GUI**: Pair navigation methods on `ScanResultsModel` — `advanceToNextPair()`, `advanceToPreviousPair()`, and `currentPairIndex` for sequential comparison workflow; `nextPairAfterAction` captured before action dispatch to avoid racing with `revalidateAfterAction`
- **GUI**: `PreviewFixtures.imageResultsModel()` factory for previewing image-mode comparison states
- **GUI**: View mode toggle — `ScanResultsModel.ViewMode` (.pairs/.groups) lets users switch between pair and group views; `canToggleViewMode` enabled when envelope has >=2 pairs; client-side union-find via `synthesizeGroups(from:)` (path compression + rank) with result cached on first toggle; `effectivePairMode` replaces direct `isPairMode` in views
- **GUI**: Selection mode for batch actions — `ScanResultsModel.isSelectMode`, `selectedForAction: Set<PairIdentifier>`, `selectedGroupsForAction: Set<Int>`; when active, `bulkActionCandidates()` filters to selected subset; toolbar toggle clears selection on deactivate
- **GUI**: Thumbnail system — `ThumbnailProvider` actor (`Sources/Bridge/`) with resolution chain: memory cache → disk cache (mtime-validated) → embedded base64 → QuickLook → workspace icon; `NSCache` (500 count / 100MB) + disk cache at `~/Library/Caches/DuplicatesDetector/thumbnails/` (SHA256-keyed PNGs, LRU eviction at 500MB); `ThumbnailView` (`Sources/Views/Components/`) extracted from `ComparisonPanel` with progressive async loading (system icon → real thumbnail crossfade via `.task(id:)`) and sync base64 path; backward-compatible with all existing call sites
- **GUI**: Replay coordinator path — `ScanCoordinator.startReplay(url:)` drives CLI with `--replay <path>` via `FlagAssembler`; `ScanConfig.replayPath: String?` triggers replay-only flag assembly (output shaping flags only; no filters, weights, content, audio, or directories emitted); shares `driveStream(config:progress:)` with the normal scan path
- **GUI**: Throughput indicator moved to `ScanProgressModel.currentThroughput: Double?` — previously computed in `ProgressScreen` as view-local state; now part of the view model for testability and reuse across views
- **GUI**: Full action support (issue #10 increment B) — `ResultsScreen` toolbar button and `InspectorPane` per-file buttons now adapt to the scan's `--action` flag: trash (macOS Trash via `FileManager.default.trashItem()`), permanent delete (inline 3-second two-click confirmation guard), and move-to (destination chosen via `fileImporter`, persisted via `@AppStorage`); hardlink/symlink/reflink are shown but disabled with a tooltip (CLI-side only)
- **GUI**: Ignore pair action — `InspectorPane`'s previously-stub Ignore Pair button is now functional; `ignorePairAndUpdateState()` writes the pair to the CLI ignore list via `IgnoreListManager` and excludes it from `filteredPairs` for the session; `ScanResultsModel.ignoredPairs: Set<PairIdentifier>` tracks session-level decisions
- **GUI**: Keep Strategy and Action pickers in Configuration screen — `ConfigurationScreen` Output disclosure group now exposes a Keep Strategy picker, an Action picker, and a Move To directory picker (conditional on action = moveTo); previously deferred as DEFERRED comments
- **GUI**: `IgnoreListManager` in `Sources/Bridge/` — reads and writes the CLI's persistent ignore list at `$XDG_DATA_HOME/duplicates-detector/ignored-pairs.json`; format matches `ignorelist.py` exactly (flat JSON array of sorted 2-element path arrays); atomic writes via temp file + `os.replace()`-equivalent
- **GUI**: `PreviewFixtures` helpers `resultsModelWithDelete()` and `resultsModelWithMoveTo()` for previewing permanent-delete and move-to action states
- **GUI**: Bulk trash for scan results — "Trash Duplicates" toolbar button in `ResultsScreen` sends all non-keep, non-reference duplicates to the macOS Trash via `FileManager.default.trashItem()` after a confirmation dialog showing file count and total reclaim size; trashed files are excluded from filtered results in the same session
- **GUI**: Per-file trash from `InspectorPane` — previously disabled "Move to Trash" buttons are now active for both pair and group inspector modes, calling `trashFileAndUpdateState()` on `ScanResultsModel`
- **GUI**: Add `#Preview` macros (guarded by `#if DEBUG`, backed by `PreviewFixtures` helpers) to `ScanFlowView`, `ContentView`, `ScoreRing`, `BreakdownBar`, `GlassEffectContainer`, `DirectoryPickerSection`, and `WeightsEditorView`
- **GUI**: Add `DDSpacing.sliderThumb` (16pt) and `DDSpacing.iconFrame` (20pt) tokens used by `WeightsEditorView`'s `ColoredSlider` thumb and `DirectoryPickerSection`'s folder icons respectively; add `DDSpacing.xxs` (2pt) for tight intra-row spacing
- **GUI**: Add `"filesize"` CLI key aliases to `DDComparators.names` and `DDColors.comparatorColors` so both the JSON-decoded camelCase key (`"fileSize"`) and the raw CLI weight key (`"filesize"`) resolve to the correct display name and teal color
- Complete design token system for GUI (`DesignTokens.swift`): surface hierarchy (`DDColors.surface0`–`surface3`, Graphite Forge palette), score-semantic colors (`scoreCritical`/`scoreHigh`/`scoreMedium`/`scoreLow`) with `scoreColor(for:)` helper, emphasis colors (accent/destructive/warning/success/info), state colors (selection/hover/focusRing), typography roles (`DDTypography`: displayStat/heading/body/metadata/monospaced/label), animation presets (`DDMotion`: snappy/smooth/spring with named duration constants), density variants (`DDDensity`: compact/regular `EdgeInsets`), corner radius tokens (`DDRadius`: small/medium/large/panel), and glass `ViewModifier`s (`DDGlass`: Chrome/Card/Pill/Interactive) with `View` extension helpers (`ddGlassChrome()`, `ddGlassCard()`, `ddGlassPill()`, `ddGlassInteractive()`)
- `DESIGN_SPEC.md` — written design reference covering palette rationale, surface hierarchy rules, typography guide, score color semantics, glass placement rules, motion guidelines, density guide, corner radius rules, and anti-patterns
- Add SwiftUI scan configuration UI — `ScanConfigurationView` with directory picker (`DirectoryPickerSection`) supporting add/remove/reference toggles via `fileImporter`, mode selector, content/audio toggles, weight editor (`WeightsEditorView`) with per-key text fields and live sum validation indicator, keep/action settings, filters, output options, and advanced options; all wired to `ScanSetupModel` (`@Observable`) with full client-side validation matching CLI rules
- Add `WeightDefaults` to `Bridge/` — 8 default weight tables matching CLI defaults for all mode/flag combinations (video, image, audio, video+content, video+audio, video+content+audio, image+content, audio+content), mode transition logic (required/forbidden key rules), and weight reset on mode change
- Add `ScanSetupModel` to `ViewModels/` — `@Observable` view model managing directory list, mode, weight map, content/audio/keep/action flags, and all filter fields; emits `ScanConfig` via `buildConfig()`; validates weight sum, required/forbidden keys per mode, and inter-flag constraints (e.g., audio forbidden in image mode); 2 new test files covering weight table sums, mode rules, validation, mode changes, weight resets, and directory management
- Add native macOS SwiftUI companion app scaffold (`DuplicatesDetectorGUI/`) — SPM package (macOS 26+, Swift 6.2, strict concurrency), `CLIBridge` actor for subprocess management via `swift-subprocess`, complete Codable models for JSON envelope/progress/watch event parsing, `ScanConfig`/`FlagAssembler` for CLI flag assembly, dependency check view, and 42 unit tests
- Add `--machine-progress` flag to emit JSON-lines progress events to stderr for GUI frontend integration — structured `stage_start`, `progress`, and `stage_end` events with 100ms per-stage throttling; suppresses Rich progress bars when active; available on both `scan` and `watch` subcommands (silently ignored in watch mode); `machine_progress` persisted via `--save-config`
- Add `watch` subcommand for real-time daemon mode — monitors a directory with watchdog, debounces FS events (default 2s window), scores each new file incrementally against the known-file set via `score_file_against_set()` (O(n) per event), and emits duplicate pairs as JSON-lines to stdout; observe-only (no deletion); requires `pip install "duplicates-detector[watch]"`
- Add `scan` subcommand as the explicit name for the existing scan pipeline — backward-compatible: bare invocations without a subcommand continue to work
- Add `score_file_against_set()` to `scorer.py` for O(n) incremental scoring of a single file against an existing metadata set (used by watch mode)
- Add `watcher.py` module with `EventEmitter`, `WatchState`, `DebouncedHandler`, and `run_watch()` — watchdog is lazy-imported so scan mode incurs zero overhead when `[watch]` is not installed
- Add `watch = ["watchdog>=4.0,<6"]` optional dependency group
- Add `--mode audio` for audio file deduplication (MP3, FLAC, AAC, WAV, OGG, etc.) using metadata tags — scores pairs on filename, duration, and tag similarity (title, artist, album) via new `TagComparator`; uses mutagen for format-agnostic tag extraction; compatible with `--audio` for Chromaprint fingerprinting; requires `pip install "duplicates-detector[audio]"`
- Add `--action reflink` for copy-on-write deduplication on APFS/Btrfs/XFS — zero additional disk usage, both paths remain independently accessible; uses `cp -c` (macOS) / `cp --reflink=always` (Linux) to guarantee CoW-or-fail semantics; `"reflinked"` undo handler generates `cp`+`mv` reversal (same as hardlink)
- Edge-case test coverage for malformed files, permission errors, ultra-short videos, non-ASCII paths, circular symlinks, race conditions, and blank frames
- Add `--generate-undo LOG_FILE` flag to generate a shell script that reverses deletions recorded in a `--log` action log (supports move, hardlink, symlink reversal; warns for trash and permanent deletes)
- Add `--embed-thumbnails` flag to embed base64 JPEG thumbnails in JSON envelope output, with configurable `--thumbnail-size WxH` (default 160×90 for video, 160×160 for image); extract shared thumbnail generation into new `thumbnails.py` module
- Add `--replay FILE` to re-enter the post-scoring pipeline from a previously saved JSON envelope (`--format json --json-envelope`) — re-applies `--keep`, `--min-score`, `--sort`, `--group`, `--limit`, `--format`, `-i`, `--dry-run`, `--reference`, `--json-envelope`, `--log`, and `--ignore-file` without re-scanning or re-extracting metadata; supports both pair-mode and group-mode envelopes; `--reference` re-tagging works in replay mode; replay output with `--json-envelope` can itself be replayed; bare JSON arrays (non-envelope output) are rejected with a descriptive error; conflicts with scan-specific flags (`--content`, `--audio`, `--weights`, `--exclude`, `--codec`, size/duration/resolution/bitrate filters, cache flags, and explicit directories)
- Add `mtime` field to per-file metadata in JSON output — enables `--sort mtime` to work after `--replay` without access to the filesystem
- Add `--format html` for self-contained HTML report output — sortable pair/group tables, base64-encoded file thumbnails (120×120 JPEG), color-coded score badges, summary dashboard, collapsible group sections via `<details>/<summary>`, and dry-run summary; fully inline CSS/JS with no external dependencies; works with all modes (video/image/auto), `--group`, `--keep`, `--dry-run`, and `--output`
- Add `--audio` flag for Chromaprint-based audio fingerprinting — detects re-encoded video duplicates that share identical audio tracks regardless of filename or visual differences; requires `fpcalc` on PATH; video mode only; `--no-audio-cache` disables disk caching; audio default weights: filename=25, duration=25, resolution=10, filesize=10, audio=30; with content: filename=15, duration=15, resolution=10, filesize=10, audio=10, content=40
- Add `ExifComparator` for image mode — scores EXIF metadata similarity (capture timestamp, camera model, lens, GPS coordinates, EXIF dimensions) using 5 redistributable sub-fields; automatically included in `--mode image` and image sub-pipeline of `--mode auto`; image default weights: filename=25, resolution=20, filesize=15, exif=40; with content: filename=15, resolution=10, filesize=10, exif=25, content=40
- Extract 7 EXIF fields from images via PIL (DateTimeOriginal, Make+Model, LensModel, GPS lat/lon, ExifImageWidth/Height) — stored on `VideoMetadata`, cached in `MetadataCache` with backward-compatible defaults
- Add per-comparator score diagnostics in `-v` verbose mode — breakdown column now shows raw similarity, weight, and weighted contribution for each comparator (`name: raw × weight = weighted`), making it easier to understand scoring and tune `--weights`; JSON output always includes the `detail` field with `[raw_score, weight]` arrays per comparator
- Add `--content-strategy scene` for adaptive scene-based keyframe extraction using ffmpeg's `select='gt(scene,T)'` filter — extracts only visually distinct frames instead of fixed intervals, with automatic fallback to interval mode when scene detection yields too few frames
- Add `--scene-threshold` (0.0–1.0 exclusive, default 0.3) to tune scene detection sensitivity — lower values detect more transitions
- Add `--rotation-invariant` flag for rotation/flip-invariant image content hashing — computes perceptual hashes for all 8 D₄ orientations, catches rotated or flipped duplicates with 4–8× content hashing cost; image mode only, silently ignored without `--content`
- Add `--hash-algo phash|dhash|whash|ahash` flag to select perceptual hashing algorithm for `--content` mode — dhash is faster, whash is more robust against transforms, ahash is fastest; default phash preserves backward compatibility
- Add `--mode auto` for mixed media directories — scans videos and images together in a single run with independent sub-pipelines per type
- Add `--profile NAME` and `--save-profile NAME` flags for named scan profiles — reusable TOML configurations stored in `~/.config/duplicates-detector/profiles/`
- Add `--min-score N` flag to filter results by minimum similarity score (0–100) — post-scoring display filter, works with `--limit`, `--group`, all output formats, and config file
- Add prominent truncation warning to stderr when Rich table output exceeds `_MAX_TABLE_ROWS` (500), with `--limit` and `--min-score` refinement suggestions
- Add `_MAX_TABLE_ROWS` truncation to group tables (`print_group_table()`) for consistency with pair tables
- Show "showing X of Y" in summary panel when results are truncated by `--limit` or `_MAX_TABLE_ROWS`
- Add `--content-method phash|ssim` flag to choose content comparison approach — SSIM (Structural Similarity Index) compares frames at the pixel level for more robust detection of heavily compressed, watermarked, or color-graded duplicates; default `phash` preserves backward compatibility; `scikit-image` required for SSIM (`pip install "duplicates-detector[ssim]"`)
- **GUI**: Add `QueuePane` — left pane of the review desk; scrollable `List` of `PairQueueRow` / `GroupQueueRow` items with path search filter and sort picker; each row shows a thumbnail (`ThumbnailView`), a `ScoreRing`, filenames, `BreakdownBar`, and crown/pin badges for keep and reference indicators; `ContentUnavailableView` empty states for no results and no search matches
- **GUI**: Add `GroupReviewView` — center pane for group mode; horizontal filmstrip of `FilmstripTile` thumbnails (120×90) with keep/reference overlay badges and selection ring; `PairRelationshipRow` list below showing per-pair score rings and breakdown bars; group header summarizes file count, score range, average, and keep recommendation
- **GUI**: Add `InspectorPane` (`PairInspectorPane` + `GroupInspectorPane`) — right pane for file-level detail; segmented `InspectorSide` toggle (File A / File B) for pair mode; full metadata `Grid` (size, duration, resolution, codec, bitrate, FPS, audio channels, modified, audio tags); keep recommendation label; action buttons (Reveal in Finder, Quick Look, Copy Path active; Move to Trash and Ignore Pair disabled pending filesystem integration); `GroupInspectorPane` mirrors layout for a selected filmstrip member
- `--delete-session SESSION_ID` flag for per-session deletion
- SIGUSR1 signal handler to toggle pipeline pause (Unix only)
- Session save on pause with `paused_at` timestamp
- `--list-sessions-json` hidden flag for GUI bridge
- **GUI**: Per-cache hit rate breakdown in progress screen
- **GUI**: "Paused — session saved" descriptive label during pipeline pause
- **GUI**: Enhanced resume card with directories, mode, and relative timestamp
- `EPHEMERAL_CONFIG_KEYS` (11 keys) and `RESUME_OVERRIDE_KEYS` (6 presentation-only keys) in `session.py` for full-config session snapshots
- `build_session_config()` helper in `session.py` to create full resolved config snapshots excluding ephemeral keys
- `compute_stage_list()` in `pipeline.py` — single source of truth for authoritative stage lists used by `session_start.stages`; always emits all 6 canonical stages even in pass-through mode; SSIM and replay have distinct stage sets
- `PipelineResult` dataclass in `pipeline.py` — includes `files_scanned`, `files_after_filter`, `total_pairs_scored`, `pairs_found`, per-stage timings, `stage_timings`, `stage_counts`
- `_CANONICAL_STAGES` module constant in `pipeline.py` standardizing the 6 canonical stage names
- `AggregatingProgressEmitter` and `_SubEmitter` in `progress.py` — merges stage lifecycle and progress events from N concurrent sub-pipelines; thread-safe via `threading.Lock`
- `PipelineController.linked()` creates controllers sharing pause/cancel state but with independent stage tracking via `_SharedControl` inner class — used for concurrent auto-mode sub-pipelines
- `AggregatingProgressEmitter.unified_stage_state()` returns `(completed_stages, active_stage)` from the unified perspective for session persistence in auto mode

### Changed
- **GUI**: Unified scan and watch configuration into a single screen and coordinator — removed separate `WatchConfigurationScreen`, `WatchFlowView`, `WatchSetupModel`, `WatchCoordinator`, and `DirectoryManaging`/`WeightsEditable` protocols; `DirectoryPickerSection` and `WeightsEditorView` now use `ScanSetupModel` directly; watch is launched from `ConfigurationScreen`'s "Watch Options" disclosure group via a "Start Watching" bottom-bar button; sidebar no longer has a `.watch` destination
- **GUI**: `ScanResultsModel.trashedPaths` renamed to `actionedPaths` and `trashError` renamed to `actionError` (backward-compat aliases retained); `bulkTrashCandidates()` renamed to `bulkActionCandidates()` and `executeBulkTrash()` replaced by `executeBulkAction(destination:)` — unified to support trash, permanent delete, and move-to
- **GUI**: `GroupReviewView` filmstrip badge terminology updated from `isTrashed`/`trashedPaths` to `isActioned`/`actionedPaths`
- **GUI**: `PairAction.bulkTrash` renamed to `bulkAction`
- **GUI**: Replace hardcoded colors, spacing, and corner radii in `DirectoryPickerSection`, `WeightsEditorView`, and `GlassEffectContainer` with design tokens (`DDColors`, `DDSpacing`, `DDRadius`, `DDDensity`) — eliminates all raw magic values from these files
- **GUI**: `ScanFlowView` now animates between coordinator phases (configuration → progress → results → error) using `.transition(.push(from: .trailing))` driven by `DDMotion.smooth`; error phase uses `.transition(.opacity)`
- **GUI**: Implement Phase 4 "Review Desk" — `ResultsScreen` rewritten as a three-pane `HSplitView` orchestrator (queue, comparison surface, inspector); `StatCapsule` and `DryRunBanner` updated to use design tokens; auto-selects first pair/group on appear; keyboard focus state via `FocusedPane` enum; Export menu (CSV + clipboard summary)
- **GUI**: `ComparisonPanel` rewritten as visual comparison surface — side-by-side thumbnails (`ThumbnailView` with base64 decode and placeholder fallback), `MetadataDiffTable` three-column grid highlighting differing field values, `ScoreBreakdownDetail` with stacked `BreakdownBar` and per-`ComparatorRow` breakdown (raw%, weight, contribution)
- **GUI**: `ScoreRing` fixed to use `DDColors.scoreColor(for:)` instead of hardcoded colors
- **GUI**: Replace centered-percentage progress screen with contextual scan dashboard — scan context header (mode badge, directory list, feature pills), enriched horizontal pipeline bar with real per-node counts and elapsed time, primary progress display with percentage/elapsed/throughput/ETA, conditional active-file detail, progressive stat counters that appear as stages complete, pinned cancel bar with glass chrome styling, full design token compliance, and adaptive density (sections self-omit when no data is available)
- **GUI**: Replaced 6-tab configuration panel with scan composer — hero source picker, mode selector, preset chips (Quick/Standard/Thorough), session summary, and advanced disclosure groups
- **GUI**: Added scan presets with exact CLI flag mappings per mode (video/image/audio), automatic Custom detection when values are manually changed
- **GUI**: Keep/action controls (previously deferred) now fully implemented in `ConfigurationScreen` and wired through to scan execution (issue #10)
- Replace `TabView` navigation (Scan/Watch/History tabs) with a `NavigationSplitView` sidebar workspace (New Scan, Settings) in the macOS GUI — sidebar selection drives the detail area via `AppState.selectedDestination`
- Redesign dependency check screen with capability-first framing: leads with 5 capability cards (Video Scanning, Image Scanning, Audio Scanning, Content Hashing, Audio Fingerprinting) backed by `DependencyStatus`; tool details moved to a collapsible `DisclosureGroup`; all colors replaced with design tokens

### Fixed
- **GUI**: Trash errors now surfaced as alerts (`trashError` on `ScanResultsModel`) instead of being silently swallowed — both bulk trash and per-file trash paths report failures to the user
- Fix GUI auto-advance gating: use `meetsMinimumRequirements` instead of `canScanVideo` so users who only have image-mode dependencies (PIL, no ffprobe) can proceed past the dependency check screen
- Fix `"fileSize"` → `"filesize"` in `DesignTokens.swift` (`DDComparators.names` and `comparatorColors`) to match the CLI comparator key naming convention
- **GUI**: Fix `WeightsEditorView` "filesize" color lookup — CLI weight key `"filesize"` now resolves to the correct teal color via the `"filesize"` alias in `comparatorColors`; previously fell back to `DDColors.textMuted`
- Fix `--machine-progress` score stage stalling during filename cross-bucket (pass 2) and content all-pairs (pass 3) scoring — emit incremental progress updates inside pass-2/pass-3 loops instead of a single lump-sum event at the end of each pass
- Fix `--rotation-invariant` content comparison being order-dependent — `compare(a, b)` could return a different score than `compare(b, a)` for 8-tuple hashes, now checks both directions symmetrically
- Validate `--min-score` bounds (0–100) on the CLI path — previously out-of-range values like `-1` or `150` were silently accepted
- Fix group table header reporting file count from truncated set instead of all groups
- Suppress truncation warnings in `--quiet` mode for both pair and group tables
- Show throughput (files/s, pairs/s) in progress bars during metadata extraction, content hashing, and scoring

### Removed
- **GUI**: Delete `WatchCoordinator.swift`, `WatchSetupModel.swift`, `WatchConfigurationScreen.swift`, `WatchFlowView.swift` — unified into `ScanCoordinator`, `ScanSetupModel`, and `ConfigurationScreen`; deleted corresponding test files `WatchCoordinatorTests.swift` and `WatchSetupModelTests.swift`
- **GUI**: Delete `DirectoryManaging` and `WeightsEditable` protocols from `ScanSetupModel.swift` — `DirectoryPickerSection` and `WeightsEditorView` now use `ScanSetupModel` directly
- **GUI**: Remove `.watch` sidebar destination from `SidebarDestination` — watch mode is now launched from the configuration screen, not a separate sidebar entry
- **GUI**: Delete empty `ScoreBadge.swift` — file contained no implementation and had no callers; score badge rendering is handled by `ScoreRing`
- Delete empty placeholder `WatchFlowView.swift` and `HistoryScreen.swift` from the GUI (screens will be re-added once implemented)

## [1.2.0] - 2026-03-02
### Fixed
- Fix `--keep --dry-run --format json|shell --log FILE` not writing dry-run records to action log — action log is now initialized before the pre-compute step
- Fix `--content-interval` / `--hash-size` validation errors when `--content` is not enabled — these flags are now silently ignored without content mode
- Fix JSON envelope `args` to use a stable key set with all keys always present (null when unset) and `weights` as a structured object instead of raw CLI string

### Changed
- Vectorize `compare_content_hashes()` with numpy for significantly faster content-mode scoring (pure-Python fallback retained for `--hash-size` > 8)

### Added
- Add `--content-interval SECS` flag to control frame extraction interval for content hashing (default: 2.0)
- Add `--hash-size N` flag to control perceptual hash size NxN for content hashing (default: 8)
- Add `--json-envelope` flag to wrap `--format json` output in a richer envelope with version, timestamp, args, and stats
- Add `--min-resolution WxH` and `--max-resolution WxH` flags to filter files by pixel count before scoring
- Add `--min-bitrate RATE` and `--max-bitrate RATE` flags to filter files by container bitrate (supports bps, kbps, Mbps, Gbps suffixes)
- Add `--codec CODEC,...` flag to restrict comparison to specific video codecs (comma-separated, case-insensitive)
- Add `--log FILE` flag for append-only JSON-lines action log — records every deletion, move, or link action with timestamp, score, strategy, and kept file for audit trails and manual recovery
- Add `--ignore-file PATH` flag to specify a custom ignored-pairs file location
- Add `--clear-ignored` flag to clear the ignored-pairs list and exit
- Add `s!` (skip & remember) choice in interactive review to permanently ignore a pair — ignored pairs are filtered out on subsequent runs
- Add `ignorelist.py` module for persistent false-positive ignore list (`$XDG_DATA_HOME/duplicates-detector/ignored-pairs.json`)
- Add `actionlog.py` module for JSON-lines action logging

## [1.1.0] - 2026-03-01
### Added
- Add `--print-completion SHELL` flag for shell tab completion via shtab (supports bash, zsh, fish)
- Add `--action hardlink` and `--action symlink` to replace duplicates with filesystem links instead of deleting
- Add `--weights SPEC` flag for custom comparator weights (e.g., `filename=50,duration=30,resolution=10,filesize=10`)
- Show Rich progress bars unconditionally during all pipeline stages (scan, metadata extraction, content hashing, scoring) — no longer requires `-v`
- Add post-run summary panel showing files scanned, duplicates found, space recoverable, cache hit rates, and per-stage timing
- Add `stats` out-parameter to `find_duplicates()` exposing total pairs scored for summary reporting
- Add `--sort FIELD` flag to sort output by `score`, `size`, `path`, or `mtime` (default: `score`)
- Add `--limit N` flag to limit displayed pairs or groups to the top N results
- Add `-q` / `--quiet` flag to suppress progress bars and summary panel (machine-friendly output)
- Add `--no-color` flag to disable colored terminal output
- Add structured dry-run summary to JSON and shell output when using `--keep --dry-run` — includes files to delete, sizes, and totals

### Changed
- `-v` / `--verbose` now controls supplementary text output (cache stats, bucket details, skipped files) but no longer gates progress bars

### Fixed
- `--quiet` now suppresses all early-exit messages and summary panels (previously leaked output when fewer than 2 files found)
- `--no-color` now reliably disables ANSI styling in progress bars and pipeline status output
- `--no-color` is honored by `--show-config` and `--save-config` early-exit paths
- `no_color = true` in config.toml now applies to the main pipeline (previously only worked via CLI flag)
- `-q` now suppresses config file validation warnings when passed on the command line
- Exit with code 1 when deletion errors occur in quiet mode (previously exited 0 silently)

## [1.0.0] - 2026-02-28

### Added
- Add TOML config file (`~/.config/duplicates-detector/config.toml`) for persistent flag defaults — CLI flags always override
- Add `--save-config` flag to write current flags to the config file and exit
- Add `--show-config` flag to print the resolved config (after merging defaults, config file, and CLI) and exit
- Add `--no-config` flag to ignore the config file for a single run
- Add `format_size()` utility for converting bytes back to human-readable strings (inverse of `parse_size()`)
- Display codec, bitrate, frame rate, and audio channels in group tables, interactive panels, JSON, and CSV output — helps users decide which duplicate to keep
- Add disk-based metadata cache for ffprobe results — enabled by default, skips ffprobe on re-runs for unchanged files (`$XDG_CACHE_HOME/duplicates-detector/metadata.json`)
- Add `--no-metadata-cache` flag to disable metadata caching and force ffprobe on every file
- Add disk-based content hash cache to avoid redundant ffmpeg extraction on re-runs (`$XDG_CACHE_HOME/duplicates-detector/content-hashes.json`)
- Add `--no-content-cache` flag to disable content hash caching and force re-extraction
- Add `--keep STRATEGY` flag for auto-selecting which file to keep in each duplicate pair (newest, oldest, biggest, smallest, longest, highest-res)
- Add `mtime` field to VideoMetadata for file modification time tracking (supports newest/oldest strategies)
- Add `auto_delete()` function for non-interactive bulk deletion with keep strategy
- Add keep-strategy markers to all output formats (table: KEEP label, JSON: keep field, CSV: keep column, shell: uncommented rm)
- Add `--reference DIR` flag for reference directories whose files participate in comparison but are never suggested for deletion
- Add `--group` flag for cluster-based duplicate display using transitive grouping (union-find) instead of individual pairs
- Add `--content` flag for perceptual video hashing — catches re-encodes, resolution changes, watermarked copies, and different containers of the same content
- Add `--action delete|trash|move-to` flag for safe deletion alternatives (trash and staging directory)
- Add `--move-to-dir DIR` flag for specifying staging directory with `--action move-to`
- Add `deleter.py` module with strategy pattern for deletion methods (PermanentDeleter, TrashDeleter, MoveDeleter)
- Add optional `send2trash` dependency via `[trash]` extras group for `--action trash`
- Add `--cache-dir DIR` flag to control the cache directory for metadata and content hashes (overrides XDG default)
- Add `cache_dir` config file support — persistable via `--save-config`, CLI always overrides
- Display codec, bitrate, frame rate, and audio channels in the default pair table output (previously only shown in grouped/interactive views)

### Fixed
- Handle `PermissionError` during directory scanning — unreadable subdirectories and files are skipped with a warning instead of aborting the entire scan
- Add defensive deduplication to parallel filename and content scoring passes to prevent duplicate pairs in results

- Disable filename gate when `--content` is active so renamed re-encodes are detected by the content comparator
- Widen cross-bucket candidate filter in `--content` mode to catch renamed re-encodes with duration drift beyond the ±4s bucket tolerance
- Restrict zero filename cutoff to pairs where both files have content hashes; metadata-only pairs in content mode now keep the standard 80% cutoff
- Fix timeout race in content hashing: if ffmpeg exits naturally as the timer fires, hashes are preserved instead of discarded

### Changed
- Bump metadata cache version to v2 — existing caches are silently discarded on first run after upgrade
- ffprobe now extracts all streams instead of only the first video stream, enabling audio channel detection
- Content-mode Pass 3 (all-pairs on hashed subset) now parallelizes via ProcessPoolExecutor when `workers > 1` and `len(hashed) > 100`, improving cached-run performance
- Content hashing worker count reduced from `cpu_count * 4` (cap 64) to `cpu_count * 2` (cap 32) — ffmpeg frame extraction is heavier than ffprobe
- Scorer parallel workers now accept custom comparator lists instead of hardcoding defaults
- CSV output derives breakdown columns dynamically from scored pairs instead of hardcoding column names
