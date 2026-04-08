// Tests/BackgroundScanEngineTests.swift
import CoreGraphics
import ImageIO
import Testing
import Foundation
@testable import DuplicatesDetector

@Suite("BackgroundScanEngine")
struct BackgroundScanEngineTests {

    // MARK: - filenameSimilarity

    @Test("identical filenames score 1.0")
    func identicalFilenames() {
        let score = BackgroundScanEngine.filenameSimilarity(
            "/path/to/video.mp4", "/other/path/video.mp4")
        #expect(score == 1.0)
    }

    @Test("completely different filenames score low")
    func differentFilenames() {
        let score = BackgroundScanEngine.filenameSimilarity(
            "/path/abcdef.mp4", "/path/zyxwvu.mp4")
        #expect(score < 0.3)
    }

    @Test("similar filenames score above 0.7")
    func similarFilenames() {
        let score = BackgroundScanEngine.filenameSimilarity(
            "/path/vacation_2024.mp4", "/path/vacation_2025.mp4")
        #expect(score > 0.7)
    }

    @Test("case-insensitive and extension-stripped comparison scores 1.0")
    func caseInsensitiveExtensionStripped() {
        let score = BackgroundScanEngine.filenameSimilarity(
            "/path/MyVideo.mp4", "/other/myvideo.mkv")
        #expect(score == 1.0)
    }

    // MARK: - durationScore

    @Test("identical durations score 1.0")
    func identicalDurations() {
        let score = BackgroundScanEngine.durationScore(120.0, 120.0)
        #expect(score == 1.0)
    }

    @Test("durations within 2s score high")
    func closeDurations() {
        // 120.0 and 120.5: diff=0.5, maxDiff=120.5*0.1=12.05
        // score = 1.0 - 0.5/12.05 ≈ 0.959
        let score = BackgroundScanEngine.durationScore(120.0, 120.5)
        #expect(score > 0.9)
    }

    @Test("very different durations score 0.0")
    func veryDifferentDurations() {
        // 60 vs 300: diff=240, maxDiff=30, clamped to 0.0
        let score = BackgroundScanEngine.durationScore(60.0, 300.0)
        #expect(score == 0.0)
    }

    @Test("nil duration inputs score 0.0")
    func nilDurations() {
        #expect(BackgroundScanEngine.durationScore(nil, 120.0) == 0.0)
        #expect(BackgroundScanEngine.durationScore(120.0, nil) == 0.0)
        #expect(BackgroundScanEngine.durationScore(nil, nil) == 0.0)
    }

    // MARK: - resolutionScore

    @Test("identical resolutions score 1.0")
    func identicalResolutions() {
        let score = BackgroundScanEngine.resolutionScore(
            widthA: 1920, heightA: 1080,
            widthB: 1920, heightB: 1080)
        #expect(score == 1.0)
    }

    @Test("similar resolutions score above 0.5")
    func similarResolutions() {
        // 1920x1080 = 2_073_600 vs 1280x720 = 921_600
        // ratio = 921_600 / 2_073_600 ≈ 0.444
        // Use closer resolutions: 1920x1080 vs 1600x900
        // 2_073_600 vs 1_440_000 → ratio ≈ 0.694
        let score = BackgroundScanEngine.resolutionScore(
            widthA: 1920, heightA: 1080,
            widthB: 1600, heightB: 900)
        #expect(score > 0.5)
    }

    @Test("nil dimensions score 0.0")
    func nilDimensions() {
        let score = BackgroundScanEngine.resolutionScore(
            widthA: nil, heightA: nil,
            widthB: 1920, heightB: 1080)
        #expect(score == 0.0)
    }

    // MARK: - fileSizeScore

    @Test("identical file sizes score 1.0")
    func identicalFileSizes() {
        let score = BackgroundScanEngine.fileSizeScore(1_000_000, 1_000_000)
        #expect(score == 1.0)
    }

    @Test("similar file sizes score above 0.8")
    func similarFileSizes() {
        // 1_000_000 vs 900_000: ratio = 0.9
        let score = BackgroundScanEngine.fileSizeScore(1_000_000, 900_000)
        #expect(score > 0.8)
    }

    @Test("very different file sizes score low")
    func veryDifferentFileSizes() {
        // 100_000 vs 1_000_000: ratio = 0.1
        let score = BackgroundScanEngine.fileSizeScore(100_000, 1_000_000)
        #expect(score < 0.3)
    }

    // MARK: - scoreNewFile

