import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Create a default SessionConfig for testing.
private func defaultConfig(
    directories: [String] = ["/videos"],
    mode: ScanMode = .video,
    content: Bool = false,
    audio: Bool = false,
    embedThumbnails: Bool = false,
    contentMethod: ContentMethod = .phash
) -> SessionConfig {
    var c = SessionConfig()
    c.directories = directories
    c.mode = mode
    c.content = content
    c.audio = audio
    c.embedThumbnails = embedThumbnails
    c.contentMethod = contentMethod
    return c
}

/// Create a Session in .scanning phase with ScanProgress initialized.
private func scanningSession(
    config: SessionConfig? = nil,
    overallStartTime: Date? = Date(),
    currentThroughput: Double? = nil,
    currentSessionId: String? = nil,
    pauseFileURL: URL? = nil
) -> Session {
    let cfg = config ?? defaultConfig()
    var session = Session(phase: .scanning)
    session.lastScanConfig = cfg
    var scan = ScanProgress()
    scan.stages = ScanProgress.initialStages(
        mode: cfg.mode, content: cfg.content, audio: cfg.audio,
        embedThumbnails: cfg.embedThumbnails, contentMethod: cfg.contentMethod ?? .phash
    )
    scan.timing.scanPhaseStartTime = Date()
    scan.timing.overallStartTime = overallStartTime
    scan.currentThroughput = currentThroughput
    scan.currentSessionId = currentSessionId
    scan.pauseFileURL = pauseFileURL
    session.scan = scan
    return session
}

/// Create a Session in .scanning phase with pause state set to .pausing.
private func pausingSession(
    sessionId: String? = "sess-1",
    overallStartTime: Date? = Date(),
    currentThroughput: Double? = 42.5,
    pauseFileURL: URL? = URL(fileURLWithPath: "/tmp/pause")
) -> Session {
    var session = Session(phase: .scanning)
    var scan = ScanProgress()
    scan.pause = .pausing(sessionId: sessionId)
    scan.stages = ScanProgress.initialStages(mode: .video, content: false, audio: false)
    scan.timing.overallStartTime = overallStartTime
    scan.timing.scanPhaseStartTime = Date()
    scan.currentThroughput = currentThroughput
    scan.currentSessionId = sessionId
    scan.pauseFileURL = pauseFileURL
    // Mark first stage as active
    if !scan.stages.isEmpty {
        scan.stages[0].status = .active(current: 5, total: 10)
        scan.stages[0].currentFile = "file.mp4"
    }
    session.scan = scan
    session.lastScanConfig = defaultConfig()
    return session
}

/// Create a Session in .scanning phase with pause state set to .paused.
private func pausedSession(
    sessionId: String? = "sess-1",
    overallStartTime: Date? = Date(),
    currentThroughput: Double? = 42.5,
    pauseStartTime: Date? = Date(),
    accumulatedPauseDuration: TimeInterval = 0,
    pauseFileURL: URL? = URL(fileURLWithPath: "/tmp/pause")
) -> Session {
    var session = Session(phase: .scanning)
    var scan = ScanProgress()
    scan.pause = .paused(sessionId: sessionId)
    scan.stages = ScanProgress.initialStages(mode: .video, content: false, audio: false)
    scan.timing.overallStartTime = overallStartTime
    scan.timing.scanPhaseStartTime = Date()
    scan.timing.pauseStartTime = pauseStartTime
    scan.timing.accumulatedPauseDuration = accumulatedPauseDuration
    scan.currentThroughput = currentThroughput
    scan.currentSessionId = sessionId
    scan.pauseFileURL = pauseFileURL
    // Mark first stage as active
    if !scan.stages.isEmpty {
        scan.stages[0].status = .active(current: 5, total: 10)
        scan.stages[0].currentFile = "file.mp4"
    }
    session.scan = scan
    session.lastScanConfig = defaultConfig()
    return session
}

/// Helper to check that an effects array contains a specific effect.
private func containsEffect(_ effects: [SessionEffect], _ effect: SessionEffect) -> Bool {
    effects.contains(effect)
}

/// Helper to check that an effects array does NOT contain any effect matching a predicate.
private func noEffect(_ effects: [SessionEffect], matching predicate: (SessionEffect) -> Bool) -> Bool {
    !effects.contains(where: predicate)
}

/// Create a test SessionInfo via JSON decoding (no memberwise init available).
private func makeSessionInfo(sessionId: String = "sess-1") throws -> SessionInfo {
    let data = """
    {
        "session_id": "\(sessionId)",
        "directories": ["/videos"],
        "config": {"mode": "video"},
        "completed_stages": ["scan"],
        "active_stage": "extract",
        "total_files": 10,
        "elapsed_seconds": 5.0,
        "created_at": 1711100000.0,
        "paused_at": "2024-01-01T00:00:00.000+00:00",
        "progress_percent": 50
    }
    """.data(using: .utf8)!
    return try JSONDecoder().decode(SessionInfo.self, from: data)
}

