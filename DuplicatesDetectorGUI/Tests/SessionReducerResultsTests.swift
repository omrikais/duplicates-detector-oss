import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Create a minimal ScanEnvelope for results tests.
private func makeEnvelope(
    pairs: [PairResult] = [],
    groups: [GroupResult]? = nil,
    keep: String? = nil,
    action: String = "trash",
    group: Bool = false
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
            keep: keep,
            action: action,
            group: group,
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

/// Create a pair result for testing.
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

/// Create a second pair result for testing multi-pair scenarios.
private func makePair2(
    fileA: String = "/videos/c.mp4",
    fileB: String = "/videos/d.mp4",
    score: Double = 72.0
) -> PairResult {
    PairResult(
        fileA: fileA,
        fileB: fileB,
        score: score,
        breakdown: ["filename": 30.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: 500_000),
        fileBMetadata: FileMetadata(fileSize: 400_000),
        fileAIsReference: false,
        fileBIsReference: false,
        keep: "a"
    )
}

/// Create a Session in results phase with the given envelope.
private func resultsSession(
    envelope: ScanEnvelope? = nil,
    isDryRun: Bool = false,
    hasKeepStrategy: Bool = false,
    ignoreFile: String? = nil
) -> Session {
    let env = envelope ?? makeEnvelope(pairs: [makePair(), makePair2()])
    let snapshot = ResultsSnapshot(envelope: env, isDryRun: isDryRun, hasKeepStrategy: hasKeepStrategy)
    var config: SessionConfig? = nil
    if let ignoreFile {
        var c = SessionConfig()
        c.ignoreFile = ignoreFile
        config = c
    }
    return Session(
        phase: .results,
        results: snapshot,
        display: DisplayState(viewMode: .pairs),
        lastScanConfig: config
    )
}

/// Helper to check that an effects array contains a specific effect.
private func containsEffect(_ effects: [SessionEffect], _ effect: SessionEffect) -> Bool {
    effects.contains(effect)
}

// MARK: - Display State Tests

@Suite("Session Reducer: Results Display State")
struct SessionReducerDisplayStateTests {

    @Test("selectPair updates selectedPairID")
    func selectPairUpdates() {
        let session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (newState, _) = SessionReducer.reduce(state: session, action: .selectPair(pairID))
        #expect(newState.display.selectedPairID == pairID)
    }

    @Test("selectPair with nil clears selection")
    func selectPairNil() {
        var session = resultsSession()
        session.display.selectedPairID = PairIdentifier(fileA: "/a", fileB: "/b")
        let (newState, _) = SessionReducer.reduce(state: session, action: .selectPair(nil))
        #expect(newState.display.selectedPairID == nil)
    }

    @Test("setSearchText updates searchText and increments filterGeneration")
    func setSearchTextUpdates() {
        let session = resultsSession()
        let gen = session.results?.filterGeneration ?? 0
        let (newState, _) = SessionReducer.reduce(state: session, action: .setSearchText("test"))
        #expect(newState.display.searchText == "test")
        #expect(newState.results?.filterGeneration == gen &+ 1)
    }

    @Test("setSortOrder updates sortOrder and increments filterGeneration")
    func setSortOrderUpdates() {
        let session = resultsSession()
        let gen = session.results?.filterGeneration ?? 0
        let (newState, _) = SessionReducer.reduce(state: session, action: .setSortOrder(.pathAscending))
        #expect(newState.display.sortOrder == .pathAscending)
        #expect(newState.results?.filterGeneration == gen &+ 1)
    }

    @Test("setActiveAction updates activeAction")
    func setActiveActionUpdates() {
        let session = resultsSession()
        let (newState, _) = SessionReducer.reduce(state: session, action: .setActiveAction(.delete))
        #expect(newState.display.activeAction == .delete)
    }

    @Test("setMoveDestination updates moveDestination")
    func setMoveDestinationUpdates() {
        let session = resultsSession()
        let url = URL(fileURLWithPath: "/tmp/dest")
        let (newState, _) = SessionReducer.reduce(state: session, action: .setMoveDestination(url))
        #expect(newState.display.moveDestination == url)
    }

    @Test("toggleSelectMode enables select mode")
    func toggleSelectModeOn() {
        let session = resultsSession()
        #expect(session.display.isSelectMode == false)
        let (newState, _) = SessionReducer.reduce(state: session, action: .toggleSelectMode)
        #expect(newState.display.isSelectMode == true)
    }

    @Test("toggleSelectMode off clears selections")
    func toggleSelectModeOffClearsSelections() {
        var session = resultsSession()
        session.display.isSelectMode = true
        session.display.selectedForAction = [PairIdentifier(fileA: "/a", fileB: "/b")]
        session.display.selectedGroupsForAction = [1, 2]
        let (newState, _) = SessionReducer.reduce(state: session, action: .toggleSelectMode)
        #expect(newState.display.isSelectMode == false)
        #expect(newState.display.selectedForAction.isEmpty)
        #expect(newState.display.selectedGroupsForAction.isEmpty)
    }

    @Test("deselectAll clears both selection sets")
    func deselectAllClears() {
        var session = resultsSession()
        session.display.selectedForAction = [PairIdentifier(fileA: "/a", fileB: "/b")]
        session.display.selectedGroupsForAction = [1]
        let (newState, _) = SessionReducer.reduce(state: session, action: .deselectAll)
        #expect(newState.display.selectedForAction.isEmpty)
        #expect(newState.display.selectedGroupsForAction.isEmpty)
    }

    @Test("selectAll is a no-op in reducer")
    func selectAllNoOp() {
        let session = resultsSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .selectAll)
        #expect(newState.display.selectedForAction.isEmpty)
        #expect(effects.isEmpty)
    }
}

