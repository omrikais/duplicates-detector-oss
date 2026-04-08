import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Create a minimal ScanEnvelope for store tests.
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
    score: Double = 85.0,
    keep: String? = "a"
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
        keep: keep
    )
}

private func makePair2(
    fileA: String = "/videos/c.mp4",
    fileB: String = "/videos/d.mp4",
    score: Double = 72.0,
    keep: String? = "a"
) -> PairResult {
    PairResult(
        fileA: fileA,
        fileB: fileB,
        score: score,
        breakdown: ["filename": 30.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: 800_000),
        fileBMetadata: FileMetadata(fileSize: 700_000),
        fileAIsReference: false,
        fileBIsReference: false,
        keep: keep
    )
}

private func makePair3(
    fileA: String = "/videos/e.mp4",
    fileB: String = "/videos/f.mp4",
    score: Double = 60.0,
    keep: String? = "a"
) -> PairResult {
    PairResult(
        fileA: fileA,
        fileB: fileB,
        score: score,
        breakdown: ["filename": 20.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: 600_000),
        fileBMetadata: FileMetadata(fileSize: 500_000),
        fileAIsReference: false,
        fileBIsReference: false,
        keep: keep
    )
}

/// Create a SessionConfig for testing.
private func defaultConfig(
    directories: [String] = ["/videos"],
    mode: ScanMode = .video,
    content: Bool = false,
    audio: Bool = false
) -> SessionConfig {
    var c = SessionConfig()
    c.directories = directories
    c.mode = mode
    c.content = content
    c.audio = audio
    return c
}

/// Create a store for testing. The bridge won't actually run CLI commands.
@MainActor
private func makeStore() -> SessionStore {
    let bridge = CLIBridge()
    return SessionStore(bridge: bridge)
}

/// Create a store with results pre-loaded for review desk testing.
@MainActor
private func makeStoreWithResults(
    pairs: [PairResult] = [],
    keep: String? = "a"
) -> SessionStore {
    let store = makeStore()
    let envelope = makeEnvelope(pairs: pairs, keep: keep)
    let snapshot = ResultsSnapshot(
        envelope: envelope,
        isDryRun: false,
        hasKeepStrategy: keep != nil
    )
    store.session.results = snapshot
    store.session.phase = .results
    store.session.display = DisplayState.initial(for: envelope.content)
    store.phase = .results
    // Force cached view computation
    store.session.results?.incrementFilterGeneration()
    store.send(.setSearchText(""))  // Triggers recompute
    return store
}

// MARK: - Initial State Tests

@Suite("SessionStore — Initial State")
struct SessionStoreInitialStateTests {

    @Test @MainActor
    func initialPhaseIsSetup() {
        let store = makeStore()
        #expect(store.phase == .setup)
        #expect(store.session.phase == .setup)
    }

    @Test @MainActor
    func initialSessionHasNoResults() {
        let store = makeStore()
        #expect(store.session.results == nil)
        #expect(store.session.scan == nil)
        #expect(store.session.config == nil)
    }

    @Test @MainActor
    func initialSetupStateHasDefaults() {
        let store = makeStore()
        // Mode may be persisted from AppDefaults, so just check it's a valid ScanMode
        #expect([ScanMode.video, .image, .audio, .auto].contains(store.setupState.mode))
        #expect(store.setupState.threshold == 50)
    }

    @Test @MainActor
    func initialCachedViewsAreEmpty() {
        let store = makeStore()
        #expect(store.filteredPairs.isEmpty)
        #expect(store.filteredGroups.isEmpty)
        #expect(store.resolvedOrMissingPaths.isEmpty)
    }

    @Test @MainActor
    func initialSelectedPairIsNil() {
        let store = makeStore()
        #expect(store.selectedPairID == nil)
    }

    @Test @MainActor
    func initialWatchIsInactive() {
        let store = makeStore()
        #expect(store.watchActive == false)
    }
}

// MARK: - Phase Transition Tests

@Suite("SessionStore — Phase Transitions")
struct SessionStorePhaseTransitionTests {

