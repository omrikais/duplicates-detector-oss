import Foundation
import UniformTypeIdentifiers

/// A single item in a bulk file-action request.
///
/// Wraps the `(PairID, String, ActionType)` tuple so the compiler can
/// auto-synthesize `Equatable` for `SessionEffect`.
struct BulkActionItem: Sendable, Equatable {
    let pairID: PairID
    let filePath: String
    let action: ActionType
}

/// Side effects returned by the session reducer. Executed by the session store.
///
/// Consolidates the former `ScanEffect` and `ResultsEffect` into a single enum
/// so all side effects flow through one execution layer.
enum SessionEffect: Sendable, Equatable {

    // MARK: - Scan

    case runScan(SessionConfig)
    case runPhotosScan(PhotosScope, SessionConfig)
    case loadReplayData(URL)
    case cancelCLI
    case sendPauseSignal
    case sendResumeSignal
    case writePauseCommand(URL, String)
    case removePauseFile(URL)
    case schedulePauseTimeout(TimeInterval)
    case cancelPauseTimeout
    case configureResults(ScanEnvelope?, Data?, SessionConfig, Data?)
    case scheduleMinimumDisplay(Date?)
    case cleanupTempReplayFile(URL)

    // MARK: - File Actions

    case performFileAction(ActionType, String, PairID)
    case executeBulk([BulkActionItem])
    case addToIgnoreList(String, String, URL?)
    case removeFromIgnoreList(String, String, URL?, Set<PairID>)
    case clearIgnoreList(Set<PairID>, URL?)

    // MARK: - Watch

    case startWatch(SessionConfig, [KnownFile])
    case stopWatch

    // MARK: - Filesystem Monitor

    case startFileMonitor([String])
    case expandFileMonitor([String])
    case stopFileMonitor
    case checkFileStatuses([String])

    // MARK: - Persistence

    case saveSession
    case saveSessionDebounced
    case loadSession(UUID)
    case deleteSession(UUID)
    case deleteCliSession(String)
    case pruneOldSessions(Int)
    case exportSession(UUID, URL, ExportFormat)

    // MARK: - Cached Views

    case rebuildSynthesizedViews

    // MARK: - Navigation

    case activateWindow
    case persistSessionId(String?)

    // MARK: - Action Log

    case writeActionLog(ActionRecord)
}

// MARK: - ExportFormat

/// Supported export formats for session data.
enum ExportFormat: Sendable, Equatable {
    case json
    case html
    case csv
    case shell

    /// The UTType for formats that produce files via NSSavePanel.
    var contentType: UTType {
        switch self {
        case .json: .json
        case .html: .html
        case .csv: .commaSeparatedText
        case .shell: .shellScript
        }
    }

    /// Human-readable name shown in error messages.
    var displayName: String {
        switch self {
        case .json: "JSON"
        case .html: "HTML"
        case .csv: "CSV"
        case .shell: "shell script"
        }
    }

    /// Default filename when saving via NSSavePanel.
    var defaultFileName: String {
        switch self {
        case .json: "scan-results.ddscan"
        case .html: "scan-results.html"
        case .csv: "scan-results.csv"
        case .shell: "scan-results.sh"
        }
    }

    /// CLI `--format` flag value for replay-based export (html/shell only).
    var cliFormatString: String? {
        switch self {
        case .html: "html"
        case .shell: "shell"
        case .json, .csv: nil
        }
    }
}
