import AppIntents

/// App Intent enum representing the scan mode.
///
/// Maps to the CLI's `--mode` flag. Excludes `.document` which is not
/// supported by the CLI.
enum ScanModeEntity: String, AppEnum {
    case video, image, audio, auto

    nonisolated(unsafe) static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Scan Mode")
    nonisolated(unsafe) static var caseDisplayRepresentations: [ScanModeEntity: DisplayRepresentation] = [
        .video: "Video",
        .image: "Image",
        .audio: "Audio",
        .auto: "Auto",
    ]

    /// Convert to the internal `ScanMode` used by `ScanConfig`.
    var toScanMode: ScanMode {
        switch self {
        case .video: .video
        case .image: .image
        case .audio: .audio
        case .auto: .auto
        }
    }
}
