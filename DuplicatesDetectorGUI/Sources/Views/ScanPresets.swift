import Foundation

/// Scan intent presets that map to exact CLI flag combinations.
///
/// Each preset configures content, audio, threshold, weights, and extras
/// on the `SetupState`. A `nil` active preset indicates "Custom" state.
enum ScanPreset: String, CaseIterable, Identifiable, Sendable {
    case quick
    case standard
    case thorough

    var id: Self { self }

    var displayName: String {
        switch self {
        case .quick: "Quick"
        case .standard: "Standard"
        case .thorough: "Thorough"
        }
    }

    var icon: String {
        switch self {
        case .quick: "hare"
        case .standard: "gauge.with.dots.needle.50percent"
        case .thorough: "magnifyingglass"
        }
    }
}

/// Concrete flag values for a preset configuration.
///
/// Every field that `buildConfig()` emits and that varies by preset
/// must be present here so that apply resets it and detect checks it.
struct PresetConfiguration: Sendable {
    let content: Bool
    let audio: Bool
    let threshold: Int
    let weights: [String: Double]
    let embedThumbnails: Bool
    let group: Bool
    let rotationInvariant: Bool

    // Advanced content-hashing fields — presets always use CLI defaults.
    let contentMethod: ContentMethod
    let thumbnailSize: String

    /// Convenience initializer — advanced fields default to CLI defaults.
    init(
        content: Bool, audio: Bool, threshold: Int,
        weights: [String: Double],
        embedThumbnails: Bool, group: Bool, rotationInvariant: Bool,
        contentMethod: ContentMethod = .phash,
        thumbnailSize: String = ""
    ) {
        self.content = content
        self.audio = audio
        self.threshold = threshold
        self.weights = weights
        self.embedThumbnails = embedThumbnails
        self.group = group
        self.rotationInvariant = rotationInvariant
        self.contentMethod = contentMethod
        self.thumbnailSize = thumbnailSize
    }
}

/// Preset lookup and application logic.
///
/// All preset tables are defined here. The view model is NOT modified —
/// only this enum knows the concrete flag mappings.
enum PresetManager {

    // MARK: - Video Presets

    private static let videoQuick = PresetConfiguration(
        content: false, audio: false, threshold: 50,
        weights: ["filename": 50, "duration": 30, "resolution": 10, "filesize": 10],
        embedThumbnails: false, group: false, rotationInvariant: false
    )

    private static let videoStandard = PresetConfiguration(
        content: true, audio: false, threshold: 50,
        weights: ["filename": 20, "duration": 20, "resolution": 10, "filesize": 10, "content": 40],
        embedThumbnails: true, group: false, rotationInvariant: false
    )

    private static let videoThorough = PresetConfiguration(
        content: true, audio: true, threshold: 30,
        weights: ["filename": 15, "duration": 15, "resolution": 10, "filesize": 10, "audio": 10, "content": 40],
        embedThumbnails: true, group: true, rotationInvariant: false
    )

    // MARK: - Image Presets

    private static let imageQuick = PresetConfiguration(
        content: false, audio: false, threshold: 50,
        weights: ["filename": 25, "resolution": 20, "filesize": 15, "exif": 40],
        embedThumbnails: false, group: false, rotationInvariant: false
    )

    private static let imageStandard = PresetConfiguration(
        content: true, audio: false, threshold: 50,
        weights: ["filename": 15, "resolution": 10, "filesize": 10, "exif": 25, "content": 40],
        embedThumbnails: true, group: false, rotationInvariant: false
    )

    private static let imageThorough = PresetConfiguration(
        content: true, audio: false, threshold: 30,
        weights: ["filename": 15, "resolution": 10, "filesize": 10, "exif": 25, "content": 40],
        embedThumbnails: true, group: true, rotationInvariant: true
    )

    // MARK: - Audio Presets

    private static let audioQuick = PresetConfiguration(
        content: false, audio: false, threshold: 50,
        weights: ["filename": 30, "duration": 30, "tags": 40],
        embedThumbnails: false, group: false, rotationInvariant: false
    )

    private static let audioStandard = PresetConfiguration(
        content: false, audio: true, threshold: 50,
        weights: ["filename": 15, "duration": 15, "tags": 20, "audio": 50],
        embedThumbnails: false, group: false, rotationInvariant: false
    )

    private static let audioThorough = PresetConfiguration(
        content: false, audio: true, threshold: 30,
        weights: ["filename": 15, "duration": 15, "tags": 20, "audio": 50],
        embedThumbnails: false, group: true, rotationInvariant: false
    )

    // MARK: - Lookup

    /// Returns the preset configuration for a given mode and preset.
    /// Returns `nil` for auto mode (presets not available).
    static func configuration(for mode: ScanMode, preset: ScanPreset) -> PresetConfiguration? {
        switch mode {
        case .video:
            switch preset {
            case .quick: videoQuick
            case .standard: videoStandard
            case .thorough: videoThorough
            }
        case .image:
            switch preset {
            case .quick: imageQuick
            case .standard: imageStandard
            case .thorough: imageThorough
            }
        case .audio:
            switch preset {
            case .quick: audioQuick
            case .standard: audioStandard
            case .thorough: audioThorough
            }
        case .auto, .document:
            nil
        }
    }

    /// Whether presets are available for the given mode.
    static func presetsAvailable(for mode: ScanMode) -> Bool {
        mode != .auto && mode != .document
    }

    // MARK: - Apply

    /// Apply a preset to the store via the reducer.
    @MainActor
    static func apply(preset: ScanPreset, mode: ScanMode, to store: SessionStore) {
        store.sendSetup(.applyPreset(preset))
    }

    // MARK: - Detect

    /// Detect which preset (if any) matches the current setup state.
    @MainActor
    static func detectPreset(for mode: ScanMode, from state: SetupState) -> ScanPreset? {
        guard presetsAvailable(for: mode) else { return nil }

        for preset in ScanPreset.allCases {
            guard let config = configuration(for: mode, preset: preset) else { continue }
            if matches(config: config, state: state) {
                return preset
            }
        }
        return nil
    }

    /// Check if a preset configuration matches the setup state.
    private static func matches(config: PresetConfiguration, state: SetupState) -> Bool {
        guard state.content == config.content,
              state.audio == config.audio,
              state.threshold == config.threshold,
              state.embedThumbnails == config.embedThumbnails,
              state.group == config.group,
              state.rotationInvariant == config.rotationInvariant
        else { return false }

        guard state.contentMethod == config.contentMethod,
              state.thumbnailSize == config.thumbnailSize
        else { return false }

        let currentWeights = state.visibleWeightKeys.reduce(into: [String: Double]()) { dict, key in
            dict[key] = Double(state.weightStrings[key] ?? "") ?? 0
        }
        return currentWeights == config.weights
    }
}
