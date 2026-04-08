#if DEBUG
import Foundation

@MainActor
enum PreviewFixtures {
    static let sampleDirectoryEntries = [
        DirectoryEntry(path: "/Users/demo/Videos"),
        DirectoryEntry(path: "/Volumes/Backup/Videos", isReference: true),
    ]

    /// SessionStore configured for the setup phase with sample directories.
    static func sessionStore() -> SessionStore {
        let bridge = CLIBridge()
        let store = SessionStore(bridge: bridge)
        for entry in sampleDirectoryEntries {
            store.sendSetup(.addDirectory(URL(filePath: entry.path)))
            if entry.isReference {
                store.sendSetup(.toggleReference(URL(filePath: entry.path)))
            }
        }
        return store
    }

    /// SessionStore with no directories (empty setup).
    static func emptySessionStore() -> SessionStore {
        let bridge = CLIBridge()
        return SessionStore(bridge: bridge)
    }

    /// SessionStore configured for image mode weights preview.
    static func imageWeightsSessionStore() -> SessionStore {
        let bridge = CLIBridge()
        let store = SessionStore(bridge: bridge)
        store.sendSetup(.setMode(.image))
        return store
    }

    /// Create a ScanProgress value pre-loaded with mid-scan progress for previews.
    static func scanProgress(pauseState: PauseState = .running) -> ScanProgress {
        var scan = ScanProgress()
        scan.pause = pauseState
        scan.stages = ScanProgress.initialStages(
            mode: .video, content: true, audio: false,
            embedThumbnails: true, hasFilters: true
        )
        // Simulate scan + extract + filter completed, content_hash in progress
        scan.stages[0].status = .completed(elapsed: 0.8, total: 120, extras: [:])
        scan.stages[1].status = .completed(elapsed: 3.2, total: 120, extras: [:])
        scan.stages[2].status = .completed(elapsed: 0.1, total: 98, extras: [:])
        scan.stages[3].status = .active(current: 42, total: 98)
        scan.stages[3].currentFile = "/Users/demo/Videos/vacation_2024.mp4"
        scan.timing.overallStartTime = Date().addingTimeInterval(-5.0)
        return scan
    }

    /// Create a SessionStore pre-loaded with progress state for previews.
    static func progressSessionStore(pauseState: PauseState = .running) -> SessionStore {
        let bridge = CLIBridge()
        let store = SessionStore(bridge: bridge)
        for entry in sampleDirectoryEntries {
            store.sendSetup(.addDirectory(URL(filePath: entry.path)))
            if entry.isReference {
                store.sendSetup(.toggleReference(URL(filePath: entry.path)))
            }
        }
        let scan = scanProgress(pauseState: pauseState)
        store.send(._injectPreviewState(scan: scan, config: ScanConfig()))
        return store
    }

    static func allAvailableDependencyStatus() -> DependencyStatus {
        DependencyStatus(
            cli: ToolStatus(
                name: "duplicates-detector",
                isAvailable: true,
                path: "/usr/local/bin/duplicates-detector",
                version: "1.5.0",
                isRequired: true
            ),
            ffmpeg: ToolStatus(
                name: "ffmpeg",
                isAvailable: true,
                path: "/opt/homebrew/bin/ffmpeg",
                version: "7.1",
                isRequired: false
            ),
            ffprobe: ToolStatus(
                name: "ffprobe",
                isAvailable: true,
                path: "/opt/homebrew/bin/ffprobe",
                version: "7.1",
                isRequired: false
            ),
            fpcalc: ToolStatus(
                name: "fpcalc",
                isAvailable: true,
                path: "/opt/homebrew/bin/fpcalc",
                version: "1.5.1",
                isRequired: false
            ),
            hasMutagen: true,
            hasSkimage: true,
            hasPdfminer: true
        )
    }

    static func missingCLIDependencyStatus() -> DependencyStatus {
        DependencyStatus(
            cli: ToolStatus(
                name: "duplicates-detector",
                isAvailable: false,
                path: nil,
                version: nil,
                isRequired: true
            ),
            ffmpeg: ToolStatus(
                name: "ffmpeg",
                isAvailable: true,
                path: "/opt/homebrew/bin/ffmpeg",
                version: "7.1",
                isRequired: false
            ),
            ffprobe: ToolStatus(
                name: "ffprobe",
                isAvailable: true,
                path: "/opt/homebrew/bin/ffprobe",
                version: "7.1",
                isRequired: false
            ),
            fpcalc: ToolStatus(
                name: "fpcalc",
                isAvailable: false,
                path: nil,
                version: nil,
                isRequired: false
            ),
            hasMutagen: false,
            hasSkimage: false,
            hasPdfminer: false
        )
    }