// MARK: - Review Desk Tests

@Suite("Session Reducer: Review Desk")
struct SessionReducerReviewDeskTests {

    @Test("keepFile emits performFileAction effect")
    func keepFileEmitsEffect() {
        let session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .keepFile(pairID, "/videos/b.mp4", .trash)
        )
        #expect(containsEffect(effects, .performFileAction(.trash, "/videos/b.mp4", pairID)))
    }

    @Test("keepFile guards dry-run mode and sets per-pair error")
    func keepFileGuardsDryRun() {
        let session = resultsSession(isDryRun: true)
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .keepFile(pairID, "/videos/b.mp4", .trash)
        )
        #expect(effects.isEmpty)
        #expect(newState.results?.pairErrors[pairID] != nil)
        #expect(newState.results?.pairErrors[pairID]?.message.contains("dry-run") == true)
    }

    @Test("keepFile guards bulk in progress and sets per-pair error")
    func keepFileGuardsBulk() {
        var session = resultsSession()
        session.results?.bulkProgress = BulkProgress(completed: 0, total: 5)
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .keepFile(pairID, "/videos/b.mp4", .trash)
        )
        #expect(effects.isEmpty)
        #expect(newState.results?.pairErrors[pairID] != nil)
        #expect(newState.results?.pairErrors[pairID]?.message.contains("bulk") == true)
    }

    @Test("skipPair is a no-op")
    func skipPairNoOp() {
        let session = resultsSession()
        let (_, effects) = SessionReducer.reduce(state: session, action: .skipPair)
        #expect(effects.isEmpty)
    }

    @Test("previousPair is a no-op")
    func previousPairNoOp() {
        let session = resultsSession()
        let (_, effects) = SessionReducer.reduce(state: session, action: .previousPair)
        #expect(effects.isEmpty)
    }
}

// MARK: - Ignore List Tests

@Suite("Session Reducer: Ignore List")
struct SessionReducerIgnoreListTests {

