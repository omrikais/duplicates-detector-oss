import Foundation

/// Parses a complete JSON envelope from scan output.
enum JSONEnvelopeParser {
    /// Parse a `ScanEnvelope` from raw JSON data.
    static func parse(data: Data) throws -> ScanEnvelope {
        try CLIDecoder.shared.decode(ScanEnvelope.self, from: data)
    }

    /// Parse a `ScanEnvelope` from a JSON string.
    static func parse(string: String) throws -> ScanEnvelope {
        guard let data = string.data(using: .utf8) else {
            throw DecodingError.dataCorrupted(
                .init(codingPath: [], debugDescription: "Invalid UTF-8 string")
            )
        }
        return try parse(data: data)
    }
}
