import AppKit
import Foundation
import Observation
import os
import SwiftUI

private let diagLog = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "SessionStore")

/// Unified observable store that drives the entire session lifecycle.
///
/// Replaces the fragmented `ScanStore` + `ResultsStore` with a single store
/// that holds `Session` state, dispatches actions through `SessionReducer`,
/// and executes side effects.
@Observable @MainActor
public final class SessionStore {

    // MARK: - Source of Truth

    /// Full session state (value type, driven by reducer).
    var session: Session

    // MARK: - Mirrored Routing Properties

    /// Separate tracked properties for efficient SwiftUI observation.
    /// Because these are Equatable, @Observable only fires when the value changes,
    /// preventing parent re-evaluation on every progress event.
    var phase: Session.Phase
    var watchActive: Bool = false
    var selectedPairID: PairID?

    /// Whether the user intends to watch after scan completes.
    /// Set during setup, consumed when transitioning to results.
    var watchEnabled: Bool = false

    // MARK: - Profile State (UI-only, not in reducer)

    /// Available configuration profiles loaded from disk.
    var profiles: [ProfileEntry] = []

    /// Currently selected profile name (nil = none).
    var selectedProfileName: String?

    // MARK: - Menu Command Routing

    /// A timestamped menu command for views to observe via `.onChange`.
    struct TimestampedMenuCommand: Equatable {
        let command: MenuCommand
        let seq: UInt
    }

    /// Last menu command received, for views to observe via `.onChange`.
    private(set) var lastMenuCommand: TimestampedMenuCommand?
    private var menuCommandSeq: UInt = 0

    // MARK: - Cached Filtered Views

    /// Filtered and sorted pairs, recomputed when `filterGeneration` changes.
    private(set) var filteredPairs: [PairResult] = []

    /// Filtered and sorted groups, recomputed when `filterGeneration` changes.
    private(set) var filteredGroups: [GroupResult] = []

    /// Paths from all resolution entries (resolved or probably-solved).
    private(set) var resolvedOrMissingPaths: Set<String> = []

    // MARK: - Setup State

    /// Setup/configuration state, driven by `SetupReducer`.
    var setupState: SetupState

    // MARK: - In-Flight Action Tracking

    /// In-flight action tasks that must complete before reading the log file.
    private(set) var inflightActionTasks: [Task<Void, Never>] = []

    /// Error from the last export attempt. Views observe this to show an alert.
    var lastExportError: String?

    // MARK: - Private Infrastructure

    let bridge: any CLIBridgeProtocol
    public let registry: SessionRegistry
    private var scanTask: Task<Void, Never>?
    private var scanGeneration: UInt = 0
    private var pauseTimeoutTask: Task<Void, Never>?
    private var saveDebounceTask: Task<Void, Never>?
    private var saveSessionTask: Task<Void, Never>?
    private var minimumDisplayTask: Task<Void, Never>?
    /// Monotonically increasing counter for session restore requests.
    /// Prevents stale async loads from overwriting newer restores.
    private var restoreGeneration: UInt = 0
    /// Queue for actions dispatched during an active `send()` cycle.
    /// Prevents re-entrant reduce-sync-recompute-execute nesting.
    private var pendingActions: [SessionAction] = []
    private var isDispatching = false

    /// Whether `continueStartup()` has finished (XDG path resolved, session restored).
    private var startupComplete = false
    /// Buffered watch notification received before startup completed.
    private var pendingWatchNotificationID: UUID?

    /// Callback to activate or recreate the main window. Wired by the SwiftUI
    /// scene body so the effect layer can request window creation without
    /// depending on `AppDelegate` (which lives in the app target).
    public var onActivateMainWindow: (() -> Void)?

    /// Continuations for in-flight destructive file actions, keyed by pair ID.
    private var pendingActionContinuations: [PairIdentifier: CheckedContinuation<Bool, Never>] = [:]
    /// In-flight file action tasks, keyed by pair ID. Cancelled on session transitions
    /// to prevent stale completions from writing into the wrong session.
    private var fileActionTasks: [PairIdentifier: Task<Void, Never>] = [:]
    /// In-flight bulk action task. Cancelled on session transitions.
    private var bulkActionTask: Task<Void, Never>?

    /// Resume all pending action continuations with `false`, cancel in-flight file
    /// action and bulk action tasks, and clear all tracking state. Called on session
    /// reset and deinit to prevent continuation leaks and stale completions.
    private func cancelPendingContinuations() {
        bulkActionTask?.cancel()
        bulkActionTask = nil
        for (_, task) in fileActionTasks {
            task.cancel()
        }
        fileActionTasks.removeAll()
        for (_, continuation) in pendingActionContinuations {
            continuation.resume(returning: false)
        }
        pendingActionContinuations.removeAll()
    }

    /// Immediately execute any pending debounced save to prevent data loss
    /// during state transitions.
    private func flushPendingSave() {
        guard saveDebounceTask != nil else { return }
        saveDebounceTask?.cancel()
        saveDebounceTask = nil
        execute(.saveSession)
    }

    private var lastFilterGeneration: UInt = .max  // Forces initial computation
    private var fileMonitor: FileStatusMonitor?

    // MARK: - Watch Infrastructure

    private var directoryWatcher: DirectoryWatcher?
    private var backgroundEngine: BackgroundScanEngine?
    private let menuBarManager = MenuBarManager()
    private let notificationManager = WatchNotificationManager()
    private var watchStartupTask: Task<Void, Never>?
    private var watchBridgeTask: Task<Void, Never>?
    private var watchStatsTimer: Task<Void, Never>?

    /// Cached resolved shell environment for watch subprocess spawning.
    private var cachedShellEnvironment: [String: String]?

    // MARK: - Constants

    nonisolated static let minimumDisplayDuration: TimeInterval = 0.8
    nonisolated static let pausedSessionDefaultsKey = "dd.lastPausedSessionId"

    private static let iso8601Formatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    // MARK: - Initialisation

    init(bridge: any CLIBridgeProtocol, registry: SessionRegistry) {
        self.bridge = bridge
        self.registry = registry
        self.session = Session()
        self.phase = .setup
        self.setupState = SetupState.fromDefaults()
    }

    /// Convenience init that creates a default registry. Used by tests and
    /// production code that doesn't need a custom storage directory.
    convenience init(bridge: any CLIBridgeProtocol) {
        self.init(bridge: bridge, registry: SessionRegistry())
    }

    // SE-0371: Under Swift 6 strict concurrency, deinit on @MainActor classes
    // is nonisolated. MainActor.assumeIsolated is safe here because
    // SessionStore's lifecycle is tied to the SwiftUI view hierarchy, which
    // always deallocates @Observable objects on the main actor.
    deinit {
        MainActor.assumeIsolated {
            cancelPendingContinuations()
            scanTask?.cancel()
            pauseTimeoutTask?.cancel()
            saveDebounceTask?.cancel()
            watchBridgeTask?.cancel()
            watchStatsTimer?.cancel()
            // Best-effort cleanup for actor-based resources.
            // Fire-and-forget since deinit can't await.
            let monitor = fileMonitor
            let watcher = directoryWatcher
            let engine = backgroundEngine
            if monitor != nil || watcher != nil || engine != nil {
                Task {
                    await monitor?.stop()
                    await watcher?.stop()
                    await engine?.stop()
                }
            }
        }
    }

    // MARK: - Dispatch (Session Actions)

    /// Central dispatch: intercept navigation-dependent actions, run the reducer,
    /// sync routing properties, recompute cached views, and execute effects.
    ///
    /// `interceptAction` expands a single user action into one or more reducer
    /// actions (e.g., `.skipPair` becomes `[.selectPair(next), .skipPair]`).
    /// All actions are reduced sequentially, but routing properties and cached
    /// views are synced only once at the end, avoiding redundant recomputation.
    func send(_ action: SessionAction) {
        // Re-entrancy guard: if we're already dispatching, queue for later.
        if isDispatching {
            pendingActions.append(action)
            return
        }

        isDispatching = true
        defer { isDispatching = false }

        dispatchAction(action)

        // Drain any actions queued by effect handlers or post-dispatch logic.
        while !pendingActions.isEmpty {
            let next = pendingActions.removeFirst()
            dispatchAction(next)
        }
    }

    /// Core dispatch: intercept, reduce, sync, recompute, execute effects, auto-watch.
    private func dispatchAction(_ action: SessionAction) {
        let actions = interceptAction(action)
        let oldPhase = session.phase

        var allEffects: [SessionEffect] = []
        for resolved in actions {
            let (newState, effects) = SessionReducer.reduce(state: session, action: resolved)
            session = newState
            allEffects.append(contentsOf: effects)
        }

        // Sync routing properties once (Equatable — @Observable only fires on change)
        syncRoutingProperties()

        // Clear watch intent only when user explicitly disables watch — not on
        // automatic teardown (e.g. .startScan clearing state.watch).
        if case .setWatchEnabled(false) = action {
            watchEnabled = false
        }

        // Recompute cached views when filter generation changes OR when results
        // first appear (generation 0 == 0 but filteredPairs is still empty).
        if let results = session.results,
           results.filterGeneration != lastFilterGeneration || filteredPairs.isEmpty
        {
            recomputeCachedViews()
        } else if session.results == nil, lastFilterGeneration != .max {
            // Results cleared (e.g. resetToSetup) — reset cached views so the
            // next snapshot forces recomputation even if filterGeneration matches.
            lastFilterGeneration = .max
            filteredPairs = []
            filteredGroups = []
            resolvedOrMissingPaths = []
        }

        // Execute effects
        for effect in allEffects {
            execute(effect)
        }

        // Auto-start watch when transitioning to results if watchEnabled intent is set.
        // Uses send() which will queue if we're in a dispatch cycle.
        if oldPhase != .results,
           session.phase == .results,
           watchEnabled,
           session.watch == nil
        {
            send(.setWatchEnabled(true))
        }

        // Track menu commands for view observation
        if case .menuCommand(let cmd) = action {
            menuCommandSeq &+= 1
            lastMenuCommand = TimestampedMenuCommand(command: cmd, seq: menuCommandSeq)
        }
    }

    /// Sync mirrored routing properties from session state.
    private func syncRoutingProperties() {
        phase = session.phase
        watchActive = session.watch?.isActive ?? false
        selectedPairID = session.display.selectedPairID
    }

    // MARK: - Dispatch (Setup Actions)

    /// Dispatch a setup/configuration action through the setup reducer.
    func sendSetup(_ action: SetupAction) {
        let (newState, effects) = SetupReducer.reduce(state: setupState, action: action)
        setupState = newState
        for effect in effects {
            executeSetupEffect(effect)
        }
    }

    // MARK: - Convenience Accessors

    /// Whether the scan can be started from the current state.
    var canStartScan: Bool {
        setupState.isValid && phase == .setup
    }

    /// The pair that should be selected after the current pair is removed by an action.
    var nextPairAfterAction: PairIdentifier? {
        let pairs = filteredPairs
        guard let id = selectedPairID,
              let idx = pairs.firstIndex(where: { $0.pairIdentifier == id }),
              pairs.count > 1 else { return nil }
        if idx + 1 < pairs.count { return pairs[idx + 1].pairIdentifier }
        if idx > 0 { return pairs[idx - 1].pairIdentifier }
        return nil
    }

    /// Index of the currently selected pair within `filteredPairs`.
    var currentPairIndex: Int? {
        guard let id = selectedPairID else { return nil }
        return filteredPairs.firstIndex { $0.pairIdentifier == id }
    }

    /// Whether a group is fully resolved (all non-keeper, non-reference members
    /// actioned or missing).
    func isGroupFullyResolved(_ group: GroupResult) -> Bool {
        let candidates: [GroupFile]
        if let keepPath = group.keep {
            candidates = group.files.filter { $0.path != keepPath && !$0.isReference }
        } else {
            candidates = group.files.filter { !$0.isReference }
        }
        guard !candidates.isEmpty else { return false }
        return candidates.allSatisfy { resolvedOrMissingPaths.contains($0.path) }
    }