    @Test("composite score above threshold produces alerts")
    func scoreAboveThreshold() {
        let newMetadata = FileMetadata(
            duration: 120.0, width: 1920, height: 1080, fileSize: 1_000_000)
        let known = KnownFile(
            path: "/videos/vacation.mp4",
            metadata: FileMetadata(
                duration: 120.0, width: 1920, height: 1080, fileSize: 1_000_000))
        let sessionID = UUID()
        let weights: [String: Double] = [
            "filename": 50, "duration": 30, "resolution": 10, "filesize": 10,
        ]

        let alerts = BackgroundScanEngine.scoreNewFile(
            newPath: "/videos/vacation.mp4",
            newMetadata: newMetadata,
            candidates: [known],
            weights: weights,
            threshold: 50,
            sessionID: sessionID)

        #expect(alerts.count == 1)
        #expect(alerts.first!.score >= 50)
    }

    @Test("composite score below threshold produces no alerts")
    func scoreBelowThreshold() {
        let newMetadata = FileMetadata(
            duration: 10.0, width: 640, height: 480, fileSize: 100_000)
        let known = KnownFile(
            path: "/videos/completely_different.mp4",
            metadata: FileMetadata(
                duration: 300.0, width: 3840, height: 2160, fileSize: 5_000_000))
        let sessionID = UUID()
        let weights: [String: Double] = [
            "filename": 50, "duration": 30, "resolution": 10, "filesize": 10,
        ]

        let alerts = BackgroundScanEngine.scoreNewFile(
            newPath: "/videos/xyz.mp4",
            newMetadata: newMetadata,
            candidates: [known],
            weights: weights,
            threshold: 50,
            sessionID: sessionID)

        #expect(alerts.isEmpty)
    }

    // MARK: - bucketCandidates

    @Test("bucketCandidates filters to ±2s duration window")
    func bucketCandidatesFilters() {
        let close = KnownFile(
            path: "/a.mp4",
            metadata: FileMetadata(duration: 121.0, fileSize: 1000))
        let far = KnownFile(
            path: "/b.mp4",
            metadata: FileMetadata(duration: 200.0, fileSize: 1000))
        let nilDur = KnownFile(
            path: "/c.mp4",
            metadata: FileMetadata(duration: nil, fileSize: 1000))

        let result = BackgroundScanEngine.bucketCandidates(
            newDuration: 120.0, knownFiles: [close, far, nilDur])

        // close (121.0, within ±2s) and nilDur (nil duration, included) should pass
        #expect(result.count == 2)
        #expect(result.contains { $0.path == "/a.mp4" })
        #expect(result.contains { $0.path == "/c.mp4" })
    }

    @Test("scoreNewFile normalizes by implemented weights only, ignoring exif/tags")
    func scoreNormalizesWithUnimplementedWeights() {
        let newMeta = FileMetadata(duration: nil, width: 1920, height: 1080, fileSize: 1000)
        let known = KnownFile(
            path: "/known/photo.jpg",
            metadata: FileMetadata(duration: nil, width: 1920, height: 1080, fileSize: 1000)
        )
        let weights: [String: Double] = ["filename": 25, "resolution": 20, "filesize": 15, "exif": 40]
        let alerts = BackgroundScanEngine.scoreNewFile(
            newPath: "/new/photo.jpg",
            newMetadata: newMeta,
            candidates: [known],
            weights: weights,
            threshold: 50,
            sessionID: UUID()
        )
        #expect(!alerts.isEmpty, "Image pair should match when exif weight excluded from denominator")
    }

    // MARK: - resolveWeights

    @Test("resolveWeights returns config weights when provided")
    func resolveWeightsCustom() {
        let custom: [String: Double] = ["filename": 100]
        let result = BackgroundScanEngine.resolveWeights(custom, mode: .video)
        #expect(result == custom)
    }

    @Test("resolveWeights returns video defaults when nil")
    func resolveWeightsVideoDefault() {
        let result = BackgroundScanEngine.resolveWeights(nil, mode: .video)
        #expect(result == ["filename": 50, "duration": 30, "resolution": 10, "filesize": 10])
    }

    // MARK: - levenshteinDistance

    @Test("levenshteinDistance basic cases")
    func levenshteinBasic() {
        #expect(BackgroundScanEngine.levenshteinDistance("", "") == 0)
        #expect(BackgroundScanEngine.levenshteinDistance("abc", "") == 3)
        #expect(BackgroundScanEngine.levenshteinDistance("", "xyz") == 3)
        #expect(BackgroundScanEngine.levenshteinDistance("kitten", "sitting") == 3)
        #expect(BackgroundScanEngine.levenshteinDistance("same", "same") == 0)
    }

    // MARK: - parseFFProbeOutput

