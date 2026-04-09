import Foundation
import Photos

/// A scored pair of PhotoKit assets with breakdown detail.
struct PhotosScoredPair: Sendable, Equatable, Codable {
    let assetA: String  // asset ID
    let assetB: String  // asset ID
    let score: Int  // 0-100
    let breakdown: [String: Double]  // comparator name -> weighted contribution
    let detail: [String: DetailScoreTuple]  // comparator name -> (raw, weight)
}

/// Raw score + weight pair for PhotoKit scoring detail.
struct DetailScoreTuple: Sendable, Equatable, Codable {
    let raw: Double
    let weight: Double
}

/// Result of a PhotosScorer.score() call, including total comparisons evaluated.
struct PhotosScorerResult: Sendable {
    /// Pairs scoring at or above threshold (for display/results).
    let pairs: [PhotosScoredPair]
    /// ALL evaluated pairs including below-threshold (for caching).
    let allEvaluated: [PhotosScoredPair]
    let totalComparisons: Int
}

/// Orchestrates scoring of PhotoAssetMetadata pairs using the same
/// bucketing and weighting strategy as the CLI's scorer.py.
///
/// - Images: bucketed by 30-minute creation-date windows, weights filename=25 resolution=20 filesize=15 exif=40
/// - Videos: bucketed by duration (±2s via Int(dur/2)), weights filename=50 duration=30 resolution=10 filesize=10
/// - Cross-type pairs are never produced.
enum PhotosScorer {

    // MARK: - Weight tables (match CLI defaults per mode)

    private struct WeightEntry {
        let name: String
        let weight: Double
    }

    private static let imageWeights: [WeightEntry] = [
        WeightEntry(name: "filename", weight: 25),
        WeightEntry(name: "resolution", weight: 20),
        WeightEntry(name: "filesize", weight: 15),
        WeightEntry(name: "exif", weight: 40),
    ]

    private static let videoWeights: [WeightEntry] = [
        WeightEntry(name: "filename", weight: 50),
        WeightEntry(name: "duration", weight: 30),
        WeightEntry(name: "resolution", weight: 10),
        WeightEntry(name: "filesize", weight: 10),
    ]

    // MARK: - Comparator instances

    private static let filenameComparator = FilenameComparator()
    private static let durationComparator = DurationComparator()
    private static let resolutionComparator = ResolutionComparator()
    private static let fileSizeComparator = FileSizeComparator()
    private static let exifComparator = EXIFComparator()

    /// Minimum raw filename score to proceed with full scoring.
    /// Matches CLI's _MIN_FILENAME_RATIO (0.6) in scorer.py _score_pair().
    private static let minFilenameRatio: Double = 0.60

    /// Maximum creation-date difference (seconds) for cross-bucket image pairs.
    /// Same-name photos in different time windows must have EXIF dates within
    /// this threshold to be considered duplicates. Filters out filename counter
    /// resets (e.g. IMG_0001 from 2020 vs IMG_0001 from 2023).
    private static let maxCrossBucketDateDiff: TimeInterval = 120

    /// Minimum filename ratio for the secondary cross-bucket pass.
    private static let minFilenameCrossBucket: Double = 0.80

    // MARK: - Config Hash

    /// Compute a stable config hash from the effective weight table for cache keying.
    static func configHash(weights: [(String, Double)]?, isVideo: Bool) -> String {
        let effective: [WeightEntry]
        if let w = weights {
            effective = w.map { WeightEntry(name: $0.0, weight: $0.1) }
        } else {
            effective = isVideo ? videoWeights : imageWeights
        }
        var hashWeights = effective.map { ($0.name, $0.weight) }
        if !isVideo {
            hashWeights.append(("_bucket_date30m", 1))
        }
        return PhotosCacheDB.configHash(weights: hashWeights)
    }

    // MARK: - Public API

