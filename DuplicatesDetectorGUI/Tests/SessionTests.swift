import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Session Tests

@Suite("Session Data Types")
struct SessionTests {

    // MARK: - Session Init

    @Test("Session init produces .setup phase with default display state")
    func sessionInitDefaults() {
        let session = Session()
        #expect(session.phase == .setup)
        #expect(session.display.viewMode == .pairs)
        #expect(session.display.searchText == "")
        #expect(session.display.sortOrder == .scoreDescending)
        #expect(session.config == nil)
        #expect(session.scan == nil)
        #expect(session.results == nil)
        #expect(session.watch == nil)
        #expect(session.pendingReplayURL == nil)
        #expect(session.scanSequence == 0)
        #expect(session.lastScanConfig == nil)
        #expect(session.lastOriginalEnvelope == nil)
        #expect(session.lastPausedSessionId == nil)
        #expect(session.pendingSession == nil)
    }

    // MARK: - Resolution Equality

    @Test("Resolution .active equals .active")
    func resolutionActiveEquality() {
        #expect(Resolution.active == Resolution.active)
    }

    @Test("Resolution .resolved with matching ActionRecord")
    func resolutionResolvedEquality() {
        let record = ActionRecord(
            pairID: PairIdentifier(fileA: "/tmp/dup.mp4", fileB: "/tmp/orig.mp4"),
            timestamp: Date(timeIntervalSince1970: 1_711_526_400),
            action: "trash",
            actedOnPath: "/tmp/dup.mp4",
            keptPath: "/tmp/orig.mp4",
            bytesFreed: 1024,
            score: 85,
            strategy: "newest",
            destination: nil
        )
        let a = Resolution.resolved(record)
        let b = Resolution.resolved(record)
        #expect(a == b)
    }

    @Test("Resolution .active does not equal .resolved")
    func resolutionMismatch() {
        let record = ActionRecord(
            pairID: PairIdentifier(fileA: "/tmp/dup.mp4", fileB: "/tmp/other.mp4"),
            timestamp: Date(timeIntervalSince1970: 1_711_526_400),
            action: "trash",
            actedOnPath: "/tmp/dup.mp4",
            keptPath: "/tmp/other.mp4",
            bytesFreed: nil,
            score: 50,
            strategy: nil,
            destination: nil
        )
        #expect(Resolution.active != Resolution.resolved(record))
    }

    @Test("Resolution .probablySolved equality")
    func resolutionProbablySolvedEquality() {
        let a = Resolution.probablySolved(missing: ["/a.mp4"])
        let b = Resolution.probablySolved(missing: ["/a.mp4"])
        #expect(a == b)
    }

    // MARK: - DisplayState

    @Test("DisplayState.initial(for:) returns .pairs for pairs content")
    func displayStateInitialPairs() {
        let content = ScanContent.pairs([])
        let display = DisplayState.initial(for: content)
        #expect(display.viewMode == .pairs)
    }

    @Test("DisplayState.initial(for:) returns .groups for groups content")
    func displayStateInitialGroups() {
        let content = ScanContent.groups([])
        let display = DisplayState.initial(for: content)
        #expect(display.viewMode == .groups)
    }

    // MARK: - FileStatus Equality

    @Test("FileStatus equality")
    func fileStatusEquality() {
        #expect(FileStatus.present == FileStatus.present)
        #expect(FileStatus.missing == FileStatus.missing)
        #expect(FileStatus.present != FileStatus.missing)
        #expect(FileStatus.moved(to: "/a") == FileStatus.moved(to: "/a"))
        #expect(FileStatus.moved(to: "/a") != FileStatus.moved(to: "/b"))
        #expect(FileStatus.present != FileStatus.moved(to: "/a"))
    }

    // MARK: - ActionRecord Codable Round-Trip

