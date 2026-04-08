import Foundation
import Testing

@testable import DuplicatesDetector

// MARK: - Helpers

/// Create a minimal ScanEnvelope for registry tests.
private func makeEnvelope(
    pairs: [PairResult] = [],
    groups: [GroupResult]? = nil,
    keep: String? = nil
) -> ScanEnvelope {
    let content: ScanContent = if let groups {
        .groups(groups)
    } else {
        .pairs(pairs)
    }
    return ScanEnvelope(
        version: "1.0.0",
        generatedAt: "2025-01-01T00:00:00Z",
        args: ScanArgs(
            directories: ["/videos"],
            threshold: 50,
            content: false,
            weights: nil,
            keep: keep,
            action: "trash",
            group: false,
            sort: "score",
            mode: "video",
            embedThumbnails: false
        ),
        stats: ScanStats(
            filesScanned: 100,
            filesAfterFilter: 80,
            totalPairsScored: 200,
            pairsAboveThreshold: pairs.count,
            scanTime: 1.0,
            extractTime: 2.0,
            filterTime: 0.5,
            contentHashTime: 0.0,
            scoringTime: 2.0,
            totalTime: 5.5
        ),
        content: content
    )
}

/// Create a pair result for testing.
private func makePair(
    fileA: String = "/videos/a.mp4",
    fileB: String = "/videos/b.mp4",
    score: Double = 85.0,
    keep: String? = "a"
) -> PairResult {
    PairResult(
        fileA: fileA,
        fileB: fileB,
        score: score,
        breakdown: ["filename": 40.0],
        detail: [:],
        fileAMetadata: FileMetadata(fileSize: 1_000_000),
        fileBMetadata: FileMetadata(fileSize: 900_000),
        fileAIsReference: false,
        fileBIsReference: false,
        keep: keep
    )
}

/// Create a PersistedSession for testing.
private func makePersistedSession(
    id: UUID = UUID(),
    pairs: [PairResult]? = nil,
    resolutions: [String: Resolution] = [:],
    ignoredPairs: [[String]] = [],
    actionHistory: [ActionRecord] = [],
    metadata: SessionMetadata? = nil,
    watchConfig: WatchConfig? = nil
) -> PersistedSession {
    let envelope = makeEnvelope(pairs: pairs ?? [makePair()])
    let meta = metadata ?? SessionMetadata(
        createdAt: Date(),
        directories: ["/videos"],
        sourceLabel: "/videos",
        mode: .video,
        pairCount: (pairs ?? [makePair()]).count,
        fileCount: 100
    )
    return PersistedSession(
        id: id,
        config: SessionConfig(),
        results: PersistedResults(
            envelope: envelope,
            resolutions: resolutions,
            ignoredPairs: ignoredPairs,
            actionHistory: actionHistory,
            pendingWatchPairs: []
        ),
        metadata: meta,
        watchConfig: watchConfig
    )
}