    @Test("ignorePair adds to ignored set and increments filterGeneration")
    func ignorePairAdds() {
        let session = resultsSession(ignoreFile: "/custom/ignore.json")
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let gen = session.results?.filterGeneration ?? 0
        let (newState, effects) = SessionReducer.reduce(state: session, action: .ignorePair(pairID))
        #expect(newState.results?.ignoredPairs.contains(pairID) == true)
        #expect(newState.results?.filterGeneration == gen &+ 1)
        #expect(containsEffect(effects, .addToIgnoreList("/videos/a.mp4", "/videos/b.mp4", URL(fileURLWithPath: "/custom/ignore.json"))))
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("ignorePair guards dry-run mode and sets per-pair error")
    func ignorePairGuardsDryRun() {
        let session = resultsSession(isDryRun: true)
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .ignorePair(pairID))
        #expect(newState.results?.ignoredPairs.isEmpty == true)
        #expect(effects.isEmpty)
        #expect(newState.results?.pairErrors[pairID] != nil)
        #expect(newState.results?.pairErrors[pairID]?.message.contains("dry-run") == true)
    }

    @Test("unignorePair removes both orderings")
    func unignorePairBothOrderings() {
        var session = resultsSession(ignoreFile: "/custom/ignore.json")
        let forward = PairIdentifier(fileA: "/a", fileB: "/b")
        let reverse = PairIdentifier(fileA: "/b", fileB: "/a")
        session.results?.ignoredPairs.insert(forward)
        session.results?.ignoredPairs.insert(reverse)
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .unignorePair("/a", "/b")
        )
        #expect(newState.results?.ignoredPairs.contains(forward) == false)
        #expect(newState.results?.ignoredPairs.contains(reverse) == false)
        let expectedRemoved: Set<PairID> = [forward, reverse]
        #expect(containsEffect(effects, .removeFromIgnoreList("/a", "/b", URL(fileURLWithPath: "/custom/ignore.json"), expectedRemoved)))
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("clearIgnoredPairs clears all and emits effects")
    func clearIgnoredPairsClears() {
        var session = resultsSession(ignoreFile: "/custom/ignore.json")
        let pairID = PairIdentifier(fileA: "/a", fileB: "/b")
        session.results?.ignoredPairs.insert(pairID)
        let (newState, effects) = SessionReducer.reduce(state: session, action: .clearIgnoredPairs)
        #expect(newState.results?.ignoredPairs.isEmpty == true)
        #expect(containsEffect(effects, .clearIgnoreList([pairID], URL(fileURLWithPath: "/custom/ignore.json"))))
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("ignorePair passes nil URL when no custom ignoreFile configured")
    func ignorePairDefaultPath() {
        let session = resultsSession() // no ignoreFile
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (_, effects) = SessionReducer.reduce(state: session, action: .ignorePair(pairID))
        #expect(containsEffect(effects, .addToIgnoreList("/videos/a.mp4", "/videos/b.mp4", nil)))
    }
}

// MARK: - Resolution Tests

@Suite("Session Reducer: Resolution & History")
struct SessionReducerResolutionTests {

    @Test("undoResolution removes resolution and matching history entry")
    func undoResolutionRemoves() {
        var session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let record = ActionRecord(
            pairID: pairID,
            timestamp: Date(timeIntervalSince1970: 1_000_000),
            action: "trash",
            actedOnPath: "/videos/b.mp4",
            keptPath: "/videos/a.mp4",
            bytesFreed: 900_000,
            score: 85,
            strategy: "newest",
            destination: nil
        )
        session.results?.resolutions[pairID] = .resolved(record)
        session.results?.actionHistory.append(record)

        let (newState, effects) = SessionReducer.reduce(state: session, action: .undoResolution(pairID))
        #expect(newState.results?.resolutions[pairID] == nil)
        #expect(newState.results?.actionHistory.isEmpty == true)
        #expect(containsEffect(effects, .saveSessionDebounced))
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("undoResolution is a no-op when not resolved")
    func undoResolutionNoOp() {
        let session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (_, effects) = SessionReducer.reduce(state: session, action: .undoResolution(pairID))
        #expect(effects.isEmpty)
    }

    @Test("fileActionCompleted updates resolutions and actionHistory")
    func fileActionCompletedUpdates() {
        let session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let otherPair = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/c.mp4")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .fileActionCompleted(pairID, .trash, "/videos/b.mp4", [pairID, otherPair], FileActionMeta(bytesFreed: 1024, score: 85, strategy: "newest", destination: nil))
        )
        #expect(newState.results?.resolutions[pairID] != nil)
        #expect(newState.results?.resolutions[otherPair] != nil)
        #expect(newState.results?.actionHistory.count == 1)
        #expect(effects.contains(.saveSessionDebounced))
        #expect(effects.contains(.rebuildSynthesizedViews))
        // Should also have writeActionLog effect
        #expect(effects.count == 3)
    }

