import Foundation

/// Shared JSON decoder configured for CLI output (snake_case → camelCase keys).
///
/// Used by all parsers and any ad-hoc decode site that reads CLI JSON.
enum CLIDecoder {
    static let shared: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
}

/// A `CodingKey` that accepts any string, for dynamic JSON keys.
struct DynamicCodingKey: CodingKey, Sendable {
    var stringValue: String
    var intValue: Int?

    init(stringValue: String) {
        self.stringValue = stringValue
        self.intValue = nil
    }

    init?(intValue: Int) {
        self.stringValue = String(intValue)
        self.intValue = intValue
    }
}

// NOTE ON COMPARATOR KEY CONSISTENCY:
//
// All dicts keyed by comparator name (`breakdown`, `detail`, `weights`) MUST
// decode through a path that applies `convertFromSnakeCase` so that keys like
// `file_size` become `fileSize` uniformly. Swift's `Dictionary<String, T>`
// Decodable conformance does NOT apply the decoder's key strategy — it keeps
// raw JSON keys. Two patterns are used to work around this:
//
//   1. `nestedContainer(keyedBy: DynamicCodingKey.self)` — used by
//      `decodeNullableDoubleDict` (breakdown) and `decodeDetailDict` (detail)
//      in `PairResult` and `GroupPair`.
//
//   2. `ComparatorWeights` wrapper — used by `ScanArgs.weights`; manually
//      applies snake→camel conversion since synthesized Codable can't use
//      nestedContainer.
//
// Do NOT replace these with plain `[String: T]` decode — it will silently
// break key consistency between weights, breakdown, and detail dicts.

/// Decode a `[String: Double?]` dict where values may be JSON `null`.
///
/// Standard `Codable` doesn't handle nullable dict values cleanly,
/// so we iterate keys and check `decodeNil` for each.
func decodeNullableDoubleDict<K: CodingKey>(
    from container: KeyedDecodingContainer<K>,
    forKey key: K
) throws -> [String: Double?] {
    let nested = try container.nestedContainer(
        keyedBy: DynamicCodingKey.self, forKey: key
    )
    var result: [String: Double?] = [:]
    for k in nested.allKeys {
        if try nested.decodeNil(forKey: k) {
            result[k.stringValue] = nil as Double?
        } else {
            result[k.stringValue] = try nested.decode(Double.self, forKey: k)
        }
    }
    return result
}

/// Decode a `[String: V]` dict via `nestedContainer` so keys go through
/// the decoder's key strategy (e.g., `convertFromSnakeCase`).
func decodeDetailDict<K: CodingKey, V: Decodable>(
    from container: KeyedDecodingContainer<K>,
    forKey key: K
) throws -> [String: V] {
    let nested = try container.nestedContainer(
        keyedBy: DynamicCodingKey.self, forKey: key
    )
    var result: [String: V] = [:]
    for k in nested.allKeys {
        result[k.stringValue] = try nested.decode(V.self, forKey: k)
    }
    return result
}
