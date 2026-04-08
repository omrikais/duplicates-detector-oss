import Foundation

/// Pure reducer for all session state transitions.
///
/// Every state mutation is driven through `reduce(state:action:)` which returns
/// the updated state plus a list of side-effect descriptors for the store to execute.
/// This function is intentionally **not** `@MainActor` — it can be called from any context.
enum SessionReducer {

    /// Process a single action against the current state.
    /// Returns the new state and any effects to execute.
    static func reduce(
        state: Session,
        action: SessionAction
    ) -> (Session, [SessionEffect]) {
        switch action {
        // Scan lifecycle actions
        case .startScan, .startPhotosScan, .startReplay, .resumeSession, .discardSession,
             .cliSessionStart, .cliStageStart, .cliProgress, .cliStageEnd,
             .cliStreamCompleted, .cliStreamFailed, .cliStreamCancelled,
             .resultsReady, .photosAuthorizationLimited, .photosAuthRevoked,
             .cancelScan, .pauseScan, .resumeScan,
             .cliPauseConfirmed, .cliResumeConfirmed,
             .pauseTimeoutFired, .minimumDisplayElapsed, .resetToSetup,
             .setPauseFile, .configureReplay, .updateSynthesizedViews,
             .setPausedSession:
            return reduceScanLifecycle(state: state, action: action)

        // Results & review desk
        case .selectPair, .keepFile, .skipPair, .previousPair,
             .ignorePair, .unignorePair, .clearIgnoredPairs,
             ._rollbackIgnore, ._rollbackUnignore, ._rollbackClearIgnored,
             .undoResolution, .toggleViewMode, .setViewMode,
             .setSearchText, .setSortOrder, .setActiveAction, .setMoveDestination,
             .toggleInsights, .setDirectoryFilter,
             .toggleSelectMode, .selectAll, .deselectAll,
             .setSelectedPairs, .setSelectedGroups,
             .togglePairSelection, .toggleGroupSelection, .clearPairError,
             .startBulk, .bulkStarted, .cancelBulk, .bulkItemCompleted, .bulkFinished,
             .fileActionCompleted, .fileActionFailed:
            return reduceResultsAction(state: state, action: action)

        // Watch mode & filesystem liveness
        case .setWatchEnabled, .watchAlertReceived, .watchFileChanged,
             .watchFileBatchChanged, .fileStatusChecked:
            return reduceWatchAction(state: state, action: action)

        // External signals, history, navigation
        case .openReplayFile, .openWatchNotification, .activateWindow, .menuCommand,
             .restoreSession, .sessionLoaded, .deleteHistorySession:
            return reduceExternalSignal(state: state, action: action)

        #if DEBUG
        case ._injectPreviewState(let scan, let config):
            var state = state
            state.scan = scan
            state.phase = .scanning
            state.lastScanConfig = config
            return (state, [])
        #endif
        }
    }

    // MARK: - Scan Lifecycle

