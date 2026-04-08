import Foundation

// MARK: - DirectoryEntry

/// A user-selected scan directory with optional reference flag.
struct DirectoryEntry: Identifiable, Sendable, Equatable {
    let id = UUID()
    var path: String
    var isReference: Bool = false

    /// Equality by meaningful fields only (path + isReference); `id` is an opaque
    /// identity for SwiftUI `ForEach` and is intentionally excluded.
    static func == (lhs: DirectoryEntry, rhs: DirectoryEntry) -> Bool {
        lhs.path == rhs.path && lhs.isReference == rhs.isReference
    }
}

// MARK: - SetupAction

/// Every mutation to the setup/configuration state maps to exactly one action.
enum SetupAction: Sendable {
    case setMode(ScanMode)
    case setThreshold(Int)
    case setContent(Bool)
    case setAudio(Bool)
    case setWorkers(Int)
    case addDirectory(URL)
    case removeDirectory(URL)
    case toggleReference(URL)
    case setWeightString(key: String, value: String)
    case toggleLockedWeight(String)
    case applyPreset(ScanPreset)
    case applyProfile(ProfileData)
    case reloadDefaults
    case setFilter(FilterField, String)
    case setKeep(KeepStrategy?)
    case setAction(ActionType)
    case setMoveToDir(String)
    case setSort(SortField)
    case setGroup(Bool)
    case setLimit(String)
    case setMinScore(String)
    case setExtensions(String)
    case addExclude(String)
    case removeExclude(Int)
    case setExcludeInput(String)
    case setScanSource(ScanSource)
    case setBool(SetupBoolField, Bool)
    case fileCountUpdated(Int?)
    case setDependencyStatus(DependencyStatus?)
    case setContentMethod(ContentMethod)
    case setThumbnailSize(String)
    case setCacheDir(String)
    case setIgnoreFile(String)
    case setLog(String)
}

/// Identifies which filter field to update.
enum FilterField: Sendable {
    case minSize, maxSize, minDuration, maxDuration
    case minResolution, maxResolution, minBitrate, maxBitrate, codec
}

/// Identifies which boolean field to update via `.setBool`.
enum SetupBoolField: Sendable {
    case noRecursive, noMetadataCache, noContentCache, noAudioCache
    case verbose, dryRun, embedThumbnails, rotationInvariant
    case hasAppliedInitialPreset, suppressPresetOnModeChange
}

// MARK: - SetupEffect

/// Side effects returned by the setup reducer. Executed by the store.
enum SetupEffect: Sendable, Equatable {
    case updateFileCount
    case detectPreset
}

// MARK: - SetupState

/// Pure-value replacement for `ScanSetupModel`.
///
/// All fields from the old `@Observable` class are ported here as a plain
/// `Sendable, Equatable` struct. Mutations happen exclusively through
/// `SetupReducer.reduce(state:action:)`.
struct SetupState: Sendable, Equatable {

    // MARK: - Source selection

    var scanSource: ScanSource = .directory

    // MARK: - Directory management

    var entries: [DirectoryEntry] = []

    // MARK: - Core settings

    var mode: ScanMode = .video
    var threshold: Int = 50
    var workers: Int = 0

    // MARK: - Keep / Action

    var keep: KeepStrategy? = nil
    var action: ActionType = .trash
    var moveToDir: String = ""

    // MARK: - Content hashing

    var content: Bool = false
    var contentMethod: ContentMethod = .phash
    var rotationInvariant: Bool = false

    // MARK: - Audio fingerprinting

    var audio: Bool = false

    // MARK: - Weights

    /// String intermediates for weight text fields (keyed by weight name).
    var weightStrings: [String: String] = [:]

    /// Weight keys that are locked (excluded from auto-rebalance redistribution).
    var lockedWeights: Set<String> = []

    // MARK: - Filters

    var minSize: String = ""
    var maxSize: String = ""
    var minDuration: String = ""
    var maxDuration: String = ""
    var minResolution: String = ""
    var maxResolution: String = ""
    var minBitrate: String = ""
    var maxBitrate: String = ""
    var codec: String = ""

    // MARK: - Output

    var sort: SortField = .score
    var limit: String = ""
    var minScore: String = ""
    var group: Bool = false
    var verbose: Bool = false

    // MARK: - Advanced

    var extensions: String = ""
    var exclude: [String] = []
    var excludeInput: String = ""
    var noRecursive: Bool = false
    var noMetadataCache: Bool = false
    var noContentCache: Bool = false
    var noAudioCache: Bool = false
    var cacheDir: String = ""
    var ignoreFile: String = ""
    var log: String = ""
    var dryRun: Bool = false
    /// Defaults to `true` (unlike CLI's `false`) because the GUI results screen
    /// renders base64 thumbnails for file previews.
    var embedThumbnails: Bool = true
    var thumbnailSize: String = ""

    // MARK: - File count estimation

    var estimatedFileCount: Int?
    var isCountingFiles: Bool = false

