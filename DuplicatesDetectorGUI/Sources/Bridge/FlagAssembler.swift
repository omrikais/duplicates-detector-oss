import Foundation

/// Assembles CLI argument arrays from ``ScanConfig``.
///
/// Always includes: `scan`, `--no-config`, `--format json`, `--json-envelope`,
/// `--machine-progress`, `--no-color`. Only emits flags for non-default values.
enum FlagAssembler {
    /// Build `[String]` arguments for a scan or replay invocation.
    static func assembleFlags(from config: ScanConfig) -> [String] {
        if let replayPath = config.replayPath {
            return assembleReplayFlags(replayPath: replayPath, config: config)
        }
        if let sessionId = config.resume {
            return assembleResumeFlags(sessionId: sessionId, config: config)
        }
        return assembleScanFlags(from: config)
    }

    /// Build `[String]` arguments for resuming a paused CLI session.
    ///
    /// The CLI treats `--resume` as mutually exclusive with directory arguments
    /// and config-altering flags (the session contains a full config snapshot).
    /// Only presentation-only overrides (RESUME_OVERRIDE_KEYS) are permitted.
    private static func assembleResumeFlags(sessionId: String, config: ScanConfig) -> [String] {
        var args = ["scan", "--no-config", "--format", "json", "--json-envelope",
                    "--machine-progress", "--no-color"]
        args += ["--resume", sessionId]

        // RESUME_OVERRIDE_KEYS: presentation-only flags the CLI allows alongside --resume
        if config.verbose { args.append("--verbose") }
        if config.cacheStats { args.append("--cache-stats") }

        // Pause file (GUI-originated, not a CLI config key)
        if let pauseFile = config.pauseFile {
            args += ["--pause-file", pauseFile]
        }
        if let output = config.resultOutputFile { args += ["--output", output] }

        return args
    }

    /// Build `[String]` arguments for a replay invocation.
    ///
    /// Only emits replay-compatible flags per CLI `_validate_replay_conflicts()`:
    /// output shaping, ignore/log, and thumbnail options. No directories, filters,
    /// weights, content, or audio flags.
    private static func assembleReplayFlags(replayPath: String, config: ScanConfig) -> [String] {
        var args = ["scan", "--no-config", "--format", "json", "--json-envelope",
                    "--machine-progress", "--no-color"]
        args += ["--replay", replayPath]

        // Keep strategy (replay-compatible per CLI _validate_replay_conflicts)
        if let keep = config.keep { args += ["--keep", keep.rawValue] }

        // Output shaping only
        if config.sort != .score { args += ["--sort", config.sort.rawValue] }
        if let limit = config.limit { args += ["--limit", String(limit)] }
        if let minScore = config.minScore { args += ["--min-score", String(minScore)] }
        if config.group { args.append("--group") }
        for ref in config.reference { args += ["--reference", ref] }
        if config.embedThumbnails {
            args.append("--embed-thumbnails")
            if let size = config.thumbnailSize { args += ["--thumbnail-size", size] }
        }
        if let f = config.ignoreFile { args += ["--ignore-file", f] }
        if let f = config.log { args += ["--log", f] }
        if let output = config.resultOutputFile { args += ["--output", output] }

        return args
    }