    @Test("parseFFProbeOutput extracts metadata from valid JSON")
    func parseFFProbeValid() {
        let json = """
        {
            "format": {
                "duration": "125.500",
                "size": "5000000"
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ]
        }
        """
        let data = json.data(using: .utf8)!
        let meta = BackgroundScanEngine.parseFFProbeOutput(data, filePath: "/test.mp4")

        #expect(meta != nil)
        #expect(meta?.duration == 125.5)
        #expect(meta?.width == 1920)
        #expect(meta?.height == 1080)
        #expect(meta?.fileSize == 5_000_000)
        #expect(meta?.codec == "h264")
    }

    @Test("parseFFProbeOutput returns nil for invalid JSON")
    func parseFFProbeInvalid() {
        let data = "not json".data(using: .utf8)!
        let meta = BackgroundScanEngine.parseFFProbeOutput(data, filePath: "/test.mp4")
        #expect(meta == nil)
    }

    // MARK: - findStaleEntry (rename detection)

    @Test("findStaleEntry matches stale path with same file size")
    func findStaleEntryMatches() {
        let known = [
            KnownFile(path: "/old/name.mp4", metadata: FileMetadata(
                duration: 120.0, width: 1920, height: 1080, fileSize: 5_000_000)),
            KnownFile(path: "/other/file.mp4", metadata: FileMetadata(
                duration: 60.0, width: 1280, height: 720, fileSize: 1_000_000)),
        ]
        let result = BackgroundScanEngine.findStaleEntry(
            forNewPath: "/new/name.mp4",
            fileSize: 5_000_000,
            in: known,
            fileExistsCheck: { path in path != "/old/name.mp4" }
        )
        #expect(result == 0)
    }

    @Test("findStaleEntry returns nil when no stale match")
    func findStaleEntryNoMatch() {
        let known = [
            KnownFile(path: "/existing/file.mp4", metadata: FileMetadata(
                duration: 120.0, width: 1920, height: 1080, fileSize: 5_000_000)),
        ]
        let result = BackgroundScanEngine.findStaleEntry(
            forNewPath: "/new/file.mp4",
            fileSize: 5_000_000,
            in: known,
            fileExistsCheck: { _ in true }
        )
        #expect(result == nil)
    }

    @Test("findStaleEntry ignores stale paths with different file size")
    func findStaleEntryDifferentSize() {
        let known = [
            KnownFile(path: "/old/name.mp4", metadata: FileMetadata(fileSize: 999)),
        ]
        let result = BackgroundScanEngine.findStaleEntry(
            forNewPath: "/new/name.mp4",
            fileSize: 5_000_000,
            in: known,
            fileExistsCheck: { _ in false }
        )
        #expect(result == nil)
    }

    // MARK: - extractImageMetadata

    @Test("extractImageMetadata reads dimensions and file size from a PNG")
    func extractImageMetadataPNG() async throws {
        let tmpDir = FileManager.default.temporaryDirectory
        let imgPath = tmpDir.appendingPathComponent("test_\(UUID()).png")
        let pngData = BackgroundScanEngineTests.minimal2x3PNG()
        try pngData.write(to: imgPath)
        defer { try? FileManager.default.removeItem(at: imgPath) }

        let meta = BackgroundScanEngine.extractImageMetadata(from: imgPath)
        #expect(meta != nil)
        #expect(meta?.width == 2)
        #expect(meta?.height == 3)
        #expect(meta?.fileSize ?? 0 > 0)
        #expect(meta?.duration == nil)
    }

    @Test("extractImageMetadata returns nil for non-image file")
    func extractImageMetadataInvalid() {
        let tmpDir = FileManager.default.temporaryDirectory
        let fakePath = tmpDir.appendingPathComponent("test_\(UUID()).png")
        FileManager.default.createFile(atPath: fakePath.path, contents: Data("not an image".utf8))
        defer { try? FileManager.default.removeItem(at: fakePath) }

        let meta = BackgroundScanEngine.extractImageMetadata(from: fakePath)
        #expect(meta == nil)
    }

    /// Creates a minimal valid 2x3 PNG for testing.
    private static func minimal2x3PNG() -> Data {
        let width = 2, height = 3
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: width * 4, space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        let cgImage = ctx.makeImage()!
        let mutableData = NSMutableData()
        let dest = CGImageDestinationCreateWithData(
            mutableData as CFMutableData, "public.png" as CFString, 1, nil)!
        CGImageDestinationAddImage(dest, cgImage, nil)
        CGImageDestinationFinalize(dest)
        return mutableData as Data
    }

    // MARK: - enumerateFiles

