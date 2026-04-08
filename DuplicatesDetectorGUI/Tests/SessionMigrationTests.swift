import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Create a minimal legacy .meta.json content as Data.
private func makeLegacyMeta(
    id: UUID = UUID(),
    date: Date = Date(timeIntervalSince1970: 1_700_000_000),
    directories: [String] = ["/videos"],
    mode: String = "video",
    pairCount: Int = 3,
    groupCount: Int? = nil,
    duration: Double = 5.5,
    fileCount: Int = 100,
    envelopeFilename: String = "20250101-120000-video.ddscan"
) throws -> (Data, ScanHistoryEntry) {
    let entry = ScanHistoryEntry(
        id: id,
        date: date,
        directories: directories,
        mode: mode,
        pairCount: pairCount,
        groupCount: groupCount,
        duration: duration,
        fileCount: fileCount,
        envelopeFilename: envelopeFilename
    )
    let encoder = JSONEncoder()
    encoder.keyEncodingStrategy = .convertToSnakeCase
    encoder.dateEncodingStrategy = .iso8601
    let data = try encoder.encode(entry)
    return (data, entry)
}

/// Create a minimal .ddscan envelope Data.
private func makeLegacyEnvelope(
    directories: [String] = ["/videos"],
    mode: String = "video",
    threshold: Int = 50,
    pairCount: Int = 3
) throws -> Data {
    let pair = PairResult(
        fileA: "/videos/a.mp4",
        fileB: "/videos/b.mp4",
        score: 85.0,
        breakdown: ["filename": 40.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: 1_000_000),
        fileBMetadata: FileMetadata(fileSize: 900_000),
        fileAIsReference: false,
        fileBIsReference: false,
        keep: "a"
    )

    let envelope = ScanEnvelope(
        version: "1.0.0",
        generatedAt: "2025-01-01T12:00:00Z",
        args: ScanArgs(
            directories: directories,
            threshold: threshold,
            content: false,
            weights: nil,
            keep: nil,
            action: "trash",
            group: false,
            sort: "score",
            mode: mode,
            embedThumbnails: false
        ),
        stats: ScanStats(
            filesScanned: 100,
            filesAfterFilter: 80,
            totalPairsScored: 200,
            pairsAboveThreshold: pairCount,
            scanTime: 1.0,
            extractTime: 2.0,
            filterTime: 0.5,
            contentHashTime: 0.0,
            scoringTime: 2.0,
            totalTime: 5.5
        ),
        content: .pairs(Array(repeating: pair, count: pairCount))
    )

    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = .iso8601
    return try encoder.encode(envelope)
}

/// Create a legacy .actions.json sidecar Data.
private func makeLegacyActions(
    actions: [HistoryAction] = []
) throws -> Data {
    let sidecar = HistoryActionSidecar(version: 1, actions: actions)
    let encoder = JSONEncoder()
    encoder.keyEncodingStrategy = .convertToSnakeCase
    encoder.dateEncodingStrategy = .iso8601
    return try encoder.encode(sidecar)
}

