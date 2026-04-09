import Foundation

/// Resolution state of a duplicate pair in the results view.
enum PairResolutionStatus: Equatable, Sendable {
    /// Both files exist on disk, no prior action recorded.
    case active
    /// Explicitly actioned — sidecar record exists with action details.
    case resolved(HistoryAction)
    /// Legacy fallback — one or both files missing on disk, no sidecar record.
    case probablySolved(missing: [String])
}
