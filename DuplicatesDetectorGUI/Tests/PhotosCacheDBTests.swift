import Foundation
import Photos
import Testing

@testable import DuplicatesDetector

@Suite("PhotosCacheDB")
struct PhotosCacheDBTests {

    private static func makeCache() throws -> PhotosCacheDB {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("PhotosCacheDBTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return PhotosCacheDB(databaseDirectory: dir)
    }

    private static func sampleMetadata(
        id: String = "asset-1",
        modificationDate: Date = Date(timeIntervalSince1970: 1_000_000)
    ) -> PhotoAssetMetadata {
        PhotoAssetMetadata(
            id: id, filename: "IMG_0001.jpg", duration: nil,
            width: 4032, height: 3024, fileSize: 5_000_000,
            creationDate: Date(timeIntervalSince1970: 999_000),
            modificationDate: modificationDate,
            latitude: 37.7749, longitude: -122.4194,
            cameraModel: nil, lensModel: nil,
            albumNames: ["Vacation"],
            mediaType: .image
        )
    }

    @Test("database opens and creates schema")
    func schemaCreation() async throws {
        let cache = try Self.makeCache()
        let size = await cache.totalSize()
        #expect(size > 0)
    }

    @Test("put and get metadata round-trips")
    func metadataRoundTrip() async throws {
        let cache = try Self.makeCache()
        let meta = Self.sampleMetadata()
        let modDate = Date(timeIntervalSince1970: 1_000_000)
        await cache.putMetadataBatch([(assetID: "asset-1", modDate: modDate, metadata: meta)])
        let result = await cache.getMetadataBatch(assetIDs: [(id: "asset-1", modDate: modDate)])
        #expect(result.count == 1)
        #expect(result["asset-1"]?.metadata.filename == "IMG_0001.jpg")
        #expect(result["asset-1"]?.metadata.width == 4032)
    }

    @Test("stale metadata is not returned")
    func metadataStale() async throws {
        let cache = try Self.makeCache()
        let meta = Self.sampleMetadata()
        let oldDate = Date(timeIntervalSince1970: 1_000_000)
        let newDate = Date(timeIntervalSince1970: 2_000_000)
        await cache.putMetadataBatch([(assetID: "asset-1", modDate: oldDate, metadata: meta)])
        let result = await cache.getMetadataBatch(assetIDs: [(id: "asset-1", modDate: newDate)])
        #expect(result.isEmpty)
    }

    @Test("metadata stats track hits and misses")
    func metadataStats() async throws {
        let cache = try Self.makeCache()
        let meta = Self.sampleMetadata()
        let modDate = Date(timeIntervalSince1970: 1_000_000)
        await cache.putMetadataBatch([(assetID: "asset-1", modDate: modDate, metadata: meta)])
        _ = await cache.getMetadataBatch(assetIDs: [
            (id: "asset-1", modDate: modDate),
            (id: "asset-2", modDate: modDate),
        ])
        let s = await cache.stats()
        #expect(s.metadataHits == 1)
        #expect(s.metadataMisses == 1)
    }

    @Test("put and get scored pairs round-trips")
    func scoredPairsRoundTrip() async throws {
        let cache = try Self.makeCache()
        let pair = PhotosScoredPair(
            assetA: "a1", assetB: "a2", score: 85,
            breakdown: ["filename": 42.5, "exif": 34.0],
            detail: [
                "filename": DetailScoreTuple(raw: 0.85, weight: 50),
                "exif": DetailScoreTuple(raw: 0.85, weight: 40),
            ]
        )
        let modA = Date(timeIntervalSince1970: 1_000)
        let modB = Date(timeIntervalSince1970: 2_000)
        await cache.putScoredPairsBulk(
            [(pair: pair, modDateA: modA, modDateB: modB)],
            configHash: "test-hash"
        )
        let result = await cache.getCachedScoringData(
            configHash: "test-hash",
            assetModDates: ["a1": modA, "a2": modB],
            threshold: 0
        )
        #expect(result.pairs.count == 1)
        #expect(result.pairs[0].score == 85)
        #expect(result.pairs[0].assetA == "a1")
        #expect(result.keys.count == 1)
    }

    @Test("scored pairs with wrong config hash are not returned")
    func scoredPairsWrongConfig() async throws {
        let cache = try Self.makeCache()
        let pair = PhotosScoredPair(
            assetA: "a1", assetB: "a2", score: 85,
            breakdown: [:], detail: [:]
        )
        await cache.putScoredPairsBulk(
            [(pair: pair, modDateA: Date(), modDateB: Date())],
            configHash: "hash-A"
        )
        let result = await cache.getCachedScoringData(
            configHash: "hash-B",
            assetModDates: ["a1": Date(), "a2": Date()],
            threshold: 0
        )
        #expect(result.keys.isEmpty)
    }

    @Test("scored pairs stale when asset modified")
    func scoredPairsStale() async throws {
        let cache = try Self.makeCache()
        let oldDate = Date(timeIntervalSince1970: 1_000)
        let newDate = Date(timeIntervalSince1970: 2_000)
        let pair = PhotosScoredPair(
            assetA: "a1", assetB: "a2", score: 85,
            breakdown: [:], detail: [:]
        )
        await cache.putScoredPairsBulk(
            [(pair: pair, modDateA: oldDate, modDateB: oldDate)],
            configHash: "h"
        )
        let result = await cache.getCachedScoringData(
            configHash: "h",
            assetModDates: ["a1": newDate, "a2": oldDate],
            threshold: 0
        )
        #expect(result.keys.isEmpty)
    }

    @Test("scored pairs with deleted asset are excluded")
    func scoredPairsDeletedAsset() async throws {
        let cache = try Self.makeCache()
        let pair = PhotosScoredPair(
            assetA: "a1", assetB: "a2", score: 85,
            breakdown: [:], detail: [:]
        )
        let modDate = Date(timeIntervalSince1970: 1_000)
        await cache.putScoredPairsBulk(
            [(pair: pair, modDateA: modDate, modDateB: modDate)],
            configHash: "h"
        )
        let result = await cache.getCachedScoringData(
            configHash: "h",
            assetModDates: ["a1": modDate],
            threshold: 0
        )
        #expect(result.keys.isEmpty)
    }

    @Test("prune removes entries for deleted assets")
    func pruneRemovesDeleted() async throws {
        let cache = try Self.makeCache()
        let modDate = Date(timeIntervalSince1970: 1_000)
        await cache.putMetadataBatch([
            (assetID: "keep", modDate: modDate, metadata: Self.sampleMetadata(id: "keep")),
            (assetID: "delete", modDate: modDate, metadata: Self.sampleMetadata(id: "delete")),
        ])
        await cache.prune(activeAssetIDs: Set(["keep"]))
        let result = await cache.getMetadataBatch(assetIDs: [
            (id: "keep", modDate: modDate),
            (id: "delete", modDate: modDate),
        ])
        #expect(result.count == 1)
        #expect(result["keep"] != nil)
    }

    @Test("prune removes scored pairs for deleted assets")
    func pruneRemovesScoredPairs() async throws {
        let cache = try Self.makeCache()
        let modDate = Date(timeIntervalSince1970: 1_000)
        let pair = PhotosScoredPair(
            assetA: "keep", assetB: "delete", score: 80,
            breakdown: [:], detail: [:]
        )
        await cache.putScoredPairsBulk(
            [(pair: pair, modDateA: modDate, modDateB: modDate)],
            configHash: "h"
        )
        await cache.prune(activeAssetIDs: Set(["keep"]))
        let result = await cache.getCachedScoringData(
            configHash: "h",
            assetModDates: ["keep": modDate, "delete": modDate],
            threshold: 0
        )
        #expect(result.keys.isEmpty)
    }

    @Test("clear removes all data")
    func clearAll() async throws {
        let cache = try Self.makeCache()
        let modDate = Date(timeIntervalSince1970: 1_000)
        await cache.putMetadataBatch([
            (assetID: "a1", modDate: modDate, metadata: Self.sampleMetadata()),
        ])
        try await cache.clear()
        let result = await cache.getMetadataBatch(assetIDs: [(id: "a1", modDate: modDate)])
        #expect(result.isEmpty)
    }

    @Test("resetStats clears counters")
    func resetStats() async throws {
        let cache = try Self.makeCache()
        let modDate = Date(timeIntervalSince1970: 1_000)
        _ = await cache.getMetadataBatch(assetIDs: [(id: "a1", modDate: modDate)])
        await cache.resetStats()
        let s = await cache.stats()
        #expect(s.metadataHits == 0)
        #expect(s.metadataMisses == 0)
    }

    @Test("getAllCachedMetadata returns full cache contents")
    func getAllCachedMetadata() async throws {
        let cache = try Self.makeCache()
        let modDate = Date(timeIntervalSince1970: 1_000)
        await cache.putMetadataBatch([
            (assetID: "a1", modDate: modDate, metadata: Self.sampleMetadata(id: "a1")),
            (assetID: "a2", modDate: modDate, metadata: Self.sampleMetadata(id: "a2")),
        ])
        let all = await cache.getAllCachedMetadata()
        #expect(all.count == 2)
        #expect(all["a1"]?.metadata.id == "a1")
        #expect(all["a2"]?.metadata.id == "a2")
    }

    @Test("configHash is deterministic and normalized")
    func configHash() {
        let hash1 = PhotosCacheDB.configHash(weights: [("filename", 25), ("exif", 40), ("filesize", 15), ("resolution", 20)])
        let hash2 = PhotosCacheDB.configHash(weights: [("resolution", 20), ("filename", 25), ("filesize", 15), ("exif", 40)])
        #expect(hash1 == hash2)
        let hash3 = PhotosCacheDB.configHash(weights: [("fileSize", 15), ("filename", 25), ("exif", 40), ("resolution", 20)])
        #expect(hash1 == hash3)
    }
}