/// Create a minimal ScanEnvelope for testing.
private func makeEnvelope(pairs: [PairResult] = []) -> ScanEnvelope {
    ScanEnvelope(
        version: "1.0.0",
        generatedAt: "2025-01-01T00:00:00Z",
        args: ScanArgs(
            directories: ["/videos"],
            threshold: 50,
            content: false,
            weights: nil,
            keep: nil,
            action: "delete",
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
        content: .pairs(pairs)
    )
}

// MARK: - 1. Phase Transition Tests

@Suite("Session Reducer: Phase Transitions")
struct SessionReducerPhaseTransitionTests {

    @Test("startScan transitions .setup to .scanning")
    func startScanTransition() {
        let session = Session()
        let config = defaultConfig()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .startScan(config))
        #expect(newState.phase == .scanning)
        #expect(newState.scan != nil)
        #expect(newState.scanSequence == 1)
        #expect(newState.config == config)
        #expect(newState.lastScanConfig == config)
        #expect(newState.lastOriginalEnvelope == nil)
        #expect(containsEffect(effects, .runScan(config)))
    }

    @Test("startScan creates ScanProgress with correct stages")
    func startScanCreatesStages() {
        let session = Session()
        let config = defaultConfig(content: true, contentMethod: .phash)
        let (newState, _) = SessionReducer.reduce(state: session, action: .startScan(config))
        let stageIds = newState.scan?.stages.map(\.id)
        #expect(stageIds?.contains(.scan) == true)
        #expect(stageIds?.contains(.extract) == true)
        #expect(stageIds?.contains(.contentHash) == true)
        #expect(stageIds?.contains(.score) == true)
        #expect(stageIds?.contains(.report) == true)
    }

    @Test("startScan with audio flag includes audioFingerprint stage")
    func startScanWithAudio() {
        let session = Session()
        let config = defaultConfig(audio: true)
        let (newState, _) = SessionReducer.reduce(state: session, action: .startScan(config))
        let stageIds = newState.scan?.stages.map(\.id)
        #expect(stageIds?.contains(.audioFingerprint) == true)
    }

    @Test("startReplay transitions .setup to .scanning with replay stages")
    func startReplayTransition() {
        let session = Session()
        let url = URL(fileURLWithPath: "/tmp/replay.json")
        let config = defaultConfig()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .startReplay(url, config))
        #expect(newState.phase == .scanning)
        #expect(newState.scan != nil)
        #expect(newState.config == config)
        let stageIds = newState.scan?.stages.map(\.id)
        #expect(stageIds?.contains(.replay) == true)
        #expect(stageIds?.contains(.filter) == true)
        #expect(stageIds?.contains(.report) == true)
        #expect(containsEffect(effects, .loadReplayData(url)))
    }

    @Test("resumeSession transitions .setup to .scanning, clears lastPausedSessionId")
    func resumeSessionTransition() {
        var session = Session()
        session.lastPausedSessionId = "old-sess"
        let config = defaultConfig()
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .resumeSession("old-sess", config)
        )
        // The reducer injects the session ID into config.resume so FlagAssembler emits --resume
        var expectedConfig = config
        expectedConfig.resume = "old-sess"
        #expect(newState.phase == .scanning)
        #expect(newState.scan != nil)
        #expect(newState.config == expectedConfig)
        #expect(newState.lastPausedSessionId == nil)
        #expect(containsEffect(effects, .persistSessionId(nil)))
        #expect(containsEffect(effects, .runScan(expectedConfig)))
    }

    @Test("pauseScan transitions to pausing sub-state")
    func pauseScanTransition() {
        var session = scanningSession(currentSessionId: "sess-1")
        session.scan?.pauseFileURL = URL(fileURLWithPath: "/tmp/pause")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(newState.phase == .scanning) // Phase stays .scanning
        #expect(newState.scan?.pause == .pausing(sessionId: "sess-1"))
        #expect(containsEffect(effects, .sendPauseSignal))
        #expect(containsEffect(effects, .schedulePauseTimeout(5)))
    }

    @Test("pauseTimeoutFired transitions from .pausing to .paused")
    func pauseTimeoutTransition() {
        let session = pausingSession(sessionId: "sess-1")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .pauseTimeoutFired)
        #expect(newState.scan?.pause == .paused(sessionId: "sess-1"))
        #expect(newState.scan?.timing.pauseStartTime != nil)
        #expect(containsEffect(effects, .persistSessionId("sess-1")))
    }

    @Test("cliPauseConfirmed transitions from .pausing to .paused immediately")
    func cliPauseConfirmedTransition() {
        let session = pausingSession(sessionId: "sess-1")
        let event = PauseEvent(sessionId: "sess-1", sessionFile: "/tmp/sess", timestamp: "2024-01-01T00:00:00Z")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliPauseConfirmed(event))
        #expect(newState.scan?.pause == .paused(sessionId: "sess-1"))
        #expect(newState.scan?.timing.pauseStartTime != nil)
        #expect(newState.scan?.currentSessionId == "sess-1")
        #expect(containsEffect(effects, .cancelPauseTimeout))
        #expect(containsEffect(effects, .persistSessionId("sess-1")))
        // Must NOT re-send pause signal
        #expect(!containsEffect(effects, .sendPauseSignal))
    }

    @Test("cliPauseConfirmed is no-op when not pausing")
    func cliPauseConfirmedNoOp() {
        let session = scanningSession() // pause == .running
        let event = PauseEvent(sessionId: "sess-1", sessionFile: "/tmp/sess", timestamp: "2024-01-01T00:00:00Z")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliPauseConfirmed(event))
        #expect(newState.scan?.pause == .running)
        #expect(effects.isEmpty)
    }

    @Test("cliResumeConfirmed transitions from .paused to .running without re-sending signal")
    func cliResumeConfirmedTransition() {
        let session = pausedSession(pauseStartTime: Date(timeIntervalSinceNow: -10))
        let event = ResumeEvent(sessionId: "sess-1", timestamp: "2024-01-01T00:00:00Z")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliResumeConfirmed(event))
        #expect(newState.scan?.pause == .running)
        #expect(newState.scan?.timing.pauseStartTime == nil)
        #expect((newState.scan?.timing.accumulatedPauseDuration ?? 0) > 0)
        // Must NOT re-send resume signal or write pause commands
        #expect(!containsEffect(effects, .sendResumeSignal))
        #expect(effects.isEmpty)
    }

    @Test("cliResumeConfirmed is no-op when already running")
    func cliResumeConfirmedAlreadyRunning() {
        let session = scanningSession() // pause == .running
        let event = ResumeEvent(sessionId: "sess-1", timestamp: "2024-01-01T00:00:00Z")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliResumeConfirmed(event))
        #expect(newState.scan?.pause == .running)
        #expect(effects.isEmpty)
    }

    @Test("resumeScan from paused transitions to .running")
    func resumeScanFromPaused() {
        let session = pausedSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.pause == .running)
        #expect(containsEffect(effects, .cancelPauseTimeout))
        #expect(containsEffect(effects, .sendResumeSignal))
    }

    @Test("resumeScan from pausing transitions to .running")
    func resumeScanFromPausing() {
        let session = pausingSession()
        let (newState, _) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.pause == .running)
    }

    @Test("minimumDisplayElapsed transitions .scanning to .results with file monitor")
    func minimumDisplayElapsedTransition() {
        var session = scanningSession()
        session.scan?.isFinalizingResults = true
        // Pre-populate results so collectFilePaths has paths to collect
        let pairs = [PairResult(
            fileA: "/videos/a.mp4", fileB: "/videos/b.mp4", score: 85,
            breakdown: [:], detail: [:],
            fileAMetadata: FileMetadata(fileSize: 1_000_000),
            fileBMetadata: FileMetadata(fileSize: 900_000),
            fileAIsReference: false, fileBIsReference: false, keep: "a"
        )]
        session.results = ResultsSnapshot(envelope: makeEnvelope(pairs: pairs))

        let (newState, effects) = SessionReducer.reduce(state: session, action: .minimumDisplayElapsed)
        #expect(newState.phase == .results)
        #expect(newState.scan == nil)
        #expect(newState.lastPausedSessionId == nil)
        #expect(containsEffect(effects, .persistSessionId(nil)))
        // File monitor must start after scan completion (parity with .sessionLoaded)
        let expectedPaths = ["/videos/a.mp4", "/videos/b.mp4"]
        #expect(containsEffect(effects, .checkFileStatuses(expectedPaths)))
        #expect(containsEffect(effects, .startFileMonitor(expectedPaths)))
    }

    @Test("cliStreamFailed transitions to .error")
    func streamFailedTransition() {
        let session = scanningSession()
        let error = ErrorInfo(message: "Something went wrong", category: .unknown)
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliStreamFailed(error))
        if case .error(let info) = newState.phase {
            #expect(info == error)
        } else {
            Issue.record("Expected .error phase, got \(newState.phase)")
        }
        #expect(newState.scan == nil)
        #expect(containsEffect(effects, .cancelPauseTimeout))
    }

    @Test("cliStreamCancelled transitions to .setup")
    func streamCancelledTransition() {
        let session = scanningSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliStreamCancelled)
        #expect(newState.phase == .setup)
        #expect(newState.scan == nil)
        #expect(containsEffect(effects, .cancelPauseTimeout))
    }

    @Test("resetToSetup clears everything back to .setup")
    func resetToSetupTransition() throws {
        var session = scanningSession()
        session.config = defaultConfig()
        session.pendingReplayURL = URL(fileURLWithPath: "/tmp/replay.json")
        session.watch = WatchState()
        session.lastPausedSessionId = "sess-1"
        session.pendingSession = try makeSessionInfo(sessionId: "sess-1")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .resetToSetup)
        #expect(newState.phase == .setup)
        #expect(newState.scan == nil)
        // Config preserved when watch is active (persisted() and setWatchEnabled need it)
        #expect(newState.config != nil)
        #expect(newState.pendingReplayURL == nil)
        // Watch and results preserved across resetToSetup when watch is active
        #expect(newState.watch != nil)
        #expect(newState.results == nil)
        #expect(newState.lastPausedSessionId == nil)
        #expect(newState.pendingSession == nil)
        #expect(containsEffect(effects, .persistSessionId(nil)))
        #expect(containsEffect(effects, .cancelCLI))
        #expect(containsEffect(effects, .cancelPauseTimeout))
        // .stopWatch NOT emitted when watch is active
        #expect(!containsEffect(effects, .stopWatch))
        #expect(containsEffect(effects, .stopFileMonitor))
    }
}

