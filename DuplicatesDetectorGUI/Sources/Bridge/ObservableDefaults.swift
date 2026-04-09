import SwiftUI

/// An `@Observable` wrapper around `AppDefaults` that enables direct two-way
/// bindings in SwiftUI views without `@State` mirrors, `.onChange` writebacks,
/// or notification-based resyncs.
///
/// Inject via `.environment()` at the `SettingsView` level; consume in tabs
/// with `@Environment(ObservableDefaults.self) private var defaults`.
/// Use `@Bindable var defaults = defaults` at the top of `body` for `$` syntax.
@MainActor @Observable
final class ObservableDefaults {

    // MARK: - Scan settings

    var mode: ScanMode {
        get { access(keyPath: \.mode); return AppDefaults.mode }
        set { withMutation(keyPath: \.mode) { AppDefaults.mode = newValue } }
    }

    var threshold: Int {
        get { access(keyPath: \.threshold); return AppDefaults.threshold }
        set { withMutation(keyPath: \.threshold) { AppDefaults.threshold = newValue } }
    }

    var keep: KeepStrategy? {
        get { access(keyPath: \.keep); return AppDefaults.keep }
        set { withMutation(keyPath: \.keep) { AppDefaults.keep = newValue } }
    }

    var action: ActionType {
        get { access(keyPath: \.action); return AppDefaults.action }
        set { withMutation(keyPath: \.action) { AppDefaults.action = newValue } }
    }

    var content: Bool {
        get { access(keyPath: \.content); return AppDefaults.content }
        set { withMutation(keyPath: \.content) { AppDefaults.content = newValue } }
    }

    var audio: Bool {
        get { access(keyPath: \.audio); return AppDefaults.audio }
        set { withMutation(keyPath: \.audio) { AppDefaults.audio = newValue } }
    }

    var workers: Int {
        get { access(keyPath: \.workers); return AppDefaults.workers }
        set { withMutation(keyPath: \.workers) { AppDefaults.workers = newValue } }
    }

    var contentMethod: ContentMethod {
        get { access(keyPath: \.contentMethod); return AppDefaults.contentMethod }
        set { withMutation(keyPath: \.contentMethod) { AppDefaults.contentMethod = newValue } }
    }

    var rotationInvariant: Bool {
        get { access(keyPath: \.rotationInvariant); return AppDefaults.rotationInvariant }
        set { withMutation(keyPath: \.rotationInvariant) { AppDefaults.rotationInvariant = newValue } }
    }

    var sort: SortField {
        get { access(keyPath: \.sort); return AppDefaults.sort }
        set { withMutation(keyPath: \.sort) { AppDefaults.sort = newValue } }
    }

    var group: Bool {
        get { access(keyPath: \.group); return AppDefaults.group }
        set { withMutation(keyPath: \.group) { AppDefaults.group = newValue } }
    }

    var verbose: Bool {
        get { access(keyPath: \.verbose); return AppDefaults.verbose }
        set { withMutation(keyPath: \.verbose) { AppDefaults.verbose = newValue } }
    }

    var embedThumbnails: Bool {
        get { access(keyPath: \.embedThumbnails); return AppDefaults.embedThumbnails }
        set { withMutation(keyPath: \.embedThumbnails) { AppDefaults.embedThumbnails = newValue } }
    }

    // MARK: - Cache settings

    var noMetadataCache: Bool {
        get { access(keyPath: \.noMetadataCache); return AppDefaults.noMetadataCache }
        set { withMutation(keyPath: \.noMetadataCache) { AppDefaults.noMetadataCache = newValue } }
    }

    var noContentCache: Bool {
        get { access(keyPath: \.noContentCache); return AppDefaults.noContentCache }
        set { withMutation(keyPath: \.noContentCache) { AppDefaults.noContentCache = newValue } }
    }

    var noAudioCache: Bool {
        get { access(keyPath: \.noAudioCache); return AppDefaults.noAudioCache }
        set { withMutation(keyPath: \.noAudioCache) { AppDefaults.noAudioCache = newValue } }
    }

    var cacheDir: String {
        get { access(keyPath: \.cacheDir); return AppDefaults.cacheDir }
        set { withMutation(keyPath: \.cacheDir) { AppDefaults.cacheDir = newValue } }
    }

    // MARK: - Advanced settings

    var extensions: String {
        get { access(keyPath: \.extensions); return AppDefaults.extensions }
        set { withMutation(keyPath: \.extensions) { AppDefaults.extensions = newValue } }
    }

    var exclude: String {
        get { access(keyPath: \.exclude); return AppDefaults.exclude }
        set { withMutation(keyPath: \.exclude) { AppDefaults.exclude = newValue } }
    }

    var log: String {
        get { access(keyPath: \.log); return AppDefaults.log }
        set { withMutation(keyPath: \.log) { AppDefaults.log = newValue } }
    }

    var videoExtensions: String {
        get { access(keyPath: \.videoExtensions); return AppDefaults.videoExtensions }
        set { withMutation(keyPath: \.videoExtensions) { AppDefaults.videoExtensions = newValue } }
    }

    var imageExtensions: String {
        get { access(keyPath: \.imageExtensions); return AppDefaults.imageExtensions }
        set { withMutation(keyPath: \.imageExtensions) { AppDefaults.imageExtensions = newValue } }
    }