    /// Score all pairs within the given assets, returning pairs at or above `threshold`.
    ///
    /// - Parameters:
    ///   - assets: Metadata for all assets to compare.
    ///   - threshold: Minimum score (0-100) for inclusion.
    ///   - weights: Optional custom weights as `(name, weight)` tuples. When nil,
    ///              mode-appropriate defaults are used for each media type independently.
    ///   - imageWeights: Optional custom weights for images. Takes precedence over `weights` for the image pass.
    ///   - videoWeights: Optional custom weights for videos. Takes precedence over `weights` for the video pass.
    ///   - cachedPairs: Pre-cached scored pairs to include without re-scoring.
    ///   - cachedPairKeys: Pair keys corresponding to `cachedPairs`, used to skip
    ///     those pairs during scoring.
    /// Progress report from the scoring loop.
    struct Progress: Sendable {
        let current: Int
        let total: Int
        let pairsFound: Int
        let rate: Double  // comparisons per second
        let cacheHits: Int
        let cacheMisses: Int
    }

    ///   - onProgress: Called periodically with scoring progress including total and throughput.
    ///   - isCancelled: Polled periodically; returns early with partial results when true.
    static func score(
        _ assets: [PhotoAssetMetadata],
        threshold: Int,
        weights: [(String, Double)]? = nil,
        imageWeights: [(String, Double)]? = nil,
        videoWeights: [(String, Double)]? = nil,
        cachedPairs: [PhotosScoredPair]? = nil,
        cachedPairKeys: Set<PairKey>? = nil,
        onProgress: (@Sendable (Progress) -> Void)? = nil,
        isCancelled: (@Sendable () -> Bool)? = nil
    ) -> PhotosScorerResult {
        // Build per-type custom weight tables. Type-specific overrides take precedence
        // over the shared `weights` parameter so that mixed-library scans score each
        // media type with the correct comparator set.
        let customImageWeights: [WeightEntry]? = (imageWeights ?? weights).map { tuples in
            tuples.map { WeightEntry(name: $0.0, weight: $0.1) }
        }
        let customVideoWeights: [WeightEntry]? = (videoWeights ?? weights).map { tuples in
            tuples.map { WeightEntry(name: $0.0, weight: $0.1) }
        }

        // Separate by media type — no cross-type pairs
        let images = assets.filter(\.isImage)
        let videos = assets.filter(\.isVideo)

        // Pre-compute estimated total comparisons from bucket sizes (within-bucket pairs).
        let estimatedTotal = estimateComparisons(images, isVideo: false)
            + estimateComparisons(videos, isVideo: true)

        var seen = Set<PairKey>()
        var results: [PhotosScoredPair] = []
        var allEvaluated: [PhotosScoredPair] = []
        var totalComparisons = 0

        // Pre-populate from cache — cached pairs are skipped during scoring
        // and counted as already-completed comparisons for progress reporting.
        let cachedCount = cachedPairKeys?.count ?? 0
        if let cachedPairs, let cachedPairKeys {
            for key in cachedPairKeys {
                seen.insert(key)
            }
            results.append(contentsOf: cachedPairs.filter { $0.score >= threshold })
            totalComparisons = cachedCount
        }

        // Score images
        totalComparisons += scoreGroup(
            images, isVideo: false, threshold: threshold,
            customWeights: customImageWeights, seen: &seen, results: &results,
            allEvaluated: &allEvaluated, cachedCount: cachedCount,
            baseComparisons: totalComparisons, estimatedTotal: estimatedTotal + cachedCount,
            onProgress: onProgress, isCancelled: isCancelled
        )

        guard isCancelled?() != true else {
            return PhotosScorerResult(
                pairs: results, allEvaluated: allEvaluated,
                totalComparisons: totalComparisons
            )
        }

        // Score videos
        totalComparisons += scoreGroup(
            videos, isVideo: true, threshold: threshold,
            customWeights: customVideoWeights, seen: &seen, results: &results,
            allEvaluated: &allEvaluated, cachedCount: cachedCount,
            baseComparisons: totalComparisons, estimatedTotal: estimatedTotal + cachedCount,
            onProgress: onProgress, isCancelled: isCancelled
        )

        return PhotosScorerResult(
            pairs: results.sorted { $0.score > $1.score },
            allEvaluated: allEvaluated,
            totalComparisons: totalComparisons
        )
    }