    /// Teardown the store, cancelling all inflight tasks and stopping watch infrastructure.
    public func teardown() {
        // Cancel any in-flight async saves so they don't race with the
        // synchronous save below. The debounce Task schedules saves; the
        // saveSessionTask performs the actual registry write. Both must be
        // cancelled before the sync write to avoid index.json corruption.
        saveDebounceTask?.cancel()
        saveDebounceTask = nil
        saveSessionTask?.cancel()
        saveSessionTask = nil
        minimumDisplayTask?.cancel()
        minimumDisplayTask = nil
        if let persisted = session.persisted() {
            let envelopeData: Data? = session.lastOriginalEnvelope ?? {
                guard let envelope = session.results?.envelope else { return nil }
                let encoder = JSONEncoder()
                encoder.keyEncodingStrategy = .convertToSnakeCase
                return try? encoder.encode(envelope)
            }()
            registry.saveSessionSync(persisted, envelopeData: envelopeData)
        }
        scanTask?.cancel()
        pauseTimeoutTask?.cancel()
        watchBridgeTask?.cancel()
        watchStatsTimer?.cancel()

        // Stop watch infrastructure
        if let watcher = directoryWatcher {
            directoryWatcher = nil
            Task { await watcher.stop() }
        }
        if let engine = backgroundEngine {
            backgroundEngine = nil
            Task { await engine.stop() }
        }
        menuBarManager.deactivate()
        Task { await notificationManager.flush() }

        // Stop file monitor
        if let monitor = fileMonitor {
            fileMonitor = nil
            Task { await monitor.stop() }
        }

        // Cancel bridge
        Task { await bridge.cancelCurrentTask() }

        // Save last session ID for window restoration
        if phase == .results {
            AppDefaults.lastActiveSessionID = session.id.uuidString
        }
    }

    /// Check for a previously active session and restore it on app launch.
    /// Also triggers one-time legacy history migration on first run.
    public func start() async {
        // Resolve XDG data path from login shell BEFORE any registry access,
        // so Finder-launched instances use the correct session storage path.
        let dataBase = await ShellEnvironmentResolver.shared.dataBaseDirectory()
        await registry.resolveStorageDirectory(dataBase: dataBase)
        // Continue startup on MainActor after resolution completes
        continueStartup()
    }

    /// Second phase of startup, called after XDG path resolution completes.
    private func continueStartup() {
        // One-time legacy history migration
        migrateLegacyHistoryIfNeeded()

        // Restore a full results session from the last active session ID.
        // Guard: only restore if the user hasn't started working yet (still in
        // pristine setup state). On slow shell startups the user may have already
        // begun a scan by the time continueStartup() fires.
        if let savedID = AppDefaults.lastActiveSessionID,
           let uuid = UUID(uuidString: savedID) {
            if session.phase == .setup, session.scanSequence == 0,
               !setupState.hasUserModifications {
                // Clear so the restore is one-shot — the user starts fresh
                // on the next launch unless teardown() saves a new active session.
                // Only clear AFTER the guard passes — if the user modified setup
                // during a slow launch, preserve the ID for a future restart.
                AppDefaults.lastActiveSessionID = nil
                send(.restoreSession(uuid))
                // Do NOT return — the paused-session probe below must still run
                // so the resume card appears even when restoring a previous session.
            }
        }

        // Check for a CLI-paused session that can be resumed
        if let pausedId = UserDefaults.standard.string(forKey: Self.pausedSessionDefaultsKey) {
            // Dispatch through reducer so syncRoutingProperties() runs.
            send(.setPausedSession(pausedId, nil))
            // Fetch session details from CLI in the background
            let bridge = self.bridge
            Task {
                guard let sessions = await bridge.listSessionsJSON() else {
                    // Command failed (binary not found, subprocess error) — keep the
                    // paused card as-is rather than discarding a potentially valid session.
                    return
                }
                if let match = sessions.first(where: { $0.sessionId == pausedId }) {
                    self.send(.setPausedSession(pausedId, match))
                } else {
                    // CLI session was pruned or deleted externally — clear the stale card
                    self.send(.discardSession(pausedId))
                }
            }
        }

        // Mark startup complete and replay any buffered watch notification
        // that arrived before XDG path resolution finished.
        startupComplete = true
        if let pendingID = pendingWatchNotificationID {
            pendingWatchNotificationID = nil
            send(.openWatchNotification(pendingID))
        }
    }

    /// UserDefaults key tracking whether legacy migration has been performed.
    private nonisolated static let legacyMigrationKey = "dd.legacyHistoryMigrated"

    /// Run legacy history migration once, gated by a UserDefaults flag.
    private func migrateLegacyHistoryIfNeeded() {
        guard !UserDefaults.standard.bool(forKey: Self.legacyMigrationKey) else { return }
        let reg = registry
        Task.detached {
            let success = await reg.migrateFromLegacyFormat()
            if success {
                await MainActor.run {
                    UserDefaults.standard.set(true, forKey: SessionStore.legacyMigrationKey)
                }
            }
        }
    }

    // MARK: - Public API (App Target)

    /// Open a replay file from a URL (e.g., double-click a .ddscan file).
    ///
    /// When in setup phase, seeds `session.config` from the current setup form
    /// so the replay inherits the user's action, move-to, ignore-file, and log
    /// settings (fields that don't round-trip through the envelope).
    public func openReplayFile(_ url: URL) {
        if session.phase == .setup {
            session.config = setupState.buildConfig()
        }
        send(.openReplayFile(url))
    }

    /// Route a watch notification tap to the correct session.
    /// On cold launch, buffers the notification until `continueStartup()` finishes
    /// so the session registry has resolved the correct XDG storage path.
    public func openWatchNotification(sessionID: UUID) {
        guard startupComplete else {
            pendingWatchNotificationID = sessionID
            return
        }
        send(.openWatchNotification(sessionID))
    }

    /// Dispatch a menu command from the Review menu.
    public enum PublicMenuCommand: Sendable {
        case keepA, keepB, skip, previous, ignore, actionMember, focusQueue
    }

    public func sendMenuCommand(_ command: PublicMenuCommand) {
        let internal_: MenuCommand = switch command {
        case .keepA: .keepA
        case .keepB: .keepB
        case .skip: .skip
        case .previous: .previous
        case .ignore: .ignore
        case .actionMember: .actionMember
        case .focusQueue: .focusQueue
        }
        send(.menuCommand(internal_))
    }
}

// MARK: - Action Interception

extension SessionStore {

    /// Expand a single user action into one or more reducer actions.
    ///
    /// Actions that require pre-computed navigation context (e.g., "advance to
    /// next pair") return a sequence like `[.selectPair(next), .skipPair]` so
    /// that navigation and the originating action are both reduced without
    /// re-entrant `send()` calls.
    private func interceptAction(_ action: SessionAction) -> [SessionAction] {
        switch action {

        case .skipPair:
            if let next = nextPairAfterAction {
                return [.selectPair(next), action]
            }
            return [action]

        case .previousPair:
            let pairs = filteredPairs
            guard !pairs.isEmpty else { return [action] }
            guard let idx = currentPairIndex else {
                return [.selectPair(pairs.first?.pairIdentifier), action]
            }
            if idx > 0 {
                return [.selectPair(pairs[idx - 1].pairIdentifier), action]
            }
            return [action]

        case .keepFile:
            // Navigation handled by callers after the async file operation completes.
            return [action]

        case .ignorePair:
            // Advance to next pair before ignore
            if session.results?.isDryRun != true, let next = nextPairAfterAction {
                return [.selectPair(next), action]
            }
            return [action]

        case .selectAll:
            // Compute the full selection set from filtered views and dispatch
            // through the reducer via dedicated actions (no direct mutation).
            if session.display.viewMode == .pairs {
                let selection = Set(filteredPairs.compactMap { pair -> PairIdentifier? in
                    let id = pair.pairIdentifier
                    guard let results = session.results else { return nil }
                    if case .active = results.resolutionStatus(for: id) { return id }
                    return nil
                })
                return [.setSelectedPairs(selection)]
            } else {
                let selection = Set(filteredGroups.compactMap { group -> Int? in
                    if isGroupFullyResolved(group) { return nil }
                    return group.groupId
                })
                return [.setSelectedGroups(selection)]
            }

        case .startBulk:
            // Compute bulk candidates from filtered views before executing
            // The reducer sets up bulkProgress; we'll compute real candidates in execute()
            return [action]

        case .resetToSetup:
            // Flush any debounced session save before the reducer clears results,
            // otherwise the last ignore/action/undo changes are lost from history.
            flushPendingSave()
            return [action]

        default:
            return [action]
        }
    }
}

// MARK: - Cached View Recomputation

extension SessionStore {

    /// Recompute all cached filtered views from the current session state.
    private func recomputeCachedViews() {
        guard let results = session.results else { return }
        lastFilterGeneration = results.filterGeneration

        resolvedOrMissingPaths = results.computeResolvedOrMissingPaths()

        filteredPairs = results.computeFilteredPairs(display: session.display)

        filteredGroups = results.computeFilteredGroups(
            display: session.display,
            isGroupFullyResolved: { self.isGroupFullyResolved($0) }
        )
    }
}

// MARK: - Setup Effect Execution

extension SessionStore {

    /// Execute a single setup side effect.
    private func executeSetupEffect(_ effect: SetupEffect) {
        switch effect {
        case .updateFileCount:
            let entries = setupState.entries
            let mode = setupState.mode
            let extensions = setupState.extensions
            let noRecursive = setupState.noRecursive
            Task {
                let count = await Self.countFiles(
                    entries: entries, mode: mode,
                    extensions: extensions, noRecursive: noRecursive
                )
                self.sendSetup(.fileCountUpdated(count))
            }

        case .detectPreset:
            // Preset detection is handled synchronously by checking current state.
            // No async work needed — the reducer handles this.
            break
        }
    }

    /// Count files matching the current setup configuration.
    /// Runs on a detached task to avoid blocking the main actor.
    nonisolated private static func countFiles(
        entries: [DirectoryEntry],
        mode: ScanMode,
        extensions: String,
        noRecursive: Bool
    ) async -> Int? {
        await Task.detached {
            Self.countFilesSync(
                entries: entries, mode: mode,
                extensions: extensions, noRecursive: noRecursive
            )
        }.value
    }

    /// Synchronous file counting (must not be called from async context directly
    /// due to NSEnumerator restrictions).
    nonisolated private static func countFilesSync(
        entries: [DirectoryEntry],
        mode: ScanMode,
        extensions: String,
        noRecursive: Bool
    ) -> Int? {
        let dirs = entries.filter { !$0.isReference }.map(\.path)
        guard !dirs.isEmpty else { return nil }

        let exts: Set<String>
        if !extensions.trimmingCharacters(in: .whitespaces).isEmpty {
            exts = Set(
                extensions.split(separator: ",")
                    .map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
            )
        } else {
            exts = defaultExtensions(for: mode)
        }

        var count = 0
        let fm = FileManager.default
        for dir in dirs {
            let url = URL(fileURLWithPath: dir)
            if noRecursive {
                guard let contents = try? fm.contentsOfDirectory(
                    at: url, includingPropertiesForKeys: [.isRegularFileKey],
                    options: [.skipsHiddenFiles]
                ) else { continue }
                for fileURL in contents {
                    if Task.isCancelled { return count }
                    let ext = fileURL.pathExtension.lowercased()
                    if exts.contains(ext) { count += 1 }
                }
            } else {
                guard let enumerator = fm.enumerator(
                    at: url,
                    includingPropertiesForKeys: [.isRegularFileKey],
                    options: [.skipsHiddenFiles]
                ) else { continue }
                while let fileURL = enumerator.nextObject() as? URL {
                    if Task.isCancelled { return count }
                    let ext = fileURL.pathExtension.lowercased()
                    if exts.contains(ext) { count += 1 }
                }
            }
        }
        return count
    }

    nonisolated private static func defaultExtensions(for mode: ScanMode) -> Set<String> {
        switch mode {
        case .video: ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "ts", "3gp"]
        case .image: ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "heic", "heif", "avif"]
        case .audio: ["mp3", "flac", "wav", "aac", "ogg", "m4a", "wma", "opus", "aiff", "alac"]
        case .document: ["pdf", "docx", "txt", "md"]
        case .auto:
            ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "ts", "3gp",
             "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "heic", "heif", "avif"]
        }
    }
}

// MARK: - Session Effect Execution

extension SessionStore {

