import Foundation

// MARK: - Enums

/// The deduplication mode (`--mode`).
enum ScanMode: String, Sendable, CaseIterable {
    case video
    case image
    case audio
    case document
    case auto
}

/// File extensions per media type — single source of truth mirroring the CLI's scanner.py.
enum MediaExtensions {
    static let video: Set<String> = [
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v",
        "mpg", "mpeg", "ts", "vob", "3gp", "ogv",
    ]
    static let image: Set<String> = [
        "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif",
        "heic", "heif", "avif", "svg", "ico",
    ]
    static let audio: Set<String> = [
        "mp3", "flac", "aac", "m4a", "wav", "ogg", "opus", "wma",
        "ape", "alac", "aiff", "aif", "wv", "dsf", "dff",
    ]
    static let document: Set<String> = ["pdf", "docx", "txt", "md"]
}

/// The keep strategy (`--keep`).
enum KeepStrategy: String, Sendable, CaseIterable {
    case newest
    case oldest
    case biggest
    case smallest
    case longest
    case highestRes = "highest-res"

    var displayName: String {
        rawValue.replacingOccurrences(of: "-", with: " ").capitalized
    }
}

/// The action to perform on duplicates (`--action`).
enum ActionType: String, Sendable, CaseIterable {
    case delete
    case trash
    case moveTo = "move-to"
    case hardlink
    case symlink
    case reflink

    /// Human-readable name for display in the GUI.
    var displayName: String {
        switch self {
        case .delete: "Permanent Delete"
        case .trash: "Move to Trash"
        case .moveTo: "Move To..."
        case .hardlink: "Hardlink"
        case .symlink: "Symlink"
        case .reflink: "Reflink"
        }
    }
}

/// Sort field (`--sort`).
enum SortField: String, Sendable, CaseIterable {
    case score
    case size
    case path
    case mtime
}

/// Content comparison method (`--content-method`).
enum ContentMethod: String, Sendable, CaseIterable {
    case phash
    case ssim
    case clip
    case simhash
    case tfidf
}

// MARK: - ScanConfig

/// All CLI flags represented as Swift types.
///
/// Mirrors the Python `DEFAULTS` dict from `config.py`.
/// Values left as `nil` use CLI defaults and are not emitted as flags.
struct ScanConfig: Codable, Equatable, Sendable {
    // Source type
    var scanSource: ScanSource = .directory

    // Directories to scan (positional args)
    var directories: [String] = []

    // Core options
    var mode: ScanMode = .video
    var threshold: Int = 50
    var extensions: String?
    var workers: Int = 0

    // Keep / action
    var keep: KeepStrategy?
    var action: ActionType = .delete
    /// True when the user explicitly chose the action in the GUI (as opposed to
    /// inheriting the ScanConfig default). Used by `SessionStore` to decide
    /// whether to apply the GUI safety override (.delete → .trash).
    var actionExplicitlySet: Bool = false
    var moveToDir: String?

    // Output
    var sort: SortField = .score
    var limit: Int?
    var minScore: Int?
    var group: Bool = false
    var verbose: Bool = false

    // Content hashing
    var content: Bool = false
    var rotationInvariant: Bool?
    var contentMethod: ContentMethod?

    // Audio fingerprinting
    var audio: Bool = false

    // Filters
    var minSize: String?
    var maxSize: String?
    var minDuration: Double?
    var maxDuration: Double?
    var minResolution: String?
    var maxResolution: String?
    var minBitrate: String?
    var maxBitrate: String?
    var codec: String?

    /// Whether any filter is set (determines if CLI emits a filter progress stage).
    var hasFilters: Bool {
        minSize?.isEmpty == false || maxSize?.isEmpty == false
            || minResolution?.isEmpty == false || maxResolution?.isEmpty == false
            || minBitrate?.isEmpty == false || maxBitrate?.isEmpty == false
            || codec?.isEmpty == false
            || minDuration != nil || maxDuration != nil
    }

    // Exclude patterns
    var exclude: [String] = []

    // Reference directories
    var reference: [String] = []

    // Cache control
    var cacheDir: String?
    var noMetadataCache: Bool = false
    var noContentCache: Bool = false
    var noAudioCache: Bool = false
    var noRecursive: Bool = false

    // Thumbnails
    var embedThumbnails: Bool = false
    var thumbnailSize: String?

    // Ignore / log
    var ignoreFile: String?
    var log: String?

    // Dry run
    var dryRun: Bool = false

    // Weights
    var weights: [String: Double]?

    // Replay
    /// Path to a JSON envelope file for replay mode.
    var replayPath: String?

    // Pause control
    /// Path to the pause control file for GUI-to-CLI communication.
    var pauseFile: String?

    // Session resume
    /// Session ID to resume a previously paused scan.
    var resume: String?

    // Cache statistics
    /// Show cache statistics in output.
    var cacheStats: Bool = false

    // Internal: temp file for JSON output (bypasses slow stdout pipe reads).
    /// When set, the GUI passes ``--output`` so the CLI writes its JSON
    /// envelope to this file instead of stdout.  The GUI reads the file
    /// after the process exits, avoiding the 1-byte-at-a-time DispatchIO
    /// overhead caused by ``preferredBufferSize: 1``.
    var resultOutputFile: String?