    private static func reduceScanLifecycle(
        state: Session,
        action: SessionAction
    ) -> (Session, [SessionEffect]) {
        var state = state
        var effects: [SessionEffect] = []

        switch action {

        // MARK: - User Intent

        case .startScan(let config):
            guard state.phase == .setup || state.phase == .results else { return (state, []) }
            // Tear down any lingering watch session from the previous scan.
            // Keep state.results — needed for notification routing until new
            // results arrive via .resultsReady. Guard in .watchAlertReceived
            // prevents stale engine events from mutating these preserved results.
            let hadWatch = state.watch != nil
            if hadWatch {
                state.watch = nil
            }
            // When launching from results (dry-run rerun or refine), reset
            // scan state and stop the file monitor so the new scan starts clean.
            let fromResults = state.phase == .results
            if fromResults {
                resetScanState(&state)
            }
            state.id = UUID()
            state.scanSequence &+= 1
            state.config = config
            state.lastScanConfig = config
            // Preserve the original envelope during refine (replay from results)
            // so that loosening settings later can restore filtered pairs.
            // Fresh scans and dry-run reruns clear it.
            if config.replayPath == nil {
                state.lastOriginalEnvelope = nil
            }
            state.metadata = SessionMetadata(
                directories: config.directories,
                sourceLabel: config.directories.map { ($0 as NSString).lastPathComponent }.joined(separator: ", "),
                mode: config.mode
            )
            state.scan = ScanProgress()
            state.scan?.stages = ScanProgress.initialStages(
                mode: config.mode, content: config.content, audio: config.audio,
                embedThumbnails: config.embedThumbnails, contentMethod: config.contentMethod ?? .phash,
                hasFilters: config.hasFilters
            )
            state.phase = .scanning
            state.scan?.timing.scanPhaseStartTime = Date()
            effects = [.runScan(config)]
            if hadWatch {
                effects.append(contentsOf: [.stopWatch, .stopFileMonitor])
            } else if fromResults {
                effects.append(.stopFileMonitor)
            }

        case .startPhotosScan(let scope, let config):
            guard state.phase == .setup || state.phase == .results else { return (state, []) }
            // Tear down any lingering watch session from the previous scan.
            let hadWatch = state.watch != nil
            if hadWatch {
                state.watch = nil
            }
            let fromResults = state.phase == .results
            if fromResults {
                resetScanState(&state)
            }
            state.id = UUID()
            state.scanSequence &+= 1
            state.config = config
            state.lastScanConfig = config
            state.lastOriginalEnvelope = nil
            state.metadata = SessionMetadata(
                directories: [],
                sourceLabel: SessionMetadata.photosLibraryLabel,
                mode: .auto
            )
            state.scan = ScanProgress()
            state.scan?.stages = [
                ScanProgress.StageState(id: .authorize, displayName: "Authorizing"),
                ScanProgress.StageState(id: .extract, displayName: "Extracting metadata"),
                ScanProgress.StageState(id: .filter, displayName: "Filtering"),
                ScanProgress.StageState(id: .score, displayName: "Scoring pairs"),
                ScanProgress.StageState(id: .report, displayName: "Building report"),
            ]
            state.phase = .scanning
            state.scan?.timing.scanPhaseStartTime = Date()
            effects = [.runPhotosScan(scope, config)]
            if hadWatch {
                effects.append(contentsOf: [.stopWatch, .stopFileMonitor])
            } else if fromResults {
                effects.append(.stopFileMonitor)
            }

        case .startReplay(let url, let setupConfig):
            guard state.phase == .setup else { return (state, []) }
            // Tear down any lingering watch session — keep results for notification routing.
            let hadWatch = state.watch != nil
            if hadWatch {
                state.watch = nil
            }
            state.id = UUID()
            state.scanSequence &+= 1
            state.config = setupConfig
            state.phase = .scanning
            state.scan = ScanProgress()
            state.scan?.timing.scanPhaseStartTime = Date()
            state.scan?.stages = ScanProgress.replayStages(
                embedThumbnails: setupConfig.embedThumbnails
            )
            state.lastScanConfig = setupConfig
            state.metadata = SessionMetadata(
                directories: setupConfig.directories,
                sourceLabel: setupConfig.directories.map { ($0 as NSString).lastPathComponent }.joined(separator: ", "),
                mode: setupConfig.mode
            )
            effects = [.loadReplayData(url)]
            if hadWatch {
                effects.append(contentsOf: [.stopWatch, .stopFileMonitor])
            }

        case .resumeSession(let sessionId, let formConfig):
            guard state.phase == .setup else { return (state, []) }
            // Build config from the paused session's full config snapshot so
            // state.config/lastScanConfig match the CLI's restored settings.
            // Fall back to the setup form if pendingSession is unavailable.
            var config: SessionConfig
            if let ps = state.pendingSession {
                config = SessionConfig.fromPausedSession(ps)
            } else {
                config = formConfig
            }
            config.resume = sessionId
            // Presentation-only overrides always come from the current form
            config.verbose = formConfig.verbose
            config.cacheStats = formConfig.cacheStats
            config.pauseFile = formConfig.pauseFile
            state.id = UUID()
            state.scanSequence &+= 1
            state.config = config
            state.lastScanConfig = config
            // Clear stale results from a prior scan so teardown() doesn't
            // persist them under the new session UUID during the resume.
            state.results = nil
            state.scan = ScanProgress()
            state.scan?.stages = ScanProgress.initialStages(
                mode: config.mode, content: config.content, audio: config.audio,
                embedThumbnails: config.embedThumbnails, contentMethod: config.contentMethod ?? .phash,
                hasFilters: config.hasFilters
            )
            state.phase = .scanning
            state.scan?.timing.scanPhaseStartTime = Date()
            state.lastPausedSessionId = nil
            state.metadata = SessionMetadata(
                directories: config.directories,
                sourceLabel: config.directories.map { ($0 as NSString).lastPathComponent }.joined(separator: ", "),
                mode: config.mode
            )
            effects = [.persistSessionId(nil), .runScan(config)]

        case .discardSession(let sessionId):
            state.lastPausedSessionId = nil
            state.pendingSession = nil
            effects = [.persistSessionId(nil), .deleteCliSession(sessionId)]

        case .cancelScan:
            guard state.scan?.isCancelling != true else { return (state, []) }
            state.scan?.isCancelling = true
            effects = [.cancelPauseTimeout, .cancelCLI]

        case .pauseScan:
            guard state.phase == .scanning,
                  let scan = state.scan,
                  scan.pause == .running,
                  !scan.isFinalizingResults,
                  !scan.isComplete else { return (state, []) }
            let currentSessionId = state.scan?.currentSessionId
            state.scan?.pause = .pausing(sessionId: currentSessionId)
            effects = [.sendPauseSignal]
            if let url = state.scan?.pauseFileURL {
                effects.append(.writePauseCommand(url, "pause"))
            }
            effects.append(.schedulePauseTimeout(5))

        case .resumeScan:
            guard let scan = state.scan,
                  isPausing(scan.pause) || isPaused(scan.pause) else {
                return (state, [])
            }
            // CRITICAL: Accumulate pause duration WITHOUT clearing any progress state.
            if let pauseStart = state.scan?.timing.pauseStartTime {
                state.scan?.timing.accumulatedPauseDuration += Date().timeIntervalSince(pauseStart)
            }
            state.scan?.timing.pauseStartTime = nil
            state.scan?.pause = .running
            // Does NOT touch overallStartTime, currentThroughput, or stages.
            effects = [.cancelPauseTimeout, .sendResumeSignal]
            if let url = state.scan?.pauseFileURL {
                effects.append(.writePauseCommand(url, "resume"))
            }

        // MARK: - CLI Events (pause/resume confirmations)

        case .cliPauseConfirmed(let e):
            // CLI confirmed the pause. Transition .pausing → .paused immediately
            // (rather than waiting for the 5-second timeout). No-op if already
            // paused or if a different lifecycle phase.
            guard isPausing(state.scan?.pause ?? .running) else { return (state, []) }
            state.scan?.pause = .paused(sessionId: e.sessionId)
            state.scan?.timing.pauseStartTime = Date()
            state.scan?.currentSessionId = e.sessionId
            effects = [.cancelPauseTimeout, .persistSessionId(e.sessionId)]

        case .cliResumeConfirmed:
            // CLI confirmed the resume. If the user already initiated resumeScan,
            // state is already .running — this is a safe no-op. If an external
            // agent resumed the CLI (SIGUSR1/pause-file), transition to .running
            // without re-sending signals.
            guard isPaused(state.scan?.pause ?? .running) else { return (state, []) }
            if let pauseStart = state.scan?.timing.pauseStartTime {
                state.scan?.timing.accumulatedPauseDuration += Date().timeIntervalSince(pauseStart)
            }
            state.scan?.timing.pauseStartTime = nil
            state.scan?.pause = .running

        // MARK: - CLI Events

        case .cliSessionStart(let e):
            // Parse wallStart into a Date, preserving the earliest timestamp
            // to keep the timer monotonic when stage_start arrives before session_start.
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let parsedDate = formatter.date(from: e.wallStart)
                ?? ISO8601DateFormatter().date(from: e.wallStart)
            if let date = parsedDate {
                if let existing = state.scan?.timing.overallStartTime {
                    state.scan?.timing.overallStartTime = min(existing, date)
                } else {
                    state.scan?.timing.overallStartTime = date
                }
            }
            state.scan?.timing.receivedSessionStart = true

            // Handle resumed scans
            if e.resumedFrom != nil {
                state.scan?.timing.isResumed = true
                state.scan?.timing.resumedBaseline = e.priorElapsedSeconds ?? 0
            }

            // Rebuild stages from CLI list, preserving existing status
            if state.scan != nil {
                rebuildStages(&state, from: e.stages)
            }

            state.scan?.currentSessionId = e.sessionId

            // Session ID patching for pause states
            if case .pausing(let sid) = state.scan?.pause, sid != e.sessionId {
                state.scan?.pause = .pausing(sessionId: e.sessionId)
                effects.append(.persistSessionId(e.sessionId))
            } else if case .paused(let sid) = state.scan?.pause, sid != e.sessionId {
                state.scan?.pause = .paused(sessionId: e.sessionId)
                effects.append(.persistSessionId(e.sessionId))
            }

        case .cliStageStart(let e):
            // Fallback overallStartTime when no session_start received
            if state.scan?.timing.overallStartTime == nil,
               state.scan?.timing.receivedSessionStart != true {
                state.scan?.timing.overallStartTime = Date()
            }
            guard let pipelineStage = PipelineStage(rawValue: e.stage),
                  let idx = state.scan?.stages.firstIndex(where: { $0.id == pipelineStage }) else {
                return (state, [])
            }
            state.scan?.stages[idx].status = .active(current: 0, total: e.total)
            state.scan?.stages[idx].currentFile = nil
            state.scan?.stageStartTimes[pipelineStage] = Date()

        case .cliProgress(let e):
            guard let pipelineStage = PipelineStage(rawValue: e.stage),
                  let idx = state.scan?.stages.firstIndex(where: { $0.id == pipelineStage }) else {
                // Unknown stage: update cache stats if applicable, otherwise ignore
                if state.scan != nil {
                    updateCacheStats(&state, stage: e.stage, hits: e.cacheHits, misses: e.cacheMisses)
                }
                return (state, [])
            }
            // Update current/total, preserving known total if event omits it
            let existingTotal: Int? = {
                if case .active(_, let t) = state.scan?.stages[idx].status { return t }
                return nil
            }()
            let newTotal = e.total ?? existingTotal
            state.scan?.stages[idx].status = .active(current: e.current, total: newTotal)
            state.scan?.stages[idx].currentFile = e.file

            // Update throughput
            if let rate = e.rate {
                state.scan?.currentThroughput = rate
            }

            // Update per-stage cache stats
            updateCacheStats(&state, stage: e.stage, hits: e.cacheHits, misses: e.cacheMisses)

        case .cliStageEnd(let e):
            guard let pipelineStage = PipelineStage(rawValue: e.stage),
                  let idx = state.scan?.stages.firstIndex(where: { $0.id == pipelineStage }) else {
                if state.scan != nil {
                    updateCacheStats(&state, stage: e.stage, hits: e.cacheHits, misses: e.cacheMisses)
                }
                return (state, [])
            }
            state.scan?.stages[idx].status = .completed(elapsed: e.elapsed, total: e.total, extras: e.extras)
            state.scan?.stages[idx].currentFile = nil
            state.scan?.stageStartTimes.removeValue(forKey: pipelineStage)

            // Recompute completedElapsed from all completed stages
            if let stages = state.scan?.stages {
                state.scan?.timing.completedElapsed = stages.reduce(0.0) { sum, stage in
                    if case .completed(let elapsed, _, _) = stage.status { return sum + elapsed }
                    return sum
                }
            }

            // Update cache stats from stage end
            updateCacheStats(&state, stage: e.stage, hits: e.cacheHits, misses: e.cacheMisses)

            // Clear per-event transient state
            state.scan?.currentThroughput = nil

        case .cliStreamCompleted(let envelope, let data):
            // Guard against a late completion arriving after scan state was
            // cleared (e.g. resetToSetup while the CLI stream was still open).
            guard state.scan != nil else { return (state, []) }
            state.scan?.isFinalizingResults = true
            let config = state.lastScanConfig ?? SessionConfig()
            effects.append(.configureResults(envelope, data, config, state.lastOriginalEnvelope))
            // Schedule temp replay file cleanup
            if let replayPath = state.lastScanConfig?.replayPath {
                effects.append(.cleanupTempReplayFile(URL(fileURLWithPath: replayPath)))
            }

        case .cliStreamFailed(let error):
            let pauseURL = state.scan?.pauseFileURL
            resetScanState(&state)
            // Clear stale results from a previous scan so teardown() doesn't
            // persist them under the current (new) session UUID.
            state.results = nil
            state.phase = .error(error)
            effects.append(.cancelPauseTimeout)
            if let url = pauseURL {
                effects.append(.removePauseFile(url))
            }

        case .photosAuthorizationLimited:
            state.scan?.photosLimitedWarning = true

        case .photosAuthRevoked:
            guard state.phase == .scanning else { return (state, []) }
            state.phase = .error(ErrorInfo.classify(PhotoKitError.authorizationDenied))
            state.scan = nil
            effects.append(.cancelCLI)

        case .cliStreamCancelled:
            let pauseURL = state.scan?.pauseFileURL
            resetScanState(&state)
            // Clear stale results — same rationale as cliStreamFailed above.
            state.results = nil
            state.phase = .setup
            effects.append(.cancelPauseTimeout)
            if let url = pauseURL {
                effects.append(.removePauseFile(url))
            }

        // MARK: - Internal

        case .resultsReady(let snapshot, let displayConfig):
            state.results = snapshot
            state.metadata.pairCount = snapshot.envelope.stats.pairsAboveThreshold
            state.metadata.fileCount = snapshot.envelope.stats.filesScanned
            state.metadata.filesScanned = snapshot.envelope.stats.filesScanned
            state.metadata.spaceRecoverable = snapshot.envelope.stats.spaceRecoverable
            state.metadata.groupsCount = snapshot.envelope.stats.groupsCount
            // Apply display config atomically with results — no direct store mutations.
            state.display = DisplayState.initial(for: snapshot.envelope.content)
            state.display.activeAction = displayConfig.activeAction
            state.display.moveDestination = displayConfig.moveDestination
            if let rawData = displayConfig.rawEnvelopeData, state.lastOriginalEnvelope == nil {
                state.lastOriginalEnvelope = rawData
            }
            let startTime = state.scan?.timing.scanPhaseStartTime ?? Date()
            effects.append(.scheduleMinimumDisplay(startTime))
            effects.append(.saveSession)

        case .pauseTimeoutFired:
            guard case .pausing(let sessionId) = state.scan?.pause else { return (state, []) }
            state.scan?.pause = .paused(sessionId: sessionId)
            state.scan?.timing.pauseStartTime = Date()
            effects.append(.persistSessionId(sessionId))

        case .minimumDisplayElapsed:
            guard state.scan?.isFinalizingResults == true else { return (state, []) }
            state.phase = .results
            state.scan = nil
            state.lastPausedSessionId = nil
            effects.append(.persistSessionId(nil))
            let paths = collectFilePaths(from: state.results)
            effects.append(.checkFileStatuses(paths))
            effects.append(.startFileMonitor(paths))

        case .resetToSetup:
            let pauseURL = state.scan?.pauseFileURL
            let keepWatch = state.watch != nil
            resetScanState(&state)
            state.phase = .setup
            state.pendingReplayURL = nil
            state.lastPausedSessionId = nil
            state.pendingSession = nil
            // Preserve watch, results, AND config when watch is active — watch
            // alerts need the results snapshot to add new pairs, notification
            // taps need results to navigate back, and persisted() / setWatchEnabled
            // read state.config for directories/threshold/weights.
            if !keepWatch {
                state.config = nil
                state.watch = nil
                state.results = nil
            }
            effects = [.persistSessionId(nil), .cancelCLI, .cancelPauseTimeout, .stopFileMonitor]
            if !keepWatch {
                effects.append(.stopWatch)
            }
            if let url = pauseURL {
                effects.append(.removePauseFile(url))
            }

        // MARK: - Internal State Patching

        case .setPauseFile(let url):
            state.scan?.pauseFileURL = url

        case .configureReplay(let config, let data):
            state.config = config
            state.lastScanConfig = config
            if let data {
                state.lastOriginalEnvelope = data
            }

        case .updateSynthesizedViews(let groups, let pairs):
            if var groups {
                state.results?.assignStableIDs(to: &groups)
                state.results?.synthesizedGroups = groups
                state.results?.incrementFilterGeneration()
            }
            if let pairs {
                var mergedPairs = pairs
                // Append accumulated watch pairs — do NOT clear the buffer.
                // pendingWatchPairs is the persistent record of group-mode watch
                // hits; clearing it here would race with the debounced save and
                // cause watch hits to be lost on the next persist/restore.
                if let pending = state.results?.pendingWatchPairs, !pending.isEmpty {
                    mergedPairs.append(contentsOf: pending)
                }
                state.results?.synthesizedPairs = mergedPairs
                state.results?.incrementFilterGeneration()
            }

        case .setPausedSession(let sessionId, let info):
            state.lastPausedSessionId = sessionId
            state.pendingSession = info

        default:
            break // Unreachable — routed by top-level reduce()
        }

        return (state, effects)
    }