    /// Estimate within-bucket pair count for progress reporting.
    private static func estimateComparisons(_ assets: [PhotoAssetMetadata], isVideo: Bool) -> Int {
        var buckets: [Int: Int] = [:]
        for asset in assets {
            let key = isVideo ? videoBucketKey(asset) : imageBucketKey(asset)
            buckets[key, default: 0] += 1
        }
        return buckets.values.reduce(0) { $0 + $1 * ($1 - 1) / 2 }
    }

    // MARK: - Internal scoring

    /// Score all pairs within `assets`, returning the number of comparisons evaluated.
    ///
    /// - Parameter baseComparisons: Running total from prior scoreGroup calls,
    ///   so progress reports reflect the cumulative count across image + video passes.
    /// - Parameter estimatedTotal: Pre-computed total within-bucket pairs for progress display.
    @discardableResult
    private static func scoreGroup(
        _ assets: [PhotoAssetMetadata],
        isVideo: Bool,
        threshold: Int,
        customWeights: [WeightEntry]?,
        seen: inout Set<PairKey>,
        results: inout [PhotosScoredPair],
        allEvaluated: inout [PhotosScoredPair],
        cachedCount: Int = 0,
        baseComparisons: Int = 0,
        estimatedTotal: Int = 0,
        onProgress: (@Sendable (Progress) -> Void)? = nil,
        isCancelled: (@Sendable () -> Bool)? = nil
    ) -> Int {
        guard assets.count >= 2 else { return 0 }
        var comparisons = 0
        // Throttle progress callbacks to ~100ms intervals
        var lastProgressTime = DispatchTime.now()
        let throttleInterval: UInt64 = 100_000_000 // 100ms in nanoseconds
        let startTime = DispatchTime.now()
        // Check cancellation every N comparisons to avoid per-comparison overhead
        let cancelCheckInterval = 100

        func reportProgress() {
            let now = DispatchTime.now()
            if now.uptimeNanoseconds - lastProgressTime.uptimeNanoseconds >= throttleInterval {
                let current = baseComparisons + comparisons
                let elapsed = Double(now.uptimeNanoseconds - startTime.uptimeNanoseconds) / 1_000_000_000
                let rate = elapsed > 0 ? Double(comparisons) / elapsed : 0
                onProgress?(Progress(
                    current: current, total: estimatedTotal,
                    pairsFound: results.count, rate: rate,
                    cacheHits: cachedCount, cacheMisses: current - cachedCount
                ))
                lastProgressTime = now
            }
        }

        // Bucket assets
        var buckets: [Int: [PhotoAssetMetadata]] = [:]
        for asset in assets {
            let key = isVideo ? videoBucketKey(asset) : imageBucketKey(asset)
            buckets[key, default: []].append(asset)
        }

        // Pass 1: Score all pairs within each bucket
        for (_, bucket) in buckets {
            for i in 0..<bucket.count {
                for j in (i + 1)..<bucket.count {
                    if comparisons % cancelCheckInterval == 0, isCancelled?() == true {
                        return comparisons
                    }
                    let key = PairKey(bucket[i].id, bucket[j].id)
                    guard !seen.contains(key) else { continue }
                    seen.insert(key)
                    comparisons += 1
                    if let pair = scorePair(
                        bucket[i], bucket[j], isVideo: isVideo,
                        customWeights: customWeights
                    ) {
                        allEvaluated.append(pair)
                        if pair.score >= threshold {
                            results.append(pair)
                        }
                    }
                    reportProgress()
                }
            }
        }

        guard isCancelled?() != true else { return comparisons }

        if isVideo {
            // Pass 2 (video): Existing bucket-pair enumeration — few buckets, cheap.
            let allBucketKeys = Array(buckets.keys.sorted())
            for i in 0..<allBucketKeys.count {
                for j in (i + 1)..<allBucketKeys.count {
                    let bucketA = buckets[allBucketKeys[i]]!
                    let bucketB = buckets[allBucketKeys[j]]!
                    for a in bucketA {
                        if isCancelled?() == true { return comparisons }
                        for b in bucketB {
                            let key = PairKey(a.id, b.id)
                            guard !seen.contains(key) else { continue }
                            let fnScore = filenameComparator.score(a.filename, b.filename)
                            guard fnScore >= minFilenameCrossBucket else { continue }
                            seen.insert(key)
                            comparisons += 1
                            if let pair = scorePair(
                                a, b, isVideo: isVideo,
                                customWeights: customWeights
                            ) {
                                allEvaluated.append(pair)
                                if pair.score >= threshold {
                                    results.append(pair)
                                }
                            }
                            reportProgress()
                        }
                    }
                }
            }
        } else {
            // Pass 2 (image): Filename-indexed cross-bucket pass.
            // Group by normalized filename, then score cross-bucket pairs
            // within each filename group. O(n) index build + O(collisions) scoring.
            var filenameIndex: [String: [PhotoAssetMetadata]] = [:]
            for asset in assets {
                let normalized = FilenameComparator.normalize(asset.filename)
                guard !normalized.isEmpty else { continue }
                filenameIndex[normalized, default: []].append(asset)
            }
            for (_, group) in filenameIndex {
                guard group.count >= 2 else { continue }
                for i in 0..<group.count {
                    if isCancelled?() == true { return comparisons }
                    let bucketI = imageBucketKey(group[i])
                    for j in (i + 1)..<group.count {
                        // Skip same-bucket pairs — already scored in Pass 1
                        guard imageBucketKey(group[j]) != bucketI else { continue }
                        // Date proximity gate: same-name photos in different time
                        // windows must have similar EXIF dates to be actual duplicates.
                        // Filters filename counter resets (IMG_0001 from different years).
                        if let dateI = group[i].creationDate, let dateJ = group[j].creationDate,
                           abs(dateI.timeIntervalSince(dateJ)) > maxCrossBucketDateDiff {
                            continue
                        }
                        let key = PairKey(group[i].id, group[j].id)
                        guard !seen.contains(key) else { continue }
                        seen.insert(key)
                        comparisons += 1
                        if let pair = scorePair(
                            group[i], group[j], isVideo: false,
                            customWeights: customWeights
                        ) {
                            allEvaluated.append(pair)
                            if pair.score >= threshold {
                                results.append(pair)
                            }
                        }
                        reportProgress()
                    }
                }
            }
        }

        // Final progress report
        let finalElapsed = Double(DispatchTime.now().uptimeNanoseconds - startTime.uptimeNanoseconds) / 1_000_000_000
        let current = baseComparisons + comparisons
        onProgress?(Progress(
            current: current, total: estimatedTotal,
            pairsFound: results.count,
            rate: finalElapsed > 0 ? Double(comparisons) / finalElapsed : 0,
            cacheHits: cachedCount, cacheMisses: current - cachedCount
        ))

        return comparisons
    }