/// Create a temporary directory for test I/O.
private func makeTempDir() throws -> URL {
    let dir = FileManager.default.temporaryDirectory
        .appendingPathComponent("SessionRegistryTests-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    return dir
}

/// Clean up a temporary directory.
private func cleanupTempDir(_ dir: URL) {
    try? FileManager.default.removeItem(at: dir)
}

// MARK: - PersistedSession Codable Round-Trip

@Suite("PersistedSession Codable")
struct PersistedSessionCodableTests {

    @Test("PersistedSession round-trips through JSON encoding/decoding")
    func roundTrip() throws {
        let pairID = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let record = ActionRecord(
            pairID: pairID,
            timestamp: Date(timeIntervalSince1970: 1_700_000_000),
            action: "trash",
            actedOnPath: "/videos/b.mp4",
            keptPath: "/videos/a.mp4",
            bytesFreed: 900_000,
            score: 85,
            strategy: "newest",
            destination: nil
        )

        let persisted = makePersistedSession(
            resolutions: ["/videos/a.mp4\t/videos/b.mp4": .resolved(record)],
            ignoredPairs: [["/videos/c.mp4", "/videos/d.mp4"]],
            actionHistory: [record]
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(persisted)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        #expect(decoded.id == persisted.id)
        #expect(decoded.metadata.sourceLabel == persisted.metadata.sourceLabel)
        #expect(decoded.metadata.mode == persisted.metadata.mode)
        #expect(decoded.results.resolutions.count == 1)
        #expect(decoded.results.ignoredPairs.count == 1)
        #expect(decoded.results.actionHistory.count == 1)
    }

    @Test("PersistedResults encodes resolutions with tab-separated keys that round-trip")
    func resolutionKeyRoundTrip() throws {
        let tabKey = "/a.mp4\t/b.mp4"
        let persisted = makePersistedSession(
            resolutions: [tabKey: .active]
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(persisted)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        // The tab-separated key round-trips correctly
        #expect(decoded.results.resolutions[tabKey] == .active)
    }

    @Test("PersistedResults encodes ignored pairs as sorted arrays")
    func ignoredPairsFormat() throws {
        let persisted = makePersistedSession(
            ignoredPairs: [["z.mp4", "a.mp4"]]  // already sorted by caller
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(persisted)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        #expect(decoded.results.ignoredPairs == [["z.mp4", "a.mp4"]])
    }

    @Test("Resolution Codable round-trips all cases")
    func resolutionCodable() throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        // active
        let activeData = try encoder.encode(Resolution.active)
        let activeDecoded = try decoder.decode(Resolution.self, from: activeData)
        #expect(activeDecoded == .active)

        // resolved
        let record = ActionRecord(
            pairID: PairIdentifier(fileA: "/a", fileB: "/b"),
            timestamp: Date(timeIntervalSince1970: 1_700_000_000),
            action: "trash",
            actedOnPath: "/b",
            keptPath: "/a",
            bytesFreed: nil,
            score: 80,
            strategy: nil,
            destination: nil
        )
        let resolvedData = try encoder.encode(Resolution.resolved(record))
        let resolvedDecoded = try decoder.decode(Resolution.self, from: resolvedData)
        #expect(resolvedDecoded == .resolved(record))

        // probablySolved
        let probData = try encoder.encode(Resolution.probablySolved(missing: ["/a", "/b"]))
        let probDecoded = try decoder.decode(Resolution.self, from: probData)
        #expect(probDecoded == .probablySolved(missing: ["/a", "/b"]))
    }

    @Test("PersistedResults round-trip includes pendingWatchPairs")
    func pendingWatchPairsRoundTrip() throws {
        let watchPair = makePair(
            fileA: "/videos/watch1.mp4",
            fileB: "/videos/watch2.mp4",
            score: 72
        )
        let envelope = makeEnvelope(pairs: [makePair()])
        let results = PersistedResults(
            envelope: envelope,
            resolutions: [:],
            ignoredPairs: [],
            actionHistory: [],
            pendingWatchPairs: [watchPair]
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(results)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedResults.self, from: data)

        #expect(decoded.pendingWatchPairs.count == 1)
        #expect(decoded.pendingWatchPairs.first?.fileA == "/videos/watch1.mp4")
        #expect(decoded.pendingWatchPairs.first?.fileB == "/videos/watch2.mp4")
        #expect(decoded.pendingWatchPairs.first?.score == 72)
    }
}

// MARK: - Session ↔ PersistedSession Conversion

@Suite("Session Persistence Conversion")
struct SessionConversionTests {

    @Test("Session.persisted() returns nil when no results")
    func persistedNilWithoutResults() {
        let session = Session(phase: .setup)
        #expect(session.persisted() == nil)
    }

    @Test("Session.persisted() captures resolutions and ignored pairs")
    func persistedCapturesState() {
        let pair = makePair()
        let envelope = makeEnvelope(pairs: [pair])
        var snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
        let record = ActionRecord(
            pairID: pairID,
            timestamp: Date(),
            action: "trash",
            actedOnPath: pair.fileB,
            keptPath: pair.fileA,
            bytesFreed: 900_000,
            score: 85,
            strategy: nil,
            destination: nil
        )
        snapshot.resolutions[pairID] = .resolved(record)

        let ignoredID = PairIdentifier(fileA: "/c.mp4", fileB: "/d.mp4")
        snapshot.ignoredPairs.insert(ignoredID)
        snapshot.actionHistory = [record]

        let session = Session(
            phase: .results,
            config: SessionConfig(),
            results: snapshot,
            metadata: SessionMetadata(directories: ["/videos"], mode: .video, pairCount: 1)
        )

        let persisted = session.persisted()
        #expect(persisted != nil)
        #expect(persisted!.results.resolutions.count == 1)
        #expect(persisted!.results.ignoredPairs.count == 1)
        #expect(persisted!.results.actionHistory.count == 1)
    }

    @Test("Session(from:) round-trip preserves all fields")
    func roundTripConversion() throws {
        let pair = makePair()
        let envelope = makeEnvelope(pairs: [pair])
        var snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
        let record = ActionRecord(
            pairID: pairID,
            timestamp: Date(timeIntervalSince1970: 1_700_000_000),
            action: "trash",
            actedOnPath: pair.fileB,
            keptPath: pair.fileA,
            bytesFreed: 900_000,
            score: 85,
            strategy: "newest",
            destination: nil
        )
        snapshot.resolutions[pairID] = .resolved(record)
        snapshot.actionHistory = [record]

        let ignoredID = PairIdentifier(fileA: "/c.mp4", fileB: "/d.mp4")
        snapshot.ignoredPairs.insert(ignoredID)

        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 1_700_000_000),
            directories: ["/videos"],
            sourceLabel: "Test scan",
            mode: .video,
            pairCount: 1,
            fileCount: 100
        )

        let original = Session(
            phase: .results,
            config: SessionConfig(),
            results: snapshot,
            metadata: metadata
        )

        guard let persisted = original.persisted() else {
            Issue.record("persisted() should not be nil")
            return
        }

        let restored = Session(from: persisted)
        #expect(restored.id == persisted.id)
        #expect(restored.phase == .results)
        #expect(restored.metadata.sourceLabel == "Test scan")
        #expect(restored.metadata.mode == .video)
        #expect(restored.results?.resolutions.count == 1)
        // Both directions stored for order-independent lookup
        #expect(restored.results?.ignoredPairs.count == 2)
        #expect(restored.results?.actionHistory.count == 1)
        #expect(restored.results?.resolutions[pairID] == .resolved(record))
        #expect(restored.results?.ignoredPairs.contains(ignoredID) == true)
    }
}

// MARK: - SessionRegistry CRUD

@Suite("SessionRegistry CRUD")
struct SessionRegistryCRUDTests {

    @Test("saveSession creates session.json and envelope.dat files")
    func saveCreatesFiles() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        try await registry.saveSession(persisted, envelopeData: Data("raw-envelope".utf8))

        let fm = FileManager.default
        let sessionFile = tempDir.appendingPathComponent("\(persisted.id.uuidString).session.json")
        let envelopeFile = tempDir.appendingPathComponent("\(persisted.id.uuidString).envelope.dat")
        let indexFile = tempDir.appendingPathComponent("index.json")

        #expect(fm.fileExists(atPath: sessionFile.path))
        #expect(fm.fileExists(atPath: envelopeFile.path))
        #expect(fm.fileExists(atPath: indexFile.path))
    }

    @Test("saveSession without envelope data does not create .envelope.dat")
    func saveWithoutEnvelope() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        try await registry.saveSession(persisted, envelopeData: nil)

        let fm = FileManager.default
        let sessionFile = tempDir.appendingPathComponent("\(persisted.id.uuidString).session.json")
        let envelopeFile = tempDir.appendingPathComponent("\(persisted.id.uuidString).envelope.dat")

        #expect(fm.fileExists(atPath: sessionFile.path))
        #expect(!fm.fileExists(atPath: envelopeFile.path))
    }

    @Test("loadSession round-trips correctly")
    func loadRoundTrip() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let id = UUID()
        let metadata = SessionMetadata(
            createdAt: Date(timeIntervalSince1970: 1_700_000_000),
            directories: ["/photos"],
            sourceLabel: "photo scan",
            mode: .image,
            pairCount: 5,
            fileCount: 50
        )
        let persisted = makePersistedSession(id: id, metadata: metadata)

        try await registry.saveSession(persisted, envelopeData: Data("test".utf8))

        let loaded = try await registry.loadSession(id)
        #expect(loaded.id == id)
        #expect(loaded.metadata.sourceLabel == "photo scan")
        #expect(loaded.metadata.mode == .image)
        #expect(loaded.metadata.pairCount == 5)
    }

    @Test("listEntries returns saved entries sorted by date newest first")
    func listEntriesSorted() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)

        let older = makePersistedSession(
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_000_000),
                directories: ["/old"],
                sourceLabel: "old",
                mode: .video,
                pairCount: 1,
                fileCount: 10
            )
        )
        let newer = makePersistedSession(
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 2_000_000),
                directories: ["/new"],
                sourceLabel: "new",
                mode: .video,
                pairCount: 2,
                fileCount: 20
            )
        )

        try await registry.saveSession(older, envelopeData: nil)
        try await registry.saveSession(newer, envelopeData: nil)

        let entries = try await registry.listEntries()
        #expect(entries.count == 2)
        #expect(entries[0].sourceLabel == "new")
        #expect(entries[1].sourceLabel == "old")
    }

    @Test("deleteSession removes files and index entry")
    func deleteSession() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        try await registry.saveSession(persisted, envelopeData: Data("data".utf8))

        let entriesBefore = try await registry.listEntries()
        #expect(entriesBefore.count == 1)

        try await registry.deleteSession(persisted.id)

        let entriesAfter = try await registry.listEntries()
        #expect(entriesAfter.count == 0)

        let fm = FileManager.default
        let sessionFile = tempDir.appendingPathComponent("\(persisted.id.uuidString).session.json")
        let envelopeFile = tempDir.appendingPathComponent("\(persisted.id.uuidString).envelope.dat")
        #expect(!fm.fileExists(atPath: sessionFile.path))
        #expect(!fm.fileExists(atPath: envelopeFile.path))
    }

    @Test("pruneOldSessions keeps only the specified count")
    func pruneOldSessions() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)

        // Save 5 sessions with different timestamps
        for i in 0..<5 {
            let persisted = makePersistedSession(
                metadata: SessionMetadata(
                    createdAt: Date(timeIntervalSince1970: Double(i) * 1_000_000),
                    directories: ["/dir\(i)"],
                    sourceLabel: "scan \(i)",
                    mode: .video,
                    pairCount: i,
                    fileCount: i * 10
                )
            )
            try await registry.saveSession(persisted, envelopeData: nil)
        }

        let entriesBefore = try await registry.listEntries()
        #expect(entriesBefore.count == 5)

        try await registry.pruneOldSessions(keep: 2)

        let entriesAfter = try await registry.listEntries()
        #expect(entriesAfter.count == 2)

        // The two newest should remain
        #expect(entriesAfter[0].sourceLabel == "scan 4")
        #expect(entriesAfter[1].sourceLabel == "scan 3")
    }

    @Test("loading a non-existent session throws sessionNotFound")
    func loadNonExistent() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let fakeID = UUID()

        do {
            _ = try await registry.loadSession(fakeID)
            Issue.record("Expected error for non-existent session")
        } catch let error as SessionRegistry.RegistryError {
            if case .sessionNotFound(let id) = error {
                #expect(id == fakeID)
            } else {
                Issue.record("Expected sessionNotFound but got \(error)")
            }
        }
    }

    @Test("saveSession updates existing entry on re-save")
    func saveUpdatesExisting() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let id = UUID()

        let first = makePersistedSession(
            id: id,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_000_000),
                directories: ["/first"],
                sourceLabel: "first",
                mode: .video,
                pairCount: 1,
                fileCount: 10
            )
        )
        try await registry.saveSession(first, envelopeData: nil)

        let second = makePersistedSession(
            id: id,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_000_000),
                directories: ["/second"],
                sourceLabel: "second",
                mode: .video,
                pairCount: 2,
                fileCount: 20
            )
        )
        try await registry.saveSession(second, envelopeData: nil)

        let entries = try await registry.listEntries()
        #expect(entries.count == 1)
        #expect(entries[0].sourceLabel == "second")
    }

    @Test("loadEnvelopeData returns raw bytes")
    func loadEnvelopeData() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()
        let rawBytes = Data("raw-cli-envelope-output".utf8)

        try await registry.saveSession(persisted, envelopeData: rawBytes)

        let loaded = try await registry.loadEnvelopeData(persisted.id)
        #expect(loaded == rawBytes)
    }

    @Test("loadEnvelopeData returns nil when no envelope file")
    func loadEnvelopeDataMissing() async throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        try await registry.saveSession(persisted, envelopeData: nil)

        let loaded = try await registry.loadEnvelopeData(persisted.id)
        #expect(loaded == nil)
    }
}

