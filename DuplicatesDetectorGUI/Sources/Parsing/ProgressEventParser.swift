import Foundation

/// Parses machine-progress JSON-lines from stderr.
enum ProgressEventParser {
    /// Parse a single line into a ``ProgressEvent``, returning `nil` for
    /// malformed or unrecognized lines (tolerant parsing).
    static func parseLine(_ line: String) -> ProgressEvent? {
        guard let data = line.data(using: .utf8) else { return nil }
        return parseLine(data)
    }

    /// Parse a single line (as `Data`) into a ``ProgressEvent``.
    static func parseLine(_ data: Data) -> ProgressEvent? {
        try? CLIDecoder.shared.decode(ProgressEvent.self, from: data)
    }

    /// Parse multiple lines (e.g., from a complete stderr capture).
    static func parseLines(_ text: String) -> [ProgressEvent] {
        text
            .split(separator: "\n", omittingEmptySubsequences: true)
            .compactMap { parseLine(String($0)) }
    }
}