    /// Execute a single session side effect.
    private func execute(_ effect: SessionEffect) {
        switch effect {

        // MARK: - Scan Effects

        case .runScan(let config):
            flushPendingSave()
            cancelPendingContinuations()
            executeScan(config: config)

        case .runPhotosScan(let scope, let config):
            flushPendingSave()
            cancelPendingContinuations()
            executePhotosScan(scope: scope, config: config)

        case .loadReplayData(let url):
            flushPendingSave()
            cancelPendingContinuations()
            executeLoadReplay(url: url)

        case .cancelCLI:
            cancelPendingContinuations()
            scanTask?.cancel()
            Task { await bridge.cancelCurrentTask() }

        case .sendPauseSignal:
            CLIBridge.sendPauseSignal()

        case .sendResumeSignal:
            CLIBridge.sendResumeSignal()

        case .writePauseCommand(let url, let command):
            CLIBridge.writePauseCommand(command, to: url)

        case .removePauseFile(let url):
            CLIBridge.removePauseFile(at: url)

        case .schedulePauseTimeout(let duration):
            pauseTimeoutTask?.cancel()
            pauseTimeoutTask = Task {
                try? await Task.sleep(for: .seconds(duration))
                guard !Task.isCancelled else { return }
                self.send(.pauseTimeoutFired)
            }

        case .cancelPauseTimeout:
            pauseTimeoutTask?.cancel()
            pauseTimeoutTask = nil

        case .configureResults(let envelope, let rawData, let config, let priorEnvelope):
            let gen = scanGeneration
            Task {
                await self.configureResults(
                    envelope: envelope, rawData: rawData,
                    config: config, priorOriginalEnvelope: priorEnvelope,
                    generation: gen
                )
            }

        case .scheduleMinimumDisplay(let startTime):
            minimumDisplayTask?.cancel()
            let remaining = Self.minimumDisplayDelay(start: startTime ?? Date())
            if remaining > 0 {
                minimumDisplayTask = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(remaining))
                    guard !Task.isCancelled else { return }
                    self?.send(.minimumDisplayElapsed)
                }
            } else {
                send(.minimumDisplayElapsed)
            }

        case .cleanupTempReplayFile(let url):
            let tempPrefix = FileManager.default.temporaryDirectory
                .appendingPathComponent("DuplicatesDetector", isDirectory: true).path
            if url.path.hasPrefix(tempPrefix) {
                try? FileManager.default.removeItem(at: url)
            }

        // MARK: - File Action Effects

        case .performFileAction(let type, let path, let pairID):
            executeFileAction(type: type, path: path, pairID: pairID)

        case .executeBulk(let candidates):
            executeBulkAction(candidates: candidates)

        case .addToIgnoreList(let fileA, let fileB, let url):
            let filePath = url
            let pairID = PairIdentifier(fileA: fileA, fileB: fileB)
            Task {
                do {
                    try await IgnoreListManager.shared.addPair(fileA, fileB, to: filePath)
                } catch {
                    diagLog.warning("Failed to add pair to ignore list: \(error.localizedDescription, privacy: .public)")
                    await MainActor.run { [weak self] in self?.send(._rollbackIgnore(pairID)) }
                }
            }

        case .removeFromIgnoreList(let fileA, let fileB, let url, let removedPairs):
            let filePath = url
            Task {
                do {
                    try await IgnoreListManager.shared.removePair(fileA, fileB, from: filePath)
                } catch {
                    diagLog.warning("Failed to remove pair from ignore list: \(error.localizedDescription, privacy: .public)")
                    await MainActor.run { [weak self] in self?.send(._rollbackUnignore(removedPairs)) }
                }
            }

        case .clearIgnoreList(let snapshot, let url):
            let filePath = url
            Task {
                do {
                    try await IgnoreListManager.shared.clearAll(at: filePath)
                } catch {
                    diagLog.warning("Failed to clear ignore list: \(error.localizedDescription, privacy: .public)")
                    await MainActor.run { [weak self] in self?.send(._rollbackClearIgnored(snapshot)) }
                }
            }

        // MARK: - Watch Effects

        case .startWatch(let config, let knownFiles):
            executeStartWatch(config: config, knownFiles: knownFiles)

        case .stopWatch:
            executeStopWatch()

        // MARK: - Filesystem Monitor Effects

        case .startFileMonitor(let paths):
            if let existing = fileMonitor {
                fileMonitor = nil
                Task { await existing.stop() }
            }
            let monitor = FileStatusMonitor { [weak self] changes in
                await MainActor.run {
                    guard let self else { return }
                    var updates: [String: FileStatus] = [:]
                    for change in changes {
                        switch change {
                        case .disappeared(let path):
                            updates[path] = .missing
                        case .appeared(let path):
                            updates[path] = .present
                        case .moved(let from, let to):
                            updates[from] = .moved(to: to)
                            // Surface destination as present so clearStaleMissingResolutions
                            // can reactivate pairs if a file returns to a tracked path.
                            updates[to] = .present
                        }
                    }
                    if !updates.isEmpty {
                        self.send(.watchFileBatchChanged(updates))
                    }
                }
            }
            fileMonitor = monitor
            Task { await monitor.start(paths: paths) }

        case .expandFileMonitor(let paths):
            if let monitor = fileMonitor {
                Task { await monitor.addPaths(paths) }
            }

        case .stopFileMonitor:
            if let monitor = fileMonitor {
                fileMonitor = nil
                Task { await monitor.stop() }
            }

        case .checkFileStatuses(let paths):
            if let monitor = fileMonitor {
                Task { [weak self] in
                    let statuses = await monitor.checkStatuses()
                    await MainActor.run {
                        self?.send(.fileStatusChecked(statuses))
                    }
                }
            } else {
                // No monitor — do a one-time check inline
                var statuses: [String: FileStatus] = [:]
                for path in paths {
                    statuses[path] = FileManager.default.fileExists(atPath: path) ? .present : .missing
                }
                send(.fileStatusChecked(statuses))
            }

        // MARK: - Persistence Effects

        case .saveSession:
            let persisted = session.persisted()
            // Use original bytes when available; re-encode if the envelope was
            // mutated (e.g., pair-mode watch alerts) and the cache was invalidated.
            let envelopeData: Data? = session.lastOriginalEnvelope ?? {
                guard let envelope = session.results?.envelope else { return nil }
                let encoder = JSONEncoder()
                encoder.keyEncodingStrategy = .convertToSnakeCase
                return try? encoder.encode(envelope)
            }()
            saveSessionTask?.cancel()
            saveSessionTask = Task { [weak self, registry] in
                guard let persisted, !Task.isCancelled else { return }
                do {
                    try await registry.saveSession(persisted, envelopeData: envelopeData)
                } catch {
                    guard !Task.isCancelled else { return }
                    diagLog.warning("Failed to save session: \(error.localizedDescription, privacy: .public)")
                }
                self?.saveSessionTask = nil
            }

        case .saveSessionDebounced:
            saveDebounceTask?.cancel()
            saveDebounceTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                self?.execute(.saveSession)
            }

        case .loadSession(let id):
            flushPendingSave()
            cancelPendingContinuations()
            restoreGeneration &+= 1
            let expectedGeneration = restoreGeneration
            Task { [weak self, registry] in
                do {
                    let persisted = try await registry.loadSession(id)
                    let envelopeData = try? await registry.loadEnvelopeData(id)
                    await MainActor.run {
                        guard let self, self.restoreGeneration == expectedGeneration else { return }
                        self.send(.sessionLoaded(persisted, envelopeData))
                    }
                } catch {
                    diagLog.warning("Failed to load session \(id): \(error.localizedDescription, privacy: .public)")
                }
            }

        case .deleteSession(let id):
            Task { [registry] in
                do {
                    try await registry.deleteSession(id)
                } catch {
                    diagLog.warning("Failed to delete session \(id): \(error.localizedDescription, privacy: .public)")
                }
            }

        case .deleteCliSession(let sessionId):
            Task { [bridge] in
                await bridge.deleteSession(sessionId)
            }

        case .pruneOldSessions(let count):
            Task { [registry] in
                do {
                    try await registry.pruneOldSessions(keep: count)
                } catch {
                    diagLog.warning("Failed to prune sessions: \(error.localizedDescription, privacy: .public)")
                }
            }

        case .exportSession(let id, let url, let format):
            executeExportSession(id: id, url: url, format: format)

        // MARK: - Cached Views

        case .rebuildSynthesizedViews:
            rebuildSynthesizedViewsIfNeeded()

        // MARK: - Navigation

        case .activateWindow:
            // Use the callback wired by the SwiftUI scene body — it calls
            // openWindow(id:) which brings an existing window to front or
            // recreates it when the user closed it (e.g. during watch mode).
            if let activate = onActivateMainWindow {
                activate()
            } else {
                NSApp.activate()
            }

        case .persistSessionId(let id):
            if let id {
                UserDefaults.standard.set(id, forKey: Self.pausedSessionDefaultsKey)
            } else {
                UserDefaults.standard.removeObject(forKey: Self.pausedSessionDefaultsKey)
            }

        // MARK: - Action Log

        case .writeActionLog(let record):
            guard let logPath = session.lastScanConfig?.log, !logPath.isEmpty else { break }
            let writer = ActionLogWriter(logPath: logPath)
            // Photos URIs must not be passed through URL(fileURLWithPath:) which
            // treats the scheme as a relative path component, mangling the URI.
            let isPhotosAction = record.actedOnPath.isPhotosAssetURI
            let resolvedPath = isPhotosAction
                ? record.actedOnPath
                : URL(fileURLWithPath: record.actedOnPath).resolvingSymlinksInPath().path
            let resolvedKept: String? = record.keptPath.isEmpty
                ? nil
                : (record.keptPath.isPhotosAssetURI
                    ? record.keptPath
                    : URL(fileURLWithPath: record.keptPath).resolvingSymlinksInPath().path)
            let logTask = Task {
                let error: String?
                if isPhotosAction {
                    error = await writer.logPhotosTrash(
                        assetID: record.actedOnPath.photosAssetID ?? record.actedOnPath,
                        filename: record.actedOnPath.displayFileName,
                        score: Double(record.score),
                        kept: resolvedKept ?? ""
                    )
                } else {
                    error = await writer.appendRecord(ActionLogRecord(
                        action: record.action,
                        path: resolvedPath,
                        score: Double(record.score),
                        strategy: record.strategy,
                        kept: resolvedKept,
                        bytesFreed: record.bytesFreed ?? 0,
                        destination: record.destination
                    ))
                }
                if let error {
                    diagLog.warning("Action log write failed: \(error)")
                }
            }
            trackActionTask(logTask)
        }
    }
}

// MARK: - Scan Execution

extension SessionStore {

