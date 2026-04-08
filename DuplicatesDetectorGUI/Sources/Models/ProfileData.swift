import Foundation

/// Transfer type carrying CLI-compatible profile fields.
///
/// All properties are optional — `nil` means "not set in this profile".
/// Key names match the CLI's ``config.py`` `DEFAULTS` dict (snake_case) for
/// direct TOML round-trip compatibility.
struct ProfileData: Sendable, Equatable {
    var mode: String?
    var threshold: Int?
    var keep: String?
    var action: String?
    var moveToDir: String?
    var content: Bool?
    var audio: Bool?
    var workers: Int?
    var sort: String?
    var group: Bool?
    var verbose: Bool?
    var embedThumbnails: Bool?
    var contentMethod: String?
    var rotationInvariant: Bool?
    var noMetadataCache: Bool?
    var noContentCache: Bool?
    var noAudioCache: Bool?
    var noRecursive: Bool?
    var cacheDir: String?
    var extensions: String?
    var exclude: [String]?
    var ignoreFile: String?
    var log: String?
    var thumbnailSize: String?
    var weights: [String: Double]?
    var minSize: String?
    var maxSize: String?
    var minDuration: Double?
    var maxDuration: Double?
    var minResolution: String?
    var maxResolution: String?
    var minBitrate: String?
    var maxBitrate: String?
    var codec: String?
    var limit: Int?
    var minScore: Int?

    // CLI-only fields — not exposed in the GUI edit sheet, but round-tripped
    // so that saving a profile from the GUI doesn't silently drop them.
    var format: String?
    var jsonEnvelope: Bool?
    var quiet: Bool?
    var noColor: Bool?
    var machineProgress: Bool?

    /// True when no defaults-importable field is set.
    ///
    /// Used by `importCLIConfig()` to guard against a destructive
    /// `AppDefaults.resetAll()` when nothing useful would be re-applied.
    /// Excludes CLI-only display fields AND per-session fields that
    /// `applyProfileDataToDefaults` does not persist to `AppDefaults`.
    var isEmpty: Bool {
        var copy = self
        // CLI-only display fields
        copy.format = nil
        copy.jsonEnvelope = nil
        copy.quiet = nil
        copy.noColor = nil
        copy.machineProgress = nil
        // Per-session fields with no AppDefaults backing
        copy.moveToDir = nil
        copy.thumbnailSize = nil
        copy.noRecursive = nil
        copy.ignoreFile = nil
        copy.weights = nil
        copy.limit = nil
        copy.minScore = nil
        return copy == ProfileData()
    }

    /// Merge non-nil fields from `source`, preserving fields that `source` doesn't set.
    ///
    /// `keep` and `extensions` are always assigned (nil clears the key).
    /// `weights` are always cleared (AppDefaults doesn't track them, and
    /// existing values may be incompatible with the exported mode/content/audio flags).
    /// Filter fields always overwrite so cleared GUI defaults remove stale values.
    mutating func merge(from source: ProfileData) {
        if let v = source.mode { mode = v }
        if let v = source.threshold { threshold = v }
        // Always assign keep — nil means "clear the strategy".
        keep = source.keep
        if let v = source.action { action = v }
        // Always assign content/audio — nil clears the key
        // (mode normalization sets these to nil for incompatible modes).
        content = source.content
        audio = source.audio
        if let v = source.workers { workers = v }
        if let v = source.sort { sort = v }
        if let v = source.group { group = v }
        if let v = source.verbose { verbose = v }
        if let v = source.embedThumbnails { embedThumbnails = v }
        if let v = source.contentMethod { contentMethod = v }
        if let v = source.rotationInvariant { rotationInvariant = v }
        if let v = source.noMetadataCache { noMetadataCache = v }
        if let v = source.noContentCache { noContentCache = v }
        if let v = source.noAudioCache { noAudioCache = v }
        if let v = source.cacheDir { cacheDir = v }
        // Always assign extensions — nil means "clear the key" (auto mode
        // rejects --extensions, so the export must remove stale values).
        extensions = source.extensions
        if let v = source.exclude { exclude = v }
        if let v = source.log { log = v }
        // Filter fields: always overwrite so cleared values propagate.
        minSize = source.minSize
        maxSize = source.maxSize
        minDuration = source.minDuration
        maxDuration = source.maxDuration
        minResolution = source.minResolution
        maxResolution = source.maxResolution
        minBitrate = source.minBitrate
        maxBitrate = source.maxBitrate
        codec = source.codec
        // Always clear weights — AppDefaults doesn't track them.
        weights = nil
    }

