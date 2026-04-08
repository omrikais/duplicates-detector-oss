import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Create a minimal ScanEnvelope for watch tests.
private func makeEnvelope(
    pairs: [PairResult] = [],
    groups: [GroupResult]? = nil,
    keep: String? = nil
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
            action: "trash",
            group: false,
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

/// Create a Session in results phase.
private func resultsSession(
    envelope: ScanEnvelope? = nil,
    isDryRun: Bool = false
) -> Session {
    let env = envelope ?? makeEnvelope(pairs: [makePair()])
    let snapshot = ResultsSnapshot(envelope: env, isDryRun: isDryRun)
    return Session(
        phase: .results,
        results: snapshot,
        display: DisplayState(viewMode: .pairs)
    )
}

/// Helper to check that an effects array contains a specific effect.
private func containsEffect(_ effects: [SessionEffect], _ effect: SessionEffect) -> Bool {
    effects.contains(effect)
}

// MARK: - Watch Enable/Disable Tests

@Suite("Session Reducer: Watch Enable/Disable")
struct SessionReducerWatchEnableTests {

    @Test("setWatchEnabled(true) creates WatchState and emits startWatch in results phase")
    func enableWatchInResults() {
        let session = resultsSession()
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .setWatchEnabled(true)
        )
        #expect(newState.watch != nil)
        #expect(newState.watch?.isActive == true)
        #expect(newState.watch?.sourceLabel == "scan")
        // Should emit startWatch and startFileMonitor
        let hasStartWatch = effects.contains { effect in
            if case .startWatch = effect { return true }
            return false
        }
        let hasStartMonitor = effects.contains { effect in
            if case .startFileMonitor = effect { return true }
            return false
        }
        #expect(hasStartWatch)
        #expect(hasStartMonitor)
    }

    @Test("setWatchEnabled(true) guards non-results phase")
    func enableWatchGuardsPhase() {
        let session = Session(phase: .setup)
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .setWatchEnabled(true)
        )
        #expect(newState.watch == nil)
        #expect(effects.isEmpty)
    }

    @Test("setWatchEnabled(false) nils watch and emits stopWatch")
    func disableWatch() {
        var session = resultsSession()
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "scan")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .setWatchEnabled(false)
        )
        #expect(newState.watch == nil)
        #expect(containsEffect(effects, .stopWatch))
        #expect(containsEffect(effects, .stopFileMonitor))
    }
}

// MARK: - Watch Alert Tests

@Suite("Session Reducer: Watch Alerts")
struct SessionReducerWatchAlertTests {

    @Test("watchAlertReceived appends to envelope pairs in pairs mode")
    func watchAlertAppendsPairs() {
        var session = resultsSession()
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")
        let newPair = makePair(fileA: "/videos/x.mp4", fileB: "/videos/y.mp4")

        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([newPair])
        )

        if case .pairs(let pairs) = newState.results?.envelope.content {
            // Original pair + new watch pair
            #expect(pairs.count == 2)
        } else {
            Issue.record("Expected pairs content")
        }
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
        #expect(containsEffect(effects, .saveSessionDebounced))
    }

    @Test("watchAlertReceived appends to envelope for pair-mode even in groups view")
    func watchAlertAppendsPairModeInGroups() {
        let pairs = [
            makePair(fileA: "/a.mp4", fileB: "/b.mp4"),
            makePair(fileA: "/c.mp4", fileB: "/d.mp4"),
        ]
        var session = resultsSession(envelope: makeEnvelope(pairs: pairs))
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")
        // Toggle to groups
        let (groupState, _) = SessionReducer.reduce(state: session, action: .toggleViewMode)

        let watchPair = makePair(fileA: "/e.mp4", fileB: "/f.mp4")
        let (newState, effects) = SessionReducer.reduce(
            state: groupState,
            action: .watchAlertReceived([watchPair])
        )

        // Pair-mode envelopes always append directly to envelope.content so
        // pairs aren't lost when toggling back from groups view.
        #expect(newState.results?.pendingWatchPairs.isEmpty == true)
        if case .pairs(let envPairs) = newState.results?.envelope.content {
            #expect(envPairs.count == 3)
        } else {
            Issue.record("Expected .pairs envelope")
        }
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("watchAlertReceived is a no-op when pairs empty")
    func watchAlertEmptyNoOp() {
        let session = resultsSession()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([])
        )
        #expect(effects.isEmpty)
    }

    @Test("watchAlertReceived is a no-op without results")
    func watchAlertNoResults() {
        let session = Session(phase: .setup)
        let newPair = makePair()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([newPair])
        )
        #expect(effects.isEmpty)
    }
}

// MARK: - File Status Tests

@Suite("Session Reducer: File Status")
struct SessionReducerFileStatusTests {

