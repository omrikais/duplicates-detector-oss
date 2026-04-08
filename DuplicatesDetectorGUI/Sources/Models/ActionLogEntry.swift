// MARK: - Legacy (migration only — Task 11 will integrate into SessionRegistry)
import Foundation
import SwiftUI

/// Typed representation of CLI file-action strings.
enum FileAction: String, Sendable {
    case trashed
    case deleted
    case moved

    var color: Color {
        switch self {
        case .trashed: DDColors.warning
        case .deleted: DDColors.destructive
        case .moved: DDColors.accent
        }
    }

    var icon: String {
        switch self {
        case .trashed: "trash"
        case .deleted: "trash.slash"
        case .moved: "folder.badge.plus"
        }
    }

    var pastTenseCapitalized: String {
        switch self {
        case .trashed: "Trashed"
        case .deleted: "Deleted"
        case .moved: "Moved"
        }
    }
}

/// A single record from a JSON-lines action log file.
///
/// Compatible with both CLI-written and GUI-written records.
/// Fields are optional where the CLI may omit them (e.g., `destination` is only present for moves).
struct ActionLogEntry: Decodable, Identifiable, Sendable {
    let timestamp: String
    let action: String
    let path: String
    let score: Double?
    let strategy: String?
    let kept: String?
    let bytesFreed: Int?
    let destination: String?
    let dryRun: Bool?
    let source: String?

    let id = UUID()

    enum CodingKeys: String, CodingKey {
        case timestamp, action, path, score, strategy, kept
        case bytesFreed = "bytes_freed"
        case destination
        case dryRun = "dry_run"
        case source
    }

    /// The file name extracted from the full path.
    var fileName: String {
        (path as NSString).lastPathComponent
    }

    var fileAction: FileAction? { FileAction(rawValue: action) }

    /// SF Symbol name for the action type.
    var actionIcon: String {
        fileAction?.icon ?? "questionmark.circle"
    }
}

extension ActionLogEntry {
    /// JSON decoder for action log entries (no key strategy — uses manual CodingKeys).
    private static let decoder = JSONDecoder()

    /// Parse a JSON-lines action log file into an array of entries.
    ///
    /// Skips blank and malformed lines gracefully. Returns an empty array
    /// if the file doesn't exist or cannot be read.
    static func parseLogFile(at path: String) -> [ActionLogEntry] {
        guard let data = FileManager.default.contents(atPath: path) else { return [] }
        // Use lossy decoding (U+FFFD for invalid bytes) so a single corrupt
        // byte doesn't drop the entire file — matches the CLI's replacement
        // decoding behaviour used by --generate-undo.
        let content = String(decoding: data, as: UTF8.self)

        return content.components(separatedBy: .newlines).compactMap { line in
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty,
                  let lineData = trimmed.data(using: .utf8)
            else { return nil }
            return try? decoder.decode(ActionLogEntry.self, from: lineData)
        }
    }
}