    @Test("ActionRecord Codable round-trip preserves all fields")
    func actionRecordCodableRoundTrip() throws {
        let ts = Date(timeIntervalSince1970: 1_711_526_400)
        let original = ActionRecord(
            pairID: PairIdentifier(fileA: "/Users/test/dup.mp4", fileB: "/Users/test/orig.mp4"),
            timestamp: ts,
            action: "trash",
            actedOnPath: "/Users/test/dup.mp4",
            keptPath: "/Users/test/orig.mp4",
            bytesFreed: 2048,
            score: 92,
            strategy: "biggest",
            destination: "/Users/test/trash/"
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(original)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(ActionRecord.self, from: data)

        #expect(decoded == original)
        #expect(decoded.timestamp == ts)
        #expect(decoded.action == "trash")
        #expect(decoded.actedOnPath == "/Users/test/dup.mp4")
        #expect(decoded.keptPath == "/Users/test/orig.mp4")
        #expect(decoded.bytesFreed == 2048)
        #expect(decoded.score == 92)
        #expect(decoded.strategy == "biggest")
        #expect(decoded.destination == "/Users/test/trash/")
    }

    @Test("ActionRecord Codable round-trip with nil optionals")
    func actionRecordCodableNilFields() throws {
        let ts = Date(timeIntervalSince1970: 1_711_526_400)
        let original = ActionRecord(
            pairID: PairIdentifier(fileA: "/tmp/file.mp4", fileB: "/tmp/other.mp4"),
            timestamp: ts,
            action: "delete",
            actedOnPath: "/tmp/file.mp4",
            keptPath: "/tmp/other.mp4",
            bytesFreed: nil,
            score: 50,
            strategy: nil,
            destination: nil
        )

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(ActionRecord.self, from: data)

        #expect(decoded == original)
        #expect(decoded.bytesFreed == nil)
        #expect(decoded.strategy == nil)
        #expect(decoded.destination == nil)
    }

    // MARK: - WatchConfig Codable Round-Trip

    @Test("WatchConfig Codable round-trip preserves all fields")
    func watchConfigCodableRoundTrip() throws {
        let original = WatchConfig(
            directories: ["/Users/test/Videos", "/Users/test/Downloads"],
            mode: .video,
            threshold: 60,
            extensions: "mp4,mov",
            weights: ["filename": 50.0, "duration": 30.0]
        )

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(WatchConfig.self, from: data)

        #expect(decoded == original)
        #expect(decoded.directories == ["/Users/test/Videos", "/Users/test/Downloads"])
        #expect(decoded.mode == .video)
        #expect(decoded.threshold == 60)
        #expect(decoded.extensions == "mp4,mov")
        #expect(decoded.weights == ["filename": 50.0, "duration": 30.0])
    }

    @Test("WatchConfig default init")
    func watchConfigDefaults() {
        let config = WatchConfig()
        #expect(config.directories.isEmpty)
        #expect(config.mode == .video)
        #expect(config.threshold == 50)
        #expect(config.extensions == nil)
        #expect(config.weights == nil)
    }

    // MARK: - SessionMetadata Codable Round-Trip

    @Test("SessionMetadata Codable round-trip preserves all fields")
    func sessionMetadataCodableRoundTrip() throws {
        let now = Date(timeIntervalSince1970: 1_711_526_400) // fixed date for determinism
        let original = SessionMetadata(
            createdAt: now,
            directories: ["/Users/test/Videos"],
            sourceLabel: "Test Scan",
            mode: .image,
            pairCount: 10,
            fileCount: 25
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(original)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(SessionMetadata.self, from: data)

        #expect(decoded == original)
        #expect(decoded.sourceLabel == "Test Scan")
        #expect(decoded.mode == .image)
        #expect(decoded.createdAt == now)
        #expect(decoded.directories == ["/Users/test/Videos"])
        #expect(decoded.pairCount == 10)
        #expect(decoded.fileCount == 25)
    }

    @Test("SessionMetadata Codable round-trip with all modes")
    func sessionMetadataCodableAllModes() throws {
        for mode in ScanMode.allCases {
            let original = SessionMetadata(mode: mode)
            let data = try JSONEncoder().encode(original)
            let decoded = try JSONDecoder().decode(SessionMetadata.self, from: data)
            #expect(decoded.mode == mode)
        }
    }

    // MARK: - ResultsSnapshot

    @Test("ResultsSnapshot.incrementFilterGeneration increments the counter")
    func resultsSnapshotIncrementFilterGeneration() {
        let envelope = ScanEnvelope(
            version: "1.0",
            generatedAt: "",
            args: ScanArgs(
                directories: [], threshold: 50, content: false,
                weights: nil, keep: nil, action: "delete",
                group: false, sort: "score", mode: "video",
                embedThumbnails: false
            ),
            stats: ScanStats(
                filesScanned: 0, filesAfterFilter: 0,
                totalPairsScored: 0, pairsAboveThreshold: 0,
                groupsCount: nil, spaceRecoverable: nil,
                scanTime: 0, extractTime: 0, filterTime: 0,
                contentHashTime: 0, scoringTime: 0, totalTime: 0
            ),
            content: .pairs([]),
            dryRunSummary: nil
        )
        var snapshot = ResultsSnapshot(envelope: envelope)
        #expect(snapshot.filterGeneration == 0)

        snapshot.incrementFilterGeneration()
        #expect(snapshot.filterGeneration == 1)

        snapshot.incrementFilterGeneration()
        #expect(snapshot.filterGeneration == 2)
    }

    // MARK: - ScanProgress

    @Test("ScanProgress default init has empty stages")
    func scanProgressDefaults() {
        let progress = ScanProgress()
        #expect(progress.stages.isEmpty)
        #expect(progress.isCancelling == false)
        #expect(progress.isFinalizingResults == false)
        #expect(progress.isComplete == false)
        #expect(progress.activeStage == nil)
        #expect(progress.overallProgress == 0)
    }

    @Test("ScanProgress.initialStages creates correct pipeline")
    func scanProgressInitialStages() {
        let stages = ScanProgress.initialStages(mode: .video, content: true, audio: true)
        let names = stages.map(\.id)
        #expect(names.contains(.scan))
        #expect(names.contains(.extract))
        #expect(names.contains(.filter))
        #expect(names.contains(.contentHash))
        #expect(names.contains(.audioFingerprint))
        #expect(names.contains(.score))
        #expect(names.contains(.report))
    }

    @Test("ScanProgress.replayStages creates correct pipeline")
    func scanProgressReplayStages() {
        let stages = ScanProgress.replayStages()
        let names = stages.map(\.id)
        #expect(names.contains(.replay))
        #expect(names.contains(.filter))
        #expect(names.contains(.report))
        #expect(!names.contains(.scan))
        #expect(!names.contains(.extract))
    }

    @Test("ScanProgress.formatElapsed formats correctly")
    func scanProgressFormatElapsed() {
        #expect(ScanProgress.formatElapsed(0.5) == "500ms")
        #expect(ScanProgress.formatElapsed(1.5) == "1.5s")
        #expect(ScanProgress.formatElapsed(90) == "1m 30s")
    }

    // MARK: - PauseState

    @Test("PauseState enum cases")
    func pauseStateCases() {
        #expect(PauseState.running == PauseState.running)
        #expect(PauseState.pausing(sessionId: "abc") == PauseState.pausing(sessionId: "abc"))
        #expect(PauseState.paused(sessionId: "abc") == PauseState.paused(sessionId: "abc"))
        #expect(PauseState.running != PauseState.pausing(sessionId: nil))
        #expect(PauseState.pausing(sessionId: "a") != PauseState.paused(sessionId: "a"))
    }

    @Test("ScanTiming has pause fields")
    func scanTimingPauseFields() {
        let timing = ScanTiming()
        #expect(timing.pauseStartTime == nil)
        #expect(timing.accumulatedPauseDuration == 0)
    }

    // MARK: - CacheStats

    @Test("CacheStats defaults are all zero")
    func cacheStatsDefaults() {
        let stats = CacheStats()
        #expect(stats.cacheHits == 0)
        #expect(stats.cacheMisses == 0)
        #expect(stats.cacheTimeSaved == nil)
        #expect(stats.metadataCacheHits == 0)
        #expect(stats.metadataCacheMisses == 0)
        #expect(stats.contentCacheHits == 0)
        #expect(stats.contentCacheMisses == 0)
        #expect(stats.audioCacheHits == 0)
        #expect(stats.audioCacheMisses == 0)
        #expect(stats.scoreCacheHits == 0)
        #expect(stats.scoreCacheMisses == 0)
    }

    // MARK: - Session Phase Equality

    @Test("Session.Phase equality")
    func sessionPhaseEquality() {
        #expect(Session.Phase.setup == Session.Phase.setup)
        #expect(Session.Phase.scanning == Session.Phase.scanning)
        #expect(Session.Phase.results == Session.Phase.results)
        #expect(Session.Phase.setup != Session.Phase.scanning)

        let error1 = ErrorInfo(message: "test error")
        let error2 = ErrorInfo(message: "test error")
        let error3 = ErrorInfo(message: "different error")
        #expect(Session.Phase.error(error1) == Session.Phase.error(error2))
        #expect(Session.Phase.error(error1) != Session.Phase.error(error3))
    }

    // MARK: - ActionError

    @Test("ActionError equality")
    func actionErrorEquality() {
        let a = ActionError(message: "File not found")
        let b = ActionError(message: "File not found")
        let c = ActionError(message: "Permission denied")
        #expect(a == b)
        #expect(a != c)
    }

    // MARK: - BulkProgress

    @Test("BulkProgress equality")
    func bulkProgressEquality() {
        let a = BulkProgress(completed: 5, total: 10)
        let b = BulkProgress(completed: 5, total: 10)
        let c = BulkProgress(completed: 3, total: 10)
        #expect(a == b)
        #expect(a != c)
    }
}
