import AppKit
import Photos
import Testing
@testable import DuplicatesDetector

// MARK: - MockPhotoKitBridge

actor MockPhotoKitBridge: PhotoKitBridgeProtocol {
    var authorizationStatus: PHAuthorizationStatus = .authorized
    var mockAssets: [PhotoAssetMetadata] = []
    var deleteCallCount = 0
    var lastDeletedIDs: [String] = []

    func requestAuthorization() async -> PHAuthorizationStatus { authorizationStatus }

    func scanLibrary(
        scope: PhotosScope, threshold: Int, weights: [(String, Double)]?,
        onProgress: @Sendable @escaping (ProgressEvent) -> Void
    ) async throws -> [PhotosScoredPair] {
        PhotosScorer.score(mockAssets, threshold: threshold, weights: weights).pairs
    }

    func fetchThumbnail(assetID: String, size: CGSize) async -> NSImage? { nil }

    func deleteAssets(_ assetIDs: [String]) async throws {
        deleteCallCount += 1
        lastDeletedIDs = assetIDs
    }

    nonisolated func revealInPhotos(assetID: String) {}
}

// MARK: - Tests

@Suite("PhotoKitBridge")
struct PhotoKitBridgeTests {

    static func makeAsset(
        id: String = UUID().uuidString,
        filename: String = "IMG_0001.jpg",
        duration: Double? = nil,
        width: Int = 4032, height: Int = 3024,
        fileSize: Int64 = 3_200_000,
        creationDate: Date? = nil,
        cameraModel: String? = nil,
        mediaType: PHAssetMediaType = .image
    ) -> PhotoAssetMetadata {
        PhotoAssetMetadata(
            id: id, filename: filename, duration: duration,
            width: width, height: height, fileSize: fileSize,
            creationDate: creationDate, modificationDate: nil,
            latitude: nil, longitude: nil,
            cameraModel: cameraModel, lensModel: nil,
            albumNames: [], mediaType: mediaType
        )
    }

    @Test("authorized status proceeds with scan and finds duplicate pair")
    func authorizedScanFindsDuplicates() async throws {
        let bridge = MockPhotoKitBridge()
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let assetA = Self.makeAsset(id: "A", filename: "vacation.jpg", creationDate: date, cameraModel: "iPhone 15")
        let assetB = Self.makeAsset(id: "B", filename: "vacation.jpg", creationDate: date, cameraModel: "iPhone 15")
        await bridge.setMockAssets([assetA, assetB])

        let status = await bridge.requestAuthorization()
        #expect(status == .authorized)

        let pairs = try await bridge.scanLibrary(
            scope: .fullLibrary, threshold: 50, weights: nil
        ) { _ in }

        #expect(pairs.count == 1)
        #expect(pairs[0].assetA == "A" || pairs[0].assetB == "A")
        #expect(pairs[0].score >= 90)
    }

    @Test("denied status returns .denied from requestAuthorization")
    func deniedStatus() async {
        let bridge = MockPhotoKitBridge()
        await bridge.setAuthorizationStatus(.denied)

        let status = await bridge.requestAuthorization()
        #expect(status == .denied)
    }

    @Test("delete records asset IDs and increments call count")
    func deleteRecordsAssetIDs() async throws {
        let bridge = MockPhotoKitBridge()
        let ids = ["asset-1", "asset-2", "asset-3"]

        try await bridge.deleteAssets(ids)

        let count = await bridge.deleteCallCount
        let lastIDs = await bridge.lastDeletedIDs

        #expect(count == 1)
        #expect(lastIDs == ids)
    }

    @Test("fetchThumbnail returns nil from mock")
    func fetchThumbnailReturnsNil() async {
        let bridge = MockPhotoKitBridge()
        let image = await bridge.fetchThumbnail(assetID: "any-id", size: CGSize(width: 100, height: 100))
        #expect(image == nil)
    }

    @Test("revealInPhotos is callable without error")
    func revealInPhotosCallable() {
        let bridge = MockPhotoKitBridge()
        bridge.revealInPhotos(assetID: "some-asset-id")
        // No crash = success (nonisolated, no return value)
    }

    @Test("scan with custom weights passes through to scorer")
    func scanWithCustomWeights() async throws {
        let bridge = MockPhotoKitBridge()
        let assetA = Self.makeAsset(id: "A", filename: "photo.jpg")
        let assetB = Self.makeAsset(id: "B", filename: "photo.jpg")
        await bridge.setMockAssets([assetA, assetB])

        // Filename weight = 100, everything else 0 — should still score high
        let pairs = try await bridge.scanLibrary(
            scope: .fullLibrary, threshold: 0,
            weights: [("filename", 100)]
        ) { _ in }

        #expect(pairs.count == 1)
        #expect(pairs[0].score >= 95)
    }

    @Test("PhotoKitError has localized descriptions")
    func errorDescriptions() {
        let denied = PhotoKitError.authorizationDenied
        #expect(denied.localizedDescription.contains("denied"))

        let restricted = PhotoKitError.authorizationRestricted
        #expect(restricted.localizedDescription.contains("restricted"))

        let fetchFailed = PhotoKitError.fetchFailed("test reason")
        #expect(fetchFailed.localizedDescription.contains("test reason"))
    }
}

// MARK: - Mock Helpers

extension MockPhotoKitBridge {
    func setMockAssets(_ assets: [PhotoAssetMetadata]) {
        mockAssets = assets
    }

    func setAuthorizationStatus(_ status: PHAuthorizationStatus) {
        authorizationStatus = status
    }
}
