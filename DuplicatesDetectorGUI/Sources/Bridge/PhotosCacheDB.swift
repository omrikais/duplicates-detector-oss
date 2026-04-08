import CryptoKit
import Foundation
import SQLite3

/// SQLite transient destructor — tells SQLite to copy bound data immediately.
/// Required because Swift string/blob pointers may be freed before `sqlite3_step`.
private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

// MARK: - Stats

/// Hit/miss counters for Photos cache operations.
struct PhotosCacheDBStats: Sendable, Equatable {
    var metadataHits: Int = 0
    var metadataMisses: Int = 0
    var scoredPairHits: Int = 0
    var scoredPairMisses: Int = 0
}

// MARK: - Cached entry wrapper

/// A cached metadata entry with its stored modification date.
struct CachedMetadataEntry: Sendable {
    let metadata: PhotoAssetMetadata
    let modDate: Date
}

// MARK: - PhotosCacheDB

/// SQLite-backed cache for Photos Library metadata and scored pairs.
///
/// Thread-safe via Swift actor isolation. Uses WAL mode for concurrent reads.
/// Modification-date-based validation ensures stale entries are never returned.
actor PhotosCacheDB {

    // MARK: - Singleton

    static let shared = PhotosCacheDB()

    // MARK: - Schema

    private static let schemaVersion = 1

    // MARK: - State

    private let databaseDirectory: URL
    private nonisolated(unsafe) var db: OpaquePointer?
    private var _stats = PhotosCacheDBStats()

    // MARK: - Init

    /// - Parameter databaseDirectory: Custom directory for the SQLite file.
    ///   Defaults to `~/Library/Application Support/DuplicatesDetector/`.
    init(databaseDirectory: URL? = nil) {
        if let dir = databaseDirectory {
            self.databaseDirectory = dir
        } else {
            let appSupport = FileManager.default.urls(
                for: .applicationSupportDirectory, in: .userDomainMask
            ).first!
            self.databaseDirectory = appSupport.appendingPathComponent("DuplicatesDetector")
        }
        self.db = Self.openDB(directory: self.databaseDirectory)
    }

    deinit {
        if let db {
            sqlite3_close(db)
        }
    }

    // MARK: - Database Setup

    /// Open the database file synchronously (called from init, nonisolated).
    private nonisolated static func openDB(directory: URL) -> OpaquePointer? {
        let fm = FileManager.default
        if !fm.fileExists(atPath: directory.path) {
            try? fm.createDirectory(at: directory, withIntermediateDirectories: true)
        }

        let dbPath = directory.appendingPathComponent("photos-cache.db").path
        var db: OpaquePointer?
        guard sqlite3_open(dbPath, &db) == SQLITE_OK else {
            return nil
        }

        // WAL mode for concurrent reads
        sqlite3_exec(db, "PRAGMA journal_mode = WAL", nil, nil, nil)
        sqlite3_exec(db, "PRAGMA synchronous = NORMAL", nil, nil, nil)

        initSchema(db: db)
        return db
    }

    /// Reopen the database after clear().
    private func reopenDatabase() {
        self.db = Self.openDB(directory: databaseDirectory)
    }

    private nonisolated static func initSchema(db: OpaquePointer?) {
        // Check if schema_version table exists and read the current version.
        var currentVersion = 0
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(
            db,
            "SELECT version FROM schema_version LIMIT 1",
            -1, &stmt, nil
        ) == SQLITE_OK, sqlite3_step(stmt) == SQLITE_ROW {
            currentVersion = Int(sqlite3_column_int(stmt, 0))
        }
        sqlite3_finalize(stmt)

        // If version matches, nothing to do.
        guard currentVersion != schemaVersion else { return }

        // Version mismatch or table absent — drop everything and recreate inside a transaction.
        // Check return codes so a half-created schema doesn't persist with the version row.
        sqlite3_exec(db, "DROP TABLE IF EXISTS photo_metadata", nil, nil, nil)
        sqlite3_exec(db, "DROP TABLE IF EXISTS scored_pairs", nil, nil, nil)
        sqlite3_exec(db, "DROP TABLE IF EXISTS schema_version", nil, nil, nil)

        let ddl: [String] = [
            "BEGIN TRANSACTION",
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE photo_metadata (
                asset_id TEXT PRIMARY KEY,
                mod_date REAL NOT NULL,
                json_data BLOB NOT NULL
            )
            """,
            """
            CREATE TABLE scored_pairs (
                asset_a TEXT NOT NULL,
                asset_b TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                mod_date_a REAL NOT NULL,
                mod_date_b REAL NOT NULL,
                score INTEGER NOT NULL,
                breakdown_json BLOB NOT NULL,
                detail_json BLOB NOT NULL,
                PRIMARY KEY (asset_a, asset_b, config_hash)
            )
            """,
            "INSERT INTO schema_version (version) VALUES (\(schemaVersion))",
        ]

        for sql in ddl {
            if sqlite3_exec(db, sql, nil, nil, nil) != SQLITE_OK {
                sqlite3_exec(db, "ROLLBACK", nil, nil, nil)
                return
            }
        }
        sqlite3_exec(db, "COMMIT", nil, nil, nil)
    }

    // MARK: - Metadata Operations

    /// Returns all cached metadata entries (no staleness check).
    func getAllCachedMetadata() -> [String: CachedMetadataEntry] {
        var result: [String: CachedMetadataEntry] = [:]
        var stmt: OpaquePointer?
        let sql = "SELECT asset_id, mod_date, json_data FROM photo_metadata"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return result }
        defer { sqlite3_finalize(stmt) }

        let decoder = JSONDecoder()
        while sqlite3_step(stmt) == SQLITE_ROW {
            let assetID = String(cString: sqlite3_column_text(stmt, 0))
            let modDateTs = sqlite3_column_double(stmt, 1)
            let blobPtr = sqlite3_column_blob(stmt, 2)
            let blobLen = sqlite3_column_bytes(stmt, 2)
            guard let blobPtr, blobLen > 0 else { continue }
            let data = Data(bytes: blobPtr, count: Int(blobLen))
            guard let metadata = try? decoder.decode(PhotoAssetMetadata.self, from: data) else { continue }
            result[assetID] = CachedMetadataEntry(
                metadata: metadata,
                modDate: Date(timeIntervalSince1970: modDateTs)
            )
        }
        return result
    }

    /// Fetch cached metadata for a batch of asset IDs, validating modification dates.
    /// Returns a dictionary of asset ID -> cached entry for hits only.
    func getMetadataBatch(
        assetIDs: [(id: String, modDate: Date)]
    ) -> [String: CachedMetadataEntry] {
        guard !assetIDs.isEmpty else { return [:] }

        var result: [String: CachedMetadataEntry] = [:]
        let decoder = JSONDecoder()

        // Prepare once, reset per iteration to avoid redundant SQL compilation.
        var stmt: OpaquePointer?
        let sql = "SELECT mod_date, json_data FROM photo_metadata WHERE asset_id = ?"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [:] }
        defer { sqlite3_finalize(stmt) }

        for (id, expectedModDate) in assetIDs {
            sqlite3_reset(stmt)
            sqlite3_bind_text(stmt, 1, (id as NSString).utf8String, -1, SQLITE_TRANSIENT)

            if sqlite3_step(stmt) == SQLITE_ROW {
                let storedModDate = sqlite3_column_double(stmt, 0)
                let expectedTs = expectedModDate.timeIntervalSince1970
                if abs(storedModDate - expectedTs) < 0.001 {
                    let blobPtr = sqlite3_column_blob(stmt, 1)
                    let blobLen = sqlite3_column_bytes(stmt, 1)
                    if let blobPtr, blobLen > 0 {
                        let data = Data(bytes: blobPtr, count: Int(blobLen))
                        if let metadata = try? decoder.decode(PhotoAssetMetadata.self, from: data) {
                            result[id] = CachedMetadataEntry(
                                metadata: metadata,
                                modDate: expectedModDate
                            )
                            _stats.metadataHits += 1
                            continue
                        }
                    }
                }
            }
            _stats.metadataMisses += 1
        }
        return result
    }

    /// Store a batch of metadata entries, replacing any existing entries.
    func putMetadataBatch(
        _ entries: [(assetID: String, modDate: Date, metadata: PhotoAssetMetadata)]
    ) {
        guard !entries.isEmpty else { return }

        let encoder = JSONEncoder()
        exec("BEGIN TRANSACTION")

        // Prepare once, reset per iteration to avoid redundant SQL compilation.
        var stmt: OpaquePointer?
        let sql = "INSERT OR REPLACE INTO photo_metadata (asset_id, mod_date, json_data) VALUES (?, ?, ?)"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            exec("ROLLBACK")
            return
        }
        defer { sqlite3_finalize(stmt) }

        for (assetID, modDate, metadata) in entries {
            guard let jsonData = try? encoder.encode(metadata) else { continue }
            sqlite3_reset(stmt)
            sqlite3_bind_text(stmt, 1, (assetID as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_double(stmt, 2, modDate.timeIntervalSince1970)
            jsonData.withUnsafeBytes { ptr in
                sqlite3_bind_blob(stmt, 3, ptr.baseAddress, Int32(jsonData.count), SQLITE_TRANSIENT)
            }
            sqlite3_step(stmt)
        }

        exec("COMMIT")
    }

    // MARK: - Scored Pairs Operations

    /// Fast: fetch only validated pair keys + scores (no JSON blob decode).
    /// Returns `(keys, aboveThreshold)` where `keys` is the set of all valid
    /// cached pair keys (for `seen`) and `aboveThreshold` is the full decoded
    /// pairs that meet the threshold (for `results`).
    func getCachedScoringData(
        configHash: String,
        assetModDates: [String: Date],
        threshold: Int
    ) -> (keys: Set<PairKey>, pairs: [PhotosScoredPair]) {
        var keys = Set<PairKey>()
        // Collect row IDs of above-threshold pairs for a second pass
        var aboveThresholdRowIDs: [(assetA: String, assetB: String)] = []

        // Pass 1: lightweight scan — no blob columns
        do {
            var stmt: OpaquePointer?
            let sql = """
                SELECT asset_a, asset_b, mod_date_a, mod_date_b, score
                FROM scored_pairs WHERE config_hash = ?
                """
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
                return (keys, [])
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, (configHash as NSString).utf8String, -1, SQLITE_TRANSIENT)

            while sqlite3_step(stmt) == SQLITE_ROW {
                let assetA = String(cString: sqlite3_column_text(stmt, 0))
                let assetB = String(cString: sqlite3_column_text(stmt, 1))
                let modDateA = sqlite3_column_double(stmt, 2)
                let modDateB = sqlite3_column_double(stmt, 3)
                let score = Int(sqlite3_column_int(stmt, 4))

                guard let expectedModA = assetModDates[assetA],
                      let expectedModB = assetModDates[assetB]
                else {
                    _stats.scoredPairMisses += 1
                    continue
                }
                guard abs(modDateA - expectedModA.timeIntervalSince1970) < 0.001,
                      abs(modDateB - expectedModB.timeIntervalSince1970) < 0.001
                else {
                    _stats.scoredPairMisses += 1
                    continue
                }

                keys.insert(PairKey(assetA, assetB))
                _stats.scoredPairHits += 1
                if score >= threshold {
                    aboveThresholdRowIDs.append((assetA: assetA, assetB: assetB))
                }
            }
        }

        // Pass 2: full decode only for above-threshold pairs
        var pairs: [PhotosScoredPair] = []
        pairs.reserveCapacity(aboveThresholdRowIDs.count)
        let decoder = JSONDecoder()
        for (assetA, assetB) in aboveThresholdRowIDs {
            var stmt: OpaquePointer?
            let sql = """
                SELECT score, breakdown_json, detail_json
                FROM scored_pairs WHERE asset_a = ? AND asset_b = ? AND config_hash = ?
                """
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { continue }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, (assetA as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 2, (assetB as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 3, (configHash as NSString).utf8String, -1, SQLITE_TRANSIENT)

            guard sqlite3_step(stmt) == SQLITE_ROW else { continue }
            let score = Int(sqlite3_column_int(stmt, 0))

            let breakdownPtr = sqlite3_column_blob(stmt, 1)
            let breakdownLen = sqlite3_column_bytes(stmt, 1)
            let breakdown: [String: Double]
            if let breakdownPtr, breakdownLen > 0 {
                let data = Data(bytes: breakdownPtr, count: Int(breakdownLen))
                breakdown = (try? decoder.decode([String: Double].self, from: data)) ?? [:]
            } else {
                breakdown = [:]
            }

            let detailPtr = sqlite3_column_blob(stmt, 2)
            let detailLen = sqlite3_column_bytes(stmt, 2)
            let detail: [String: DetailScoreTuple]
            if let detailPtr, detailLen > 0 {
                let data = Data(bytes: detailPtr, count: Int(detailLen))
                detail = (try? decoder.decode([String: DetailScoreTuple].self, from: data)) ?? [:]
            } else {
                detail = [:]
            }

            pairs.append(PhotosScoredPair(
                assetA: assetA, assetB: assetB, score: score,
                breakdown: breakdown, detail: detail
            ))
        }

        return (keys, pairs)
    }

    /// Store scored pairs with canonical ordering (asset_a < asset_b).
    func putScoredPairsBulk(
        _ entries: [(pair: PhotosScoredPair, modDateA: Date, modDateB: Date)],
        configHash: String
    ) {
        guard !entries.isEmpty else { return }

        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        exec("BEGIN TRANSACTION")

        // Prepare once, reset per iteration to avoid redundant SQL compilation.
        var stmt: OpaquePointer?
        let sql = """
            INSERT OR REPLACE INTO scored_pairs
            (asset_a, asset_b, config_hash, mod_date_a, mod_date_b, score, breakdown_json, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            exec("ROLLBACK")
            return
        }
        defer { sqlite3_finalize(stmt) }

        for (pair, modDateA, modDateB) in entries {
            // Canonical ordering: asset_a < asset_b
            let (a, b, mA, mB) = pair.assetA < pair.assetB
                ? (pair.assetA, pair.assetB, modDateA, modDateB)
                : (pair.assetB, pair.assetA, modDateB, modDateA)

            guard let breakdownData = try? encoder.encode(pair.breakdown),
                  let detailData = try? encoder.encode(pair.detail)
            else { continue }

            sqlite3_reset(stmt)
            sqlite3_bind_text(stmt, 1, (a as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 2, (b as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 3, (configHash as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_double(stmt, 4, mA.timeIntervalSince1970)
            sqlite3_bind_double(stmt, 5, mB.timeIntervalSince1970)
            sqlite3_bind_int(stmt, 6, Int32(pair.score))
            breakdownData.withUnsafeBytes { ptr in
                sqlite3_bind_blob(stmt, 7, ptr.baseAddress, Int32(breakdownData.count), SQLITE_TRANSIENT)
            }
            detailData.withUnsafeBytes { ptr in
                sqlite3_bind_blob(stmt, 8, ptr.baseAddress, Int32(detailData.count), SQLITE_TRANSIENT)
            }

            sqlite3_step(stmt)
        }

        exec("COMMIT")
    }

    // MARK: - Maintenance

    /// Remove entries for assets no longer in the library.
    func prune(activeAssetIDs: Set<String>) {
        guard !activeAssetIDs.isEmpty else { return }

        // Populate a temp table with active IDs for efficient batch deletes.
        exec("BEGIN TRANSACTION")
        exec("CREATE TEMP TABLE IF NOT EXISTS _active_ids (id TEXT PRIMARY KEY)")
        exec("DELETE FROM _active_ids")

        var insertStmt: OpaquePointer?
        let insertSQL = "INSERT OR IGNORE INTO _active_ids (id) VALUES (?)"
        guard sqlite3_prepare_v2(db, insertSQL, -1, &insertStmt, nil) == SQLITE_OK else {
            exec("ROLLBACK")
            return
        }
        for assetID in activeAssetIDs {
            sqlite3_reset(insertStmt)
            sqlite3_bind_text(insertStmt, 1, (assetID as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_step(insertStmt)
        }
        sqlite3_finalize(insertStmt)

        // Prune metadata not in the active set.
        exec("DELETE FROM photo_metadata WHERE asset_id NOT IN (SELECT id FROM _active_ids)")

        // Prune scored pairs where either asset is no longer active.
        exec("""
            DELETE FROM scored_pairs WHERE
                asset_a NOT IN (SELECT id FROM _active_ids) OR
                asset_b NOT IN (SELECT id FROM _active_ids)
            """)

        exec("DROP TABLE IF EXISTS _active_ids")
        exec("COMMIT")
    }

    /// Returns the total size of the database file in bytes.
    func totalSize() -> Int64 {
        let dbPath = databaseDirectory.appendingPathComponent("photos-cache.db").path
        let attrs = try? FileManager.default.attributesOfItem(atPath: dbPath)
        return (attrs?[.size] as? Int64) ?? 0
    }

    /// Delete the database and recreate it.
    func clear() throws {
        if let db {
            sqlite3_close(db)
            self.db = nil
        }
        let dbPath = databaseDirectory.appendingPathComponent("photos-cache.db")
        try? FileManager.default.removeItem(at: dbPath)
        // Also remove WAL/SHM files
        try? FileManager.default.removeItem(
            at: databaseDirectory.appendingPathComponent("photos-cache.db-wal")
        )
        try? FileManager.default.removeItem(
            at: databaseDirectory.appendingPathComponent("photos-cache.db-shm")
        )
        reopenDatabase()
    }

    /// Reset hit/miss counters.
    func resetStats() {
        _stats = PhotosCacheDBStats()
    }

    /// Current hit/miss counters.
    func stats() -> PhotosCacheDBStats {
        _stats
    }

    // MARK: - Config Hash

    /// Compute a deterministic hash from weight configuration.
    /// Keys are lowercased and sorted for normalization.
    nonisolated static func configHash(weights: [(String, Double)]) -> String {
        let normalized = weights
            .map { (key: $0.0.lowercased(), weight: $0.1) }
            .sorted { $0.key < $1.key }
        let canonical = normalized.map { "\($0.key)=\($0.weight)" }.joined(separator: ",")
        let hash = SHA256.hash(data: Data(canonical.utf8))
        return hash.map { String(format: "%02x", $0) }.joined()
    }

    // MARK: - Helpers

    @discardableResult
    private func exec(_ sql: String) -> Bool {
        sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK
    }
}