// MARK: - saveSessionSync Tests

@Suite("SessionRegistry saveSessionSync")
struct SessionRegistrySaveSessionSyncTests {

    @Test("saveSessionSync writes a valid session.json that can be decoded")
    func syncSaveWritesDecodableSession() throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        registry.saveSessionSync(persisted, envelopeData: nil)

        // Verify the file exists and is decodable
        let sessionURL = tempDir.appendingPathComponent("\(persisted.id.uuidString).session.json")
        #expect(FileManager.default.fileExists(atPath: sessionURL.path))

        let data = try Data(contentsOf: sessionURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        #expect(decoded.id == persisted.id)
        #expect(decoded.metadata.sourceLabel == persisted.metadata.sourceLabel)
        #expect(decoded.metadata.mode == persisted.metadata.mode)
    }

    @Test("saveSessionSync writes envelope data when provided")
    func syncSaveWritesEnvelopeData() throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()
        let envelopeBytes = Data("raw-cli-envelope-bytes".utf8)

        registry.saveSessionSync(persisted, envelopeData: envelopeBytes)

        let envelopeURL = tempDir.appendingPathComponent("\(persisted.id.uuidString).envelope.dat")
        #expect(FileManager.default.fileExists(atPath: envelopeURL.path))

        let loaded = try Data(contentsOf: envelopeURL)
        #expect(loaded == envelopeBytes)
    }

    @Test("saveSessionSync does not crash when envelope data is nil")
    func syncSaveNilEnvelopeDoesNotCrash() {
        let tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("SessionRegistryTests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        // This should not crash -- the key behavior being tested
        registry.saveSessionSync(persisted, envelopeData: nil)

        // Session file should still be written
        let sessionURL = tempDir.appendingPathComponent("\(persisted.id.uuidString).session.json")
        #expect(FileManager.default.fileExists(atPath: sessionURL.path))

        // Envelope file should not exist
        let envelopeURL = tempDir.appendingPathComponent("\(persisted.id.uuidString).envelope.dat")
        #expect(!FileManager.default.fileExists(atPath: envelopeURL.path))
    }

    @Test("saveSessionSync creates index.json with the saved session entry")
    func syncSaveUpdatesIndex() throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let persisted = makePersistedSession()

        registry.saveSessionSync(persisted, envelopeData: nil)

        // Verify index.json was created and contains the session entry
        let indexURL = tempDir.appendingPathComponent("index.json")
        #expect(FileManager.default.fileExists(atPath: indexURL.path))

        let indexData = try Data(contentsOf: indexURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let entries = try decoder.decode([SessionRegistry.Entry].self, from: indexData)

        #expect(entries.count == 1)
        #expect(entries[0].id == persisted.id)
        #expect(entries[0].sourceLabel == persisted.metadata.sourceLabel)
        #expect(entries[0].mode == persisted.metadata.mode)
        #expect(entries[0].pairCount == persisted.metadata.pairCount)
    }

    @Test("saveSessionSync updates existing index entry without duplicating")
    func syncSaveUpdatesExistingIndexEntry() throws {
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let indexURL = tempDir.appendingPathComponent("index.json")

        // Save a first session to populate the index with one entry
        let otherID = UUID()
        let otherSession = makePersistedSession(
            id: otherID,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_000_000),
                directories: ["/other"],
                sourceLabel: "other scan",
                mode: .image,
                pairCount: 3,
                fileCount: 30
            )
        )
        registry.saveSessionSync(otherSession, envelopeData: nil)

        // Verify index has 1 entry
        let dataAfterFirst = try Data(contentsOf: indexURL)
        let entriesAfterFirst = try decoder.decode([SessionRegistry.Entry].self, from: dataAfterFirst)
        #expect(entriesAfterFirst.count == 1)
        #expect(entriesAfterFirst[0].id == otherID)

        // Save a second session with a different ID
        let targetID = UUID()
        let targetSession = makePersistedSession(
            id: targetID,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 2_000_000),
                directories: ["/target"],
                sourceLabel: "target scan",
                mode: .video,
                pairCount: 5,
                fileCount: 50
            )
        )
        registry.saveSessionSync(targetSession, envelopeData: nil)

        // Verify index now has 2 entries
        let dataAfterSecond = try Data(contentsOf: indexURL)
        let entriesAfterSecond = try decoder.decode([SessionRegistry.Entry].self, from: dataAfterSecond)
        #expect(entriesAfterSecond.count == 2)
        #expect(entriesAfterSecond.contains { $0.id == otherID })
        #expect(entriesAfterSecond.contains { $0.id == targetID })

        // Re-save the target session with updated metadata (different pairCount)
        let updatedSession = makePersistedSession(
            id: targetID,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 2_000_000),
                directories: ["/target"],
                sourceLabel: "target scan updated",
                mode: .video,
                pairCount: 10,
                fileCount: 100
            )
        )
        registry.saveSessionSync(updatedSession, envelopeData: nil)

        // Verify index still has exactly 2 entries (update, not append)
        let dataAfterUpdate = try Data(contentsOf: indexURL)
        let entriesAfterUpdate = try decoder.decode([SessionRegistry.Entry].self, from: dataAfterUpdate)
        #expect(entriesAfterUpdate.count == 2)

        // The other session is unchanged
        let otherEntry = entriesAfterUpdate.first { $0.id == otherID }
        #expect(otherEntry != nil)
        #expect(otherEntry?.sourceLabel == "other scan")
        #expect(otherEntry?.pairCount == 3)

        // The target session was updated (not duplicated)
        let targetEntry = entriesAfterUpdate.first { $0.id == targetID }
        #expect(targetEntry != nil)
        #expect(targetEntry?.sourceLabel == "target scan updated")
        #expect(targetEntry?.pairCount == 10)
    }
}