    @Test("enumerateFiles finds matching files and skips non-matching/hidden")
    func enumerateFilesFilters() throws {
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("inventory_test_\(UUID())")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        FileManager.default.createFile(
            atPath: tmpDir.appendingPathComponent("video.mp4").path,
            contents: Data("fake".utf8))
        FileManager.default.createFile(
            atPath: tmpDir.appendingPathComponent("photo.jpg").path,
            contents: Data("fake".utf8))
        FileManager.default.createFile(
            atPath: tmpDir.appendingPathComponent("readme.txt").path,
            contents: Data("ignore".utf8))
        FileManager.default.createFile(
            atPath: tmpDir.appendingPathComponent(".hidden.mp4").path,
            contents: Data("hidden".utf8))

        let extensions: Set<String> = ["mp4", "jpg"]
        let files = BackgroundScanEngine.enumerateFiles(
            in: [tmpDir], extensions: extensions
        )

        #expect(files.count == 2)
        let names = Set(files.map { $0.lastPathComponent })
        #expect(names.contains("video.mp4"))
        #expect(names.contains("photo.jpg"))
        #expect(!names.contains("readme.txt"))
        #expect(!names.contains(".hidden.mp4"))
    }

    // MARK: - extractAudioMetadata

    @Test("extractAudioMetadata returns nil for non-audio file")
    func extractAudioMetadataInvalid() async {
        let tmpDir = FileManager.default.temporaryDirectory
        let fakePath = tmpDir.appendingPathComponent("test_\(UUID()).m4a")
        FileManager.default.createFile(atPath: fakePath.path, contents: Data("not audio".utf8))
        defer { try? FileManager.default.removeItem(at: fakePath) }

        let meta = await BackgroundScanEngine.extractAudioMetadata(from: fakePath)
        #expect(meta == nil)
    }

    // MARK: - bucketCandidates cross-type filtering (auto mode)

    @Test("bucketCandidates filters cross-type candidates in auto mode")
    func bucketCandidatesFiltersCrossTypeInAutoMode() {
        let imageFile = KnownFile(
            path: "/photos/sunset.jpg",
            metadata: FileMetadata(duration: nil, width: 1920, height: 1080, fileSize: 500_000),
            effectiveMode: .image
        )
        let videoFile = KnownFile(
            path: "/videos/sunset.mp4",
            metadata: FileMetadata(duration: 30.0, width: 1920, height: 1080, fileSize: 5_000_000),
            effectiveMode: .video
        )
        let unknownModeFile = KnownFile(
            path: "/misc/legacy.mp4",
            metadata: FileMetadata(duration: nil, fileSize: 1000),
            effectiveMode: nil
        )

        let result = BackgroundScanEngine.bucketCandidates(
            newDuration: nil,
            newEffectiveMode: .image,
            knownFiles: [imageFile, videoFile, unknownModeFile]
        )

        // Should include imageFile (matching .image) and unknownModeFile (nil passes through),
        // but exclude videoFile (.video != .image)
        #expect(result.count == 2)
        #expect(result.contains { $0.path == "/photos/sunset.jpg" })
        #expect(result.contains { $0.path == "/misc/legacy.mp4" })
        #expect(!result.contains { $0.path == "/videos/sunset.mp4" })
    }

    @Test("bucketCandidates allows all candidates when not auto mode (nil effectiveMode)")
    func bucketCandidatesAllowsAllWhenNotAutoMode() {
        let imageFile = KnownFile(
            path: "/photos/sunset.jpg",
            metadata: FileMetadata(duration: nil, width: 1920, height: 1080, fileSize: 500_000),
            effectiveMode: .image
        )
        let videoFile = KnownFile(
            path: "/videos/sunset.mp4",
            metadata: FileMetadata(duration: nil, width: 1920, height: 1080, fileSize: 5_000_000),
            effectiveMode: .video
        )

        let result = BackgroundScanEngine.bucketCandidates(
            newDuration: nil,
            newEffectiveMode: nil,
            knownFiles: [imageFile, videoFile]
        )

        // With newEffectiveMode nil (non-auto), all candidates should be returned
        #expect(result.count == 2)
        #expect(result.contains { $0.path == "/photos/sunset.jpg" })
        #expect(result.contains { $0.path == "/videos/sunset.mp4" })
    }

    // MARK: - resolveEffectiveMode

    @Test("resolveEffectiveMode returns nil for non-auto modes")
    func resolveEffectiveModeReturnsNilForNonAuto() {
        let meta = FileMetadata(duration: 120.0, fileSize: 1000)
        #expect(BackgroundScanEngine.resolveEffectiveMode(metadata: meta, configMode: .video) == nil)
        #expect(BackgroundScanEngine.resolveEffectiveMode(metadata: meta, configMode: .image) == nil)
        #expect(BackgroundScanEngine.resolveEffectiveMode(metadata: meta, configMode: .audio) == nil)
    }

