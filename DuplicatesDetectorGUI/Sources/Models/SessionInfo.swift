import Foundation

/// Rich metadata for a saved scan session, decoded from CLI `--list-sessions-json`.
struct SessionInfo: Decodable, Sendable, Identifiable {
    var id: String { sessionId }

    let sessionId: String
    let directories: [String]
    let config: [String: AnyCodable]
    let completedStages: [String]
    let activeStage: String
    let totalFiles: Int
    let elapsedSeconds: Double
    let createdAt: Double
    let pausedAt: String?
    /// Conservative progress percentage (0–100) based on completed pipeline stages.
    /// Defaults to 0 for backward compatibility with older CLI output that lacks this field.
    let progressPercent: Int

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case directories, config
        case completedStages = "completed_stages"
        case activeStage = "active_stage"
        case totalFiles = "total_files"
        case elapsedSeconds = "elapsed_seconds"
        case createdAt = "created_at"
        case pausedAt = "paused_at"
        case progressPercent = "progress_percent"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sessionId = try container.decode(String.self, forKey: .sessionId)
        directories = try container.decode([String].self, forKey: .directories)
        config = try container.decode([String: AnyCodable].self, forKey: .config)
        completedStages = try container.decode([String].self, forKey: .completedStages)
        activeStage = try container.decode(String.self, forKey: .activeStage)
        totalFiles = try container.decode(Int.self, forKey: .totalFiles)
        elapsedSeconds = try container.decode(Double.self, forKey: .elapsedSeconds)
        createdAt = try container.decode(Double.self, forKey: .createdAt)
        pausedAt = try container.decodeIfPresent(String.self, forKey: .pausedAt)
        progressPercent = try container.decodeIfPresent(Int.self, forKey: .progressPercent) ?? 0
    }

    var mode: String {
        (config["mode"]?.stringValue) ?? "video"
    }

    var relativePausedAt: String? {
        guard let iso = pausedAt else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: iso) else { return nil }
        let rel = RelativeDateTimeFormatter()
        rel.unitsStyle = .full
        return rel.localizedString(for: date, relativeTo: Date())
    }
}

/// Type-erased Codable wrapper for flexible JSON dict values (Sendable-safe).
enum AnyCodable: Decodable, Sendable, Equatable {
    case string(String)
    case bool(Bool)
    case int(Int)
    case double(Double)
    case null

    var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    var boolValue: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }

    var intValue: Int? {
        if case .int(let i) = self { return i }
        return nil
    }

    var doubleValue: Double? {
        if case .double(let d) = self { return d }
        if case .int(let i) = self { return Double(i) }
        return nil
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let s = try? container.decode(String.self) { self = .string(s) }
        else if let b = try? container.decode(Bool.self) { self = .bool(b) }
        else if let i = try? container.decode(Int.self) { self = .int(i) }
        else if let d = try? container.decode(Double.self) { self = .double(d) }
        else { self = .null }
    }
}