    /// Reconstruct a `ScanConfig` from a paused CLI session's config snapshot.
    ///
    /// The `SessionInfo.config` dict uses Python snake_case keys matching the CLI's
    /// `DEFAULTS` dict. Maps all fields so `state.config`/`lastScanConfig` faithfully
    /// reflect the paused session rather than the GUI setup form.
    static func fromPausedSession(_ info: SessionInfo) -> ScanConfig {
        let c = info.config
        var config = ScanConfig()
        config.directories = info.directories

        // Core options
        if let v = c["mode"]?.stringValue { config.mode = ScanMode(rawValue: v) ?? .video }
        if let v = c["threshold"]?.intValue { config.threshold = v }
        if let v = c["extensions"]?.stringValue { config.extensions = v }
        if let v = c["workers"]?.intValue { config.workers = v }

        // Keep / action
        if let v = c["keep"]?.stringValue { config.keep = KeepStrategy(rawValue: v) }
        if let v = c["action"]?.stringValue { config.action = ActionType(rawValue: v) ?? .delete }
        if let v = c["move_to_dir"]?.stringValue { config.moveToDir = v }

        // Output
        if let v = c["sort"]?.stringValue { config.sort = SortField(rawValue: v) ?? .score }
        if let v = c["limit"]?.intValue { config.limit = v }
        if let v = c["min_score"]?.intValue { config.minScore = v }
        config.group = c["group"]?.boolValue ?? false
        config.verbose = c["verbose"]?.boolValue ?? false

        // Content hashing
        config.content = c["content"]?.boolValue ?? false
        if let v = c["rotation_invariant"]?.boolValue { config.rotationInvariant = v }
        if let v = c["content_method"]?.stringValue { config.contentMethod = ContentMethod(rawValue: v) }

        // Audio
        config.audio = c["audio"]?.boolValue ?? false

        // Filters
        if let v = c["min_size"]?.stringValue { config.minSize = v }
        if let v = c["max_size"]?.stringValue { config.maxSize = v }
        if let v = c["min_duration"]?.doubleValue { config.minDuration = v }
        if let v = c["max_duration"]?.doubleValue { config.maxDuration = v }
        if let v = c["min_resolution"]?.stringValue { config.minResolution = v }
        if let v = c["max_resolution"]?.stringValue { config.maxResolution = v }
        if let v = c["min_bitrate"]?.stringValue { config.minBitrate = v }
        if let v = c["max_bitrate"]?.stringValue { config.maxBitrate = v }
        if let v = c["codec"]?.stringValue { config.codec = v }

        // Exclude / reference — these are arrays in the CLI but stored as single
        // values in the session snapshot. The GUI only uses them for persistence,
        // not for flag assembly during resume.
        // (Not mapped — CLI restores from its own snapshot.)

        // Cache control
        if let v = c["cache_dir"]?.stringValue { config.cacheDir = v }
        config.noMetadataCache = c["no_metadata_cache"]?.boolValue ?? false
        config.noContentCache = c["no_content_cache"]?.boolValue ?? false
        config.noAudioCache = c["no_audio_cache"]?.boolValue ?? false
        config.noRecursive = c["no_recursive"]?.boolValue ?? false

        // Thumbnails
        config.embedThumbnails = c["embed_thumbnails"]?.boolValue ?? false
        if let v = c["thumbnail_size"]?.stringValue { config.thumbnailSize = v }

        // Ignore / log
        if let v = c["ignore_file"]?.stringValue { config.ignoreFile = v }
        if let v = c["log"]?.stringValue { config.log = v }

        return config
    }

    /// Reconstruct a `ScanConfig` from a `ScanArgs` dict (from a saved envelope).
    ///
    /// Not all fields round-trip perfectly — presentation-only fields like `verbose`
    /// and `log` are not stored in the envelope args. This is sufficient for
    /// re-scanning the same directories with the same core settings.
    static func fromEnvelopeArgs(_ args: ScanArgs) -> ScanConfig {
        var config = ScanConfig()
        config.directories = args.directories
        config.mode = ScanMode(rawValue: args.mode) ?? .video
        config.threshold = args.threshold
        config.content = args.content
        if let method = args.contentMethod { config.contentMethod = ContentMethod(rawValue: method) }
        config.weights = args.weights?.values
        if let keep = args.keep { config.keep = KeepStrategy(rawValue: keep) }
        config.action = ActionType(rawValue: args.action) ?? .trash
        config.group = args.group
        config.sort = SortField(rawValue: args.sort) ?? .score
        config.limit = args.limit
        config.minScore = args.minScore
        config.exclude = args.exclude ?? []
        config.reference = args.reference ?? []
        config.embedThumbnails = args.embedThumbnails
        return config
    }
}

// MARK: - Codable Conformances (for SessionRegistry persistence)

extension KeepStrategy: Codable {}
extension ActionType: Codable {}
extension SortField: Codable {}
extension ContentMethod: Codable {}
