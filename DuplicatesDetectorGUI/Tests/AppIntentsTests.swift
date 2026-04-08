import AppIntents
import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("App Intent Entities")
struct AppIntentsTests {

    // MARK: - ScanModeEntity

    @Test("ScanModeEntity converts to ScanMode", arguments: [
        (ScanModeEntity.video, ScanMode.video),
        (ScanModeEntity.image, ScanMode.image),
        (ScanModeEntity.audio, ScanMode.audio),
        (ScanModeEntity.auto, ScanMode.auto),
    ])
    func modeConversion(entity: ScanModeEntity, expected: ScanMode) {
        #expect(entity.toScanMode == expected)
    }

    @Test("ScanModeEntity has display representations for all cases")
    func modeDisplayRepresentations() {
        for mode in ScanModeEntity.allCases {
            let rep = ScanModeEntity.caseDisplayRepresentations[mode]
            #expect(rep != nil, "Missing display representation for \(mode)")
        }
    }

    @Test("ScanModeEntity type display representation exists")
    func modeTypeDisplayRepresentation() {
        let rep = ScanModeEntity.typeDisplayRepresentation
        // Just verify it's accessible and non-empty.
        #expect(rep.name != nil)
    }

    // MARK: - ScanSummaryEntity

    @Test("ScanSummaryEntity stores properties correctly")
    func scanSummaryProperties() {
        let summary = ScanSummaryEntity(
            pairCount: 42,
            filesScanned: 100,
            topScore: 95.5,
            scanDuration: 12.3
        )
        #expect(summary.pairCount == 42)
        #expect(summary.filesScanned == 100)
        #expect(summary.topScore == 95.5)
        #expect(summary.scanDuration == 12.3)
    }

    @Test("ScanSummaryEntity default init has zero values")
    func scanSummaryDefaultInit() {
        let summary = ScanSummaryEntity()
        #expect(summary.pairCount == 0)
        #expect(summary.filesScanned == 0)
        #expect(summary.topScore == 0)
        #expect(summary.scanDuration == 0)
    }

    @Test("ScanSummaryEntity displayRepresentation title shows pair count")
    func scanSummaryDisplayRepresentation() {
        let summary = ScanSummaryEntity(
            pairCount: 42,
            filesScanned: 100,
            topScore: 95.5,
            scanDuration: 12.3
        )
        let rep = summary.displayRepresentation
        let title = String(localized: rep.title)
        #expect(title == "42 duplicate pairs found")
        let subtitle = rep.subtitle.map { String(localized: $0) }
        #expect(subtitle == "100 files scanned in 12.3s")
    }

    // MARK: - PairSummaryEntity

    @Test("PairSummaryEntity stores properties correctly")
    func pairSummaryProperties() {
        let pair = PairSummaryEntity(
            fileA: "/path/to/video1.mp4",
            fileB: "/path/to/video2.mp4",
            score: 87.5
        )
        #expect(pair.fileA == "/path/to/video1.mp4")
        #expect(pair.fileB == "/path/to/video2.mp4")
        #expect(pair.score == 87.5)
    }

    @Test("PairSummaryEntity displayRepresentation shows filenames and score")
    func pairSummaryDisplayRepresentation() {
        let pair = PairSummaryEntity(
            fileA: "/Users/test/Videos/clip_a.mp4",
            fileB: "/Users/test/Videos/clip_b.mp4",
            score: 87.5
        )
        let rep = pair.displayRepresentation
        let title = String(localized: rep.title)
        // Title format: "fileA_name ↔ fileB_name"
        #expect(title == "clip_a.mp4 \u{2194} clip_b.mp4")
        let subtitle = rep.subtitle.map { String(localized: $0) }
        // Score truncated to Int: 87
        #expect(subtitle == "Score: 87")
    }

    @Test("PairSummaryEntity default init sets empty strings and zero score")
    func pairSummaryDefaultInit() {
        let pair = PairSummaryEntity()
        #expect(pair.fileA == "")
        #expect(pair.fileB == "")
        #expect(pair.score == 0)
    }

    // MARK: - LastScanEntity