    /// Launch a CLI scan subprocess and drive the stream.
    private func executeScan(config: SessionConfig) {
        scanTask?.cancel()
        minimumDisplayTask?.cancel()
        minimumDisplayTask = nil
        scanGeneration &+= 1
        let gen = scanGeneration

        // Create pause file and inject into config
        let pauseURL = CLIBridge.createPauseFile()
        // Update session scan state with pause file URL (via reducer)
        send(.setPauseFile(pauseURL))

        var scanConfig = config
        scanConfig.pauseFile = pauseURL.path

        #if DEBUG
        diagLog.notice("[runScan] gen=\(gen), launching CLI task")
        #endif

        scanTask = Task {
            do {
                let stream = await bridge.runScan(config: scanConfig)
                var eventCount = 0
                for try await output in stream {
                    guard self.scanGeneration == gen else {
                        #if DEBUG
                        diagLog.error("[runScan] STALE gen=\(gen) vs current=\(self.scanGeneration), dropping")
                        #endif
                        return
                    }
                    eventCount += 1
                    switch output {
                    case .progress(let event):
                        if let action = event.toSessionAction() {
                            self.send(action)
                        }
                    case .result(let envelope, let rawData):
                        #if DEBUG
                        let evtCount = eventCount
                        diagLog.notice("[runScan] gen=\(gen), received .result after \(evtCount) events")
                        #endif
                        self.send(.cliStreamCompleted(envelope, rawData))
                    }
                }
                // Stream ended normally — only act if this scan generation is still current
                // and the scan hasn't already produced results (scan is nil after .minimumDisplayElapsed)
                guard self.scanGeneration == gen else { return }
                if self.session.scan?.isCancelling == true {
                    self.send(.cliStreamCancelled)
                } else if self.session.scan != nil, self.session.scan?.isFinalizingResults != true {
                    self.send(.cliStreamCompleted(nil, nil))
                }
            } catch is CancellationError {
                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamCancelled)
            } catch {
                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamFailed(ErrorInfo.classify(error)))
            }
            if self.scanGeneration == gen { self.scanTask = nil }
        }
    }

    /// Launch a PhotoKit scan and drive progress through the session state machine.
    private func executePhotosScan(scope: PhotosScope, config: SessionConfig) {
        #if DEBUG
        if ProcessInfo.processInfo.environment["DD_UI_TEST_MOCK"] != nil {
            executePhotosTestScan(scope: scope, config: config)
            return
        }
        #endif

        scanTask?.cancel()
        minimumDisplayTask?.cancel()
        minimumDisplayTask = nil
        scanGeneration &+= 1
        let gen = scanGeneration
        let formatter = Self.iso8601Formatter

        #if DEBUG
        diagLog.notice("[runPhotosScan] gen=\(gen), launching PhotoKit task")
        #endif

        scanTask = Task {
            // Stage 1: Authorize
            let authorizeStart = Date()
            self.send(.cliStageStart(StageStartEvent(
                stage: "authorize", timestamp: formatter.string(from: authorizeStart)
            )))

            let status = await PhotoKitBridge.shared.requestAuthorization()
            guard self.scanGeneration == gen else { return }

            let authorizeElapsed = Date().timeIntervalSince(authorizeStart)
            self.send(.cliStageEnd(StageEndEvent(
                stage: "authorize", total: 1, elapsed: authorizeElapsed,
                timestamp: formatter.string(from: Date())
            )))

            switch status {
            case .authorized:
                break
            case .limited:
                self.send(.photosAuthorizationLimited)
            case .denied:
                self.send(.cliStreamFailed(ErrorInfo.classify(PhotoKitError.authorizationDenied)))
                if self.scanGeneration == gen { self.scanTask = nil }
                return
            case .restricted:
                self.send(.cliStreamFailed(ErrorInfo.classify(PhotoKitError.authorizationRestricted)))
                if self.scanGeneration == gen { self.scanTask = nil }
                return
            default:
                self.send(.cliStreamFailed(ErrorInfo.classify(PhotoKitError.authorizationDenied)))
                if self.scanGeneration == gen { self.scanTask = nil }
                return
            }

            // Stage 2 & 3: Extract metadata + Score (via bridge)
            do {
                await PhotosCacheDB.shared.resetStats()

                let extractStart = Date()
                self.send(.cliStageStart(StageStartEvent(
                    stage: "extract", timestamp: formatter.string(from: extractStart)
                )))

                // Load cached metadata before extraction
                let cachedRaw = await PhotosCacheDB.shared.getAllCachedMetadata()
                let cachedMetadata: [String: (modDate: Date, metadata: PhotoAssetMetadata)] =
                    cachedRaw.mapValues { ($0.modDate, $0.metadata) }

                // Extract metadata off the main thread — fetchAssets is synchronous
                // and enumerates every PHAsset in the library.
                let parentTaskForExtract = self.scanTask
                let extractTask = Task.detached {
                    try PhotoKitBridge.fetchAssets(
                        scope: scope,
                        cachedMetadata: cachedMetadata,
                        isCancelled: {
                            parentTaskForExtract?.isCancelled ?? false
                        }
                    ) { event in
                        Task { @MainActor in
                            guard self.scanGeneration == gen else { return }
                            if let action = event.toSessionAction() {
                                self.send(action)
                            }
                        }
                    }
                }
                let assets: [PhotoAssetMetadata]
                var extractICloudSkipped = 0
                do {
                    let (fetchedAssets, newEntries, iCloudSkipped) = try await extractTask.value
                    assets = fetchedAssets
                    extractICloudSkipped = iCloudSkipped

                    // Write new metadata entries to cache
                    if !newEntries.isEmpty {
                        await PhotosCacheDB.shared.putMetadataBatch(
                            newEntries.map { (assetID: $0.0, modDate: $0.1, metadata: $0.2) }
                        )
                    }

                    // Prune stale cache entries for full-library scans.
                    // Skip when cancelled — partial enumeration would incorrectly
                    // prune entries for assets not yet visited.
                    if scope == .fullLibrary, parentTaskForExtract?.isCancelled != true {
                        let activeIDs = Set(assets.map(\.id))
                        await PhotosCacheDB.shared.prune(activeAssetIDs: activeIDs)
                    }
                } catch is CancellationError {
                    extractTask.cancel()
                    throw CancellationError()
                }
                guard self.scanGeneration == gen else { return }

                let extractElapsed = Date().timeIntervalSince(extractStart)
                let extractStats = await PhotosCacheDB.shared.stats()
                self.send(.cliStageEnd(StageEndEvent(
                    stage: "extract", total: assets.count, elapsed: extractElapsed,
                    timestamp: formatter.string(from: Date()),
                    cacheHits: extractStats.metadataHits,
                    cacheMisses: extractStats.metadataMisses,
                    extras: extractICloudSkipped > 0 ? ["iCloudSkipped": extractICloudSkipped] : [:]
                )))

                try Task.checkCancellation()
                guard PhotoKitBridge.isStillAuthorized() else {
                    self.send(.photosAuthRevoked)
                    if self.scanGeneration == gen { self.scanTask = nil }
                    return
                }

                // Filter stage (pass-through — all assets pass)
                let filterStart = Date()
                self.send(.cliStageStart(StageStartEvent(
                    stage: "filter", timestamp: formatter.string(from: filterStart)
                )))
                self.send(.cliStageEnd(StageEndEvent(
                    stage: "filter", total: assets.count,
                    elapsed: Date().timeIntervalSince(filterStart),
                    timestamp: formatter.string(from: Date())
                )))

                try Task.checkCancellation()
                guard PhotoKitBridge.isStillAuthorized() else {
                    self.send(.photosAuthRevoked)
                    if self.scanGeneration == gen { self.scanTask = nil }
                    return
                }

                // Score off the main thread — O(n²) comparisons.
                let scoreStart = Date()
                self.send(.cliStageStart(StageStartEvent(
                    stage: "score", timestamp: formatter.string(from: scoreStart)
                )))

                let threshold = config.threshold
                let weights: [(String, Double)]? = config.weights.map { dict in
                    dict.map { ($0.key, $0.value) }
                }

                // Load cached scored pairs — fast key-only scan, then selective decode.
                // Use the same fallback chain as fetchAssets/putScoredPairsBulk so
                // assets with nil modificationDate still hit the scored-pair cache.
                let assetModDates: [String: Date] = Dictionary(
                    uniqueKeysWithValues: assets.map { asset in
                        (asset.id, asset.modificationDate ?? asset.creationDate ?? Date.distantPast)
                    }
                )
                let imageConfigHash = PhotosScorer.configHash(weights: weights, isVideo: false)
                let videoConfigHash = PhotosScorer.configHash(weights: weights, isVideo: true)
                let cachedImage = await PhotosCacheDB.shared.getCachedScoringData(
                    configHash: imageConfigHash, assetModDates: assetModDates,
                    threshold: threshold
                )
                let cachedVideo = await PhotosCacheDB.shared.getCachedScoringData(
                    configHash: videoConfigHash, assetModDates: assetModDates,
                    threshold: threshold
                )
                let allCachedPairs = cachedImage.pairs + cachedVideo.pairs
                let cachedPairKeys = cachedImage.keys.union(cachedVideo.keys)

                // Capture the parent task so the scorer can check cancellation.
                let parentTask = self.scanTask
                let scoreTask = Task.detached {
                    PhotosScorer.score(
                        assets, threshold: threshold, weights: weights,
                        cachedPairs: allCachedPairs.isEmpty ? nil : allCachedPairs,
                        cachedPairKeys: cachedPairKeys.isEmpty ? nil : cachedPairKeys
                    ) { progress in
                        let ts = ISO8601DateFormatter().string(from: Date())
                        Task { @MainActor in
                            guard self.scanGeneration == gen else { return }
                            self.send(.cliProgress(StageProgressEvent(
                                stage: "score", current: progress.current,
                                timestamp: ts, total: progress.total,
                                file: nil, rate: progress.rate,
                                cacheHits: progress.cacheHits,
                                cacheMisses: progress.cacheMisses
                            )))
                        }
                    } isCancelled: {
                        parentTask?.isCancelled ?? false
                    }
                }
                let scorerResult = await scoreTask.value
                let scoredPairs = scorerResult.pairs
                guard self.scanGeneration == gen else { return }

                let scoreElapsed = Date().timeIntervalSince(scoreStart)
                let scoreStats = await PhotosCacheDB.shared.stats()
                self.send(.cliStageEnd(StageEndEvent(
                    stage: "score", total: scorerResult.totalComparisons, elapsed: scoreElapsed,
                    timestamp: formatter.string(from: Date()),
                    cacheHits: scoreStats.scoredPairHits,
                    cacheMisses: scoreStats.scoredPairMisses,
                    extras: ["pairs_found": scoredPairs.count]
                )))

                // Build asset lookup for metadata
                let assetLookup = Dictionary(uniqueKeysWithValues: assets.map { ($0.id, $0) })

                // Write ALL newly evaluated pairs to cache (including below-threshold)
                // so they are skipped on the next scan, not just above-threshold results.
                // When cancelled, write in the background so the UI transitions immediately.
                let newPairs = scorerResult.allEvaluated
                let newImagePairs = newPairs.filter { assetLookup[$0.assetA]?.isImage == true }
                let newVideoPairs = newPairs.filter { assetLookup[$0.assetA]?.isVideo == true }

                let isCancelled = Task.isCancelled
                let writeCacheBlock: @Sendable () async -> Void = {
                    if !newImagePairs.isEmpty {
                        await PhotosCacheDB.shared.putScoredPairsBulk(
                            newImagePairs.map { pair in
                                (pair: pair,
                                 modDateA: assetModDates[pair.assetA] ?? Date.distantPast,
                                 modDateB: assetModDates[pair.assetB] ?? Date.distantPast)
                            },
                            configHash: imageConfigHash
                        )
                    }
                    if !newVideoPairs.isEmpty {
                        await PhotosCacheDB.shared.putScoredPairsBulk(
                            newVideoPairs.map { pair in
                                (pair: pair,
                                 modDateA: assetModDates[pair.assetA] ?? Date.distantPast,
                                 modDateB: assetModDates[pair.assetB] ?? Date.distantPast)
                            },
                            configHash: videoConfigHash
                        )
                    }
                }

                if isCancelled {
                    // Fire-and-forget: write cache in background, don't block UI
                    Task.detached { await writeCacheBlock() }
                    throw CancellationError()
                } else {
                    await writeCacheBlock()
                }

                guard PhotoKitBridge.isStillAuthorized() else {
                    self.send(.photosAuthRevoked)
                    if self.scanGeneration == gen { self.scanTask = nil }
                    return
                }

                // Report stage: build envelope and encode
                let reportStart = Date()
                self.send(.cliStageStart(StageStartEvent(
                    stage: "report", timestamp: formatter.string(from: reportStart)
                )))

                // Filter out pairs where either asset has been offloaded to iCloud
                // since the cache was populated. This runs on the small set of paired
                // asset IDs (not the full library), so PHAssetResource cost is bounded.
                let pairedAssetIDs = Set(scoredPairs.flatMap { [$0.assetA, $0.assetB] })
                let offloaded = await PhotoKitBridge.shared.filterOffloadedAssets(pairedAssetIDs)
                let filteredPairs = offloaded.isEmpty
                    ? scoredPairs
                    : scoredPairs.filter { !offloaded.contains($0.assetA) && !offloaded.contains($0.assetB) }

                // Convert scored pairs to PairResults
                let keepStrategy = config.keep?.rawValue
                let pairResults: [PairResult] = filteredPairs.compactMap { scored in
                    guard let metaA = assetLookup[scored.assetA],
                          let metaB = assetLookup[scored.assetB]
                    else { return nil }

                    let detail: [String: DetailScore] = scored.detail.reduce(into: [:]) { dict, entry in
                        dict[entry.key] = DetailScore(raw: entry.value.raw, weight: entry.value.weight)
                    }

                    let uriA = metaA.photosURI
                    let uriB = metaB.photosURI
                    let fmA = metaA.toFileMetadata()
                    let fmB = metaB.toFileMetadata()

                    // Resolve keep annotation using the same logic as CLI pick_keep.
                    let keep: String? = keepStrategy.flatMap { strategy in
                        let files = [
                            GroupFile(path: uriA, duration: fmA.duration, width: fmA.width,
                                      height: fmA.height, fileSize: fmA.fileSize, codec: nil,
                                      bitrate: nil, framerate: nil, audioChannels: nil,
                                      mtime: fmA.mtime, tagTitle: nil, tagArtist: nil,
                                      tagAlbum: nil, isReference: false, thumbnail: nil),
                            GroupFile(path: uriB, duration: fmB.duration, width: fmB.width,
                                      height: fmB.height, fileSize: fmB.fileSize, codec: nil,
                                      bitrate: nil, framerate: nil, audioChannels: nil,
                                      mtime: fmB.mtime, tagTitle: nil, tagArtist: nil,
                                      tagAlbum: nil, isReference: false, thumbnail: nil),
                        ]
                        guard let keepPath = ResultsSnapshot.pickKeepFromGroup(
                            files: files, strategy: strategy
                        ) else { return nil }
                        return keepPath == uriA ? "a" : "b"
                    }

                    return PairResult(
                        fileA: uriA,
                        fileB: uriB,
                        score: Double(scored.score),
                        breakdown: scored.breakdown.mapValues { Optional($0) },
                        detail: detail,
                        fileAMetadata: fmA,
                        fileBMetadata: fmB,
                        fileAIsReference: false,
                        fileBIsReference: false,
                        keep: keep
                    )
                }

                let totalElapsed = Date().timeIntervalSince(extractStart)

                // Build envelope
                let envelope = ScanEnvelope(
                    version: "1.0",
                    generatedAt: formatter.string(from: Date()),
                    args: ScanArgs(
                        directories: [], threshold: config.threshold,
                        content: false, weights: nil,
                        keep: config.keep?.rawValue, action: config.action.rawValue,
                        group: false, sort: config.sort.rawValue,
                        mode: "auto", embedThumbnails: false
                    ),
                    stats: ScanStats(
                        filesScanned: assets.count,
                        filesAfterFilter: assets.count,
                        totalPairsScored: scorerResult.totalComparisons,
                        pairsAboveThreshold: pairResults.count,
                        scanTime: extractElapsed,
                        extractTime: 0,
                        filterTime: 0,
                        contentHashTime: 0,
                        scoringTime: scoreElapsed,
                        totalTime: totalElapsed
                    ),
                    content: .pairs(pairResults)
                )

                // Encode envelope as raw data for export
                let encoder = JSONEncoder()
                encoder.keyEncodingStrategy = .convertToSnakeCase
                let rawData = try? encoder.encode(envelope)

                self.send(.cliStageEnd(StageEndEvent(
                    stage: "report", total: pairResults.count,
                    elapsed: Date().timeIntervalSince(reportStart),
                    timestamp: formatter.string(from: Date())
                )))

                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamCompleted(envelope, rawData))

            } catch is CancellationError {
                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamCancelled)
            } catch {
                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamFailed(ErrorInfo.classify(error)))
            }

            if self.scanGeneration == gen { self.scanTask = nil }
        }
    }

    /// Load a replay file and dispatch the appropriate actions.
    private func executeLoadReplay(url: URL) {
        scanTask?.cancel()
        scanGeneration &+= 1
        let replayGen = scanGeneration
        let setupConfig = session.config ?? SessionConfig()

        scanTask = Task {
            let (originalData, config) = await Task.detached {
                let data = try? Data(contentsOf: url)
                var cfg = setupConfig
                cfg.replayPath = url.path
                cfg.dryRun = false  // replay is never dry-run
                if let data {
                    Self.seedConfigFromEnvelope(&cfg, data: data)
                }
                return (data, cfg)
            }.value
            guard self.scanGeneration == replayGen else { return }
            guard !Task.isCancelled else {
                self.send(.cliStreamCancelled)
                return
            }
            // Update config via reducer and dispatch to run the replay scan
            self.send(.configureReplay(config, originalData))
            // Drive the replay through the bridge
            self.executeScan(config: config)
        }
    }

    /// Build a `ResultsSnapshot` from a completed scan.
    private func configureResults(
        envelope: ScanEnvelope?,
        rawData: Data?,
        config: ScanConfig,
        priorOriginalEnvelope: Data?,
        generation: UInt
    ) async {
        // 1. Build initial ResultsSnapshot
        let snapshot: ResultsSnapshot

        if let envelope {
            snapshot = ResultsSnapshot(
                envelope: envelope,
                isDryRun: config.dryRun,
                hasKeepStrategy: envelope.args.keep != nil
            )
        } else {
            // Zero-result scan — build empty snapshot with metrics from progress stages
            let stageResults: [(stage: PipelineStage, elapsed: Double, total: Int)] =
                (session.scan?.stages ?? []).compactMap { stage in
                    if case .completed(let elapsed, let total, _) = stage.status {
                        return (stage: stage.id, elapsed: elapsed, total: total)
                    }
                    return nil
                }
            let totalElapsed = session.scan?.timing.completedElapsed ?? 0
            let emptyEnvelope = ScanEnvelope(
                version: "1.0",
                generatedAt: "",
                args: ScanArgs(
                    directories: config.directories, threshold: config.threshold,
                    content: config.content, weights: nil,
                    keep: config.keep?.rawValue, action: config.action.rawValue,
                    group: config.group, sort: config.sort.rawValue,
                    mode: config.mode.rawValue, embedThumbnails: config.embedThumbnails
                ),
                stats: ScanStats(
                    filesScanned: stageResults.first { $0.stage == .scan }?.total ?? 0,
                    filesAfterFilter: stageResults.first { $0.stage == .filter }?.total
                        ?? stageResults.first { $0.stage == .extract }?.total ?? 0,
                    totalPairsScored: stageResults.first { $0.stage == .score }?.total ?? 0,
                    pairsAboveThreshold: 0,
                    groupsCount: config.group ? 0 : nil, spaceRecoverable: nil,
                    scanTime: stageResults.first { $0.stage == .scan }?.elapsed ?? 0,
                    extractTime: stageResults.first { $0.stage == .extract }?.elapsed ?? 0,
                    filterTime: stageResults.first { $0.stage == .filter }?.elapsed ?? 0,
                    contentHashTime: stageResults.first { $0.stage == .contentHash }?.elapsed ?? 0,
                    scoringTime: stageResults.first { $0.stage == .score }?.elapsed ?? 0,
                    totalTime: totalElapsed
                ),
                content: config.group ? .groups([]) : .pairs([]),
                dryRunSummary: nil
            )
            snapshot = ResultsSnapshot(
                envelope: emptyEnvelope,
                isDryRun: config.dryRun,
                hasKeepStrategy: false
            )
        }

        // Abandon if a newer scan started
        guard scanGeneration == generation else { return }

        // Build display config — the reducer applies this atomically with the
        // results snapshot, eliminating the former direct session mutations.
        let activeAction: ActionType
        if config.action == .delete && !config.actionExplicitlySet {
            activeAction = .trash
        } else if config.action == .moveTo && config.scanSource != .directory {
            // Move To is not supported for Photos Library assets — normalize to trash.
            activeAction = .trash
        } else {
            activeAction = config.action
        }
        let displayConfig = ResultsDisplayConfig(
            activeAction: activeAction,
            moveDestination: config.moveToDir.map { URL(fileURLWithPath: $0) },
            rawEnvelopeData: rawData
        )

        send(.resultsReady(snapshot, displayConfig))
    }

    /// Compute the delay needed to meet the minimum display duration.
    nonisolated static func minimumDisplayDelay(
        start: Date, now: Date = Date(), minimumDuration: TimeInterval = minimumDisplayDuration
    ) -> TimeInterval {
        max(0, minimumDuration - now.timeIntervalSince(start))
    }
}

