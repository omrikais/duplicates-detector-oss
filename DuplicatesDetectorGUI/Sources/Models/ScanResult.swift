import Foundation

// MARK: - Envelope

/// Top-level JSON envelope from `--format json --json-envelope`.
struct ScanEnvelope: Equatable, Sendable {
    var version: String
    var generatedAt: String
    var args: ScanArgs
    var stats: ScanStats
    var content: ScanContent
    var dryRunSummary: DryRunSummary?
    var analytics: AnalyticsData?
}

extension ScanEnvelope: Decodable {
    enum CodingKeys: String, CodingKey {
        case version, generatedAt, args, stats, pairs, groups, dryRunSummary, analytics
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decode(String.self, forKey: .version)
        generatedAt = try c.decode(String.self, forKey: .generatedAt)
        args = try c.decode(ScanArgs.self, forKey: .args)
        stats = try c.decode(ScanStats.self, forKey: .stats)
        dryRunSummary = try c.decodeIfPresent(DryRunSummary.self, forKey: .dryRunSummary)
        analytics = try c.decodeIfPresent(AnalyticsData.self, forKey: .analytics)

        if c.contains(.groups) {
            let groups = try c.decode([GroupResult].self, forKey: .groups)
            content = .groups(groups)
        } else {
            let pairs = try c.decode([PairResult].self, forKey: .pairs)
            content = .pairs(pairs)
        }
    }
}

/// Discriminated content: envelope contains either pairs or groups.
enum ScanContent: Equatable, Sendable {
    case pairs([PairResult])
    case groups([GroupResult])
}

// MARK: - Args & Stats

/// Mirrors the `args` dict in the JSON envelope.
struct ScanArgs: Codable, Equatable, Sendable {
    var directories: [String]
    var threshold: Int
    var content: Bool
    var contentMethod: String?
    var weights: ComparatorWeights?
    var keep: String?
    var action: String
    var group: Bool
    var sort: String
    var limit: Int?
    var minScore: Int?
    var exclude: [String]?
    var reference: [String]?
    var minSize: Int?
    var maxSize: Int?
    var minDuration: Double?
    var maxDuration: Double?
    var minResolution: String?
    var maxResolution: String?
    var minBitrate: String?
    var maxBitrate: String?
    var codec: String?
    var mode: String
    var embedThumbnails: Bool
    var thumbnailSize: [Int]?
}

/// Mirrors the `stats` dict in the JSON envelope.
struct ScanStats: Codable, Equatable, Sendable {
    var filesScanned: Int
    var filesAfterFilter: Int
    var totalPairsScored: Int
    var pairsAboveThreshold: Int
    var groupsCount: Int?
    var spaceRecoverable: Int?
    var scanTime: Double
    var extractTime: Double
    var filterTime: Double
    var contentHashTime: Double
    var scoringTime: Double
    var totalTime: Double
}

// MARK: - Pair result

/// A single scored pair from the CLI JSON output.
struct PairResult: Equatable, Sendable {
    var fileA: String
    var fileB: String
    var score: Double
    var breakdown: [String: Double?]
    var detail: [String: DetailScore]
    var fileAMetadata: FileMetadata
    var fileBMetadata: FileMetadata
    var fileAIsReference: Bool
    var fileBIsReference: Bool
    var keep: String?
}

extension PairResult {
    /// Resolves the CLI keep token ("a"/"b") to the actual file path.
    var keepPath: String? {
        switch keep {
        case "a": fileA
        case "b": fileB
        default: nil
        }
    }
}

extension PairResult: Decodable {
    enum CodingKeys: String, CodingKey {
        case fileA, fileB, score, breakdown, detail, fileAMetadata, fileBMetadata
        case fileAIsReference, fileBIsReference, keep
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        fileA = try c.decode(String.self, forKey: .fileA)
        fileB = try c.decode(String.self, forKey: .fileB)
        score = try c.decode(Double.self, forKey: .score)
        fileAMetadata = try c.decode(FileMetadata.self, forKey: .fileAMetadata)
        fileBMetadata = try c.decode(FileMetadata.self, forKey: .fileBMetadata)
        fileAIsReference = try c.decodeIfPresent(Bool.self, forKey: .fileAIsReference) ?? false
        fileBIsReference = try c.decodeIfPresent(Bool.self, forKey: .fileBIsReference) ?? false
        keep = try c.decodeIfPresent(String.self, forKey: .keep)