    // MARK: - Private Helpers

    /// Check if pause state is in the paused case (any session ID).
    private static func isPaused(_ pause: PauseState) -> Bool {
        if case .paused = pause { return true }
        return false
    }

    /// Check if pause state is in the pausing case (any session ID).
    private static func isPausing(_ pause: PauseState) -> Bool {
        if case .pausing = pause { return true }
        return false
    }

    /// Reset all scan-related transient state fields to their initial values.
    private static func resetScanState(_ state: inout Session) {
        state.scan = nil
    }

    /// Rebuild the stage list from CLI-reported stage names, preserving status
    /// of any stages that already had non-pending status.
    private static func rebuildStages(
        _ state: inout Session,
        from stageNames: [String]
    ) {
        let displayNames: [String: String] = [
            "scan": "Scanning files",
            "extract": "Extracting metadata",
            "filter": "Filtering",
            "content_hash": "Hashing content",
            "ssim_extract": "Extracting SSIM frames",
            "audio_fingerprint": "Audio fingerprinting",
            "score": "Scoring pairs",
            "thumbnail": "Generating thumbnails",
            "report": "Building report",
            "replay": "Loading replay",
        ]

        var newStages: [ScanProgress.StageState] = []
        for stageName in stageNames {
            if let pipelineStage = PipelineStage(rawValue: stageName) {
                let displayName = displayNames[stageName] ?? stageName.capitalized
                newStages.append(
                    ScanProgress.StageState(id: pipelineStage, displayName: displayName)
                )
            }
        }

        if !newStages.isEmpty {
            // Preserve status of already-started stages
            if let existingStages = state.scan?.stages {
                for (i, newStage) in newStages.enumerated() {
                    if let existingIdx = existingStages.firstIndex(where: { $0.id == newStage.id }) {
                        newStages[i].status = existingStages[existingIdx].status
                        newStages[i].currentFile = existingStages[existingIdx].currentFile
                    }
                }
            }
            state.scan?.stages = newStages
        }
    }

