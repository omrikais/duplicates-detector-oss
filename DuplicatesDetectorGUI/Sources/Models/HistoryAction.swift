import Foundation

/// A single user action persisted in the history sidecar (`.actions.json`).
///
/// Stores **original envelope paths** (unresolved) for direct matching against
/// `PairIdentifier.fileA`/`.fileB`. This differs from `ActionLogWriter` which
/// resolves symlinks before writing.
struct HistoryAction: Codable, Sendable, Equatable {
    let timestamp: String
    let action: String
    let path: String
    let kept: String?
    let bytesFreed: Int
    let score: Double
    let strategy: String?
    let destination: String?

    var fileAction: FileAction? { FileAction(rawValue: action) }
}

/// Top-level wrapper for the `.actions.json` sidecar file.
struct HistoryActionSidecar: Codable, Sendable, Equatable {
    let version: Int
    let actions: [HistoryAction]
}