// MARK: - 2. Guard Condition Tests

@Suite("Session Reducer: Guard Conditions")
struct SessionReducerGuardTests {

    @Test("startScan ignored when not in .setup")
    func startScanIgnoredWhenScanning() {
        let session = scanningSession()
        let config = defaultConfig()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .startScan(config))
        #expect(newState.phase == .scanning)
        #expect(effects.isEmpty)
    }

    @Test("startScan ignored when in .error")
    func startScanIgnoredWhenError() {
        let error = ErrorInfo(message: "Something went wrong", category: .unknown)
        let session = Session(phase: .error(error))
        let config = defaultConfig()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .startScan(config))
        #expect(newState.phase == .error(error))
        #expect(effects.isEmpty)
    }

    @Test("pauseScan ignored when isFinalizingResults")
    func pauseIgnoredWhenFinalizing() {
        var session = scanningSession()
        session.scan?.isFinalizingResults = true
        let (_, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(effects.isEmpty)
    }

    @Test("pauseScan ignored when isComplete (all stages done)")
    func pauseIgnoredWhenComplete() {
        var session = scanningSession()
        if let stages = session.scan?.stages {
            for i in stages.indices {
                session.scan?.stages[i].status = .completed(elapsed: 1.0, total: 10, extras: [:])
            }
        }
        let (_, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(effects.isEmpty)
    }

    @Test("pauseScan ignored when not in .scanning phase")
    func pauseIgnoredWhenNotScanning() {
        let session = Session()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(newState.phase == .setup)
        #expect(effects.isEmpty)
    }

    @Test("pauseScan ignored when already pausing")
    func pauseIgnoredWhenAlreadyPausing() {
        let session = pausingSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        // Should not change pause state or emit effects
        #expect(newState.scan?.pause == .pausing(sessionId: "sess-1"))
        #expect(effects.isEmpty)
    }

    @Test("cancelScan ignored when already cancelling")
    func cancelIgnoredWhenAlreadyCancelling() {
        var session = scanningSession()
        session.scan?.isCancelling = true
        let (_, effects) = SessionReducer.reduce(state: session, action: .cancelScan)
        #expect(effects.isEmpty)
    }

    @Test("resumeScan ignored when not pausing/paused")
    func resumeIgnoredWhenRunning() {
        let session = scanningSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.pause == .running)
        #expect(effects.isEmpty)
    }

    @Test("pauseTimeoutFired ignored when not pausing")
    func pauseTimeoutIgnoredWhenNotPausing() {
        let session = scanningSession()
        let (_, effects) = SessionReducer.reduce(state: session, action: .pauseTimeoutFired)
        #expect(effects.isEmpty)
    }

    @Test("minimumDisplayElapsed ignored when not finalizing")
    func minimumDisplayIgnoredWhenNotFinalizing() {
        let session = scanningSession()
        let (newState, effects) = SessionReducer.reduce(state: session, action: .minimumDisplayElapsed)
        #expect(newState.phase == .scanning)
        #expect(effects.isEmpty)
    }
}

