import Foundation

/// Every state change in the unified session lifecycle maps to exactly one action.
/// Actions are dispatched via the session store's `send(_:)` method.
///
/// Consolidates the former `ScanAction` and `ResultsAction` into a single enum
/// so every domain event flows through one reducer.
enum SessionAction: Sendable {

    // MARK: - Setup

    case startScan(SessionConfig)
    case startPhotosScan(PhotosScope, SessionConfig)
    case startReplay(URL, SessionConfig)
    case resumeSession(String, SessionConfig)
    case discardSession(String)

    // MARK: - Scan Lifecycle

    case cliSessionStart(SessionStartEvent)
    case cliStageStart(StageStartEvent)
    case cliProgress(StageProgressEvent)
    case cliStageEnd(StageEndEvent)
    case cliStreamCompleted(ScanEnvelope?, Data?)
    case cliStreamFailed(ErrorInfo)
    case cliStreamCancelled
    case resultsReady(ResultsSnapshot, ResultsDisplayConfig)
    case photosAuthorizationLimited
    case photosAuthRevoked
    case cancelScan
    case pauseScan
    case resumeScan
    case cliPauseConfirmed(PauseEvent)
    case cliResumeConfirmed(ResumeEvent)
    case pauseTimeoutFired
    case minimumDisplayElapsed

    // MARK: - Results & Review

    case selectPair(PairID?)
    case keepFile(PairID, String, ActionType)
    case skipPair
    case previousPair
    case ignorePair(PairID)
    case unignorePair(String, String)
    case clearIgnoredPairs
    // Internal rollback actions (dispatched by store on ignore-list write failure)
    case _rollbackIgnore(PairID)
    case _rollbackUnignore(Set<PairID>)
    case _rollbackClearIgnored(Set<PairID>)
    case undoResolution(PairID)
    case toggleViewMode
    case setViewMode(DisplayState.ViewMode)
    case setSearchText(String)
    case setSortOrder(ResultSortOrder)
    case setActiveAction(ActionType)
    case setMoveDestination(URL?)
    case toggleInsights
    case setDirectoryFilter(String?)
    case toggleSelectMode
    case selectAll
    case deselectAll
    case setSelectedPairs(Set<PairIdentifier>)
    case setSelectedGroups(Set<Int>)
    case togglePairSelection(PairIdentifier)
    case toggleGroupSelection(Int)
    case clearPairError(PairID)
    case startBulk
    case bulkStarted(Int)
    case cancelBulk
    case bulkItemCompleted(PairID, ActionType, String, [PairID], FileActionMeta)
    case bulkFinished([String])
    case fileActionCompleted(PairID, ActionType, String, [PairID], FileActionMeta)
    case fileActionFailed(PairID, String)

    // MARK: - Watch

    case setWatchEnabled(Bool)
    case watchAlertReceived([PairResult])
    case watchFileChanged(String, FileStatus)
    case watchFileBatchChanged([String: FileStatus])

    // MARK: - Filesystem Liveness

    case fileStatusChecked([String: FileStatus])

    // MARK: - History / Sessions

    case restoreSession(UUID)
    case sessionLoaded(PersistedSession, Data?)
    case deleteHistorySession(UUID)

    // MARK: - External Signals

    case openReplayFile(URL)
    case openWatchNotification(UUID)
    case activateWindow
    case menuCommand(MenuCommand)

    // MARK: - Internal State Patching

    /// Inject pause file URL into the scan state (set before CLI launch).
    case setPauseFile(URL)
    /// Configure replay session config and optional original envelope data.
    case configureReplay(SessionConfig, Data?)
    /// Update synthesized views (groups/pairs) computed by the store.
    case updateSynthesizedViews(groups: [GroupResult]?, pairs: [PairResult]?)
    /// Set paused CLI session info discovered at startup.
    case setPausedSession(String, SessionInfo?)

    // MARK: - Navigation

    case resetToSetup

    // MARK: - Debug

    #if DEBUG
    /// Inject preview state for SwiftUI previews. Routes through the reducer
    /// so `syncRoutingProperties()` runs after the state change.
    case _injectPreviewState(scan: ScanProgress, config: ScanConfig)
    #endif
}

// MARK: - MenuCommand

/// Commands triggered from the app's menu bar (Review menu).
enum MenuCommand: Sendable {
    case keepA
    case keepB
    case skip
    case previous
    case ignore
    case actionMember
    case focusQueue
}

// MARK: - ResultsDisplayConfig

/// Display configuration computed by the store and applied by the reducer
/// when results become ready. Eliminates direct session mutations in
/// the store's `configureResults()` method.
struct ResultsDisplayConfig: Sendable, Equatable {
    let activeAction: ActionType
    let moveDestination: URL?
    let rawEnvelopeData: Data?
}

// MARK: - FileActionMeta

/// Metadata captured at action execution time for accurate action log records.
struct FileActionMeta: Sendable, Equatable {
    let bytesFreed: Int?
    let score: Int
    let strategy: String?
    let destination: String?
}

// MARK: - ProgressEvent Bridge

extension ProgressEvent {
    /// Convert a CLI progress event into a session action for the unified reducer.
    func toSessionAction() -> SessionAction? {
        switch self {
        case .sessionStart(let e): .cliSessionStart(e)
        case .stageStart(let e):   .cliStageStart(e)
        case .progress(let e):     .cliProgress(e)
        case .stageEnd(let e):     .cliStageEnd(e)
        case .sessionEnd:          nil // handled via stream completion, not progress events
        case .pause(let e):        .cliPauseConfirmed(e)
        case .resume(let e):       .cliResumeConfirmed(e)
        }
    }
}
