import Foundation

/// Centralized app-level persistent defaults.
///
/// All keys are namespaced with `dd.defaults.` to avoid collisions.
/// `UserDefaults.standard` is thread-safe for individual key access, so
/// this enum needs no actor isolation.
///
/// `SetupState.fromAppDefaults()` calls stored properties to hydrate setup state.
/// The Preferences window writes through the typed static properties.
public enum AppDefaults {
    // MARK: - Key constants

    private enum Key {
        static let mode = "dd.defaults.mode"
        static let threshold = "dd.defaults.threshold"
        static let keep = "dd.defaults.keep"
        static let action = "dd.defaults.action"
        static let content = "dd.defaults.content"
        static let audio = "dd.defaults.audio"
        static let workers = "dd.defaults.workers"
        static let contentMethod = "dd.defaults.contentMethod"
        static let rotationInvariant = "dd.defaults.rotationInvariant"
        static let sort = "dd.defaults.sort"
        static let group = "dd.defaults.group"
        static let verbose = "dd.defaults.verbose"
        static let embedThumbnails = "dd.defaults.embedThumbnails"
        static let noMetadataCache = "dd.defaults.noMetadataCache"
        static let noContentCache = "dd.defaults.noContentCache"
        static let noAudioCache = "dd.defaults.noAudioCache"
        static let cacheDir = "dd.defaults.cacheDir"
        static let extensions = "dd.defaults.extensions"
        static let exclude = "dd.defaults.exclude"
        static let log = "dd.defaults.log"
        static let confirmationPref = "dd.defaults.confirmationPref"
        static let ffmpegPath = "dd.defaults.ffmpegPath"
        static let ffprobePath = "dd.defaults.ffprobePath"
        static let minSize = "dd.defaults.minSize"
        static let maxSize = "dd.defaults.maxSize"
        static let minDuration = "dd.defaults.minDuration"
        static let maxDuration = "dd.defaults.maxDuration"
        static let minResolution = "dd.defaults.minResolution"
        static let maxResolution = "dd.defaults.maxResolution"
        static let minBitrate = "dd.defaults.minBitrate"
        static let maxBitrate = "dd.defaults.maxBitrate"
        static let codec = "dd.defaults.codec"
        static let hasSeenCLIConfigNotice = "dd.defaults.hasSeenCLIConfigNotice"
        static let lastActiveSessionID = "dd.defaults.lastActiveSessionID"
        static let videoExtensions = "dd.defaults.videoExtensions"
        static let imageExtensions = "dd.defaults.imageExtensions"
        static let audioExtensions = "dd.defaults.audioExtensions"
        static let documentExtensions = "dd.defaults.documentExtensions"
    }

    // MARK: - Registration

    /// Register factory defaults so `integer(forKey:)` etc. return sensible
    /// values even before the user explicitly sets anything.
    public static func registerDefaults() {
        // One-time migration: older versions used "delete" as the factory default.
        // Clear persisted "delete" so the new "trash" registered default takes effect.
        // Users who explicitly want permanent delete will re-select it.
        let migrationKey = "dd.internal.migratedActionDefault"
        if !UserDefaults.standard.bool(forKey: migrationKey) {
            if UserDefaults.standard.string(forKey: Key.action) == ActionType.delete.rawValue {
                UserDefaults.standard.removeObject(forKey: Key.action)
            }
            UserDefaults.standard.set(true, forKey: migrationKey)
        }

        UserDefaults.standard.register(defaults: [
            Key.mode: ScanMode.video.rawValue,
            Key.threshold: 50,
            Key.action: ActionType.trash.rawValue,
            Key.content: false,
            Key.audio: false,
            Key.workers: 0,
            Key.contentMethod: ContentMethod.phash.rawValue,
            Key.rotationInvariant: false,
            Key.sort: SortField.score.rawValue,
            Key.group: false,
            Key.verbose: false,
            Key.embedThumbnails: true,
            Key.noMetadataCache: false,
            Key.noContentCache: false,
            Key.noAudioCache: false,
            Key.cacheDir: "",
            Key.extensions: "",
            Key.exclude: "",
            Key.log: "",
            Key.confirmationPref: ConfirmationPreference.always.rawValue,
            Key.ffmpegPath: "",
            Key.ffprobePath: "",
            Key.minSize: "",
            Key.maxSize: "",
            Key.minDuration: "",
            Key.maxDuration: "",
            Key.minResolution: "",
            Key.maxResolution: "",
            Key.minBitrate: "",
            Key.maxBitrate: "",
            Key.codec: "",
            Key.hasSeenCLIConfigNotice: false,
            Key.videoExtensions: "",
            Key.imageExtensions: "",
            Key.audioExtensions: "",
            Key.documentExtensions: "",
        ])
    }

