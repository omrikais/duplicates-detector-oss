import AppKit
import Photos

/// Error types for PhotoKit bridge operations.
enum PhotoKitError: Error, LocalizedError {
    case authorizationDenied
    case authorizationRestricted
    case fetchFailed(String)

    var errorDescription: String? {
        switch self {
        case .authorizationDenied:
            "Photos Library access was denied. Grant access in System Settings > Privacy & Security > Photos."
        case .authorizationRestricted:
            "Photos Library access is restricted by a device management profile."
        case .fetchFailed(let reason):
            "Failed to fetch assets from Photos Library: \(reason)"
        }
    }
}

/// Protocol for PhotoKit operations, enabling mock injection for tests.
protocol PhotoKitBridgeProtocol: Actor, Sendable {

    /// Request read-write authorization for the Photos Library.
    func requestAuthorization() async -> PHAuthorizationStatus

    /// Scan the Photos Library for duplicate pairs.
    ///
    /// - Parameters:
    ///   - scope: Which portion of the library to scan.
    ///   - threshold: Minimum score (0-100) for a pair to be reported.
    ///   - weights: Optional custom comparator weights as `(name, weight)` tuples.
    ///              When nil, mode-appropriate defaults are used.
    ///   - onProgress: Callback for progress events during the scan.
    /// - Returns: Scored pairs at or above the threshold.
    func scanLibrary(
        scope: PhotosScope, threshold: Int, weights: [(String, Double)]?,
        onProgress: @Sendable @escaping (ProgressEvent) -> Void
    ) async throws -> [PhotosScoredPair]

    /// Fetch a thumbnail image for a Photos asset.
    ///
    /// - Parameters:
    ///   - assetID: The `PHAsset.localIdentifier`.
    ///   - size: Desired thumbnail size in points.
    /// - Returns: The thumbnail as an `NSImage`, or nil if unavailable.
    func fetchThumbnail(assetID: String, size: CGSize) async -> NSImage?

    /// Delete assets from the Photos Library via a change request.
    ///
    /// - Parameter assetIDs: Array of `PHAsset.localIdentifier` values.
    func deleteAssets(_ assetIDs: [String]) async throws

    /// Open the Photos app to reveal an asset. Nonisolated for synchronous UI calls.
    nonisolated func revealInPhotos(assetID: String)
}