    /// Update per-stage and aggregate cache statistics.
    private static func updateCacheStats(
        _ state: inout Session,
        stage: String,
        hits: Int?,
        misses: Int?
    ) {
        guard hits != nil || misses != nil else { return }

        if let hits {
            switch stage {
            case "extract": state.scan?.cache.metadataCacheHits = hits
            case "content_hash": state.scan?.cache.contentCacheHits = hits
            case "audio_fingerprint": state.scan?.cache.audioCacheHits = hits
            case "score": state.scan?.cache.scoreCacheHits = hits
            default: break
            }
        }
        if let misses {
            switch stage {
            case "extract": state.scan?.cache.metadataCacheMisses = misses
            case "content_hash": state.scan?.cache.contentCacheMisses = misses
            case "audio_fingerprint": state.scan?.cache.audioCacheMisses = misses
            case "score": state.scan?.cache.scoreCacheMisses = misses
            default: break
            }
        }

        // Recompute headline totals
        if let cache = state.scan?.cache {
            state.scan?.cache.cacheHits = cache.metadataCacheHits + cache.contentCacheHits
                + cache.audioCacheHits + cache.scoreCacheHits
            state.scan?.cache.cacheMisses = cache.metadataCacheMisses + cache.contentCacheMisses
                + cache.audioCacheMisses + cache.scoreCacheMisses
        }
    }

    // MARK: - Results & Review Desk