// MARK: - 3. Effects Tests

@Suite("Session Reducer: Effects Emitted")
struct SessionReducerEffectsTests {

    @Test("startScan emits runScan effect")
    func startScanEffects() {
        let session = Session()
        let config = defaultConfig()
        let (_, effects) = SessionReducer.reduce(state: session, action: .startScan(config))
        #expect(effects == [.runScan(config)])
    }

    @Test("cancelScan emits cancelPauseTimeout and cancelCLI")
    func cancelScanEffects() {
        let session = scanningSession()
        let (_, effects) = SessionReducer.reduce(state: session, action: .cancelScan)
        #expect(containsEffect(effects, .cancelPauseTimeout))
        #expect(containsEffect(effects, .cancelCLI))
    }

    @Test("pauseScan emits sendPauseSignal and schedulePauseTimeout")
    func pauseScanEffects() {
        let session = scanningSession()
        let (_, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(containsEffect(effects, .sendPauseSignal))
        #expect(containsEffect(effects, .schedulePauseTimeout(5)))
    }

    @Test("pauseScan emits writePauseCommand when pauseFileURL is set")
    func pauseScanWithPauseFile() {
        let pauseURL = URL(fileURLWithPath: "/tmp/pause")
        var session = scanningSession()
        session.scan?.pauseFileURL = pauseURL
        let (_, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(containsEffect(effects, .writePauseCommand(pauseURL, "pause")))
    }

    @Test("pauseScan omits writePauseCommand when no pauseFileURL")
    func pauseScanNoPauseFile() {
        var session = scanningSession()
        session.scan?.pauseFileURL = nil
        let (_, effects) = SessionReducer.reduce(state: session, action: .pauseScan)
        #expect(noEffect(effects) { if case .writePauseCommand = $0 { return true }; return false })
    }

    @Test("resumeScan emits cancelPauseTimeout and sendResumeSignal")
    func resumeScanEffects() {
        let session = pausedSession()
        let (_, effects) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(containsEffect(effects, .cancelPauseTimeout))
        #expect(containsEffect(effects, .sendResumeSignal))
    }

    @Test("resumeScan emits writePauseCommand when pauseFileURL is set")
    func resumeScanWithPauseFile() {
        let pauseURL = URL(fileURLWithPath: "/tmp/pause")
        let session = pausedSession(pauseFileURL: pauseURL)
        let (_, effects) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(containsEffect(effects, .writePauseCommand(pauseURL, "resume")))
    }

    @Test("resumeScan omits writePauseCommand when no pauseFileURL")
    func resumeScanNoPauseFile() {
        let session = pausedSession(pauseFileURL: nil)
        let (_, effects) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(noEffect(effects) { if case .writePauseCommand = $0 { return true }; return false })
    }

    @Test("resetToSetup emits removePauseFile when pauseFileURL is set")
    func resetToSetupRemovesPauseFile() {
        let pauseURL = URL(fileURLWithPath: "/tmp/pause")
        var session = scanningSession()
        session.scan?.pauseFileURL = pauseURL
        let (_, effects) = SessionReducer.reduce(state: session, action: .resetToSetup)
        #expect(containsEffect(effects, .removePauseFile(pauseURL)))
    }

    @Test("cliStreamCompleted emits configureResults and cleanupTempReplayFile")
    func streamCompletedEffects() {
        var session = scanningSession()
        session.lastScanConfig?.replayPath = "/tmp/replay.json"
        let (_, effects) = SessionReducer.reduce(
            state: session, action: .cliStreamCompleted(nil, nil)
        )
        let hasConfigureResults = effects.contains { if case .configureResults = $0 { return true }; return false }
        #expect(hasConfigureResults)
        #expect(containsEffect(effects, .cleanupTempReplayFile(URL(fileURLWithPath: "/tmp/replay.json"))))
    }

    @Test("discardSession emits persistSessionId(nil)")
    func discardSessionEffects() {
        let session = Session()
        let (_, effects) = SessionReducer.reduce(state: session, action: .discardSession("sess-1"))
        #expect(containsEffect(effects, .persistSessionId(nil)))
    }
}

// MARK: - 4. CLI Event Tests

@Suite("Session Reducer: CLI Events")
struct SessionReducerCLIEventTests {

    @Test("cliProgress updates active stage progress")
    func cliProgressUpdatesStage() {
        var session = scanningSession()
        // Mark first stage (scan) as active
        session.scan?.stages[0].status = .active(current: 0, total: 100)
        let event = StageProgressEvent(
            stage: "scan", current: 42, timestamp: "2024-01-01T00:00:00Z",
            total: 100, file: "video.mp4"
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliProgress(event))
        #expect(newState.scan?.stages[0].status == .active(current: 42, total: 100))
        #expect(newState.scan?.stages[0].currentFile == "video.mp4")
    }

    @Test("cliProgress preserves existing total when event omits it")
    func cliProgressPreservesTotal() {
        var session = scanningSession()
        session.scan?.stages[0].status = .active(current: 5, total: 100)
        let event = StageProgressEvent(
            stage: "scan", current: 10, timestamp: "2024-01-01T00:00:00Z"
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliProgress(event))
        #expect(newState.scan?.stages[0].status == .active(current: 10, total: 100))
    }

    @Test("cliProgress updates throughput")
    func cliProgressUpdatesThroughput() {
        var session = scanningSession()
        session.scan?.stages[0].status = .active(current: 0, total: 100)
        let event = StageProgressEvent(
            stage: "scan", current: 10, timestamp: "2024-01-01T00:00:00Z",
            rate: 55.0, etaSeconds: 20.0
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliProgress(event))
        #expect(newState.scan?.currentThroughput == 55.0)
    }

    @Test("cliProgress updates cache stats")
    func cliProgressUpdatesCacheStats() {
        var session = scanningSession()
        session.scan?.stages[1].status = .active(current: 0, total: 50) // extract stage
        let event = StageProgressEvent(
            stage: "extract", current: 10, timestamp: "2024-01-01T00:00:00Z",
            cacheHits: 5, cacheMisses: 5
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliProgress(event))
        #expect(newState.scan?.cache.metadataCacheHits == 5)
        #expect(newState.scan?.cache.metadataCacheMisses == 5)
        #expect(newState.scan?.cache.cacheHits == 5)
        #expect(newState.scan?.cache.cacheMisses == 5)
    }

    @Test("cliStageStart marks stage active")
    func cliStageStartMarksActive() {
        let session = scanningSession()
        let event = StageStartEvent(stage: "scan", timestamp: "2024-01-01T00:00:00Z", total: 50)
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliStageStart(event))
        #expect(newState.scan?.stages[0].status == .active(current: 0, total: 50))
        #expect(newState.scan?.stageStartTimes[.scan] != nil)
    }

    @Test("cliStageStart sets fallback overallStartTime")
    func cliStageStartFallbackStartTime() {
        var session = scanningSession(overallStartTime: nil)
        session.scan?.timing.receivedSessionStart = false
        let event = StageStartEvent(stage: "scan", timestamp: "2024-01-01T00:00:00Z", total: 50)
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliStageStart(event))
        #expect(newState.scan?.timing.overallStartTime != nil)
    }

