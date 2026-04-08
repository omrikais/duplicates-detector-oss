import Foundation

// MARK: - ScanMode Codable Conformance

/// ScanMode is `String`-backed so Codable synthesis is trivial.
/// Added here because `WatchConfig` and `SessionMetadata` require it.
extension ScanMode: Codable {}

/// SessionInfo needs Equatable for use in `Session` (which is Equatable).
/// All stored properties are already Equatable types.
extension SessionInfo: Equatable {
    static func == (lhs: SessionInfo, rhs: SessionInfo) -> Bool {
        lhs.sessionId == rhs.sessionId
            && lhs.directories == rhs.directories
            && lhs.config == rhs.config
            && lhs.completedStages == rhs.completedStages
            && lhs.activeStage == rhs.activeStage
            && lhs.totalFiles == rhs.totalFiles
            && lhs.elapsedSeconds == rhs.elapsedSeconds
            && lhs.createdAt == rhs.createdAt
            && lhs.pausedAt == rhs.pausedAt
            && lhs.progressPercent == rhs.progressPercent
    }
}

// MARK: - PairID

/// Stable pair identity for selection (not affected by sort/filter changes).
/// Points to the existing `PairIdentifier` type.
public typealias PairID = PairIdentifier

// MARK: - SessionConfig

/// Session config is the full set of CLI flags for a scan.
typealias SessionConfig = ScanConfig

// MARK: - Resolution

/// Resolution state of a duplicate pair in the results view.
///
/// Replaces `PairResolutionStatus` with a unified naming convention.
enum Resolution: Codable, Equatable, Sendable {
    /// Both files exist on disk, no prior action recorded.
    case active
    /// Explicitly actioned -- sidecar record exists with action details.
    case resolved(ActionRecord)
    /// Legacy fallback -- one or both files missing on disk, no sidecar record.
    case probablySolved(missing: [String])

    private enum Tag: String, Codable {
        case active, resolved, probablySolved
    }

    private enum CodingKeys: String, CodingKey {
        case tag, record, missing
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let tag = try c.decode(Tag.self, forKey: .tag)
        switch tag {
        case .active:
            self = .active
        case .resolved:
            let record = try c.decode(ActionRecord.self, forKey: .record)
            self = .resolved(record)
        case .probablySolved:
            let missing = try c.decode([String].self, forKey: .missing)
            self = .probablySolved(missing: missing)
        }
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .active:
            try c.encode(Tag.active, forKey: .tag)
        case .resolved(let record):
            try c.encode(Tag.resolved, forKey: .tag)
            try c.encode(record, forKey: .record)
        case .probablySolved(let missing):
            try c.encode(Tag.probablySolved, forKey: .tag)
            try c.encode(missing, forKey: .missing)
        }
    }
}

// MARK: - Resolution ↔ PairResolutionStatus Bridge

extension Resolution {
    private nonisolated(unsafe) static let iso8601Formatter = ISO8601DateFormatter()

    /// Convert to the legacy `PairResolutionStatus` for views that still consume
    /// the old type (e.g. `PairQueueRow`, `ComparisonPanel`).
    var asPairResolutionStatus: PairResolutionStatus {
        switch self {
        case .active:
            return .active
        case .resolved(let record):
            return .resolved(HistoryAction(
                timestamp: Self.iso8601Formatter.string(from: record.timestamp),
                action: record.action,
                path: record.actedOnPath,
                kept: record.keptPath.isEmpty ? nil : record.keptPath,
                bytesFreed: record.bytesFreed ?? 0,
                score: Double(record.score),
                strategy: record.strategy,
                destination: record.destination
            ))
        case .probablySolved(let missing):
            return .probablySolved(missing: missing)
        }
    }
}

// MARK: - ActionRecord

/// A single user action persisted in the history sidecar (`.actions.json`).
///
/// Stores **original envelope paths** (unresolved) for direct matching against
/// `PairID.fileA`/`.fileB`. Replaces `HistoryAction` with a unified naming convention.
public struct ActionRecord: Codable, Sendable, Equatable {
    public let pairID: PairID
    public let timestamp: Date
    public let action: String
    public let actedOnPath: String
    public let keptPath: String
    public let bytesFreed: Int?
    public let score: Int
    public let strategy: String?
    public let destination: String?
}

// MARK: - FileStatus

/// Whether a file referenced by a pair still exists on disk.
public enum FileStatus: Sendable, Equatable {
    /// File is present and accessible.
    case present
    /// File is missing (deleted or inaccessible).
    case missing
    /// File was moved to a new location.
    case moved(to: String)
    /// File was actioned (trash, delete, move, etc.) with a recorded action.
    case actioned(ActionRecord)
}

// MARK: - WatchConfig

/// Configuration for a background watch session.
struct WatchConfig: Codable, Equatable, Sendable {
    /// Directories being monitored.
    var directories: [String]
    /// The scan mode for watch detection.
    var mode: ScanMode
    /// Score threshold for duplicate alerts.
    var threshold: Int
    /// File extension filter (e.g. "mp4,mov,avi"), if any.
    public let extensions: String?
    /// Custom weights, if any.
    var weights: [String: Double]?

    init(
        directories: [String] = [],
        mode: ScanMode = .video,
        threshold: Int = 50,
        extensions: String? = nil,
        weights: [String: Double]? = nil
    ) {
        self.directories = directories
        self.mode = mode
        self.threshold = threshold
        self.extensions = extensions
        self.weights = weights
    }
}

// MARK: - WatchState

/// Live state for a background watch session.
struct WatchState: Equatable, Sendable {
    /// Whether the watch session is currently active.
    public var isActive: Bool
    /// Live statistics.
    var stats: WatchStats
    /// When the watch session started.
    var startedAt: Date
    /// Human-readable label for the source directories.
    var sourceLabel: String

    init(
        isActive: Bool = false,
        stats: WatchStats = WatchStats(trackedFiles: 0),
        startedAt: Date = Date(),
        sourceLabel: String = ""
    ) {
        self.isActive = isActive
        self.stats = stats
        self.startedAt = startedAt
        self.sourceLabel = sourceLabel
    }
}

// MARK: - SessionMetadata

/// Metadata about a session for history and persistence.
struct SessionMetadata: Codable, Equatable, Sendable {
    /// Canonical source label for Photos Library scans.
    static let photosLibraryLabel = "Photos Library"
    /// When the session was created.
    var createdAt: Date
    /// Source directories for this session.
    var directories: [String]
    /// Human-readable label (e.g., directory names).
    var sourceLabel: String
    /// The scan mode used.
    var mode: ScanMode
    /// Number of pairs found in this session.
    var pairCount: Int
    /// Number of files scanned in this session.
    var fileCount: Int
    /// Number of files scanned (mirrors `ScanStats.filesScanned`). Nil for legacy sessions.
    var filesScanned: Int?
    /// Total recoverable space in bytes (mirrors `ScanStats.spaceRecoverable`). Nil for legacy sessions.
    var spaceRecoverable: Int?
    /// Number of groups (mirrors `ScanStats.groupsCount`). Nil for legacy sessions or pair-mode scans.
    var groupsCount: Int?