    @Test("watchFileChanged updates fileStatuses")
    func watchFileChangedUpdates() {
        let session = resultsSession()
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .watchFileChanged("/videos/a.mp4", .missing)
        )
        #expect(newState.results?.fileStatuses["/videos/a.mp4"] == .missing)
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("watchFileChanged doesn't overwrite .actioned status")
    func watchFileChangedPreservesActioned() {
        var session = resultsSession()
        let record = ActionRecord(
            pairID: PairIdentifier(fileA: "/a", fileB: "/b"),
            timestamp: Date(),
            action: "trash",
            actedOnPath: "/videos/a.mp4",
            keptPath: "/videos/b.mp4",
            bytesFreed: nil,
            score: 0,
            strategy: nil,
            destination: nil
        )
        session.results?.fileStatuses["/videos/a.mp4"] = .actioned(record)

        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .watchFileChanged("/videos/a.mp4", .missing)
        )
        // Status should remain .actioned, not overwritten to .missing
        if case .actioned = newState.results?.fileStatuses["/videos/a.mp4"] {
            // Expected
        } else {
            Issue.record("Expected .actioned status to be preserved")
        }
        #expect(effects.isEmpty) // Guard triggered, no effects
    }

    @Test("watchFileBatchChanged updates multiple statuses")
    func watchFileBatchChangedUpdates() {
        let session = resultsSession()
        let updates: [String: FileStatus] = [
            "/videos/a.mp4": .missing,
            "/videos/b.mp4": .present,
        ]
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .watchFileBatchChanged(updates)
        )
        #expect(newState.results?.fileStatuses["/videos/a.mp4"] == .missing)
        #expect(newState.results?.fileStatuses["/videos/b.mp4"] == .present)
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("fileStatusChecked bulk-populates statuses")
    func fileStatusCheckedPopulates() {
        let session = resultsSession()
        let statuses: [String: FileStatus] = [
            "/videos/a.mp4": .present,
            "/videos/b.mp4": .missing,
            "/videos/c.mp4": .present,
        ]
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .fileStatusChecked(statuses)
        )
        #expect(newState.results?.fileStatuses.count == 3)
        #expect(newState.results?.fileStatuses["/videos/a.mp4"] == .present)
        #expect(newState.results?.fileStatuses["/videos/b.mp4"] == .missing)
        #expect(containsEffect(effects, .rebuildSynthesizedViews))
    }

    @Test("fileStatusChecked preserves .actioned entries")
    func fileStatusCheckedPreservesActioned() {
        var session = resultsSession()
        let record = ActionRecord(
            pairID: PairIdentifier(fileA: "/a", fileB: "/b"),
            timestamp: Date(),
            action: "trash",
            actedOnPath: "/videos/a.mp4",
            keptPath: "/videos/b.mp4",
            bytesFreed: nil,
            score: 0,
            strategy: nil,
            destination: nil
        )
        session.results?.fileStatuses["/videos/a.mp4"] = .actioned(record)

        let statuses: [String: FileStatus] = [
            "/videos/a.mp4": .missing,
            "/videos/b.mp4": .present,
        ]
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .fileStatusChecked(statuses)
        )
        // .actioned should be preserved for /videos/a.mp4
        if case .actioned = newState.results?.fileStatuses["/videos/a.mp4"] {
            // Expected
        } else {
            Issue.record("Expected .actioned status to be preserved")
        }
        #expect(newState.results?.fileStatuses["/videos/b.mp4"] == .present)
    }
}

// MARK: - External Signal Tests

@Suite("Session Reducer: External Signals")
struct SessionReducerExternalSignalTests {