// MARK: - Concurrent saveSessionSync (NSLock)

@Suite("SessionRegistry Concurrent saveSessionSync")
struct SessionRegistryConcurrentTests {

    @Test("Concurrent saveSessionSync calls from multiple threads preserve all index entries")
    func concurrentSaveSessionSyncPreservesAllEntries() throws {
        /// Verifies that the NSLock in saveIndex/syncUpdateIndex prevents
        /// concurrent read-modify-write races that could lose entries.
        let tempDir = try makeTempDir()
        defer { cleanupTempDir(tempDir) }

        let registry = SessionRegistry(storageDirectory: tempDir)
        let sessionCount = 10

        // Generate unique sessions upfront
        var sessions: [PersistedSession] = []
        for i in 0..<sessionCount {
            let session = makePersistedSession(
                metadata: SessionMetadata(
                    createdAt: Date(timeIntervalSince1970: Double(i) * 1_000_000),
                    directories: ["/dir\(i)"],
                    sourceLabel: "concurrent-\(i)",
                    mode: .video,
                    pairCount: i,
                    fileCount: i * 10
                )
            )
            sessions.append(session)
        }

        // Dispatch all saves concurrently from separate threads
        let group = DispatchGroup()
        let queue = DispatchQueue(label: "test.concurrent", attributes: .concurrent)

        for session in sessions {
            group.enter()
            queue.async {
                registry.saveSessionSync(session, envelopeData: nil)
                group.leave()
            }
        }

        group.wait()

        // Read back the index and verify all entries are present
        let indexURL = tempDir.appendingPathComponent("index.json")
        #expect(FileManager.default.fileExists(atPath: indexURL.path))

        let indexData = try Data(contentsOf: indexURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let entries = try decoder.decode([SessionRegistry.Entry].self, from: indexData)

        #expect(entries.count == sessionCount, "Expected \(sessionCount) entries but found \(entries.count)")

        // Verify each session ID is present in the index
        let indexedIDs = Set(entries.map(\.id))
        for session in sessions {
            #expect(indexedIDs.contains(session.id), "Missing session \(session.id) from index")
        }

        // Verify each session file was written
        let fm = FileManager.default
        for session in sessions {
            let sessionURL = tempDir.appendingPathComponent("\(session.id.uuidString).session.json")
            #expect(fm.fileExists(atPath: sessionURL.path), "Missing session file for \(session.id)")
        }
    }
}

// MARK: - Ignored Pair Deduplication Tests

@Suite("Ignored Pair Deduplication")
struct IgnoredPairDeduplicationTests {