    var audioExtensions: String {
        get { access(keyPath: \.audioExtensions); return AppDefaults.audioExtensions }
        set { withMutation(keyPath: \.audioExtensions) { AppDefaults.audioExtensions = newValue } }
    }

    var documentExtensions: String {
        get { access(keyPath: \.documentExtensions); return AppDefaults.documentExtensions }
        set { withMutation(keyPath: \.documentExtensions) { AppDefaults.documentExtensions = newValue } }
    }

    // MARK: - General settings (external tools)

    var ffmpegPath: String {
        get { access(keyPath: \.ffmpegPath); return AppDefaults.ffmpegPath }
        set { withMutation(keyPath: \.ffmpegPath) { AppDefaults.ffmpegPath = newValue } }
    }

    var ffprobePath: String {
        get { access(keyPath: \.ffprobePath); return AppDefaults.ffprobePath }
        set { withMutation(keyPath: \.ffprobePath) { AppDefaults.ffprobePath = newValue } }
    }

    var confirmationPref: ConfirmationPreference {
        get { access(keyPath: \.confirmationPref); return AppDefaults.confirmationPref }
        set { withMutation(keyPath: \.confirmationPref) { AppDefaults.confirmationPref = newValue } }
    }

    // MARK: - Filters

    var minSize: String {
        get { access(keyPath: \.minSize); return AppDefaults.minSize }
        set { withMutation(keyPath: \.minSize) { AppDefaults.minSize = newValue } }
    }

    var maxSize: String {
        get { access(keyPath: \.maxSize); return AppDefaults.maxSize }
        set { withMutation(keyPath: \.maxSize) { AppDefaults.maxSize = newValue } }
    }

    var minDuration: String {
        get { access(keyPath: \.minDuration); return AppDefaults.minDuration }
        set { withMutation(keyPath: \.minDuration) { AppDefaults.minDuration = newValue } }
    }

    var maxDuration: String {
        get { access(keyPath: \.maxDuration); return AppDefaults.maxDuration }
        set { withMutation(keyPath: \.maxDuration) { AppDefaults.maxDuration = newValue } }
    }

    var minResolution: String {
        get { access(keyPath: \.minResolution); return AppDefaults.minResolution }
        set { withMutation(keyPath: \.minResolution) { AppDefaults.minResolution = newValue } }
    }

    var maxResolution: String {
        get { access(keyPath: \.maxResolution); return AppDefaults.maxResolution }
        set { withMutation(keyPath: \.maxResolution) { AppDefaults.maxResolution = newValue } }
    }

    var minBitrate: String {
        get { access(keyPath: \.minBitrate); return AppDefaults.minBitrate }
        set { withMutation(keyPath: \.minBitrate) { AppDefaults.minBitrate = newValue } }
    }

    var maxBitrate: String {
        get { access(keyPath: \.maxBitrate); return AppDefaults.maxBitrate }
        set { withMutation(keyPath: \.maxBitrate) { AppDefaults.maxBitrate = newValue } }
    }

    var codec: String {
        get { access(keyPath: \.codec); return AppDefaults.codec }
        set { withMutation(keyPath: \.codec) { AppDefaults.codec = newValue } }
    }

    // MARK: - Bulk reload

    /// Re-notify all observers after an external bulk change (e.g. import CLI config, reset all).
    /// Each `withMutation` fires without actually writing — the underlying `AppDefaults`
    /// values have already changed, so the next `get` picks up the new value.
    func reload() {
        withMutation(keyPath: \.mode) {}
        withMutation(keyPath: \.threshold) {}
        withMutation(keyPath: \.keep) {}
        withMutation(keyPath: \.action) {}
        withMutation(keyPath: \.content) {}
        withMutation(keyPath: \.audio) {}
        withMutation(keyPath: \.workers) {}
        withMutation(keyPath: \.contentMethod) {}
        withMutation(keyPath: \.rotationInvariant) {}
        withMutation(keyPath: \.sort) {}
        withMutation(keyPath: \.group) {}
        withMutation(keyPath: \.verbose) {}
        withMutation(keyPath: \.embedThumbnails) {}
        withMutation(keyPath: \.noMetadataCache) {}
        withMutation(keyPath: \.noContentCache) {}
        withMutation(keyPath: \.noAudioCache) {}
        withMutation(keyPath: \.cacheDir) {}
        withMutation(keyPath: \.extensions) {}
        withMutation(keyPath: \.exclude) {}
        withMutation(keyPath: \.log) {}
        withMutation(keyPath: \.videoExtensions) {}
        withMutation(keyPath: \.imageExtensions) {}
        withMutation(keyPath: \.audioExtensions) {}
        withMutation(keyPath: \.documentExtensions) {}
        withMutation(keyPath: \.ffmpegPath) {}
        withMutation(keyPath: \.ffprobePath) {}
        withMutation(keyPath: \.confirmationPref) {}
        withMutation(keyPath: \.minSize) {}
        withMutation(keyPath: \.maxSize) {}
        withMutation(keyPath: \.minDuration) {}
        withMutation(keyPath: \.maxDuration) {}
        withMutation(keyPath: \.minResolution) {}
        withMutation(keyPath: \.maxResolution) {}
        withMutation(keyPath: \.minBitrate) {}
        withMutation(keyPath: \.maxBitrate) {}
        withMutation(keyPath: \.codec) {}
    }
}