    init(
        createdAt: Date = Date(),
        directories: [String] = [],
        sourceLabel: String = "",
        mode: ScanMode = .video,
        pairCount: Int = 0,
        fileCount: Int = 0,
        filesScanned: Int? = nil,
        spaceRecoverable: Int? = nil,
        groupsCount: Int? = nil
    ) {
        self.createdAt = createdAt
        self.directories = directories
        self.sourceLabel = sourceLabel
        self.mode = mode
        self.pairCount = pairCount
        self.fileCount = fileCount
        self.filesScanned = filesScanned
        self.spaceRecoverable = spaceRecoverable
        self.groupsCount = groupsCount
    }
}

// MARK: - DisplayState

/// UI display state that is orthogonal to domain data.
struct DisplayState: Equatable, Sendable {

    /// Whether to display pairs or groups.
    enum ViewMode: String, CaseIterable, Sendable {
        case pairs = "Pairs"
        case groups = "Groups"
    }

    var viewMode: ViewMode
    var searchText: String = ""
    var sortOrder: ResultSortOrder = .scoreDescending
    var selectedPairID: PairID?
    var isSelectMode: Bool = false
    var selectedForAction: Set<PairID> = []
    var selectedGroupsForAction: Set<Int> = []
    var activeAction: ActionType = .trash
    var moveDestination: URL?
    public var inspectorVisible: Bool = true
    /// Whether the insights panel is visible (separate from ViewMode).
    var showInsights: Bool = false
    /// Optional directory path to filter analytics by.
    var directoryFilter: String?

    /// Factory: returns the correct initial display state for a given scan content type.
    static func initial(for content: ScanContent) -> DisplayState {
        let mode: ViewMode
        switch content {
        case .groups: mode = .groups
        case .pairs: mode = .pairs
        }
        return DisplayState(viewMode: mode)
    }
}

// MARK: - PauseState

/// Pause lifecycle state for a scan in progress.
public enum PauseState: Equatable, Sendable {
    case running
    case pausing(sessionId: String?)
    case paused(sessionId: String?)
}

// MARK: - ScanTiming

/// Timing fields for a scan in progress.
struct ScanTiming: Equatable, Sendable {
    /// When the overall scan started.
    var overallStartTime: Date?
    /// Elapsed time from completed stages (frozen on completion).
    var completedElapsed: TimeInterval = 0
    /// Baseline elapsed time carried forward from a resumed session.
    var resumedBaseline: TimeInterval = 0
    /// Whether this scan was resumed from a paused session.
    var isResumed: Bool = false
    /// Whether we have received the CLI session_start event.
    var receivedSessionStart: Bool = false
    /// When the scanning phase UI was entered (for minimum display duration).
    var scanPhaseStartTime: Date?
    /// When the current pause started (moved from old PauseState struct).
    var pauseStartTime: Date? = nil
    /// Total accumulated pause duration from prior pauses (moved from old PauseState struct).
    var accumulatedPauseDuration: TimeInterval = 0
}

// MARK: - CacheStats

/// Cache hit/miss counters accumulated during a scan.
struct CacheStats: Equatable, Sendable {
    var cacheHits: Int = 0
    var cacheMisses: Int = 0
    var cacheTimeSaved: Double?
    var metadataCacheHits: Int = 0
    var metadataCacheMisses: Int = 0
    var contentCacheHits: Int = 0
    var contentCacheMisses: Int = 0
    var audioCacheHits: Int = 0
    var audioCacheMisses: Int = 0
    var scoreCacheHits: Int = 0
    var scoreCacheMisses: Int = 0
}

// MARK: - ScanProgress

/// All state for a scan in progress. Replaces `ScanLifecycleState` scan-specific fields.
struct ScanProgress: Equatable, Sendable {

    // MARK: - Nested Types (ported from ScanLifecycleState)

    /// Status of a single pipeline stage.
    enum StageStatus: Equatable, Sendable {
        case pending
        case active(current: Int, total: Int?)
        case completed(elapsed: Double, total: Int, extras: [String: Int])
    }

    /// State for a single pipeline stage, identified by its ``PipelineStage``.
    struct StageState: Identifiable, Equatable, Sendable {
        let id: PipelineStage
        let displayName: String
        var status: StageStatus = .pending
        var currentFile: String?

        var isActive: Bool {
            if case .active = status { return true }
            return false
        }

        var isCompleted: Bool {
            if case .completed = status { return true }
            return false
        }

        /// Accessibility label for the pipeline node.
        var accessibilityText: String {
            "\(displayName), \(accessibilityStatus)"
        }

        /// Status portion of the accessibility label.
        var accessibilityStatus: String {
            switch status {
            case .completed(let elapsed, let total, _):
                "completed, \(total) items in \(ScanProgress.formatElapsed(elapsed))"
            case .active(let current, let total):
                if let total { "in progress, \(current) of \(total)" } else { "in progress" }
            case .pending:
                "pending"
            }
        }
    }

    // MARK: - Phase

    /// Whether we are cancelling the scan.
    var isCancelling: Bool = false
    /// Whether we are finalizing results after the CLI exits.
    var isFinalizingResults: Bool = false

    // MARK: - Photos Warnings

    /// Set when Photos authorization is `.limited` — only user-selected photos are visible.
    var photosLimitedWarning: Bool = false

    // MARK: - Pipeline Progress

    var stages: [StageState] = []
    var stageStartTimes: [PipelineStage: Date] = [:]
    var currentThroughput: Double?

    // MARK: - Timing

    var timing: ScanTiming = ScanTiming()

    // MARK: - Pause

    var pause: PauseState = .running

    // MARK: - Cache Stats

    var cache: CacheStats = CacheStats()

    // MARK: - Session

    var currentSessionId: String?
    var pauseFileURL: URL?
    var watchEnabled: Bool = false

    // MARK: - Computed Properties

    /// Overall scan progress, computed from stage states. Never stored -- always derived.
    var overallProgress: Double {
        computeWeightedProgress().total
    }

    /// Fraction of overall progress from fully completed stages (green bar segment).
    var completedProgress: Double {
        computeWeightedProgress().completed
    }

    /// Fraction of overall progress from the active stage's partial completion (blue bar segment).
    var activeProgress: Double {
        let p = computeWeightedProgress()
        return max(0, p.total - p.completed)
    }