    // MARK: - Preset tracking

    /// Lightweight hash of all preset-controlled fields.
    /// Used by `ScanSetupView` to detect preset changes with a single `onChange`.
    struct PresetSignature: Hashable, Sendable {
        let content: Bool
        let audio: Bool
        let threshold: Int
        let group: Bool
        let embedThumbnails: Bool
        let rotationInvariant: Bool
        let weightStrings: [String: String]
        let contentMethod: ContentMethod
        let thumbnailSize: String
    }

    var presetSignature: PresetSignature {
        PresetSignature(
            content: content, audio: audio, threshold: threshold,
            group: group, embedThumbnails: embedThumbnails,
            rotationInvariant: rotationInvariant,
            weightStrings: weightStrings,
            contentMethod: contentMethod, thumbnailSize: thumbnailSize
        )
    }

    var activePreset: ScanPreset? = nil
    var hasAppliedInitialPreset: Bool = false
    var suppressPresetOnModeChange: Bool = false

    // MARK: - CLI-only profile fields

    var cliOnlyFormat: String?
    var cliOnlyJsonEnvelope: Bool?
    var cliOnlyQuiet: Bool?
    var cliOnlyNoColor: Bool?
    var cliOnlyMachineProgress: Bool?

    // MARK: - Dependencies

    var dependencyStatus: DependencyStatus?

    // MARK: - Computed Properties

    /// Whether the user has modified any configuration beyond system-driven defaults.
    /// Excludes `dependencyStatus`, `estimatedFileCount`, `isCountingFiles`, and
    /// CLI-only profile fields which are set automatically during launch.
    var hasUserModifications: Bool {
        var normalized = self
        var defaults = SetupState.fromDefaults()
        // Zero out system-driven fields so they don't affect comparison
        normalized.dependencyStatus = nil
        defaults.dependencyStatus = nil
        normalized.estimatedFileCount = nil
        defaults.estimatedFileCount = nil
        normalized.isCountingFiles = false
        defaults.isCountingFiles = false
        // CLI-only fields are never user-driven in the GUI
        normalized.cliOnlyFormat = nil
        defaults.cliOnlyFormat = nil
        normalized.cliOnlyJsonEnvelope = nil
        defaults.cliOnlyJsonEnvelope = nil
        normalized.cliOnlyQuiet = nil
        defaults.cliOnlyQuiet = nil
        normalized.cliOnlyNoColor = nil
        defaults.cliOnlyNoColor = nil
        normalized.cliOnlyMachineProgress = nil
        defaults.cliOnlyMachineProgress = nil
        return normalized != defaults
    }

    /// The weight keys currently visible based on mode + content + audio.
    var visibleWeightKeys: [String] {
        WeightDefaults.requiredKeys(mode: mode, content: content, audio: audio) ?? []
    }

    /// Sum of all visible weight values (non-finite values treated as 0).
    var weightSum: Double {
        visibleWeightKeys.compactMap { Double(weightStrings[$0] ?? "") }
            .filter(\.isFinite)
            .reduce(0, +)
    }

    /// Whether the weight sum equals 100 (within tolerance).
    var isWeightSumValid: Bool {
        abs(weightSum - 100) <= 0.01
    }

