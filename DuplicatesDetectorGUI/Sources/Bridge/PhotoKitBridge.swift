import AppKit
import CoreLocation
import ImageIO
import Photos

/// Concrete PhotoKit bridge that interacts with the real Photos Library.
///
/// All PhotoKit calls run off `@MainActor` via the actor isolation.
/// `fetchAssets()` is a `nonisolated static` helper because
/// `PHFetchResult.enumerateObjects` requires a non-isolated synchronous
/// closure in Swift 6 strict concurrency.
actor PhotoKitBridge: PhotoKitBridgeProtocol {

    static let shared = PhotoKitBridge()

    private init() {}

    // MARK: - Authorization

    func requestAuthorization() async -> PHAuthorizationStatus {
        await withCheckedContinuation { continuation in
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
                continuation.resume(returning: status)
            }
        }
    }

    // MARK: - Authorization Helpers

    /// Check if Photos authorization is still granted (`.authorized` or `.limited`).
    /// Used to detect mid-scan auth revocation at stage boundaries.
    nonisolated static func isStillAuthorized() -> Bool {
        let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        return status == .authorized || status == .limited
    }

    // MARK: - Scan

    func scanLibrary(
        scope: PhotosScope, threshold: Int, weights: [(String, Double)]?,
        onProgress: @Sendable @escaping (ProgressEvent) -> Void
    ) async throws -> [PhotosScoredPair] {
        let (assets, _, _) = try Self.fetchAssets(scope: scope, onProgress: onProgress)
        return PhotosScorer.score(assets, threshold: threshold, weights: weights).pairs
    }

    // MARK: - Asset Fetching (nonisolated static)

    /// Fetch all eligible assets from the Photos Library.
    ///
    /// This is `nonisolated static` because `PHFetchResult.enumerateObjects`
    /// requires a non-isolated synchronous closure under Swift 6 strict concurrency.
    ///
    /// - Parameters:
    ///   - scope: Which portion of the library to scan.
    ///   - cachedMetadata: Pre-loaded cached metadata keyed by asset local identifier.
    ///     When a cache hit matches by modification date, the expensive
    ///     `PHAssetResource.assetResources` and album-name lookups are skipped.
    ///   - isCancelled: Polled each iteration; stops enumeration when true.
    ///   - onProgress: Called for each asset with throughput info.
    /// - Returns: A tuple of all asset metadata and new entries that were not in the cache
    ///   (suitable for writing back to the cache).
    nonisolated static func fetchAssets(
        scope: PhotosScope,
        cachedMetadata: [String: (modDate: Date, metadata: PhotoAssetMetadata)]? = nil,
        isCancelled: (@Sendable () -> Bool)? = nil,
        onProgress: @Sendable @escaping (ProgressEvent) -> Void
    ) throws -> (assets: [PhotoAssetMetadata], newEntries: [(String, Date, PhotoAssetMetadata)], iCloudSkipped: Int) {
        let options = PHFetchOptions()
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        // Fetch images and videos
        options.predicate = NSPredicate(
            format: "mediaType == %d OR mediaType == %d",
            PHAssetMediaType.image.rawValue,
            PHAssetMediaType.video.rawValue
        )

        let fetchResult = PHAsset.fetchAssets(with: options)
        let total = fetchResult.count

        guard total > 0 else {
            return (assets: [], newEntries: [], iCloudSkipped: 0)
        }

        let formatter = ISO8601DateFormatter()
        let startTime = DispatchTime.now()
        var assets: [PhotoAssetMetadata] = []
        assets.reserveCapacity(total)
        var newEntries: [(String, Date, PhotoAssetMetadata)] = []
        var cacheHits = 0
        var cacheMisses = 0
        var iCloudSkipped = 0

        fetchResult.enumerateObjects { asset, index, stop in
            if isCancelled?() == true {
                stop.pointee = true
                return
            }

            let assetModDate = asset.modificationDate ?? asset.creationDate ?? Date.distantPast

            // Cache hit — skip expensive PHAssetResource + albumNames calls.
            // iCloud availability is NOT re-checked here because
            // PHAssetResource.assetResources(for:) is ~2ms per asset and would
            // negate the entire cache benefit on large libraries. Instead,
            // iCloud-offloaded assets in results are filtered post-scoring via
            // filterOffloadedAssets() on the much smaller set of paired assets.
            // Use epsilon comparison (< 1ms) because the Date round-trip through
            // timeIntervalSince1970 → SQLite REAL → Date(timeIntervalSince1970:)
            // can lose sub-microsecond precision due to IEEE 754 (x+offset)-offset != x.
            if let cached = cachedMetadata?[asset.localIdentifier],
               abs(cached.modDate.timeIntervalSince1970 - assetModDate.timeIntervalSince1970) < 0.001
            {
                cacheHits += 1
                assets.append(cached.metadata)
                let elapsed = Double(
                    DispatchTime.now().uptimeNanoseconds - startTime.uptimeNanoseconds
                ) / 1_000_000_000
                let rate = elapsed > 0 ? Double(index + 1) / elapsed : 0
                onProgress(.progress(StageProgressEvent(
                    stage: "extract", current: index + 1,
                    timestamp: formatter.string(from: Date()),
                    total: total, file: nil, rate: rate,
                    cacheHits: cacheHits, cacheMisses: cacheMisses
                )))
                return
            }

            // Identify the primary resource and check local availability.
            let resources = PHAssetResource.assetResources(for: asset)
            let primaryTypes: Set<PHAssetResourceType> = [.photo, .video, .fullSizePhoto, .fullSizeVideo]
            guard let primary = resources.first(where: { primaryTypes.contains($0.type) }) else {
                return
            }

            // Skip iCloud-only assets whose data isn't downloaded locally.
            // locallyAvailable is not public API but stable KVC (same pattern as fileSize).
            let locallyAvailable: Bool
            if primary.responds(to: Selector(("locallyAvailable"))) {
                locallyAvailable = (primary.value(forKey: "locallyAvailable") as? Bool) ?? true
            } else {
                locallyAvailable = true
            }
            guard locallyAvailable else {
                iCloudSkipped += 1
                return
            }

            // Extract file size from primary resource (private KVC, same guard as locallyAvailable).
            let fileSize: Int64
            if primary.responds(to: Selector(("fileSize"))) {
                fileSize = (primary.value(forKey: "fileSize") as? Int64) ?? 0
            } else {
                fileSize = 0
            }

            // Extract filename
            let filename = primary.originalFilename

            // Extract EXIF-like metadata
            let location = asset.location
            // Read camera model and lens from image EXIF via ImageIO.
            // PHAsset doesn't expose these directly, but PHAssetResource
            // provides a fileURL (private KVC, same pattern as fileSize/locallyAvailable).
            var cameraModel: String?
            var lensModel: String?
            if asset.mediaType == .image,
               primary.responds(to: Selector(("fileURL"))),
               let fileURL = primary.value(forKey: "fileURL") as? URL,
               let source = CGImageSourceCreateWithURL(fileURL as CFURL, nil),
               let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any]
            {
                let tiff = props[kCGImagePropertyTIFFDictionary as String] as? [String: Any]
                cameraModel = tiff?[kCGImagePropertyTIFFModel as String] as? String
                let exif = props[kCGImagePropertyExifDictionary as String] as? [String: Any]
                lensModel = exif?[kCGImagePropertyExifLensModel as String] as? String
            }

            // Album names
            let albumNames = albumNamesForAsset(asset)

            let metadata = PhotoAssetMetadata(
                id: asset.localIdentifier,
                filename: filename,
                duration: asset.mediaType == .video ? asset.duration : nil,
                width: asset.pixelWidth,
                height: asset.pixelHeight,
                fileSize: fileSize,
                creationDate: asset.creationDate,
                modificationDate: asset.modificationDate,
                latitude: location?.coordinate.latitude,
                longitude: location?.coordinate.longitude,
                cameraModel: cameraModel,
                lensModel: lensModel,
                albumNames: albumNames,
                mediaType: asset.mediaType
            )
            cacheMisses += 1
            assets.append(metadata)
            newEntries.append((asset.localIdentifier, assetModDate, metadata))

            // Emit progress event with throughput
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startTime.uptimeNanoseconds) / 1_000_000_000
            let rate = elapsed > 0 ? Double(index + 1) / elapsed : 0
            let event = StageProgressEvent(
                stage: "extract",
                current: index + 1,
                timestamp: formatter.string(from: Date()),
                total: total,
                file: nil,
                rate: rate,
                cacheHits: cacheHits,
                cacheMisses: cacheMisses
            )
            onProgress(.progress(event))
        }

        return (assets: assets, newEntries: newEntries, iCloudSkipped: iCloudSkipped)
    }

    /// Resolve album names for a given asset.
    ///
    /// `nonisolated static` for use inside `enumerateObjects` closures.
    nonisolated static func albumNamesForAsset(_ asset: PHAsset) -> [String] {
        let collections = PHAssetCollection.fetchAssetCollectionsContaining(
            asset, with: .album, options: nil
        )
        var names: [String] = []
        collections.enumerateObjects { collection, _, _ in
            if let title = collection.localizedTitle {
                names.append(title)
            }
        }
        return names
    }

    // MARK: - Thumbnails

    func fetchThumbnail(assetID: String, size: CGSize) async -> NSImage? {
        let fetchResult = PHAsset.fetchAssets(
            withLocalIdentifiers: [assetID], options: nil
        )
        guard let asset = fetchResult.firstObject else { return nil }

        return await withCheckedContinuation { continuation in
            let options = PHImageRequestOptions()
            options.deliveryMode = .highQualityFormat
            options.isNetworkAccessAllowed = true
            options.isSynchronous = false

            // Guard against double-resume: PHImageManager.requestImage can
            // invoke the handler more than once despite .highQualityFormat.
            var resumed = false
            PHImageManager.default().requestImage(
                for: asset,
                targetSize: size,
                contentMode: .aspectFit,
                options: options
            ) { image, _ in
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: image)
            }
        }
    }

    // MARK: - iCloud Availability Filter

    /// Check which asset IDs are locally available (not offloaded to iCloud).
    /// Called post-scoring on the small set of paired assets, not during the
    /// O(N) extraction loop where PHAssetResource calls would be too expensive.
    func filterOffloadedAssets(_ assetIDs: Set<String>) -> Set<String> {
        guard !assetIDs.isEmpty else { return [] }
        let fetchResult = PHAsset.fetchAssets(
            withLocalIdentifiers: Array(assetIDs), options: nil
        )
        var offloaded: Set<String> = []
        fetchResult.enumerateObjects { asset, _, _ in
            let resources = PHAssetResource.assetResources(for: asset)
            let primaryTypes: Set<PHAssetResourceType> = [.photo, .video, .fullSizePhoto, .fullSizeVideo]
            guard let primary = resources.first(where: { primaryTypes.contains($0.type) }) else { return }
            if primary.responds(to: Selector(("locallyAvailable"))),
               (primary.value(forKey: "locallyAvailable") as? Bool) == false
            {
                offloaded.insert(asset.localIdentifier)
            }
        }
        return offloaded
    }

    // MARK: - Delete

    func deleteAssets(_ assetIDs: [String]) async throws {
        let fetchResult = PHAsset.fetchAssets(
            withLocalIdentifiers: assetIDs, options: nil
        )
        guard fetchResult.count > 0 else { return }

        try await PHPhotoLibrary.shared().performChanges {
            let assets = NSMutableArray()
            fetchResult.enumerateObjects { asset, _, _ in
                assets.add(asset)
            }
            PHAssetChangeRequest.deleteAssets(assets)
        }
    }

    // MARK: - Reveal

    nonisolated func revealInPhotos(assetID: String) {
        // Use AppleScript's `spotlight` verb to navigate Photos.app to the
        // specific media item. Requires com.apple.security.automation.apple-events.
        let escaped = assetID.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let source = """
        tell application "Photos"
            activate
            spotlight media item id "\(escaped)"
        end tell
        """
        if let script = NSAppleScript(source: source) {
            var error: NSDictionary?
            script.executeAndReturnError(&error)
        }
    }
}
