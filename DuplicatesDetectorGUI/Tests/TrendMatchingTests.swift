import Foundation
import Testing

@testable import DuplicatesDetector

@Suite struct TrendMatchingTests {

    // MARK: - Helpers

    /// Build a minimal `SessionRegistry.Entry` with enrichment fields.
    private func makeEntry(
        id: UUID = UUID(),
        createdAt: Date = Date(),
        directories: [String] = ["/videos"],
        mode: ScanMode = .video,
        pairCount: Int = 5,
        filesScanned: Int? = 100,
        spaceRecoverable: Int? = 50_000,
        groupsCount: Int? = nil
    ) -> SessionRegistry.Entry {
        SessionRegistry.Entry(
            id: id,
            createdAt: createdAt,
            directories: directories,
            mode: mode,
            pairCount: pairCount,
            sourceLabel: directories.joined(separator: ", "),
            hasWatchConfig: false,
            filesScanned: filesScanned,
            spaceRecoverable: spaceRecoverable,
            groupsCount: groupsCount
        )
    }

    // MARK: - Tests

    @Test("Matches entries with identical directories and same mode")
    func matchesSameDirectories() {
        let entries = [
            makeEntry(directories: ["/videos"], filesScanned: 100),
            makeEntry(directories: ["/photos"], filesScanned: 50),
        ]
        let matches = SessionRegistry.findMatchingScans(for: ["/videos"], mode: .video, in: entries)
        #expect(matches.count == 1)
        #expect(matches[0].directories == ["/videos"])
    }

    @Test("Excludes legacy entries where filesScanned is nil")
    func excludesLegacyEntries() {
        let entries = [
            makeEntry(directories: ["/videos"], filesScanned: nil),
            makeEntry(directories: ["/videos"], filesScanned: 100),
        ]
        let matches = SessionRegistry.findMatchingScans(for: ["/videos"], mode: .video, in: entries)
        #expect(matches.count == 1)
        #expect(matches[0].filesScanned == 100)
    }

    @Test("Requires at least 50% Jaccard directory overlap")
    func requiresFiftyPercentJaccardOverlap() {
        // Jaccard: intersection / union
        // 1 of 4 union = 25% -- should NOT match
        let lowOverlap = makeEntry(directories: ["/a"])
        // {/a, /b} ∩ {/a, /b, /c, /d} = {/a, /b}, union = {/a, /b, /c, /d}, Jaccard = 2/4 = 50% -- should match
        let halfOverlap = makeEntry(directories: ["/a", "/b"])

        let entries = [lowOverlap, halfOverlap]
        let matches = SessionRegistry.findMatchingScans(
            for: ["/a", "/b", "/c", "/d"],
            mode: .video,
            in: entries
        )
        #expect(matches.count == 1)
        #expect(Set(matches[0].directories) == Set(["/a", "/b"]))
    }

    @Test("Limits results to 10 entries maximum")
    func limitsToTen() {
        let entries = (0..<15).map { i in
            makeEntry(
                createdAt: Date(timeIntervalSince1970: Double(i) * 86400),
                directories: ["/videos"],
                filesScanned: 100 + i
            )
        }
        let matches = SessionRegistry.findMatchingScans(for: ["/videos"], mode: .video, in: entries)
        #expect(matches.count == 10)
        // Should keep the 10 most recent (suffix of sorted ascending)
        #expect(matches.first?.filesScanned == 105)
        #expect(matches.last?.filesScanned == 114)
    }

    @Test("Returns results in ascending chronological order")
    func ascendingChronologicalOrder() {
        let entries = [
            makeEntry(createdAt: Date(timeIntervalSince1970: 300), directories: ["/videos"]),
            makeEntry(createdAt: Date(timeIntervalSince1970: 100), directories: ["/videos"]),
            makeEntry(createdAt: Date(timeIntervalSince1970: 200), directories: ["/videos"]),
        ]
        let matches = SessionRegistry.findMatchingScans(for: ["/videos"], mode: .video, in: entries)
        #expect(matches.count == 3)
        #expect(matches[0].createdAt < matches[1].createdAt)
        #expect(matches[1].createdAt < matches[2].createdAt)
    }