// MARK: - File Action Execution

extension SessionStore {

    /// Execute a single file action (trash, delete, move).
    private func executeFileAction(type: ActionType, path: String, pairID: PairID) {
        let envelope = session.results?.envelope
        let dest = session.display.moveDestination
        let meta = buildFileActionMeta(pairID: pairID, dest: dest, envelope: envelope)

        let task = Task {
            do {
                // Capture file size before the operation (file may be removed after)
                let fileSize = Self.fileSizeAtPath(path)
                if path.isPhotosAssetURI {
                    try await Self.performPhotosAction(action: type, path: path)
                } else {
                    _ = try await Task.detached(priority: .userInitiated) {
                        try Self.performFileOperation(action: type, path: path, destination: dest)
                    }.value
                }
                guard !Task.isCancelled else { return }
                let affected = Self.findAffectedPairs(path: path, envelope: envelope)
                let finalMeta = FileActionMeta(
                    bytesFreed: fileSize, score: meta.score,
                    strategy: meta.strategy, destination: meta.destination
                )
                self.fileActionTasks.removeValue(forKey: pairID)
                self.send(.fileActionCompleted(pairID, type, path, affected, finalMeta))
                self.pendingActionContinuations.removeValue(forKey: pairID)?.resume(returning: true)
            } catch {
                guard !Task.isCancelled else { return }
                self.fileActionTasks.removeValue(forKey: pairID)
                self.send(.fileActionFailed(
                    pairID,
                    "Failed to \(type.displayName) \(path.displayFileName): \(error.localizedDescription)"
                ))
                self.pendingActionContinuations.removeValue(forKey: pairID)?.resume(returning: false)
            }
        }
        fileActionTasks[pairID] = task
    }

    /// Execute a bulk file action across multiple candidates.
    private func executeBulkAction(candidates: [BulkActionItem]) {
        // Compute real candidates from filtered views if the reducer passed empty
        let realCandidates: [BulkActionItem]
        if candidates.isEmpty {
            realCandidates = computeBulkCandidates()
        } else {
            realCandidates = candidates
        }

        guard !realCandidates.isEmpty else {
            send(.bulkFinished([]))
            return
        }

        // Set real candidate count through the reducer (no direct session mutation).
        send(.bulkStarted(realCandidates.count))

        let envelope = session.results?.envelope
        let dest = session.display.moveDestination

        // Build lookup tables once for the entire bulk operation instead of
        // calling synthesizePairs(from:) per item via findAffectedPairs/pairScore.
        let pathIndex = Self.buildPathToPairsIndex(envelope: envelope)
        let scoreIndex = Self.buildPairScoreIndex(envelope: envelope)
        let strategy = session.results?.envelope.args.keep
        let destPath = dest?.path

        bulkActionTask = Task {
            var failures: [String] = []

            // Partition into filesystem and Photos items so Photos assets
            // can be batched into a single deleteAssets() call (one system dialog).
            var photosItems: [BulkActionItem] = []
            var fsItems: [BulkActionItem] = []
            for item in realCandidates {
                if item.filePath.isPhotosAssetURI {
                    photosItems.append(item)
                } else {
                    fsItems.append(item)
                }
            }

            // Process filesystem items individually
            for item in fsItems {
                let pairID = item.pairID
                let path = item.filePath
                let actionType = item.action
                guard session.results?.bulkCancelled != true, !Task.isCancelled else { break }

                do {
                    let fileSize = Self.fileSizeAtPath(path)
                    _ = try await Task.detached(priority: .userInitiated) {
                        try Self.performFileOperation(action: actionType, path: path, destination: dest)
                    }.value
                    guard !Task.isCancelled else { break }
                    let affected = pathIndex[path] ?? []
                    let meta = FileActionMeta(
                        bytesFreed: fileSize, score: scoreIndex[pairID] ?? 0,
                        strategy: strategy, destination: destPath
                    )
                    self.send(.bulkItemCompleted(pairID, actionType, path, affected, meta))
                } catch {
                    guard !Task.isCancelled else { break }
                    failures.append(path)
                }
            }

            // Batch all Photos items into a single deleteAssets() call (one system dialog)
            if !photosItems.isEmpty,
               session.results?.bulkCancelled != true,
               !Task.isCancelled
            {
                let assetIDs = photosItems.compactMap { $0.filePath.photosAssetID }
                do {
                    try await PhotoKitBridge.shared.deleteAssets(assetIDs)
                    for item in photosItems {
                        guard !Task.isCancelled else { break }
                        let affected = pathIndex[item.filePath] ?? []
                        let meta = FileActionMeta(
                            bytesFreed: 0, score: scoreIndex[item.pairID] ?? 0,
                            strategy: strategy, destination: destPath
                        )
                        self.send(.bulkItemCompleted(
                            item.pairID, item.action, item.filePath, affected, meta
                        ))
                    }
                } catch {
                    for item in photosItems {
                        failures.append(item.filePath)
                    }
                }
            }

            guard !Task.isCancelled else { return }
            self.bulkActionTask = nil
            self.send(.bulkFinished(failures))
        }
    }