    /// Score a single pair. Returns nil when the pair is gated (low filename similarity).
    private static func scorePair(
        _ a: PhotoAssetMetadata,
        _ b: PhotoAssetMetadata,
        isVideo: Bool,
        customWeights: [WeightEntry]? = nil
    ) -> PhotosScoredPair? {
        let weights = customWeights ?? (isVideo ? videoWeights : imageWeights)
        var breakdown: [String: Double] = [:]
        var detail: [String: DetailScoreTuple] = [:]
        var total: Double = 0

        for entry in weights {
            let rawValue = rawScore(entry.name, a, b)
            let contribution = rawValue * entry.weight
            breakdown[entry.name] = contribution
            detail[entry.name] = DetailScoreTuple(raw: rawValue, weight: entry.weight)
            total += contribution

            // Filename gate: low filename similarity means the files are unrelated,
            // regardless of how similar their metadata happens to be.
            // Matches CLI's _MIN_FILENAME_RATIO gate in scorer.py _score_pair().
            if entry.name == "filename" && entry.weight > 0 && rawValue < minFilenameRatio {
                return nil
            }
        }

        let intScore = Int(total.rounded())

        return PhotosScoredPair(
            assetA: a.id,
            assetB: b.id,
            score: intScore,
            breakdown: breakdown,
            detail: detail
        )
    }