    private static func reduceResultsAction(
        state: Session,
        action: SessionAction
    ) -> (Session, [SessionEffect]) {
        // Guard effect-completion actions that mutate domain state — they must
        // not apply after resetToSetup has discarded results.
        switch action {
        case .fileActionCompleted, .fileActionFailed, .bulkItemCompleted, .bulkFinished,
             .keepFile, .ignorePair, .unignorePair, .clearIgnoredPairs, .undoResolution,
             .startBulk, .cancelBulk:
            guard state.phase == .results else { return (state, []) }
        default: break
        }

        var state = state
        var effects: [SessionEffect] = []

        switch action {

        // MARK: Display State

        case .selectPair(let id):
            state.display.selectedPairID = id

        case .setSearchText(let text):
            state.display.searchText = text
            state.results?.incrementFilterGeneration()

        case .setSortOrder(let order):
            state.display.sortOrder = order
            state.results?.incrementFilterGeneration()

        case .setActiveAction(let actionType):
            state.display.activeAction = actionType

        case .setMoveDestination(let url):
            state.display.moveDestination = url

        case .toggleInsights:
            state.display.showInsights.toggle()

        case .setDirectoryFilter(let path):
            state.display.directoryFilter = path
            state.results?.incrementFilterGeneration()

        case .toggleSelectMode:
            state.display.isSelectMode.toggle()
            if !state.display.isSelectMode {
                state.display.selectedForAction = []
                state.display.selectedGroupsForAction = []
            }

        case .selectAll:
            break // Intercepted by store — it computes the selection set and returns .setSelectedPairs/.setSelectedGroups

        case .setSelectedPairs(let ids):
            state.display.selectedForAction = ids

        case .setSelectedGroups(let ids):
            state.display.selectedGroupsForAction = ids

        case .deselectAll:
            state.display.selectedForAction = []
            state.display.selectedGroupsForAction = []

        case .togglePairSelection(let id):
            if state.display.selectedForAction.contains(id) {
                state.display.selectedForAction.remove(id)
            } else {
                state.display.selectedForAction.insert(id)
            }

        case .toggleGroupSelection(let id):
            if state.display.selectedGroupsForAction.contains(id) {
                state.display.selectedGroupsForAction.remove(id)
            } else {
                state.display.selectedGroupsForAction.insert(id)
            }

        case .clearPairError(let pairID):
            state.results?.pairErrors.removeValue(forKey: pairID)

        // MARK: View Mode Toggle

        case .toggleViewMode:
            let target: DisplayState.ViewMode = state.display.viewMode == .pairs ? .groups : .pairs
            if let fx = applyViewModeChange(to: target, state: &state) {
                effects = fx
            }

        case .setViewMode(let mode):
            if let fx = applyViewModeChange(to: mode, state: &state) {
                effects = fx
            }

        // MARK: Review Desk Actions

        case .keepFile(let pairID, let pathToAct, let actionType):
            guard state.results?.isDryRun != true else {
                state.results?.pairErrors[pairID] = ActionError(
                    message: "Cannot \(actionType.rawValue) files in dry-run mode"
                )
                return (state, [])
            }
            guard state.results?.bulkProgress == nil else {
                state.results?.pairErrors[pairID] = ActionError(
                    message: "Cannot \(actionType.rawValue) files while a bulk operation is in progress"
                )
                return (state, [])
            }
            effects = [.performFileAction(actionType, pathToAct, pairID)]

        case .skipPair:
            break // Navigation handled by store

        case .previousPair:
            break // Navigation handled by store

        case .ignorePair(let id):
            guard state.results?.isDryRun != true else {
                state.results?.pairErrors[id] = ActionError(
                    message: "Cannot ignore pairs in dry-run mode"
                )
                return (state, [])
            }
            state.results?.ignoredPairs.insert(id)
            state.results?.incrementFilterGeneration()
            let ignoreURL = state.lastScanConfig?.ignoreFile.map { URL(fileURLWithPath: $0) }
            effects = [.addToIgnoreList(id.fileA, id.fileB, ignoreURL), .rebuildSynthesizedViews, .saveSessionDebounced]

        case .unignorePair(let fileA, let fileB):
            let resolvedA = URL(fileURLWithPath: fileA).resolvingSymlinksInPath().path
            let resolvedB = URL(fileURLWithPath: fileB).resolvingSymlinksInPath().path
            // Capture removed pairs BEFORE mutation for rollback
            var removedPairs: Set<PairID> = []
            for a in Set([fileA, resolvedA]) {
                for b in Set([fileB, resolvedB]) {
                    let fwd = PairIdentifier(fileA: a, fileB: b)
                    let rev = PairIdentifier(fileA: b, fileB: a)
                    if state.results?.ignoredPairs.contains(fwd) == true { removedPairs.insert(fwd) }
                    if state.results?.ignoredPairs.contains(rev) == true { removedPairs.insert(rev) }
                    state.results?.ignoredPairs.remove(fwd)
                    state.results?.ignoredPairs.remove(rev)
                }
            }
            state.results?.incrementFilterGeneration()
            let ignoreURL = state.lastScanConfig?.ignoreFile.map { URL(fileURLWithPath: $0) }
            effects = [.removeFromIgnoreList(fileA, fileB, ignoreURL, removedPairs), .rebuildSynthesizedViews, .saveSessionDebounced]

        case .clearIgnoredPairs:
            let snapshot = state.results?.ignoredPairs ?? []
            state.results?.ignoredPairs = []
            state.results?.incrementFilterGeneration()
            let ignoreURL = state.lastScanConfig?.ignoreFile.map { URL(fileURLWithPath: $0) }
            effects = [.clearIgnoreList(snapshot, ignoreURL), .rebuildSynthesizedViews, .saveSessionDebounced]

        case ._rollbackIgnore(let id):
            state.results?.ignoredPairs.remove(id)
            state.results?.incrementFilterGeneration()
            effects = [.rebuildSynthesizedViews, .saveSessionDebounced]

        case ._rollbackUnignore(let pairs):
            state.results?.ignoredPairs.formUnion(pairs)
            state.results?.incrementFilterGeneration()
            effects = [.rebuildSynthesizedViews, .saveSessionDebounced]

        case ._rollbackClearIgnored(let snapshot):
            state.results?.ignoredPairs = snapshot
            state.results?.incrementFilterGeneration()
            effects = [.rebuildSynthesizedViews, .saveSessionDebounced]

        case .undoResolution(let pairID):
            guard case .resolved(let record) = state.results?.resolutions[pairID] else {
                return (state, [])
            }
            state.results?.resolutions.removeValue(forKey: pairID)
            state.results?.actionHistory.removeAll {
                $0.actedOnPath == record.actedOnPath && $0.timestamp == record.timestamp
            }
            state.results?.incrementFilterGeneration()
            effects = [.saveSessionDebounced, .rebuildSynthesizedViews]

        // MARK: Bulk Operations

        case .startBulk:
            guard state.results?.bulkProgress == nil else { return (state, []) }
            guard state.results?.isDryRun != true else {
                let sentinelKey = PairIdentifier(fileA: "_bulk", fileB: "_bulk")
                state.results?.pairErrors[sentinelKey] = ActionError(
                    message: "Cannot perform bulk actions in dry-run mode"
                )
                return (state, [])
            }
            // Bulk candidates are computed by the store (needs filtered views).
            // Emit the effect with an empty list; the store intercepts .startBulk
            // and computes candidates before executing.
            state.results?.bulkProgress = BulkProgress(completed: 0, total: 0)
            state.results?.bulkCancelled = false
            effects = [.executeBulk([])]

        case .bulkStarted(let total):
            state.results?.bulkProgress = BulkProgress(completed: 0, total: total)

        case .cancelBulk:
            state.results?.bulkCancelled = true

        case .bulkItemCompleted(let pairID, let actionType, let actedOnPath, let affectedPairs, let meta):
            let keptPath = (actedOnPath == pairID.fileA) ? pairID.fileB : pairID.fileA
            let record = ActionRecord(
                pairID: pairID,
                timestamp: Date(),
                action: actionType.rawValue,
                actedOnPath: actedOnPath,
                keptPath: keptPath,
                bytesFreed: meta.bytesFreed,
                score: meta.score,
                strategy: meta.strategy,
                destination: meta.destination
            )
            for pair in affectedPairs {
                if state.results?.resolutions[pair] == nil {
                    state.results?.resolutions[pair] = .resolved(record)
                }
            }
            state.results?.actionHistory.append(record)
            state.results?.bulkProgress?.completed += 1
            state.results?.incrementFilterGeneration()
            effects = [.writeActionLog(record)]

        case .bulkFinished(let failures):
            state.results?.bulkProgress = nil
            if !failures.isEmpty {
                state.results?.pairErrors[PairIdentifier(fileA: "_bulk", fileB: "_bulk")] = ActionError(
                    message: "\(failures.count) file(s) failed"
                )
            }
            effects = [.saveSessionDebounced, .rebuildSynthesizedViews]

        // MARK: Effect Completions

        case .fileActionCompleted(let pairID, let actionType, let actedOnPath, let affectedPairs, let meta):
            let keptPath = (actedOnPath == pairID.fileA) ? pairID.fileB : pairID.fileA
            let record = ActionRecord(
                pairID: pairID,
                timestamp: Date(),
                action: actionType.rawValue,
                actedOnPath: actedOnPath,
                keptPath: keptPath,
                bytesFreed: meta.bytesFreed,
                score: meta.score,
                strategy: meta.strategy,
                destination: meta.destination
            )
            for pair in affectedPairs {
                if state.results?.resolutions[pair] == nil {
                    state.results?.resolutions[pair] = .resolved(record)
                }
            }
            state.results?.actionHistory.append(record)
            state.results?.incrementFilterGeneration()
            effects = [.writeActionLog(record), .saveSessionDebounced, .rebuildSynthesizedViews]

        case .fileActionFailed(let pairID, let error):
            state.results?.pairErrors[pairID] = ActionError(message: error)

        default:
            break // Unreachable — routed by top-level reduce()
        }

        return (state, effects)
    }