    @Test("openReplayFile in setup phase initializes scanning state and loads replay")
    func openReplaySetup() {
        let session = Session(phase: .setup)
        let url = URL(fileURLWithPath: "/tmp/replay.json")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .openReplayFile(url)
        )
        #expect(newState.phase == .scanning)
        #expect(newState.scan != nil)
        #expect(containsEffect(effects, .loadReplayData(url)))
    }

    @Test("openReplayFile in results phase initializes scanning state and loads replay")
    func openReplayResults() {
        let session = resultsSession()
        let url = URL(fileURLWithPath: "/tmp/replay.json")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .openReplayFile(url)
        )
        // Transitions to .scanning (not .setup) so the completion flow
        // (.cliStreamCompleted → .minimumDisplayElapsed → .results) works.
        #expect(newState.phase == .scanning)
        #expect(newState.scan != nil)
        #expect(newState.pendingReplayURL == nil)
        #expect(newState.results == nil)
        #expect(containsEffect(effects, .loadReplayData(url)))
        #expect(containsEffect(effects, .persistSessionId(nil)))
        #expect(containsEffect(effects, .stopFileMonitor))
    }

    @Test("openReplayFile in scanning phase is no-op")
    func openReplayScanning() {
        let session = Session(phase: .scanning)
        let url = URL(fileURLWithPath: "/tmp/replay.json")
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .openReplayFile(url)
        )
        #expect(newState.pendingReplayURL == nil)
        #expect(effects.isEmpty)
    }

    @Test("openWatchNotification with matching ID emits activateWindow")
    func openWatchNotificationMatch() {
        let session = resultsSession()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .openWatchNotification(session.id)
        )
        #expect(containsEffect(effects, .activateWindow))
    }

    @Test("openWatchNotification from setup navigates to results and selects pair")
    func openWatchNotificationFromSetup() {
        // Simulate: scan completed → watch active → user went back to setup
        let sessionID = UUID()
        var session = resultsSession()
        session.id = sessionID
        session.watch = WatchState(
            isActive: true, stats: WatchStats(trackedFiles: 5),
            startedAt: Date(), sourceLabel: "scan"
        )
        // Reset to setup (preserving watch + results)
        let (afterReset, _) = SessionReducer.reduce(state: session, action: .resetToSetup)
        #expect(afterReset.phase == .setup)
        #expect(afterReset.results != nil)
        #expect(afterReset.id == sessionID)

        // Notification tap with same session ID
        let (afterNotification, effects) = SessionReducer.reduce(
            state: afterReset,
            action: .openWatchNotification(sessionID)
        )
        #expect(afterNotification.phase == .results)
        #expect(afterNotification.display.selectedPairID != nil)
        #expect(containsEffect(effects, .activateWindow))
    }

    @Test("openWatchNotification with mismatched ID still works when watch is active")
    func openWatchNotificationMismatchedID() {
        // Simulate: watch active with results, but state.id diverged
        // (e.g. user started a new scan while watch was running)
        var session = resultsSession()
        session.id = UUID() // Different from the notification's UUID
        session.watch = WatchState(
            isActive: true, stats: WatchStats(trackedFiles: 5),
            startedAt: Date(), sourceLabel: "scan"
        )
        let staleID = UUID() // The ID the engine captured at watch start
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .openWatchNotification(staleID)
        )
        // Should still navigate to results via the watch-active fallback
        #expect(newState.phase == .results)
        #expect(containsEffect(effects, .activateWindow))
    }

    @Test("openWatchNotification with different ID and results but no watch emits loadSession")
    func openWatchNotificationDifferentWithResultsNoWatch() {
        let session = resultsSession()
        let otherID = UUID()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .openWatchNotification(otherID)
        )
        // Without an active watch, a mismatched session ID should load
        // the notification's session — not route into unrelated results.
        #expect(containsEffect(effects, .loadSession(otherID)))
    }

    @Test("openWatchNotification with different ID and no results emits loadSession")
    func openWatchNotificationDifferentNoResults() {
        var session = Session(phase: .setup)
        let otherID = UUID()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .openWatchNotification(otherID)
        )
        #expect(containsEffect(effects, .loadSession(otherID)))
    }

    @Test("restoreSession emits loadSession")
    func restoreSessionEmits() {
        let session = Session(phase: .setup)
        let id = UUID()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .restoreSession(id)
        )
        #expect(containsEffect(effects, .loadSession(id)))
    }

    @Test("deleteHistorySession emits deleteSession")
    func deleteHistorySessionEmits() {
        let session = Session(phase: .setup)
        let id = UUID()
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .deleteHistorySession(id)
        )
        #expect(containsEffect(effects, .deleteSession(id)))
    }

    @Test("sessionLoaded restores full session from persisted data")
    func sessionLoadedRestores() {
        let session = Session(phase: .setup)
        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 1_000_000),
            directories: ["/other"],
            sourceLabel: "other scan",
            mode: .image,
            pairCount: 42,
            fileCount: 200
        )
        let envelope = makeEnvelope(pairs: [makePair()])
        let persisted = PersistedSession(
            id: UUID(),
            config: SessionConfig(),
            results: PersistedResults(
                envelope: envelope,
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: []
            ),
            metadata: metadata,
            watchConfig: nil
        )
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .sessionLoaded(persisted, nil)
        )
        #expect(newState.metadata.sourceLabel == "other scan")
        #expect(newState.metadata.mode == .image)
        #expect(newState.metadata.pairCount == 42)
        #expect(newState.phase == .results)
        #expect(newState.results != nil)
        // Should emit file status effects
        #expect(effects.contains { if case .checkFileStatuses = $0 { return true }; return false })
        #expect(effects.contains { if case .startFileMonitor = $0 { return true }; return false })
    }

    @Test("menuCommand ignore with selected pair delegates to ignorePair")
    func menuCommandIgnore() {
        var session = resultsSession()
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        session.display.selectedPairID = pairID
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .menuCommand(.ignore)
        )
        #expect(newState.results?.ignoredPairs.contains(pairID) == true)
        #expect(effects.contains { if case .addToIgnoreList = $0 { return true }; return false })
    }

    @Test("menuCommand ignore without selected pair is no-op")
    func menuCommandIgnoreNoSelection() {
        let session = resultsSession()
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .menuCommand(.ignore)
        )
        #expect(newState.results?.ignoredPairs.isEmpty == true)
        #expect(effects.isEmpty)
    }

    @Test("sessionLoaded during scanning phase is discarded (phase guard)")
    func sessionLoadedDuringScanningIsDiscarded() {
        var session = Session(phase: .scanning)
        session.scan = ScanProgress()
        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 1_000_000),
            directories: ["/other"],
            sourceLabel: "other scan",
            mode: .image,
            pairCount: 42,
            fileCount: 200
        )
        let envelope = makeEnvelope(pairs: [makePair()])
        let persisted = PersistedSession(
            id: UUID(),
            config: SessionConfig(),
            results: PersistedResults(
                envelope: envelope,
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: []
            ),
            metadata: metadata,
            watchConfig: nil
        )
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .sessionLoaded(persisted, nil)
        )
        // Phase should remain .scanning -- the load is discarded
        #expect(newState.phase == .scanning)
        // No effects should be emitted
        #expect(effects.isEmpty)
        // Results should NOT be populated from the persisted data
        #expect(newState.results == nil)
        // Metadata should not change
        #expect(newState.metadata.sourceLabel != "other scan")
    }

    @Test("sessionLoaded during setup phase applies the session (existing behavior)")
    func sessionLoadedDuringSetupApplies() {
        let session = Session(phase: .setup)
        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 1_000_000),
            directories: ["/restored"],
            sourceLabel: "restored scan",
            mode: .video,
            pairCount: 10,
            fileCount: 50
        )
        let envelope = makeEnvelope(pairs: [makePair()])
        let persisted = PersistedSession(
            id: UUID(),
            config: SessionConfig(),
            results: PersistedResults(
                envelope: envelope,
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: []
            ),
            metadata: metadata,
            watchConfig: nil
        )
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .sessionLoaded(persisted, nil)
        )
        // Phase should transition to .results
        #expect(newState.phase == .results)
        #expect(newState.results != nil)
        #expect(newState.metadata.sourceLabel == "restored scan")
        // Should emit file status effects
        #expect(!effects.isEmpty)
    }

    @Test("sessionLoaded during results phase applies the session")
    func sessionLoadedDuringResultsApplies() {
        let existingSession = resultsSession()
        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 2_000_000),
            directories: ["/new-results"],
            sourceLabel: "new scan",
            mode: .image,
            pairCount: 7,
            fileCount: 30
        )
        let envelope = makeEnvelope(pairs: [makePair()])
        let persisted = PersistedSession(
            id: UUID(),
            config: SessionConfig(),
            results: PersistedResults(
                envelope: envelope,
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: []
            ),
            metadata: metadata,
            watchConfig: nil
        )
        let (newState, effects) = SessionReducer.reduce(
            state: existingSession,
            action: .sessionLoaded(persisted, nil)
        )
        // Phase should be .results with the new session data
        #expect(newState.phase == .results)
        #expect(newState.metadata.sourceLabel == "new scan")
        #expect(newState.metadata.mode == .image)
        #expect(!effects.isEmpty)
    }

    @Test("sessionLoaded during error phase is discarded (phase guard)")
    func sessionLoadedDuringErrorIsDiscarded() {
        let errorInfo = ErrorInfo(message: "Something failed", category: .binaryNotFound)
        let session = Session(phase: .error(errorInfo))
        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 1_000_000),
            directories: ["/other"],
            sourceLabel: "other scan",
            mode: .video,
            pairCount: 5,
            fileCount: 20
        )
        let envelope = makeEnvelope(pairs: [makePair()])
        let persisted = PersistedSession(
            id: UUID(),
            config: SessionConfig(),
            results: PersistedResults(
                envelope: envelope,
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: []
            ),
            metadata: metadata,
            watchConfig: nil
        )
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .sessionLoaded(persisted, nil)
        )
        // Phase should remain .error -- the load is discarded
        #expect(newState.phase == .error(errorInfo))
        #expect(effects.isEmpty)
        #expect(newState.results == nil)
    }

    @Test("menuCommand in non-results phase is no-op")
    func menuCommandNonResults() {
        let session = Session(phase: .setup)
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .menuCommand(.skip)
        )
        #expect(effects.isEmpty)
    }
}