    /// Build `[String]` arguments for a scan invocation.
    private static func assembleScanFlags(from config: ScanConfig) -> [String] {
        var args: [String] = ["scan"]

        // Always-on flags for GUI operation
        args += ["--no-config", "--format", "json", "--json-envelope", "--machine-progress", "--no-color"]

        appendSharedFlags(from: config, to: &args)

        // Keep / action (scan-only)
        if let keep = config.keep {
            args += ["--keep", keep.rawValue]
        }
        // Note: --action and --move-to-dir are intentionally NOT sent to the CLI.
        // The GUI handles all file operations (trash, delete, move) locally via
        // FileManager, so the CLI only needs to scan and produce JSON output.
        // Sending --action trash would fail on installs without send2trash.

        // Output options (scan-only)
        if config.sort != .score {
            args += ["--sort", config.sort.rawValue]
        }
        if let limit = config.limit {
            args += ["--limit", String(limit)]
        }
        if config.group {
            args.append("--group")
        }
        if config.verbose {
            args.append("--verbose")
        }

        // Thumbnails (scan-only)
        if config.embedThumbnails {
            args.append("--embed-thumbnails")
            if let size = config.thumbnailSize {
                args += ["--thumbnail-size", size]
            }
        }

        // Output file (internal: bypass slow stdout pipe for large JSON)
        if let output = config.resultOutputFile { args += ["--output", output] }

        // Log (scan-only)
        if let f = config.log { args += ["--log", f] }

        // Dry run (scan-only)
        if config.dryRun { args.append("--dry-run") }

        // Pause file (scan-only, GUI-originated)
        if let pauseFile = config.pauseFile {
            args += ["--pause-file", pauseFile]
        }

        // Session resume
        if let sessionId = config.resume {
            args += ["--resume", sessionId]
        }

        // Cache statistics
        if config.cacheStats {
            args.append("--cache-stats")
        }

        // Directories (positional, always last)
        args += config.directories

        return args
    }

    // MARK: - Shared Flags

    /// Append shared flags to the argument list.
    private static func appendSharedFlags(from config: ScanConfig, to args: inout [String]) {
        // Mode (default: video)
        if config.mode != .video {
            args += ["--mode", config.mode.rawValue]
        }

        // Threshold (default: 50)
        if config.threshold != 50 {
            args += ["--threshold", String(config.threshold)]
        }

        // Extensions
        if let ext = config.extensions {
            args += ["--extensions", ext]
        }

        // Workers (default: 0 = auto)
        if config.workers != 0 {
            args += ["--workers", String(config.workers)]
        }

        // Weights
        if let weights = config.weights, !weights.isEmpty {
            let spec = weights
                .sorted(by: { $0.key < $1.key })
                .map { "\($0.key)=\(formatWeight($0.value))" }
                .joined(separator: ",")
            args += ["--weights", spec]
        }

        // Content hashing
        if config.content {
            args.append("--content")

            if let ri = config.rotationInvariant, ri {
                args.append("--rotation-invariant")
            }
            if let method = config.contentMethod {
                args += ["--content-method", method.rawValue]
            }
        }

        // Audio fingerprinting
        if config.audio {
            args.append("--audio")
        }

        // Min score
        if let minScore = config.minScore {
            args += ["--min-score", String(minScore)]
        }

        // Filters
        if let v = config.minSize { args += ["--min-size", v] }
        if let v = config.maxSize { args += ["--max-size", v] }
        if let v = config.minDuration { args += ["--min-duration", String(v)] }
        if let v = config.maxDuration { args += ["--max-duration", String(v)] }
        if let v = config.minResolution { args += ["--min-resolution", v] }
        if let v = config.maxResolution { args += ["--max-resolution", v] }
        if let v = config.minBitrate { args += ["--min-bitrate", v] }
        if let v = config.maxBitrate { args += ["--max-bitrate", v] }
        if let v = config.codec { args += ["--codec", v] }

        // Exclude patterns (repeated flag)
        for pattern in config.exclude {
            args += ["--exclude", pattern]
        }

        // Reference directories (repeated flag)
        for ref in config.reference {
            args += ["--reference", ref]
        }

        // Cache control
        if let dir = config.cacheDir { args += ["--cache-dir", dir] }
        if config.noMetadataCache { args.append("--no-metadata-cache") }
        if config.noContentCache { args.append("--no-content-cache") }
        if config.noAudioCache { args.append("--no-audio-cache") }
        if config.noRecursive { args.append("--no-recursive") }

        // Ignore
        if let f = config.ignoreFile { args += ["--ignore-file", f] }
    }

    /// Format a weight value: drop `.0` for whole numbers, preserve fractional parts.
    private static func formatWeight(_ value: Double) -> String {
        value.isWholeNumber ? String(Int(value)) : String(value)
    }
}

// MARK: - Double helpers

extension Double {
    /// Whether this value represents a whole number (e.g. 50.0 → true, 50.5 → false).
    var isWholeNumber: Bool {
        self == rounded(.towardZero) && truncatingRemainder(dividingBy: 1) == 0
    }
}