/// Create a temporary directory for test I/O.
private func makeTempDir(prefix: String = "SessionMigrationTests") throws -> URL {
    let dir = FileManager.default.temporaryDirectory
        .appendingPathComponent("\(prefix)-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    return dir
}

/// Clean up a temporary directory.
private func cleanupTempDir(_ dir: URL) {
    try? FileManager.default.removeItem(at: dir)
}

/// Write legacy files to the specified directory.
private func writeLegacyFiles(
    to dir: URL,
    metaData: Data,
    envelopeData: Data,
    envelopeFilename: String,
    actionsData: Data? = nil
) throws {
    let fm = FileManager.default
    try fm.createDirectory(at: dir, withIntermediateDirectories: true)

    // .ddscan envelope
    let envelopeURL = dir.appendingPathComponent(envelopeFilename)
    try envelopeData.write(to: envelopeURL)

    // .meta.json
    let metaFilename = envelopeFilename
        .replacingOccurrences(of: ".ddscan", with: ".meta.json")
    let metaURL = dir.appendingPathComponent(metaFilename)
    try metaData.write(to: metaURL)

    // .actions.json (optional)
    if let actionsData {
        let actionsFilename = envelopeFilename
            .replacingOccurrences(of: ".ddscan", with: ".actions.json")
        let actionsURL = dir.appendingPathComponent(actionsFilename)
        try actionsData.write(to: actionsURL)
    }
}

// MARK: - Tests

@Suite("Legacy History Migration")
struct SessionMigrationTests {

    @Test("Basic migration converts old format files to new sessions")
    func basicMigration() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        let entryID = UUID()
        let envelopeFilename = "20250101-120000-video.ddscan"
        let (metaData, _) = try makeLegacyMeta(id: entryID, envelopeFilename: envelopeFilename)
        let envelopeData = try makeLegacyEnvelope()

        try writeLegacyFiles(
            to: legacyDir,
            metaData: metaData,
            envelopeData: envelopeData,
            envelopeFilename: envelopeFilename
        )

        let registry = SessionRegistry(storageDirectory: registryDir)
        await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)

        let entries = try await registry.listEntries()
        #expect(entries.count == 1)
        #expect(entries[0].id == entryID)
        #expect(entries[0].mode == .video)
        #expect(entries[0].directories == ["/videos"])
        #expect(entries[0].pairCount == 3)

        // Verify full session loads correctly
        let loaded = try await registry.loadSession(entryID)
        #expect(loaded.id == entryID)
        #expect(loaded.metadata.fileCount == 100)
        #expect(loaded.metadata.mode == .video)
        #expect(loaded.config.mode == .video)
        #expect(loaded.config.directories == ["/videos"])
        #expect(loaded.results.actionHistory.isEmpty)

        // Verify raw envelope data is preserved
        let rawEnvelope = try await registry.loadEnvelopeData(entryID)
        #expect(rawEnvelope != nil)
        #expect(rawEnvelope == envelopeData)
    }

    @Test("Migration with actions converts HistoryAction to ActionRecord")
    func migrationWithActions() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-actions-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-actions-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        let entryID = UUID()
        let envelopeFilename = "20250101-120000-video.ddscan"
        let (metaData, _) = try makeLegacyMeta(id: entryID, envelopeFilename: envelopeFilename)
        let envelopeData = try makeLegacyEnvelope()
        let actionsData = try makeLegacyActions(actions: [
            HistoryAction(
                timestamp: "2025-01-01T12:05:00Z",
                action: "trash",
                path: "/videos/b.mp4",
                kept: "/videos/a.mp4",
                bytesFreed: 900_000,
                score: 85.3,
                strategy: "newest",
                destination: nil
            ),
        ])

        try writeLegacyFiles(
            to: legacyDir,
            metaData: metaData,
            envelopeData: envelopeData,
            envelopeFilename: envelopeFilename,
            actionsData: actionsData
        )

        let registry = SessionRegistry(storageDirectory: registryDir)
        await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)

        let loaded = try await registry.loadSession(entryID)
        #expect(loaded.results.actionHistory.count == 1)

        let record = loaded.results.actionHistory[0]
        #expect(record.action == "trash")
        #expect(record.actedOnPath == "/videos/b.mp4")
        #expect(record.keptPath == "/videos/a.mp4")
        #expect(record.bytesFreed == 900_000)
        #expect(record.score == 85)  // Rounded from 85.3
        #expect(record.strategy == "newest")
        #expect(record.destination == nil)
        #expect(record.pairID.fileA == "/videos/a.mp4")
        #expect(record.pairID.fileB == "/videos/b.mp4")
    }

    @Test("Entry with .meta.json but no .ddscan is skipped")
    func metadataOnlySkipped() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-metaonly-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-metaonly-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        let envelopeFilename = "20250101-120000-video.ddscan"
        let (metaData, _) = try makeLegacyMeta(envelopeFilename: envelopeFilename)

        // Write only the .meta.json, no .ddscan
        let metaFilename = envelopeFilename
            .replacingOccurrences(of: ".ddscan", with: ".meta.json")
        try metaData.write(to: legacyDir.appendingPathComponent(metaFilename))

        let registry = SessionRegistry(storageDirectory: registryDir)
        await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)

        let entries = try await registry.listEntries()
        #expect(entries.isEmpty)
    }

    @Test("Migration is idempotent — running twice does not create duplicates")
    func idempotency() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-idem-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-idem-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        let entryID = UUID()
        let envelopeFilename = "20250101-120000-video.ddscan"
        let (metaData, _) = try makeLegacyMeta(id: entryID, envelopeFilename: envelopeFilename)
        let envelopeData = try makeLegacyEnvelope()

        try writeLegacyFiles(
            to: legacyDir,
            metaData: metaData,
            envelopeData: envelopeData,
            envelopeFilename: envelopeFilename
        )

        let registry = SessionRegistry(storageDirectory: registryDir)

        // Run migration twice
        await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)
        await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)

        let entries = try await registry.listEntries()
        #expect(entries.count == 1)
        #expect(entries[0].id == entryID)
    }

    @Test("Partial failure: corrupted .meta.json does not block valid entries")
    func partialFailure() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-partial-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-partial-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        // Valid entry
        let validID = UUID()
        let validEnvFilename = "20250101-120000-video.ddscan"
        let (validMeta, _) = try makeLegacyMeta(id: validID, envelopeFilename: validEnvFilename)
        let validEnvData = try makeLegacyEnvelope()
        try writeLegacyFiles(
            to: legacyDir,
            metaData: validMeta,
            envelopeData: validEnvData,
            envelopeFilename: validEnvFilename
        )

        // Corrupted entry: write garbage as .meta.json
        let corruptedEnvFilename = "20250102-130000-image.ddscan"
        let corruptedMetaFilename = corruptedEnvFilename
            .replacingOccurrences(of: ".ddscan", with: ".meta.json")
        try Data("not valid json".utf8).write(
            to: legacyDir.appendingPathComponent(corruptedMetaFilename)
        )
        // Also write its .ddscan so it's not just a missing-envelope issue
        try Data("also garbage".utf8).write(
            to: legacyDir.appendingPathComponent(corruptedEnvFilename)
        )

        let registry = SessionRegistry(storageDirectory: registryDir)
        let result = await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)
        #expect(result == false)

        let entries = try await registry.listEntries()
        #expect(entries.count == 1)
        #expect(entries[0].id == validID)
    }

    @Test("Fully successful migration returns true")
    func fullSuccessReturnsTrue() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-success-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-success-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        let entryID = UUID()
        let envelopeFilename = "20250101-120000-video.ddscan"
        let (metaData, _) = try makeLegacyMeta(id: entryID, envelopeFilename: envelopeFilename)
        let envelopeData = try makeLegacyEnvelope()

        try writeLegacyFiles(
            to: legacyDir,
            metaData: metaData,
            envelopeData: envelopeData,
            envelopeFilename: envelopeFilename
        )

        let registry = SessionRegistry(storageDirectory: registryDir)
        let result = await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)
        #expect(result == true)

        let entries = try await registry.listEntries()
        #expect(entries.count == 1)
        #expect(entries[0].id == entryID)
    }

    @Test("Empty legacy directory completes without error")
    func emptyDirectory() async throws {
        let legacyDir = try makeTempDir(prefix: "LegacyMigration-empty-legacy")
        let registryDir = try makeTempDir(prefix: "LegacyMigration-empty-registry")
        defer {
            cleanupTempDir(legacyDir)
            cleanupTempDir(registryDir)
        }

        let registry = SessionRegistry(storageDirectory: registryDir)
        await registry.migrateFromLegacyFormat(legacyDirectory: legacyDir)

        let entries = try await registry.listEntries()
        #expect(entries.isEmpty)
    }

    @Test("Non-existent legacy directory completes without error")
    func nonExistentDirectory() async throws {
        let registryDir = try makeTempDir(prefix: "LegacyMigration-nodir-registry")
        defer { cleanupTempDir(registryDir) }

        let fakeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("NonExistent-\(UUID().uuidString)", isDirectory: true)

        let registry = SessionRegistry(storageDirectory: registryDir)
        await registry.migrateFromLegacyFormat(legacyDirectory: fakeDir)

        let entries = try await registry.listEntries()
        #expect(entries.isEmpty)
    }
}