    // MARK: - Watch & Filesystem Liveness

    private static func reduceWatchAction(
        state: Session,
        action: SessionAction
    ) -> (Session, [SessionEffect]) {
        var state = state
        var effects: [SessionEffect] = []

        switch action {

        case .setWatchEnabled(let enabled):
            if enabled {
                guard state.phase == .results else { return (state, []) }
                state.watch = WatchState(
                    isActive: true,
                    stats: WatchStats(trackedFiles: 0),
                    startedAt: Date(),
                    sourceLabel: "scan"
                )
                let config = state.config ?? SessionConfig()
                let paths = collectFilePaths(from: state.results)
                let knownFiles = buildKnownFiles(from: state.results)
                effects = [
                    .startWatch(config, knownFiles),
                    .startFileMonitor(paths),
                ]
            } else {
                state.watch = nil
                effects = [.stopWatch, .stopFileMonitor]
            }

        case .watchAlertReceived(let pairs):
            // Require active watch — prevents stale engine events from mutating
            // preserved results after .startScan tears down the watch.
            guard state.watch != nil, let results = state.results, !pairs.isEmpty else { return (state, []) }
            // For pair-mode envelopes, always append to envelope.content regardless
            // of current view mode. This ensures watch pairs aren't lost when the
            // user toggles back from a temporary groups view — computeFilteredPairs
            // reads envelope.content for pair-mode envelopes, not synthesizedPairs.
            switch results.envelope.content {
            case .pairs(var existing):
                existing.append(contentsOf: pairs)
                state.results?.envelope.content = .pairs(existing)
                // Envelope mutated — raw sidecar bytes are now stale
                state.lastOriginalEnvelope = nil
            case .groups:
                // Groups-mode envelope: buffer pairs for synthesized pairs view
                state.results?.pendingWatchPairs.append(contentsOf: pairs)
            }
            // Update stats so the results header and persisted metadata reflect watch hits
            state.results?.envelope.stats.pairsAboveThreshold += pairs.count
            state.metadata.pairCount = state.results?.envelope.stats.pairsAboveThreshold
                ?? state.metadata.pairCount
            // Recompute recoverable space and analytics only for pair-mode
            // envelopes — both helpers require .pairs content. Group-mode
            // stats are left at their initial scan values.
            if case .pairs = state.results?.envelope.content {
                if let results = state.results {
                    let recoverable = results.computeSpaceRecoverable()
                    state.results?.envelope.stats.spaceRecoverable = recoverable
                    state.metadata.spaceRecoverable = recoverable
                }
                state.results?.recomputeAnalytics()
            }
            state.results?.incrementFilterGeneration()
            let newPaths = pairs.flatMap { [$0.fileA, $0.fileB] }
            effects = [.rebuildSynthesizedViews, .saveSessionDebounced, .expandFileMonitor(newPaths)]

        case .watchFileChanged(let path, let status):
            guard state.results != nil else { return (state, []) }
            // Don't overwrite .actioned status with a lesser status
            if case .actioned = state.results?.fileStatuses[path] {
                return (state, [])
            }
            state.results?.fileStatuses[path] = status
            propagateMissingFileResolutions(&state, statuses: [(key: path, value: status)])
            clearStaleMissingResolutions(&state, statuses: [(key: path, value: status)])
            state.results?.incrementFilterGeneration()
            effects = [.rebuildSynthesizedViews]

        case .watchFileBatchChanged(let updates):
            guard state.results != nil else { return (state, []) }
            for (path, status) in updates {
                // Don't overwrite .actioned status
                if case .actioned = state.results?.fileStatuses[path] {
                    continue
                }
                state.results?.fileStatuses[path] = status
            }
            propagateMissingFileResolutions(&state, statuses: updates.map { (key: $0.key, value: $0.value) })
            clearStaleMissingResolutions(&state, statuses: updates.map { (key: $0.key, value: $0.value) })
            state.results?.incrementFilterGeneration()
            effects = [.rebuildSynthesizedViews]

        case .fileStatusChecked(let statuses):
            guard state.results != nil else { return (state, []) }
            for (path, status) in statuses {
                // Don't overwrite .actioned status
                if case .actioned = state.results?.fileStatuses[path] {
                    continue
                }
                state.results?.fileStatuses[path] = status
            }
            propagateMissingFileResolutions(&state, statuses: statuses.map { (key: $0.key, value: $0.value) })
            clearStaleMissingResolutions(&state, statuses: statuses.map { (key: $0.key, value: $0.value) })
            state.results?.incrementFilterGeneration()
            effects = [.rebuildSynthesizedViews]

        default:
            break // Unreachable — routed by top-level reduce()
        }

        return (state, effects)
    }