// MARK: - Pending Watch Pairs Persistence Tests

@Suite("Session Reducer: Pending Watch Pairs Persistence")
struct SessionReducerPendingWatchPairsTests {

    @Test("Persistence round-trip preserves group-mode pending watch pairs")
    func persistenceRoundTripGroupModeWatchPairs() throws {
        // Arrange: create a session with a groups envelope and active watch
        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 90,
            minScore: 90,
            avgScore: 90,
            files: [
                GroupFile(path: "/videos/a.mp4", fileSize: 1_000_000, isReference: false),
                GroupFile(path: "/videos/b.mp4", fileSize: 900_000, isReference: false),
            ],
            pairs: [
                GroupPair(
                    fileA: "/videos/a.mp4", fileB: "/videos/b.mp4",
                    score: 90, breakdown: ["filename": 40.0], detail: [:]
                ),
            ],
            keep: "a"
        )
        let envelope = makeEnvelope(groups: [group], keep: "newest")
        var session = resultsSession(envelope: envelope)
        session.display = DisplayState(viewMode: .groups)
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")

        // Act: dispatch watchAlertReceived with new pairs while in groups mode
        let watchPair = makePair(fileA: "/videos/x.mp4", fileB: "/videos/y.mp4", score: 75)
        let (afterWatch, _) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([watchPair])
        )

        // Verify pairs are buffered in pendingWatchPairs (not merged into groups envelope)
        #expect(afterWatch.results?.pendingWatchPairs.count == 1)
        #expect(afterWatch.results?.pendingWatchPairs.first?.fileA == "/videos/x.mp4")

        // Persist the session
        let persisted = afterWatch.persisted()
        #expect(persisted != nil, "persisted() should return non-nil when results exist")
        #expect(persisted!.results.pendingWatchPairs.count == 1)
        #expect(persisted!.results.pendingWatchPairs.first?.fileA == "/videos/x.mp4")

        // Reconstruct from persisted data
        let restored = Session(from: persisted!)
        #expect(restored.phase == .results)
        #expect(restored.results?.pendingWatchPairs.count == 1)
        #expect(restored.results?.pendingWatchPairs.first?.fileA == "/videos/x.mp4")
        #expect(restored.results?.pendingWatchPairs.first?.fileB == "/videos/y.mp4")
        #expect(restored.results?.pendingWatchPairs.first?.score == 75)
    }

    @Test("Backward compatibility: old sessions without pendingWatchPairs decode with empty array")
    func backwardCompatOldSessionWithoutPendingWatchPairs() throws {
        // Build a PersistedResults JSON manually WITHOUT the pendingWatchPairs key,
        // simulating a session file saved before this feature was added.
        //
        // Note: ScanEnvelope's Decodable reads "pairs"/"groups" at the top level
        // of the envelope object (not nested inside a "content" wrapper).

        // PersistedResults JSON WITHOUT pendingWatchPairs field
        let resultsJSON = """
        {
            "envelope": {
                "version": "1.0.0",
                "generatedAt": "2025-01-01T00:00:00Z",
                "args": {
                    "directories": ["/videos"],
                    "threshold": 50,
                    "content": false,
                    "action": "trash",
                    "group": false,
                    "sort": "score",
                    "mode": "video",
                    "embedThumbnails": false
                },
                "stats": {
                    "filesScanned": 100,
                    "filesAfterFilter": 80,
                    "totalPairsScored": 200,
                    "pairsAboveThreshold": 1,
                    "scanTime": 1.0,
                    "extractTime": 2.0,
                    "filterTime": 0.5,
                    "contentHashTime": 0.0,
                    "scoringTime": 2.0,
                    "totalTime": 5.5
                },
                "pairs": [{
                    "fileA": "/a.mp4",
                    "fileB": "/b.mp4",
                    "score": 80.0,
                    "breakdown": {"filename": 40.0},
                    "detail": {},
                    "fileAMetadata": {"fileSize": 1000},
                    "fileBMetadata": {"fileSize": 900},
                    "fileAIsReference": false,
                    "fileBIsReference": false,
                    "keep": "a"
                }]
            },
            "resolutions": {},
            "ignoredPairs": [],
            "actionHistory": []
        }
        """

        let data = Data(resultsJSON.utf8)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        // Act: decode PersistedResults from JSON missing pendingWatchPairs
        let decoded = try decoder.decode(PersistedResults.self, from: data)

        // Assert: pendingWatchPairs defaults to empty array
        #expect(decoded.pendingWatchPairs.isEmpty)
        // Also verify the rest of the data decoded correctly
        if case .pairs(let pairs) = decoded.envelope.content {
            #expect(pairs.count == 1)
        } else {
            Issue.record("Expected pairs content")
        }
    }
}

