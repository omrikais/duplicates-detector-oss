import Foundation
import os

// MARK: - PersistedResults

/// Persisted results -- serialization-friendly representation of `ResultsSnapshot`.
struct PersistedResults: Sendable, Encodable {
    /// The scan envelope containing pairs or groups.
    let envelope: ScanEnvelope
    /// Resolutions keyed by "fileA\tfileB" for JSON compatibility.
    let resolutions: [String: Resolution]
    /// Ignored pairs as sorted two-element arrays (CLI-compatible format).
    let ignoredPairs: [[String]]
    /// History of user actions on duplicate pairs.
    let actionHistory: [ActionRecord]
    /// Watch pairs that arrived while in group-mode view (not yet merged into envelope).
    let pendingWatchPairs: [PairResult]
}

extension PersistedResults: Decodable {
    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        envelope = try c.decode(ScanEnvelope.self, forKey: .envelope)
        resolutions = try c.decode([String: Resolution].self, forKey: .resolutions)
        ignoredPairs = try c.decode([[String]].self, forKey: .ignoredPairs)
        actionHistory = try c.decode([ActionRecord].self, forKey: .actionHistory)
        // Backward compat: old sessions lack this field
        pendingWatchPairs = try c.decodeIfPresent([PairResult].self, forKey: .pendingWatchPairs) ?? []
    }
}

// MARK: - PersistedSession

/// A session snapshot persisted to disk.
struct PersistedSession: Codable, Sendable {
    /// Unique session identifier.
    let id: UUID
    /// The scan configuration used for this session.
    let config: SessionConfig
    /// Results data in a serialization-friendly format.
    let results: PersistedResults
    /// Metadata for display in history lists.
    let metadata: SessionMetadata
    /// Watch configuration, if a watch was active.
    let watchConfig: WatchConfig?
}

// MARK: - Session Conversion

extension Session {

    /// Convert the current session to a persistable snapshot.
    /// Returns `nil` if the session has no results (e.g., still scanning or in setup).
    func persisted() -> PersistedSession? {
        guard let results else { return nil }

        // Convert resolutions: PairID -> "fileA\tfileB" string key
        var stringResolutions: [String: Resolution] = [:]
        for (pairID, resolution) in results.resolutions {
            let key = "\(pairID.fileA)\t\(pairID.fileB)"
            stringResolutions[key] = resolution
        }

        // Convert ignored pairs: Set<PairID> -> [[String]] sorted arrays.
        // Deduplicate: both (A,B) and (B,A) map to the same sorted pair.
        let sortedIgnoredPairs: [[String]] = Set(results.ignoredPairs.map { pairID in
            [pairID.fileA, pairID.fileB].sorted()
        }).sorted { a, b in
            a.lexicographicallyPrecedes(b)
        }

        let persistedResults = PersistedResults(
            envelope: results.envelope,
            resolutions: stringResolutions,
            ignoredPairs: sortedIgnoredPairs,
            actionHistory: results.actionHistory,
            pendingWatchPairs: results.pendingWatchPairs
        )

        let effectiveConfig = config ?? lastScanConfig ?? SessionConfig()
        return PersistedSession(
            id: id,
            config: effectiveConfig,
            results: persistedResults,
            metadata: metadata,
            watchConfig: watch.map { _ in
                WatchConfig(
                    directories: effectiveConfig.directories,
                    mode: effectiveConfig.mode,
                    threshold: effectiveConfig.threshold,
                    extensions: effectiveConfig.extensions,
                    weights: effectiveConfig.weights
                )
            }
        )
    }

