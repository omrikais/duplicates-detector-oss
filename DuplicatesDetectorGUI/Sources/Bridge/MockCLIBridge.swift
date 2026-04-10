#if DEBUG
import Foundation
import Subprocess

/// Mock CLI bridge for UI testing. Returns canned data based on the scenario name.
///
/// Controlled by the `DD_UI_TEST_SCENARIO` environment variable:
/// - `"pairs"`: Returns a canned envelope with 3 pairs, emits progress events
/// - `"slow-pairs"`: Like "pairs" but with longer delays so cancel can be observed
/// - `"groups"`: Returns a canned envelope with 2 groups
/// - `"marketing-image"`: Returns a canned envelope with 4 image pairs using real demo photos
/// - `"marketing-video"`: Returns a canned envelope with 5 video pairs using real demo videos
/// - `"empty"`: Returns an envelope with 0 pairs
/// - `"error"`: Throws a simulated CLI error during scan
actor MockCLIBridge: CLIBridgeProtocol {
    let scenario: String

    var binaryPath: String? { "/usr/local/bin/duplicates-detector" }

    init(scenario: String = "pairs") {
        self.scenario = scenario
    }

    // MARK: - CLIBridgeProtocol

    func validateDependencies(
        userConfiguredPath: String?,
        refreshShellEnvironment: Bool
    ) async -> DependencyStatus {
        DependencyStatus(
            cli: ToolStatus(name: "duplicates-detector", isAvailable: true,
                            path: binaryPath, version: "1.5.0-mock", isRequired: true),
            ffmpeg: ToolStatus(name: "ffmpeg", isAvailable: true,
                               path: "/usr/local/bin/ffmpeg", version: "6.0", isRequired: false),
            ffprobe: ToolStatus(name: "ffprobe", isAvailable: true,
                                path: "/usr/local/bin/ffprobe", version: "6.0", isRequired: false),
            fpcalc: ToolStatus(name: "fpcalc", isAvailable: true,
                               path: "/usr/local/bin/fpcalc", version: "1.5.1", isRequired: false),
            hasMutagen: true,
            hasSkimage: false,
            hasPdfminer: false
        )
    }

    func runScan(config: ScanConfig) -> AsyncThrowingStream<CLIOutput, any Error> {
        let currentScenario = scenario
        return AsyncThrowingStream { continuation in
            Task {
                do {
                    try await Self.emitProgressEvents(continuation: continuation, scenario: currentScenario)

                    switch currentScenario {
                    case "error":
                        throw CLIBridgeError.processExitedWithErrorMessage(
                            code: 1,
                            stderr: "Mock error: simulated CLI failure for UI testing"
                        )
                    case "marketing-image":
                        let envelope = Self.makeMarketingImageEnvelope()
                        let data = try JSONEncoder.snakeCase.encode(envelope)
                        continuation.yield(.result(envelope, data))
                    case "marketing-video":
                        let envelope = Self.makeMarketingVideoEnvelope()
                        let data = try JSONEncoder.snakeCase.encode(envelope)
                        continuation.yield(.result(envelope, data))
                    case "empty":
                        let envelope = Self.makeEmptyEnvelope()
                        let data = try JSONEncoder.snakeCase.encode(envelope)
                        continuation.yield(.result(envelope, data))
                    case "groups":
                        let envelope = Self.makeGroupsEnvelope()
                        let data = try JSONEncoder.snakeCase.encode(envelope)
                        continuation.yield(.result(envelope, data))
                    case "slow-pairs":
                        let envelope = Self.makePairsEnvelope()
                        let data = try JSONEncoder.snakeCase.encode(envelope)
                        continuation.yield(.result(envelope, data))
                    default: // "pairs"
                        let envelope = Self.makePairsEnvelope()
                        let data = try JSONEncoder.snakeCase.encode(envelope)
                        continuation.yield(.result(envelope, data))
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    func cancelCurrentTask() {
        // No-op for mock
    }

    func listSessionsJSON() async -> [SessionInfo]? {
        []
    }

    func deleteSession(_ sessionId: String) async {
        // No-op for mock
    }

    func generateUndoScript(logPath: String) async throws -> String {
        "#!/bin/bash\n# Mock undo script\necho 'Nothing to undo (mock)'\n"
    }

    func exportAsFormat(
        envelopePath: String,
        format: String,
        outputPath: String,
        keep: String?,
        embedThumbnails: Bool,
        group: Bool,
        ignoreFile: String?
    ) async throws {
        // Write a minimal placeholder to the output path
        let content: String
        switch format {
        case "json":
            content = "{\"mock\": true}"
        case "csv":
            content = "file_a,file_b,score\n"
        case "shell":
            content = "#!/bin/bash\n# Mock export\n"
        default:
            content = "<!-- Mock export -->"
        }
        try content.write(toFile: outputPath, atomically: true, encoding: .utf8)
    }

    func resolvedEnvironment() async -> Environment {
        .inherit
    }

    func cliPythonPath() -> String? {
        "/usr/bin/python3"
    }

    func clearPersistedUserConfiguredPath() {
        // No-op for mock
    }

    nonisolated func hasBundledCLI() -> Bool {
        false
    }

    func cleanupOrphanedProcess() {
        // No-op for mock
    }

    // MARK: - Progress Event Emission

    private static func emitProgressEvents(
        continuation: AsyncThrowingStream<CLIOutput, any Error>.Continuation,
        scenario: String
    ) async throws {
        let stages: [(String, Int)] = [
            ("scan", 10),
            ("extract", 8),
            ("filter", 8),
            ("score", 28),
        ]

        // slow-pairs uses longer delays so cancel can be observed mid-scan
        let isSlow = scenario == "slow-pairs"
        let interStageDelay: UInt64 = isSlow ? 800 : 30
        let intraStageDelay: UInt64 = isSlow ? 500 : 20

        // session_start
        continuation.yield(.progress(.sessionStart(SessionStartEvent(
            sessionId: "mock-\(scenario)",
            wallStart: iso8601Now(),
            totalFiles: 0,
            stages: stages.map(\.0),
            resumedFrom: nil,
            priorElapsedSeconds: nil
        ))))

        try await Task.sleep(for: .milliseconds(50))

        for (stage, total) in stages {
            // stage_start
            continuation.yield(.progress(.stageStart(StageStartEvent(
                stage: stage,
                timestamp: iso8601Now(),
                total: total
            ))))

            try await Task.sleep(for: .milliseconds(interStageDelay))

            // One progress event per stage (filter is instant, no intermediate progress)
            if stage != "filter" {
                continuation.yield(.progress(.progress(StageProgressEvent(
                    stage: stage,
                    current: total,
                    timestamp: iso8601Now(),
                    total: total
                ))))
                try await Task.sleep(for: .milliseconds(intraStageDelay))
            }

            // stage_end
            var extras: [String: Int] = [:]
            if stage == "score" {
                extras["pairsFound"] = scenario == "empty" ? 0 : 3
            }
            continuation.yield(.progress(.stageEnd(StageEndEvent(
                stage: stage,
                total: total,
                elapsed: 0.1,
                timestamp: iso8601Now(),
                extras: extras
            ))))

            try await Task.sleep(for: .milliseconds(intraStageDelay))
        }
    }

    private static func iso8601Now() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }

    // MARK: - Mock Media Files

    /// Shared temp directory for mock media files.
    /// File operations (trash/delete) need real files at these paths to succeed.
    private static let mockMediaDir: URL = {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("dd-ui-test-media")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    /// Returns a path under the mock temp dir, creating an empty file if needed.
    private static func mockPath(_ filename: String) -> String {
        let url = mockMediaDir.appendingPathComponent(filename)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: Data())
        }
        return url.path
    }

    /// Returns a path under the mock temp dir, copying a real file from `sourceDir` so
    /// QuickLook can generate real thumbnails. Falls back to an empty placeholder if the
    /// source is unavailable (e.g. on CI where demo media isn't present).
    private static func marketingMediaPath(_ filename: String, sourceDir: String) -> String {
        let dest = mockMediaDir.appendingPathComponent(filename)
        if !FileManager.default.fileExists(atPath: dest.path) {
            let source = URL(fileURLWithPath: sourceDir)
                .appendingPathComponent(filename)
            if (try? FileManager.default.copyItem(at: source, to: dest)) == nil {
                FileManager.default.createFile(atPath: dest.path, contents: Data())
            }
        }
        return dest.path
    }

    // MARK: - Canned Envelopes

    private static func makePairsEnvelope() -> ScanEnvelope {
        ScanEnvelope(
            version: "1.5.0",
            generatedAt: iso8601Now(),
            args: makeArgs(keep: "newest"),
            stats: makeStats(filesScanned: 10, pairsAboveThreshold: 3),
            content: .pairs([
                makePair(
                    fileA: mockPath("vacation_2024.mp4"),
                    fileB: mockPath("vacation_2024_copy.mp4"),
                    score: 92.5,
                    sizeA: 104_857_600, sizeB: 104_857_600,
                    keep: "a"
                ),
                makePair(
                    fileA: mockPath("birthday_party.mov"),
                    fileB: mockPath("birthday_party_edit.mov"),
                    score: 78.0,
                    sizeA: 52_428_800, sizeB: 48_000_000,
                    keep: "a"
                ),
                makePair(
                    fileA: mockPath("drone_footage_001.mp4"),
                    fileB: mockPath("drone_footage_v2.mp4"),
                    score: 65.3,
                    sizeA: 209_715_200, sizeB: 198_000_000,
                    keep: "a"
                ),
            ]),
            dryRunSummary: nil,
            analytics: nil
        )
    }

    private static func makeGroupsEnvelope() -> ScanEnvelope {
        ScanEnvelope(
            version: "1.5.0",
            generatedAt: iso8601Now(),
            args: makeArgs(keep: nil, group: true),
            stats: makeStats(filesScanned: 5, pairsAboveThreshold: 3, groupsCount: 2),
            content: .groups([
                GroupResult(
                    groupId: 1,
                    fileCount: 3,
                    maxScore: 95.0,
                    minScore: 72.0,
                    avgScore: 83.5,
                    files: [
                        GroupFile(path: mockPath("clip_a.mp4"), duration: 30.0,
                                 width: 1920, height: 1080, fileSize: 50_000_000,
                                 codec: "h264", bitrate: 5_000_000, framerate: 30.0,
                                 audioChannels: 2, mtime: 1700000000.0,
                                 tagTitle: nil, tagArtist: nil, tagAlbum: nil,
                                 isReference: false, thumbnail: nil),
                        GroupFile(path: mockPath("clip_a_copy.mp4"), duration: 30.0,
                                 width: 1920, height: 1080, fileSize: 50_100_000,
                                 codec: "h264", bitrate: 5_000_000, framerate: 30.0,
                                 audioChannels: 2, mtime: 1700000100.0,
                                 tagTitle: nil, tagArtist: nil, tagAlbum: nil,
                                 isReference: false, thumbnail: nil),
                        GroupFile(path: mockPath("clip_a_v2.mp4"), duration: 30.5,
                                 width: 1920, height: 1080, fileSize: 48_000_000,
                                 codec: "h264", bitrate: 4_800_000, framerate: 30.0,
                                 audioChannels: 2, mtime: 1700001000.0,
                                 tagTitle: nil, tagArtist: nil, tagAlbum: nil,
                                 isReference: false, thumbnail: nil),
                    ],
                    pairs: [
                        GroupPair(fileA: mockPath("clip_a.mp4"),
                                 fileB: mockPath("clip_a_copy.mp4"),
                                 score: 95.0,
                                 breakdown: ["filename": 42.0, "duration": 30.0,
                                             "resolution": 10.0, "filesize": 9.5],
                                 detail: ["filename": DetailScore(raw: 0.84, weight: 50.0),
                                          "duration": DetailScore(raw: 1.0, weight: 30.0),
                                          "resolution": DetailScore(raw: 1.0, weight: 10.0),
                                          "filesize": DetailScore(raw: 0.95, weight: 10.0)]),
                        GroupPair(fileA: mockPath("clip_a.mp4"),
                                 fileB: mockPath("clip_a_v2.mp4"),
                                 score: 72.0,
                                 breakdown: ["filename": 35.0, "duration": 28.0,
                                             "resolution": 10.0, "filesize": 9.0],
                                 detail: ["filename": DetailScore(raw: 0.70, weight: 50.0),
                                          "duration": DetailScore(raw: 0.93, weight: 30.0),
                                          "resolution": DetailScore(raw: 1.0, weight: 10.0),
                                          "filesize": DetailScore(raw: 0.90, weight: 10.0)]),
                    ],
                    keep: nil
                ),
                GroupResult(
                    groupId: 2,
                    fileCount: 2,
                    maxScore: 88.0,
                    minScore: 88.0,
                    avgScore: 88.0,
                    files: [
                        GroupFile(path: mockPath("interview.mov"), duration: 120.0,
                                 width: 3840, height: 2160, fileSize: 500_000_000,
                                 codec: "prores", bitrate: 30_000_000, framerate: 24.0,
                                 audioChannels: 2, mtime: 1699000000.0,
                                 tagTitle: nil, tagArtist: nil, tagAlbum: nil,
                                 isReference: false, thumbnail: nil),
                        GroupFile(path: mockPath("interview_h264.mp4"), duration: 120.0,
                                 width: 3840, height: 2160, fileSize: 150_000_000,
                                 codec: "h264", bitrate: 10_000_000, framerate: 24.0,
                                 audioChannels: 2, mtime: 1699100000.0,
                                 tagTitle: nil, tagArtist: nil, tagAlbum: nil,
                                 isReference: false, thumbnail: nil),
                    ],
                    pairs: [
                        GroupPair(fileA: mockPath("interview.mov"),
                                 fileB: mockPath("interview_h264.mp4"),
                                 score: 88.0,
                                 breakdown: ["filename": 38.0, "duration": 30.0,
                                             "resolution": 10.0, "filesize": 5.0],
                                 detail: ["filename": DetailScore(raw: 0.76, weight: 50.0),
                                          "duration": DetailScore(raw: 1.0, weight: 30.0),
                                          "resolution": DetailScore(raw: 1.0, weight: 10.0),
                                          "filesize": DetailScore(raw: 0.50, weight: 10.0)]),
                    ],
                    keep: nil
                ),
            ]),
            dryRunSummary: nil,
            analytics: nil
        )
    }

    // MARK: - Photos Mock Envelope

    /// Canned envelope for Photos Library UI testing. Uses `photos://asset/` URIs
    /// so all Photos-specific UI conditionals activate (inspector labels, export restrictions, etc.).
    static func makePhotosEnvelope() -> ScanEnvelope {
        ScanEnvelope(
            version: "1.5.0",
            generatedAt: iso8601Now(),
            args: ScanArgs(
                directories: [], threshold: 50,
                content: false, keep: "newest",
                action: "trash", group: false,
                sort: "score", mode: "auto",
                embedThumbnails: false
            ),
            stats: makeStats(filesScanned: 12, pairsAboveThreshold: 3),
            content: .pairs([
                makePair(
                    fileA: "photos://asset/MOCK-UUID-A1#IMG_2024_beach.heic",
                    fileB: "photos://asset/MOCK-UUID-A2#IMG_2024_beach_edit.heic",
                    score: 91.0,
                    sizeA: 8_500_000, sizeB: 8_200_000,
                    keep: "a"
                ),
                makePair(
                    fileA: "photos://asset/MOCK-UUID-B1#sunset_panorama.jpg",
                    fileB: "photos://asset/MOCK-UUID-B2#sunset_panorama_2.jpg",
                    score: 76.5,
                    sizeA: 12_000_000, sizeB: 11_500_000,
                    keep: "a"
                ),
                makePair(
                    fileA: "photos://asset/MOCK-UUID-C1#family_video.mov",
                    fileB: "photos://asset/MOCK-UUID-C2#family_video_trimmed.mov",
                    score: 63.0,
                    sizeA: 150_000_000, sizeB: 120_000_000,
                    keep: "a"
                ),
            ]),
            dryRunSummary: nil,
            analytics: nil
        )
    }

    private static func makeEmptyEnvelope() -> ScanEnvelope {
        ScanEnvelope(
            version: "1.5.0",
            generatedAt: iso8601Now(),
            args: makeArgs(keep: "newest"),
            stats: makeStats(filesScanned: 5, pairsAboveThreshold: 0),
            content: .pairs([]),
            dryRunSummary: nil,
            analytics: nil
        )
    }

    // MARK: - Marketing Envelopes

    private static let demoPhotosDir = "/Volumes/TRANSCEND/repos/duplicates-detector/demo-media/photos"
    private static let demoVideosDir = "/Volumes/TRANSCEND/repos/duplicates-detector/demo-media/videos"

    private static func makeMarketingImageEnvelope() -> ScanEnvelope {
        ScanEnvelope(
            version: "1.5.0",
            generatedAt: iso8601Now(),
            args: ScanArgs(
                directories: [mockMediaDir.path],
                threshold: 50,
                content: false,
                keep: "newest",
                action: "trash",
                group: false,
                sort: "score",
                mode: "image",
                embedThumbnails: false
            ),
            stats: makeStats(filesScanned: 8, pairsAboveThreshold: 4),
            content: .pairs([
                makeMarketingImagePair(
                    fileA: marketingMediaPath("sunset_beach.jpg", sourceDir: demoPhotosDir),
                    fileB: marketingMediaPath("sunset_beach_edited.jpg", sourceDir: demoPhotosDir),
                    score: 88.5,
                    sizeA: 1_048_576, sizeB: 224_256,
                    widthA: 3000, heightA: 4500,
                    widthB: 800, heightB: 1200,
                    keep: "a"
                ),
                makeMarketingImagePair(
                    fileA: marketingMediaPath("mountain_lake.jpg", sourceDir: demoPhotosDir),
                    fileB: marketingMediaPath("mountain_lake_copy.jpg", sourceDir: demoPhotosDir),
                    score: 82.3,
                    sizeA: 646_144, sizeB: 249_856,
                    widthA: 3000, heightA: 2000,
                    widthB: 1200, heightB: 800,
                    keep: "a"
                ),
                makeMarketingImagePair(
                    fileA: marketingMediaPath("city_skyline.jpg", sourceDir: demoPhotosDir),
                    fileB: marketingMediaPath("city_skyline_backup.jpg", sourceDir: demoPhotosDir),
                    score: 74.1,
                    sizeA: 954_368, sizeB: 313_344,
                    widthA: 3000, heightA: 1862,
                    widthB: 1200, heightB: 745,
                    keep: "a"
                ),
                makeMarketingImagePair(
                    fileA: marketingMediaPath("garden_flowers.jpg", sourceDir: demoPhotosDir),
                    fileB: marketingMediaPath("garden_flowers_v2.jpg", sourceDir: demoPhotosDir),
                    score: 67.8,
                    sizeA: 2_306_867, sizeB: 444_416,
                    widthA: 3000, heightA: 4000,
                    widthB: 900, heightB: 1200,
                    keep: "a"
                ),
            ]),
            dryRunSummary: nil,
            analytics: makeMarketingAnalytics()
        )
    }

    private static func makeMarketingVideoEnvelope() -> ScanEnvelope {
        ScanEnvelope(
            version: "1.5.0",
            generatedAt: iso8601Now(),
            args: ScanArgs(
                directories: [mockMediaDir.path],
                threshold: 50,
                content: false,
                keep: "largest",
                action: "trash",
                group: false,
                sort: "score",
                mode: "video",
                embedThumbnails: false
            ),
            stats: makeStats(filesScanned: 10, pairsAboveThreshold: 5),
            content: .pairs([
                makePair(
                    fileA: marketingMediaPath("ocean_waves.mp4", sourceDir: demoVideosDir),
                    fileB: marketingMediaPath("ocean_waves_720p.mp4", sourceDir: demoVideosDir),
                    score: 91.2,
                    sizeA: 10_066_329, sizeB: 8_294_400,
                    keep: "a"
                ),
                makePair(
                    fileA: marketingMediaPath("traffic_timelapse.mp4", sourceDir: demoVideosDir),
                    fileB: marketingMediaPath("traffic_timelapse_backup.mp4", sourceDir: demoVideosDir),
                    score: 85.7,
                    sizeA: 20_971_520, sizeB: 3_355_443,
                    keep: "a"
                ),
                makePair(
                    fileA: marketingMediaPath("forest_walk.mp4", sourceDir: demoVideosDir),
                    fileB: marketingMediaPath("forest_walk_edit.mp4", sourceDir: demoVideosDir),
                    score: 79.4,
                    sizeA: 51_380_224, sizeB: 7_759_462,
                    keep: "a"
                ),
                makePair(
                    fileA: marketingMediaPath("sunset_clouds.mp4", sourceDir: demoVideosDir),
                    fileB: marketingMediaPath("sunset_clouds_copy.mp4", sourceDir: demoVideosDir),
                    score: 72.1,
                    sizeA: 18_874_368, sizeB: 4_089_446,
                    keep: "a"
                ),
                makePair(
                    fileA: marketingMediaPath("aerial_landscape.mp4", sourceDir: demoVideosDir),
                    fileB: marketingMediaPath("aerial_landscape_v2.mp4", sourceDir: demoVideosDir),
                    score: 65.8,
                    sizeA: 8_493_465, sizeB: 1_887_436,
                    keep: "a"
                ),
            ]),
            dryRunSummary: nil,
            analytics: makeMarketingAnalytics()
        )
    }

    /// Image-mode pair helper: uses image-appropriate comparators (filename, resolution, filesize, exif).
    private static func makeMarketingImagePair(
        fileA: String,
        fileB: String,
        score: Double,
        sizeA: Int,
        sizeB: Int,
        widthA: Int,
        heightA: Int,
        widthB: Int,
        heightB: Int,
        keep: String?
    ) -> PairResult {
        let filenameRaw = score / 100.0
        let sizeRatio = Double(min(sizeA, sizeB)) / Double(max(sizeA, sizeB))
        let resPixelsA = Double(widthA * heightA)
        let resPixelsB = Double(widthB * heightB)
        let resRatio = min(resPixelsA, resPixelsB) / max(resPixelsA, resPixelsB)

        return PairResult(
            fileA: fileA,
            fileB: fileB,
            score: score,
            breakdown: [
                "filename": filenameRaw * 25.0,
                "resolution": resRatio * 20.0,
                "filesize": sizeRatio * 15.0,
                "exif": 0.9 * 40.0,
            ],
            detail: [
                "filename": DetailScore(raw: filenameRaw, weight: 25.0),
                "resolution": DetailScore(raw: resRatio, weight: 20.0),
                "filesize": DetailScore(raw: sizeRatio, weight: 15.0),
                "exif": DetailScore(raw: 0.9, weight: 40.0),
            ],
            fileAMetadata: FileMetadata(
                duration: nil, width: widthA, height: heightA,
                fileSize: sizeA, codec: nil, bitrate: nil,
                framerate: nil, audioChannels: nil,
                mtime: 1700000000.0
            ),
            fileBMetadata: FileMetadata(
                duration: nil, width: widthB, height: heightB,
                fileSize: sizeB, codec: nil, bitrate: nil,
                framerate: nil, audioChannels: nil,
                mtime: 1700000100.0
            ),
            fileAIsReference: false,
            fileBIsReference: false,
            keep: keep
        )
    }

    private static func makeMarketingAnalytics() -> AnalyticsData {
        AnalyticsData(
            directoryStats: [
                DirectoryStat(
                    path: "/Volumes/Media/Photos/2024",
                    totalFiles: 1247,
                    duplicateFiles: 89,
                    totalSize: 15_032_385_536,
                    recoverableSize: 2_147_483_648,
                    duplicateDensity: 0.071
                ),
                DirectoryStat(
                    path: "/Volumes/Media/Photos/2023",
                    totalFiles: 983,
                    duplicateFiles: 45,
                    totalSize: 11_274_289_152,
                    recoverableSize: 1_073_741_824,
                    duplicateDensity: 0.046
                ),
                DirectoryStat(
                    path: "/Volumes/Media/Videos/Projects",
                    totalFiles: 312,
                    duplicateFiles: 28,
                    totalSize: 53_687_091_200,
                    recoverableSize: 8_589_934_592,
                    duplicateDensity: 0.090
                ),
            ],
            scoreDistribution: [
                ScoreBucket(range: "50-59", min: 50, max: 59, count: 12),
                ScoreBucket(range: "60-69", min: 60, max: 69, count: 28),
                ScoreBucket(range: "70-79", min: 70, max: 79, count: 45),
                ScoreBucket(range: "80-89", min: 80, max: 89, count: 34),
                ScoreBucket(range: "90-100", min: 90, max: 100, count: 18),
            ],
            filetypeBreakdown: [
                FiletypeEntry(ext: "jpg", count: 842, size: 4_294_967_296),
                FiletypeEntry(ext: "heic", count: 356, size: 2_147_483_648),
                FiletypeEntry(ext: "png", count: 128, size: 1_073_741_824),
                FiletypeEntry(ext: "mp4", count: 203, size: 32_212_254_720),
                FiletypeEntry(ext: "mov", count: 87, size: 21_474_836_480),
                FiletypeEntry(ext: "raw", count: 42, size: 5_368_709_120),
            ],
            creationTimeline: []
        )
    }

    // MARK: - Helpers

    private static func makeArgs(keep: String? = "newest", group: Bool = false) -> ScanArgs {
        ScanArgs(
            directories: [mockMediaDir.path],
            threshold: 50,
            content: false,
            keep: keep,
            action: "delete",
            group: group,
            sort: "score",
            mode: "video",
            embedThumbnails: false
        )
    }

    private static func makeStats(
        filesScanned: Int,
        pairsAboveThreshold: Int,
        groupsCount: Int? = nil
    ) -> ScanStats {
        ScanStats(
            filesScanned: filesScanned,
            filesAfterFilter: filesScanned,
            totalPairsScored: filesScanned * (filesScanned - 1) / 2,
            pairsAboveThreshold: pairsAboveThreshold,
            groupsCount: groupsCount,
            spaceRecoverable: pairsAboveThreshold > 0 ? 104_857_600 : 0,
            scanTime: 0.15,
            extractTime: 1.234,
            filterTime: 0.002,
            contentHashTime: 0.0,
            scoringTime: 0.567,
            totalTime: 2.003
        )
    }

    private static func makePair(
        fileA: String,
        fileB: String,
        score: Double,
        sizeA: Int,
        sizeB: Int,
        keep: String?
    ) -> PairResult {
        PairResult(
            fileA: fileA,
            fileB: fileB,
            score: score,
            breakdown: [
                "filename": score * 0.5,
                "duration": score * 0.3,
                "resolution": score * 0.1,
                "filesize": score * 0.1,
            ],
            detail: [
                "filename": DetailScore(raw: score / 100.0, weight: 50.0),
                "duration": DetailScore(raw: 1.0, weight: 30.0),
                "resolution": DetailScore(raw: 1.0, weight: 10.0),
                "filesize": DetailScore(raw: Double(min(sizeA, sizeB)) / Double(max(sizeA, sizeB)),
                                        weight: 10.0),
            ],
            fileAMetadata: FileMetadata(
                duration: 30.0, width: 1920, height: 1080,
                fileSize: sizeA, codec: "h264", bitrate: 5_000_000,
                framerate: 30.0, audioChannels: 2,
                mtime: 1700000000.0
            ),
            fileBMetadata: FileMetadata(
                duration: 30.0, width: 1920, height: 1080,
                fileSize: sizeB, codec: "h264", bitrate: 5_000_000,
                framerate: 30.0, audioChannels: 2,
                mtime: 1700000100.0
            ),
            fileAIsReference: false,
            fileBIsReference: false,
            keep: keep
        )
    }
}

// MARK: - JSON Encoder Extension

private extension JSONEncoder {
    static let snakeCase: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()
}
#endif
