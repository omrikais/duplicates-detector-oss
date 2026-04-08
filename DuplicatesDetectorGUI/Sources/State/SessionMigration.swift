import Foundation
import os

// MARK: - Legacy History Migration

private let migLog = Logger(subsystem: "com.omrikaisari.DuplicatesDetector", category: "SessionMigration")

extension SessionRegistry {

    /// One-time migration from the old `ScanHistoryManager` format to the new
    /// `SessionRegistry` format.
    ///
    /// Old format (in `~/Library/Application Support/DuplicatesDetector/scans/`):
    /// - `{timestamp}-{mode}.ddscan` -- JSON envelope
    /// - `{timestamp}-{mode}.meta.json` -- `ScanHistoryEntry` metadata
    /// - `{timestamp}-{mode}.actions.json` -- `HistoryActionSidecar`
    ///
    /// New format (in `~/.local/share/duplicates-detector/sessions/`):
    /// - `{uuid}.session.json` -- `PersistedSession`
    /// - `{uuid}.envelope.dat` -- raw envelope bytes
    /// - `index.json` -- `[Entry]`
    ///
    /// Idempotent: skips entries whose UUID already exists in the registry.
    /// Graceful: individual entry failures are logged and skipped.
    /// Returns `true` if migration completed successfully or there was nothing
    /// to migrate. Returns `false` on transient errors that should allow retry.
    @discardableResult
    func migrateFromLegacyFormat(legacyDirectory: URL? = nil) async -> Bool {
        guard let legacyDir = legacyDirectory ?? Self.defaultLegacyDirectory else {
            migLog.warning("Could not determine Application Support directory — skipping migration")
            return true
        }
        let fm = FileManager.default

        guard fm.fileExists(atPath: legacyDir.path) else {
            migLog.info("No legacy history directory found at \(legacyDir.path, privacy: .public) — nothing to migrate")
            return true
        }

        // Check for migration sentinel — prevents re-migration if index is later corrupted
        let sentinelURL = legacyDir.appendingPathComponent(".migrated")
        if fm.fileExists(atPath: sentinelURL.path) {
            migLog.info("Legacy migration sentinel found — skipping migration")
            return true
        }

        // Collect existing session IDs for idempotency check
        let existingIDs: Set<UUID>
        do {
            let entries = try listEntries()
            existingIDs = Set(entries.map(\.id))
        } catch {
            migLog.error("Failed to load existing entries for migration: \(error.localizedDescription, privacy: .public)")
            return false
        }

        // Find all .meta.json files
        let contents: [URL]
        do {
            contents = try fm.contentsOfDirectory(at: legacyDir, includingPropertiesForKeys: nil)
        } catch {
            migLog.error("Failed to list legacy directory: \(error.localizedDescription, privacy: .public)")
            return false
        }

        let metaFiles = contents.filter { $0.pathExtension == "json" && $0.lastPathComponent.hasSuffix(".meta.json") }

        guard !metaFiles.isEmpty else {
            migLog.info("No .meta.json files found in legacy directory — nothing to migrate")
            return true
        }

        migLog.info("Found \(metaFiles.count, privacy: .public) legacy history entries to migrate")

        let legacyDecoder: JSONDecoder = {
            let dec = JSONDecoder()
            dec.keyDecodingStrategy = .convertFromSnakeCase
            dec.dateDecodingStrategy = .iso8601
            return dec
        }()

        // The envelope decoder uses the default (no snake_case) because
        // ScanEnvelope has custom Decodable and explicit CodingKeys
        let envelopeDecoder: JSONDecoder = {
            let dec = JSONDecoder()
            dec.dateDecodingStrategy = .iso8601
            return dec
        }()

        var migrated = 0
        var skipped = 0
        var failed = 0

        for metaFile in metaFiles {
            do {
                let entry = try decodeLegacyEntry(metaFile, decoder: legacyDecoder)

                // Idempotency: skip if session already exists
                if existingIDs.contains(entry.id) {
                    migLog.debug("Session \(entry.id, privacy: .public) already exists — skipping")
                    skipped += 1
                    continue
                }

                // Find the corresponding .ddscan envelope file
                let envelopeURL = legacyDir.appendingPathComponent(entry.envelopeFilename)
                guard fm.fileExists(atPath: envelopeURL.path) else {
                    migLog.warning("Envelope file \(entry.envelopeFilename, privacy: .public) not found — skipping entry \(entry.id, privacy: .public)")
                    failed += 1
                    continue
                }

                let envelopeData = try Data(contentsOf: envelopeURL)
                let envelope = try envelopeDecoder.decode(ScanEnvelope.self, from: envelopeData)

                // Find optional .actions.json sidecar
                let actionsFilename = entry.envelopeFilename
                    .replacingOccurrences(of: ".ddscan", with: ".actions.json")
                let actionsURL = legacyDir.appendingPathComponent(actionsFilename)
                let actionHistory: [ActionRecord]
                if fm.fileExists(atPath: actionsURL.path) {
                    let actionsData = try Data(contentsOf: actionsURL)
                    let sidecar = try legacyDecoder.decode(HistoryActionSidecar.self, from: actionsData)
                    actionHistory = sidecar.actions.compactMap { convertHistoryAction($0) }
                } else {
                    actionHistory = []
                }

                // Build config from envelope args — copy all available fields
                // so refine/export uses the original scan configuration.
                var config = SessionConfig()
                config.directories = envelope.args.directories
                config.mode = ScanMode(rawValue: envelope.args.mode) ?? .video
                config.threshold = envelope.args.threshold
                config.content = envelope.args.content
                config.group = envelope.args.group
                if let keep = envelope.args.keep.flatMap(KeepStrategy.init(rawValue:)) {
                    config.keep = keep
                }
                config.action = ActionType(rawValue: envelope.args.action) ?? .delete
                config.sort = SortField(rawValue: envelope.args.sort) ?? .score
                config.limit = envelope.args.limit
                config.minScore = envelope.args.minScore
                config.exclude = envelope.args.exclude ?? []
                config.reference = envelope.args.reference ?? []
                config.weights = envelope.args.weights?.values
                config.embedThumbnails = envelope.args.embedThumbnails

                // Content hashing options
                if let method = envelope.args.contentMethod { config.contentMethod = ContentMethod(rawValue: method) }

                // Filter options (CLI parse_size() accepts plain byte counts)
                if let v = envelope.args.minSize { config.minSize = String(v) }
                if let v = envelope.args.maxSize { config.maxSize = String(v) }
                config.minDuration = envelope.args.minDuration
                config.maxDuration = envelope.args.maxDuration
                config.minResolution = envelope.args.minResolution
                config.maxResolution = envelope.args.maxResolution
                config.minBitrate = envelope.args.minBitrate
                config.maxBitrate = envelope.args.maxBitrate
                config.codec = envelope.args.codec

                // Build metadata
                let metadata = SessionMetadata(
                    createdAt: entry.date,
                    directories: entry.directories,
                    sourceLabel: entry.directories.joined(separator: ", "),
                    mode: ScanMode(rawValue: entry.mode) ?? .video,
                    pairCount: entry.pairCount,
                    fileCount: entry.fileCount
                )

                // Materialize action history into resolutions so restored sessions
                // show previously-acted-on pairs as resolved, not active.
                // Legacy sidecars tracked the acted-on file, so mark ALL envelope
                // pairs containing that path as resolved (matching the old replay logic).
                var resolutions: [String: Resolution] = [:]
                let actionedPaths: [String: ActionRecord] = {
                    var map: [String: ActionRecord] = [:]
                    for record in actionHistory {
                        if map[record.actedOnPath] == nil {
                            map[record.actedOnPath] = record
                        }
                    }
                    return map
                }()
                let allPairs: [(String, String)]
                switch envelope.content {
                case .pairs(let pairs):
                    allPairs = pairs.map { ($0.fileA, $0.fileB) }
                case .groups(let groups):
                    allPairs = ResultsSnapshot.synthesizePairs(from: groups).map { ($0.fileA, $0.fileB) }
                }
                for (fileA, fileB) in allPairs {
                    let key = "\(fileA)\t\(fileB)"
                    if let record = actionedPaths[fileA] ?? actionedPaths[fileB] {
                        if resolutions[key] == nil {
                            resolutions[key] = .resolved(record)
                        }
                    }
                }

                // Build persisted session
                let persisted = PersistedSession(
                    id: entry.id,
                    config: config,
                    results: PersistedResults(
                        envelope: envelope,
                        resolutions: resolutions,
                        ignoredPairs: [],
                        actionHistory: actionHistory,
                        pendingWatchPairs: []
                    ),
                    metadata: metadata,
                    watchConfig: nil
                )

                try saveSession(persisted, envelopeData: envelopeData)
                migrated += 1

            } catch {
                migLog.error("Failed to migrate \(metaFile.lastPathComponent, privacy: .public): \(error.localizedDescription, privacy: .public)")
                failed += 1
            }
        }

        migLog.info("Legacy migration complete: \(migrated, privacy: .public) migrated, \(skipped, privacy: .public) skipped (duplicate), \(failed, privacy: .public) failed")

        // Write sentinel only when all entries were processed successfully.
        // Partial failures leave the sentinel absent so the next launch retries
        // the remaining entries.
        if failed == 0 {
            fm.createFile(atPath: sentinelURL.path, contents: nil)
        }
        return failed == 0
    }