    /// Reconstruct a session from a persisted snapshot, in the `.results` phase
    /// with default display state.
    init(from persisted: PersistedSession) {
        // Reconstruct resolutions: "fileA\tfileB" -> PairID
        var resolutions: [PairID: Resolution] = [:]
        for (key, resolution) in persisted.results.resolutions {
            let parts = key.split(separator: "\t", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let pairID = PairIdentifier(fileA: String(parts[0]), fileB: String(parts[1]))
            resolutions[pairID] = resolution
        }

        // Reconstruct ignored pairs: [[String]] -> Set<PairID>
        var ignoredPairs = Set<PairID>()
        for pair in persisted.results.ignoredPairs {
            guard pair.count == 2 else { continue }
            // Pairs are stored sorted, but PairIdentifier uses natural order (fileA, fileB).
            // Insert both directions so lookup works regardless of envelope order.
            ignoredPairs.insert(PairIdentifier(fileA: pair[0], fileB: pair[1]))
            ignoredPairs.insert(PairIdentifier(fileA: pair[1], fileB: pair[0]))
        }

        // Build ResultsSnapshot
        var snapshot = ResultsSnapshot(
            envelope: persisted.results.envelope,
            isDryRun: persisted.config.dryRun,
            hasKeepStrategy: persisted.results.envelope.args.keep != nil
        )
        snapshot.resolutions = resolutions
        snapshot.ignoredPairs = ignoredPairs
        snapshot.actionHistory = persisted.results.actionHistory
        snapshot.pendingWatchPairs = persisted.results.pendingWatchPairs

        self.init(
            id: persisted.id,
            phase: .results,
            config: persisted.config,
            scan: nil,
            results: snapshot,
            watch: nil,
            display: DisplayState.initial(for: persisted.results.envelope.content),
            metadata: persisted.metadata,
            scanSequence: 0,
            lastScanConfig: persisted.config,
            lastOriginalEnvelope: nil
        )
    }
}

// MARK: - SessionRegistry

/// Actor-based persistence layer for scan sessions.
///
/// Replaces `ScanHistoryManager` + `ActionLogWriter` with a unified storage model.
/// Each session produces:
/// - `{uuid}.session.json` -- the full `PersistedSession` JSON
/// - `{uuid}.envelope.dat` -- raw CLI envelope bytes (for export/replay)
/// - `index.json` -- lightweight `[Entry]` array for fast listing
///
/// Storage directory: `~/.local/share/duplicates-detector/sessions/`
public actor SessionRegistry {

    private static let logger = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "SessionRegistry")

    // MARK: - Entry

    /// Lightweight index entry for listing sessions without loading full data.
    struct Entry: Codable, Sendable, Identifiable, Equatable {
        let id: UUID
        let createdAt: Date
        let directories: [String]
        let mode: ScanMode
        let pairCount: Int
        let sourceLabel: String
        let hasWatchConfig: Bool
        /// Number of files scanned. Nil for legacy entries pre-dating enrichment.
        let filesScanned: Int?
        /// Total recoverable space in bytes. Nil for legacy entries.
        let spaceRecoverable: Int?
        /// Number of groups. Nil for legacy entries or pair-mode scans.
        let groupsCount: Int?

        init(
            id: UUID,
            createdAt: Date,
            directories: [String],
            mode: ScanMode,
            pairCount: Int,
            sourceLabel: String,
            hasWatchConfig: Bool,
            filesScanned: Int? = nil,
            spaceRecoverable: Int? = nil,
            groupsCount: Int? = nil
        ) {
            self.id = id
            self.createdAt = createdAt
            self.directories = directories
            self.mode = mode
            self.pairCount = pairCount
            self.sourceLabel = sourceLabel
            self.hasWatchConfig = hasWatchConfig
            self.filesScanned = filesScanned
            self.spaceRecoverable = spaceRecoverable
            self.groupsCount = groupsCount
        }

        init(from persisted: PersistedSession) {
            self.init(
                id: persisted.id,
                createdAt: persisted.metadata.createdAt,
                directories: persisted.metadata.directories,
                mode: persisted.metadata.mode,
                pairCount: persisted.metadata.pairCount,
                sourceLabel: persisted.metadata.sourceLabel,
                hasWatchConfig: persisted.watchConfig != nil,
                filesScanned: persisted.metadata.filesScanned,
                spaceRecoverable: persisted.metadata.spaceRecoverable,
                groupsCount: persisted.metadata.groupsCount
            )
        }
    }