    /// Compute raw comparator score (0.0-1.0) for a named comparator.
    private static func rawScore(
        _ name: String,
        _ a: PhotoAssetMetadata,
        _ b: PhotoAssetMetadata
    ) -> Double {
        switch name {
        case "filename":
            return filenameComparator.score(a.filename, b.filename)
        case "duration":
            return durationComparator.score(a.duration, b.duration) ?? 0.0
        case "resolution":
            return resolutionComparator.score(a.width, a.height, b.width, b.height) ?? 0.0
        case "filesize":
            return fileSizeComparator.score(a.fileSize, b.fileSize)
        case "exif":
            // width/height intentionally nil — resolution is already scored by
            // the resolution comparator. Passing pixel dimensions here causes
            // weight redistribution to award full EXIF credit for matching
            // resolution when other EXIF sub-fields (datetime, camera, GPS) are
            // absent, which is common for screenshots and stripped exports.
            let exifA = EXIFData(
                creationDate: a.creationDate,
                cameraModel: a.cameraModel,
                lensModel: a.lensModel,
                latitude: a.latitude,
                longitude: a.longitude
            )
            let exifB = EXIFData(
                creationDate: b.creationDate,
                cameraModel: b.cameraModel,
                lensModel: b.lensModel,
                latitude: b.latitude,
                longitude: b.longitude
            )
            return exifComparator.score(exifA, exifB) ?? 0.0
        default:
            return 0.0
        }
    }

    // MARK: - Bucketing

    /// Resolution tier (0-5) for nil-date fallback bucketing.
    /// Matches the CLI's `_resolution_tier()` in `scorer.py`.
    private static func resolutionTier(_ asset: PhotoAssetMetadata) -> Int {
        let pixels = asset.width * asset.height
        if pixels <= 153_600 { return 0 }   // ld  — ≤ ~360p
        if pixels <= 409_920 { return 1 }   // sd  — ≤ ~480p
        if pixels <= 921_600 { return 2 }   // hd  — ≤ ~720p
        if pixels <= 2_073_600 { return 3 } // fhd — ≤ ~1080p
        if pixels <= 3_686_400 { return 4 } // qhd — ≤ ~1440p
        return 5                            // uhd
    }

    /// Image bucket key: 30-minute creation-date window.
    /// Nil-date assets fall back to resolution tier in a separate namespace.
    private static func imageBucketKey(_ asset: PhotoAssetMetadata) -> Int {
        guard let date = asset.creationDate else {
            return Int.min + resolutionTier(asset)
        }
        return Int(date.timeIntervalSince1970 / 1800)
    }

    /// Video bucket key: duration ±2s via Int(duration / 2).
    private static func videoBucketKey(_ asset: PhotoAssetMetadata) -> Int {
        guard let duration = asset.duration else { return -1 }
        return Int(duration / 2)
    }
}

// MARK: - PairKey (sorted ID pair for deduplication)

struct PairKey: Hashable {
    let a: String
    let b: String

    init(_ id1: String, _ id2: String) {
        if id1 < id2 {
            a = id1
            b = id2
        } else {
            a = id2
            b = id1
        }
    }
}
