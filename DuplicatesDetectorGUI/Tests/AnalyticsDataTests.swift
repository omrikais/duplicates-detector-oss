import Foundation
import Testing

@testable import DuplicatesDetector

@Suite("AnalyticsData")
struct AnalyticsDataTests {
    private func loadFixture(_ name: String) throws -> Data {
        try FixtureLoader.data(named: name)
    }

    @Test("Decodes analytics from pair envelope")
    func decodesFromPairEnvelope() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        #expect(envelope.analytics != nil)

        let analytics = try #require(envelope.analytics)
        #expect(analytics.directoryStats.count == 1)
        #expect(analytics.scoreDistribution.count == 2)
        #expect(analytics.filetypeBreakdown.count == 2)
        #expect(analytics.creationTimeline.count == 2)
    }

    @Test("Directory stats fields decode correctly")
    func directoryStatFields() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        let stat = try #require(envelope.analytics?.directoryStats.first)

        #expect(stat.path == "/videos")
        #expect(stat.totalFiles == 10)
        #expect(stat.duplicateFiles == 4)
        #expect(stat.totalSize == 50_000_000)
        #expect(stat.recoverableSize == 20_000_000)
        #expect(stat.duplicateDensity == 0.4)
    }

    @Test("Score distribution fields decode correctly")
    func scoreDistributionFields() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        let buckets = try #require(envelope.analytics?.scoreDistribution)

        #expect(buckets[0].range == "60-65")
        #expect(buckets[0].min == 60)
        #expect(buckets[0].max == 65)
        #expect(buckets[0].count == 1)

        #expect(buckets[1].range == "85-90")
        #expect(buckets[1].min == 85)
        #expect(buckets[1].max == 90)
        #expect(buckets[1].count == 1)
    }

    @Test("Filetype breakdown decodes 'extension' key via CodingKeys")
    func filetypeBreakdownFields() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        let entries = try #require(envelope.analytics?.filetypeBreakdown)

        #expect(entries[0].ext == ".mp4")
        #expect(entries[0].count == 8)
        #expect(entries[0].size == 40_000_000)

        #expect(entries[1].ext == ".mkv")
        #expect(entries[1].count == 2)
        #expect(entries[1].size == 10_000_000)
    }

    @Test("Creation timeline fields decode correctly")
    func creationTimelineFields() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        let entries = try #require(envelope.analytics?.creationTimeline)

        #expect(entries[0].date == "2024-01-15")
        #expect(entries[0].totalFiles == 6)
        #expect(entries[0].duplicateFiles == 4)

        #expect(entries[1].date == "2024-01-16")
        #expect(entries[1].totalFiles == 4)
        #expect(entries[1].duplicateFiles == 0)
    }

    @Test("Analytics decodes as nil when absent from envelope")
    func decodesNilWhenAbsent() throws {
        let data = try loadFixture("envelope-groups.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)

        #expect(envelope.analytics == nil)
    }

    @Test("Identifiable conformance uses expected id values")
    func identifiableConformance() throws {
        let data = try loadFixture("envelope-pairs.json")
        let envelope = try JSONEnvelopeParser.parse(data: data)
        let analytics = try #require(envelope.analytics)

        #expect(analytics.directoryStats[0].id == "/videos")
        #expect(analytics.scoreDistribution[0].id == "60-65")
        #expect(analytics.filetypeBreakdown[0].id == ".mp4")
        #expect(analytics.creationTimeline[0].id == "2024-01-15")
    }

    @Test("Round-trip encode and decode preserves analytics")
    func roundTrip() throws {
        let data = try loadFixture("envelope-pairs.json")
        let original = try JSONEnvelopeParser.parse(data: data)

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let encoded = try encoder.encode(original)
        let decoded = try CLIDecoder.shared.decode(ScanEnvelope.self, from: encoded)

        #expect(decoded.analytics == original.analytics)
    }

    // MARK: - Recompute Analytics

    @Test("recomputeAnalytics updates score distribution from current pairs")
    func recomputeUpdatesScoreDistribution() {
        let initialAnalytics = AnalyticsData(
            directoryStats: [DirectoryStat(path: "/videos", totalFiles: 10, duplicateFiles: 2, totalSize: 1000, recoverableSize: 500, duplicateDensity: 0.2)],
            scoreDistribution: [ScoreBucket(range: "80-85", min: 80, max: 85, count: 1)],
            filetypeBreakdown: [FiletypeEntry(ext: ".mp4", count: 2, size: 2000)],
            creationTimeline: [TimelineEntry(date: "2024-01-15", totalFiles: 10, duplicateFiles: 2)]
        )
        var envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 1, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 82.0)
            ]),
            analytics: initialAnalytics
        )

        // Simulate watch mode: append a new pair with a different score bucket
        if case .pairs(var existing) = envelope.content {
            existing.append(makePair(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 63.0))
            envelope.content = .pairs(existing)
        }

        var snapshot = ResultsSnapshot(envelope: envelope)
        snapshot.analyticsData = initialAnalytics // simulate initial state
        snapshot.recomputeAnalytics()

        let updated = try! #require(snapshot.analyticsData)

        // Should now have buckets covering both score 82 and score 63
        let bucketRanges = Set(updated.scoreDistribution.map(\.range))
        #expect(bucketRanges.contains("80-85"))
        #expect(bucketRanges.contains("60-65"))
        #expect(updated.scoreDistribution.reduce(0) { $0 + $1.count } == 2)

        // directoryStats and creationTimeline should be preserved
        #expect(updated.directoryStats == initialAnalytics.directoryStats)
        #expect(updated.creationTimeline == initialAnalytics.creationTimeline)

        // envelope.analytics must be synced for persistence round-trip
        #expect(snapshot.envelope.analytics == updated)
    }

    @Test("recomputeAnalytics updates filetype breakdown from current pairs")
    func recomputeUpdatesFiletypeBreakdown() {
        let initialAnalytics = AnalyticsData(
            directoryStats: [],
            scoreDistribution: [],
            filetypeBreakdown: [FiletypeEntry(ext: ".mp4", count: 2, size: 2_000_000)],
            creationTimeline: []
        )
        let envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 2, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85.0),
                makePair(fileA: "/videos/c.mkv", fileB: "/videos/d.mkv", score: 75.0),
            ]),
            analytics: initialAnalytics
        )

        var snapshot = ResultsSnapshot(envelope: envelope)
        snapshot.analyticsData = initialAnalytics
        snapshot.recomputeAnalytics()

        let updated = try! #require(snapshot.analyticsData)
        let extMap = Dictionary(uniqueKeysWithValues: updated.filetypeBreakdown.map { ($0.ext, $0.count) })
        #expect(extMap[".mp4"] == 2)
        #expect(extMap[".mkv"] == 2)
    }

    @Test("recomputeAnalytics is a no-op when analyticsData is nil")
    func recomputeNoOpWhenNil() {
        let envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 0, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([])
        )

        var snapshot = ResultsSnapshot(envelope: envelope)
        #expect(snapshot.analyticsData == nil)
        snapshot.recomputeAnalytics()
        #expect(snapshot.analyticsData == nil)
    }

    // MARK: - Space Recoverable

    @Test("computeSpaceRecoverable sums smaller file per pair, deduped by path")
    func computeSpaceRecoverableBasic() {
        let envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 2, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([
                // Pair 1: smaller is fileA (500K vs 900K)
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85.0, fileSizeA: 500_000, fileSizeB: 900_000),
                // Pair 2: smaller is fileB (800K vs 300K)
                makePair(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 75.0, fileSizeA: 800_000, fileSizeB: 300_000),
            ])
        )
        let snapshot = ResultsSnapshot(envelope: envelope)
        // 500K + 300K = 800K
        #expect(snapshot.computeSpaceRecoverable() == 800_000)
    }

    @Test("computeSpaceRecoverable skips both-reference pairs")
    func computeSpaceRecoverableSkipsBothReference() {
        let envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 1, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85.0, fileAIsReference: true, fileBIsReference: true),
            ])
        )
        let snapshot = ResultsSnapshot(envelope: envelope)
        #expect(snapshot.computeSpaceRecoverable() == 0)
    }

    @Test("computeSpaceRecoverable picks non-reference file when one is reference")
    func computeSpaceRecoverableReferencePick() {
        let envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 1, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([
                // fileA is reference (larger), so fileB (300K) is the candidate even though fileA is bigger
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85.0, fileSizeA: 1_000_000, fileSizeB: 300_000, fileAIsReference: true),
            ])
        )
        let snapshot = ResultsSnapshot(envelope: envelope)
        #expect(snapshot.computeSpaceRecoverable() == 300_000)
    }

    @Test("computeSpaceRecoverable deduplicates by path")
    func computeSpaceRecoverableDedupes() {
        let envelope = ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(directories: ["/videos"], threshold: 50, content: false, weights: nil, keep: "a", action: "trash", group: false, sort: "score", mode: "video", embedThumbnails: false),
            stats: ScanStats(filesScanned: 10, filesAfterFilter: 8, totalPairsScored: 10, pairsAboveThreshold: 2, scanTime: 1.0, extractTime: 1.0, filterTime: 0.1, contentHashTime: 0.0, scoringTime: 1.0, totalTime: 3.0),
            content: .pairs([
                // Same smaller file (a.mp4) appears in two pairs
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85.0, fileSizeA: 500_000, fileSizeB: 900_000),
                makePair(fileA: "/videos/a.mp4", fileB: "/videos/c.mp4", score: 75.0, fileSizeA: 500_000, fileSizeB: 800_000),
            ])
        )
        let snapshot = ResultsSnapshot(envelope: envelope)
        // a.mp4 counted only once = 500K
        #expect(snapshot.computeSpaceRecoverable() == 500_000)
    }
}

// MARK: - Helpers

private func makePair(
    fileA: String = "/videos/a.mp4",
    fileB: String = "/videos/b.mp4",
    score: Double = 85.0,
    fileSizeA: Int = 1_000_000,
    fileSizeB: Int = 900_000,
    fileAIsReference: Bool = false,
    fileBIsReference: Bool = false
) -> PairResult {
    PairResult(
        fileA: fileA,
        fileB: fileB,
        score: score,
        breakdown: ["filename": 40.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: fileSizeA),
        fileBMetadata: FileMetadata(fileSize: fileSizeB),
        fileAIsReference: fileAIsReference,
        fileBIsReference: fileBIsReference,
        keep: "a"
    )
}