    // MARK: - Errors

    enum RegistryError: Error, LocalizedError {
        case sessionNotFound(UUID)
        case corruptedData(UUID)

        var errorDescription: String? {
            switch self {
            case .sessionNotFound(let id):
                "Session \(id) not found"
            case .corruptedData(let id):
                "Session \(id) data is corrupted"
            }
        }
    }

    // MARK: - State

    private var entries: [Entry] = []
    /// Storage directory for session files. Set at init and optionally updated once
    /// by `resolveStorageDirectory(dataBase:)` before any CRUD operations.
    /// Marked `nonisolated(unsafe)` so `saveSessionSync` can read it synchronously
    /// during app teardown when async actor hops cannot complete.
    nonisolated(unsafe) private var storageDirectory: URL
    private var indexLoaded = false

    /// Serializes index.json writes between the actor-isolated `saveIndex()` and
    /// the `nonisolated` `syncUpdateIndex()` teardown path. Without this lock,
    /// a concurrent `saveSession` (on the actor) and `saveSessionSync` (nonisolated)
    /// can race on the index read-modify-write sequence, losing an entry.
    nonisolated(unsafe) private let indexLock = NSLock()

    private let encoder: JSONEncoder = {
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .iso8601
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        return enc
    }()

    private let decoder: JSONDecoder = {
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        return dec
    }()

    // MARK: - Init

    /// Default storage directory: `~/.local/share/duplicates-detector/sessions/`
    static var defaultStorageDirectory: URL {
        let xdgDataHome: URL
        if let xdg = ProcessInfo.processInfo.environment["XDG_DATA_HOME"], !xdg.isEmpty {
            xdgDataHome = URL(fileURLWithPath: xdg, isDirectory: true)
        } else {
            xdgDataHome = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent(".local", isDirectory: true)
                .appendingPathComponent("share", isDirectory: true)
        }
        return xdgDataHome
            .appendingPathComponent("duplicates-detector", isDirectory: true)
            .appendingPathComponent("sessions", isDirectory: true)
    }

    init(storageDirectory: URL? = nil) {
        self.storageDirectory = storageDirectory ?? Self.defaultStorageDirectory
    }

    /// Update the storage directory from the resolved login-shell XDG path.
    /// Call once at startup (before any CRUD operations) so Finder-launched
    /// instances use the same data path as shell-launched ones.
    func resolveStorageDirectory(dataBase: URL) {
        guard !indexLoaded else { return }
        storageDirectory = dataBase.appendingPathComponent("sessions", isDirectory: true)
    }

    // MARK: - CRUD

    /// List all saved session entries, sorted by date (newest first).
    func listEntries() throws -> [Entry] {
        try ensureIndexLoaded()
        return entries.sorted { $0.createdAt > $1.createdAt }
    }

    /// Save a session and its raw envelope data.
    func saveSession(_ persisted: PersistedSession, envelopeData: Data?) throws {
        try ensureDirectory()
        try ensureIndexLoaded()

        // Encode session JSON
        let sessionData = try encoder.encode(persisted)

        // Write session file atomically
        let sessionURL = sessionFileURL(for: persisted.id)
        try atomicWrite(data: sessionData, to: sessionURL)

        // Write raw envelope bytes if available
        if let envelopeData {
            let envelopeURL = envelopeFileURL(for: persisted.id)
            try atomicWrite(data: envelopeData, to: envelopeURL)
        }

        // Update index
        let entry = Entry(from: persisted)

        // Replace existing entry with same ID, or append
        if let idx = entries.firstIndex(where: { $0.id == persisted.id }) {
            entries[idx] = entry
        } else {
            entries.append(entry)
        }

        try saveIndex()
    }

    /// Load a full persisted session by ID.
    func loadSession(_ id: UUID) throws -> PersistedSession {
        try ensureIndexLoaded()

        let sessionURL = sessionFileURL(for: id)
        guard FileManager.default.fileExists(atPath: sessionURL.path) else {
            throw RegistryError.sessionNotFound(id)
        }

        let data = try Data(contentsOf: sessionURL)
        do {
            return try decoder.decode(PersistedSession.self, from: data)
        } catch {
            throw RegistryError.corruptedData(id)
        }
    }