    @Test("persisted() deduplicates ignored pairs stored in both directions")
    func persistedDeduplicatesIgnoredPairs() {
        /// When Session.init(from:) restores ignored pairs, it inserts both (A,B)
        /// and (B,A) for order-independent lookup. persisted() must collapse these
        /// back to a single logical pair in the serialized output.
        let pair = makePair()
        let envelope = makeEnvelope(pairs: [pair])
        var snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        // Insert both directions, simulating what Session.init(from:) does
        let idAB = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let idBA = PairIdentifier(fileA: "/videos/b.mp4", fileB: "/videos/a.mp4")
        snapshot.ignoredPairs.insert(idAB)
        snapshot.ignoredPairs.insert(idBA)

        let session = Session(
            phase: .results,
            config: SessionConfig(),
            results: snapshot,
            metadata: SessionMetadata(directories: ["/videos"], mode: .video, pairCount: 1)
        )

        let persisted = session.persisted()
        #expect(persisted != nil)
        // Both directions should collapse to exactly 1 serialized pair
        #expect(persisted!.results.ignoredPairs.count == 1)
        // The serialized pair should be sorted alphabetically
        #expect(persisted!.results.ignoredPairs[0] == ["/videos/a.mp4", "/videos/b.mp4"])
    }

    @Test("uniqueIgnoredPairCount counts both directions as one logical pair")
    func uniqueIgnoredPairCountHandlesBothDirections() {
        /// ResultsSnapshot stores both (A,B) and (B,A) for O(1) lookup.
        /// uniqueIgnoredPairCount must report the number of logical pairs, not
        /// the raw set count.
        let envelope = makeEnvelope(pairs: [makePair()])
        var snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        let idAB = PairIdentifier(fileA: "/videos/a.mp4", fileB: "/videos/b.mp4")
        let idBA = PairIdentifier(fileA: "/videos/b.mp4", fileB: "/videos/a.mp4")
        snapshot.ignoredPairs.insert(idAB)
        snapshot.ignoredPairs.insert(idBA)

        // Raw count includes both directions
        #expect(snapshot.ignoredPairs.count == 2)
        // Unique count collapses to 1 logical pair
        #expect(snapshot.uniqueIgnoredPairCount == 1)
    }