    /// Compute bulk action candidates from filtered views.
    private func computeBulkCandidates() -> [BulkActionItem] {
        let actionType = session.display.activeAction
        let isSelectMode = session.display.isSelectMode
        let selectedPairs = session.display.selectedForAction
        let selectedGroups = session.display.selectedGroupsForAction

        if session.display.viewMode == .pairs {
            return filteredPairs.compactMap { pair in
                let id = pair.pairIdentifier
                if isSelectMode {
                    guard selectedPairs.contains(id) else { return nil }
                }
                guard let results = session.results,
                      case .active = results.resolutionStatus(for: id) else { return nil }
                // Pick the file to act on based on keep strategy
                let pathToAct: String
                if pair.keep == "a" {
                    pathToAct = pair.fileB
                } else if pair.keep == "b" {
                    pathToAct = pair.fileA
                } else {
                    return nil  // No keep strategy — can't determine which file to act on
                }
                return BulkActionItem(pairID: id, filePath: pathToAct, action: actionType)
            }
        } else {
            // Groups mode — act on all non-keeper, non-reference files
            var candidates: [BulkActionItem] = []
            for group in filteredGroups {
                if isSelectMode {
                    guard selectedGroups.contains(group.groupId) else { continue }
                }
                for file in group.files {
                    if file.path == group.keep || file.isReference { continue }
                    if resolvedOrMissingPaths.contains(file.path) { continue }
                    let id = PairIdentifier(fileA: group.keep ?? "", fileB: file.path)
                    candidates.append(BulkActionItem(pairID: id, filePath: file.path, action: actionType))
                }
            }
            return candidates
        }
    }

    /// Find all pairs containing a given path.
    nonisolated static func findAffectedPairs(path: String, envelope: ScanEnvelope?) -> [PairIdentifier] {
        guard let envelope else { return [] }
        let allPairs: [PairResult]
        switch envelope.content {
        case .pairs(let p): allPairs = p
        case .groups(let g): allPairs = ResultsSnapshot.synthesizePairs(from: g)
        }
        return allPairs.compactMap { pair in
            guard pair.fileA == path || pair.fileB == path else { return nil }
            return PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
        }
    }

    /// Look up the score for a pair from the envelope.
    nonisolated private static func pairScore(for pairID: PairID, envelope: ScanEnvelope?) -> Int {
        guard let envelope else { return 0 }
        let allPairs: [PairResult]
        switch envelope.content {
        case .pairs(let p): allPairs = p
        case .groups(let g): allPairs = ResultsSnapshot.synthesizePairs(from: g)
        }
        let match = allPairs.first {
            ($0.fileA == pairID.fileA && $0.fileB == pairID.fileB) ||
            ($0.fileA == pairID.fileB && $0.fileB == pairID.fileA)
        }
        return Int(match?.score ?? 0)
    }

    /// Build a path → [PairIdentifier] index for O(1) lookups during bulk operations.
    nonisolated private static func buildPathToPairsIndex(envelope: ScanEnvelope?) -> [String: [PairIdentifier]] {
        guard let envelope else { return [:] }
        let allPairs: [PairResult]
        switch envelope.content {
        case .pairs(let p): allPairs = p
        case .groups(let g): allPairs = ResultsSnapshot.synthesizePairs(from: g)
        }
        var index: [String: [PairIdentifier]] = [:]
        for pair in allPairs {
            let id = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
            index[pair.fileA, default: []].append(id)
            index[pair.fileB, default: []].append(id)
        }
        return index
    }

    /// Build a PairID → score index for O(1) lookups during bulk operations.
    nonisolated private static func buildPairScoreIndex(envelope: ScanEnvelope?) -> [PairIdentifier: Int] {
        guard let envelope else { return [:] }
        let allPairs: [PairResult]
        switch envelope.content {
        case .pairs(let p): allPairs = p
        case .groups(let g): allPairs = ResultsSnapshot.synthesizePairs(from: g)
        }
        var index: [PairIdentifier: Int] = [:]
        for pair in allPairs {
            let id = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
            index[id] = Int(pair.score)
        }
        return index
    }

    /// Read file size (bytes) at a path, returning nil if the file doesn't exist.
    nonisolated private static func fileSizeAtPath(_ path: String) -> Int? {
        (try? FileManager.default.attributesOfItem(atPath: path)[.size] as? Int) ?? nil
    }

    /// Build a `FileActionMeta` with score, strategy, and destination from current state.
    private func buildFileActionMeta(
        pairID: PairID, dest: URL?, envelope: ScanEnvelope?
    ) -> FileActionMeta {
        FileActionMeta(
            bytesFreed: nil,
            score: Self.pairScore(for: pairID, envelope: envelope),
            strategy: session.results?.envelope.args.keep,
            destination: dest?.path
        )
    }

    /// Rebuild synthesized views (groups from pairs or pairs from groups) if needed.
    private func rebuildSynthesizedViewsIfNeeded() {
        guard session.results != nil else { return }

        if session.display.viewMode == .groups, session.results?.isPairMode == true {
            // Pairs data with groups view → synthesize groups.
            // Dispatch through reducer; recompute happens when the action is drained.
            let rawPairs = rawFilteredPairs()
            let groups = ResultsSnapshot.synthesizeGroups(
                from: rawPairs, keepStrategy: session.results?.envelope.args.keep
            )
            send(.updateSynthesizedViews(groups: groups, pairs: nil))
        } else if session.display.viewMode == .pairs, session.results?.isPairMode == false {
            // Groups data with pairs view → synthesize pairs.
            // Dispatch through reducer; recompute happens when the action is drained.
            let rawGroups = rawFilteredGroups()
            let pairs = ResultsSnapshot.synthesizePairs(from: rawGroups)
            send(.updateSynthesizedViews(groups: nil, pairs: pairs))
        } else {
            // No synthesis needed — still recompute cached views (e.g., resolution status changed).
            recomputeCachedViews()
        }
    }

    /// Delegate to shared `ResultsSnapshot.rawFilteredPairs(viewMode:)`.
    private func rawFilteredPairs() -> [PairResult] {
        session.results?.rawFilteredPairs(viewMode: session.display.viewMode) ?? []
    }

    /// Delegate to shared `ResultsSnapshot.rawFilteredGroups(viewMode:)`.
    private func rawFilteredGroups() -> [GroupResult] {
        session.results?.rawFilteredGroups(viewMode: session.display.viewMode) ?? []
    }

    // MARK: - Migrated Static Helpers (from ScanStore / ResultsStore)

    /// Extract replay-compatible fields from a saved envelope and apply them to a ScanConfig.
    nonisolated private static func seedConfigFromEnvelope(_ config: inout ScanConfig, data: Data) {
        guard let envelope = try? CLIDecoder.shared.decode(ScanEnvelope.self, from: data) else { return }
        let args = envelope.args

        config.keep = KeepStrategy(rawValue: args.keep ?? "")
        // Note: config.action is intentionally NOT restored from the envelope.
        // The GUI never sends --action to the CLI, so saved envelopes always
        // record the CLI default ("delete"). Overwriting from the envelope would
        // reset the user's GUI-side action choice. The caller's config.action
        // is the correct source of truth.
        config.sort = SortField(rawValue: args.sort) ?? .score
        config.limit = args.limit
        config.minScore = args.minScore
        config.group = args.group
        config.reference = args.reference ?? []
        config.embedThumbnails = args.embedThumbnails
        if let dims = args.thumbnailSize, dims.count == 2 {
            config.thumbnailSize = "\(dims[0])x\(dims[1])"
        }
    }

    /// Perform a single file operation off the main actor so that
    /// `FileManager` I/O does not block the UI.
    nonisolated static func performFileOperation(
        action: ActionType, path: String, destination: URL?
    ) throws -> (actionName: String, size: Int, destinationPath: String?) {
        let size = fileSizeAtPath(path) ?? 0
        switch action {
        case .trash:
            var resultingURL: NSURL?
            try FileManager.default.trashItem(at: URL(fileURLWithPath: path), resultingItemURL: &resultingURL)
            return ("trashed", size, (resultingURL as URL?)?.path)
        case .delete:
            try FileManager.default.removeItem(at: URL(fileURLWithPath: path))
            return ("deleted", size, nil)
        case .moveTo:
            guard let dest = destination else {
                throw CocoaError(.fileWriteUnknown, userInfo: [
                    NSLocalizedDescriptionKey: "No destination set",
                ])
            }
            try FileManager.default.createDirectory(at: dest, withIntermediateDirectories: true)
            let destURL = uniqueDestination(for: path, in: dest)
            try FileManager.default.moveItem(at: URL(fileURLWithPath: path), to: destURL)
            return ("moved", size, destURL.path)
        case .hardlink, .symlink, .reflink:
            throw CocoaError(.fileWriteUnknown, userInfo: [
                NSLocalizedDescriptionKey: "Action not supported in the GUI",
            ])
        }
    }

    /// Perform a file action on a Photos Library asset via PhotoKit.
    ///
    /// Trash and delete both move the asset to Recently Deleted (PhotoKit
    /// does not support immediate permanent deletion). Move is not supported.
    private static func performPhotosAction(action: ActionType, path: String) async throws {
        guard let assetID = path.photosAssetID else {
            throw CocoaError(.fileReadNoSuchFile, userInfo: [
                NSLocalizedDescriptionKey: "Invalid Photos asset URI: \(path)",
            ])
        }
        switch action {
        case .trash, .delete:
            try await PhotoKitBridge.shared.deleteAssets([assetID])
        case .moveTo, .hardlink, .symlink, .reflink:
            throw CocoaError(.fileWriteUnknown, userInfo: [
                NSLocalizedDescriptionKey: "\(action.displayName) is not supported for Photos Library assets",
            ])
        }
    }

    /// Compute a unique destination path without requiring actor isolation.
    nonisolated static func uniqueDestination(for sourcePath: String, in directory: URL) -> URL {
        let name = (sourcePath as NSString).lastPathComponent
        let stem = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var candidate = directory.appendingPathComponent(name)
        var counter = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            let newName = ext.isEmpty ? "\(stem) (\(counter))" : "\(stem) (\(counter)).\(ext)"
            candidate = directory.appendingPathComponent(newName)
            counter += 1
        }
        return candidate
    }
}

// MARK: - Watch Effect Execution

extension SessionStore {