    @Test("fileActionCompleted does not overwrite existing resolutions")
    func fileActionCompletedPreservesExisting() {
        var session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let existingRecord = ActionRecord(
            pairID: pairID,
            timestamp: Date(timeIntervalSince1970: 1),
            action: "delete",
            actedOnPath: "/videos/b.mp4",
            keptPath: "/videos/a.mp4",
            bytesFreed: nil,
            score: 0,
            strategy: nil,
            destination: nil
        )
        session.results?.resolutions[pairID] = .resolved(existingRecord)

        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .fileActionCompleted(pairID, .trash, "/videos/b.mp4", [pairID], FileActionMeta(bytesFreed: nil, score: 0, strategy: nil, destination: nil))
        )
        // Existing resolution should be preserved
        if case .resolved(let record) = newState.results?.resolutions[pairID] {
            #expect(record.action == "delete") // Original, not overwritten
        } else {
            Issue.record("Expected .resolved resolution")
        }
    }

    @Test("fileActionFailed sets pairErrors")
    func fileActionFailedSetsError() {
        let session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .fileActionFailed(pairID, "Permission denied")
        )
        #expect(newState.results?.pairErrors[pairID]?.message == "Permission denied")
    }
}

// MARK: - Bulk Operation Tests

@Suite("Session Reducer: Bulk Operations")
struct SessionReducerBulkTests {

    @Test("startBulk sets bulkProgress and emits executeBulk")
    func startBulkSetsProgress() {
        let session = resultsSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .startBulk)
        #expect(newState.results?.bulkProgress != nil)
        #expect(newState.results?.bulkCancelled == false)
        #expect(effects.contains(.executeBulk([])))
    }

    @Test("startBulk guards dry-run mode and sets error")
    func startBulkGuardsDryRun() {
        let session = resultsSession(isDryRun: true)
        let (newState, effects) = SessionReducer.reduce(state: session, action: .startBulk)
        #expect(newState.results?.bulkProgress == nil)
        #expect(effects.isEmpty)
        let sentinelKey = PairIdentifier(fileA: "_bulk", fileB: "_bulk")
        #expect(newState.results?.pairErrors[sentinelKey] != nil)
        #expect(newState.results?.pairErrors[sentinelKey]?.message.contains("dry-run") == true)
    }

    @Test("startBulk guards existing bulk in progress")
    func startBulkGuardsExisting() {
        var session = resultsSession()
        session.results?.bulkProgress = BulkProgress(completed: 1, total: 5)
        let (_, effects) = SessionReducer.reduce(state: session, action: .startBulk)
        #expect(effects.isEmpty)
    }

    @Test("cancelBulk sets bulkCancelled")
    func cancelBulkSets() {
        var session = resultsSession()
        session.results?.bulkProgress = BulkProgress(completed: 0, total: 5)
        let (newState, _) = SessionReducer.reduce(state: session, action: .cancelBulk)
        #expect(newState.results?.bulkCancelled == true)
    }

    @Test("bulkItemCompleted increments bulkProgress.completed")
    func bulkItemCompletedIncrements() {
        var session = resultsSession()
        session.results?.bulkProgress = BulkProgress(completed: 2, total: 10)
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .bulkItemCompleted(pairID, .trash, "/videos/b.mp4", [pairID], FileActionMeta(bytesFreed: 2048, score: 90, strategy: "biggest", destination: nil))
        )
        #expect(newState.results?.bulkProgress?.completed == 3)
        #expect(newState.results?.resolutions[pairID] != nil)
        #expect(!effects.isEmpty)
    }

    @Test("bulkFinished clears bulkProgress")
    func bulkFinishedClears() {
        var session = resultsSession()
        session.results?.bulkProgress = BulkProgress(completed: 5, total: 5)
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .bulkFinished([])
        )
        #expect(newState.results?.bulkProgress == nil)
        #expect(effects.contains(.saveSessionDebounced))
        #expect(effects.contains(.rebuildSynthesizedViews))
    }

    @Test("bulkFinished with failures sets error")
    func bulkFinishedWithFailures() {
        var session = resultsSession()
        session.results?.bulkProgress = BulkProgress(completed: 3, total: 5)
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .bulkFinished(["error 1", "error 2"])
        )
        #expect(newState.results?.bulkProgress == nil)
        // The error is stored in pairErrors with a sentinel key
        let sentinelKey = PairIdentifier(fileA: "_bulk", fileB: "_bulk")
        #expect(newState.results?.pairErrors[sentinelKey]?.message == "2 file(s) failed")
    }
}