// MARK: - Move-and-Restore Clears Stale Resolution Tests

@Suite("Session Reducer: Move Clears Stale Resolution")
struct SessionReducerMoveClearsStaleTests {

    @Test("Move marks pair as probablySolved, then present clears the stale resolution")
    func moveAndRestoreClearsStaleResolution() {
        // Arrange: create a session with a pair (a.mp4, b.mp4)
        let pair = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85)
        let envelope = makeEnvelope(pairs: [pair])
        let session = resultsSession(envelope: envelope)

        // Act 1: simulate file A being moved away
        let (afterMove, moveEffects) = SessionReducer.reduce(
            state: session,
            action: .watchFileBatchChanged(["/videos/a.mp4": .moved(to: "/tmp/other")])
        )

        // Assert 1: file status updated and pair gets .probablySolved resolution
        #expect(afterMove.results?.fileStatuses["/videos/a.mp4"] == .moved(to: "/tmp/other"))
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        #expect(afterMove.results?.resolutions[pairID] == .probablySolved(missing: ["/videos/a.mp4"]))
        #expect(containsEffect(moveEffects, .rebuildSynthesizedViews))

        // Act 2: simulate file A reappearing at its original path
        let (afterRestore, restoreEffects) = SessionReducer.reduce(
            state: afterMove,
            action: .watchFileBatchChanged(["/videos/a.mp4": .present])
        )

        // Assert 2: the stale .probablySolved resolution is cleared
        #expect(afterRestore.results?.fileStatuses["/videos/a.mp4"] == .present)
        #expect(afterRestore.results?.resolutions[pairID] == nil,
                "probablySolved should be cleared when the missing file reappears")
        #expect(containsEffect(restoreEffects, .rebuildSynthesizedViews))
    }
}

// MARK: - Fix 1: pendingWatchPairs NOT Drained on Synthesized Views Rebuild

@Suite("Session Reducer: pendingWatchPairs Persistence Across Rebuilds")
struct SessionReducerPendingWatchPairsDrainTests {