// MARK: - HistoryAction Conversion Tests

@Suite("HistoryAction Conversion")
struct HistoryActionConversionTests {

    @Test("convertHistoryAction maps all fields correctly")
    func fullConversion() {
        let legacy = HistoryAction(
            timestamp: "2025-01-01T12:05:00Z",
            action: "trash",
            path: "/videos/b.mp4",
            kept: "/videos/a.mp4",
            bytesFreed: 900_000,
            score: 85.7,
            strategy: "newest",
            destination: nil
        )

        let record = convertHistoryAction(legacy)
        #expect(record != nil)
        #expect(record!.action == "trash")
        #expect(record!.actedOnPath == "/videos/b.mp4")
        #expect(record!.keptPath == "/videos/a.mp4")
        #expect(record!.bytesFreed == 900_000)
        #expect(record!.score == 86)  // Rounded from 85.7
        #expect(record!.strategy == "newest")
        #expect(record!.destination == nil)
        #expect(record!.pairID.fileA == "/videos/a.mp4")
        #expect(record!.pairID.fileB == "/videos/b.mp4")
    }

    @Test("convertHistoryAction handles nil kept path")
    func nilKept() {
        let legacy = HistoryAction(
            timestamp: "2025-06-15T08:30:00Z",
            action: "delete",
            path: "/videos/orphan.mp4",
            kept: nil,
            bytesFreed: 500_000,
            score: 60.0,
            strategy: nil,
            destination: nil
        )

        let record = convertHistoryAction(legacy)
        #expect(record != nil)
        #expect(record!.keptPath == "")
        // When kept is nil, fileA is empty (unknown) rather than self-referencing
        #expect(record!.pairID.fileA == "")
        #expect(record!.pairID.fileB == "/videos/orphan.mp4")
    }