    // MARK: - External Signals & History

    private static func reduceExternalSignal(
        state: Session,
        action: SessionAction
    ) -> (Session, [SessionEffect]) {
        var state = state
        var effects: [SessionEffect] = []

        switch action {

        case .openReplayFile(let url):
            switch state.phase {
            case .setup:
                // Initialize scan lifecycle state so the completion flow
                // (.cliStreamCompleted → .minimumDisplayElapsed → .results)
                // works correctly. Without this, state.scan is nil and the
                // minimumDisplayElapsed guard blocks the results transition.
                let hadWatch = state.watch != nil
                if hadWatch {
                    state.watch = nil
                }
                let config = state.config ?? SessionConfig()
                state.id = UUID()
                state.scanSequence &+= 1
                state.phase = .scanning
                state.scan = ScanProgress()
                state.scan?.timing.scanPhaseStartTime = Date()
                state.scan?.stages = ScanProgress.replayStages(
                    embedThumbnails: config.embedThumbnails
                )
                state.metadata = SessionMetadata(
                    directories: config.directories,
                    sourceLabel: config.directories.map {
                        ($0 as NSString).lastPathComponent
                    }.joined(separator: ", "),
                    mode: config.mode
                )
                effects = [.loadReplayData(url)]
                if hadWatch {
                    effects.append(contentsOf: [.stopWatch, .stopFileMonitor])
                }
            case .results:
                // Reset previous scan state and immediately start a replay so
                // opening a .ddscan file from Finder during results actually
                // loads it. Initialize full scan lifecycle state so the
                // completion flow (.cliStreamCompleted → .minimumDisplayElapsed
                // → .results) works correctly.
                // Preserve state.config so executeLoadReplay() can seed the
                // replay with GUI-only fields (action, moveToDir, etc.) that
                // seedConfigFromEnvelope() intentionally does not restore.
                let config = state.config ?? state.lastScanConfig ?? SessionConfig()
                resetScanState(&state)
                state.pendingReplayURL = nil
                state.lastPausedSessionId = nil
                state.pendingSession = nil
                state.watch = nil
                state.results = nil
                state.id = UUID()
                state.scanSequence &+= 1
                state.phase = .scanning
                state.scan = ScanProgress()
                state.scan?.timing.scanPhaseStartTime = Date()
                state.scan?.stages = ScanProgress.replayStages(
                    embedThumbnails: config.embedThumbnails
                )
                state.metadata = SessionMetadata(
                    directories: config.directories,
                    sourceLabel: config.directories.map {
                        ($0 as NSString).lastPathComponent
                    }.joined(separator: ", "),
                    mode: config.mode
                )
                effects = [.persistSessionId(nil), .stopFileMonitor, .stopWatch, .loadReplayData(url)]
            default:
                break
            }

        case .openWatchNotification(let sessionID):
            // Match by session ID, or fall back to the current session when
            // watch is active with results. The app has a single session at a
            // time, so if watch is running the results belong to this session
            // even if state.id diverged (e.g. after a new scan started while
            // watch was still active). Only fall back when watch is actually
            // active — a bare results != nil would match restored history
            // entries or replays that have nothing to do with this notification.
            let isMatch = state.id == sessionID
                || (state.watch != nil && state.results != nil)

            if isMatch {
                // Don't interrupt an active scan — just bring the window forward
                guard state.phase != .scanning else {
                    effects = [.activateWindow]
                    break
                }
                // Navigate to results if we have them (user may be on setup screen)
                if state.results != nil, state.phase != .results {
                    state.phase = .results
                }
                // Auto-select the last pair (most recently added by watch)
                if let results = state.results {
                    switch results.envelope.content {
                    case .pairs(let pairs):
                        if let last = pairs.last {
                            state.display.selectedPairID = PairIdentifier(fileA: last.fileA, fileB: last.fileB)
                        }
                    case .groups:
                        break
                    }
                }
                effects = [.activateWindow]
            } else if state.phase == .scanning {
                // Don't load a different session while a scan is running —
                // just bring the window forward. Loading would overwrite
                // scanning state without cancelling the in-flight CLI task.
                effects = [.activateWindow]
            } else {
                effects = [.loadSession(sessionID)]
            }

        case .activateWindow:
            effects = [.activateWindow]

        case .menuCommand(let cmd):
            guard state.phase == .results else { return (state, []) }
            // Menu commands that need current pair context are store-intercepted.
            // The reducer only handles .ignore which can work with selectedPairID.
            switch cmd {
            case .ignore:
                if let pairID = state.display.selectedPairID {
                    // Delegate to the ignore logic
                    return reduceResultsAction(state: state, action: .ignorePair(pairID))
                }
            case .keepA, .keepB, .skip, .previous, .actionMember, .focusQueue:
                break // Store-intercepted: requires pair context the reducer doesn't have
            }

        case .restoreSession(let id):
            effects = [.loadSession(id)]

        case .sessionLoaded(let persisted, let envelopeData):
            // Ignore stale loads — the user may have started a new scan or replay
            // while the async load was in flight.
            guard state.phase == .setup || state.phase == .results else {
                return (state, [])
            }
            // Tear down any active watch/monitor before replacing state — without
            // this, alerts from the old watch directories would flow into the
            // newly loaded results.
            let hadWatch = state.watch != nil
            // Full restore from persisted session
            state = Session(from: persisted)
            state.lastOriginalEnvelope = envelopeData
            let paths = collectFilePaths(from: state.results)
            if hadWatch {
                effects = [.stopWatch, .stopFileMonitor,
                           .checkFileStatuses(paths), .startFileMonitor(paths)]
            } else {
                effects = [.stopFileMonitor,
                           .checkFileStatuses(paths), .startFileMonitor(paths)]
            }

        case .deleteHistorySession(let id):
            effects = [.deleteSession(id)]

        default:
            break // Unreachable — routed by top-level reduce()
        }

        return (state, effects)
    }

    // MARK: - Results Filtering Helpers (for view mode toggle)

    /// Delegate to shared `ResultsSnapshot.rawFilteredPairs(viewMode:)`.
    private static func rawFilteredPairs(state: Session) -> [PairResult] {
        state.results?.rawFilteredPairs(viewMode: state.display.viewMode) ?? []
    }

    /// Delegate to shared `ResultsSnapshot.rawFilteredGroups(viewMode:)`.
    private static func rawFilteredGroups(state: Session) -> [GroupResult] {
        state.results?.rawFilteredGroups(viewMode: state.display.viewMode) ?? []
    }

