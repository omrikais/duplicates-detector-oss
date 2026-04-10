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

    /// Parse a Photos URI into (assetID, fragment). Returns nil for non-Photos paths.
    private var photosURIComponents: (assetID: String, fragment: String?)? {
        guard isPhotosAssetURI else { return nil }
        let raw = String(dropFirst(Self.photosAssetPrefix.count))
        if let hashIndex = raw.firstIndex(of: "#") {
            let id = String(raw[raw.startIndex..<hashIndex])
            let frag = String(raw[raw.index(after: hashIndex)...])
            return (id, frag.isEmpty ? nil : frag)
        }
        return (raw, nil)
    }

    /// Extract the PHAsset localIdentifier from a `photos://asset/` URI.
    /// Strips any `#filename` fragment appended for display purposes.
    /// Returns `nil` for non-Photos paths.
    var photosAssetID: String? { photosURIComponents?.assetID }

    /// Human-readable display name for a file path.
    ///
    /// For Photos Library assets, returns the embedded original filename from the
    /// URI fragment (e.g. `IMG_1234.JPG`), falling back to a truncated UUID.
    /// For filesystem paths, returns the last path component (filename).
    var displayFileName: String {
        guard let components = photosURIComponents else { return fileName }
        if let name = components.fragment { return name }
        let uuid = components.assetID.prefix(while: { $0 != "/" })
        return uuid.count > 8 ? "Photo \(uuid.prefix(8))\u{2026}" : "Photo \(uuid)"
    }
}