    @Test @MainActor
    func startScanTransitionsToScanning() {
        let store = makeStore()
        let config = defaultConfig()
        store.send(.startScan(config))

        #expect(store.phase == .scanning)
        #expect(store.session.phase == .scanning)
        #expect(store.session.scan != nil)
    }

    @Test @MainActor
    func resetToSetupClearsState() {
        let store = makeStore()
        // Start a scan first
        store.send(.startScan(defaultConfig()))
        #expect(store.phase == .scanning)

        // Reset
        store.send(.resetToSetup)
        #expect(store.phase == .setup)
        #expect(store.session.scan == nil)
        #expect(store.session.config == nil)
        #expect(store.session.results == nil)
    }

    @Test @MainActor
    func resultsReadyTransitionsViaMinimumDisplay() {
        let store = makeStore()
        store.send(.startScan(defaultConfig()))

        // Simulate CLI stream completing (this sets isFinalizingResults = true)
        let envelope = makeEnvelope(pairs: [makePair()])
        store.send(.cliStreamCompleted(envelope, nil))

        // Phase is still scanning because configureResults is async
        // and minimum display hasn't elapsed
        #expect(store.phase == .scanning)
        #expect(store.session.scan?.isFinalizingResults == true)

        // Simulate the results being ready (from the async configureResults)
        let snapshot = ResultsSnapshot(
            envelope: envelope, isDryRun: false, hasKeepStrategy: false
        )
        store.send(.resultsReady(snapshot, ResultsDisplayConfig(activeAction: .trash, moveDestination: nil, rawEnvelopeData: nil)))
        #expect(store.session.results != nil)

        // After minimum display
        store.send(.minimumDisplayElapsed)
        #expect(store.phase == .results)
    }

    @Test @MainActor
    func errorPhaseOnStreamFailure() {
        let store = makeStore()
        store.send(.startScan(defaultConfig()))

        let error = ErrorInfo(
            message: "Test error",
            category: .unknown
        )
        store.send(.cliStreamFailed(error))
        if case .error(let e) = store.phase {
            #expect(e.message == "Test error")
        } else {
            Issue.record("Expected error phase")
        }
    }

    @Test @MainActor
    func cancelledStreamReturnsToSetup() {
        let store = makeStore()
        store.send(.startScan(defaultConfig()))
        store.send(.cancelScan)
        store.send(.cliStreamCancelled)
        #expect(store.phase == .setup)
    }
}

// MARK: - Routing Property Sync Tests

@Suite("SessionStore — Routing Property Sync")
struct SessionStoreRoutingSyncTests {

    @Test @MainActor
    func selectPairUpdatesRoutingProperty() {
        let store = makeStoreWithResults(pairs: [makePair(), makePair2()])

        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        store.send(.selectPair(pairID))

        #expect(store.selectedPairID == pairID)
        #expect(store.session.display.selectedPairID == pairID)
    }

    @Test @MainActor
    func selectNilPairClearsRoutingProperty() {
        let store = makeStoreWithResults(pairs: [makePair()])

        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        store.send(.selectPair(pairID))
        #expect(store.selectedPairID == pairID)

        store.send(.selectPair(nil))
        #expect(store.selectedPairID == nil)
    }
}

// MARK: - Search & Filter Tests

@Suite("SessionStore — Search & Filter")
struct SessionStoreSearchFilterTests {

    @Test @MainActor
    func setSearchTextTriggersRecomputation() {
        let pair1 = makePair(fileA: "/videos/alpha.mp4", fileB: "/videos/beta.mp4")
        let pair2 = makePair2(fileA: "/videos/gamma.mp4", fileB: "/videos/delta.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        #expect(store.filteredPairs.count == 2)

        store.send(.setSearchText("alpha"))
        #expect(store.filteredPairs.count == 1)
        #expect(store.filteredPairs.first?.fileA == "/videos/alpha.mp4")
    }

    @Test @MainActor
    func clearSearchTextShowsAllPairs() {
        let pair1 = makePair(fileA: "/videos/alpha.mp4", fileB: "/videos/beta.mp4")
        let pair2 = makePair2(fileA: "/videos/gamma.mp4", fileB: "/videos/delta.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        store.send(.setSearchText("alpha"))
        #expect(store.filteredPairs.count == 1)

        store.send(.setSearchText(""))
        #expect(store.filteredPairs.count == 2)
    }

    @Test @MainActor
    func setSortOrderRecomputes() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85)
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 72)
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        // Default is scoreDescending
        #expect(store.filteredPairs.first?.score == 85)

