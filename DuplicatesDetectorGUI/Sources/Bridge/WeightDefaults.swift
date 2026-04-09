import Foundation

/// Mode-specific rules for which weight keys are valid and which features are supported.
struct ModeRules: Sendable {
    /// Base weight keys always required for this mode.
    let baseKeys: [String]
    /// Weight keys that are invalid for this mode.
    let forbiddenKeys: Set<String>
    /// Whether `--content` is supported.
    let supportsContent: Bool
    /// Whether `--audio` is supported.
    let supportsAudio: Bool
}

/// Default weight tables and mode rules matching the CLI's `comparators.py`.
enum WeightDefaults {
    // MARK: - Mode rules

    static let videoRules = ModeRules(
        baseKeys: ["filename", "duration", "resolution", "filesize"],
        forbiddenKeys: ["exif", "tags"],
        supportsContent: true,
        supportsAudio: true
    )

    static let imageRules = ModeRules(
        baseKeys: ["filename", "resolution", "filesize", "exif"],
        forbiddenKeys: ["duration", "audio", "tags"],
        supportsContent: true,
        supportsAudio: false
    )

    static let audioRules = ModeRules(
        baseKeys: ["filename", "duration", "tags"],
        forbiddenKeys: ["resolution", "filesize", "exif", "content"],
        supportsContent: false,
        supportsAudio: true
    )

    static let documentRules = ModeRules(
        baseKeys: ["filename", "filesize", "page_count", "doc_meta"],
        forbiddenKeys: ["duration", "resolution", "exif", "tags", "audio"],
        supportsContent: true,
        supportsAudio: false
    )

    /// Returns the mode rules, or `nil` for auto mode (weights rejected).
    static func rules(for mode: ScanMode) -> ModeRules? {
        switch mode {
        case .video: videoRules
        case .image: imageRules
        case .audio: audioRules
        case .auto: nil
        case .document: documentRules
        }
    }

    // MARK: - Required keys

    /// Returns the required weight keys for the given mode + feature combination.
    /// Returns `nil` for auto mode (weights not applicable).
    static func requiredKeys(mode: ScanMode, content: Bool, audio: Bool) -> [String]? {
        guard let modeRules = rules(for: mode) else { return nil }
        var keys = modeRules.baseKeys
        if content && modeRules.supportsContent {
            keys.append("content")
        }
        if audio && modeRules.supportsAudio {
            keys.append("audio")
        }
        return keys
    }

    // MARK: - Default weight tables

    /// Video: filename=50, duration=30, resolution=10, filesize=10
    static let videoDefault: [String: Double] = [
        "filename": 50, "duration": 30, "resolution": 10, "filesize": 10,
    ]

    /// Video + content: filename=20, duration=20, resolution=10, filesize=10, content=40
    static let videoContent: [String: Double] = [
        "filename": 20, "duration": 20, "resolution": 10, "filesize": 10, "content": 40,
    ]

    /// Video + audio: filename=25, duration=25, resolution=10, filesize=10, audio=30
    static let videoAudio: [String: Double] = [
        "filename": 25, "duration": 25, "resolution": 10, "filesize": 10, "audio": 30,
    ]

    /// Video + content + audio: filename=15, duration=15, resolution=10, filesize=10, audio=10, content=40
    static let videoContentAudio: [String: Double] = [
        "filename": 15, "duration": 15, "resolution": 10, "filesize": 10, "audio": 10, "content": 40,
    ]

    /// Image: filename=25, resolution=20, filesize=15, exif=40
    static let imageDefault: [String: Double] = [
        "filename": 25, "resolution": 20, "filesize": 15, "exif": 40,
    ]

    /// Image + content: filename=15, resolution=10, filesize=10, exif=25, content=40
    static let imageContent: [String: Double] = [
        "filename": 15, "resolution": 10, "filesize": 10, "exif": 25, "content": 40,
    ]

    /// Audio mode: filename=30, duration=30, tags=40
    static let audioDefault: [String: Double] = [
        "filename": 30, "duration": 30, "tags": 40,
    ]

    /// Audio mode + fingerprint: filename=15, duration=15, tags=20, audio=50
    static let audioFingerprint: [String: Double] = [
        "filename": 15, "duration": 15, "tags": 20, "audio": 50,
    ]

    /// Document: filename=30, filesize=15, page_count=15, doc_meta=40
    static let documentDefault: [String: Double] = [
        "filename": 30, "filesize": 15, "page_count": 15, "doc_meta": 40,
    ]

    /// Document + content: filename=15, filesize=10, page_count=10, doc_meta=25, content=40
    static let documentContent: [String: Double] = [
        "filename": 15, "filesize": 10, "page_count": 10, "doc_meta": 25, "content": 40,
    ]

    /// Returns the default weight table for the given mode + feature combination.
    /// Returns `nil` for auto mode.
    static func defaults(mode: ScanMode, content: Bool, audio: Bool) -> [String: Double]? {
        switch mode {
        case .video:
            switch (content, audio) {
            case (false, false): videoDefault
            case (true, false): videoContent
            case (false, true): videoAudio
            case (true, true): videoContentAudio
            }
        case .image:
            content ? imageContent : imageDefault
        case .audio:
            audio ? audioFingerprint : audioDefault
        case .auto:
            nil
        case .document:
            content ? documentContent : documentDefault
        }
    }
}