// MARK: - View Mode Toggle Tests

@Suite("Session Reducer: View Mode Toggle")
struct SessionReducerViewModeTests {

    @Test("toggleViewMode synthesizes groups from pairs")
    func toggleToGroups() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4", score: 85),
            makePair(fileA: "/a.mp4", fileB: "/c.mp4", score: 70),
        ]
        let session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        let (newState, _) = SessionReducer.reduce(state: session, action: .toggleViewMode)
        #expect(newState.display.viewMode == .groups)
        #expect(newState.results?.synthesizedGroups != nil)
        #expect(newState.results?.synthesizedGroups?.isEmpty == false)
    }

    @Test("toggleViewMode from groups to pairs synthesizes pairs")
    func toggleToPairs() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4", score: 85),
            makePair(fileA: "/a.mp4", fileB: "/c.mp4", score: 70),
        ]
        // Start in pairs, toggle to groups, then toggle back to pairs
        var session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        let (groupState, _) = SessionReducer.reduce(state: session, action: .toggleViewMode)
        #expect(groupState.display.viewMode == .groups)

        let (pairState, _) = SessionReducer.reduce(state: groupState, action: .toggleViewMode)
        #expect(pairState.display.viewMode == .pairs)
        #expect(pairState.results?.synthesizedPairs != nil)
    }

    @Test("toggleViewMode guards insufficient pairs")
    func toggleGuardsInsufficient() {
        let session = resultsSession(envelope: makeEnvelope(pairs: [makePair()]))
        let (newState, _) = SessionReducer.reduce(state: session, action: .toggleViewMode)
        // With only 1 pair, toggle should be blocked
        #expect(newState.display.viewMode == .pairs) // unchanged
    }

    @Test("toggleViewMode to pairs includes pendingWatchPairs without draining")
    func toggleIncludesPendingWatch() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4"),
            makePair(fileA: "/c.mp4", fileB: "/d.mp4"),
        ]
        var session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        // Toggle to groups first
        let (groupState, _) = SessionReducer.reduce(state: session, action: .toggleViewMode)
        var withPending = groupState
        let watchPair = makePair(fileA: "/e.mp4", fileB: "/f.mp4")
        withPending.results?.pendingWatchPairs = [watchPair]

        // Toggle back to pairs — buffer is NOT drained (persisted for save)
        let (pairState, _) = SessionReducer.reduce(state: withPending, action: .toggleViewMode)
        #expect(pairState.results?.pendingWatchPairs.count == 1)
        // The watch pair should still be included in synthesized pairs
        let hasWatchPair = pairState.results?.synthesizedPairs?.contains { $0.fileA == "/e.mp4" } ?? false
        #expect(hasWatchPair)
    }
}

// MARK: - Set View Mode Tests

@Suite("Session Reducer: Set View Mode")
struct SessionReducerSetViewModeTests {