    static func appState() -> AppState {
        AppState()
    }

    static func partiallyMissingDependencyStatus() -> DependencyStatus {
        DependencyStatus(
            cli: ToolStatus(
                name: "duplicates-detector",
                isAvailable: true,
                path: "/usr/local/bin/duplicates-detector",
                version: "1.5.0",
                isRequired: true
            ),
            ffmpeg: ToolStatus(
                name: "ffmpeg",
                isAvailable: false,
                path: nil,
                version: nil,
                isRequired: false
            ),
            ffprobe: ToolStatus(
                name: "ffprobe",
                isAvailable: false,
                path: nil,
                version: nil,
                isRequired: false
            ),
            fpcalc: ToolStatus(
                name: "fpcalc",
                isAvailable: false,
                path: nil,
                version: nil,
                isRequired: false
            ),
            hasMutagen: false,
            hasSkimage: false,
            hasPdfminer: false
        )
    }

    // Minimal 8×6 PNG thumbnails for preview rendering
    private static let thumbnailA = "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAEUlEQVR4nGMICEjBihgGUgIARegwwWN1S5IAAAAASUVORK5CYII="
    private static let thumbnailB = "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAEUlEQVR4nGNICQjAihgGUgIATWgwwSo2PrkAAAAASUVORK5CYII="

    // MARK: - Ignore List Fixtures

    static func ignoreListPairs() -> [[String]] {
        [
            ["/Users/demo/Videos/clip.mp4", "/Users/demo/Videos/clip_copy.mp4"],
            ["/Users/demo/Photos/IMG_1234.heic", "/Volumes/Backup/Photos/IMG_1234.heic"],
            ["/Users/demo/Music/track.mp3", "/Users/demo/Music/track (1).mp3"],
        ]
    }

    // MARK: - Scan History Fixtures

    nonisolated static func scanHistoryEntries() -> [ScanHistoryEntry] {
        [
            ScanHistoryEntry(
                id: UUID(),
                date: Date().addingTimeInterval(-3600),
                directories: ["/Users/demo/Videos"],
                mode: "video",
                pairCount: 15,
                groupCount: nil,
                duration: 5.6,
                fileCount: 120,
                envelopeFilename: "2026-03-15T11-26-12Z-video.ddscan"
            ),
            ScanHistoryEntry(
                id: UUID(),
                date: Date().addingTimeInterval(-86400),
                directories: ["/Users/demo/Photos", "/Volumes/Backup/Photos"],
                mode: "image",
                pairCount: 42,
                groupCount: 8,
                duration: 12.3,
                fileCount: 500,
                envelopeFilename: "2026-03-14T10-00-00Z-image.ddscan"
            ),
        ]
    }

    // MARK: - Static Sample Data (store-independent)

    /// Sample pair results for previews that don't need a full store.
    static var samplePairResults: [PairResult] {
        let metadataA = FileMetadata(
            duration: 125.3, width: 1920, height: 1080, fileSize: 52_400_000,
            codec: "h264", bitrate: 5_000_000, framerate: 29.97, audioChannels: 2,
            mtime: Date().timeIntervalSince1970, thumbnail: thumbnailA
        )
        let metadataB = FileMetadata(
            duration: 124.8, width: 3840, height: 2160, fileSize: 98_200_000,
            codec: "hevc", bitrate: 12_800_000, framerate: 29.97, audioChannels: 6,
            mtime: Date().timeIntervalSince1970 - 86400, thumbnail: thumbnailB
        )
        return [
            PairResult(
                fileA: "/Users/demo/Videos/vacation_2024.mp4",
                fileB: "/Users/demo/Videos/vacation_2024_copy.mp4",
                score: 95.5,
                breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
                detail: [
                    "filename": DetailScore(raw: 0.96, weight: 50),
                    "duration": DetailScore(raw: 0.98, weight: 30),
                    "resolution": DetailScore(raw: 1.0, weight: 10),
                    "fileSize": DetailScore(raw: 0.8, weight: 10),
                ],
                fileAMetadata: metadataA, fileBMetadata: metadataB,
                fileAIsReference: false, fileBIsReference: false, keep: "a"
            ),
            PairResult(
                fileA: "/Users/demo/Videos/birthday_party.mp4",
                fileB: "/Volumes/Backup/Videos/bday.mp4",
                score: 72.3,
                breakdown: ["filename": 15.0, "duration": 28.0, "resolution": 10.0, "fileSize": 9.3],
                detail: [
                    "filename": DetailScore(raw: 0.30, weight: 50),
                    "duration": DetailScore(raw: 0.93, weight: 30),
                    "resolution": DetailScore(raw: 1.0, weight: 10),
                    "fileSize": DetailScore(raw: 0.93, weight: 10),
                ],
                fileAMetadata: metadataA, fileBMetadata: metadataB,
                fileAIsReference: false, fileBIsReference: true, keep: nil
            ),
        ]
    }