    /// Start a background watch session with directory watcher and scan engine.
    ///
    /// **IMPORTANT — ordering constraint (recurring regression):**
    /// Menu bar activation, notification auth, and the stats timer MUST run
    /// before `buildInventory()`. The inventory crawl spawns ffprobe on every
    /// file in the watched directories and can take minutes on large libraries.
    /// If anything visible to the user is sequenced after the crawl, the watch
    /// will appear broken because the user sees no feedback. Keep the crawl as
    /// the LAST async step inside `watchStartupTask`.
    private func executeStartWatch(config: SessionConfig, knownFiles: [KnownFile]) {
        // Stop any existing watch first
        executeStopWatch()

        let directories = config.directories.map { URL(filePath: $0) }
        let sessionID = session.id

        watchStartupTask = Task {
            // Resolve shell environment for subprocess spawning
            let shellEnv = await resolveShellEnvironmentForSubprocess()
            guard !Task.isCancelled else { return }

            let watcher = DirectoryWatcher()
            let engine = BackgroundScanEngine(
                config: config,
                sessionID: sessionID,
                knownFiles: knownFiles,
                shellEnvironment: shellEnv
            )
            self.directoryWatcher = watcher
            self.backgroundEngine = engine

            // Start engine and watcher first so file events are captured
            // while the potentially slow inventory crawl runs.
            let alertStream = await engine.start()
            let extensions = DirectoryWatcher.extensionsForMode(config.mode)
            let eventStream = await watcher.start(
                directories: directories,
                latency: 1.0,
                extensions: extensions
            )
            guard !Task.isCancelled else {
                self.directoryWatcher = nil
                self.backgroundEngine = nil
                return
            }

            // Activate menu bar and notifications immediately — don't block
            // behind the potentially slow inventory crawl.
            await notificationManager.requestAuthorization()
            guard !Task.isCancelled else {
                self.directoryWatcher = nil
                self.backgroundEngine = nil
                return
            }

            if !self.menuBarManager.isActive {
                self.menuBarManager.onStopWatch = { [weak self] in
                    self?.send(.setWatchEnabled(false))
                }
                self.menuBarManager.onShowWindow = { [weak self] in
                    guard let self else { return }
                    if self.session.results != nil, self.session.phase != .results {
                        self.send(.openWatchNotification(self.session.id))
                    } else {
                        self.send(.activateWindow)
                    }
                }
                self.menuBarManager.activate()
            }

            // Start stats refresh timer
            self.watchStatsTimer = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(2))
                    guard !Task.isCancelled, let self else { break }
                    if let engine = self.backgroundEngine {
                        let stats = await engine.stats
                        self.menuBarManager.updateStats(
                            duplicates: stats.duplicatesFound,
                            trackedFiles: stats.trackedFiles
                        )
                    }
                }
            }

            // Bridge task: forward watcher events to engine and engine alerts
            // to notifications. Started before the inventory crawl so events
            // arriving during the crawl are ingested concurrently.
            self.watchBridgeTask = Task { [weak self] in
                await withTaskGroup(of: Void.self) { group in
                    // Forward file events to the engine
                    group.addTask {
                        for await event in eventStream {
                            guard !Task.isCancelled else { break }
                            await engine.ingest(event)
                        }
                    }

                    // Forward alerts to notification manager and state
                    group.addTask { [weak self] in
                        for await alert in alertStream {
                            guard !Task.isCancelled else { break }
                            guard let self else { break }
                            await MainActor.run {
                                self.send(.watchAlertReceived([alert.toPairResult()]))
                            }
                            await self.notificationManager.scheduleDuplicateAlert(alert)
                        }
                    }
                }
            }

            // Upgrade to full directory inventory now that watcher is live.
            // Events arriving during the crawl are forwarded to the engine
            // concurrently by the bridge task above.
            let fullInventory = await BackgroundScanEngine.buildInventory(
                directories: directories, mode: config.mode, environment: shellEnv
            )
            guard !Task.isCancelled else {
                self.directoryWatcher = nil
                self.backgroundEngine = nil
                return
            }
            await engine.mergeKnownFiles(fullInventory)
            await engine.markInventoryComplete()
        }
    }

    /// Stop the background watch session and clean up all watch infrastructure.
    private func executeStopWatch() {
        watchStartupTask?.cancel()
        watchStartupTask = nil

        watchBridgeTask?.cancel()
        watchBridgeTask = nil

        watchStatsTimer?.cancel()
        watchStatsTimer = nil

        if let watcher = directoryWatcher {
            directoryWatcher = nil
            Task { await watcher.stop() }
        }
        if let engine = backgroundEngine {
            backgroundEngine = nil
            Task { await engine.stop() }
        }

        Task { await notificationManager.flush() }
        menuBarManager.deactivate()
    }

    /// Resolve the user's login-shell PATH for subprocess spawning.
    private func resolveShellEnvironmentForSubprocess() async -> [String: String] {
        if let cached = cachedShellEnvironment { return cached }

        var env = ProcessInfo.processInfo.environment
        let provider = ProcessEnvironmentProvider()
        if let output = try? await provider.runLoginShell(command: "/usr/bin/printenv PATH") {
            let resolvedPath = output.trimmingCharacters(in: .whitespacesAndNewlines)
            if !resolvedPath.isEmpty {
                env["PATH"] = resolvedPath
            }
        }
        cachedShellEnvironment = env
        return env
    }
}

// MARK: - Export Effect Execution

extension SessionStore {

    /// Execute an export session operation.
    private func executeExportSession(id: UUID, url: URL, format: ExportFormat) {
        switch format {
        case .json:
            guard let data = session.lastOriginalEnvelope else {
                lastExportError = "No envelope data to export"
                return
            }
            Task {
                do {
                    try data.write(to: url, options: .atomic)
                } catch {
                    self.lastExportError = "Failed to export JSON: \(error.localizedDescription)"
                }
            }

        case .csv:
            guard session.results != nil else { return }
            let pairs = filteredPairs
            guard !pairs.isEmpty else { return }

            var csv = "file_a,file_b,score\n"
            for pair in pairs {
                let a = pair.fileA.replacingOccurrences(of: "\"", with: "\"\"")
                let b = pair.fileB.replacingOccurrences(of: "\"", with: "\"\"")
                csv += "\"\(a)\",\"\(b)\",\(pair.score)\n"
            }
            do {
                try csv.write(to: url, atomically: true, encoding: .utf8)
            } catch {
                lastExportError = "Failed to export CSV: \(error.localizedDescription)"
            }

        case .html, .shell:
            guard let cliFormat = format.cliFormatString else { return }
            guard let data = session.lastOriginalEnvelope else {
                lastExportError = "No envelope data for export"
                return
            }
            let config = session.lastScanConfig ?? SessionConfig()
            let isGroups = session.display.viewMode == .groups
            Task {
                do {
                    let tempDir = FileManager.default.temporaryDirectory
                        .appendingPathComponent("DuplicatesDetector", isDirectory: true)
                    try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
                    let replayURL = tempDir.appendingPathComponent("export-replay-\(UUID().uuidString).ddscan")
                    try data.write(to: replayURL, options: .atomic)

                    try await bridge.exportAsFormat(
                        envelopePath: replayURL.path,
                        format: cliFormat,
                        outputPath: url.path,
                        keep: config.keep?.rawValue,
                        embedThumbnails: false,
                        group: isGroups,
                        ignoreFile: config.ignoreFile
                    )

                    try? FileManager.default.removeItem(at: replayURL)
                } catch {
                    self.lastExportError = "Failed to export \(format.displayName): \(error.localizedDescription)"
                }
            }
        }
    }
}

// MARK: - Setup Binding Helper

extension SessionStore {

    /// Create a SwiftUI `Binding` that reads from `SetupState` and writes through `sendSetup`.
    func setupBinding<T: Equatable & Sendable>(
        _ keyPath: KeyPath<SetupState, T>,
        action: @escaping (T) -> SetupAction
    ) -> Binding<T> {
        Binding(
            get: { self.setupState[keyPath: keyPath] },
            set: { self.sendSetup(action($0)) }
        )
    }
}

// MARK: - Convenience Methods for Views

extension SessionStore {

    // MARK: Results Navigation

    /// The currently selected pair looked up from the cached filtered list.
    var selectedPair: PairResult? {
        guard let id = selectedPairID else { return nil }
        return filteredPairs.first { $0.pairIdentifier == id }
    }

    /// Total count of filtered pairs for "N of M" display.
    var totalFilteredPairs: Int { filteredPairs.count }

    /// Count of filtered pairs that are still actionable (not resolved or probably solved).
    var activePairsCount: Int {
        guard let results = session.results,
              results.effectivePairMode(for: session.display.viewMode) else { return 0 }
        return filteredPairs.filter { pair in
            if case .active = results.resolutionStatus(for: pair.pairIdentifier) { return true }
            return false
        }.count
    }

    // MARK: Group Helpers

    /// Count of resolved members in a group.
    func resolvedMemberCount(in group: GroupResult) -> Int {
        let candidates: [GroupFile]
        if let keepPath = group.keep {
            candidates = group.files.filter { $0.path != keepPath && !$0.isReference }
        } else {
            candidates = group.files.filter { !$0.isReference }
        }
        return candidates.filter { resolvedOrMissingPaths.contains($0.path) }.count
    }

    // MARK: File Operations (Finder, Clipboard)

    /// Reveal a file in Finder, or in Photos for Photos Library assets.
    func revealInFinder(_ path: String) {
        if path.isPhotosAssetURI, let assetID = path.photosAssetID {
            PhotoKitBridge.shared.revealInPhotos(assetID: assetID)
        } else {
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
        }
    }

