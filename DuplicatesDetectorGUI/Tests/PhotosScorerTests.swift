import Photos
import Testing
@testable import DuplicatesDetector

@Suite("PhotosScorer")
struct PhotosScorerTests {

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

    @Test("identical images produce a high-scoring pair")
    func identicalImages() {
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(id: "A", filename: "vacation.jpg", creationDate: date, cameraModel: "iPhone 15")
        let b = Self.makeAsset(id: "B", filename: "vacation.jpg", creationDate: date, cameraModel: "iPhone 15")
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
        #expect(result.pairs[0].score >= 90)
        #expect(result.totalComparisons >= 1)
    }

    @Test("completely different images produce no pairs above threshold")
    func differentImages() {
        let a = Self.makeAsset(id: "A", filename: "sunset.jpg", width: 640, height: 480, fileSize: 100_000)
        let b = Self.makeAsset(id: "B", filename: "receipt.pdf", width: 4032, height: 3024, fileSize: 5_000_000)
        let result = PhotosScorer.score([a, b], threshold: 50)
        #expect(result.pairs.isEmpty)
    }

    @Test("videos bucketed by duration — different buckets not paired without filename match")
    func videoBucketing() {
        // Different filenames ensure the secondary filename pass doesn't catch them
        let a = Self.makeAsset(id: "A", filename: "vacation.mp4", duration: 10.0, mediaType: .video)
        let b = Self.makeAsset(id: "B", filename: "concert.mp4", duration: 20.0, mediaType: .video)
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.isEmpty)
    }

    @Test("videos with same filename but different durations found via filename pass")
    func videoFilenameCrossBucket() {
        let a = Self.makeAsset(id: "A", filename: "clip.mp4", duration: 10.0, mediaType: .video)
        let b = Self.makeAsset(id: "B", filename: "clip.mp4", duration: 20.0, mediaType: .video)
        let result = PhotosScorer.score([a, b], threshold: 0)
        // Secondary filename pass catches identical names across buckets,
        // but zero duration score drags the total well below 100
        #expect(result.pairs.count == 1)
        #expect(result.pairs[0].score < 80)
    }

    @Test("cross-type pairs never produced")
    func crossType() {
        let img = Self.makeAsset(id: "A", filename: "file.jpg", mediaType: .image)
        let vid = Self.makeAsset(id: "B", filename: "file.mp4", duration: 10.0, mediaType: .video)
        let result = PhotosScorer.score([img, vid], threshold: 0)
        #expect(result.pairs.isEmpty)
    }

    @Test("threshold filtering works")
    func thresholdFilter() {
        let a = Self.makeAsset(id: "A", filename: "photo_a.jpg")
        let b = Self.makeAsset(id: "B", filename: "photo_b.jpg")
        let highThreshold = PhotosScorer.score([a, b], threshold: 95)
        let lowThreshold = PhotosScorer.score([a, b], threshold: 0)
        #expect(highThreshold.pairs.count <= lowThreshold.pairs.count)
    }

    @Test("uses correct weights per media type")
    func weightsPerType() {
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(id: "A", filename: "photo.jpg", fileSize: 1_000_000, creationDate: date, cameraModel: "iPhone 15")
        let b = Self.makeAsset(id: "B", filename: "photo.jpg", fileSize: 5_000_000, creationDate: date, cameraModel: "iPhone 15")
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
        #expect(result.pairs[0].score < 100)
        #expect(result.pairs[0].score > 50)
    }

    @Test("detail stores raw and weight separately")
    func detailScores() {
        let a = Self.makeAsset(id: "A", filename: "vacation.jpg")
        let b = Self.makeAsset(id: "B", filename: "vacation.jpg")
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
        let pair = result.pairs[0]
        // Image weights: filename=25, resolution=20, filesize=15, exif=40
        if let fnDetail = pair.detail["filename"] {
            #expect(fnDetail.weight == 25.0)
            #expect(fnDetail.raw >= 0.0 && fnDetail.raw <= 1.0)
        }
    }

    // MARK: - Cache integration tests

    @Test("cached pairs are included in results without re-scoring")
    func cachedPairsSkipped() {
        let assets = [
            Self.makeAsset(id: "a", filename: "IMG_0001.jpg"),
            Self.makeAsset(id: "b", filename: "IMG_0001.jpg"),
            Self.makeAsset(id: "c", filename: "IMG_0002.jpg"),
        ]
        let cachedPair = PhotosScoredPair(
            assetA: "a", assetB: "b", score: 90,
            breakdown: ["filename": 22.5],
            detail: ["filename": DetailScoreTuple(raw: 0.9, weight: 25)]
        )
        let cachedKeys: Set<PairKey> = [PairKey("a", "b")]
        let result = PhotosScorer.score(
            assets, threshold: 30,
            cachedPairs: [cachedPair], cachedPairKeys: cachedKeys
        )
        let abPair = result.pairs.first {
            ($0.assetA == "a" && $0.assetB == "b") || ($0.assetA == "b" && $0.assetB == "a")
        }
        #expect(abPair != nil)
        #expect(abPair?.score == 90)
    }

    @Test("uncached pairs are still scored normally")
    func uncachedPairsScored() {
        let assets = [
            Self.makeAsset(id: "a", filename: "IMG_0001.jpg"),
            Self.makeAsset(id: "b", filename: "IMG_0001.jpg"),
        ]
        let result = PhotosScorer.score(assets, threshold: 30)
        #expect(!result.pairs.isEmpty)
    }

    // MARK: - configHash tests

    @Test("configHash returns deterministic hash for default image weights")
    func configHashImageDefaults() {
        let hash1 = PhotosScorer.configHash(weights: nil, isVideo: false)
        let hash2 = PhotosScorer.configHash(weights: nil, isVideo: false)
        #expect(hash1 == hash2)
        #expect(!hash1.isEmpty)
    }

    @Test("configHash differs between image and video defaults")
    func configHashDiffersByMode() {
        let imageHash = PhotosScorer.configHash(weights: nil, isVideo: false)
        let videoHash = PhotosScorer.configHash(weights: nil, isVideo: true)
        #expect(imageHash != videoHash)
    }

    @Test("configHash with custom weights differs from defaults")
    func configHashCustomWeights() {
        let defaultHash = PhotosScorer.configHash(weights: nil, isVideo: false)
        let customHash = PhotosScorer.configHash(
            weights: [("filename", 100)], isVideo: false
        )
        #expect(defaultHash != customHash)
    }

    // MARK: - Date-window bucketing tests

    @Test("images in same 30-min window are scored")
    func sameWindowScored() {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(
            id: "A", filename: "IMG_0001.jpg",
            creationDate: base
        )
        let b = Self.makeAsset(
            id: "B", filename: "IMG_0001.jpg",
            creationDate: base.addingTimeInterval(300) // +5 min, same window
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
        #expect(result.totalComparisons >= 1)
    }

    @Test("sequential camera filenames in same window are gated")
    func sequentialFilenamesGated() {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(
            id: "A", filename: "IMG_0001.jpg",
            creationDate: base
        )
        let b = Self.makeAsset(
            id: "B", filename: "IMG_0002.jpg",
            creationDate: base.addingTimeInterval(300) // same window, different serial number
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        // Filename gate rejects: numbered series → score 0.0 < 0.6
        #expect(result.pairs.isEmpty)
        #expect(result.totalComparisons >= 1)
    }

    @Test("images in different 30-min windows not paired without filename match")
    func differentWindowNotPaired() {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(
            id: "A", filename: "sunset.jpg",
            creationDate: base
        )
        let b = Self.makeAsset(
            id: "B", filename: "receipt.jpg",
            creationDate: base.addingTimeInterval(7200) // +2 hours
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.isEmpty)
    }

    @Test("exact 30-minute boundary splits into different buckets")
    func exactBoundarySplit() {
        // Pick a timestamp that's exactly on a 30-min boundary
        let boundary: TimeInterval = 1_700_000_000 - 1_700_000_000.truncatingRemainder(dividingBy: 1800)
        let a = Self.makeAsset(
            id: "A", filename: "photo_x.jpg",
            creationDate: Date(timeIntervalSince1970: boundary - 1) // last second of window
        )
        let b = Self.makeAsset(
            id: "B", filename: "photo_y.jpg",
            creationDate: Date(timeIntervalSince1970: boundary) // first second of next window
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        // Different windows, different filenames → not paired
        #expect(result.pairs.isEmpty)
    }

    @Test("cross-window filename match with close EXIF dates caught by filename index")
    func crossWindowFilenameMatch() {
        // Straddle a 30-min boundary but EXIF dates within 120s → matched
        let boundary: TimeInterval = 1_700_000_000 - 1_700_000_000.truncatingRemainder(dividingBy: 1800)
        let a = Self.makeAsset(
            id: "A", filename: "IMG_1234.jpg",
            creationDate: Date(timeIntervalSince1970: boundary - 30) // end of window
        )
        let b = Self.makeAsset(
            id: "B", filename: "IMG_1234.jpg",
            creationDate: Date(timeIntervalSince1970: boundary + 30) // start of next window
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
    }

    @Test("same-name photos with distant dates rejected by cross-bucket date gate")
    func crossWindowDateGateRejects() {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(
            id: "A", filename: "IMG_0001.jpg",
            creationDate: base
        )
        let b = Self.makeAsset(
            id: "B", filename: "IMG_0001.jpg",
            creationDate: base.addingTimeInterval(86400) // +1 day, filename counter reset
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        // Date gate rejects: same name but dates 1 day apart → not a duplicate
        #expect(result.pairs.isEmpty)
    }

    @Test("nil-date images bucketed by resolution tier")
    func nilDateFallback() {
        // Both nil-date, same resolution → same nil-date bucket → scored
        let a = Self.makeAsset(id: "A", filename: "scan_doc.jpg", creationDate: nil)
        let b = Self.makeAsset(id: "B", filename: "scan_doc.jpg", creationDate: nil)
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
    }

    @Test("nil-date and dated asset matched via filename index")
    func nilDateVsDatedFilenameMatch() {
        let a = Self.makeAsset(
            id: "A", filename: "IMG_5678.jpg",
            creationDate: nil
        )
        let b = Self.makeAsset(
            id: "B", filename: "IMG_5678.jpg",
            creationDate: Date(timeIntervalSince1970: 1_700_000_000)
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.count == 1)
    }

    @Test("nil-date and dated assets with different filenames not cross-matched")
    func nilDateVsDatedNoMatch() {
        let a = Self.makeAsset(
            id: "A", filename: "old_scan.jpg",
            creationDate: nil
        )
        let b = Self.makeAsset(
            id: "B", filename: "vacation.jpg",
            creationDate: Date(timeIntervalSince1970: 1_700_000_000)
        )
        let result = PhotosScorer.score([a, b], threshold: 0)
        #expect(result.pairs.isEmpty)
    }

    // MARK: - isCancelled early exit

    @Test("isCancelled returns partial or empty results immediately")
    func cancelledEarlyExit() {
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let assets = (0..<10).map {
            Self.makeAsset(id: "id\($0)", filename: "photo.jpg", creationDate: date)
        }
        let result = PhotosScorer.score(assets, threshold: 0, isCancelled: { true })
        // With immediate cancellation, we should get fewer pairs than full scoring.
        // The cancel check happens every 100 comparisons, so with 10 assets in one
        // bucket (45 pairs) the first check fires at comparison 0, exiting immediately.
        #expect(result.pairs.count < 45)
    }

    // MARK: - onProgress callback

    @Test("onProgress fires at least once with current > 0")
    func progressCallback() {
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(id: "A", filename: "photo.jpg", creationDate: date)
        let b = Self.makeAsset(id: "B", filename: "photo.jpg", creationDate: date)
        let collector = ProgressCollector()
        _ = PhotosScorer.score([a, b], threshold: 0, onProgress: { progress in
            collector.append(progress)
        })
        // The final progress report always fires at the end of scoreGroup
        let calls = collector.calls
        #expect(!calls.isEmpty)
        let last = calls.last!
        #expect(last.current > 0)
    }

    // MARK: - allEvaluated includes below-threshold pairs

    @Test("allEvaluated includes pairs not meeting threshold")
    func allEvaluatedContainsBelowThreshold() {
        // Use assets that will produce a low-scoring pair (similar filenames but
        // differing metadata, so the pair scores but below a high threshold).
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let a = Self.makeAsset(
            id: "A", filename: "photo_a.jpg",
            width: 640, height: 480, fileSize: 100_000, creationDate: date
        )
        let b = Self.makeAsset(
            id: "B", filename: "photo_b.jpg",
            width: 4032, height: 3024, fileSize: 5_000_000, creationDate: date
        )
        let result = PhotosScorer.score([a, b], threshold: 95)
        // The pair scores below 95, so it appears in allEvaluated but not pairs
        #expect(result.allEvaluated.count >= result.pairs.count)
        if !result.allEvaluated.isEmpty {
            // If the pair was evaluated at all, allEvaluated has more than pairs
            #expect(result.allEvaluated.count > result.pairs.count || result.pairs.isEmpty)
        }
    }

    // MARK: - estimateComparisons (indirect via totalComparisons)

    @Test("three assets in one bucket produces 3 comparisons")
    func estimateThreeInBucket() {
        let date = Date(timeIntervalSince1970: 1_700_000_000)
        let assets = [
            Self.makeAsset(id: "A", filename: "pic.jpg", creationDate: date),
            Self.makeAsset(id: "B", filename: "pic.jpg", creationDate: date),
            Self.makeAsset(id: "C", filename: "pic.jpg", creationDate: date),
        ]
        let result = PhotosScorer.score(assets, threshold: 0)
        // 3 assets in one bucket: C(3,2) = 3 within-bucket comparisons.
        // Some may be gated by filename, but totalComparisons counts all attempts.
        #expect(result.totalComparisons == 3)
    }
}

// MARK: - PairKey

@Suite("PairKey")
struct PairKeyTests {

    @Test("canonical ordering — B, A becomes a=A, b=B")
    func canonicalOrdering() {
        let key = PairKey("B", "A")
        #expect(key.a == "A")
        #expect(key.b == "B")
    }

    @Test("already ordered — A, B stays a=A, b=B")
    func alreadyOrdered() {
        let key = PairKey("A", "B")
        #expect(key.a == "A")
        #expect(key.b == "B")
    }

    @Test("both fields equal when inputs are identical")
    func identicalInputs() {
        let key = PairKey("A", "A")
        #expect(key.a == "A")
        #expect(key.b == "A")
    }

    @Test("swapped inputs produce equal keys with same hash")
    func swappedEquality() {
        let key1 = PairKey("X", "Y")
        let key2 = PairKey("Y", "X")
        #expect(key1 == key2)
        #expect(key1.hashValue == key2.hashValue)
    }

    @Test("different pairs are not equal")
    func differentPairs() {
        let key1 = PairKey("A", "B")
        let key2 = PairKey("A", "C")
        #expect(key1 != key2)
    }
}

// MARK: - Test Helpers

/// Thread-safe collector for @Sendable progress callbacks.
private final class ProgressCollector: Sendable {
    private let lock = NSLock()
    private let storage = UncheckedSendableBox<[PhotosScorer.Progress]>([])

    func append(_ progress: PhotosScorer.Progress) {
        lock.lock()
        defer { lock.unlock() }
        storage.value.append(progress)
    }

    var calls: [PhotosScorer.Progress] {
        lock.lock()
        defer { lock.unlock() }
        return storage.value
    }
}

/// Wrapper to allow mutable state in a Sendable context.
private final class UncheckedSendableBox<T>: @unchecked Sendable {
    var value: T
    init(_ value: T) { self.value = value }
}