    /// Shared logic for switching view mode to `targetMode`.
    /// Returns `nil` (no-op) when the mode is already active or the toggle precondition fails.
    private static func applyViewModeChange(
        to targetMode: DisplayState.ViewMode,
        state: inout Session
    ) -> [SessionEffect]? {
        guard let results = state.results,
              state.display.viewMode != targetMode,
              results.canToggleViewMode(for: state.display.viewMode) else {
            return nil
        }

        if targetMode == .groups {
            // Switching pairs -> groups
            let rawPairs = rawFilteredPairs(state: state)
            var groups = ResultsSnapshot.synthesizeGroups(
                from: rawPairs, keepStrategy: results.envelope.args.keep
            )
            state.results?.assignStableIDs(to: &groups)
            state.results?.synthesizedGroups = groups

            // Translate pair selection to group selection
            if !state.display.selectedForAction.isEmpty {
                let selectedPaths = state.display.selectedForAction.flatMap { id in
                    [id.fileA, id.fileB]
                }
                let selectedPathSet = Set(selectedPaths)
                var groupIDs = Set<Int>()
                for group in groups {
                    let memberPaths = Set(group.files.map(\.path))
                    if !memberPaths.isDisjoint(with: selectedPathSet) {
                        groupIDs.insert(group.groupId)
                    }
                }
                state.display.selectedGroupsForAction = groupIDs
            }

            state.display.viewMode = .groups
            state.results?.incrementFilterGeneration()
        } else {
            // Switching groups -> pairs
            let rawGroups = rawFilteredGroups(state: state)
            var pairs = ResultsSnapshot.synthesizePairs(from: rawGroups)
            // Include accumulated watch pairs (do not drain — see updateSynthesizedViews)
            if let pending = state.results?.pendingWatchPairs, !pending.isEmpty {
                pairs.append(contentsOf: pending)
            }
            state.results?.synthesizedPairs = pairs
            state.display.viewMode = .pairs
            state.results?.incrementFilterGeneration()
        }

        return []
    }

    /// When files are detected as missing or moved, create `.probablySolved`
    /// resolutions for any pairs containing those paths (unless already `.resolved`).
    private static func propagateMissingFileResolutions(_ state: inout Session, statuses: some Sequence<(key: String, value: FileStatus)>) {
        guard let results = state.results else { return }
        let missingPaths = statuses.compactMap { path, status -> String? in
            switch status {
            case .missing: path
            case .moved: path  // original path no longer exists
            default: nil
            }
        }
        guard !missingPaths.isEmpty else { return }

        let allPairs: [(String, String)]
        switch results.envelope.content {
        case .pairs(let pairs):
            allPairs = pairs.map { ($0.fileA, $0.fileB) }
        case .groups(let groups):
            allPairs = ResultsSnapshot.synthesizePairs(from: groups).map { ($0.fileA, $0.fileB) }
        }

        for missingPath in missingPaths {
            for (fileA, fileB) in allPairs {
                guard fileA == missingPath || fileB == missingPath else { continue }
                let pairID = PairIdentifier(fileA: fileA, fileB: fileB)
                guard state.results?.resolutions[pairID] == nil else { continue }
                state.results?.resolutions[pairID] = .probablySolved(missing: [missingPath])
            }
        }
    }

    /// When files reappear at their original path, clear any `.probablySolved`
    /// resolutions whose missing-path set becomes empty.
    private static func clearStaleMissingResolutions(_ state: inout Session, statuses: some Sequence<(key: String, value: FileStatus)>) {
        guard state.results != nil else { return }
        let reappearedPaths = Set(statuses.compactMap { path, status -> String? in
            status == .present ? path : nil
        })
        guard !reappearedPaths.isEmpty else { return }

        guard let resolutions = state.results?.resolutions else { return }
        for (pairID, resolution) in resolutions {
            guard case .probablySolved(let missing) = resolution else { continue }
            let remaining = missing.filter { !reappearedPaths.contains($0) }
            if remaining.isEmpty {
                state.results?.resolutions.removeValue(forKey: pairID)
            } else if remaining.count < missing.count {
                state.results?.resolutions[pairID] = .probablySolved(missing: remaining)
            }
        }
    }

    /// Collect all file paths referenced in scan results (for file monitoring).
    private static func collectFilePaths(from results: ResultsSnapshot?) -> [String] {
        guard let results else { return [] }
        var paths = Set<String>()
        switch results.envelope.content {
        case .pairs(let pairs):
            for pair in pairs {
                paths.insert(pair.fileA)
                paths.insert(pair.fileB)
            }
        case .groups(let groups):
            for group in groups {
                for file in group.files {
                    paths.insert(file.path)
                }
            }
        }
        // Include paths from pending watch pairs (group-mode watch hits
        // that aren't in the envelope) so they get file-status monitoring.
        for pair in results.pendingWatchPairs {
            paths.insert(pair.fileA)
            paths.insert(pair.fileB)
        }
        // Exclude photos:// URIs — FileStatusMonitor uses FSEventStream
        // which can't monitor synthetic Photos Library URIs.
        return Array(paths.filter { !$0.isPhotosAssetURI }).sorted()
    }

    /// Build the watch engine's known-file inventory from scan results.
    ///
    /// Extracts unique files with their metadata so the engine can score
    /// newly detected files against the existing scan baseline.
    private static func buildKnownFiles(from results: ResultsSnapshot?) -> [KnownFile] {
        guard let results else { return [] }
        var seen = Set<String>()
        var known: [KnownFile] = []

        func add(path: String, metadata: FileMetadata?) {
            guard !seen.contains(path), let metadata else { return }
            seen.insert(path)
            known.append(KnownFile(path: path, metadata: metadata))
        }

        switch results.envelope.content {
        case .pairs(let pairs):
            for pair in pairs {
                add(path: pair.fileA, metadata: pair.fileAMetadata)
                add(path: pair.fileB, metadata: pair.fileBMetadata)
            }
        case .groups(let groups):
            for group in groups {
                for file in group.files {
                    let meta = FileMetadata(
                        duration: file.duration, width: file.width, height: file.height,
                        fileSize: file.fileSize, codec: file.codec, bitrate: file.bitrate,
                        framerate: file.framerate, audioChannels: file.audioChannels,
                        mtime: file.mtime
                    )
                    add(path: file.path, metadata: meta)
                }
            }
        }
        // Include files from pending watch pairs so the watch engine's
        // baseline is complete when re-enabling watch on a restored session.
        for pair in results.pendingWatchPairs {
            add(path: pair.fileA, metadata: pair.fileAMetadata)
            add(path: pair.fileB, metadata: pair.fileBMetadata)
        }
        return known
    }
}
