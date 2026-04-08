import AppIntents
import Foundation

/// Shortcuts intent that scans a directory for duplicate files.
///
/// Opens the app in the foreground to avoid background execution timeouts.
/// Builds a `ScanConfig`, runs the scan via `CLIBridge`, and returns a
/// `ScanSummaryEntity` with the results.
struct ScanDirectoryIntent: ForegroundContinuableIntent {
    nonisolated(unsafe) static var title: LocalizedStringResource = "Scan Directory for Duplicates"
    nonisolated(unsafe) static var description = IntentDescription(
        "Scan a directory for duplicate video, image, or audio files.",
        categoryName: "Scanning"
    )

    @Parameter(title: "Directory")
    var directory: IntentFile

    @Parameter(title: "Mode", default: .video)
    var mode: ScanModeEntity

    @Parameter(title: "Threshold", default: 50, controlStyle: .stepper, inclusiveRange: (0, 100))
    var threshold: Int

    @Parameter(title: "Content Hash", default: false)
    var contentHash: Bool

    func perform() async throws -> some ReturnsValue<ScanSummaryEntity> {
        guard let url = directory.fileURL else {
            throw IntentError.directoryNotAccessible
        }

        // Acquire security-scoped access for sandboxed apps.
        let accessing = url.startAccessingSecurityScopedResource()
        defer {
            if accessing { url.stopAccessingSecurityScopedResource() }
        }

        // Validate it's actually a directory.
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir),
              isDir.boolValue else {
            throw IntentError.notADirectory
        }

        // Build the scan config.
        var config = ScanConfig()
        config.directories = [url.path]
        config.mode = mode.toScanMode
        config.threshold = threshold
        // CLI rejects --mode audio --content; silently clear to prevent runtime failure.
        config.content = contentHash && config.mode != .audio

        // Run the scan through CLIBridge.
        let bridge = CLIBridge()
        let stream = await bridge.runScan(config: config)

        var envelope: ScanEnvelope?
        var rawEnvelopeData: Data?
        for try await output in stream {
            switch output {
            case .progress:
                // Progress events are consumed by the GUI; ignore in shortcut context.
                break
            case .result(let scanEnvelope, let data):
                envelope = scanEnvelope
                rawEnvelopeData = data
            }
        }

        guard let envelope else {
            throw IntentError.scanFailed
        }

        let pairCount: Int
        let topScore: Double
        switch envelope.content {
        case .pairs(let pairs):
            pairCount = pairs.count
            topScore = pairs.first?.score ?? 0
        case .groups(let groups):
            pairCount = groups.reduce(0) { $0 + $1.pairs.count }
            topScore = groups.flatMap(\.pairs).map(\.score).max() ?? 0
        }

        // Persist the scan to session history so other intents can find it.
        if let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() {
            let dirName = (url.path as NSString).lastPathComponent
            let persisted = PersistedSession(
                id: UUID(),
                config: config,
                results: PersistedResults(
                    envelope: envelope,
                    resolutions: [:],
                    ignoredPairs: [],
                    actionHistory: [],
                    pendingWatchPairs: []
                ),
                metadata: SessionMetadata(
                    directories: config.directories,
                    sourceLabel: dirName,
                    mode: config.mode,
                    pairCount: pairCount,
                    fileCount: envelope.stats.filesScanned,
                    filesScanned: envelope.stats.filesScanned,
                    spaceRecoverable: envelope.stats.spaceRecoverable,
                    groupsCount: envelope.stats.groupsCount
                ),
                watchConfig: nil
            )
            try? await registry.saveSession(persisted, envelopeData: rawEnvelopeData)
        }

        let summary = ScanSummaryEntity(
            pairCount: pairCount,
            filesScanned: envelope.stats.filesScanned,
            topScore: topScore,
            scanDuration: envelope.stats.totalTime
        )

        return .result(value: summary)
    }
}

// MARK: - Errors

/// Errors specific to App Intent execution.
enum IntentError: Swift.Error, CustomLocalizedStringResourceConvertible {
    case directoryNotAccessible
    case notADirectory
    case scanFailed
    case noScanHistory

    var localizedStringResource: LocalizedStringResource {
        switch self {
        case .directoryNotAccessible:
            "The selected directory is not accessible."
        case .notADirectory:
            "The selected path is not a directory."
        case .scanFailed:
            "The scan failed to produce results."
        case .noScanHistory:
            "No scan history found. Run a scan first."
        }
    }
}