    @Test("updateSynthesizedViews does not drain pendingWatchPairs")
    func updateSynthesizedViewsPreservesPendingWatchPairs() {
        // Arrange: create a session with a groups envelope and watch pairs buffered
        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 90,
            minScore: 90,
            avgScore: 90,
            files: [
                GroupFile(path: "/videos/a.mp4", fileSize: 1_000_000, isReference: false),
                GroupFile(path: "/videos/b.mp4", fileSize: 900_000, isReference: false),
            ],
            pairs: [
                GroupPair(
                    fileA: "/videos/a.mp4", fileB: "/videos/b.mp4",
                    score: 90, breakdown: ["filename": 40.0], detail: [:]
                ),
            ],
            keep: "a"
        )
        let envelope = makeEnvelope(groups: [group], keep: "newest")
        var session = resultsSession(envelope: envelope)
        session.display = DisplayState(viewMode: .groups)
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")

        // Add a watch pair to pendingWatchPairs
        let watchPair = makePair(fileA: "/videos/x.mp4", fileB: "/videos/y.mp4", score: 75)
        let (afterWatch, _) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([watchPair])
        )
        #expect(afterWatch.results?.pendingWatchPairs.count == 1)

        // Act: dispatch updateSynthesizedViews with synthesized pairs
        let synthesizedPair = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 90)
        let (afterUpdate, _) = SessionReducer.reduce(
            state: afterWatch,
            action: .updateSynthesizedViews(groups: nil, pairs: [synthesizedPair])
        )

        // Assert: pendingWatchPairs is still populated (NOT drained)
        #expect(afterUpdate.results?.pendingWatchPairs.count == 1,
                "pendingWatchPairs must persist across updateSynthesizedViews — the buffer is append-only")
        #expect(afterUpdate.results?.pendingWatchPairs.first?.fileA == "/videos/x.mp4")

        // Assert: the synthesized pairs include the watch pair merged in
        #expect(afterUpdate.results?.synthesizedPairs?.count == 2,
                "synthesizedPairs should contain both the provided pair and the pending watch pair")
        let synthPaths = afterUpdate.results?.synthesizedPairs?.map(\.fileA) ?? []
        #expect(synthPaths.contains("/videos/x.mp4"),
                "Watch pair should be merged into synthesized pairs")
        #expect(synthPaths.contains("/videos/a.mp4"),
                "Original synthesized pair should be present")
    }
}

// MARK: - Fix 3: collectFilePaths Includes pendingWatchPairs Paths

@Suite("Session Reducer: File Monitor Paths Include Watch Pairs")
struct SessionReducerWatchPairFileMonitorTests {

    @Test("file monitor paths include pending watch pair files after restore")
    func fileMonitorPathsIncludeWatchPairFiles() {
        // Arrange: create a groups-envelope session with pendingWatchPairs
        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 90,
            minScore: 90,
            avgScore: 90,
            files: [
                GroupFile(path: "/videos/a.mp4", fileSize: 1_000_000, isReference: false),
                GroupFile(path: "/videos/b.mp4", fileSize: 900_000, isReference: false),
            ],
            pairs: [
                GroupPair(
                    fileA: "/videos/a.mp4", fileB: "/videos/b.mp4",
                    score: 90, breakdown: ["filename": 40.0], detail: [:]
                ),
            ],
            keep: "a"
        )
        let envelope = makeEnvelope(groups: [group], keep: "newest")
        let watchPair = makePair(fileA: "/videos/watch1.mp4", fileB: "/videos/watch2.mp4", score: 72)

        // Build a PersistedSession with pendingWatchPairs containing unique paths
        let persisted = PersistedSession(
            id: UUID(),
            config: SessionConfig(),
            results: PersistedResults(
                envelope: envelope,
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: [watchPair]
            ),
            metadata: SessionMetadata(
                createdAt: Date(),
                directories: ["/videos"],
                sourceLabel: "test",
                mode: .video,
                pairCount: 1,
                fileCount: 100
            ),
            watchConfig: nil
        )

        // Act: dispatch sessionLoaded which internally calls collectFilePaths
        let session = Session(phase: .setup)
        let (newState, effects) = SessionReducer.reduce(
            state: session,
            action: .sessionLoaded(persisted, nil)
        )

        // Assert: session loaded correctly
        #expect(newState.phase == .results)
        #expect(newState.results?.pendingWatchPairs.count == 1)

        // Assert: the startFileMonitor effect includes watch pair paths
        var monitorPaths: [String]?
        for effect in effects {
            if case .startFileMonitor(let paths) = effect {
                monitorPaths = paths
                break
            }
        }
        #expect(monitorPaths != nil, "sessionLoaded should emit .startFileMonitor")
        #expect(monitorPaths?.contains("/videos/watch1.mp4") == true,
                "File monitor paths must include pending watch pair fileA")
        #expect(monitorPaths?.contains("/videos/watch2.mp4") == true,
                "File monitor paths must include pending watch pair fileB")
        // Also verify envelope paths are included
        #expect(monitorPaths?.contains("/videos/a.mp4") == true,
                "File monitor paths must include envelope group file paths")
        #expect(monitorPaths?.contains("/videos/b.mp4") == true,
                "File monitor paths must include envelope group file paths")

        // Assert: the checkFileStatuses effect also includes watch pair paths
        var checkPaths: [String]?
        for effect in effects {
            if case .checkFileStatuses(let paths) = effect {
                checkPaths = paths
                break
            }
        }
        #expect(checkPaths != nil, "sessionLoaded should emit .checkFileStatuses")
        #expect(checkPaths?.contains("/videos/watch1.mp4") == true,
                "Check file statuses must include pending watch pair fileA")
        #expect(checkPaths?.contains("/videos/watch2.mp4") == true,
                "Check file statuses must include pending watch pair fileB")
    }
}