        // breakdown: { "filename": 45.0, "content": null, ... }
        breakdown = try decodeNullableDoubleDict(from: c, forKey: .breakdown)

        // detail: { "filename": [0.9, 50.0], ... }
        detail = try decodeDetailDict(from: c, forKey: .detail)
    }
}

/// Score detail for scan mode: decoded from `[raw, weight]` two-element array.
struct DetailScore: Sendable, Equatable {
    var raw: Double
    var weight: Double
}

extension DetailScore: Decodable {
    init(from decoder: any Decoder) throws {
        var c = try decoder.unkeyedContainer()
        raw = try c.decode(Double.self)
        weight = try c.decode(Double.self)
    }
}

// MARK: - Group result

/// A duplicate group from `--group` mode.
struct GroupResult: Equatable, Sendable {
    var groupId: Int
    var fileCount: Int
    var maxScore: Double
    var minScore: Double
    var avgScore: Double
    var files: [GroupFile]
    var pairs: [GroupPair]
    var keep: String?
}

extension GroupResult: Decodable {
    enum CodingKeys: String, CodingKey {
        case groupId, fileCount, maxScore, minScore, avgScore, files, pairs, keep
    }
}

/// A file within a group.
struct GroupFile: Codable, Equatable, Sendable {
    var path: String
    var duration: Double?
    var width: Int?
    var height: Int?
    var fileSize: Int
    var codec: String?
    var bitrate: Int?
    var framerate: Double?
    var audioChannels: Int?
    var mtime: Double?
    var tagTitle: String?
    var tagArtist: String?
    var tagAlbum: String?
    var isReference: Bool
    var thumbnail: String?
}

/// A pair within a group (no per-file metadata — that's on the group files).
struct GroupPair: Equatable, Sendable, Identifiable {
    var id: String { "\(fileA)\t\(fileB)" }
    var fileA: String
    var fileB: String
    var score: Double
    var breakdown: [String: Double?]
    var detail: [String: DetailScore]
}

extension GroupPair: Decodable {
    enum CodingKeys: String, CodingKey {
        case fileA, fileB, score, breakdown, detail
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        fileA = try c.decode(String.self, forKey: .fileA)
        fileB = try c.decode(String.self, forKey: .fileB)
        score = try c.decode(Double.self, forKey: .score)

        // breakdown: { "filename": 45.0, "content": null, ... }
        breakdown = try decodeNullableDoubleDict(from: c, forKey: .breakdown)

        // detail: { "filename": [0.9, 50.0], ... }
        detail = try decodeDetailDict(from: c, forKey: .detail)
    }
}

// MARK: - Dry-run summary

/// Optional dry-run output when `--dry-run --keep` is used.
struct DryRunSummary: Codable, Equatable, Sendable {
    var filesToDelete: [DryRunFile]
    var totalFiles: Int
    var totalBytes: Int
    var totalBytesHuman: String
    var strategy: String?
}

/// A file in the dry-run deletion list.
struct DryRunFile: Codable, Equatable, Sendable {
    var path: String
    var size: Int
    var sizeHuman: String
}

// MARK: - Comparator weights

/// Wraps `[String: Double]` but decodes via `nestedContainer` so that keys
/// go through `convertFromSnakeCase` (e.g., `file_size` → `fileSize`),
/// matching the key normalization used by `breakdown` and `detail` dicts.
struct ComparatorWeights: Sendable, Equatable {
    var values: [String: Double]
}