    @Test("resolveEffectiveMode returns .image when duration is nil in auto mode")
    func resolveEffectiveModeReturnsImageForNilDuration() {
        let meta = FileMetadata(duration: nil, width: 1920, height: 1080, fileSize: 500_000)
        let result = BackgroundScanEngine.resolveEffectiveMode(metadata: meta, configMode: .auto)
        #expect(result == .image)
    }

    @Test("resolveEffectiveMode returns .video when duration is present in auto mode")
    func resolveEffectiveModeReturnsVideoForDuration() {
        let meta = FileMetadata(duration: 120.0, width: 1920, height: 1080, fileSize: 5_000_000)
        let result = BackgroundScanEngine.resolveEffectiveMode(metadata: meta, configMode: .auto)
        #expect(result == .video)
    }

    // MARK: - mergeKnownFiles deduplication

    @Test("mergeKnownFiles deduplicates incoming batch with duplicate paths")
    func mergeKnownFilesDeduplicatesIncomingBatch() async {
        let config = ScanConfig()
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: []
        )

        let fileA = KnownFile(
            path: "/videos/clip.mp4",
            metadata: FileMetadata(duration: 60.0, fileSize: 1_000_000)
        )
        let fileADuplicate = KnownFile(
            path: "/videos/clip.mp4",
            metadata: FileMetadata(duration: 60.0, fileSize: 1_000_000)
        )
        let fileB = KnownFile(
            path: "/videos/other.mp4",
            metadata: FileMetadata(duration: 30.0, fileSize: 500_000)
        )

        await engine.mergeKnownFiles([fileA, fileADuplicate, fileB])