    /// Whether any filter argument is set.
    var hasFilters: Bool {
        [minSize, maxSize, minDuration, maxDuration,
         minResolution, maxResolution, minBitrate, maxBitrate, codec]
            .contains { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    /// Number of active filter fields (for badge display).
    var activeFilterCount: Int {
        [minSize, maxSize, minDuration, maxDuration,
         minResolution, maxResolution, minBitrate, maxBitrate, codec]
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            .count
    }

    /// All current validation errors.
    var validationErrors: [String] {
        environmentErrors + configurationErrors
    }

    /// Whether the configuration is valid and ready to scan.
    var isValid: Bool { validationErrors.isEmpty }

    /// Errors that should block saving a named profile (excludes environment checks).
    var profileSaveErrors: [String] {
        configurationErrors
    }

    /// Non-blocking warnings (scan can still proceed).
    var validationWarnings: [String] {
        var warnings: [String] = []
        if let deps = dependencyStatus, mode == .auto {
            if !deps.canScanVideo {
                warnings.append("ffprobe not found — video metadata extraction will fail if videos are present.")
            }
            if content && !deps.canContentHash {
                warnings.append("ffmpeg not found — video content hashing will fail if videos are present.")
            }
        }
        return warnings
    }

    // MARK: - Validation (private)

    /// Directory and dependency checks — environment-specific.
    private var environmentErrors: [String] {
        var errors: [String] = []

        if scanSource == .directory && entries.filter({ !$0.isReference }).isEmpty {
            errors.append("At least one scan directory is required.")
        }

        // Photos Library scans use PhotoKit, not the CLI — skip CLI dependency checks.
        if scanSource == .directory, let deps = dependencyStatus {
            switch mode {
            case .video:
                if !deps.canScanVideo {
                    errors.append("Video mode requires ffprobe (not found).")
                }
            case .audio:
                if !deps.canScanAudio {
                    errors.append("Audio mode requires mutagen (not installed).")
                }
            case .document:
                if !deps.canScanDocument {
                    errors.append("Document mode requires pdfminer (not installed). Install with: pip install \"duplicates-detector[document]\"")
                }
            case .image, .auto: break
            }
            if content && !deps.canContentHash && mode != .image && mode != .auto && mode != .document {
                errors.append("Content hashing requires ffmpeg (not found).")
            }
            if audio && !deps.canFingerprint {
                errors.append("Audio fingerprinting requires fpcalc (not found).")
            }
            if content && contentMethod == .ssim && !deps.canSSIM {
                errors.append(
                    "SSIM requires scikit-image (not installed). Install with: pip install \"duplicates-detector[ssim]\""
                )
            }
        }

        return errors
    }

    /// Core configuration validation.
    private var configurationErrors: [String] {
        var errors = sharedConfigurationErrors()

        if action == .moveTo && moveToDir.trimmingCharacters(in: .whitespaces).isEmpty {
            errors.append("Move To action requires a destination directory.")
        }

        if keep == .longest && (mode == .image || mode == .auto || mode == .document) {
            errors.append("Keep strategy \"longest\" is not supported in \(mode.rawValue) mode (no duration).")
        }
        if keep == .highestRes && (mode == .audio || mode == .document) {
            errors.append("Keep strategy \"highest-res\" is not supported in \(mode.rawValue) mode (no resolution).")
        }

        let trimmedLimit = limit.trimmingCharacters(in: .whitespaces)
        if !trimmedLimit.isEmpty {
            if let limitVal = Int(trimmedLimit) {
                if limitVal <= 0 { errors.append("Limit must be greater than 0.") }
            } else {
                errors.append("Limit must be a whole number.")
            }
        }

        if embedThumbnails && !Self.isValidResolution(thumbnailSize) {
            errors.append("Invalid thumbnail size (expected WxH, e.g. \"160x90\").")
        }

        return errors
    }

    private func sharedConfigurationErrors() -> [String] {
        var errors: [String] = []

        // Mode/feature compatibility
        if content && mode == .audio {
            errors.append("Content hashing is not supported in audio mode.")
        }
        if audio && mode == .image {
            errors.append("Audio fingerprinting is not supported in image mode.")
        }
        if audio && mode == .document {
            errors.append("Audio fingerprinting is not supported in document mode.")
        }
        if mode == .auto && !extensions.trimmingCharacters(in: .whitespaces).isEmpty {
            errors.append("Custom extensions are not supported in auto mode.")
        }

        // Mode-specific filter constraints
        if mode == .image {
            if !minDuration.isEmpty || !maxDuration.isEmpty {
                errors.append("Duration filters are not supported in image mode.")
            }
            if !minBitrate.isEmpty || !maxBitrate.isEmpty {
                errors.append("Bitrate filters are not supported in image mode.")
            }
        }
        if mode == .audio {
            if !minResolution.isEmpty || !maxResolution.isEmpty {
                errors.append("Resolution filters are not supported in audio mode.")
            }
        }
        if mode == .document {
            if !minDuration.isEmpty || !maxDuration.isEmpty {
                errors.append("Duration filters are not supported in document mode.")
            }
            if !minResolution.isEmpty || !maxResolution.isEmpty {
                errors.append("Resolution filters are not supported in document mode.")
            }
            if !minBitrate.isEmpty || !maxBitrate.isEmpty {
                errors.append("Bitrate filters are not supported in document mode.")
            }
            if !codec.isEmpty {
                errors.append("Codec filter is not supported in document mode.")
            }
        }

        // Weight validation
        if mode != .auto {
            if !isWeightSumValid {
                let displaySum = weightSum.isFinite ? (Int(exactly: weightSum.rounded()) ?? 0) : 0
                errors.append("Weights must sum to 100 (currently \(displaySum)).")
            }
            for key in visibleWeightKeys {
                let str = weightStrings[key] ?? ""
                if let value = Double(str) {
                    if !value.isFinite || value < 0 {
                        errors.append("Invalid weight value for \"\(key)\".")
                    }
                } else {
                    errors.append("Invalid weight value for \"\(key)\".")
                }
            }
        }

        // Min score
        let trimmedMinScore = minScore.trimmingCharacters(in: .whitespaces)
        if !trimmedMinScore.isEmpty {
            if let scoreVal = Int(trimmedMinScore) {
                if !(0...100).contains(scoreVal) { errors.append("Min score must be between 0 and 100.") }
            } else {
                errors.append("Min score must be a whole number.")
            }
        }

        // Filter field format validation
        let trimmedMinDur = minDuration.trimmingCharacters(in: .whitespaces)
        if !trimmedMinDur.isEmpty {
            if let val = Double(trimmedMinDur), val.isFinite, val >= 0 {} else {
                errors.append("Min duration must be a non-negative number (seconds).")
            }
        }
        let trimmedMaxDur = maxDuration.trimmingCharacters(in: .whitespaces)
        if !trimmedMaxDur.isEmpty {
            if let val = Double(trimmedMaxDur), val.isFinite, val >= 0 {} else {
                errors.append("Max duration must be a non-negative number (seconds).")
            }
        }
        if !Self.isValidSize(minSize) {
            errors.append("Invalid min size (expected e.g. \"500\", \"10MB\", \"1.5GB\").")
        }
        if !Self.isValidSize(maxSize) {
            errors.append("Invalid max size (expected e.g. \"500\", \"10MB\", \"1.5GB\").")
        }
        if !Self.isValidResolution(minResolution) {
            errors.append("Invalid min resolution (expected WxH, e.g. \"1920x1080\").")
        }
        if !Self.isValidResolution(maxResolution) {
            errors.append("Invalid max resolution (expected WxH, e.g. \"1920x1080\").")
        }
        if !Self.isValidBitrate(minBitrate) {
            errors.append("Invalid min bitrate (expected e.g. \"5000000\", \"5Mbps\", \"500kbps\").")
        }
        if !Self.isValidBitrate(maxBitrate) {
            errors.append("Invalid max bitrate (expected e.g. \"5000000\", \"5Mbps\", \"500kbps\").")
        }

        return errors
    }

    // MARK: - Static Validation Helpers

    // Mirrors CLI's parse_size: "500", "10MB", "1.5gb"
    // nonisolated(unsafe) because Regex is not Sendable but these are immutable constants.
    nonisolated(unsafe) private static let sizeRegex = /^\s*(\d+(?:\.\d+)?)\s*(?:b|kb|mb|gb|tb)?\s*$/
        .ignoresCase()

    static func isValidSize(_ s: String) -> Bool {
        let trimmed = s.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return true }
        return trimmed.wholeMatch(of: sizeRegex) != nil
    }

    // Mirrors CLI's parse_resolution: "1920x1080"
    nonisolated(unsafe) private static let resolutionRegex = /^\s*(\d+)\s*[xX]\s*(\d+)\s*$/

    static func isValidResolution(_ s: String) -> Bool {
        let trimmed = s.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return true }
        guard let match = trimmed.wholeMatch(of: resolutionRegex) else { return false }
        guard let w = Int(match.1), let h = Int(match.2), w > 0, h > 0 else { return false }
        return true
    }