    @Test("Restore round-trip preserves deduplicated ignored pairs without growth")
    func restoreRoundTripPreservesDeduplication() {
        /// A session with 1 ignored pair, persisted → restored → persisted again,
        /// must still have exactly 1 entry in the serialized output. This catches
        /// the bug where each round-trip doubled the ignored pairs count.
        let pair = makePair()
        let envelope = makeEnvelope(pairs: [pair])
        var snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        // Start with a single ignored pair
        let ignoredID = PairIdentifier(fileA: "/videos/c.mp4", fileB: "/videos/d.mp4")
        snapshot.ignoredPairs.insert(ignoredID)

        let original = Session(
            phase: .results,
            config: SessionConfig(),
            results: snapshot,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_700_000_000),
                directories: ["/videos"],
                mode: .video,
                pairCount: 1
            )
        )

        // First persist
        guard let persisted1 = original.persisted() else {
            Issue.record("First persisted() should not be nil")
            return
        }
        #expect(persisted1.results.ignoredPairs.count == 1)

        // Restore from persisted (this inserts both directions)
        let restored = Session(from: persisted1)
        #expect(restored.results?.ignoredPairs.count == 2) // Both (C,D) and (D,C)

        // Second persist — must still be 1, not 2
        guard let persisted2 = restored.persisted() else {
            Issue.record("Second persisted() should not be nil")
            return
        }
        #expect(persisted2.results.ignoredPairs.count == 1)
        #expect(persisted2.results.ignoredPairs[0] == ["/videos/c.mp4", "/videos/d.mp4"])
    }

    @Test("uniqueIgnoredPairCount is zero for empty set")
    func uniqueIgnoredPairCountEmpty() {
        let envelope = makeEnvelope(pairs: [makePair()])
        let snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)
        #expect(snapshot.uniqueIgnoredPairCount == 0)
        #expect(snapshot.ignoredPairs.isEmpty)
    }

    @Test("uniqueIgnoredPairCount counts multiple distinct pairs correctly")
    func uniqueIgnoredPairCountMultiplePairs() {
        let envelope = makeEnvelope(pairs: [makePair()])
        var snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        // Insert 3 logical pairs, each in both directions
        for (a, b) in [("a.mp4", "b.mp4"), ("c.mp4", "d.mp4"), ("e.mp4", "f.mp4")] {
            snapshot.ignoredPairs.insert(PairIdentifier(fileA: a, fileB: b))
            snapshot.ignoredPairs.insert(PairIdentifier(fileA: b, fileB: a))
        }

        #expect(snapshot.ignoredPairs.count == 6)
        #expect(snapshot.uniqueIgnoredPairCount == 3)
    }
}