    /// Load raw envelope bytes for a session (for export/replay).
    func loadEnvelopeData(_ id: UUID) throws -> Data? {
        let url = envelopeFileURL(for: id)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try Data(contentsOf: url)
    }

    /// Delete a session and all its associated files.
    func deleteSession(_ id: UUID) throws {
        try ensureIndexLoaded()
        deleteSessionFiles(id)
        entries.removeAll { $0.id == id }
        try saveIndex()
    }

    /// Prune old sessions, keeping at most `keep` entries (newest first).
    func pruneOldSessions(keep count: Int) throws {
        try ensureIndexLoaded()

        let sorted = entries.sorted { $0.createdAt > $1.createdAt }
        guard sorted.count > count else { return }

        let idsToRemove = Set(sorted.dropFirst(count).map(\.id))
        for id in idsToRemove {
            deleteSessionFiles(id)
        }
        entries.removeAll { idsToRemove.contains($0.id) }
        try saveIndex()
    }

    /// Remove session and envelope files for a given ID (no index update).
    private func deleteSessionFiles(_ id: UUID) {
        let fm = FileManager.default
        try? fm.removeItem(at: sessionFileURL(for: id))
        try? fm.removeItem(at: envelopeFileURL(for: id))
    }

    // MARK: - File Paths

    private func sessionFileURL(for id: UUID) -> URL {
        storageDirectory.appendingPathComponent("\(id.uuidString).session.json")
    }

    private func envelopeFileURL(for id: UUID) -> URL {
        storageDirectory.appendingPathComponent("\(id.uuidString).envelope.dat")
    }

    private var indexFileURL: URL {
        storageDirectory.appendingPathComponent("index.json")
    }

    // MARK: - Private Helpers

    /// Ensure the storage directory exists.
    private func ensureDirectory() throws {
        try FileManager.default.createDirectory(
            at: storageDirectory, withIntermediateDirectories: true
        )
    }

    /// Load the index from disk if not already loaded.
    private func ensureIndexLoaded() throws {
        guard !indexLoaded else { return }
        try ensureDirectory()

        let url = indexFileURL
        if FileManager.default.fileExists(atPath: url.path) {
            let data = try Data(contentsOf: url)
            do {
                entries = try decoder.decode([Entry].self, from: data)
            } catch {
                Self.logger.warning("Corrupted session index, attempting recovery: \(error.localizedDescription)")
                let backupURL = url.deletingLastPathComponent()
                    .appendingPathComponent("index.json.corrupt")
                try? FileManager.default.moveItem(at: url, to: backupURL)
                entries = rebuildIndexFromSessionFiles()
            }
        } else {
            entries = []
        }
        indexLoaded = true
    }

    /// Scan the storage directory for `.session.json` files and rebuild index entries.
    private func rebuildIndexFromSessionFiles() -> [Entry] {
        let fm = FileManager.default
        var rebuilt: [Entry] = []

        guard let contents = try? fm.contentsOfDirectory(
            at: storageDirectory, includingPropertiesForKeys: nil
        ) else {
            return rebuilt
        }

        for fileURL in contents where fileURL.pathExtension == "json"
            && fileURL.lastPathComponent.hasSuffix(".session.json")
        {
            do {
                let data = try Data(contentsOf: fileURL)
                let session = try decoder.decode(PersistedSession.self, from: data)
                rebuilt.append(Entry(from: session))
            } catch {
                Self.logger.warning(
                    "Skipping unreadable session file \(fileURL.lastPathComponent): \(error.localizedDescription)"
                )
            }
        }

        if !rebuilt.isEmpty {
            Self.logger.info("Rebuilt session index with \(rebuilt.count) entries from session files")
        }

        return rebuilt
    }