    /// Whether all stages have completed.
    var isComplete: Bool {
        !stages.isEmpty && stages.allSatisfy(\.isCompleted)
    }

    /// The currently active stage, if any.
    var activeStage: StageState? {
        stages.first(where: \.isActive)
    }

    /// Live elapsed time for UI display.
    func liveElapsed(at now: Date) -> TimeInterval {
        guard let start = timing.overallStartTime else { return 0 }
        if isComplete { return timing.resumedBaseline + timing.completedElapsed }
        let total = now.timeIntervalSince(start)
        if let pauseStart = timing.pauseStartTime {
            return timing.resumedBaseline + pauseStart.timeIntervalSince(start) - timing.accumulatedPauseDuration
        }
        return timing.resumedBaseline + total - timing.accumulatedPauseDuration
    }

    /// Format a time interval for display (e.g., "1.5s", "2m 30s").
    nonisolated static func formatElapsed(_ seconds: Double) -> String {
        if seconds < 0.9995 {
            return String(format: "%.0fms", seconds * 1000)
        } else if seconds < 60 {
            return String(format: "%.1fs", seconds)
        } else {
            let mins = Int(seconds) / 60
            let secs = Int(seconds) % 60
            return "\(mins)m \(secs)s"
        }
    }

    // MARK: - Static Factory Methods

    /// Build the initial stage list for a scan pipeline based on configuration flags.
    static func initialStages(
        mode: ScanMode, content: Bool, audio: Bool,
        embedThumbnails: Bool = false,
        contentMethod: ContentMethod = .phash,
        hasFilters: Bool = false
    ) -> [StageState] {
        var pipeline: [(PipelineStage, String)] = [
            (.scan, "Scanning files"),
            (.extract, "Extracting metadata"),
        ]
        pipeline.append((.filter, "Filtering"))
        if content {
            if contentMethod == .ssim {
                pipeline.append((.ssimExtract, "Extracting SSIM frames"))
            } else {
                pipeline.append((.contentHash, "Hashing content"))
            }
        }
        if audio {
            pipeline.append((.audioFingerprint, "Audio fingerprinting"))
        }
        pipeline.append((.score, "Scoring pairs"))
        if embedThumbnails {
            pipeline.append((.thumbnail, "Generating thumbnails"))
        }
        pipeline.append((.report, "Building report"))
        return pipeline.map { StageState(id: $0.0, displayName: $0.1) }
    }

    /// Build the stage list for a replay pipeline.
    static func replayStages(embedThumbnails: Bool = false) -> [StageState] {
        var pipeline: [(PipelineStage, String)] = [
            (.replay, "Loading replay"),
            (.filter, "Filtering"),
        ]
        if embedThumbnails {
            pipeline.append((.thumbnail, "Generating thumbnails"))
        }
        pipeline.append((.report, "Building report"))
        return pipeline.map { StageState(id: $0.0, displayName: $0.1) }
    }

    // MARK: - Private Helpers

    /// Canonical time-proportion weights for each pipeline stage.
    private static let stageWeights: [PipelineStage: Double] = [
        .scan: 0.05,
        .extract: 0.20,
        .filter: 0.01,
        .contentHash: 0.30,
        .ssimExtract: 0.05,
        .audioFingerprint: 0.18,
        .score: 0.12,
        .thumbnail: 0.05,
        .report: 0.04,
        .replay: 0.05,
        // Photos Library pipeline stage
        .authorize: 0.02,
    ]

    /// Compute weighted progress split into total and completed portions.
    private func computeWeightedProgress() -> (total: Double, completed: Double) {
        var weights: [PipelineStage: Double] = [:]
        var totalWeight = 0.0
        for stage in stages {
            let w = Self.stageWeights[stage.id] ?? 0.02
            weights[stage.id] = w
            totalWeight += w
        }
        if totalWeight > 0 {
            for key in weights.keys {
                weights[key]! /= totalWeight
            }
        }

        var completedPortion = 0.0
        var totalProgress = 0.0
        for stage in stages {
            let w = weights[stage.id] ?? 0.0
            switch stage.status {
            case .completed:
                completedPortion += w
                totalProgress += w
            case .active(let current, let stageTotal):
                if let stageTotal, stageTotal > 0 {
                    totalProgress += w * min(1.0, Double(current) / Double(stageTotal))
                } else if current > 0 {
                    totalProgress += w * Self.unknownTotalProgress(for: current)
                }
            case .pending:
                break
            }
        }
        return (total: totalProgress, completed: completedPortion)
    }

    /// Asymptotic progress estimate when total is unknown.
    private static func unknownTotalProgress(for current: Int) -> Double {
        let scaled = Double(max(current, 0)) / 100.0
        return min(0.9, 1.0 - 1.0 / (1.0 + scaled))
    }
}

// MARK: - StageStatus totalCount Extension

extension ScanProgress.StageStatus {
    /// The total item count, if known.
    var totalCount: Int? {
        switch self {
        case .pending:
            nil
        case .active(_, let total):
            total
        case .completed(_, let total, _):
            total
        }
    }
}

// MARK: - ActionError

/// An error that occurred during a file action (trash, delete, move, etc.).
struct ActionError: Equatable, Sendable {
    /// Human-readable error message.
    var message: String
}

// MARK: - BulkProgress

/// Progress of an in-flight bulk action.
struct BulkProgress: Equatable, Sendable {
    var completed: Int
    var total: Int
}

// MARK: - BulkCandidate

/// A file path + size eligible for a bulk action.
struct BulkCandidate: Equatable, Sendable {
    let path: String
    let size: Int
}

// MARK: - ResultsSnapshot

/// Snapshot of scan results and resolution state. Replaces `ResultsState`.
struct ResultsSnapshot: Equatable, Sendable {

    // MARK: - Envelope

    /// The scan envelope from the CLI. Mutated only to inject watch pairs.
    var envelope: ScanEnvelope

    // MARK: - Analytics

    /// Analytics data populated from `ScanEnvelope.analytics`.
    var analyticsData: AnalyticsData?

    // MARK: - Derived Flags (set once in init, stable across watch pair appends)

    let isDryRun: Bool
    let hasKeepStrategy: Bool

    // MARK: - Resolution State

    var fileStatuses: [String: FileStatus] = [:]
    var resolutions: [PairID: Resolution] = [:]
    var actionHistory: [ActionRecord] = []
    var ignoredPairs: Set<PairID> = []

    // MARK: - Bulk Operations

    var bulkProgress: BulkProgress?
    var bulkCancelled: Bool = false

    // MARK: - Errors

    public var pairErrors: [PairID: ActionError] = [:]

    // MARK: - Computed Convenience

