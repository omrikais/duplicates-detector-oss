import Photos

/// Identifies the source for a duplicate scan.
///
/// Must be Codable because ScanConfig (aka SessionConfig) is Codable
/// for session persistence. The associated PhotosScope value is simple
/// enough for auto-synthesized Codable.
enum ScanSource: Sendable, Equatable, Codable {
    case directory
    case photosLibrary(scope: PhotosScope)
}

/// Scope for a Photos Library scan.
enum PhotosScope: Sendable, Equatable, Codable {
    case fullLibrary
}

// MARK: - Photos Asset URI Helpers

extension String {
    /// The URI prefix for Photos Library synthetic paths.
    private static let photosAssetPrefix = "photos://asset/"

    /// True if this path is a Photos Library synthetic URI (e.g. `photos://asset/ABC-123`).
    var isPhotosAssetURI: Bool { hasPrefix(Self.photosAssetPrefix) }

    /// Extract the PHAsset localIdentifier from a `photos://asset/` URI.
    /// Strips any `#filename` fragment appended for display purposes.
    /// Returns `nil` for non-Photos paths.
    var photosAssetID: String? {
        guard isPhotosAssetURI else { return nil }
        let raw = String(dropFirst(Self.photosAssetPrefix.count))
        // Strip fragment (original filename) if present
        if let hashIndex = raw.firstIndex(of: "#") {
            return String(raw[raw.startIndex..<hashIndex])
        }
        return raw
    }

    /// Human-readable display name for a file path.
    ///
    /// For Photos Library assets, returns the embedded original filename from the
    /// URI fragment (e.g. `IMG_1234.JPG`), falling back to a truncated UUID.
    /// For filesystem paths, returns the last path component (filename).
    var displayFileName: String {
        guard isPhotosAssetURI else { return fileName }
        // Extract original filename from fragment
        let raw = String(dropFirst(Self.photosAssetPrefix.count))
        if let hashIndex = raw.firstIndex(of: "#") {
            let name = String(raw[raw.index(after: hashIndex)...])
            if !name.isEmpty { return name }
        }
        // Fallback for legacy URIs without fragment
        guard let assetID = photosAssetID else { return fileName }
        let uuid = assetID.prefix(while: { $0 != "/" })
        if uuid.count > 8 {
            return "Photo \(uuid.prefix(8))\u{2026}"
        }
        return "Photo \(uuid)"
    }
}