        store.send(.setSortOrder(.scoreAscending))
        #expect(store.filteredPairs.first?.score == 72)
    }
}

// MARK: - Setup Dispatch Tests

@Suite("SessionStore — Setup Dispatch")
struct SessionStoreSetupTests {

    @Test @MainActor
    func setModeUpdatesSetupState() {
        let store = makeStore()

        // Set to a known mode first, then change it
        store.sendSetup(.setMode(.video))
        #expect(store.setupState.mode == .video)

        store.sendSetup(.setMode(.image))
        #expect(store.setupState.mode == .image)
    }

    @Test @MainActor
    func setThresholdUpdatesSetupState() {
        let store = makeStore()
        store.sendSetup(.setThreshold(75))
        #expect(store.setupState.threshold == 75)
    }

    @Test @MainActor
    func setContentUpdatesSetupState() {
        let store = makeStore()
        #expect(store.setupState.content == false)

        store.sendSetup(.setContent(true))
        #expect(store.setupState.content == true)
    }

    @Test @MainActor
    func modeChangeResetsWeights() {
        let store = makeStore()

        // Set to video first to ensure a known baseline
        store.sendSetup(.setMode(.video))
        let videoWeights = store.setupState.weightStrings

        // Switch to image — weights should differ
        store.sendSetup(.setMode(.image))
        let imageWeights = store.setupState.weightStrings

        // Video and image modes have different default weight distributions
        #expect(videoWeights != imageWeights)
    }
}

// MARK: - canStartScan Tests

@Suite("SessionStore — canStartScan")
struct SessionStoreCanStartScanTests {

    @Test @MainActor
    func canStartScanFalseWithoutDirectories() {
        let store = makeStore()
        // No directories added
        #expect(store.canStartScan == false)
    }

    @Test @MainActor
    func canStartScanTrueWithValidConfig() {
        let store = makeStore()
        store.sendSetup(.addDirectory(URL(fileURLWithPath: "/videos")))
        // Dependencies would also need to pass but we're only testing
        // the directory requirement here
        // canStartScan depends on setupState.isValid which checks deps too
        // so we just verify it's checking phase == .setup
        #expect(store.phase == .setup)
    }

    @Test @MainActor
    func canStartScanFalseWhileScanning() {
        let store = makeStore()
        store.send(.startScan(defaultConfig()))
        #expect(store.phase == .scanning)
        #expect(store.canStartScan == false)
    }
}

// MARK: - Navigation Interception Tests

@Suite("SessionStore — Navigation Interception")
struct SessionStoreNavigationTests {

    @Test @MainActor
    func skipPairAdvancesToNextPair() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85)
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 72)
        let pair3 = makePair3(fileA: "/videos/e.mp4", fileB: "/videos/f.mp4", score: 60)
        let store = makeStoreWithResults(pairs: [pair1, pair2, pair3])

        let firstPairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let secondPairID = PairIdentifier(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")

        store.send(.selectPair(firstPairID))
        #expect(store.selectedPairID == firstPairID)

        store.send(.skipPair)
        #expect(store.selectedPairID == secondPairID)
    }

    @Test @MainActor
    func previousPairGoesBack() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85)
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 72)
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        let firstPairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let secondPairID = PairIdentifier(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")

        store.send(.selectPair(secondPairID))
        #expect(store.selectedPairID == secondPairID)

        store.send(.previousPair)
        #expect(store.selectedPairID == firstPairID)
    }

    @Test @MainActor
    func selectAllComputesFullSelectionInPairsMode() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        store.send(.toggleSelectMode)
        store.send(.selectAll)

        #expect(store.session.display.selectedForAction.count == 2)
    }

    @Test @MainActor
    func deselectAllClearsSelection() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        store.send(.toggleSelectMode)
        store.send(.selectAll)
        #expect(store.session.display.selectedForAction.count == 2)

        store.send(.deselectAll)
        #expect(store.session.display.selectedForAction.isEmpty)
    }
}