    @Test("LastScanEntity stores properties correctly")
    func lastScanProperties() {
        let date = Date()
        let lastScan = LastScanEntity(
            pairCount: 10,
            scanDate: date,
            directories: ["/videos", "/photos"],
            mode: "video",
            topPairs: [PairSummaryEntity(fileA: "a.mp4", fileB: "b.mp4", score: 90)]
        )
        #expect(lastScan.pairCount == 10)
        #expect(lastScan.scanDate == date)
        #expect(lastScan.directories.count == 2)
        #expect(lastScan.mode == "video")
        #expect(lastScan.topPairs.count == 1)
    }

    @Test("LastScanEntity displayRepresentation shows mode and pair count")
    func lastScanDisplayRepresentation() {
        let date = Date(timeIntervalSince1970: 0)
        let lastScan = LastScanEntity(
            pairCount: 10,
            scanDate: date,
            directories: ["/videos"],
            mode: "video",
            topPairs: []
        )
        let rep = lastScan.displayRepresentation
        let title = String(localized: rep.title)
        #expect(title == "10 pairs found")
        let subtitle = rep.subtitle.map { String(localized: $0) }
        // Subtitle format: "<mode> scan on <formatted date>"
        #expect(subtitle != nil)
        #expect(subtitle!.hasPrefix("video scan on"))
    }

    @Test("LastScanEntity default init has sensible defaults")
    func lastScanDefaultInit() {
        let lastScan = LastScanEntity()
        #expect(lastScan.pairCount == 0)
        #expect(lastScan.directories.isEmpty)
        #expect(lastScan.mode == "video")
        #expect(lastScan.topPairs.isEmpty)
    }

    // MARK: - ScanHistoryEntity

    @Test("ScanHistoryEntity created from SessionRegistry.Entry")
    func scanHistoryFromEntry() {
        let id = UUID()
        let date = Date()
        let entry = SessionRegistry.Entry(
            id: id,
            createdAt: date,
            directories: ["/test/videos"],
            mode: .image,
            pairCount: 5,
            sourceLabel: "videos",
            hasWatchConfig: false
        )
        let entity = ScanHistoryEntity(from: entry)
        #expect(entity.id == id)
        #expect(entity.scanDate == date)
        #expect(entity.directories == ["/test/videos"])
        #expect(entity.mode == "image")
        #expect(entity.pairCount == 5)
    }

    @Test("ScanHistoryEntity displayRepresentation shows pair count and mode")
    func scanHistoryDisplayRepresentation() {
        let entity = ScanHistoryEntity(
            id: UUID(),
            scanDate: Date(),
            directories: ["/Users/test/Videos", "/Users/test/Photos"],
            mode: "image",
            pairCount: 7
        )
        let rep = entity.displayRepresentation
        let title = String(localized: rep.title)
        // Title format: "<pairCount> pairs - <mode>"
        #expect(title == "7 pairs - image")
        let subtitle = rep.subtitle.map { String(localized: $0) }
        // Subtitle shows last path components joined by ", "
        #expect(subtitle == "Videos, Photos")
    }

    // MARK: - DuplicatesDetectorShortcuts

    @Test("appShortcuts contains expected number of shortcuts")
    func appShortcutsCount() {
        let shortcuts = DuplicatesDetectorShortcuts.appShortcuts
        #expect(shortcuts.count == 4)
    }

    @Test("resolvedRegistry returns sharedRegistry when set")
    func resolvedRegistryReturnsShared() async {
        let registry = SessionRegistry()
        DuplicatesDetectorShortcuts.sharedRegistry = registry
        let resolved = await DuplicatesDetectorShortcuts.resolvedRegistry()
        #expect(resolved === registry)
        // Clean up to avoid leaking state to other tests.
        DuplicatesDetectorShortcuts.sharedRegistry = nil
    }

    // MARK: - IntentError

    @Test("IntentError provides localized descriptions")
    func intentErrorDescriptions() {
        let errors: [IntentError] = [
            .directoryNotAccessible,
            .notADirectory,
            .scanFailed,
            .noScanHistory,
        ]
        for error in errors {
            // Just verify each has a non-empty description.
            let desc = error.localizedStringResource
            #expect(desc != nil)
        }
    }
}