    // MARK: - Typed accessors

    static var mode: ScanMode {
        get { ScanMode(rawValue: UserDefaults.standard.string(forKey: Key.mode) ?? "") ?? .video }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: Key.mode) }
    }

    static var threshold: Int {
        get { UserDefaults.standard.integer(forKey: Key.threshold) }
        set { UserDefaults.standard.set(newValue, forKey: Key.threshold) }
    }

    static var keep: KeepStrategy? {
        get {
            guard let raw = UserDefaults.standard.string(forKey: Key.keep), !raw.isEmpty else { return nil }
            return KeepStrategy(rawValue: raw)
        }
        set { UserDefaults.standard.set(newValue?.rawValue ?? "", forKey: Key.keep) }
    }

    static var action: ActionType {
        get { ActionType(rawValue: UserDefaults.standard.string(forKey: Key.action) ?? "") ?? .trash }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: Key.action) }
    }

    static var content: Bool {
        get { UserDefaults.standard.bool(forKey: Key.content) }
        set { UserDefaults.standard.set(newValue, forKey: Key.content) }
    }

    static var audio: Bool {
        get { UserDefaults.standard.bool(forKey: Key.audio) }
        set { UserDefaults.standard.set(newValue, forKey: Key.audio) }
    }

    static var workers: Int {
        get { UserDefaults.standard.integer(forKey: Key.workers) }
        set { UserDefaults.standard.set(newValue, forKey: Key.workers) }
    }

    static var contentMethod: ContentMethod {
        get { ContentMethod(rawValue: UserDefaults.standard.string(forKey: Key.contentMethod) ?? "") ?? .phash }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: Key.contentMethod) }
    }

    static var rotationInvariant: Bool {
        get { UserDefaults.standard.bool(forKey: Key.rotationInvariant) }
        set { UserDefaults.standard.set(newValue, forKey: Key.rotationInvariant) }
    }

    static var sort: SortField {
        get { SortField(rawValue: UserDefaults.standard.string(forKey: Key.sort) ?? "") ?? .score }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: Key.sort) }
    }

    static var group: Bool {
        get { UserDefaults.standard.bool(forKey: Key.group) }
        set { UserDefaults.standard.set(newValue, forKey: Key.group) }
    }

    static var verbose: Bool {
        get { UserDefaults.standard.bool(forKey: Key.verbose) }
        set { UserDefaults.standard.set(newValue, forKey: Key.verbose) }
    }

    static var embedThumbnails: Bool {
        get { UserDefaults.standard.bool(forKey: Key.embedThumbnails) }
        set { UserDefaults.standard.set(newValue, forKey: Key.embedThumbnails) }
    }

    static var noMetadataCache: Bool {
        get { UserDefaults.standard.bool(forKey: Key.noMetadataCache) }
        set { UserDefaults.standard.set(newValue, forKey: Key.noMetadataCache) }
    }

    static var noContentCache: Bool {
        get { UserDefaults.standard.bool(forKey: Key.noContentCache) }
        set { UserDefaults.standard.set(newValue, forKey: Key.noContentCache) }
    }

    static var noAudioCache: Bool {
        get { UserDefaults.standard.bool(forKey: Key.noAudioCache) }
        set { UserDefaults.standard.set(newValue, forKey: Key.noAudioCache) }
    }

    static var cacheDir: String {
        get { UserDefaults.standard.string(forKey: Key.cacheDir) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.cacheDir) }
    }

    static var extensions: String {
        get { UserDefaults.standard.string(forKey: Key.extensions) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.extensions) }
    }

    static var exclude: String {
        get { UserDefaults.standard.string(forKey: Key.exclude) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.exclude) }
    }

    static var log: String {
        get { UserDefaults.standard.string(forKey: Key.log) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.log) }
    }

    static var confirmationPref: ConfirmationPreference {
        get { ConfirmationPreference(rawValue: UserDefaults.standard.string(forKey: Key.confirmationPref) ?? "") ?? .always }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: Key.confirmationPref) }
    }


    static var ffmpegPath: String {
        get { UserDefaults.standard.string(forKey: Key.ffmpegPath) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.ffmpegPath) }
    }

    static var ffprobePath: String {
        get { UserDefaults.standard.string(forKey: Key.ffprobePath) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.ffprobePath) }
    }

    static var minSize: String {
        get { UserDefaults.standard.string(forKey: Key.minSize) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.minSize) }
    }

    static var maxSize: String {
        get { UserDefaults.standard.string(forKey: Key.maxSize) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.maxSize) }
    }

    static var minDuration: String {
        get { UserDefaults.standard.string(forKey: Key.minDuration) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.minDuration) }
    }

    static var maxDuration: String {
        get { UserDefaults.standard.string(forKey: Key.maxDuration) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.maxDuration) }
    }

    static var minResolution: String {
        get { UserDefaults.standard.string(forKey: Key.minResolution) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.minResolution) }
    }

    static var maxResolution: String {
        get { UserDefaults.standard.string(forKey: Key.maxResolution) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.maxResolution) }
    }

    static var minBitrate: String {
        get { UserDefaults.standard.string(forKey: Key.minBitrate) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.minBitrate) }
    }

    static var maxBitrate: String {
        get { UserDefaults.standard.string(forKey: Key.maxBitrate) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.maxBitrate) }
    }

    static var codec: String {
        get { UserDefaults.standard.string(forKey: Key.codec) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.codec) }
    }

    static var hasSeenCLIConfigNotice: Bool {
        get { UserDefaults.standard.bool(forKey: Key.hasSeenCLIConfigNotice) }
        set { UserDefaults.standard.set(newValue, forKey: Key.hasSeenCLIConfigNotice) }
    }

    /// Session ID of the last active results session, for window restoration.
    static var lastActiveSessionID: String? {
        get { UserDefaults.standard.string(forKey: Key.lastActiveSessionID) }
        set {
            if let newValue {
                UserDefaults.standard.set(newValue, forKey: Key.lastActiveSessionID)
            } else {
                UserDefaults.standard.removeObject(forKey: Key.lastActiveSessionID)
            }
        }
    }

    static var videoExtensions: String {
        get { UserDefaults.standard.string(forKey: Key.videoExtensions) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.videoExtensions) }
    }

    static var imageExtensions: String {
        get { UserDefaults.standard.string(forKey: Key.imageExtensions) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.imageExtensions) }
    }

    static var audioExtensions: String {
        get { UserDefaults.standard.string(forKey: Key.audioExtensions) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.audioExtensions) }
    }

    static var documentExtensions: String {
        get { UserDefaults.standard.string(forKey: Key.documentExtensions) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: Key.documentExtensions) }
    }

    // MARK: - Mode helpers

    /// Resolve mode-specific extensions with global fallback.
    ///
    /// Auto mode rejects `--extensions`, so returns empty.
    static func resolvedExtensions(for mode: ScanMode) -> String {
        if mode == .auto { return "" }
        let modeExt: String = switch mode {
        case .video: videoExtensions
        case .image: imageExtensions
        case .audio: audioExtensions
        case .document: documentExtensions
        case .auto: "" // unreachable
        }
        return modeExt.isEmpty ? extensions : modeExt
    }

    /// Normalize mode-incompatible keys directly in UserDefaults.
    ///
    /// Call after changing `mode` in Preferences so stored defaults stay
    /// consistent with what `apply(to:)` would produce at scan time.
    static func normalizeStoredDefaults() {
        switch mode {
        case .audio:
            content = false
            minResolution = ""; maxResolution = ""
        case .image:
            audio = false
            minDuration = ""; maxDuration = ""
            minBitrate = ""; maxBitrate = ""
        case .document:
            audio = false
            minDuration = ""; maxDuration = ""
            minResolution = ""; maxResolution = ""
            minBitrate = ""; maxBitrate = ""
            codec = ""
            if contentMethod == .phash || contentMethod == .ssim || contentMethod == .clip {
                contentMethod = .simhash
            }
        case .auto, .video: break
        }
        // Reset document-only content methods when leaving document mode
        if mode != .document && (contentMethod == .simhash || contentMethod == .tfidf) {
            contentMethod = .phash
        }
        if keep == .longest && (mode == .image || mode == .auto || mode == .document) {
            keep = nil
        }
        if keep == .highestRes && (mode == .audio || mode == .document) {
            keep = nil
        }
    }

    // MARK: - Bulk operations

    /// Apply a ``ProfileData`` to stored defaults.
    ///
    /// Used by CLI config import to map TOML fields → `AppDefaults`.
    static func apply(from data: ProfileData) {
        if let v = data.mode.flatMap(ScanMode.init(rawValue:)) { mode = v }
        if let v = data.threshold { threshold = v }
        if let v = data.keep { keep = KeepStrategy(rawValue: v) }
        if let v = data.action.flatMap(ActionType.init(rawValue:)) {
            // moveTo requires a per-session destination that AppDefaults
            // can't persist — fall back to trash (non-destructive).
            action = v == .moveTo ? .trash : v
        }
        if let v = data.content { content = v }
        if let v = data.audio { self.audio = v }
        if let v = data.workers { workers = v }
        if let v = data.contentMethod.flatMap(ContentMethod.init(rawValue:)) { contentMethod = v }
        if let v = data.rotationInvariant { rotationInvariant = v }
        if let v = data.sort.flatMap(SortField.init(rawValue:)) { sort = v }
        if let v = data.group { group = v }
        if let v = data.verbose { verbose = v }
        if let v = data.embedThumbnails { embedThumbnails = v }
        if let v = data.noMetadataCache { noMetadataCache = v }
        if let v = data.noContentCache { noContentCache = v }
        if let v = data.noAudioCache { noAudioCache = v }
        if let v = data.cacheDir { cacheDir = v }
        if let v = data.extensions { extensions = v }
        if let v = data.exclude { exclude = v.joined(separator: ", ") }
        if let v = data.log { log = v }
        if let v = data.minSize { minSize = v }
        if let v = data.maxSize { maxSize = v }
        if let v = data.minDuration { minDuration = String(v) }
        if let v = data.maxDuration { maxDuration = String(v) }
        if let v = data.minResolution { minResolution = v }
        if let v = data.maxResolution { maxResolution = v }
        if let v = data.minBitrate { minBitrate = v }
        if let v = data.maxBitrate { maxBitrate = v }
        if let v = data.codec { codec = v }
    }

    // MARK: - Key management

    /// Keys that affect scan configuration (used for "has user customized?" checks).
    /// GUI-only preferences (ffmpegPath, ffprobePath, confirmationPref,
    /// hasSeenCLIConfigNotice) are excluded — they don't
    /// affect scan behavior and shouldn't prevent the Quick preset from being
    /// applied on first open.
    private static let scanRelevantKeys: [String] = [
        Key.mode, Key.threshold, Key.keep, Key.action,
        Key.content, Key.audio, Key.workers,
        Key.contentMethod, Key.rotationInvariant,
        Key.sort, Key.group, Key.verbose, Key.embedThumbnails,
        Key.noMetadataCache, Key.noContentCache, Key.noAudioCache,
        Key.cacheDir, Key.extensions, Key.exclude, Key.log,
        Key.minSize, Key.maxSize, Key.minDuration, Key.maxDuration,
        Key.minResolution, Key.maxResolution, Key.minBitrate, Key.maxBitrate, Key.codec,
        Key.videoExtensions, Key.imageExtensions, Key.audioExtensions, Key.documentExtensions,
    ]

    /// GUI-only keys that are not part of scan configuration.
    private static let guiOnlyKeys: [String] = [
        Key.confirmationPref,
        Key.ffmpegPath, Key.ffprobePath,
        Key.hasSeenCLIConfigNotice,
    ]

    /// Whether the user has explicitly customized any scan-relevant default.
    ///
    /// Returns `false` on a fresh install where only registered defaults exist.
    /// Uses `persistentDomain(forName:)` to inspect only the application domain,
    /// excluding the registration domain populated by `registerDefaults()`.
    static var hasAnyExplicitDefaults: Bool {
        guard let bundleID = Bundle.main.bundleIdentifier,
              let domain = UserDefaults.standard.persistentDomain(forName: bundleID)
        else { return false }
        return scanRelevantKeys.contains { domain[$0] != nil }
    }

    /// Clear all `dd.defaults.*` keys back to registered defaults.
    static func resetAll() {
        for key in scanRelevantKeys + guiOnlyKeys {
            UserDefaults.standard.removeObject(forKey: key)
        }
    }
}

// MARK: - ConfirmationPreference

/// How aggressively to confirm destructive actions.
enum ConfirmationPreference: String, CaseIterable, Sendable {
    case always
    case highRiskOnly = "high-risk-only"
    case never
}