    /// Save the index to disk atomically.
    private func saveIndex() throws {
        let data = try encoder.encode(entries)
        indexLock.lock()
        defer { indexLock.unlock() }
        try atomicWrite(data: data, to: indexFileURL)
    }

    /// Synchronous, fire-and-forget save for teardown paths where async work
    /// cannot be relied upon (e.g., `applicationWillTerminate`).
    ///
    /// Writes the session file, envelope, and updates the index entry.
    /// `nonisolated` so it can be called from synchronous contexts without
    /// awaiting the actor.
    nonisolated func saveSessionSync(_ persisted: PersistedSession, envelopeData: Data?) {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let sessionData = try? encoder.encode(persisted) else { return }

        try? FileManager.default.createDirectory(
            at: storageDirectory, withIntermediateDirectories: true
        )

        let sessionURL = storageDirectory.appendingPathComponent("\(persisted.id.uuidString).session.json")
        try? sessionData.write(to: sessionURL, options: .atomic)

        if let envelopeData {
            let envelopeURL = storageDirectory.appendingPathComponent("\(persisted.id.uuidString).envelope.dat")
            try? envelopeData.write(to: envelopeURL, options: .atomic)
        }

        // Update the index so this session appears in history on next launch.
        syncUpdateIndex(for: persisted, encoder: encoder)
    }

    /// Read-modify-write the index.json synchronously for a single session entry.
    ///
    /// Acquires `indexLock` to prevent racing with the actor-isolated `saveIndex()`.
    private nonisolated func syncUpdateIndex(for persisted: PersistedSession, encoder: JSONEncoder) {
        let indexURL = storageDirectory.appendingPathComponent("index.json")
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        indexLock.lock()
        defer { indexLock.unlock() }

        var entries: [Entry] = []
        if let data = try? Data(contentsOf: indexURL) {
            entries = (try? decoder.decode([Entry].self, from: data)) ?? []
        }

        let newEntry = Entry(from: persisted)
        if let idx = entries.firstIndex(where: { $0.id == persisted.id }) {
            entries[idx] = newEntry
        } else {
            entries.append(newEntry)
        }

        if let indexData = try? encoder.encode(entries) {
            try? indexData.write(to: indexURL, options: .atomic)
        }
    }

    // MARK: - Trend Matching

    /// Find past scans that overlap with the given directories for trend analysis.
    ///
    /// Filters to entries that have enrichment data (`filesScanned != nil`),
    /// match the given scan mode, and share at least 50% Jaccard directory
    /// overlap with the given set. Returns up to 10 entries in ascending
    /// chronological order (oldest first).
    static func findMatchingScans(
        for directories: [String],
        mode: ScanMode,
        in entries: [Entry],
        upTo anchor: Date? = nil
    ) -> [Entry] {
        let currentSet = Set(directories)
        return Array(
            entries
                .filter { entry in
                    guard entry.filesScanned != nil else { return false }
                    guard entry.mode == mode else { return false }
                    if let anchor, entry.createdAt > anchor { return false }
                    let entrySet = Set(entry.directories)
                    let union = currentSet.union(entrySet)
                    guard !union.isEmpty else { return false }
                    let overlap = currentSet.intersection(entrySet)
                    return Double(overlap.count) / Double(union.count) >= 0.5
                }
                .sorted { $0.createdAt < $1.createdAt }
                .suffix(10)
        )
    }

    // MARK: - Atomic I/O

    /// Write data atomically: write to a temp file then rename.
    private func atomicWrite(data: Data, to url: URL) throws {
        let dir = url.deletingLastPathComponent()
        let tempURL = dir.appendingPathComponent(".\(UUID().uuidString).tmp")
        try data.write(to: tempURL, options: [])
        var moved = false
        defer { if !moved { try? FileManager.default.removeItem(at: tempURL) } }
        if FileManager.default.fileExists(atPath: url.path) {
            _ = try FileManager.default.replaceItemAt(url, withItemAt: tempURL)
        } else {
            try FileManager.default.moveItem(at: tempURL, to: url)
        }
        moved = true
    }
}
