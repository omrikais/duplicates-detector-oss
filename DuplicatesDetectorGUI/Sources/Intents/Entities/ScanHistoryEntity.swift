import AppIntents
import Foundation

/// Persistent entity representing a scan history entry.
///
/// Uses `ScanHistoryEntityQuery` to query entries from the `SessionRegistry`.
struct ScanHistoryEntity: AppEntity {
    nonisolated(unsafe) static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Scan History Entry")

    nonisolated(unsafe) static var defaultQuery = ScanHistoryEntityQuery()

    var id: UUID

    @Property(title: "Scan Date")
    var scanDate: Date

    @Property(title: "Directories")
    var directories: [String]

    @Property(title: "Mode")
    var mode: String

    @Property(title: "Pair Count")
    var pairCount: Int

    var displayRepresentation: DisplayRepresentation {
        let dirNames = directories.map { ($0 as NSString).lastPathComponent }.joined(separator: ", ")
        return DisplayRepresentation(
            title: "\(pairCount) pairs - \(mode)",
            subtitle: "\(dirNames)"
        )
    }

    init(id: UUID, scanDate: Date, directories: [String], mode: String, pairCount: Int) {
        self.id = id
        self.scanDate = scanDate
        self.directories = directories
        self.mode = mode
        self.pairCount = pairCount
    }

    /// Create from a `SessionRegistry.Entry`.
    init(from entry: SessionRegistry.Entry) {
        self.id = entry.id
        self.scanDate = entry.createdAt
        self.directories = entry.directories
        self.mode = entry.mode.rawValue
        self.pairCount = entry.pairCount
    }
}

// MARK: - Entity Query

/// Queries scan history entries from the `SessionRegistry`.
struct ScanHistoryEntityQuery: EntityQuery {
    func entities(for identifiers: [UUID]) async throws -> [ScanHistoryEntity] {
        guard let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() else { return [] }
        let entries = try await registry.listEntries()
        let idSet = Set(identifiers)
        return entries
            .filter { idSet.contains($0.id) }
            .map { ScanHistoryEntity(from: $0) }
    }

    func suggestedEntities() async throws -> [ScanHistoryEntity] {
        guard let registry = await DuplicatesDetectorShortcuts.resolvedRegistry() else { return [] }
        let entries = try await registry.listEntries()
        return Array(entries.prefix(10).map { ScanHistoryEntity(from: $0) })
    }
}