    @Test("cliStageEnd marks stage completed")
    func cliStageEndMarksCompleted() {
        var session = scanningSession()
        session.scan?.stages[0].status = .active(current: 10, total: 50)
        session.scan?.stageStartTimes[.scan] = Date()
        let event = StageEndEvent(
            stage: "scan", total: 50, elapsed: 2.5, timestamp: "2024-01-01T00:00:00Z",
            extras: ["discovered": 50]
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliStageEnd(event))
        #expect(newState.scan?.stages[0].status == .completed(elapsed: 2.5, total: 50, extras: ["discovered": 50]))
        #expect(newState.scan?.stages[0].currentFile == nil)
        #expect(newState.scan?.stageStartTimes[.scan] == nil)
    }

    @Test("cliStageEnd recomputes completedElapsed")
    func cliStageEndRecomputesElapsed() {
        var session = scanningSession()
        // Mark first stage as completed already
        session.scan?.stages[0].status = .completed(elapsed: 1.5, total: 10, extras: [:])
        // Now complete the second stage (extract)
        session.scan?.stages[1].status = .active(current: 20, total: 20)
        let event = StageEndEvent(
            stage: "extract", total: 20, elapsed: 3.0, timestamp: "2024-01-01T00:00:00Z"
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliStageEnd(event))
        // completedElapsed should be sum of all completed stages
        #expect(newState.scan?.timing.completedElapsed == 4.5)
    }

