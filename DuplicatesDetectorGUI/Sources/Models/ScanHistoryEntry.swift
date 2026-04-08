// MARK: - Legacy (migration only — Task 11 will integrate into SessionRegistry)
import Foundation

/// Lightweight metadata for a saved scan, stored as a `.meta.json` sidecar.
struct ScanHistoryEntry: Identifiable, Sendable, Codable {
    let id: UUID
    let date: Date
    let directories: [String]
    let mode: String
    let pairCount: Int
    let groupCount: Int?
    let duration: Double
    let fileCount: Int
    let envelopeFilename: String
}

/// Sendable metadata extracted from a ScanEnvelope for history persistence.
///
/// Used to cross the `@MainActor` → `ScanHistoryManager` actor boundary
/// without sending the full (non-Sendable) envelope.
struct HistoryMetadata: Equatable, Sendable {
    let directories: [String]
    let mode: String
    let pairCount: Int
    let groupCount: Int?
    let duration: Double
    let fileCount: Int

    init(from envelope: ScanEnvelope) {
        directories = envelope.args.directories
        mode = envelope.args.mode
        fileCount = envelope.stats.filesScanned
        duration = envelope.stats.totalTime
        switch envelope.content {
        case .pairs(let pairs):
            pairCount = pairs.count
            groupCount = nil
        case .groups(let groups):
            pairCount = groups.reduce(0) { $0 + $1.pairs.count }
            groupCount = groups.count
        }
    }
}
