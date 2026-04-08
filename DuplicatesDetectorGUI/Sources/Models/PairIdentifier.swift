import Foundation

/// Stable pair identity for selection (not affected by sort/filter changes).
public struct PairIdentifier: Hashable, Codable, Sendable {
    public let fileA: String
    public let fileB: String
}

// MARK: - PairResult Convenience

extension PairResult {
    /// Stable identifier for list selection.
    var pairIdentifier: PairIdentifier {
        PairIdentifier(fileA: fileA, fileB: fileB)
    }
}
