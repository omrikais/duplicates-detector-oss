import Foundation

/// Shared constants for the watch notification subsystem.
public enum WatchNotificationConstants {
    /// Category identifier for watch duplicate notifications.
    /// Used by both `WatchNotificationManager` (delivery) and `AppDelegate` (tap routing).
    public static let categoryID = "WATCH_DUPLICATE"
    /// User info key for the originating session UUID string.
    public static let sessionIDKey = "sessionID"
}

/// A file known to the watch engine, with optional hash/fingerprint data.
struct KnownFile: Sendable, Equatable {
    let path: String
    let metadata: FileMetadata
    var inode: UInt64?
    var contentHash: String?
    var audioFingerprint: Data?
    /// The resolved media type for this file (`.image`, `.video`, `.audio`).
    /// Set in auto mode to prevent cross-type scoring; nil in single-mode scans.
    var effectiveMode: ScanMode?

    /// Builds a known-file set from scan result pairs (deduped by path).
    static func buildFromPairs(_ pairs: [PairResult]) -> [KnownFile] {
        var seen = Set<String>()
        var files: [KnownFile] = []
        for pair in pairs {
            if seen.insert(pair.fileA).inserted {
                files.append(KnownFile(path: pair.fileA, metadata: pair.fileAMetadata))
            }
            if seen.insert(pair.fileB).inserted {
                files.append(KnownFile(path: pair.fileB, metadata: pair.fileBMetadata))
            }
        }
        return files
    }

    /// Builds a known-file set from scan content (pairs or groups), deduped by path.
    static func buildFromContent(_ content: ScanContent) -> [KnownFile] {
        switch content {
        case .pairs(let pairs):
            return buildFromPairs(pairs)
        case .groups(let groups):
            var seen = Set<String>()
            var files: [KnownFile] = []
            for group in groups {
                for file in group.files {
                    if seen.insert(file.path).inserted {
                        files.append(KnownFile(
                            path: file.path,
                            metadata: FileMetadata(
                                duration: file.duration,
                                width: file.width,
                                height: file.height,
                                fileSize: file.fileSize,
                                codec: file.codec,
                                bitrate: file.bitrate,
                                framerate: file.framerate,
                                audioChannels: file.audioChannels,
                                mtime: file.mtime,
                                tagTitle: file.tagTitle,
                                tagArtist: file.tagArtist,
                                tagAlbum: file.tagAlbum,
                                thumbnail: file.thumbnail
                            )
                        ))
                    }
                }
            }
            return files
        }
    }
}

/// Live statistics for a watch session.
struct WatchStats: Sendable, Equatable {
    var filesDetected: Int = 0
    var duplicatesFound: Int = 0
    var trackedFiles: Int
}

/// A duplicate detected by the background scan engine.
struct DuplicateAlert: Sendable, Identifiable {
    let id = UUID()
    let newFile: URL
    let matchedFile: URL
    let score: Int
    /// Per-comparator detail: raw score (0.0–1.0) and configured weight.
    let detail: [String: DetailScore]
    let timestamp: Date
    let sessionID: UUID
    let newMetadata: FileMetadata
    let matchedMetadata: FileMetadata
}

extension DuplicateAlert {
    /// Converts to a `PairResult` for injection into the results screen.
    func toPairResult() -> PairResult {
        // Derive breakdown (weighted contribution) from detail for display.
        let breakdown: [String: Double?] = detail.reduce(into: [:]) { result, entry in
            result[entry.key] = entry.value.raw * entry.value.weight
        }
        return PairResult(
            fileA: matchedFile.path,
            fileB: newFile.path,
            score: Double(score),
            breakdown: breakdown,
            detail: detail,
            fileAMetadata: matchedMetadata,
            fileBMetadata: newMetadata,
            fileAIsReference: false,
            fileBIsReference: false,
            keep: nil
        )
    }
}

/// An active watch session tracking a set of directories.
struct WatchSession: Identifiable, Sendable {
    let id: UUID
    let config: ScanConfig
    var stats: WatchStats
    var startedAt: Date
    var sourceLabel: String

    var directories: [URL] { config.directories.map { URL(filePath: $0) } }
    var mode: ScanMode { config.mode }
}