    /// Number of unique logical ignored pairs (both (A,B) and (B,A) count as one).
    var uniqueIgnoredPairCount: Int {
        Set(ignoredPairs.map { [$0.fileA, $0.fileB].sorted() }).count
    }

    /// Paths that have been actioned, derived from resolutions.
    var actionedPaths: Set<String> {
        var paths = Set<String>()
        for status in resolutions.values {
            switch status {
            case .resolved(let action): paths.insert(action.actedOnPath)
            case .probablySolved, .active: break
            }
        }
        return paths
    }

    // MARK: - View Mode Synthesis

    var synthesizedGroups: [GroupResult]?
    var synthesizedPairs: [PairResult]?
    var stableGroupIDMap: [Set<String>: Int] = [:]
    var nextStableGroupID: Int = 1

    // MARK: - Watch Mode

    /// Buffer for watch pairs that arrive while the view mode is `.groups`.
    var pendingWatchPairs: [PairResult] = []

    // MARK: - Filter Cache

    var filterGeneration: UInt = 0

    // MARK: - Init

    init(envelope: ScanEnvelope, isDryRun: Bool = false, hasKeepStrategy: Bool = false) {
        self.envelope = envelope
        self.analyticsData = envelope.analytics
        self.isDryRun = isDryRun
        self.hasKeepStrategy = hasKeepStrategy
    }

    // MARK: - Computed Properties

    /// Whether the envelope originally contained pairs data.
    var isPairMode: Bool {
        if case .pairs = envelope.content { return true }
        return false
    }

    /// True when the user can toggle between pairs and groups view.
    func canToggleViewMode(for viewMode: DisplayState.ViewMode) -> Bool {
        switch envelope.content {
        case .pairs(let pairs): pairs.count >= 2
        case .groups(let groups): groups.reduce(0) { $0 + $1.pairs.count } >= 2
        }
    }

    /// Effective pair mode: accounts for view mode toggle.
    func effectivePairMode(for viewMode: DisplayState.ViewMode) -> Bool {
        viewMode == .pairs
    }

    /// Whether this result set contains no pairs and no groups.
    var isEmpty: Bool {
        pairsCount == 0 && (groupsCount ?? 0) == 0
    }

    var pairsCount: Int {
        switch envelope.content {
        case .pairs(let pairs): pairs.count
        case .groups(let groups): groups.reduce(0) { $0 + $1.pairs.count }
        }
    }

    var groupsCount: Int? {
        if case .groups(let groups) = envelope.content {
            return groups.count
        }
        return nil
    }

    // MARK: - Stats Passthroughs

    var filesScanned: Int { envelope.stats.filesScanned }
    var filesAfterFilter: Int { envelope.stats.filesAfterFilter }
    var totalPairsScored: Int { envelope.stats.totalPairsScored }
    var pairsAboveThreshold: Int { envelope.stats.pairsAboveThreshold }
    var dryRunSummary: DryRunSummary? { envelope.dryRunSummary }
    var scanArgs: ScanArgs { envelope.args }

    var spaceRecoverable: String? {
        guard let bytes = envelope.stats.spaceRecoverable, bytes > 0 else { return nil }
        return Self.formatFileSize(bytes)
    }

    var totalTime: String {
        ScanProgress.formatElapsed(envelope.stats.totalTime)
    }

    // MARK: - Per-stage timing

    var stageTiming: [(String, Double)] {
        [("Scan", envelope.stats.scanTime),
         ("Extract", envelope.stats.extractTime),
         ("Filter", envelope.stats.filterTime),
         ("Content Hash", envelope.stats.contentHashTime),
         ("Scoring", envelope.stats.scoringTime)]
            .filter { $0.1 > 0 }
    }

    // MARK: - Resolution Properties

    /// Look up the resolution status for a pair.
    func resolutionStatus(for pairID: PairID) -> Resolution {
        resolutions[pairID] ?? .active
    }

    /// Paths that appear in any resolution entry (resolved or probably-solved).
    func computeResolvedOrMissingPaths() -> Set<String> {
        var paths = Set<String>()
        for status in resolutions.values {
            switch status {
            case .resolved(let action): paths.insert(action.actedOnPath)
            case .probablySolved(let missing): paths.formUnion(missing)
            case .active: break
            }
        }
        return paths
    }

    /// Paths from resolved sidecar actions.
    var resolvedActionPaths: Set<String> {
        Set(resolutions.values.compactMap { status -> String? in
            if case .resolved(let action) = status { return action.actedOnPath }
            return nil
        })
    }

    // MARK: - Filter/Sort Methods

    /// Compute the filtered and sorted pairs list.
    func computeFilteredPairs(display: DisplayState) -> [PairResult] {
        let pairs: [PairResult]
        if !isPairMode, display.viewMode == .pairs, let synthesized = synthesizedPairs {
            pairs = synthesized
        } else if case .pairs(let envPairs) = envelope.content {
            pairs = envPairs
        } else {
            return []
        }
        let active = pairs.filter { pair in
            let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
            let isActioned = actionedPaths.contains(pair.fileA) || actionedPaths.contains(pair.fileB)
            let hasResolution = resolutions[pairID] != nil
            if isActioned && !hasResolution { return false }
            if ignoredPairs.contains(pairID) { return false }
            return true
        }
        let directoryFiltered = applyDirectoryFilter(active, directory: display.directoryFilter)
        let filtered = applySearch(directoryFiltered, searchText: display.searchText)
        let sorted = applySortPairs(filtered, sortOrder: display.sortOrder)

        let (activePairs, resolvedPairs) = sorted.reduce(
            into: ([PairResult](), [PairResult]())
        ) { result, pair in
            let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
            if case .active = resolutionStatus(for: pairID) {
                result.0.append(pair)
            } else {
                result.1.append(pair)
            }
        }
        return activePairs + resolvedPairs
    }