    /// Construct a `ProfileData` from current `AppDefaults` values.
    ///
    /// This is a pure data-conversion function that reads `AppDefaults`
    /// static properties and returns a populated `ProfileData` suitable
    /// for export to CLI config or profile round-tripping.
    static func fromAppDefaults() -> ProfileData {
        var data = ProfileData()
        let mode = AppDefaults.mode

        // Build the data with raw AppDefaults values; normalization happens
        // at the end via normalizeModeIncompatibilities().
        data.mode = mode.rawValue
        data.threshold = AppDefaults.threshold
        data.keep = AppDefaults.keep?.rawValue
        data.action = (AppDefaults.action == .moveTo ? ActionType.delete : AppDefaults.action).rawValue
        data.content = AppDefaults.content
        data.audio = AppDefaults.audio
        data.workers = AppDefaults.workers
        data.contentMethod = AppDefaults.contentMethod.rawValue
        data.rotationInvariant = AppDefaults.rotationInvariant
        data.sort = AppDefaults.sort.rawValue
        data.group = AppDefaults.group
        data.verbose = AppDefaults.verbose
        // embed_thumbnails is intentionally omitted: the GUI always emits
        // --embed-thumbnails --json-envelope --format json via FlagAssembler,
        // so this AppDefault is GUI-internal. Exporting it without the
        // companion json_envelope/format keys produces a broken CLI config.
        data.noMetadataCache = AppDefaults.noMetadataCache
        data.noContentCache = AppDefaults.noContentCache
        data.noAudioCache = AppDefaults.noAudioCache
        // Always include tracked string fields so export can clear stale
        // keys from an existing config.toml when the user clears them.
        data.cacheDir = AppDefaults.cacheDir
        // Resolve mode-specific -> global fallback so the CLI config gets
        // the effective extensions. Auto mode rejects --extensions, so skip
        // entirely (data.extensions stays nil, normalization clears it).
        if mode != .auto {
            data.extensions = AppDefaults.resolvedExtensions(for: mode)
        }
        let excludeStr = AppDefaults.exclude
        data.exclude = excludeStr.isEmpty ? [] : excludeStr.split(separator: ",").map {
            $0.trimmingCharacters(in: .whitespaces)
        }
        data.log = AppDefaults.log
        // Filter defaults — skip mode-incompatible filters (matches CLI validation)
        let ms = AppDefaults.minSize; if !ms.isEmpty { data.minSize = ms }
        let xs = AppDefaults.maxSize; if !xs.isEmpty { data.maxSize = xs }
        if mode != .image {
            let mdu = AppDefaults.minDuration; if !mdu.isEmpty { data.minDuration = Double(mdu) }
            let xdu = AppDefaults.maxDuration; if !xdu.isEmpty { data.maxDuration = Double(xdu) }
        }
        if mode != .audio {
            let mr = AppDefaults.minResolution; if !mr.isEmpty { data.minResolution = mr }
            let xr = AppDefaults.maxResolution; if !xr.isEmpty { data.maxResolution = xr }
        }
        if mode != .image {
            let mb = AppDefaults.minBitrate; if !mb.isEmpty { data.minBitrate = mb }
            let xb = AppDefaults.maxBitrate; if !xb.isEmpty { data.maxBitrate = xb }
        }
        let co = AppDefaults.codec; if !co.isEmpty { data.codec = co }
        data.normalizeModeIncompatibilities()
        return data
    }

    /// Normalize mode-incompatible fields on this ``ProfileData``.
    ///
    /// Mirrors the typed normalization in ``AppDefaults/normalizeModeIncompatibilities(on:)``
    /// but operates on the string-typed TOML representation.
    mutating func normalizeModeIncompatibilities() {
        switch mode {
        case ScanMode.image.rawValue:
            audio = nil
            minDuration = nil; maxDuration = nil
            minBitrate = nil; maxBitrate = nil
        case ScanMode.audio.rawValue:
            content = nil
            minResolution = nil; maxResolution = nil
        case ScanMode.document.rawValue:
            audio = nil
            minDuration = nil; maxDuration = nil
            minResolution = nil; maxResolution = nil
            minBitrate = nil; maxBitrate = nil
            codec = nil
        case ScanMode.auto.rawValue:
            extensions = nil
        default: break
        }
        if let keep {
            if keep == KeepStrategy.longest.rawValue && (mode == ScanMode.image.rawValue || mode == ScanMode.auto.rawValue || mode == ScanMode.document.rawValue) {
                self.keep = nil
            }
            if keep == KeepStrategy.highestRes.rawValue && (mode == ScanMode.audio.rawValue || mode == ScanMode.document.rawValue) {
                self.keep = nil
            }
        }
    }
}