    // Mirrors CLI's parse_bitrate: "5000000", "5Mbps", "500kbps"
    nonisolated(unsafe) private static let bitrateRegex = /^\s*(\d+(?:\.\d+)?)\s*(?:bps|kbps|mbps|gbps)?\s*$/
        .ignoresCase()

    static func isValidBitrate(_ s: String) -> Bool {
        let trimmed = s.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return true }
        return trimmed.wholeMatch(of: bitrateRegex) != nil
    }

    // MARK: - Build Config

    /// Assemble the state into a `SessionConfig` for the CLI bridge.
    func buildConfig() -> SessionConfig {
        var config = ScanConfig()

        // Source
        config.scanSource = scanSource

        // Directories (omit for Photos Library — entries may hold stale filesystem paths)
        if case .photosLibrary = scanSource {
            // Photos scans don't use filesystem directories
        } else {
            config.directories = entries.filter { !$0.isReference }.map(\.path)
            config.reference = entries.filter { $0.isReference }.map(\.path)
        }

        // Core
        config.mode = mode
        config.threshold = threshold
        config.workers = workers

        // Keep / Action
        config.keep = keep
        config.action = action
        config.actionExplicitlySet = (action != .delete)
        config.moveToDir = action == .moveTo ? Self.expandPath(moveToDir) : nil

        // Content
        config.content = content
        if content {
            let defaultMethod: ContentMethod = mode == .document ? .simhash : .phash
            config.contentMethod = contentMethod == defaultMethod ? nil : contentMethod
            config.rotationInvariant = rotationInvariant ? true : nil
        }

        // Audio
        config.audio = audio

        // Weights
        if mode != .auto && !weightStrings.isEmpty {
            let defaults = WeightDefaults.defaults(mode: mode, content: content, audio: audio)
            var weights: [String: Double] = [:]
            for key in visibleWeightKeys {
                if let value = Double(weightStrings[key] ?? ""), value.isFinite {
                    weights[key] = value
                }
            }
            if weights != defaults {
                config.weights = weights
            }
        }

        // Filters
        config.minSize = Self.nilIfEmpty(minSize)
        config.maxSize = Self.nilIfEmpty(maxSize)
        config.minDuration = Self.parseDouble(minDuration)
        config.maxDuration = Self.parseDouble(maxDuration)
        config.minResolution = Self.nilIfEmpty(minResolution)
        config.maxResolution = Self.nilIfEmpty(maxResolution)
        config.minBitrate = Self.nilIfEmpty(minBitrate)
        config.maxBitrate = Self.nilIfEmpty(maxBitrate)
        config.codec = Self.nilIfEmpty(codec)

        // Output
        config.sort = sort
        config.limit = Self.parseInt(limit)
        config.minScore = Self.parseInt(minScore)
        config.group = group
        config.verbose = verbose

        // Advanced
        config.extensions = mode == .auto ? nil : Self.nilIfEmpty(extensions)
        config.exclude = exclude
        config.noRecursive = noRecursive
        config.noMetadataCache = noMetadataCache
        config.noContentCache = noContentCache
        config.noAudioCache = noAudioCache
        config.cacheDir = Self.nilIfEmpty(cacheDir)
        config.ignoreFile = Self.expandPath(ignoreFile)
        config.log = Self.nilIfEmpty(log)
        config.embedThumbnails = embedThumbnails
        config.thumbnailSize = embedThumbnails ? Self.nilIfEmpty(thumbnailSize) : nil
        config.dryRun = dryRun

        return config
    }

    // MARK: - Profile Export

    /// Snapshot current state into a `ProfileData` for saving as a TOML profile.
    func toProfileData() -> ProfileData {
        var data = ProfileData()
        data.mode = mode.rawValue
        data.threshold = threshold
        data.keep = keep?.rawValue
        data.action = action.rawValue
        if action == .moveTo {
            data.moveToDir = moveToDir.trimmingCharacters(in: .whitespaces)
        }
        data.content = content
        data.audio = audio
        data.workers = workers
        data.sort = sort.rawValue
        if let v = Int(limit) { data.limit = v }
        if let v = Int(minScore) { data.minScore = v }
        data.group = group
        data.verbose = verbose
        data.contentMethod = contentMethod.rawValue
        data.rotationInvariant = rotationInvariant
        data.embedThumbnails = embedThumbnails
        data.noMetadataCache = noMetadataCache
        data.noContentCache = noContentCache
        data.noAudioCache = noAudioCache
        data.noRecursive = noRecursive

        data.cacheDir = Self.nilIfEmpty(cacheDir)
        data.extensions = Self.nilIfEmpty(extensions)
        data.exclude = exclude.isEmpty ? nil : exclude
        data.ignoreFile = Self.nilIfEmpty(ignoreFile)
        data.log = Self.nilIfEmpty(log)
        data.thumbnailSize = Self.nilIfEmpty(thumbnailSize)

        if let v = Double(minDuration) { data.minDuration = v }
        if let v = Double(maxDuration) { data.maxDuration = v }

        data.minSize = Self.nilIfEmpty(minSize)
        data.maxSize = Self.nilIfEmpty(maxSize)
        data.minResolution = Self.nilIfEmpty(minResolution)
        data.maxResolution = Self.nilIfEmpty(maxResolution)
        data.minBitrate = Self.nilIfEmpty(minBitrate)
        data.maxBitrate = Self.nilIfEmpty(maxBitrate)
        data.codec = Self.nilIfEmpty(codec)

        let currentWeights: [String: Double] = visibleWeightKeys.reduce(into: [:]) { result, key in
            if let str = weightStrings[key], let val = Double(str), val.isFinite {
                result[key] = val
            }
        }
        data.weights = currentWeights

        data.format = cliOnlyFormat
        data.jsonEnvelope = cliOnlyJsonEnvelope
        data.quiet = cliOnlyQuiet
        data.noColor = cliOnlyNoColor
        data.machineProgress = cliOnlyMachineProgress

        return data
    }

    // MARK: - Static Factory

    /// Create a `SetupState` hydrated from `AppDefaults`.
    static func fromDefaults() -> SetupState {
        var state = SetupState()
        applyDefaults(to: &state)
        resetWeightsToDefaults(&state)
        return state
    }

    // MARK: - Helpers (static, pure)

    static func nilIfEmpty(_ s: String) -> String? {
        let trimmed = s.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// Trim, expand `~`, return nil if empty.
    static func expandPath(_ s: String) -> String? {
        guard let trimmed = nilIfEmpty(s) else { return nil }
        return (trimmed as NSString).expandingTildeInPath
    }

    static func parseDouble(_ s: String) -> Double? {
        Double(s.trimmingCharacters(in: .whitespaces))
    }

    static func parseInt(_ s: String) -> Int? {
        Int(s.trimmingCharacters(in: .whitespaces))
    }

    /// Extension sets matching duplicates_detector/scanner.py defaults.
    static func extensionsForMode(_ mode: ScanMode) -> Set<String> {
        switch mode {
        case .video: MediaExtensions.video
        case .image: MediaExtensions.image
        case .audio: MediaExtensions.audio
        case .auto: MediaExtensions.video.union(MediaExtensions.image)
        case .document: MediaExtensions.document
        }
    }

    // MARK: - Internal helpers used by the reducer

    /// Apply stored defaults onto a state value.
    static func applyDefaults(to state: inout SetupState) {
        AppDefaults.registerDefaults()
        state.mode = AppDefaults.mode
        state.threshold = AppDefaults.threshold
        state.keep = AppDefaults.keep
        state.action = AppDefaults.action
        state.content = AppDefaults.content
        state.audio = AppDefaults.audio
        state.workers = AppDefaults.workers
        state.contentMethod = AppDefaults.contentMethod
        state.rotationInvariant = AppDefaults.rotationInvariant
        state.sort = AppDefaults.sort
        state.group = AppDefaults.group
        state.verbose = AppDefaults.verbose
        state.embedThumbnails = AppDefaults.embedThumbnails
        state.noMetadataCache = AppDefaults.noMetadataCache
        state.noContentCache = AppDefaults.noContentCache
        state.noAudioCache = AppDefaults.noAudioCache
        state.cacheDir = AppDefaults.cacheDir
        state.log = AppDefaults.log

        // Filters
        state.minSize = AppDefaults.minSize
        state.maxSize = AppDefaults.maxSize
        state.minDuration = AppDefaults.minDuration
        state.maxDuration = AppDefaults.maxDuration
        state.minResolution = AppDefaults.minResolution
        state.maxResolution = AppDefaults.maxResolution
        state.minBitrate = AppDefaults.minBitrate
        state.maxBitrate = AppDefaults.maxBitrate
        state.codec = AppDefaults.codec

        state.extensions = AppDefaults.resolvedExtensions(for: state.mode)

        let excludeStr = AppDefaults.exclude
        if !excludeStr.isEmpty {
            state.exclude = excludeStr.split(separator: ",").map {
                $0.trimmingCharacters(in: .whitespaces)
            }
        }

        normalizeIncompatibilities(&state)

        if state.action == .moveTo && state.moveToDir.isEmpty {
            state.action = .trash
        }
    }

    /// Normalize mode-incompatible toggles and keep strategies.
    static func normalizeIncompatibilities(_ state: inout SetupState) {
        switch state.mode {
        case .audio:
            state.content = false
            state.minResolution = ""; state.maxResolution = ""
        case .image:
            state.audio = false
            state.minDuration = ""; state.maxDuration = ""
            state.minBitrate = ""; state.maxBitrate = ""
        case .document:
            state.audio = false
            state.minDuration = ""; state.maxDuration = ""
            state.minResolution = ""; state.maxResolution = ""
            state.minBitrate = ""; state.maxBitrate = ""
            state.codec = ""
            if state.contentMethod == .phash || state.contentMethod == .ssim || state.contentMethod == .clip {
                state.contentMethod = .simhash
            }
        case .auto, .video: break
        }
        // Reset document-only content methods when leaving document mode
        if state.mode != .document && (state.contentMethod == .simhash || state.contentMethod == .tfidf) {
            state.contentMethod = .phash
        }
        if state.keep == .longest && (state.mode == .image || state.mode == .auto || state.mode == .document) {
            state.keep = nil
        }
        if state.keep == .highestRes && (state.mode == .audio || state.mode == .document) {
            state.keep = nil
        }
    }

    /// Reset weights to the defaults for the current mode + content + audio.
    /// Also clears any locked weights so the new configuration starts clean.
    static func resetWeightsToDefaults(_ state: inout SetupState) {
        state.lockedWeights.removeAll()
        guard let defaults = WeightDefaults.defaults(mode: state.mode, content: state.content, audio: state.audio)
        else {
            state.weightStrings = [:]
            return
        }
        var strings: [String: String] = [:]
        for (key, value) in defaults {
            strings[key] = String(Int(value))
        }
        state.weightStrings = strings
    }

    /// Reset to baseline (same state as `fromDefaults()`).
    static func resetToBaseline(_ state: inout SetupState) {
        applyDefaults(to: &state)

        // Reset per-session fields that AppDefaults doesn't track.
        state.moveToDir = ""
        state.limit = ""
        state.minScore = ""
        state.excludeInput = ""
        state.noRecursive = false
        state.ignoreFile = ""
        state.dryRun = false
        state.thumbnailSize = ""

        if AppDefaults.exclude.isEmpty { state.exclude = [] }

        state.cliOnlyFormat = nil
        state.cliOnlyJsonEnvelope = nil
        state.cliOnlyQuiet = nil
        state.cliOnlyNoColor = nil
        state.cliOnlyMachineProgress = nil

        resetWeightsToDefaults(&state)
    }
}