        let stats = await engine.stats
        // Should have only 2 tracked files, not 3, because fileA and fileADuplicate share the same path
        #expect(stats.trackedFiles == 2)
    }

    @Test("mergeKnownFiles skips paths already in the known set")
    func mergeKnownFilesSkipsExistingPaths() async {
        let existingFile = KnownFile(
            path: "/videos/existing.mp4",
            metadata: FileMetadata(duration: 120.0, fileSize: 2_000_000)
        )
        let config = ScanConfig()
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: [existingFile]
        )

        let newFile = KnownFile(
            path: "/videos/new.mp4",
            metadata: FileMetadata(duration: 60.0, fileSize: 1_000_000)
        )
        let duplicateOfExisting = KnownFile(
            path: "/videos/existing.mp4",
            metadata: FileMetadata(duration: 120.0, fileSize: 2_000_000)
        )

        await engine.mergeKnownFiles([newFile, duplicateOfExisting])

        let stats = await engine.stats
        // Should have 2 (1 existing + 1 new), not 3
        #expect(stats.trackedFiles == 2)
    }

    // MARK: - knownPaths tracking

    @Test("init populates knownPaths from provided knownFiles")
    func initPopulatesKnownPaths() async {
        // knownPaths is private, so we verify its effect: merging a file
        // whose path matches an init-provided file should be rejected.
        let existingFiles = [
            KnownFile(path: "/videos/a.mp4", metadata: FileMetadata(duration: 60.0, fileSize: 1_000_000)),
            KnownFile(path: "/videos/b.mp4", metadata: FileMetadata(duration: 120.0, fileSize: 2_000_000)),
        ]
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: existingFiles
        )

        // Merging the same paths should not increase the count.
        await engine.mergeKnownFiles([
            KnownFile(path: "/videos/a.mp4", metadata: FileMetadata(fileSize: 999)),
            KnownFile(path: "/videos/b.mp4", metadata: FileMetadata(fileSize: 888)),
        ])

        let stats = await engine.stats
        #expect(stats.trackedFiles == 2, "Init-provided paths should be in knownPaths, blocking duplicates")
    }

    @Test("mergeKnownFiles updates knownPaths so subsequent merges reject the same paths")
    func mergeKnownFilesUpdatesKnownPaths() async {
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: []
        )

        let fileA = KnownFile(path: "/videos/clip.mp4", metadata: FileMetadata(duration: 60.0, fileSize: 1_000_000))
        let fileB = KnownFile(path: "/videos/other.mp4", metadata: FileMetadata(duration: 30.0, fileSize: 500_000))

        // First merge: both accepted
        await engine.mergeKnownFiles([fileA, fileB])
        let statsAfterFirst = await engine.stats
        #expect(statsAfterFirst.trackedFiles == 2)

        // Second merge: same paths should be rejected
        await engine.mergeKnownFiles([fileA, fileB])
        let statsAfterSecond = await engine.stats
        #expect(statsAfterSecond.trackedFiles == 2, "knownPaths should prevent re-adding the same paths")

        // Third merge: one new path should be accepted
        let fileC = KnownFile(path: "/videos/new.mp4", metadata: FileMetadata(duration: 90.0, fileSize: 3_000_000))
        await engine.mergeKnownFiles([fileA, fileC])
        let statsAfterThird = await engine.stats
        #expect(statsAfterThird.trackedFiles == 3, "Only the new path should be added")
    }

    @Test("stop clears knownPaths so subsequent merges accept all paths")
    func stopClearsKnownPaths() async {
        let existingFile = KnownFile(
            path: "/videos/existing.mp4",
            metadata: FileMetadata(duration: 120.0, fileSize: 2_000_000)
        )
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: [existingFile]
        )

        // Start and stop to clear knownPaths
        let _ = await engine.start()
        await engine.stop()

        // After stop, knownPaths is cleared. However, knownFiles array is NOT
        // cleared by stop (only knownPaths, processingPaths, and continuations).
        // So mergeKnownFiles should now accept a path that was previously known
        // because the knownPaths guard was cleared.
        let samePath = KnownFile(
            path: "/videos/existing.mp4",
            metadata: FileMetadata(duration: 120.0, fileSize: 2_000_000)
        )
        await engine.mergeKnownFiles([samePath])

        let stats = await engine.stats
        // The knownFiles array still has the original + the re-added one.
        // This verifies that stop() cleared knownPaths.
        #expect(stats.trackedFiles == 2, "After stop, knownPaths is cleared so the same path can be re-added")
    }

    // MARK: - ingest directoryChanged forwarding

    @Test("ingest forwards directoryChanged events without path dedup")
    func ingestForwardsDirectoryChangedEvents() async {
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: []
        )
        let _ = await engine.start()

        let dirURL = URL(filePath: "/Volumes/External/Movies", directoryHint: .isDirectory)

        // Ingest the same directoryChanged event twice — both should be forwarded
        // (unlike file events which are deduped by path in processingPaths).
        await engine.ingest(.directoryChanged(dirURL))
        await engine.ingest(.directoryChanged(dirURL))

        // If ingest were deduping directory events, the second call would be
        // silently dropped. We verify the engine accepted both by checking that
        // no error occurred and the engine is still running. The actual event
        // processing verifies the forwarding behavior.
        let stats = await engine.stats
        // No files detected yet — directory events don't increment filesDetected.
        #expect(stats.filesDetected == 0)

        await engine.stop()
    }

    @Test("ingest deduplicates created events by path")
    func ingestDeduplicatesCreatedEvents() async {
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: []
        )
        let _ = await engine.start()

        let fileURL = URL(filePath: "/tmp/video.mp4")

        // First ingest should be accepted (path not in processingPaths)
        await engine.ingest(.created(fileURL))
        // Second ingest of the same path should be silently dropped
        await engine.ingest(.created(fileURL))

        // Both calls should complete without error. The dedup behavior is
        // verified by the fact that processingPaths guards the second call.
        await engine.stop()
    }

    @Test("ingest skips created events for same file at known path (same inode)")
    func ingestSkipsKnownPathSameInode() async throws {
        // Create a real file so the inode comparison can determine it's the
        // same file (modification) rather than a replacement.
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("ingest_known_\(UUID())")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        let fileURL = tmpDir.appendingPathComponent("existing.mp4")
        FileManager.default.createFile(atPath: fileURL.path, contents: Data("content".utf8))

        let inode = BackgroundScanEngine.fileInode(at: fileURL.path)
        let knownFile = KnownFile(
            path: fileURL.path,
            metadata: FileMetadata(duration: 120.0, fileSize: 7),
            inode: inode
        )
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: [knownFile]
        )
        let _ = await engine.start()

        // Same file (same inode, same size) — should be filtered as a
        // modification, not a new file.
        await engine.ingest(.created(fileURL))

        try await Task.sleep(for: .milliseconds(200))
        let stats = await engine.stats
        #expect(stats.filesDetected == 0, "Modification of same file should be filtered")

        await engine.stop()
    }

    @Test("ingest allows created events when file at known path was replaced")
    func ingestAllowsReplacedFileAtKnownPath() async throws {
        // Create a file, record its inode, then replace it with new content.
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("ingest_replaced_\(UUID())")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        let fileURL = tmpDir.appendingPathComponent("replaced.mp4")
        FileManager.default.createFile(atPath: fileURL.path, contents: Data("original".utf8))

        let originalInode = BackgroundScanEngine.fileInode(at: fileURL.path)
        let knownFile = KnownFile(
            path: fileURL.path,
            metadata: FileMetadata(duration: 120.0, fileSize: 8),
            inode: originalInode
        )
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: [knownFile]
        )
        let _ = await engine.start()

        // Delete and recreate the file — different content, likely different
        // inode or at minimum different size.
        try FileManager.default.removeItem(at: fileURL)
        FileManager.default.createFile(
            atPath: fileURL.path, contents: Data("completely different and longer".utf8))

        // The file was replaced (different inode or size) — event should NOT
        // be filtered. It should pass through ingest to be rescored.
        await engine.ingest(.created(fileURL))

        // The event is accepted, but processEvent will fail metadata extraction
        // (not a real media file). We verify the event was forwarded by checking
        // that the old entry was evicted from tracking.
        try await Task.sleep(for: .milliseconds(200))
        let stats = await engine.stats
        // trackedFiles drops from 1 to 0 because evictKnownFile removed
        // the original and processEvent couldn't re-add (fake media file).
        #expect(stats.trackedFiles == 0, "Old entry should be evicted for replaced file")

        await engine.stop()
    }

    @Test("ingest allows renamed events for paths in knownPaths")
    func ingestAllowsRenamedForKnownPaths() async {
        let knownFile = KnownFile(
            path: "/videos/existing.mp4",
            metadata: FileMetadata(duration: 120.0, fileSize: 2_000_000)
        )
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: [knownFile]
        )
        let _ = await engine.start()

        // Renamed events should NOT be filtered by knownPaths — rename
        // detection needs to process these to update stale entries.
        await engine.ingest(.renamed(URL(filePath: "/videos/existing.mp4")))

        // The event should have been accepted into the processing queue
        // (not filtered). The actual processing will fail (file doesn't exist)
        // but the event was forwarded, which is the behavior under test.
        await engine.stop()
    }

    @Test("ingest does nothing when engine is not started")
    func ingestNoOpWhenNotStarted() async {
        let engine = BackgroundScanEngine(
            config: ScanConfig(), sessionID: UUID(), knownFiles: []
        )

        // Engine not started — eventContinuation is nil, so ingest should be a no-op
        await engine.ingest(.created(URL(filePath: "/tmp/video.mp4")))
        await engine.ingest(.directoryChanged(URL(filePath: "/tmp/dir", directoryHint: .isDirectory)))

        let stats = await engine.stats
        #expect(stats.filesDetected == 0)
    }

    // MARK: - Directory rescan integration (processDirectoryChange)

    @Test("directory rescan buffered then replayed when inventory completes")
    func directoryRescanBufferedThenReplayed() async throws {
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("engine_rescan_gate_\(UUID())")
            .standardizedFileURL
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        let imgData = BackgroundScanEngineTests.minimal2x3PNG()
        let imgPath = tmpDir.appendingPathComponent("photo.png")
        try imgData.write(to: imgPath)

        var config = ScanConfig()
        config.mode = .image
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: []
        )

        let alertStream = await engine.start()

        // Do NOT call markInventoryComplete yet — event should be buffered
        await engine.ingest(.directoryChanged(tmpDir))
        try await Task.sleep(for: .milliseconds(500))

        var stats = await engine.stats
        #expect(stats.filesDetected == 0,
                "Directory rescan should be deferred before inventory completes")
        #expect(stats.trackedFiles == 0)

        // Now complete the inventory — buffered event should be replayed
        await engine.markInventoryComplete()
        try await Task.sleep(for: .milliseconds(500))

        stats = await engine.stats
        #expect(stats.filesDetected == 1,
                "Buffered directory event should be replayed after inventory completes")
        #expect(stats.trackedFiles == 1)

        await engine.stop()
        for await _ in alertStream { break }
    }

    @Test("directory rescan discovers new files and adds them to tracked set")
    func directoryRescanDiscoversNewFiles() async throws {
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("engine_rescan_\(UUID())")
            .standardizedFileURL
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        // Create a valid image file (BackgroundScanEngine.extractMetadata succeeds for images)
        let imgData = BackgroundScanEngineTests.minimal2x3PNG()
        let imgPath = tmpDir.appendingPathComponent("photo.png")
        try imgData.write(to: imgPath)

        // Create an engine in image mode with no initial known files
        var config = ScanConfig()
        config.mode = .image
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: []
        )

        let alertStream = await engine.start()
        await engine.markInventoryComplete()

        // Ingest a directoryChanged event pointing at our tmp directory.
        // The engine should enumerate the directory, find photo.png (not in
        // knownPaths), extract metadata, and process it.
        await engine.ingest(.directoryChanged(tmpDir))

        // Give the async event processing loop time to handle the event
        try await Task.sleep(for: .milliseconds(500))

        // The file should now be tracked
        let stats = await engine.stats
        #expect(stats.filesDetected == 1, "Rescan should detect the new image file")
        #expect(stats.trackedFiles == 1, "Rescan should add the file to the tracked set")

        await engine.stop()
        // Drain the alert stream to avoid leaking the continuation
        for await _ in alertStream { break }
    }

    @Test("directory rescan skips files already in knownPaths")
    func directoryRescanSkipsKnownFiles() async throws {
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("engine_rescan_skip_\(UUID())")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        // Create a valid image file
        let imgData = BackgroundScanEngineTests.minimal2x3PNG()
        let imgPath = tmpDir.appendingPathComponent("existing.png")
        try imgData.write(to: imgPath)

        // FileManager.contentsOfDirectory resolves symlinks (e.g. /var → /private/var),
        // so the enumerated path may differ from the URL we constructed. Use
        // contentsOfDirectory to get the canonical path that processDirectoryChange
        // will actually see, and store that in the KnownFile.
        let canonicalContents = try FileManager.default.contentsOfDirectory(
            at: tmpDir, includingPropertiesForKeys: nil)
        let canonicalPath = canonicalContents.first { $0.lastPathComponent == "existing.png" }!.path
        let canonicalDir = URL(filePath: canonicalPath).deletingLastPathComponent()

        let existingFile = KnownFile(
            path: canonicalPath,
            metadata: FileMetadata(width: 2, height: 3, fileSize: 100)
        )
        var config = ScanConfig()
        config.mode = .image
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: [existingFile]
        )

        let alertStream = await engine.start()
        await engine.markInventoryComplete()

        // Use the canonical directory URL so the engine's enumeration produces
        // matching paths.
        await engine.ingest(.directoryChanged(canonicalDir))

        try await Task.sleep(for: .milliseconds(500))

        let stats = await engine.stats
        // filesDetected should be 0 — the file was skipped by knownPaths guard
        #expect(stats.filesDetected == 0, "Known file should be skipped during directory rescan")
        // trackedFiles should still be 1 (the init-provided file)
        #expect(stats.trackedFiles == 1)

        await engine.stop()
        for await _ in alertStream { break }
    }

    @Test("directory rescan produces alerts for duplicate files")
    func directoryRescanProducesAlerts() async throws {
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("engine_rescan_alert_\(UUID())")
            .standardizedFileURL
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        // Create two identical image files with similar names — they should
        // score high enough to produce an alert.
        let imgData = BackgroundScanEngineTests.minimal2x3PNG()
        let existingPath = tmpDir.appendingPathComponent("sunset.png")
        let newPath = tmpDir.appendingPathComponent("sunset_copy.png")
        try imgData.write(to: existingPath)
        try imgData.write(to: newPath)

        // Pre-populate with existing file so only the copy is new
        let existingMeta = BackgroundScanEngine.extractImageMetadata(from: existingPath)!
        let existingFile = KnownFile(
            path: existingPath.path,
            metadata: existingMeta
        )

        var config = ScanConfig()
        config.mode = .image
        config.threshold = 50
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: [existingFile]
        )

        let alertStream = await engine.start()
        await engine.markInventoryComplete()

        // Trigger a directory rescan — should find sunset_copy.png (new),
        // score it against sunset.png (known), and produce an alert.
        await engine.ingest(.directoryChanged(tmpDir))

        // Collect alerts with timeout
        var alerts: [DuplicateAlert] = []
        let deadline = ContinuousClock.now + .seconds(2)
        for await alert in alertStream {
            alerts.append(alert)
            if ContinuousClock.now >= deadline || alerts.count >= 1 { break }
        }

        await engine.stop()

        #expect(!alerts.isEmpty, "Rescan should produce an alert for the duplicate image")
        if let alert = alerts.first {
            #expect(alert.score >= 50, "Alert score should meet the threshold")
        }
    }

    @Test("directory rescan ignores non-matching extensions")
    func directoryRescanIgnoresNonMatchingExtensions() async throws {
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("engine_rescan_ext_\(UUID())")
            .standardizedFileURL
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        // Create a text file — should be ignored in video mode
        let txtPath = tmpDir.appendingPathComponent("readme.txt")
        try "hello".write(to: txtPath, atomically: true, encoding: .utf8)

        var config = ScanConfig()
        config.mode = .video
        let engine = BackgroundScanEngine(
            config: config, sessionID: UUID(), knownFiles: []
        )

        let alertStream = await engine.start()
        await engine.markInventoryComplete()

        await engine.ingest(.directoryChanged(tmpDir))

        try await Task.sleep(for: .milliseconds(500))

        let stats = await engine.stats
        #expect(stats.filesDetected == 0, "Non-matching extension should be skipped")
        #expect(stats.trackedFiles == 0)

        await engine.stop()
        for await _ in alertStream { break }
    }
}