    @Test("setViewMode to same mode is no-op")
    func setViewModeSameMode() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4", score: 85),
            makePair(fileA: "/a.mp4", fileB: "/c.mp4", score: 70),
        ]
        let session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        #expect(session.display.viewMode == .pairs)
        let (newState, effects) = SessionReducer.reduce(state: session, action: .setViewMode(.pairs))
        #expect(newState.display.viewMode == .pairs)
        #expect(newState.results?.synthesizedGroups == nil)
        #expect(effects.isEmpty)
    }

    @Test("setViewMode(.groups) synthesizes groups from pairs")
    func setViewModeToGroups() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4", score: 85),
            makePair(fileA: "/a.mp4", fileB: "/c.mp4", score: 70),
        ]
        let session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        let (newState, _) = SessionReducer.reduce(state: session, action: .setViewMode(.groups))
        #expect(newState.display.viewMode == .groups)
        #expect(newState.results?.synthesizedGroups != nil)
        #expect(newState.results?.synthesizedGroups?.isEmpty == false)
    }

    @Test("setViewMode(.pairs) from groups synthesizes pairs")
    func setViewModeToPairsFromGroups() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4", score: 85),
            makePair(fileA: "/a.mp4", fileB: "/c.mp4", score: 70),
        ]
        // Start in pairs, switch to groups, then use setViewMode back to pairs
        let session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        let (groupState, _) = SessionReducer.reduce(state: session, action: .setViewMode(.groups))
        #expect(groupState.display.viewMode == .groups)

        let (pairState, _) = SessionReducer.reduce(state: groupState, action: .setViewMode(.pairs))
        #expect(pairState.display.viewMode == .pairs)
        #expect(pairState.results?.synthesizedPairs != nil)
    }
}

// MARK: - Ignore List Rollback Tests

@Suite("Session Reducer: Ignore List Rollback")
struct SessionReducerIgnoreRollbackTests {

    @Test("_rollbackIgnore removes pair from ignored set")
    func rollbackIgnoreRemovesPair() {
        var session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        session.results?.ignoredPairs.insert(pairID)
        let gen = session.results?.filterGeneration ?? 0
        let (newState, effects) = SessionReducer.reduce(state: session, action: ._rollbackIgnore(pairID))
        #expect(newState.results?.ignoredPairs.contains(pairID) == false)
        #expect(newState.results?.filterGeneration == gen &+ 1)
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
        #expect(containsEffect(effects, .saveSessionDebounced))
        // Must NOT emit any ignore-list file effects
        for effect in effects {
            switch effect {
            case .addToIgnoreList, .removeFromIgnoreList, .clearIgnoreList:
                Issue.record("Rollback must not emit ignore-list file effects, got: \(effect)")
            default: break
            }
        }
    }

    @Test("_rollbackUnignore re-inserts all removed pairs")
    func rollbackUnignoreReinsertsPairs() {
        let session = resultsSession()
        let pairs: Set<PairID> = [
            PairIdentifier(fileA: "/a", fileB: "/b"),
            PairIdentifier(fileA: "/b", fileB: "/a"),
        ]
        let (newState, effects) = SessionReducer.reduce(state: session, action: ._rollbackUnignore(pairs))
        #expect(newState.results?.ignoredPairs == pairs)
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
        for effect in effects {
            switch effect {
            case .addToIgnoreList, .removeFromIgnoreList, .clearIgnoreList:
                Issue.record("Rollback must not emit ignore-list file effects, got: \(effect)")
            default: break
            }
        }
    }

    @Test("_rollbackClearIgnored restores snapshot")
    func rollbackClearRestoredSnapshot() {
        let session = resultsSession()
        let pairs: Set<PairID> = [
            PairIdentifier(fileA: "/a", fileB: "/b"),
            PairIdentifier(fileA: "/c", fileB: "/d"),
        ]
        let (newState, effects) = SessionReducer.reduce(state: session, action: ._rollbackClearIgnored(pairs))
        #expect(newState.results?.ignoredPairs == pairs)
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
        for effect in effects {
            switch effect {
            case .addToIgnoreList, .removeFromIgnoreList, .clearIgnoreList:
                Issue.record("Rollback must not emit ignore-list file effects, got: \(effect)")
            default: break
            }
        }
    }
}
