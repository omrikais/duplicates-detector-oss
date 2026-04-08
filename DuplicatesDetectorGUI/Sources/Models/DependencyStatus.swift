import Foundation

/// Status of a single external tool dependency.
struct ToolStatus: Sendable, Equatable {
    var name: String
    var isAvailable: Bool
    var path: String?
    var version: String?
    var isRequired: Bool
}

/// Aggregated dependency check results.
struct DependencyStatus: Sendable, Equatable {
    var cli: ToolStatus
    var ffmpeg: ToolStatus
    var ffprobe: ToolStatus
    var fpcalc: ToolStatus
    /// Whether the CLI's Python environment has mutagen installed.
    var hasMutagen: Bool
    /// Whether the CLI's Python environment has scikit-image installed.
    var hasSkimage: Bool
    /// Whether the CLI's Python environment has pdfminer installed.
    var hasPdfminer: Bool

    /// All tools in display order.
    var allTools: [ToolStatus] {
        [cli, ffmpeg, ffprobe, fpcalc,
         ToolStatus(name: "mutagen", isAvailable: hasMutagen,
                    path: nil, version: nil, isRequired: false),
         ToolStatus(name: "scikit-image", isAvailable: hasSkimage,
                    path: nil, version: nil, isRequired: false),
         ToolStatus(name: "pdfminer", isAvailable: hasPdfminer,
                    path: nil, version: nil, isRequired: false)]
    }

    /// Whether we can scan video files (need CLI + ffprobe).
    var canScanVideo: Bool { cli.isAvailable && ffprobe.isAvailable }

    /// Whether we can scan image files (CLI only).
    var canScanImage: Bool { cli.isAvailable }

    /// Whether we can scan audio files (CLI + mutagen; ffprobe not needed).
    var canScanAudio: Bool { cli.isAvailable && hasMutagen }

    /// Whether we can use audio fingerprinting (need fpcalc).
    var canFingerprint: Bool { fpcalc.isAvailable }

    /// Whether we can use content hashing for video (need ffmpeg).
    var canContentHash: Bool { ffmpeg.isAvailable }

    /// Whether we can use SSIM content comparison (need scikit-image).
    var canSSIM: Bool { hasSkimage }

    /// Whether we can scan document files (CLI + pdfminer).
    var canScanDocument: Bool { cli.isAvailable && hasPdfminer }

    /// Minimum viable: CLI must be available.
    var meetsMinimumRequirements: Bool { cli.isAvailable }

    /// Whether any installable dependency is missing.
    var hasMissingDependencies: Bool {
        !cli.isAvailable || !ffmpeg.isAvailable || !ffprobe.isAvailable
            || !fpcalc.isAvailable || !hasMutagen || !hasSkimage
    }

    /// Whether missing tools require Homebrew to install.
    var needsBrewInstall: Bool {
        !ffmpeg.isAvailable || !ffprobe.isAvailable || !fpcalc.isAvailable
    }
}
