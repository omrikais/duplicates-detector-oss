import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

private func makeEnvelope(
    pairs: [PairResult] = [],
    groups: [GroupResult]? = nil
) -> ScanEnvelope {
    let content: ScanContent = if let groups {
        .groups(groups)
    } else {
        .pairs(pairs)
    }
    return ScanEnvelope(
        version: "1.0.0",
        generatedAt: "2025-01-01T00:00:00Z",
        args: ScanArgs(
            directories: ["/videos"],
            threshold: 50,
            content: false,
            weights: nil,
            keep: "a",
            action: "trash",
            group: groups != nil,
            sort: "score",
            mode: "video",
            embedThumbnails: false
        ),
        stats: ScanStats(
            filesScanned: 100,
            filesAfterFilter: 80,
            totalPairsScored: 200,
            pairsAboveThreshold: pairs.count,
            scanTime: 1.0,
            extractTime: 2.0,
            filterTime: 0.5,
            contentHashTime: 0.0,
            scoringTime: 2.0,
            totalTime: 5.5
        ),
        content: content
    )
}

private func makePair(
    fileA: String = "/videos/a.mp4",
    fileB: String = "/videos/b.mp4",
    score: Double = 85.0
) -> PairResult {
    PairResult(
        fileA: fileA,
        fileB: fileB,
        score: score,
        breakdown: ["filename": 40.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: 1_000_000),
        fileBMetadata: FileMetadata(fileSize: 900_000),
        fileAIsReference: false,
        fileBIsReference: false,
        keep: "a"
    )
}

private func makeGroupFile(path: String, fileSize: Int = 1_000_000) -> GroupFile {
    GroupFile(
        path: path,
        duration: nil,
        width: nil,
        height: nil,
        fileSize: fileSize,
        codec: nil,
        bitrate: nil,
        framerate: nil,
        audioChannels: nil,
        mtime: nil,
        tagTitle: nil,
        tagArtist: nil,
        tagAlbum: nil,
        isReference: false,
        thumbnail: nil
    )
}

private func makeGroupPair(fileA: String, fileB: String, score: Double = 85.0) -> GroupPair {
    GroupPair(fileA: fileA, fileB: fileB, score: score, breakdown: [:], detail: [:])
}

// MARK: - Pair Filtering Tests

@Suite("Directory Filter: Pairs")
struct DirectoryFilterPairsTests {

    @Test("No filter returns all pairs")
    func noFilterReturnsAll() {
        let pairs = [
            makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4"),
            makePair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        let display = DisplayState(viewMode: .pairs)

        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 2)
    }

    @Test("Filter includes pairs where fileA matches directory")
    func filterByFileA() {
        let pairs = [
            makePair(fileA: "/videos/a.mp4", fileB: "/photos/b.jpg"),
            makePair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 1)
        #expect(filtered[0].fileA == "/videos/a.mp4")
    }

    @Test("Filter includes pairs where fileB matches directory")
    func filterByFileB() {
        let pairs = [
            makePair(fileA: "/photos/a.jpg", fileB: "/videos/b.mp4"),
            makePair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 1)
        #expect(filtered[0].fileB == "/videos/b.mp4")
    }

    @Test("Filter excludes pairs in other directories")
    func filterExcludesOther() {
        let pairs = [
            makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4"),
            makePair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg"),
            makePair(fileA: "/music/e.mp3", fileB: "/music/f.mp3"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 1)
        #expect(filtered[0].fileA == "/videos/a.mp4")
    }

    @Test("Clearing filter restores all pairs")
    func clearFilterRestoresAll() {
        let pairs = [
            makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4"),
            makePair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))

        // Filter active
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"
        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 1)