    /// Compute the filtered and sorted groups list.
    func computeFilteredGroups(display: DisplayState, isGroupFullyResolved: (GroupResult) -> Bool) -> [GroupResult] {
        let groups: [GroupResult]
        if isPairMode, display.viewMode == .groups, let synthesized = synthesizedGroups {
            groups = synthesized
        } else if case .groups(let envelopeGroups) = envelope.content {
            groups = envelopeGroups
        } else {
            return []
        }
        guard !groups.isEmpty else { return [] }
        let active = groups.filter { group in
            let candidates = group.files.filter { $0.path != group.keep && !$0.isReference }
            let allActionedWithoutResolution = !candidates.isEmpty && candidates.allSatisfy { file in
                actionedPaths.contains(file.path)
            } && !isGroupFullyResolved(group)
            if allActionedWithoutResolution { return false }
            let allIgnored = !group.pairs.isEmpty && group.pairs.allSatisfy { gp in
                ignoredPairs.contains(PairIdentifier(fileA: gp.fileA, fileB: gp.fileB))
            }
            return !allIgnored
        }
        let directoryFiltered = applyDirectoryFilterGroups(active, directory: display.directoryFilter)
        let filtered = display.searchText.isEmpty ? directoryFiltered : directoryFiltered.filter { group in
            group.files.contains { $0.path.localizedCaseInsensitiveContains(display.searchText) }
        }
        let sorted: [GroupResult]
        switch display.sortOrder {
        case .scoreDescending: sorted = filtered.sorted { $0.maxScore > $1.maxScore }
        case .scoreAscending: sorted = filtered.sorted { $0.maxScore < $1.maxScore }
        case .sizeDescending:
            let decorated = filtered.map { ($0, $0.files.reduce(0) { $0 + $1.fileSize }) }
            sorted = decorated.sorted { $0.1 > $1.1 }.map(\.0)
        case .pathAscending: sorted = filtered.sorted {
            ($0.files.first?.path ?? "") < ($1.files.first?.path ?? "")
        }
        }

        let (activeGroups, resolvedGroups) = sorted.reduce(
            into: ([GroupResult](), [GroupResult]())
        ) { result, group in
            if isGroupFullyResolved(group) {
                result.1.append(group)
            } else {
                result.0.append(group)
            }
        }
        return activeGroups + resolvedGroups
    }

    // MARK: - Static Synthesis Methods

    /// Synthesize groups from pairs using union-find with path compression and union by rank.
    static func synthesizeGroups(from pairs: [PairResult], keepStrategy: String? = nil) -> [GroupResult] {
        guard !pairs.isEmpty else { return [] }

        var parent: [String: String] = [:]
        var rank: [String: Int] = [:]

        func find(_ x: String) -> String {
            var node = x
            while let p = parent[node], p != node {
                parent[node] = parent[p] ?? p
                node = p
            }
            return node
        }

        func union(_ a: String, _ b: String) {
            let rootA = find(a)
            let rootB = find(b)
            guard rootA != rootB else { return }
            let rankA = rank[rootA, default: 0]
            let rankB = rank[rootB, default: 0]
            if rankA < rankB {
                parent[rootA] = rootB
            } else if rankA > rankB {
                parent[rootB] = rootA
            } else {
                parent[rootB] = rootA
                rank[rootA] = rankA + 1
            }
        }

        for pair in pairs {
            if parent[pair.fileA] == nil { parent[pair.fileA] = pair.fileA }
            if parent[pair.fileB] == nil { parent[pair.fileB] = pair.fileB }
        }

        for pair in pairs {
            union(pair.fileA, pair.fileB)
        }

        var clusters: [String: (members: Set<String>, pairs: [PairResult])] = [:]
        for pair in pairs {
            let root = find(pair.fileA)
            clusters[root, default: (members: [], pairs: [])].members.insert(pair.fileA)
            clusters[root, default: (members: [], pairs: [])].members.insert(pair.fileB)
            clusters[root, default: (members: [], pairs: [])].pairs.append(pair)
        }

        var groups: [GroupResult] = []
        for (_, cluster) in clusters {
            let clusterPairs = cluster.pairs

            var fileMap: [String: GroupFile] = [:]
            for pair in clusterPairs {
                if fileMap[pair.fileA] == nil {
                    fileMap[pair.fileA] = groupFile(
                        path: pair.fileA, metadata: pair.fileAMetadata, isReference: pair.fileAIsReference
                    )
                }
                if fileMap[pair.fileB] == nil {
                    fileMap[pair.fileB] = groupFile(
                        path: pair.fileB, metadata: pair.fileBMetadata, isReference: pair.fileBIsReference
                    )
                }
            }

            let files = fileMap.values.sorted { $0.path < $1.path }
            let scores = clusterPairs.map(\.score)
            let maxScore = scores.max() ?? 0
            let minScore = scores.min() ?? 0
            let avgScore = scores.isEmpty ? 0 : scores.reduce(0, +) / Double(scores.count)

            let groupPairs = clusterPairs.map { pair in
                GroupPair(
                    fileA: pair.fileA,
                    fileB: pair.fileB,
                    score: pair.score,
                    breakdown: pair.breakdown,
                    detail: pair.detail
                )
            }

            let keep = ResultsSnapshot.pickKeepFromGroup(files: files, strategy: keepStrategy)

            groups.append(GroupResult(
                groupId: 0,
                fileCount: files.count,
                maxScore: maxScore,
                minScore: minScore,
                avgScore: avgScore,
                files: files,
                pairs: groupPairs,
                keep: keep
            ))
        }

        groups.sort { $0.maxScore > $1.maxScore }
        for i in groups.indices {
            groups[i].groupId = i + 1
        }

        return groups
    }

    // MARK: - Bulk Action Candidates

    /// Compute the de-duplicated list of files eligible for bulk action.
    /// Ported from `ResultsState.bulkActionCandidates()` — takes `DisplayState` as parameter
    /// instead of reading mutable stored properties.
    func bulkActionCandidates(display: DisplayState) -> (candidates: [BulkCandidate], strategy: String?) {
        var seen = Set<String>()
        var candidates: [BulkCandidate] = []

        if isPairMode, display.viewMode == .groups, let groups = synthesizedGroups {
            collectGroupCandidates(from: groups, display: display, into: &candidates, seen: &seen)
        } else if !isPairMode, display.viewMode == .pairs {
            if case .groups(let groups) = envelope.content {
                if display.isSelectMode {
                    let activeSelections = display.selectedForAction.subtracting(ignoredPairs).filter { pair in
                        !actionedPaths.contains(pair.fileA) && !actionedPaths.contains(pair.fileB)
                    }
                    let selectedFiles = Set(activeSelections.flatMap { [$0.fileA, $0.fileB] })
                    for group in groups {
                        guard let keepPath = group.keep else { continue }
                        for file in group.files {
                            guard file.path != keepPath && !file.isReference else { continue }
                            guard selectedFiles.contains(file.path) else { continue }
                            guard !actionedPaths.contains(file.path) else { continue }
                            guard seen.insert(file.path).inserted else { continue }
                            candidates.append(BulkCandidate(path: file.path, size: file.fileSize))
                        }
                    }
                } else {
                    collectGroupCandidates(from: groups, display: display, into: &candidates, seen: &seen)
                }
            }
        } else {
            switch envelope.content {
            case .pairs(let pairs):
                collectPairCandidates(from: pairs, display: display, into: &candidates, seen: &seen)
            case .groups(let groups):
                collectGroupCandidates(from: groups, display: display, into: &candidates, seen: &seen)
            }
        }

        return (candidates: candidates, strategy: envelope.args.keep)
    }