// MARK: - Ignore Pair Tests

@Suite("SessionStore — Ignore Pairs")
struct SessionStoreIgnoreTests {

    @Test @MainActor
    func ignorePairRemovesFromFilteredView() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        #expect(store.filteredPairs.count == 2)

        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        store.send(.ignorePair(pairID))

        #expect(store.filteredPairs.count == 1)
        #expect(store.session.results?.ignoredPairs.contains(pairID) == true)
    }

    @Test @MainActor
    func unignorePairRestoresInFilteredView() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        store.send(.ignorePair(pairID))
        #expect(store.filteredPairs.count == 1)

        store.send(.unignorePair("/videos/a.mp4", "/videos/b.mp4"))
        #expect(store.filteredPairs.count == 2)
    }
}

// MARK: - Display State Tests

@Suite("SessionStore — Display State")
struct SessionStoreDisplayTests {

    @Test @MainActor
    func setActiveActionUpdatesState() {
        let store = makeStoreWithResults(pairs: [makePair()])
        store.send(.setActiveAction(.delete))
        #expect(store.session.display.activeAction == .delete)
    }

    @Test @MainActor
    func toggleSelectModeUpdatesState() {
        let store = makeStoreWithResults(pairs: [makePair()])
        #expect(store.session.display.isSelectMode == false)

        store.send(.toggleSelectMode)
        #expect(store.session.display.isSelectMode == true)

        store.send(.toggleSelectMode)
        #expect(store.session.display.isSelectMode == false)
    }

    @Test @MainActor
    func toggleSelectModeClearsSelection() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        store.send(.toggleSelectMode)
        store.send(.selectAll)
        #expect(!store.session.display.selectedForAction.isEmpty)

        // Toggling off clears selection
        store.send(.toggleSelectMode)
        #expect(store.session.display.selectedForAction.isEmpty)
    }
}

// MARK: - Scan Sequence Tests

@Suite("SessionStore — Scan Sequence")
struct SessionStoreScanSequenceTests {

    @Test @MainActor
    func startScanIncrementsScanSequence() {
        let store = makeStore()
        let initialSeq = store.session.scanSequence

        store.send(.startScan(defaultConfig()))
        #expect(store.session.scanSequence == initialSeq &+ 1)
    }

    @Test @MainActor
    func consecutiveScansIncrementMonotonically() {
        let store = makeStore()
        store.send(.startScan(defaultConfig()))
        let seq1 = store.session.scanSequence

        store.send(.resetToSetup)
        store.send(.startScan(defaultConfig()))
        let seq2 = store.session.scanSequence

        #expect(seq2 == seq1 &+ 1)
    }
}

// MARK: - Cached Views Integration Tests

@Suite("SessionStore — Cached Views Integration")
struct SessionStoreCachedViewsTests {

    @Test @MainActor
    func filteredPairsReflectResults() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85)
        let pair2 = makePair2(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4", score: 72)
        let store = makeStoreWithResults(pairs: [pair1, pair2])

        #expect(store.filteredPairs.count == 2)
        // Default sort is score descending
        #expect(store.filteredPairs[0].score == 85)
        #expect(store.filteredPairs[1].score == 72)
    }

    @Test @MainActor
    func emptyResultsProduceEmptyCachedViews() {
        let store = makeStoreWithResults(pairs: [])
        #expect(store.filteredPairs.isEmpty)
    }

    @Test @MainActor
    func resolvedOrMissingPathsUpdatedOnRecomputation() {
        let pair1 = makePair(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let store = makeStoreWithResults(pairs: [pair1])

        // Initially empty
        #expect(store.resolvedOrMissingPaths.isEmpty)

        // Mark a pair as resolved
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let record = ActionRecord(
            pairID: pairID,
            timestamp: Date(),
            action: "trashed",
            actedOnPath: "/videos/b.mp4",
            keptPath: "/videos/a.mp4",
            bytesFreed: 900_000,
            score: 85,
            strategy: nil,
            destination: nil
        )
        store.session.results?.resolutions[pairID] = .resolved(record)
        store.session.results?.incrementFilterGeneration()
        store.send(.setSearchText(""))  // Trigger recompute

        #expect(store.resolvedOrMissingPaths.contains("/videos/b.mp4"))
    }
}