// MARK: - Fix 4: Stale Envelope Data Re-encoded on Save

@Suite("Session Reducer: lastOriginalEnvelope Staleness")
struct SessionReducerEnvelopeStalenessTests {

    @Test("watchAlertReceived for pair-mode nils lastOriginalEnvelope")
    func watchAlertPairModeNilsOriginalEnvelope() {
        // Arrange: pair-mode session with lastOriginalEnvelope set
        var session = resultsSession()
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")
        session.lastOriginalEnvelope = Data("original-raw-bytes".utf8)

        // Precondition: verify pair-mode
        if case .pairs = session.results?.envelope.content {} else {
            Issue.record("Expected pairs content for this test")
            return
        }

        // Act: receive a watch alert
        let newPair = makePair(fileA: "/videos/x.mp4", fileB: "/videos/y.mp4")
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([newPair])
        )

        // Assert: lastOriginalEnvelope is nil because the envelope was mutated
        #expect(newState.lastOriginalEnvelope == nil,
                "Pair-mode watch alert mutates the envelope, so lastOriginalEnvelope must be nil to force re-encoding on save")
    }

    @Test("watchAlertReceived for groups-mode preserves lastOriginalEnvelope")
    func watchAlertGroupsModePreservesOriginalEnvelope() {
        // Arrange: groups-mode session with lastOriginalEnvelope set
        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 90,
            minScore: 90,
            avgScore: 90,
            files: [
                GroupFile(path: "/videos/a.mp4", fileSize: 1_000_000, isReference: false),
                GroupFile(path: "/videos/b.mp4", fileSize: 900_000, isReference: false),
            ],
            pairs: [
                GroupPair(
                    fileA: "/videos/a.mp4", fileB: "/videos/b.mp4",
                    score: 90, breakdown: ["filename": 40.0], detail: [:]
                ),
            ],
            keep: "a"
        )
        let envelope = makeEnvelope(groups: [group], keep: "newest")
        var session = resultsSession(envelope: envelope)
        session.display = DisplayState(viewMode: .groups)
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")
        let originalData = Data("original-raw-bytes".utf8)
        session.lastOriginalEnvelope = originalData

        // Act: receive a watch alert (groups mode buffers in pendingWatchPairs)
        let newPair = makePair(fileA: "/videos/x.mp4", fileB: "/videos/y.mp4")
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([newPair])
        )

        // Assert: lastOriginalEnvelope is preserved because the envelope itself was not mutated
        #expect(newState.lastOriginalEnvelope == originalData,
                "Groups-mode watch alert buffers in pendingWatchPairs without mutating envelope, so lastOriginalEnvelope should be preserved")
        // Also verify watch pair went to pendingWatchPairs
        #expect(newState.results?.pendingWatchPairs.count == 1)
    }
}

// MARK: - Fix: Watch Baseline Includes Pending Watch Pairs

@Suite("Session Reducer: Watch Baseline Includes Pending Watch Pairs")
struct SessionReducerWatchBaselinePendingTests {

    @Test("watch baseline includes pending watch pair files")
    func watchBaselineIncludesPendingWatchPairFiles() {
        // Arrange: create a groups-envelope session with pendingWatchPairs
        // containing unique file paths not present in the envelope itself.
        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 90,
            minScore: 90,
            avgScore: 90,
            files: [
                GroupFile(
                    path: "/videos/a.mp4", duration: nil, width: nil, height: nil,
                    fileSize: 1000, codec: nil, bitrate: nil, framerate: nil,
                    audioChannels: nil, mtime: nil, tagTitle: nil, tagArtist: nil,
                    tagAlbum: nil, isReference: false, thumbnail: nil
                ),
                GroupFile(
                    path: "/videos/b.mp4", duration: nil, width: nil, height: nil,
                    fileSize: 900, codec: nil, bitrate: nil, framerate: nil,
                    audioChannels: nil, mtime: nil, tagTitle: nil, tagArtist: nil,
                    tagAlbum: nil, isReference: false, thumbnail: nil
                ),
            ],
            pairs: [GroupPair(
                fileA: "/videos/a.mp4", fileB: "/videos/b.mp4",
                score: 90, breakdown: [:], detail: [:]
            )],
            keep: "newest"
        )
        let envelope = makeEnvelope(groups: [group], keep: "newest")

        // Build session in results phase with a valid config so startWatch can use it
        var session = Session(
            phase: .results,
            config: SessionConfig(),
            results: ResultsSnapshot(envelope: envelope, isDryRun: false),
            display: DisplayState(viewMode: .groups)
        )

        // Add pending watch pairs with unique paths
        let watchPair = makePair(
            fileA: "/videos/watch1.mp4",
            fileB: "/videos/watch2.mp4"
        )
        session.results?.pendingWatchPairs = [watchPair]

        // Act: enable watch — buildKnownFiles should include pendingWatchPairs files
        let (_, effects) = SessionReducer.reduce(
            state: session,
            action: .setWatchEnabled(true)
        )

