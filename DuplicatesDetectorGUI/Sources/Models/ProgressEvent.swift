import Foundation

/// Known pipeline stage names (stable API).
enum PipelineStage: String, Codable, Sendable {
    case scan
    case extract
    case filter
    case contentHash = "content_hash"
    case ssimExtract = "ssim_extract"
    case audioFingerprint = "audio_fingerprint"
    case score
    case thumbnail
    case report
    case replay
    case authorize
    case fetch
}

/// A machine-progress event emitted to stderr as JSON-lines.
enum ProgressEvent: Sendable {
    case stageStart(StageStartEvent)
    case progress(StageProgressEvent)
    case stageEnd(StageEndEvent)
    case sessionStart(SessionStartEvent)
    case pause(PauseEvent)
    case resume(ResumeEvent)
    case sessionEnd(SessionEndEvent)
}

extension ProgressEvent: Decodable {
    enum TypeKey: String, CodingKey {
        case type
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: TypeKey.self)
        let type = try c.decode(String.self, forKey: .type)

        switch type {
        case "stage_start":
            self = .stageStart(try StageStartEvent(from: decoder))
        case "progress":
            self = .progress(try StageProgressEvent(from: decoder))
        case "stage_end":
            self = .stageEnd(try StageEndEvent(from: decoder))
        case "session_start":
            self = .sessionStart(try SessionStartEvent(from: decoder))
        case "pause":
            self = .pause(try PauseEvent(from: decoder))
        case "resume":
            self = .resume(try ResumeEvent(from: decoder))
        case "session_end":
            self = .sessionEnd(try SessionEndEvent(from: decoder))
        default:
            throw DecodingError.dataCorrupted(
                .init(codingPath: [TypeKey.type],
                      debugDescription: "Unknown progress event type: \(type)")
            )
        }
    }
}

/// Emitted when a pipeline stage begins.
struct StageStartEvent: Sendable, Equatable {
    var stage: String
    var timestamp: String
    var total: Int?
}

extension StageStartEvent: Decodable {
    enum CodingKeys: String, CodingKey {
        case stage, timestamp, total
    }
}

/// Emitted periodically during a pipeline stage (throttled to 100ms).
struct StageProgressEvent: Sendable, Equatable {
    var stage: String
    var current: Int
    var timestamp: String
    var total: Int?
    var file: String?
    var rate: Double?
    var etaSeconds: Double?
    var cacheHits: Int?
    var cacheMisses: Int?

    init(
        stage: String, current: Int, timestamp: String,
        total: Int? = nil, file: String? = nil,
        rate: Double? = nil, etaSeconds: Double? = nil,
        cacheHits: Int? = nil, cacheMisses: Int? = nil
    ) {
        self.stage = stage
        self.current = current
        self.timestamp = timestamp
        self.total = total
        self.file = file
        self.rate = rate
        self.etaSeconds = etaSeconds
        self.cacheHits = cacheHits
        self.cacheMisses = cacheMisses
    }
}

extension StageProgressEvent: Decodable {
    // NOTE: CLIDecoder uses .convertFromSnakeCase which auto-converts
    // JSON snake_case keys to camelCase. Explicit raw values like
    // `= "eta_seconds"` would conflict (double-conversion), so we
    // let the decoder handle the mapping automatically.
    enum CodingKeys: String, CodingKey {
        case stage, current, timestamp, total, file, rate
        case etaSeconds
        case cacheHits
        case cacheMisses
    }
}

/// Emitted when a pipeline stage completes.
///
/// Contains fixed fields plus an `extras` dict for stage-specific data
/// (e.g., `hashed`, `fingerprinted`).
struct StageEndEvent: Sendable, Equatable {
    var stage: String
    var total: Int
    var elapsed: Double
    var timestamp: String
    var cacheHits: Int?
    var cacheMisses: Int?
    var extras: [String: Int]

    init(
        stage: String, total: Int, elapsed: Double, timestamp: String,
        cacheHits: Int? = nil, cacheMisses: Int? = nil, extras: [String: Int] = [:]
    ) {
        self.stage = stage
        self.total = total
        self.elapsed = elapsed
        self.timestamp = timestamp
        self.cacheHits = cacheHits
        self.cacheMisses = cacheMisses
        self.extras = extras
    }
}

extension StageEndEvent: Decodable {
    enum KnownKeys: String, CodingKey {
        case stage, total, elapsed, timestamp
        case cacheHits
        case cacheMisses
    }

    private static let knownKeyNames: Set<String> = [
        "type", "stage", "total", "elapsed", "timestamp",
        "cacheHits", "cacheMisses",
    ]

    init(from decoder: any Decoder) throws {
        let known = try decoder.container(keyedBy: KnownKeys.self)
        stage = try known.decode(String.self, forKey: .stage)
        total = try known.decode(Int.self, forKey: .total)
        elapsed = try known.decode(Double.self, forKey: .elapsed)
        timestamp = try known.decode(String.self, forKey: .timestamp)
        cacheHits = try known.decodeIfPresent(Int.self, forKey: .cacheHits)
        cacheMisses = try known.decodeIfPresent(Int.self, forKey: .cacheMisses)

        // Collect unknown keys as extras
        let dynamic = try decoder.container(keyedBy: DynamicCodingKey.self)
        var ext: [String: Int] = [:]
        for key in dynamic.allKeys where !Self.knownKeyNames.contains(key.stringValue) {
            if let intVal = try? dynamic.decode(Int.self, forKey: key) {
                ext[key.stringValue] = intVal
            }
        }
        extras = ext
    }
}

/// Emitted once at the start of a scan session.
struct SessionStartEvent: Sendable, Equatable, Decodable {
    var sessionId: String
    var wallStart: String
    var totalFiles: Int
    var stages: [String]
    var resumedFrom: String?
    var priorElapsedSeconds: Double?
}

/// Emitted once at the end of a scan session.
struct SessionEndEvent: Sendable, Equatable, Decodable {
    var sessionId: String
    var totalElapsed: Double
    var cacheTimeSaved: Double
    var timestamp: String?  // ISO 8601, optional for backward compat
}

/// Emitted when the scan is paused.
struct PauseEvent: Sendable, Equatable, Decodable {
    var sessionId: String
    var sessionFile: String
    var timestamp: String
}

/// Emitted when the scan is resumed.
struct ResumeEvent: Sendable, Equatable, Decodable {
    var sessionId: String
    var timestamp: String
}