    /// Sample group results for previews that don't need a full store.
    static var sampleGroupResults: [GroupResult] {
        [
            GroupResult(
                groupId: 1, fileCount: 3, maxScore: 95.5, minScore: 72.3, avgScore: 83.9,
                files: [
                    GroupFile(path: "/Users/demo/Videos/vacation_2024.mp4",
                             duration: 125.3, width: 1920, height: 1080, fileSize: 52_400_000,
                             codec: "h264", bitrate: 5_000_000, framerate: 29.97, audioChannels: 2,
                             mtime: Date().timeIntervalSince1970, isReference: false, thumbnail: thumbnailA),
                    GroupFile(path: "/Users/demo/Videos/vacation_2024_copy.mp4",
                             duration: 124.8, width: 3840, height: 2160, fileSize: 98_200_000,
                             codec: "hevc", bitrate: 12_800_000, framerate: 29.97, audioChannels: 6,
                             mtime: Date().timeIntervalSince1970 - 86400, isReference: false, thumbnail: thumbnailB),
                ],
                pairs: [
                    GroupPair(fileA: "/Users/demo/Videos/vacation_2024.mp4",
                              fileB: "/Users/demo/Videos/vacation_2024_copy.mp4",
                              score: 95.5,
                              breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
                              detail: ["filename": DetailScore(raw: 0.96, weight: 50),
                                       "duration": DetailScore(raw: 0.98, weight: 30),
                                       "resolution": DetailScore(raw: 1.0, weight: 10),
                                       "fileSize": DetailScore(raw: 0.8, weight: 10)]),
                ],
                keep: "/Users/demo/Videos/vacation_2024.mp4"
            ),
            GroupResult(
                groupId: 2, fileCount: 2, maxScore: 88.0, minScore: 88.0, avgScore: 88.0,
                files: [
                    GroupFile(path: "/Users/demo/Videos/birthday_party.mp4",
                             duration: 300.0, width: 1920, height: 1080, fileSize: 120_000_000,
                             codec: "h264", bitrate: 3_200_000, framerate: 30.0, audioChannels: 2,
                             mtime: Date().timeIntervalSince1970, isReference: false, thumbnail: thumbnailB),
                    GroupFile(path: "/Volumes/Backup/Videos/bday.mp4",
                             duration: 300.0, width: 1920, height: 1080, fileSize: 115_000_000,
                             codec: "h264", bitrate: 3_000_000, framerate: 30.0, audioChannels: 2,
                             mtime: Date().timeIntervalSince1970 - 604800, isReference: false, thumbnail: thumbnailA),
                ],
                pairs: [
                    GroupPair(fileA: "/Users/demo/Videos/birthday_party.mp4",
                              fileB: "/Volumes/Backup/Videos/bday.mp4",
                              score: 88.0,
                              breakdown: ["filename": 20.0, "duration": 30.0, "resolution": 10.0, "fileSize": 9.0],
                              detail: ["filename": DetailScore(raw: 0.40, weight: 50),
                                       "duration": DetailScore(raw: 1.0, weight: 30),
                                       "resolution": DetailScore(raw: 1.0, weight: 10),
                                       "fileSize": DetailScore(raw: 0.9, weight: 10)]),
                ],
                keep: nil
            ),
        ]
    }
}
#endif