    @Test("Empty directories input returns no matches")
    func emptyDirectoriesInput() {
        let entries = [makeEntry(directories: ["/videos"], filesScanned: 100)]
        let matches = SessionRegistry.findMatchingScans(for: [], mode: .video, in: entries)
        #expect(matches.isEmpty)
    }

    @Test("Empty entries array returns no matches")
    func emptyEntriesArray() {
        let matches = SessionRegistry.findMatchingScans(for: ["/videos"], mode: .video, in: [])
        #expect(matches.isEmpty)
    }

    @Test("Partial overlap above Jaccard threshold matches")
    func partialOverlapAboveThreshold() {
        // {/a, /b} ∩ {/a, /b, /extra} = {/a, /b}, union = {/a, /b, /c, /extra}, Jaccard = 2/4 = 50% -- should match
        let entry = makeEntry(directories: ["/a", "/b", "/extra"])
        let matches = SessionRegistry.findMatchingScans(for: ["/a", "/b", "/c"], mode: .video, in: [entry])
        #expect(matches.count == 1)
    }

    @Test("Exact 50% Jaccard threshold is inclusive")
    func exactThresholdInclusive() {
        // {/a} ∩ {/a, /b} = {/a}, union = {/a, /b}, Jaccard = 1/2 = 50% -- should match
        let entry = makeEntry(directories: ["/a", "/b"])
        let matches = SessionRegistry.findMatchingScans(for: ["/a"], mode: .video, in: [entry])
        #expect(matches.count == 1)
    }

    // MARK: - Mode Filtering

    @Test("Excludes entries with a different scan mode")
    func excludesDifferentMode() {
        let entries = [
            makeEntry(directories: ["/media"], mode: .video, filesScanned: 100),
            makeEntry(directories: ["/media"], mode: .image, filesScanned: 80),
            makeEntry(directories: ["/media"], mode: .audio, filesScanned: 60),
        ]
        let matches = SessionRegistry.findMatchingScans(for: ["/media"], mode: .image, in: entries)
        #expect(matches.count == 1)
        #expect(matches[0].mode == .image)
    }

    @Test("Mode filter works with auto mode")
    func modeFilterAutoMode() {
        let entries = [
            makeEntry(directories: ["/media"], mode: .auto, filesScanned: 100),
            makeEntry(directories: ["/media"], mode: .video, filesScanned: 80),
        ]
        let matches = SessionRegistry.findMatchingScans(for: ["/media"], mode: .auto, in: entries)
        #expect(matches.count == 1)
        #expect(matches[0].mode == .auto)
    }

    // MARK: - Symmetric (Jaccard) Overlap

    @Test("Rejects subset scan against much broader historical scan")
    func rejectsSubsetAgainstBroadScan() {
        // Current: {/a}, Entry: {/a, /b, /c, /d}
        // Jaccard = 1/4 = 25% -- should NOT match
        let entry = makeEntry(directories: ["/a", "/b", "/c", "/d"], filesScanned: 200)
        let matches = SessionRegistry.findMatchingScans(for: ["/a"], mode: .video, in: [entry])
        #expect(matches.isEmpty)
    }

    @Test("Rejects broad scan against narrow historical scan")
    func rejectsBroadAgainstNarrowScan() {
        // Current: {/a, /b, /c, /d}, Entry: {/a}
        // Jaccard = 1/4 = 25% -- should NOT match
        let entry = makeEntry(directories: ["/a"], filesScanned: 50)
        let matches = SessionRegistry.findMatchingScans(for: ["/a", "/b", "/c", "/d"], mode: .video, in: [entry])
        #expect(matches.isEmpty)
    }

    @Test("Matches identical directory sets via Jaccard")
    func matchesIdenticalSets() {
        // Jaccard = 3/3 = 100%
        let entry = makeEntry(directories: ["/a", "/b", "/c"], filesScanned: 100)
        let matches = SessionRegistry.findMatchingScans(for: ["/a", "/b", "/c"], mode: .video, in: [entry])
        #expect(matches.count == 1)
    }
}
