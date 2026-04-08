import Foundation

// MARK: - Analytics Data

/// Top-level analytics section from the JSON envelope.
struct AnalyticsData: Codable, Equatable, Sendable {
    let directoryStats: [DirectoryStat]
    let scoreDistribution: [ScoreBucket]
    let filetypeBreakdown: [FiletypeEntry]
    let creationTimeline: [TimelineEntry]
}

/// Per-directory duplicate statistics.
struct DirectoryStat: Codable, Equatable, Sendable, Identifiable {
    var id: String { path }
    let path: String
    let totalFiles: Int
    let duplicateFiles: Int
    let totalSize: Int
    let recoverableSize: Int
    let duplicateDensity: Double
}

/// A histogram bucket for score distribution.
struct ScoreBucket: Codable, Equatable, Sendable, Identifiable {
    var id: String { range }
    let range: String
    let min: Int
    let max: Int
    let count: Int
}

/// File-type breakdown entry.
struct FiletypeEntry: Codable, Equatable, Sendable, Identifiable {
    var id: String { ext }
    let ext: String
    let count: Int
    let size: Int

    enum CodingKeys: String, CodingKey {
        case ext = "extension"
        case count, size
    }
}

/// Timeline entry for duplicate creation dates.
struct TimelineEntry: Codable, Equatable, Sendable, Identifiable {
    var id: String { date }
    let date: String
    let totalFiles: Int
    let duplicateFiles: Int
}