    private func collectPairCandidates(
        from pairs: [PairResult],
        display: DisplayState,
        into candidates: inout [BulkCandidate],
        seen: inout Set<String>
    ) {
        for pair in pairs {
            guard !actionedPaths.contains(pair.fileA) && !actionedPaths.contains(pair.fileB)
            else { continue }
            let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
            guard resolutions[pairID] == nil else { continue }
            if display.isSelectMode {
                guard display.selectedForAction.contains(pairID) else { continue }
            }
            guard !ignoredPairs.contains(pairID) else { continue }
            guard let keepPath = pair.keepPath else { continue }
            let candidatePath: String
            let candidateSize: Int
            let candidateIsReference: Bool
            if keepPath == pair.fileA {
                candidatePath = pair.fileB
                candidateSize = pair.fileBMetadata.fileSize
                candidateIsReference = pair.fileBIsReference
            } else {
                candidatePath = pair.fileA
                candidateSize = pair.fileAMetadata.fileSize
                candidateIsReference = pair.fileAIsReference
            }
            guard !candidateIsReference else { continue }
            guard seen.insert(candidatePath).inserted else { continue }
            candidates.append(BulkCandidate(path: candidatePath, size: candidateSize))
        }
    }

    private func collectGroupCandidates(
        from groups: [GroupResult],
        display: DisplayState,
        into candidates: inout [BulkCandidate],
        seen: inout Set<String>
    ) {
        let resolvedPaths = computeResolvedOrMissingPaths()
        for group in groups {
            let groupCandidates: [GroupFile]
            if let keepPath = group.keep {
                groupCandidates = group.files.filter { $0.path != keepPath && !$0.isReference }
            } else {
                groupCandidates = group.files.filter { !$0.isReference }
            }
            let allResolved = !groupCandidates.isEmpty && groupCandidates.allSatisfy {
                resolvedPaths.contains($0.path)
            }
            if allResolved { continue }

            if display.isSelectMode {
                guard display.selectedGroupsForAction.contains(group.groupId) else { continue }
            }
            let allIgnored = !group.pairs.isEmpty && group.pairs.allSatisfy { gp in
                ignoredPairs.contains(PairIdentifier(fileA: gp.fileA, fileB: gp.fileB))
            }
            if allIgnored { continue }
            guard let keepPath = group.keep else { continue }
            for file in group.files {
                guard file.path != keepPath && !file.isReference else { continue }
                guard !actionedPaths.contains(file.path) else { continue }
                guard seen.insert(file.path).inserted else { continue }
                candidates.append(BulkCandidate(path: file.path, size: file.fileSize))
            }
        }
    }

    // MARK: - View Synthesis

    /// Flatten groups into pairs by joining each GroupPair with its members' metadata.
    static func synthesizePairs(from groups: [GroupResult]) -> [PairResult] {
        var pairs: [PairResult] = []
        for group in groups {
            let fileMap = Dictionary(
                group.files.map { ($0.path, $0) },
                uniquingKeysWith: { first, _ in first }
            )
            for gp in group.pairs {
                let fileA = fileMap[gp.fileA]
                let fileB = fileMap[gp.fileB]
                let keep: String?
                if let keepPath = group.keep {
                    if keepPath == gp.fileA { keep = "a" }
                    else if keepPath == gp.fileB { keep = "b" }
                    else { keep = nil }
                } else {
                    keep = nil
                }
                pairs.append(PairResult(
                    fileA: gp.fileA,
                    fileB: gp.fileB,
                    score: gp.score,
                    breakdown: gp.breakdown,
                    detail: gp.detail,
                    fileAMetadata: fileA.map(Self.metadata(from:)) ?? FileMetadata(fileSize: 0),
                    fileBMetadata: fileB.map(Self.metadata(from:)) ?? FileMetadata(fileSize: 0),
                    fileAIsReference: fileA?.isReference ?? false,
                    fileBIsReference: fileB?.isReference ?? false,
                    keep: keep
                ))
            }
        }
        return pairs
    }

    /// Mirrors the CLI's `pick_keep_from_group()` logic.
    static func pickKeepFromGroup(files: [GroupFile], strategy: String?) -> String? {
        guard let strategy, files.count >= 2 else {
            return files.count == 1 ? files[0].path : nil
        }

        switch strategy {
        case "newest":
            return pickBest(files, key: \.mtime, higherWins: true)
        case "oldest":
            return pickBest(files, key: \.mtime, higherWins: false)
        case "biggest":
            return pickBestSize(files, biggerWins: true)
        case "smallest":
            return pickBestSize(files, biggerWins: false)
        case "longest":
            return pickBest(files, key: \.duration, higherWins: true)
        case "highest-res":
            return pickBest(files, key: { f in
                guard let w = f.width, let h = f.height else { return nil }
                return Double(w * h)
            }, higherWins: true)
        default:
            return nil
        }
    }

    /// Assign stable display IDs to synthesized groups.
    mutating func assignStableIDs(to groups: inout [GroupResult]) {
        for i in groups.indices {
            let memberSet = Set(groups[i].files.map(\.path))

            if let (cachedSet, cachedID) = stableGroupIDMap
                .filter({ memberSet.isSubset(of: $0.key) })
                .min(by: { $0.key.count < $1.key.count }) {
                groups[i].groupId = cachedID
                if memberSet != cachedSet {
                    stableGroupIDMap.removeValue(forKey: cachedSet)
                    stableGroupIDMap[memberSet] = cachedID
                }
            } else {
                let id = nextStableGroupID
                nextStableGroupID += 1
                groups[i].groupId = id
                stableGroupIDMap[memberSet] = id
            }
        }
    }

    // MARK: - Mutating Helpers

    mutating func incrementFilterGeneration() {
        filterGeneration &+= 1
    }

    /// Rebuild `scoreDistribution` and `filetypeBreakdown` from the current
    /// pair set so Insights stays in sync after watch-mode pair appends.
    /// `directoryStats` and `creationTimeline` are preserved from the
    /// original scan (they describe scanned scope, not found pairs).
    mutating func recomputeAnalytics() {
        guard let existing = analyticsData else { return }
        guard case .pairs(let pairs) = envelope.content else { return }
        analyticsData = AnalyticsData(
            directoryStats: existing.directoryStats,
            scoreDistribution: Self.buildScoreDistribution(from: pairs),
            filetypeBreakdown: Self.buildFiletypeBreakdown(from: pairs),
            creationTimeline: existing.creationTimeline
        )
        envelope.analytics = analyticsData
    }