    @Test("convertHistoryAction handles fractional-second timestamp")
    func fractionalTimestamp() {
        let legacy = HistoryAction(
            timestamp: "2025-01-01T12:05:00.123Z",
            action: "trash",
            path: "/videos/b.mp4",
            kept: "/videos/a.mp4",
            bytesFreed: 0,
            score: 50.0,
            strategy: nil,
            destination: nil
        )

        let record = convertHistoryAction(legacy)
        #expect(record != nil)
    }

    @Test("convertHistoryAction returns nil for invalid timestamp")
    func invalidTimestamp() {
        let legacy = HistoryAction(
            timestamp: "not-a-date",
            action: "trash",
            path: "/videos/b.mp4",
            kept: nil,
            bytesFreed: 0,
            score: 50.0,
            strategy: nil,
            destination: nil
        )

        let record = convertHistoryAction(legacy)
        #expect(record == nil)
    }

    @Test("convertHistoryAction preserves move destination")
    func moveDestination() {
        let legacy = HistoryAction(
            timestamp: "2025-01-01T12:05:00Z",
            action: "move",
            path: "/videos/b.mp4",
            kept: "/videos/a.mp4",
            bytesFreed: 900_000,
            score: 75.0,
            strategy: "biggest",
            destination: "/archive/b.mp4"
        )

        let record = convertHistoryAction(legacy)
        #expect(record != nil)
        #expect(record!.action == "move")
        #expect(record!.destination == "/archive/b.mp4")
    }
}