        // Assert: pattern-match the startWatch effect and inspect knownFiles
        var foundKnownFiles: [KnownFile]?
        for effect in effects {
            if case .startWatch(_, let knownFiles) = effect {
                foundKnownFiles = knownFiles
                break
            }
        }
        guard let knownFiles = foundKnownFiles else {
            Issue.record("Expected .startWatch effect to be emitted")
            return
        }

        let knownPaths = Set(knownFiles.map(\.path))
        // Envelope group files should be present
        #expect(knownPaths.contains("/videos/a.mp4"),
                "Known files should include envelope group file a.mp4")
        #expect(knownPaths.contains("/videos/b.mp4"),
                "Known files should include envelope group file b.mp4")
        // Pending watch pair files should ALSO be present
        #expect(knownPaths.contains("/videos/watch1.mp4"),
                "Known files should include pending watch pair file watch1.mp4")
        #expect(knownPaths.contains("/videos/watch2.mp4"),
                "Known files should include pending watch pair file watch2.mp4")
    }
}

// MARK: - Fix: watchAlertReceived Updates pairsAboveThreshold

@Suite("Session Reducer: Watch Alert Updates Pair Count Stats")
struct SessionReducerWatchAlertPairCountTests {

    @Test("watchAlertReceived updates pairsAboveThreshold for pair-mode")
    func watchAlertUpdatesPairsAboveThresholdPairMode() {
        // Arrange: create a pair-mode session with 1 existing pair
        let existingPair = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85)
        let envelope = makeEnvelope(pairs: [existingPair])
        // Confirm initial stats
        #expect(envelope.stats.pairsAboveThreshold == 1)

        var session = Session(
            phase: .results,
            results: ResultsSnapshot(envelope: envelope, isDryRun: false),
            display: DisplayState(viewMode: .pairs)
        )
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")

        // Act: dispatch watchAlertReceived with 2 new pairs
        let newPair1 = makePair(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 75)
        let newPair2 = makePair(fileA: "/videos/e.mp4", fileB: "/videos/f.mp4", score: 70)
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([newPair1, newPair2])
        )

        // Assert: pairsAboveThreshold should be 1 + 2 = 3
        #expect(newState.results?.envelope.stats.pairsAboveThreshold == 3,
                "pairsAboveThreshold should increment by the number of new watch pairs")
        // Assert: session metadata pairCount should match
        #expect(newState.metadata.pairCount == 3,
                "metadata.pairCount should be updated to match pairsAboveThreshold")
    }

    @Test("watchAlertReceived updates pairsAboveThreshold for groups-mode")
    func watchAlertUpdatesPairsAboveThresholdGroupsMode() {
        // Arrange: create a groups-mode session with pairsAboveThreshold of 1
        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 90,
            minScore: 90,
            avgScore: 90,
            files: [
                GroupFile(
                    path: "/videos/a.mp4", duration: nil, width: nil, height: nil,
                    fileSize: 1000, codec: nil, bitrate: nil, framerate: nil,
                    audioChannels: nil, mtime: nil, tagTitle: nil, tagArtist: nil,
                    tagAlbum: nil, isReference: false, thumbnail: nil
                ),
                GroupFile(
                    path: "/videos/b.mp4", duration: nil, width: nil, height: nil,
                    fileSize: 900, codec: nil, bitrate: nil, framerate: nil,
                    audioChannels: nil, mtime: nil, tagTitle: nil, tagArtist: nil,
                    tagAlbum: nil, isReference: false, thumbnail: nil
                ),
            ],
            pairs: [GroupPair(
                fileA: "/videos/a.mp4", fileB: "/videos/b.mp4",
                score: 90, breakdown: [:], detail: [:]
            )],
            keep: "newest"
        )
        // makeEnvelope with groups defaults pairsAboveThreshold to pairs.count (0 for groups),
        // so we need to manually set it to 1 to simulate a real groups session
        var envelope = makeEnvelope(groups: [group], keep: "newest")
        envelope.stats.pairsAboveThreshold = 1

        var session = Session(
            phase: .results,
            results: ResultsSnapshot(envelope: envelope, isDryRun: false),
            display: DisplayState(viewMode: .groups),
            metadata: SessionMetadata(pairCount: 1)
        )
        session.watch = WatchState(isActive: true, startedAt: Date(), sourceLabel: "test")

        // Act: dispatch watchAlertReceived with 1 new pair
        let newPair = makePair(fileA: "/videos/x.mp4", fileB: "/videos/y.mp4", score: 72)
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .watchAlertReceived([newPair])
        )

        // Assert: pairsAboveThreshold should be 1 + 1 = 2
        #expect(newState.results?.envelope.stats.pairsAboveThreshold == 2,
                "pairsAboveThreshold should increment by the number of new watch pairs in groups mode")
        // Assert: session metadata pairCount should match
        #expect(newState.metadata.pairCount == 2,
                "metadata.pairCount should be updated to match pairsAboveThreshold in groups mode")
        // Also verify the pair was buffered in pendingWatchPairs (groups mode behavior)
        #expect(newState.results?.pendingWatchPairs.count == 1,
                "Groups-mode watch hits should be buffered in pendingWatchPairs")
    }
}