    /// Build score histogram with 5-point buckets matching the CLI's analytics.py.
    private static func buildScoreDistribution(from pairs: [PairResult]) -> [ScoreBucket] {
        guard !pairs.isEmpty else { return [] }
        let bucketSize = 5
        let ceilMax = 100
        let lastBucketStart = ceilMax - bucketSize
        var counts: [Int: Int] = [:]
        var floorMin = lastBucketStart
        for pair in pairs {
            var start = Int(pair.score) / bucketSize * bucketSize
            if start >= ceilMax { start = lastBucketStart }
            counts[start, default: 0] += 1
            floorMin = min(floorMin, start)
        }
        return stride(from: floorMin, to: ceilMax, by: bucketSize).map { start in
            ScoreBucket(range: "\(start)-\(start + bucketSize)", min: start, max: start + bucketSize, count: counts[start, default: 0])
        }
    }

    /// Build filetype breakdown deduplicated by path, matching the CLI's analytics.py.
    private static func buildFiletypeBreakdown(from pairs: [PairResult]) -> [FiletypeEntry] {
        guard !pairs.isEmpty else { return [] }
        var files: [String: Int] = [:] // path → fileSize
        for pair in pairs {
            files[pair.fileA] = pair.fileAMetadata.fileSize
            files[pair.fileB] = pair.fileBMetadata.fileSize
        }
        var extCount: [String: Int] = [:]
        var extSize: [String: Int] = [:]
        for (path, size) in files {
            let ext = (path as NSString).pathExtension.lowercased()
            let key = ext.isEmpty ? "(none)" : ".\(ext)"
            extCount[key, default: 0] += 1
            extSize[key, default: 0] += size
        }
        return extCount.keys.sorted { extCount[$0]! > extCount[$1]! }.map { key in
            FiletypeEntry(ext: key, count: extCount[key]!, size: extSize[key]!)
        }
    }

    /// Estimate recoverable space from the current pair set, matching the
    /// CLI's `_compute_space_recoverable` pair-mode logic: pick the smaller
    /// non-reference file per pair, deduplicated by path.
    func computeSpaceRecoverable() -> Int {
        guard case .pairs(let pairs) = envelope.content else { return 0 }
        var seen = Set<String>()
        var total = 0
        for pair in pairs {
            if pair.fileAIsReference, pair.fileBIsReference { continue }
            let candidatePath: String
            let candidateSize: Int
            if pair.fileAIsReference {
                candidatePath = pair.fileB
                candidateSize = pair.fileBMetadata.fileSize
            } else if pair.fileBIsReference || pair.fileAMetadata.fileSize <= pair.fileBMetadata.fileSize {
                candidatePath = pair.fileA
                candidateSize = pair.fileAMetadata.fileSize
            } else {
                candidatePath = pair.fileB
                candidateSize = pair.fileBMetadata.fileSize
            }
            if seen.insert(candidatePath).inserted {
                total += candidateSize
            }
        }
        return total
    }

    // MARK: - Raw Filtered Views (Shared)

    /// Compute raw filtered pairs: excludes actioned and ignored,
    /// but does NOT apply search, sort, or resolution-aware partitioning.
    /// Used by view mode toggle and synthesized view rebuilds.
    func rawFilteredPairs(viewMode: DisplayState.ViewMode) -> [PairResult] {
        let pairs: [PairResult]
        if !isPairMode, viewMode == .pairs, let synthesized = synthesizedPairs {
            pairs = synthesized
        } else if case .pairs(let envPairs) = envelope.content {
            pairs = envPairs
        } else if let synthesized = synthesizedPairs {
            pairs = synthesized
        } else {
            return []
        }

        let actioned = actionedPaths
        return pairs.filter { pair in
            let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
            if actioned.contains(pair.fileA) || actioned.contains(pair.fileB) { return false }
            if ignoredPairs.contains(pairID) { return false }
            return true
        }
    }

    /// Compute raw filtered groups: excludes fully-actioned and fully-ignored groups.
    /// Used by view mode toggle and synthesized view rebuilds.
    func rawFilteredGroups(viewMode: DisplayState.ViewMode) -> [GroupResult] {
        let groups: [GroupResult]
        if isPairMode, viewMode == .groups, let synthesized = synthesizedGroups {
            groups = synthesized
        } else if case .groups(let envGroups) = envelope.content {
            groups = envGroups
        } else if let synthesized = synthesizedGroups {
            groups = synthesized
        } else {
            return []
        }

        let actioned = actionedPaths
        return groups.filter { group in
            let candidates = group.files.filter { $0.path != group.keep && !$0.isReference }
            let allActioned = !candidates.isEmpty && candidates.allSatisfy {
                actioned.contains($0.path)
            }
            if allActioned { return false }
            let allIgnored = !group.pairs.isEmpty && group.pairs.allSatisfy { gp in
                ignoredPairs.contains(PairIdentifier(fileA: gp.fileA, fileB: gp.fileB))
            }
            return !allIgnored
        }
    }

    // MARK: - Private Helpers

    /// Format byte count to human-readable string (e.g. "1.5 MB").
    nonisolated static func formatFileSize(_ bytes: Int) -> String {
        let units = ["B", "KB", "MB", "GB", "TB"]
        var value = Double(bytes)
        var unitIndex = 0
        while value >= 1024 && unitIndex < units.count - 1 {
            value /= 1024
            unitIndex += 1
        }
        if unitIndex == 0 {
            return "\(bytes) B"
        }
        return String(format: "%.1f %@", value, units[unitIndex])
    }

    private func applyDirectoryFilter(_ pairs: [PairResult], directory: String?) -> [PairResult] {
        guard let dir = directory else { return pairs }
        let prefix = dir.hasSuffix("/") ? dir : dir + "/"
        return pairs.filter { pair in
            pair.fileA.hasPrefix(prefix) || pair.fileB.hasPrefix(prefix)
        }
    }

    private func applyDirectoryFilterGroups(_ groups: [GroupResult], directory: String?) -> [GroupResult] {
        guard let dir = directory else { return groups }
        let prefix = dir.hasSuffix("/") ? dir : dir + "/"
        return groups.filter { group in
            group.files.contains { $0.path.hasPrefix(prefix) }
        }
    }

    private func applySearch(_ pairs: [PairResult], searchText: String) -> [PairResult] {
        guard !searchText.isEmpty else { return pairs }
        return pairs.filter { pair in
            pair.fileA.localizedCaseInsensitiveContains(searchText)
                || pair.fileB.localizedCaseInsensitiveContains(searchText)
        }
    }