    @Test("cliStageEnd clears throughput")
    func cliStageEndClearsThroughput() {
        var session = scanningSession(currentThroughput: 50.0)
        session.scan?.stages[0].status = .active(current: 10, total: 50)
        let event = StageEndEvent(
            stage: "scan", total: 50, elapsed: 2.0, timestamp: "2024-01-01T00:00:00Z"
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliStageEnd(event))
        #expect(newState.scan?.currentThroughput == nil)
    }

    @Test("cliStreamCompleted sets isFinalizingResults")
    func cliStreamCompletedSetsFinalizingResults() {
        let session = scanningSession()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .cliStreamCompleted(nil, nil)
        )
        #expect(newState.scan?.isFinalizingResults == true)
    }

    @Test("cliSessionStart parses wall start and sets session ID")
    func cliSessionStartParsesWallStart() {
        let session = scanningSession(overallStartTime: nil)
        let event = SessionStartEvent(
            sessionId: "new-sess",
            wallStart: "2024-06-15T10:30:00Z",
            totalFiles: 0,
            stages: ["scan", "extract", "filter", "score", "report"],
            resumedFrom: nil,
            priorElapsedSeconds: nil
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliSessionStart(event))
        #expect(newState.scan?.currentSessionId == "new-sess")
        #expect(newState.scan?.timing.overallStartTime != nil)
        #expect(newState.scan?.timing.receivedSessionStart == true)
    }

    @Test("cliSessionStart preserves earliest overallStartTime")
    func cliSessionStartPreservesEarliest() {
        let earlyDate = Date(timeIntervalSince1970: 1000)
        let session = scanningSession(overallStartTime: earlyDate)
        let event = SessionStartEvent(
            sessionId: "new-sess",
            wallStart: "2034-01-01T00:00:00Z", // Much later
            totalFiles: 0,
            stages: ["scan", "extract", "score", "report"],
            resumedFrom: nil,
            priorElapsedSeconds: nil
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliSessionStart(event))
        #expect(newState.scan?.timing.overallStartTime == earlyDate)
    }

    @Test("cliSessionStart handles resumed scans")
    func cliSessionStartHandlesResumed() {
        let session = scanningSession()
        let event = SessionStartEvent(
            sessionId: "new-sess",
            wallStart: "2024-06-15T10:30:00Z",
            totalFiles: 0,
            stages: ["scan", "extract", "score", "report"],
            resumedFrom: "old-sess",
            priorElapsedSeconds: 42.5
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliSessionStart(event))
        #expect(newState.scan?.timing.isResumed == true)
        #expect(newState.scan?.timing.resumedBaseline == 42.5)
    }

    @Test("cliSessionStart rebuilds stages from CLI list")
    func cliSessionStartRebuildsStages() {
        let session = scanningSession()
        let event = SessionStartEvent(
            sessionId: "new-sess",
            wallStart: "2024-06-15T10:30:00Z",
            totalFiles: 0,
            stages: ["scan", "extract", "content_hash", "score", "report"],
            resumedFrom: nil,
            priorElapsedSeconds: nil
        )
        let (newState, _) = SessionReducer.reduce(state: session, action: .cliSessionStart(event))
        let stageIds = newState.scan?.stages.map(\.id)
        #expect(stageIds == [.scan, .extract, .contentHash, .score, .report])
    }

    @Test("cliSessionStart patches session ID in pause state")
    func cliSessionStartPatchesPauseSessionId() {
        let session = pausingSession(sessionId: "old-sess")
        let event = SessionStartEvent(
            sessionId: "new-sess",
            wallStart: "2024-06-15T10:30:00Z",
            totalFiles: 0,
            stages: ["scan", "extract", "score", "report"],
            resumedFrom: nil,
            priorElapsedSeconds: nil
        )
        let (newState, effects) = SessionReducer.reduce(state: session, action: .cliSessionStart(event))
        #expect(newState.scan?.pause == .pausing(sessionId: "new-sess"))
        #expect(containsEffect(effects, .persistSessionId("new-sess")))
    }

    @Test("cliStageStart for unknown stage is ignored")
    func cliStageStartUnknownStage() {
        let session = scanningSession()
        let event = StageStartEvent(stage: "unknown_stage", timestamp: "2024-01-01T00:00:00Z", total: 10)
        let (_, effects) = SessionReducer.reduce(state: session, action: .cliStageStart(event))
        #expect(effects.isEmpty)
    }

    @Test("cliProgress for unknown stage updates cache stats only")
    func cliProgressUnknownStage() {
        let session = scanningSession()
        let event = StageProgressEvent(
            stage: "unknown_stage", current: 5, timestamp: "2024-01-01T00:00:00Z",
            cacheHits: 10
        )
        let (_, effects) = SessionReducer.reduce(state: session, action: .cliProgress(event))
        // Unknown stage: cache stats not updated (no matching case)
        #expect(effects.isEmpty)
    }

    @Test("cliStreamFailed cleans up pause file")
    func cliStreamFailedCleansPauseFile() {
        let pauseURL = URL(fileURLWithPath: "/tmp/pause")
        var session = scanningSession()
        session.scan?.pauseFileURL = pauseURL
        let error = ErrorInfo(message: "Something went wrong", category: .unknown)
        let (_, effects) = SessionReducer.reduce(state: session, action: .cliStreamFailed(error))
        #expect(containsEffect(effects, .removePauseFile(pauseURL)))
    }

    @Test("cliStreamCancelled cleans up pause file")
    func cliStreamCancelledCleansPauseFile() {
        let pauseURL = URL(fileURLWithPath: "/tmp/pause")
        var session = scanningSession()
        session.scan?.pauseFileURL = pauseURL
        let (_, effects) = SessionReducer.reduce(state: session, action: .cliStreamCancelled)
        #expect(containsEffect(effects, .removePauseFile(pauseURL)))
    }
}

