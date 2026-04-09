import AppKit
import Foundation

/// Cache file operations matching the CLI's ``cache.py`` XDG layout.
///
/// Default directory: `$XDG_CACHE_HOME/duplicates-detector/`
/// (fallback: `~/.cache/duplicates-detector/`).
enum CacheManager {
    static let metadataFilename = "metadata.json"
    static let contentHashFilename = "content-hashes.json"
    static let audioFingerprintFilename = "audio-fingerprints.json"

    /// Default cache directory resolved from the user's login shell XDG environment.
    static func resolvedDefaultCacheDirectory() async -> URL {
        await ShellEnvironmentResolver.shared.cacheBaseDirectory()
    }

    /// Sync fallback (reads process environment only — may be wrong for Finder-launched apps).
    static var defaultCacheDirectory: URL {
        let base: String
        if let xdg = ProcessInfo.processInfo.environment["XDG_CACHE_HOME"], !xdg.isEmpty {
            base = xdg
        } else {
            base = (NSHomeDirectory() as NSString).appendingPathComponent(".cache")
        }
        return URL(fileURLWithPath: base)
            .appendingPathComponent("duplicates-detector")
    }

    /// Returns file sizes in bytes for each cache file. `nil` if the file is missing.
    static func cacheSizes(directory: URL? = nil) -> (metadata: Int64?, content: Int64?, audio: Int64?) {
        let dir = directory ?? defaultCacheDirectory
        return (
            metadata: fileSize(dir.appendingPathComponent(metadataFilename)),
            content: fileSize(dir.appendingPathComponent(contentHashFilename)),
            audio: fileSize(dir.appendingPathComponent(audioFingerprintFilename))
        )
    }

    /// Sum of all existing cache file sizes.
    static func totalCacheSize(directory: URL? = nil) -> Int64 {
        let sizes = cacheSizes(directory: directory)
        return (sizes.metadata ?? 0) + (sizes.content ?? 0) + (sizes.audio ?? 0)
    }

    /// Remove a specific cache file by filename.
    static func clearCache(filename: String, directory: URL? = nil) throws {
        let dir = directory ?? defaultCacheDirectory
        let path = dir.appendingPathComponent(filename)
        do {
            try FileManager.default.removeItem(at: path)
        } catch let error as CocoaError where error.code == .fileNoSuchFile || error.code == .fileReadNoSuchFile {
            // Already gone — nothing to do
        }
    }

    /// Remove all three cache files.
    static func clearAllCaches(directory: URL? = nil) throws {
        let dir = directory ?? defaultCacheDirectory
        for name in [metadataFilename, contentHashFilename, audioFingerprintFilename] {
            let path = dir.appendingPathComponent(name)
            do {
                try FileManager.default.removeItem(at: path)
            } catch let error as CocoaError where error.code == .fileNoSuchFile || error.code == .fileReadNoSuchFile {
                // Already gone — nothing to do
            }
        }
    }

    /// Open the cache directory in Finder.
    static func revealInFinder(directory: URL? = nil) {
        let dir = directory ?? defaultCacheDirectory
        if FileManager.default.fileExists(atPath: dir.path) {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: dir.path)
        } else {
            // If directory doesn't exist, open its parent
            let parent = dir.deletingLastPathComponent()
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: parent.path)
        }
    }

    // MARK: - Thumbnail Cache

    static let thumbnailCacheDirectory: URL = {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        return caches
            .appendingPathComponent("DuplicatesDetector", isDirectory: true)
            .appendingPathComponent("thumbnails", isDirectory: true)
    }()

    // MARK: - Photos Library Cache

    /// Total size of the Photos metadata & scores database.
    static func photosCacheSize() async -> Int64 {
        await PhotosCacheDB.shared.totalSize()
    }

    /// Delete and recreate the Photos metadata & scores database.
    static func clearPhotosCache() async throws {
        try await PhotosCacheDB.shared.clear()
    }

    /// Total size of the thumbnail disk cache directory.
    static func thumbnailCacheSize() -> Int64 {
        directorySize(thumbnailCacheDirectory)
    }

    /// Remove the entire thumbnail disk cache directory.
    static func clearThumbnailCache() throws {
        do {
            try FileManager.default.removeItem(at: thumbnailCacheDirectory)
        } catch let error as CocoaError where error.code == .fileNoSuchFile || error.code == .fileReadNoSuchFile {
            // Already gone — nothing to do
        }
    }

    // MARK: - Helpers

    private static func fileSize(_ url: URL) -> Int64? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path) else { return nil }
        return attrs[.size] as? Int64
    }

    private static func directorySize(_ url: URL) -> Int64 {
        let fm = FileManager.default
        guard let enumerator = fm.enumerator(
            at: url, includingPropertiesForKeys: [.fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else { return 0 }
        var total: Int64 = 0
        for case let fileURL as URL in enumerator {
            if let size = try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                total += Int64(size)
            }
        }
        return total
    }
}