// MARK: - SessionConfig Extended Fields Round-Trip

@Suite("SessionConfig Extended Fields Persistence")
struct SessionConfigExtendedFieldsTests {

    @Test("PersistedSession round-trips extended config fields through JSON encode/decode")
    func extendedConfigFieldsRoundTrip() throws {
        /// Verifies that the extended migration fields (action, sort, limit, minScore,
        /// exclude, reference, weights, content options, filter options, embedThumbnails)
        /// survive a JSON encode/decode cycle in PersistedSession.
        var config = SessionConfig()
        config.action = .trash
        config.sort = .size
        config.limit = 10
        config.minScore = 30
        config.exclude = ["*.tmp", "*.bak"]
        config.reference = ["/ref/dir"]
        config.weights = ["filename": 50, "duration": 30, "resolution": 20]
        config.embedThumbnails = true

        // Content options
        config.content = true
        config.contentMethod = .ssim

        // Filter options
        config.minDuration = 5.0
        config.maxDuration = 120.0
        config.minResolution = "720p"
        config.maxResolution = "4k"
        config.minBitrate = "1M"
        config.maxBitrate = "50M"
        config.codec = "h264"

        let persisted = makePersistedSession()
        // Reconstruct with the extended config
        let extendedPersisted = PersistedSession(
            id: persisted.id,
            config: config,
            results: persisted.results,
            metadata: persisted.metadata,
            watchConfig: nil
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(extendedPersisted)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        // Core options
        #expect(decoded.config.action == .trash)
        #expect(decoded.config.sort == .size)
        #expect(decoded.config.limit == 10)
        #expect(decoded.config.minScore == 30)
        #expect(decoded.config.exclude == ["*.tmp", "*.bak"])
        #expect(decoded.config.reference == ["/ref/dir"])
        #expect(decoded.config.weights == ["filename": 50, "duration": 30, "resolution": 20])
        #expect(decoded.config.embedThumbnails == true)

        // Content options
        #expect(decoded.config.content == true)
        #expect(decoded.config.contentMethod == .ssim)

        // Filter options
        #expect(decoded.config.minDuration == 5.0)
        #expect(decoded.config.maxDuration == 120.0)
        #expect(decoded.config.minResolution == "720p")
        #expect(decoded.config.maxResolution == "4k")
        #expect(decoded.config.minBitrate == "1M")
        #expect(decoded.config.maxBitrate == "50M")
        #expect(decoded.config.codec == "h264")
    }

    @Test("Session persisted → restore round-trip preserves extended config fields")
    func extendedConfigFieldsSessionRoundTrip() {
        /// Verifies that extended config fields survive a full Session → persisted →
        /// Session(from:) round-trip, not just JSON encoding.
        var config = SessionConfig()
        config.directories = ["/videos"]
        config.action = .trash
        config.sort = .size
        config.limit = 25
        config.minScore = 40
        config.exclude = ["*.log"]
        config.reference = ["/reference"]
        config.weights = ["filename": 60, "filesize": 40]
        config.embedThumbnails = true
        config.content = true
        config.contentMethod = .phash
        config.minDuration = 10.0
        config.maxDuration = 600.0
        config.codec = "hevc"

        let pair = makePair()
        let envelope = makeEnvelope(pairs: [pair])
        let snapshot = ResultsSnapshot(envelope: envelope, isDryRun: false)

        let session = Session(
            phase: .results,
            config: config,
            results: snapshot,
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_700_000_000),
                directories: ["/videos"],
                mode: .video,
                pairCount: 1
            )
        )

