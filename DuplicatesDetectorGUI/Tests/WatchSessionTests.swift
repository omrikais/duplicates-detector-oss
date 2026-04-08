// Tests/WatchSessionTests.swift
import Foundation
import Testing
@testable import DuplicatesDetector

@Suite("Watch Session Models")
struct WatchSessionTests {

    @Test("KnownFile stores path and metadata")
    func knownFileBasics() {
        let meta = FileMetadata(fileSize: 1024)
        let kf = KnownFile(path: "/tmp/a.mp4", metadata: meta)
        #expect(kf.path == "/tmp/a.mp4")
        #expect(kf.metadata.fileSize == 1024)
        #expect(kf.contentHash == nil)
        #expect(kf.audioFingerprint == nil)
    }

    @Test("KnownFile with content hash and fingerprint")
    func knownFileWithOptionals() {
        let meta = FileMetadata(fileSize: 2048)
        let kf = KnownFile(
            path: "/tmp/b.mp4", metadata: meta,
            contentHash: "abc123", audioFingerprint: Data([0x01, 0x02])
        )
        #expect(kf.contentHash == "abc123")
        #expect(kf.audioFingerprint == Data([0x01, 0x02]))
    }

    @Test("WatchStats defaults")
    func watchStatsDefaults() {
        let stats = WatchStats(trackedFiles: 42)
        #expect(stats.filesDetected == 0)
        #expect(stats.duplicatesFound == 0)
        #expect(stats.trackedFiles == 42)
    }

    @Test("DuplicateAlert stores all fields")
    func duplicateAlertFields() {
        let alert = DuplicateAlert(
            newFile: URL(filePath: "/tmp/new.mp4"),
            matchedFile: URL(filePath: "/tmp/old.mp4"),
            score: 85,
            detail: ["filename": DetailScore(raw: 0.8, weight: 50.0),
                     "duration": DetailScore(raw: 1.0, weight: 30.0)],
            timestamp: Date(timeIntervalSince1970: 1000),
            sessionID: UUID(),
            newMetadata: FileMetadata(fileSize: 0),
            matchedMetadata: FileMetadata(fileSize: 0)
        )
        #expect(alert.score == 85)
        #expect(alert.detail.count == 2)
    }

    @Test("WatchSession identity is by UUID")
    func watchSessionIdentity() {
        let id = UUID()
        var config = ScanConfig()
        config.directories = ["/tmp"]
        let session = WatchSession(
            id: id, config: config,
            stats: WatchStats(trackedFiles: 0),
            startedAt: .now,
            sourceLabel: "Test scan"
        )
        #expect(session.id == id)
        #expect(session.mode == .video)
        #expect(session.sourceLabel == "Test scan")
    }
}