    private func applySortPairs(_ pairs: [PairResult], sortOrder: ResultSortOrder) -> [PairResult] {
        switch sortOrder {
        case .scoreDescending:
            return pairs.sorted { $0.score > $1.score }
        case .scoreAscending:
            return pairs.sorted { $0.score < $1.score }
        case .sizeDescending:
            return pairs.sorted { a, b in
                let sizeA = a.fileAMetadata.fileSize + a.fileBMetadata.fileSize
                let sizeB = b.fileAMetadata.fileSize + b.fileBMetadata.fileSize
                return sizeA > sizeB
            }
        case .pathAscending:
            return pairs.sorted { $0.fileA.localizedCompare($1.fileA) == .orderedAscending }
        }
    }

    /// Convert a FileMetadata to a GroupFile.
    private static func groupFile(path: String, metadata m: FileMetadata, isReference: Bool) -> GroupFile {
        GroupFile(
            path: path, duration: m.duration, width: m.width, height: m.height,
            fileSize: m.fileSize, codec: m.codec, bitrate: m.bitrate,
            framerate: m.framerate, audioChannels: m.audioChannels, mtime: m.mtime,
            tagTitle: m.tagTitle, tagArtist: m.tagArtist, tagAlbum: m.tagAlbum,
            isReference: isReference, thumbnail: m.thumbnail
        )
    }

    /// Convert a GroupFile to a FileMetadata.
    private static func metadata(from file: GroupFile) -> FileMetadata {
        FileMetadata(
            duration: file.duration,
            width: file.width,
            height: file.height,
            fileSize: file.fileSize,
            codec: file.codec,
            bitrate: file.bitrate,
            framerate: file.framerate,
            audioChannels: file.audioChannels,
            mtime: file.mtime,
            tagTitle: file.tagTitle,
            tagArtist: file.tagArtist,
            tagAlbum: file.tagAlbum,
            thumbnail: file.thumbnail
        )
    }

    /// Generic N-member comparison with nil handling and file-size tiebreaker.
    private static func pickBest(
        _ files: [GroupFile],
        key: (GroupFile) -> Double?,
        higherWins: Bool
    ) -> String? {
        let candidates = files.compactMap { f -> (GroupFile, Double)? in
            guard let v = key(f) else { return nil }
            return (f, v)
        }
        guard candidates.count >= 2 else {
            return candidates.first?.0.path
        }

        let sorted = candidates.sorted { a, b in
            if a.1 != b.1 { return higherWins ? a.1 > b.1 : a.1 < b.1 }
            return a.0.fileSize > b.0.fileSize
        }

        let (bestFile, bestVal) = sorted[0]
        let secondVal = sorted[1].1
        if bestVal != secondVal { return bestFile.path }

        let tied = sorted.filter { $0.1 == bestVal }.map(\.0)
            .sorted { $0.fileSize > $1.fileSize }
        if tied[0].fileSize > tied[1].fileSize { return tied[0].path }
        return nil
    }

    /// Convenience overload for KeyPath-based key extraction.
    private static func pickBest(
        _ files: [GroupFile],
        key keyPath: KeyPath<GroupFile, Double?>,
        higherWins: Bool
    ) -> String? {
        pickBest(files, key: { $0[keyPath: keyPath] }, higherWins: higherWins)
    }

    /// Size-based selection with no secondary tiebreaker.
    private static func pickBestSize(_ files: [GroupFile], biggerWins: Bool) -> String? {
        guard files.count >= 2 else { return files.first?.path }
        let sorted = files.sorted {
            biggerWins ? $0.fileSize > $1.fileSize : $0.fileSize < $1.fileSize
        }
        if sorted[0].fileSize == sorted[1].fileSize { return nil }
        return sorted[0].path
    }
}

// MARK: - Session

/// Unified session state -- the single source of truth for a deduplication session.
///
/// Replaces the fragmented state across `ScanStore`, `ResultsStore`, `WatchSessionManager`,
/// `ScanHistoryManager`, and `AppState`.
struct Session: Equatable, Sendable {

    /// Phase state machine for a session.
    enum Phase: Equatable, Sendable {
        case setup
        case scanning
        case results
        case error(ErrorInfo)
    }

    // MARK: - Identity

    /// Unique identifier for this session instance.
    /// Reset to a fresh UUID each time a new scan starts, so that each scan
    /// gets its own entry in the session registry / scan history.
    var id: UUID

    // MARK: - Phase Machine

    /// Current lifecycle phase.
    var phase: Phase

    // MARK: - Config

    /// The scan configuration for this session, if a scan has been configured.
    var config: SessionConfig?

    // MARK: - Sub-States

    /// Progress state while scanning. Non-nil when phase is `.scanning`.
    var scan: ScanProgress?

    /// Results snapshot after scan completes. Non-nil when phase is `.results`.
    var results: ResultsSnapshot?

    /// Watch session state, if a background watch is active.
    var watch: WatchState?

    /// UI display state (view mode, search, sort, selection).
    var display: DisplayState

    /// Metadata for history and persistence.
    var metadata: SessionMetadata

    // MARK: - Replay

    /// URL of a pending replay file opened from Finder.
    var pendingReplayURL: URL?

    // MARK: - Scan Sequence

    /// Monotonically increasing counter -- incremented each time a new scan starts.
    /// Used as SwiftUI view identity to force ProgressScreen recreation.
    var scanSequence: UInt

    // MARK: - Saved State From Previous Scans

    /// The config from the last completed scan (for re-scan / refine).
    var lastScanConfig: SessionConfig?

    /// Raw envelope bytes from the last completed scan (for lossless export/replay).
    var lastOriginalEnvelope: Data?

    /// Session ID of the last paused session (for resume prompts).
    var lastPausedSessionId: String?

    /// A pending session that can be resumed.
    var pendingSession: SessionInfo?

    // MARK: - Init

    init(
        id: UUID = UUID(),
        phase: Phase = .setup,
        config: SessionConfig? = nil,
        scan: ScanProgress? = nil,
        results: ResultsSnapshot? = nil,
        watch: WatchState? = nil,
        display: DisplayState = DisplayState(viewMode: .pairs),
        metadata: SessionMetadata = SessionMetadata(),
        pendingReplayURL: URL? = nil,
        scanSequence: UInt = 0,
        lastScanConfig: SessionConfig? = nil,
        lastOriginalEnvelope: Data? = nil,
        lastPausedSessionId: String? = nil,
        pendingSession: SessionInfo? = nil
    ) {
        self.id = id
        self.phase = phase
        self.config = config
        self.scan = scan
        self.results = results
        self.watch = watch
        self.display = display
        self.metadata = metadata
        self.pendingReplayURL = pendingReplayURL
        self.scanSequence = scanSequence
        self.lastScanConfig = lastScanConfig
        self.lastOriginalEnvelope = lastOriginalEnvelope
        self.lastPausedSessionId = lastPausedSessionId
        self.pendingSession = pendingSession
    }
}