        guard let persisted = session.persisted() else {
            Issue.record("persisted() should not be nil")
            return
        }

        // Verify persisted config has the fields
        #expect(persisted.config.action == .trash)
        #expect(persisted.config.sort == .size)
        #expect(persisted.config.limit == 25)
        #expect(persisted.config.minScore == 40)
        #expect(persisted.config.exclude == ["*.log"])
        #expect(persisted.config.reference == ["/reference"])
        #expect(persisted.config.weights == ["filename": 60, "filesize": 40])
        #expect(persisted.config.embedThumbnails == true)
        #expect(persisted.config.content == true)
        #expect(persisted.config.contentMethod == .phash)
        #expect(persisted.config.minDuration == 10.0)
        #expect(persisted.config.maxDuration == 600.0)
        #expect(persisted.config.codec == "hevc")

        // Restore and verify config survives
        let restored = Session(from: persisted)
        let restoredConfig = restored.config!
        #expect(restoredConfig.action == .trash)
        #expect(restoredConfig.sort == .size)
        #expect(restoredConfig.limit == 25)
        #expect(restoredConfig.minScore == 40)
        #expect(restoredConfig.exclude == ["*.log"])
        #expect(restoredConfig.reference == ["/reference"])
        #expect(restoredConfig.weights == ["filename": 60, "filesize": 40])
        #expect(restoredConfig.embedThumbnails == true)
        #expect(restoredConfig.content == true)
        #expect(restoredConfig.contentMethod == .phash)
        #expect(restoredConfig.minDuration == 10.0)
        #expect(restoredConfig.maxDuration == 600.0)
        #expect(restoredConfig.codec == "hevc")
    }

    @Test("Default config fields decode correctly when absent from JSON")
    func defaultConfigFieldsDecodeWhenAbsent() throws {
        /// Verifies backward compatibility: a PersistedSession JSON that lacks the
        /// extended fields (from before the migration fix) still decodes without error,
        /// with defaults for the new fields.
        let persisted = makePersistedSession()

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(persisted)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        // Extended fields should have their defaults
        #expect(decoded.config.action == .delete) // ScanConfig default
        #expect(decoded.config.sort == .score)
        #expect(decoded.config.limit == nil)
        #expect(decoded.config.minScore == nil)
        #expect(decoded.config.exclude == [])
        #expect(decoded.config.reference == [])
        #expect(decoded.config.weights == nil)
        #expect(decoded.config.embedThumbnails == false)
        #expect(decoded.config.content == false)
        #expect(decoded.config.contentMethod == nil)
        #expect(decoded.config.minDuration == nil)
        #expect(decoded.config.maxDuration == nil)
        #expect(decoded.config.codec == nil)
    }

    @Test("Size filter round-trip through SessionConfig persists minSize and maxSize")
    func sizeFilterRoundTrip() throws {
        /// Verifies that minSize and maxSize string values survive a full
        /// PersistedSession → JSON → decode → Session(from:) round-trip.
        /// This covers the migration fix that converts ScanArgs.minSize (Int)
        /// to ScanConfig.minSize (String) via String(v).
        var config = SessionConfig()
        config.minSize = "1000000"
        config.maxSize = "5000000"

        let persisted = PersistedSession(
            id: UUID(),
            config: config,
            results: PersistedResults(
                envelope: makeEnvelope(pairs: [makePair()]),
                resolutions: [:],
                ignoredPairs: [],
                actionHistory: [],
                pendingWatchPairs: []
            ),
            metadata: SessionMetadata(
                createdAt: Date(timeIntervalSince1970: 1_700_000_000),
                directories: ["/videos"],
                sourceLabel: "size filter test",
                mode: .video,
                pairCount: 1,
                fileCount: 100
            ),
            watchConfig: nil
        )

        // JSON round-trip
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(persisted)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(PersistedSession.self, from: data)

        #expect(decoded.config.minSize == "1000000")
        #expect(decoded.config.maxSize == "5000000")

        // Full Session round-trip: Session(from:) restores config from PersistedSession
        let restored = Session(from: decoded)
        #expect(restored.config?.minSize == "1000000",
                "minSize must survive Session(from:) restoration")
        #expect(restored.config?.maxSize == "5000000",
                "maxSize must survive Session(from:) restoration")
    }
}