// MARK: - 5. Pause/Resume Preservation Tests

@Suite("Session Reducer: Pause/Resume State Preservation")
struct SessionReducerPausePreservationTests {

    @Test("Resume does NOT clear overallStartTime")
    func resumePreservesOverallStartTime() {
        let startTime = Date(timeIntervalSince1970: 1000)
        let session = pausedSession(overallStartTime: startTime)
        let (newState, _) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.timing.overallStartTime == startTime)
    }

    @Test("Resume does NOT clear currentThroughput")
    func resumePreservesCurrentThroughput() {
        let session = pausedSession(currentThroughput: 42.5)
        let (newState, _) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.currentThroughput == 42.5)
    }

    @Test("Resume does NOT clear stages")
    func resumePreservesStages() {
        var session = pausedSession()
        session.scan?.stages[0].status = .active(current: 7, total: 20)
        session.scan?.stages[0].currentFile = "important.mp4"
        let originalStages = session.scan?.stages

        let (newState, _) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.stages == originalStages)
    }

    @Test("Resume accumulates pause duration")
    func resumeAccumulatesPauseDuration() {
        let pauseStart = Date(timeIntervalSince1970: 1000)
        let session = pausedSession(pauseStartTime: pauseStart, accumulatedPauseDuration: 5.0)
        let (newState, _) = SessionReducer.reduce(state: session, action: .resumeScan)
        let accumulated = newState.scan?.timing.accumulatedPauseDuration ?? 0
        #expect(accumulated >= 5.0)
    }

    @Test("Resume clears pauseStartTime")
    func resumeClearsPauseStartTime() {
        let session = pausedSession(pauseStartTime: Date())
        let (newState, _) = SessionReducer.reduce(state: session, action: .resumeScan)
        #expect(newState.scan?.timing.pauseStartTime == nil)
    }
}

