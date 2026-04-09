@preconcurrency import AppKit
import CryptoKit
import Foundation
import QuickLookThumbnailing

/// Actor that resolves and caches file thumbnails for the results views.
///
/// Resolution chain:
/// 1. Memory cache hit (NSCache, keyed by path + size + mtime)
/// 2. Disk cache hit (mtime-validated PNG in ~/Library/Caches, keyed by path + size)
/// 3. Embedded base64 data from the CLI envelope
/// 4. QuickLook thumbnail generation
/// 5. Native fallback: NSWorkspace file icon
/// 6. All failed: nil
actor ThumbnailProvider {
    static let shared = ThumbnailProvider()

    private let memoryCache = NSCache<NSString, NSImage>()
    private let diskCacheDir: URL

    private static let memoryCacheCountLimit = 500
    /// 100 MB memory limit (cost = w * h * 4 bytes per pixel).
    private static let memoryCacheTotalCostLimit = 100 * 1024 * 1024
    /// 500 MB disk cache eviction threshold.
    private static let diskCacheMaxBytes = 500 * 1024 * 1024

    private var prefetchTasks: [String: Task<Void, Never>] = [:]
    private static let maxConcurrentPrefetches = 6

    private init() {
        diskCacheDir = CacheManager.thumbnailCacheDirectory

        memoryCache.countLimit = Self.memoryCacheCountLimit
        memoryCache.totalCostLimit = Self.memoryCacheTotalCostLimit

        Task { await self.pruneCache() }
    }

    /// Prefetch thumbnails for upcoming pairs so they're warm in cache when navigated to.
    /// Cancels stale in-flight prefetches and caps concurrency.
    func prefetch(paths: [(path: String, base64: String?, modificationDate: Date?)], size: CGSize) {
        let requestedPaths = Set(paths.map(\.path))

        // Cancel stale prefetches no longer in the upcoming window
        for path in prefetchTasks.keys where !requestedPaths.contains(path) {
            prefetchTasks[path]?.cancel()
            prefetchTasks.removeValue(forKey: path)
        }

        // Spawn new prefetches up to the concurrency limit
        for item in paths {
            guard prefetchTasks[item.path] == nil else { continue }
            guard prefetchTasks.count < Self.maxConcurrentPrefetches else { break }
            let path = item.path
            let base64 = item.base64
            let modDate = item.modificationDate
            prefetchTasks[path] = Task {
                _ = await resolve(path: path, embeddedBase64: base64, size: size, modificationDate: modDate)
                prefetchTasks.removeValue(forKey: path)
            }
        }
    }

    /// Resolve a thumbnail for a file, using the fastest available source.
    func resolve(path: String, embeddedBase64: String?, size: CGSize, modificationDate: Date? = nil) async -> NSImage? {
        let sizeKey = "\(Int(size.width))x\(Int(size.height))"

        // Photos Library assets — route to PhotoKitBridge (returns NSImage directly)
        if path.isPhotosAssetURI, let assetID = path.photosAssetID {
            let cacheKey = NSString(string: "\(path)@\(sizeKey)")
            if let cached = memoryCache.object(forKey: cacheKey) {
                return cached
            }

            // Disk cache check (modificationDate-validated)
            if let modDate = modificationDate {
                let diskCacheURL = cacheFileURL(for: path, sizeKey: sizeKey)
                if let diskImage = loadPhotoDiskCache(url: diskCacheURL, modificationDate: modDate) {
                    store(diskImage, forKey: cacheKey)
                    return diskImage
                }
            }

            if let nsImage = await PhotoKitBridge.shared.fetchThumbnail(
                assetID: assetID, size: CGSize(width: size.width, height: size.height)
            ) {
                store(nsImage, forKey: cacheKey)
                saveToDiskCache(nsImage, path: path, sizeKey: sizeKey)
                return nsImage
            }
            return nil // No filesystem fallback for Photos assets
        }

        // 1. Memory cache (mtime-validated)
        let mtime = (try? FileManager.default.attributesOfItem(atPath: path)[.modificationDate] as? Date)?
            .timeIntervalSince1970 ?? 0
        let key = NSString(string: "\(path)@\(sizeKey)@\(Int(mtime))")
        if let cached = memoryCache.object(forKey: key) {
            return cached
        }

        // 2. Disk cache (mtime-validated)
        if let diskImage = loadFromDiskCache(path: path, sizeKey: sizeKey) {
            store(diskImage, forKey: key)
            return diskImage
        }

        // 3. Embedded base64
        if let b64 = embeddedBase64,
           let data = Data(base64Encoded: b64),
           let image = NSImage(data: data) {
            store(image, forKey: key)
            saveToDiskCache(image, path: path, sizeKey: sizeKey)
            return image
        }

        // 4. QuickLook
        if let qlImage = await generateQuickLookThumbnail(path: path, size: size) {
            store(qlImage, forKey: key)
            saveToDiskCache(qlImage, path: path, sizeKey: sizeKey)
            return qlImage
        }

        // 5. Workspace file icon (synchronous, always available)
        let icon = NSWorkspace.shared.icon(forFile: path)
        let resizedIcon = resizeImage(icon, to: size)
        store(resizedIcon, forKey: key)
        return resizedIcon
    }

    /// Evict disk cache entries by access date when total exceeds the size limit.
    func pruneCache() {
        let fm = FileManager.default
        guard let enumerator = fm.enumerator(
            at: diskCacheDir,
            includingPropertiesForKeys: [.fileSizeKey, .contentAccessDateKey],
            options: [.skipsHiddenFiles]
        ) else { return }

        var entries: [(url: URL, size: Int, accessed: Date)] = []
        var totalSize = 0
        for case let url as URL in enumerator {
            guard let values = try? url.resourceValues(forKeys: [.fileSizeKey, .contentAccessDateKey]) else {
                continue
            }
            let size = values.fileSize ?? 0
            let accessed = values.contentAccessDate ?? .distantPast
            entries.append((url, size, accessed))
            totalSize += size
        }

        guard totalSize > Self.diskCacheMaxBytes else { return }

        // Sort oldest-accessed first for eviction
        entries.sort { $0.accessed < $1.accessed }
        for entry in entries {
            guard totalSize > Self.diskCacheMaxBytes else { break }
            try? fm.removeItem(at: entry.url)
            totalSize -= entry.size
        }
    }

    // MARK: - Private

    private func store(_ image: NSImage, forKey key: NSString) {
        let cost = Int(image.size.width * image.size.height * 4)
        memoryCache.setObject(image, forKey: key, cost: cost)
    }

    private func cacheFileURL(for path: String, sizeKey: String) -> URL {
        let raw = "\(path)@\(sizeKey)"
        let hash = SHA256.hash(data: Data(raw.utf8))
        let hex = hash.prefix(16).map { String(format: "%02x", $0) }.joined()
        return diskCacheDir.appendingPathComponent("\(hex).png")
    }

    private func loadFromDiskCache(path: String, sizeKey: String) -> NSImage? {
        let cacheURL = cacheFileURL(for: path, sizeKey: sizeKey)
        let fm = FileManager.default
        guard fm.fileExists(atPath: cacheURL.path) else { return nil }

        // Validate mtime: source must not be newer than cache
        guard let sourceAttrs = try? fm.attributesOfItem(atPath: path),
              let sourceMtime = sourceAttrs[.modificationDate] as? Date,
              let cacheAttrs = try? fm.attributesOfItem(atPath: cacheURL.path),
              let cacheCreation = cacheAttrs[.creationDate] as? Date
        else {
            try? fm.removeItem(at: cacheURL)
            return nil
        }

        if sourceMtime > cacheCreation {
            try? fm.removeItem(at: cacheURL)
            return nil
        }

        return NSImage(contentsOf: cacheURL)
    }

    /// Load a Photos asset thumbnail from disk cache, validating by modificationDate.
    /// Unlike filesystem thumbnails (validated by source file mtime), Photos assets
    /// have no local file — we use the PHAsset modificationDate instead.
    private func loadPhotoDiskCache(url: URL, modificationDate: Date) -> NSImage? {
        let fm = FileManager.default
        guard fm.fileExists(atPath: url.path) else { return nil }
        guard let cacheAttrs = try? fm.attributesOfItem(atPath: url.path),
              let cacheCreation = cacheAttrs[.creationDate] as? Date
        else {
            try? fm.removeItem(at: url)
            return nil
        }
        // If the asset was modified after the cache was created, invalidate
        if modificationDate > cacheCreation {
            try? fm.removeItem(at: url)
            return nil
        }
        return NSImage(contentsOf: url)
    }

    private func saveToDiskCache(_ image: NSImage, path: String, sizeKey: String) {
        let cacheURL = cacheFileURL(for: path, sizeKey: sizeKey)
        let fm = FileManager.default

        try? fm.createDirectory(at: diskCacheDir, withIntermediateDirectories: true)

        guard let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let pngData = bitmap.representation(using: .png, properties: [:])
        else { return }

        // Atomic write via temp file + rename
        let tempURL = diskCacheDir.appendingPathComponent(UUID().uuidString + ".tmp")
        do {
            try pngData.write(to: tempURL, options: .atomic)
            try? fm.removeItem(at: cacheURL)
            try fm.moveItem(at: tempURL, to: cacheURL)
        } catch {
            try? fm.removeItem(at: tempURL)
        }
    }

    private func generateQuickLookThumbnail(path: String, size: CGSize) async -> NSImage? {
        let url = URL(fileURLWithPath: path)
        let request = QLThumbnailGenerator.Request(
            fileAt: url,
            size: size,
            scale: 2.0,
            representationTypes: .thumbnail
        )

        do {
            let representation = try await QLThumbnailGenerator.shared.generateBestRepresentation(for: request)
            return representation.nsImage
        } catch {
            return nil
        }
    }

    private func resizeImage(_ image: NSImage, to size: CGSize) -> NSImage {
        // Use block-based init instead of lockFocus/unlockFocus for thread safety.
        NSImage(size: size, flipped: false) { rect in
            image.draw(in: rect,
                       from: NSRect(origin: .zero, size: image.size),
                       operation: .copy, fraction: 1.0)
            return true
        }
    }
}