        // Filter cleared
        display.directoryFilter = nil
        let all = snapshot.computeFilteredPairs(display: display)
        #expect(all.count == 2)
    }

    @Test("Filter uses path prefix matching, not substring")
    func filterUsesPrefix() {
        let pairs = [
            makePair(fileA: "/videos-backup/a.mp4", fileB: "/videos-backup/b.mp4"),
            makePair(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredPairs(display: display)
        // Only /videos/c.mp4 matches, not /videos-backup/a.mp4
        #expect(filtered.count == 1)
        #expect(filtered[0].fileA == "/videos/c.mp4")
    }

    @Test("Filter with trailing slash works correctly")
    func filterTrailingSlash() {
        let pairs = [
            makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos/"

        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 1)
    }

    @Test("Filter matches nested subdirectories")
    func filterMatchesSubdirs() {
        let pairs = [
            makePair(fileA: "/videos/sub/deep/a.mp4", fileB: "/videos/sub/deep/b.mp4"),
            makePair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg"),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredPairs(display: display)
        #expect(filtered.count == 1)
        #expect(filtered[0].fileA == "/videos/sub/deep/a.mp4")
    }
}

// MARK: - Group Filtering Tests

@Suite("Directory Filter: Groups")
struct DirectoryFilterGroupsTests {

    @Test("No filter returns all groups")
    func noFilterReturnsAll() {
        let groups = [
            GroupResult(
                groupId: 1, fileCount: 2, maxScore: 90, minScore: 90, avgScore: 90,
                files: [makeGroupFile(path: "/videos/a.mp4"), makeGroupFile(path: "/videos/b.mp4")],
                pairs: [makeGroupPair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")],
                keep: "/videos/a.mp4"
            ),
            GroupResult(
                groupId: 2, fileCount: 2, maxScore: 80, minScore: 80, avgScore: 80,
                files: [makeGroupFile(path: "/photos/c.jpg"), makeGroupFile(path: "/photos/d.jpg")],
                pairs: [makeGroupPair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg")],
                keep: "/photos/c.jpg"
            ),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(groups: groups))
        let display = DisplayState(viewMode: .groups)

        let filtered = snapshot.computeFilteredGroups(display: display) { _ in false }
        #expect(filtered.count == 2)
    }

    @Test("Filter includes groups containing matching files")
    func filterIncludesMatching() {
        let groups = [
            GroupResult(
                groupId: 1, fileCount: 2, maxScore: 90, minScore: 90, avgScore: 90,
                files: [makeGroupFile(path: "/videos/a.mp4"), makeGroupFile(path: "/videos/b.mp4")],
                pairs: [makeGroupPair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")],
                keep: "/videos/a.mp4"
            ),
            GroupResult(
                groupId: 2, fileCount: 2, maxScore: 80, minScore: 80, avgScore: 80,
                files: [makeGroupFile(path: "/photos/c.jpg"), makeGroupFile(path: "/photos/d.jpg")],
                pairs: [makeGroupPair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg")],
                keep: "/photos/c.jpg"
            ),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(groups: groups))
        var display = DisplayState(viewMode: .groups)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredGroups(display: display) { _ in false }
        #expect(filtered.count == 1)
        #expect(filtered[0].groupId == 1)
    }

    @Test("Group with mixed directories included when at least one file matches")
    func groupWithMixedDirectories() {
        let groups = [
            GroupResult(
                groupId: 1, fileCount: 2, maxScore: 90, minScore: 90, avgScore: 90,
                files: [makeGroupFile(path: "/videos/a.mp4"), makeGroupFile(path: "/photos/b.jpg")],
                pairs: [makeGroupPair(fileA: "/videos/a.mp4", fileB: "/photos/b.jpg")],
                keep: "/videos/a.mp4"
            ),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(groups: groups))
        var display = DisplayState(viewMode: .groups)
        display.directoryFilter = "/videos"

        let filtered = snapshot.computeFilteredGroups(display: display) { _ in false }
        #expect(filtered.count == 1)
    }

    @Test("Clearing group filter restores all groups")
    func clearFilterRestoresAll() {
        let groups = [
            GroupResult(
                groupId: 1, fileCount: 2, maxScore: 90, minScore: 90, avgScore: 90,
                files: [makeGroupFile(path: "/videos/a.mp4"), makeGroupFile(path: "/videos/b.mp4")],
                pairs: [makeGroupPair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")],
                keep: "/videos/a.mp4"
            ),
            GroupResult(
                groupId: 2, fileCount: 2, maxScore: 80, minScore: 80, avgScore: 80,
                files: [makeGroupFile(path: "/photos/c.jpg"), makeGroupFile(path: "/photos/d.jpg")],
                pairs: [makeGroupPair(fileA: "/photos/c.jpg", fileB: "/photos/d.jpg")],
                keep: "/photos/c.jpg"
            ),
        ]
        let snapshot = ResultsSnapshot(envelope: makeEnvelope(groups: groups))

        var display = DisplayState(viewMode: .groups)
        display.directoryFilter = "/videos"
        let filtered = snapshot.computeFilteredGroups(display: display) { _ in false }
        #expect(filtered.count == 1)

        display.directoryFilter = nil
        let all = snapshot.computeFilteredGroups(display: display) { _ in false }
        #expect(all.count == 2)
    }
}

// MARK: - Reducer Tests

@Suite("Directory Filter: Reducer")
struct DirectoryFilterReducerTests {

    @Test("setDirectoryFilter updates display state and bumps filter generation")
    func setDirectoryFilterUpdates() {
        let pairs = [makePair()]
        let env = makeEnvelope(pairs: pairs)
        let snapshot = ResultsSnapshot(envelope: env)
        let session = Session(
            phase: .results,
            results: snapshot,
            display: DisplayState(viewMode: .pairs)
        )
        let initialGen = session.results?.filterGeneration ?? 0

        let (newState, _) = SessionReducer.reduce(state: session, action: .setDirectoryFilter("/videos"))
        #expect(newState.display.directoryFilter == "/videos")
        #expect((newState.results?.filterGeneration ?? 0) > initialGen)
    }

    @Test("Clearing directoryFilter resets to nil and bumps filter generation")
    func clearDirectoryFilter() {
        let pairs = [makePair()]
        let env = makeEnvelope(pairs: pairs)
        let snapshot = ResultsSnapshot(envelope: env)
        var display = DisplayState(viewMode: .pairs)
        display.directoryFilter = "/videos"
        let session = Session(
            phase: .results,
            results: snapshot,
            display: display
        )
        let initialGen = session.results?.filterGeneration ?? 0

        let (newState, _) = SessionReducer.reduce(state: session, action: .setDirectoryFilter(nil))
        #expect(newState.display.directoryFilter == nil)
        #expect((newState.results?.filterGeneration ?? 0) > initialGen)
    }
}

// MARK: - Path Shortening Tests

@Suite("Directory Filter: shortenPath")
struct ShortenPathTests {

    @Test("Path under home directory shortened with tilde")
    func pathUnderHome() {
        let home = NSHomeDirectory()
        let path = "\(home)/Videos/test"
        let shortened = ResultsScreen.shortenPath(path)
        #expect(shortened == "~/Videos/test")
    }

    @Test("Path not under home directory unchanged")
    func pathNotUnderHome() {
        let path = "/tmp/other/videos"
        let shortened = ResultsScreen.shortenPath(path)
        #expect(shortened == "/tmp/other/videos")
    }

    @Test("Home directory itself shortened to tilde")
    func homeDirectoryItself() {
        let home = NSHomeDirectory()
        let shortened = ResultsScreen.shortenPath(home)
        #expect(shortened == "~")
    }
}