    /// Open a file with the default app (Quick Look).
    func quickLook(_ path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    /// Copy a file path to the clipboard.
    func copyPath(_ path: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(path, forType: .string)
    }

    /// Copy two file paths to the clipboard (one per line).
    func copyPaths(_ pathA: String, _ pathB: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString("\(pathA)\n\(pathB)", forType: .string)
    }

    // MARK: Export

    /// Export the current results to CSV via NSSavePanel.
    func exportCSV() {
        if session.display.viewMode == .pairs {
            exportPairsCSV()
        } else {
            exportGroupsCSV()
        }
    }

    private func exportPairsCSV() {
        let pairs = filteredPairs
        guard !pairs.isEmpty else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "duplicates-results.csv"
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor in
                var csv = "file_a,file_b,score\n"
                for pair in pairs {
                    let a = pair.fileA.replacingOccurrences(of: "\"", with: "\"\"")
                    let b = pair.fileB.replacingOccurrences(of: "\"", with: "\"\"")
                    csv += "\"\(a)\",\"\(b)\",\(pair.score)\n"
                }
                do {
                    try csv.write(to: url, atomically: true, encoding: .utf8)
                } catch {
                    self.lastExportError = "Failed to export CSV: \(error.localizedDescription)"
                }
            }
        }
    }

    private func exportGroupsCSV() {
        let groups = filteredGroups
        guard !groups.isEmpty else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "duplicates-groups.csv"
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor in
                var csv = "group_id,file_path,file_size,is_keep,is_reference,duration,resolution\n"
                for group in groups {
                    let actionedPaths = self.session.results?.actionedPaths ?? []
                    for file in group.files where !actionedPaths.contains(file.path) {
                        let path = file.path.replacingOccurrences(of: "\"", with: "\"\"")
                        let isKeep = group.keep == file.path
                        let dur = file.duration.map { String(format: "%.1f", $0) } ?? ""
                        let res: String
                        if let w = file.width, let h = file.height {
                            res = "\(w)x\(h)"
                        } else {
                            res = ""
                        }
                        csv += "\(group.groupId),\"\(path)\",\(file.fileSize),\(isKeep),\(file.isReference),\(dur),\(res)\n"
                    }
                }
                do {
                    try csv.write(to: url, atomically: true, encoding: .utf8)
                } catch {
                    self.lastExportError = "Failed to export CSV: \(error.localizedDescription)"
                }
            }
        }
    }

    /// Write a replay-compatible JSON envelope to a temp file for replay-based operations.
    func writeReplayEnvelopeToTempFile() throws -> URL {
        let data = session.lastOriginalEnvelope
        guard let data else {
            throw CocoaError(.fileWriteUnknown, userInfo: [
                NSLocalizedDescriptionKey: "No envelope data available for replay",
            ])
        }
        let tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("DuplicatesDetector", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        let url = tempDir.appendingPathComponent("replay-\(UUID().uuidString).ddscan")
        try data.write(to: url, options: .atomic)
        return url
    }

    /// Write a filtered replay envelope excluding ignored and resolved pairs.
    /// Used for HTML/shell export and refine, where the user expects only active results.
    func writeFilteredReplayEnvelopeToTempFile() throws -> URL {
        guard var envelope = session.results?.envelope else {
            throw CocoaError(.fileWriteUnknown, userInfo: [
                NSLocalizedDescriptionKey: "No results available for filtered replay",
            ])
        }

        let ignoredPairs = session.results?.ignoredPairs ?? []
        let resolutions = session.results?.resolutions ?? [:]

        switch envelope.content {
        case .pairs(let pairs):
            let filtered = pairs.filter { pair in
                let id = pair.pairIdentifier
                if ignoredPairs.contains(id) { return false }
                if resolutions[id] != nil { return false }
                return true
            }
            envelope.content = .pairs(filtered)
        case .groups(var groups):
            let actionedPaths = session.results?.actionedPaths ?? []
            // Inject pending watch pairs as synthetic 2-file groups so
            // replay/export includes watch-detected duplicates.
            let pendingPairs = session.results?.pendingWatchPairs ?? []
            let maxGroupId = groups.map(\.groupId).max() ?? 0
            for (offset, pair) in pendingPairs.enumerated() {
                let id = pair.pairIdentifier
                guard !ignoredPairs.contains(id), resolutions[id] == nil else { continue }
                let groupId = maxGroupId + offset + 1
                func groupFile(from meta: FileMetadata, path: String, isRef: Bool) -> GroupFile {
                    GroupFile(
                        path: path, duration: meta.duration,
                        width: meta.width, height: meta.height,
                        fileSize: meta.fileSize, codec: meta.codec,
                        bitrate: meta.bitrate, framerate: meta.framerate,
                        audioChannels: meta.audioChannels, mtime: meta.mtime,
                        tagTitle: meta.tagTitle, tagArtist: meta.tagArtist,
                        tagAlbum: meta.tagAlbum, isReference: isRef, thumbnail: nil
                    )
                }
                let fileA = groupFile(from: pair.fileAMetadata, path: pair.fileA, isRef: pair.fileAIsReference)
                let fileB = groupFile(from: pair.fileBMetadata, path: pair.fileB, isRef: pair.fileBIsReference)
                let gp = GroupPair(
                    fileA: pair.fileA, fileB: pair.fileB,
                    score: pair.score, breakdown: pair.breakdown, detail: pair.detail
                )
                groups.append(GroupResult(
                    groupId: groupId, fileCount: 2,
                    maxScore: pair.score, minScore: pair.score, avgScore: pair.score,
                    files: [fileA, fileB], pairs: [gp], keep: pair.keep
                ))
            }
            let filtered = groups.compactMap { group -> GroupResult? in
                var group = group
                group.pairs = group.pairs.filter { gp in
                    let id = PairIdentifier(fileA: gp.fileA, fileB: gp.fileB)
                    if ignoredPairs.contains(id) { return false }
                    if resolutions[id] != nil { return false }
                    return true
                }
                group.files = group.files.filter { !actionedPaths.contains($0.path) }
                guard group.files.count >= 2 else { return nil }
                return group
            }
            envelope.content = .groups(filtered)
        }

        switch envelope.content {
        case .pairs(let pairs): envelope.stats.pairsAboveThreshold = pairs.count
        case .groups(let groups): envelope.stats.pairsAboveThreshold = groups.reduce(0) { $0 + $1.pairs.count }
        }

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(envelope)
        let tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("DuplicatesDetector", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        let url = tempDir.appendingPathComponent("replay-\(UUID().uuidString).ddscan")
        try data.write(to: url, options: .atomic)
        return url
    }

    // MARK: Action Routing

    /// Route a `PairAction` through the appropriate store path.
    ///
    /// For destructive actions (trash, delete, move), this method suspends until
    /// the file operation completes and returns whether it succeeded. Non-destructive
    /// actions return synchronously.
    @discardableResult
    func handleAction(_ action: PairAction, pairID: PairIdentifier? = nil, context: ActionContext? = nil) async -> Bool {
        switch action {
        case .revealInFinder(let path):
            revealInFinder(path)
            return true
        case .quickLook(let path):
            quickLook(path)
            return true
        case .trash(let path):
            return await dispatchDestructiveAction(path: path, type: .trash, pairID: pairID)
        case .permanentDelete(let path):
            return await dispatchDestructiveAction(path: path, type: .delete, pairID: pairID)
        case .moveTo(let path):
            return await dispatchDestructiveAction(path: path, type: .moveTo, pairID: pairID)
        case .copyPath(let path):
            copyPath(path)
            return true
        case .copyPaths(let a, let b):
            copyPaths(a, b)
            return true
        case .ignorePair(let a, let b):
            let id = PairIdentifier(fileA: a, fileB: b)
            send(.ignorePair(id))
            return session.results?.isDryRun != true
        case .bulkAction:
            return true  // Handled by view layer (confirmation dialog)
        }
    }

    /// Dispatch a destructive file action and suspend until the operation completes.
    private func dispatchDestructiveAction(path: String, type: ActionType, pairID: PairIdentifier?) async -> Bool {
        guard let id = pairID ?? selectedPair?.pairIdentifier else { return false }
        guard session.results?.isDryRun != true, session.results?.bulkProgress == nil else { return false }
        // Prevent double-dispatch on the same pair (rapid taps while awaiting)
        guard pendingActionContinuations[id] == nil else { return false }
        return await withCheckedContinuation { continuation in
            pendingActionContinuations[id] = continuation
            send(.keepFile(id, path, type))
        }
    }

    /// Derive an action context for logging from the currently selected pair.
    func actionContext(for path: String) -> ActionContext? {
        if session.display.viewMode != .groups,
           let pair = selectedPair,
           pair.fileA == path || pair.fileB == path
        {
            let keptPath: String?
            if pair.keepPath == pair.fileA && path == pair.fileB {
                keptPath = pair.fileA
            } else if pair.keepPath == pair.fileB && path == pair.fileA {
                keptPath = pair.fileB
            } else {
                keptPath = pair.keepPath
            }
            return ActionContext(score: Double(pair.score), strategy: session.results?.envelope.args.keep, keptPath: keptPath)
        }
        return bulkActionContext(for: path)
    }

    /// Look up the best action context for a file from the envelope data.
    func bulkActionContext(for path: String) -> ActionContext? {
        guard let results = session.results else { return nil }

        if results.isPairMode, session.display.viewMode == .groups, let groups = results.synthesizedGroups {
            for group in groups {
                if group.files.contains(where: { $0.path == path }) {
                    return ActionContext(score: group.maxScore, strategy: results.envelope.args.keep, keptPath: group.keep)
                }
            }
        }

        switch results.envelope.content {
        case .pairs(let pairs):
            if let pair = pairs.first(where: { $0.fileA == path || $0.fileB == path }) {
                return ActionContext(score: Double(pair.score), strategy: results.envelope.args.keep, keptPath: pair.keepPath)
            }
        case .groups(let groups):
            for group in groups {
                if group.files.contains(where: { $0.path == path }) {
                    return ActionContext(score: group.maxScore, strategy: results.envelope.args.keep, keptPath: group.keep)
                }
            }
        }
        return nil
    }

    // MARK: Selection Toggles

    /// Toggle selection of a single pair for bulk action.
    func togglePairSelection(_ id: PairIdentifier) {
        send(.togglePairSelection(id))
    }

    /// Toggle selection of a single group for bulk action.
    func toggleGroupSelection(_ id: Int) {
        send(.toggleGroupSelection(id))
    }

    // MARK: Summary

    /// Copy a human-readable results summary to the system clipboard.
    func copySummaryToClipboard() {
        guard let results = session.results else { return }
        var lines = [
            "Duplicates Detector Results",
            "Files scanned: \(results.filesScanned)",
            "Pairs found: \(results.pairsCount)",
        ]
        if let space = results.spaceRecoverable {
            lines.append("Space recoverable: \(space)")
        }
        lines.append("Total time: \(results.totalTime)")
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(lines.joined(separator: "\n"), forType: .string)
    }

    // MARK: In-Flight Task Management

    /// Register an externally-spawned action task so `flushActionLog` can await it.
    func trackActionTask(_ task: Task<Void, Never>) {
        inflightActionTasks.append(task)
        Task {
            await task.value
            inflightActionTasks.removeAll { $0 == task }
        }
    }

    /// Wait for all in-flight action tasks to complete before reading the log file.
    /// Also awaits the bulk action task if one is running, since it dispatches
    /// additional log writes as each item completes.
    func flushActionLog() async {
        if let bulk = bulkActionTask {
            await bulk.value
        }
        while !inflightActionTasks.isEmpty {
            let batch = inflightActionTasks
            inflightActionTasks.removeAll()
            for task in batch {
                await task.value
            }
        }
    }

    // MARK: Error Management

    /// Clear the first pair error from the results snapshot.
    func clearFirstPairError() {
        if let firstKey = session.results?.pairErrors.keys.first {
            send(.clearPairError(firstKey))
        }
    }

    // MARK: Ignore File Path

    /// Resolved path to the ignore-list file, for the IgnoreListView.
    var ignoreFilePath: URL? {
        if let path = session.lastScanConfig?.ignoreFile {
            return URL(fileURLWithPath: path)
        }
        // Fall back to the same default as IgnoreListManager and the CLI.
        return IgnoreListManager.defaultPath
    }

    // MARK: Bulk Action Candidates

    /// Compute the de-duplicated list of files eligible for bulk action.
    func bulkActionCandidates() -> (candidates: [BulkCandidate], strategy: String?) {
        session.results?.bulkActionCandidates(display: session.display)
            ?? (candidates: [], strategy: nil)
    }

    // MARK: Progress Context

    /// Snapshot of configuration-derived fields used by `ProgressScreen`.
    struct ProgressContext {
        var mode: ScanMode
        var directoryEntries: [DirectoryEntry]
        var contentEnabled: Bool
        var contentMethod: ContentMethod
        var audioEnabled: Bool
        var sourceLabel: String?
    }

    /// Progress context derived from last scan config, pending session, or setup state.
    var progressContext: ProgressContext {
        let sourceLabel = session.metadata.sourceLabel

        if let config = session.lastScanConfig,
           let resumeId = config.resume,
           let pendingSession = session.pendingSession,
           pendingSession.sessionId == resumeId
        {
            let mode = ScanMode(rawValue: pendingSession.mode) ?? config.mode
            let contentEnabled = pendingSession.config["content"]?.boolValue ?? config.content
            let contentMethod = ContentMethod(
                rawValue: pendingSession.config["content_method"]?.stringValue ?? ""
            ) ?? .phash
            let audioEnabled = pendingSession.config["audio"]?.boolValue ?? config.audio
            let entries = pendingSession.directories.map { DirectoryEntry(path: $0) }
            return ProgressContext(
                mode: mode,
                directoryEntries: entries.isEmpty ? setupState.entries : entries,
                contentEnabled: contentEnabled,
                contentMethod: contentMethod,
                audioEnabled: audioEnabled,
                sourceLabel: sourceLabel.isEmpty ? nil : sourceLabel
            )
        }

        guard let config = session.lastScanConfig else {
            return ProgressContext(
                mode: setupState.mode,
                directoryEntries: setupState.entries,
                contentEnabled: setupState.content,
                contentMethod: setupState.contentMethod,
                audioEnabled: setupState.audio,
                sourceLabel: sourceLabel.isEmpty ? nil : sourceLabel
            )
        }

        let entries = config.directories.map { DirectoryEntry(path: $0) }
        return ProgressContext(
            mode: config.mode,
            directoryEntries: entries.isEmpty ? setupState.entries : entries,
            contentEnabled: config.content,
            contentMethod: config.contentMethod ?? .phash,
            audioEnabled: config.audio,
            sourceLabel: sourceLabel.isEmpty ? nil : sourceLabel
        )
    }

    // MARK: - Mock Photos Scan (UI Testing)

    #if DEBUG
    /// Mock Photos scan for UI testing. Emits progress stages and returns canned data
    /// with `photos://asset/` URIs so all Photos-specific UI conditionals activate.
    private func executePhotosTestScan(scope: PhotosScope, config: SessionConfig) {
        scanTask?.cancel()
        minimumDisplayTask?.cancel()
        minimumDisplayTask = nil
        scanGeneration &+= 1
        let gen = scanGeneration
        let formatter = Self.iso8601Formatter

        let scenario = ProcessInfo.processInfo.environment["DD_UI_TEST_SCENARIO"] ?? "photos-pairs"
        let isSlow = scenario == "slow-photos"
        let stageDelay: UInt64 = isSlow ? 800 : 30
        let progressDelay: UInt64 = isSlow ? 500 : 20

        scanTask = Task {
            do {
                let stages = ["authorize", "extract", "filter", "score", "report"]
                for stage in stages {
                    try Task.checkCancellation()
                    guard self.scanGeneration == gen else { return }
                    self.send(.cliStageStart(StageStartEvent(
                        stage: stage, timestamp: formatter.string(from: Date())
                    )))
                    try await Task.sleep(for: .milliseconds(stageDelay))

                    if stage == "extract" || stage == "score" {
                        self.send(.cliProgress(StageProgressEvent(
                            stage: stage, current: 12, timestamp: formatter.string(from: Date()),
                            total: 12, rate: 100.0
                        )))
                        try await Task.sleep(for: .milliseconds(progressDelay))
                    }

                    try await Task.sleep(for: .milliseconds(progressDelay))
                    try Task.checkCancellation()
                    guard self.scanGeneration == gen else { return }
                    self.send(.cliStageEnd(StageEndEvent(
                        stage: stage, total: 12, elapsed: 0.05,
                        timestamp: formatter.string(from: Date()),
                        extras: stage == "score" ? ["pairs_found": 3] : [:]
                    )))
                }

                guard self.scanGeneration == gen else { return }

                let envelope = MockCLIBridge.makePhotosEnvelope()
                let encoder = JSONEncoder()
                encoder.keyEncodingStrategy = .convertToSnakeCase
                let rawData = try? encoder.encode(envelope)
                self.send(.cliStreamCompleted(envelope, rawData))
            } catch is CancellationError {
                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamCancelled)
            } catch {
                guard self.scanGeneration == gen else { return }
                self.send(.cliStreamFailed(ErrorInfo.classify(error)))
            }

            if self.scanGeneration == gen { self.scanTask = nil }
        }
    }
    #endif
}