extension ComparatorWeights: Codable {
    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        // Decode into a nested keyed container so convertFromSnakeCase applies.
        // We re-decode from the raw data using a keyed wrapper.
        let raw = try container.decode([String: Double].self)
        // Dictionary decode bypasses convertFromSnakeCase, so manually apply
        // the same camelCase conversion the rest of the codebase gets.
        var converted: [String: Double] = [:]
        for (key, value) in raw {
            converted[Self.snakeToCamel(key)] = value
        }
        values = converted
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(values)
    }

    /// Convert a snake_case string to camelCase, matching JSONDecoder's
    /// `.convertFromSnakeCase` behavior.
    private static func snakeToCamel(_ s: String) -> String {
        let parts = s.split(separator: "_", omittingEmptySubsequences: false)
        guard let first = parts.first else { return s }
        return String(first) + parts.dropFirst().map { $0.capitalized }.joined()
    }
}

// MARK: - Encodable Conformances (for SessionRegistry persistence)

extension ScanEnvelope: Encodable {
    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(version, forKey: .version)
        try c.encode(generatedAt, forKey: .generatedAt)
        try c.encode(args, forKey: .args)
        try c.encode(stats, forKey: .stats)
        try c.encodeIfPresent(dryRunSummary, forKey: .dryRunSummary)
        try c.encodeIfPresent(analytics, forKey: .analytics)

        switch content {
        case .pairs(let pairs):
            try c.encode(pairs, forKey: .pairs)
        case .groups(let groups):
            try c.encode(groups, forKey: .groups)
        }
    }
}

extension ScanContent: Codable {
    private enum Tag: String, Codable {
        case pairs, groups
    }

    private enum CodingKeys: String, CodingKey {
        case tag, pairs, groups
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let tag = try c.decode(Tag.self, forKey: .tag)
        switch tag {
        case .pairs:
            let pairs = try c.decode([PairResult].self, forKey: .pairs)
            self = .pairs(pairs)
        case .groups:
            let groups = try c.decode([GroupResult].self, forKey: .groups)
            self = .groups(groups)
        }
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .pairs(let pairs):
            try c.encode(Tag.pairs, forKey: .tag)
            try c.encode(pairs, forKey: .pairs)
        case .groups(let groups):
            try c.encode(Tag.groups, forKey: .tag)
            try c.encode(groups, forKey: .groups)
        }
    }
}

extension PairResult: Encodable {
    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(fileA, forKey: .fileA)
        try c.encode(fileB, forKey: .fileB)
        try c.encode(score, forKey: .score)
        try c.encode(fileAMetadata, forKey: .fileAMetadata)
        try c.encode(fileBMetadata, forKey: .fileBMetadata)
        try c.encode(fileAIsReference, forKey: .fileAIsReference)
        try c.encode(fileBIsReference, forKey: .fileBIsReference)
        try c.encodeIfPresent(keep, forKey: .keep)

        // breakdown: encode nullable doubles
        try c.encode(breakdown.mapValues { $0 }, forKey: .breakdown)

        // detail: encode as [raw, weight] two-element arrays
        try c.encode(detail, forKey: .detail)
    }
}

extension DetailScore: Encodable {
    func encode(to encoder: any Encoder) throws {
        var c = encoder.unkeyedContainer()
        try c.encode(raw)
        try c.encode(weight)
    }
}

extension GroupResult: Encodable {
    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(groupId, forKey: .groupId)
        try c.encode(fileCount, forKey: .fileCount)
        try c.encode(maxScore, forKey: .maxScore)
        try c.encode(minScore, forKey: .minScore)
        try c.encode(avgScore, forKey: .avgScore)
        try c.encode(files, forKey: .files)
        try c.encode(pairs, forKey: .pairs)
        try c.encodeIfPresent(keep, forKey: .keep)
    }
}

extension GroupPair: Encodable {
    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(fileA, forKey: .fileA)
        try c.encode(fileB, forKey: .fileB)
        try c.encode(score, forKey: .score)
        try c.encode(breakdown.mapValues { $0 }, forKey: .breakdown)
        try c.encode(detail, forKey: .detail)
    }
}