    // MARK: - Private Helpers

    /// Default legacy history directory.
    static var defaultLegacyDirectory: URL? {
        guard let appSupport = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else {
            return nil
        }
        return appSupport
            .appendingPathComponent("DuplicatesDetector", isDirectory: true)
            .appendingPathComponent("scans", isDirectory: true)
    }

    /// Decode a `.meta.json` file into a `ScanHistoryEntry`.
    private func decodeLegacyEntry(_ url: URL, decoder: JSONDecoder) throws -> ScanHistoryEntry {
        let data = try Data(contentsOf: url)
        return try decoder.decode(ScanHistoryEntry.self, from: data)
    }
}

// MARK: - HistoryAction → ActionRecord Conversion

/// Convert a legacy `HistoryAction` to the new `ActionRecord` format.
///
/// Returns `nil` if the timestamp cannot be parsed.
func convertHistoryAction(_ legacy: HistoryAction) -> ActionRecord? {
    // Parse ISO 8601 timestamp
    let timestamp: Date
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = formatter.date(from: legacy.timestamp) {
        timestamp = d
    } else {
        // Try without fractional seconds
        formatter.formatOptions = [.withInternetDateTime]
        if let d = formatter.date(from: legacy.timestamp) {
            timestamp = d
        } else {
            return nil
        }
    }

    // Build PairID from path + kept
    let keptPath = legacy.kept ?? ""
    let pairID = PairIdentifier(
        fileA: keptPath,
        fileB: legacy.path
    )

    return ActionRecord(
        pairID: pairID,
        timestamp: timestamp,
        action: legacy.action,
        actedOnPath: legacy.path,
        keptPath: keptPath,
        bytesFreed: legacy.bytesFreed,
        score: Int(legacy.score.rounded()),
        strategy: legacy.strategy,
        destination: legacy.destination
    )
}