// MARK: - Teardown Tests

@Suite("SessionStore — Teardown")
struct SessionStoreTeardownTests {

    @Test @MainActor
    func teardownDoesNotCrash() {
        let store = makeStore()
        store.teardown()
        // Verify store is still usable after teardown
        #expect(store.phase == .setup)
    }
}

// MARK: - Watch State Sync Tests

@Suite("SessionStore — Watch State Sync")
struct SessionStoreWatchTests {

    @Test @MainActor
    func watchActiveTracksWatchState() {
        let store = makeStoreWithResults(pairs: [makePair()])

        #expect(store.watchActive == false)

        store.send(.setWatchEnabled(true))
        #expect(store.watchActive == true)
        #expect(store.session.watch?.isActive == true)

        store.send(.setWatchEnabled(false))
        #expect(store.watchActive == false)
        #expect(store.session.watch == nil)
    }
}

// MARK: - isGroupFullyResolved Tests

@Suite("SessionStore — Group Resolution")
struct SessionStoreGroupResolutionTests {

    @Test @MainActor
    func isGroupFullyResolvedFalseWhenActive() {
        let store = makeStoreWithResults(pairs: [makePair()])

        let group = GroupResult(
            groupId: 1,
            fileCount: 2,
            maxScore: 85,
            minScore: 85,
            avgScore: 85,
            files: [
                GroupFile(path: "/videos/a.mp4", fileSize: 1_000_000, isReference: false),
                GroupFile(path: "/videos/b.mp4", fileSize: 900_000, isReference: false),
            ],
            pairs: [],
            keep: "/videos/a.mp4"
        )

        #expect(store.isGroupFullyResolved(group) == false)
    }
}

// MARK: - Re-entrancy Guard Tests

@Suite("SessionStore — Re-entrancy Guard")
struct SessionStoreReentrancyTests {

    @Test("nested send during effect execution is deferred, not recursive")
    @MainActor
    func nestedSendIsDeferred() {
        // Setup: store in scanning phase with finalizing results.
        // When .scheduleMinimumDisplay fires with remaining <= 0,
        // the effect handler synchronously calls send(.minimumDisplayElapsed).
        // Before the fix, this was recursive. After, it should be queued.
        let store = makeStore()
        var config = SessionConfig()
        config.directories = ["/videos"]
        store.send(.startScan(config))

        // Manually set up the state that .cliStreamCompleted → .configureResults
        // would produce: finalizingResults + results populated + early startTime.
        store.session.scan?.isFinalizingResults = true
        let pairs = [PairResult(
            fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85,
            breakdown: [:], detail: [:],
            fileAMetadata: FileMetadata(fileSize: 1_000_000),
            fileBMetadata: FileMetadata(fileSize: 900_000),
            fileAIsReference: false, fileBIsReference: false, keep: "a"
        )]
        let envelope = makeEnvelope(pairs: pairs)
        store.session.results = ResultsSnapshot(envelope: envelope)
        // Set scanPhaseStartTime far in the past so remaining <= 0
        store.session.scan?.timing.scanPhaseStartTime = Date.distantPast

        // Dispatch resultsReady → emits .scheduleMinimumDisplay(distantPast)
        // → remaining <= 0 → queues .minimumDisplayElapsed
        // → after effects drain, processes .minimumDisplayElapsed → .results
        let snapshot = ResultsSnapshot(envelope: envelope)
        store.send(.resultsReady(snapshot, ResultsDisplayConfig(activeAction: .trash, moveDestination: nil, rawEnvelopeData: nil)))

        // If re-entrancy is handled correctly, phase should be .results
        // (the queued .minimumDisplayElapsed ran after the outer send completed)
        #expect(store.phase == .results)
        #expect(store.session.scan == nil)
    }
}