// MARK: - 6. resultsReady Tests

@Suite("Session Reducer: Results Ready")
struct SessionReducerResultsReadyTests {

    @Test("resultsReady sets results snapshot and saves session")
    func resultsReadySetsSnapshot() {
        var session = scanningSession()
        session.scan?.isFinalizingResults = true
        let envelope = makeEnvelope()
        let snapshot = ResultsSnapshot(envelope: envelope)
        let displayConfig = ResultsDisplayConfig(activeAction: .trash, moveDestination: nil, rawEnvelopeData: nil)
        let (newState, effects) = SessionReducer.reduce(state: session, action: .resultsReady(snapshot, displayConfig))
        #expect(newState.results?.envelope == envelope)
        // Should emit scheduleMinimumDisplay
        let hasSchedule = effects.contains { if case .scheduleMinimumDisplay = $0 { return true }; return false }
        #expect(hasSchedule)
        // Should emit saveSession on scan completion (spec: save trigger table)
        #expect(containsEffect(effects, .saveSession))
    }
}

// MARK: - 7. discardSession Tests

@Suite("Session Reducer: Discard Session")
struct SessionReducerDiscardSessionTests {

    @Test("discardSession clears session references")
    func discardClearsReferences() throws {
        var session = Session()
        session.lastPausedSessionId = "sess-1"
        session.pendingSession = try makeSessionInfo(sessionId: "sess-1")
        let (newState, effects) = SessionReducer.reduce(state: session, action: .discardSession("sess-1"))
        #expect(newState.lastPausedSessionId == nil)
        #expect(newState.pendingSession == nil)
        #expect(containsEffect(effects, .persistSessionId(nil)))
    }
}

// MARK: - 8. Scan Sequence Increment Tests

@Suite("Session Reducer: Scan Sequence")
struct SessionReducerScanSequenceTests {

    @Test("scanSequence increments on startScan")
    func scanSequenceIncrementsOnStart() {
        let session = Session()
        let (newState, _) = SessionReducer.reduce(state: session, action: .startScan(defaultConfig()))
        #expect(newState.scanSequence == 1)
    }

    @Test("scanSequence increments on startReplay")
    func scanSequenceIncrementsOnReplay() {
        let session = Session()
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .startReplay(URL(fileURLWithPath: "/tmp/replay.json"), defaultConfig())
        )
        #expect(newState.scanSequence == 1)
    }

    @Test("scanSequence increments on resumeSession")
    func scanSequenceIncrementsOnResume() {
        let session = Session()
        let (newState, _) = SessionReducer.reduce(
            state: session,
            action: .resumeSession("sess-1", defaultConfig())
        )
        #expect(newState.scanSequence == 1)
    }

    @Test("scanSequence wraps on overflow")
    func scanSequenceWraps() {
        var session = Session()
        session.scanSequence = UInt.max
        let (newState, _) = SessionReducer.reduce(state: session, action: .startScan(defaultConfig()))
        #expect(newState.scanSequence == 0) // Wraps around
    }
}