// MARK: - SetupReducer

/// Pure reducer for setup/configuration state transitions.
///
/// Every state mutation is driven through `reduce(state:action:)` which returns
/// the updated state plus a list of side-effect descriptors for the store to execute.
enum SetupReducer {

    /// Process a single action against the current state.
    /// Returns the new state and any effects to execute.
    static func reduce(
        state: SetupState,
        action: SetupAction
    ) -> (SetupState, [SetupEffect]) {
        var state = state
        var effects: [SetupEffect] = []

        switch action {

        // MARK: - Mode

        case .setMode(let mode):
            guard mode != state.mode else { return (state, []) }
            state.mode = mode
            SetupState.normalizeIncompatibilities(&state)
            state.extensions = AppDefaults.resolvedExtensions(for: mode)
            SetupState.resetWeightsToDefaults(&state)
            state.activePreset = nil
            effects.append(.detectPreset)
            effects.append(.updateFileCount)

        // MARK: - Threshold

        case .setThreshold(let value):
            state.threshold = value

        // MARK: - Content / Audio toggles

        case .setContent(let on):
            guard on != state.content else { return (state, []) }
            state.content = on
            if on { state.audio = false }
            SetupState.resetWeightsToDefaults(&state)
            effects.append(.detectPreset)

        case .setAudio(let on):
            guard on != state.audio else { return (state, []) }
            state.audio = on
            if on { state.content = false }
            SetupState.resetWeightsToDefaults(&state)
            effects.append(.detectPreset)

        // MARK: - Workers

        case .setWorkers(let value):
            state.workers = value

        // MARK: - Source selection

        case .setScanSource(let source):
            state.scanSource = source
            // When switching to Photos Library, disable content hashing and audio
            // fingerprinting (not applicable to Photos Library scans).
            // Force mode to .auto to match SessionReducer's hardcoded mode.
            if case .photosLibrary = source {
                state.content = false
                state.audio = false
                state.suppressPresetOnModeChange = true
                state.mode = .auto
                SetupState.resetWeightsToDefaults(&state)
            }
            effects.append(.detectPreset)

        // MARK: - Directory management

        case .addDirectory(let url):
            let resolved = url.resolvingSymlinksInPath().path
            guard !state.entries.contains(where: { $0.path == resolved }) else {
                return (state, [])
            }
            state.entries.append(DirectoryEntry(path: resolved))
            effects.append(.updateFileCount)

        case .removeDirectory(let url):
            let resolved = url.resolvingSymlinksInPath().path
            state.entries.removeAll { $0.path == resolved }
            effects.append(.updateFileCount)

        case .toggleReference(let url):
            let resolved = url.resolvingSymlinksInPath().path
            if let idx = state.entries.firstIndex(where: { $0.path == resolved }) {
                state.entries[idx].isReference.toggle()
            }

        // MARK: - Weights

        case .setWeightString(let key, let value):
            state.weightStrings[key] = value

        case .toggleLockedWeight(let key):
            if state.lockedWeights.contains(key) {
                state.lockedWeights.remove(key)
            } else {
                state.lockedWeights.insert(key)
            }

        // MARK: - Presets

        case .applyPreset(let preset):
            guard let config = PresetManager.configuration(for: state.mode, preset: preset) else {
                return (state, [])
            }
            state.content = config.content
            state.audio = config.audio
            state.threshold = config.threshold
            state.embedThumbnails = config.embedThumbnails
            state.group = config.group
            state.rotationInvariant = config.rotationInvariant
            state.contentMethod = config.contentMethod
            state.thumbnailSize = config.thumbnailSize

            var strings: [String: String] = [:]
            for (key, value) in config.weights {
                strings[key] = String(Int(value))
            }
            state.weightStrings = strings
            state.lockedWeights.removeAll()
            state.activePreset = preset

        // MARK: - Profile

        case .applyProfile(let data):
            let previousMode = state.mode
            state.suppressPresetOnModeChange = true
            SetupState.resetToBaseline(&state)

            if let v = data.mode.flatMap(ScanMode.init(rawValue:)) { state.mode = v }
            if let v = data.threshold { state.threshold = v }
            if let v = data.keep { state.keep = KeepStrategy(rawValue: v) }
            if let v = data.action.flatMap(ActionType.init(rawValue:)) { state.action = v }
            if let v = data.moveToDir { state.moveToDir = v }
            if let v = data.content { state.content = v }
            if let v = data.audio { state.audio = v }
            if let v = data.workers { state.workers = v }
            if let v = data.sort.flatMap(SortField.init(rawValue:)) { state.sort = v }
            if let v = data.limit { state.limit = String(v) }
            if let v = data.minScore { state.minScore = String(v) }
            if let v = data.group { state.group = v }
            if let v = data.verbose { state.verbose = v }
            if let v = data.embedThumbnails { state.embedThumbnails = v }
            if let v = data.contentMethod.flatMap(ContentMethod.init(rawValue:)) { state.contentMethod = v }
            if let v = data.rotationInvariant { state.rotationInvariant = v }
            if let v = data.noMetadataCache { state.noMetadataCache = v }
            if let v = data.noContentCache { state.noContentCache = v }
            if let v = data.noAudioCache { state.noAudioCache = v }
            if let v = data.noRecursive { state.noRecursive = v }
            if let v = data.cacheDir { state.cacheDir = v }
            if let v = data.extensions { state.extensions = v }
            if let v = data.exclude { state.exclude = v }
            if let v = data.ignoreFile { state.ignoreFile = v }
            if let v = data.log { state.log = v }
            if let v = data.thumbnailSize { state.thumbnailSize = v }
            if let v = data.minSize { state.minSize = v }
            if let v = data.maxSize { state.maxSize = v }
            if let v = data.minDuration { state.minDuration = String(v) }
            if let v = data.maxDuration { state.maxDuration = String(v) }
            if let v = data.minResolution { state.minResolution = v }
            if let v = data.maxResolution { state.maxResolution = v }
            if let v = data.minBitrate { state.minBitrate = v }
            if let v = data.maxBitrate { state.maxBitrate = v }
            if let v = data.codec { state.codec = v }

            if let profileWeights = data.weights {
                for (key, value) in profileWeights {
                    state.weightStrings[key] = value == value.rounded(.towardZero)
                        ? String(Int(value))
                        : String(value)
                }
            }

            // Re-normalize mode-incompatible toggles after profile fields override baseline
            SetupState.normalizeIncompatibilities(&state)

            // Reset weights to new mode defaults if mode changed and profile didn't supply weights
            if state.mode != previousMode && data.weights == nil {
                SetupState.resetWeightsToDefaults(&state)
            }

            if data.extensions == nil {
                state.extensions = AppDefaults.resolvedExtensions(for: state.mode)
            }

            if state.mode == previousMode {
                state.suppressPresetOnModeChange = false
            }

            state.cliOnlyFormat = data.format
            state.cliOnlyJsonEnvelope = data.jsonEnvelope
            state.cliOnlyQuiet = data.quiet
            state.cliOnlyNoColor = data.noColor
            state.cliOnlyMachineProgress = data.machineProgress

            effects.append(.detectPreset)
            effects.append(.updateFileCount)

        // MARK: - Reload defaults

        case .reloadDefaults:
            SetupState.applyDefaults(to: &state)
            SetupState.resetWeightsToDefaults(&state)
            effects.append(.detectPreset)
            effects.append(.updateFileCount)

        // MARK: - Filters

        case .setFilter(let field, let value):
            switch field {
            case .minSize: state.minSize = value
            case .maxSize: state.maxSize = value
            case .minDuration: state.minDuration = value
            case .maxDuration: state.maxDuration = value
            case .minResolution: state.minResolution = value
            case .maxResolution: state.maxResolution = value
            case .minBitrate: state.minBitrate = value
            case .maxBitrate: state.maxBitrate = value
            case .codec: state.codec = value
            }

        // MARK: - Keep / Action / Output

        case .setKeep(let value):
            state.keep = value

        case .setAction(let value):
            state.action = value

        case .setMoveToDir(let value):
            state.moveToDir = value

        case .setSort(let value):
            state.sort = value

        case .setGroup(let value):
            state.group = value

        case .setLimit(let value):
            state.limit = value

        case .setMinScore(let value):
            state.minScore = value

        case .setExtensions(let value):
            state.extensions = value
            effects.append(.updateFileCount)

        // MARK: - Exclude patterns

        case .addExclude(let pattern):
            let trimmed = pattern.trimmingCharacters(in: .whitespaces)
            if !trimmed.isEmpty {
                state.exclude.append(trimmed)
            }

        case .removeExclude(let index):
            guard state.exclude.indices.contains(index) else { return (state, []) }
            state.exclude.remove(at: index)

        case .setExcludeInput(let text):
            state.excludeInput = text

        // MARK: - Boolean fields

        case .setBool(let field, let value):
            switch field {
            case .noRecursive:
                state.noRecursive = value
                effects.append(.updateFileCount)
            case .noMetadataCache: state.noMetadataCache = value
            case .noContentCache: state.noContentCache = value
            case .noAudioCache: state.noAudioCache = value
            case .verbose: state.verbose = value
            case .dryRun: state.dryRun = value
            case .embedThumbnails: state.embedThumbnails = value
            case .rotationInvariant: state.rotationInvariant = value
            case .hasAppliedInitialPreset: state.hasAppliedInitialPreset = value
            case .suppressPresetOnModeChange: state.suppressPresetOnModeChange = value
            }

        // MARK: - Content hashing fields

        case .setContentMethod(let value):
            state.contentMethod = value

        case .setThumbnailSize(let value):
            state.thumbnailSize = value

        case .setCacheDir(let value):
            state.cacheDir = value

        case .setIgnoreFile(let value):
            state.ignoreFile = value

        case .setLog(let value):
            state.log = value

        // MARK: - File count

        case .fileCountUpdated(let count):
            state.estimatedFileCount = count
            state.isCountingFiles = false

        // MARK: - Dependencies

        case .setDependencyStatus(let status):
            state.dependencyStatus = status
        }

        return (state, effects)
    }
}
