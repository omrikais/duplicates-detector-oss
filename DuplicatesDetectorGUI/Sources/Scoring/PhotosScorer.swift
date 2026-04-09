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
    /// Newly evaluated pairs (for caching). Does not include pre-cached pairs.
    let allEvaluated: [PhotosScoredPair]
    let totalComparisons: Int
}

/// Orchestrates scoring of PhotoAssetMetadata pairs using the same
/// bucketing and weighting strategy as the CLI's scorer.py.
///
/// - Images: bucketed by 30-minute creation-date windows, weights from WeightDefaults.imageDefault
/// - Videos: bucketed by duration (±2s via Int(dur/2)), weights from WeightDefaults.videoDefault
/// - Cross-type pairs are never produced.
enum PhotosScorer {

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

    // MARK: - Scoring State

    /// Mutable accumulator threaded through scoring passes, replacing the
    /// previous 8-parameter sprawl in scoreGroup().
    private struct ScoringState {
        var seen: Set<PairKey>
        var results: [PhotosScoredPair]
        var allEvaluated: [PhotosScoredPair]
        var totalComparisons: Int
        let cachedCount: Int
        let estimatedTotal: Int
        let threshold: Int
        let onProgress: (@Sendable (Progress) -> Void)?
        let isCancelled: (@Sendable () -> Bool)?
    }

    // MARK: - Config Hash

    /// Compute a stable config hash from the effective weight table for cache keying.
    static func configHash(weights: [(String, Double)]?, isVideo: Bool) -> String {
        var hashWeights = weights ?? defaultWeights(isVideo: isVideo)
        if !isVideo {
            hashWeights.append(("_bucket_date30m", 1))
        }
        return PhotosCacheDB.configHash(weights: hashWeights)
    }

    /// Default weight tuples for the given mode, derived from WeightDefaults.
    private static func defaultWeights(isVideo: Bool) -> [(String, Double)] {
        let dict = isVideo ? WeightDefaults.videoDefault : WeightDefaults.imageDefault
        return dict.map { ($0.key, $0.value) }
    }

    // MARK: - Public API

    /// Progress report from the scoring loop.
    struct Progress: Sendable {
        let current: Int
        let total: Int
        let pairsFound: Int
        let rate: Double  // comparisons per second
        let cacheHits: Int
        let cacheMisses: Int
    }

    /// Score all pairs within the given assets, returning pairs at or above `threshold`.
    ///
    /// - Parameters:
    ///   - assets: Metadata for all assets to compare.
    ///   - threshold: Minimum score (0-100) for inclusion.
    ///   - weights: Optional custom weights as `(name, weight)` tuples. When nil,
    ///              mode-appropriate defaults are used for each media type independently.
    ///   - imageWeights: Optional custom weights for images. Takes precedence over `weights`.
    ///   - videoWeights: Optional custom weights for videos. Takes precedence over `weights`.
    ///   - cachedPairs: Pre-cached scored pairs to include without re-scoring.
    ///   - cachedPairKeys: Pair keys corresponding to `cachedPairs`, used to skip
    ///     those pairs during scoring.
    ///   - onProgress: Called periodically with scoring progress.
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
        let customImageWeights = imageWeights ?? weights
        let customVideoWeights = videoWeights ?? weights

        let images = assets.filter(\.isImage)
        let videos = assets.filter(\.isVideo)

        let estimatedTotal = estimateComparisons(images, isVideo: false)
            + estimateComparisons(videos, isVideo: true)

        let cachedCount = cachedPairKeys?.count ?? 0
        var state = ScoringState(
            seen: Set(cachedPairKeys ?? []),
            results: cachedPairs?.filter { $0.score >= threshold } ?? [],
            allEvaluated: [],
            totalComparisons: cachedCount,
            cachedCount: cachedCount,
            estimatedTotal: estimatedTotal + cachedCount,
            threshold: threshold,
            onProgress: onProgress,
            isCancelled: isCancelled
        )

        scoreGroup(images, isVideo: false, customWeights: customImageWeights, state: &state)

        guard isCancelled?() != true else {
            return PhotosScorerResult(
                pairs: state.results, allEvaluated: state.allEvaluated,
                totalComparisons: state.totalComparisons
            )
        }

        scoreGroup(videos, isVideo: true, customWeights: customVideoWeights, state: &state)

        return PhotosScorerResult(
            pairs: state.results.sorted { $0.score > $1.score },
            allEvaluated: state.allEvaluated,
            totalComparisons: state.totalComparisons
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

    private static func scoreGroup(
        _ assets: [PhotoAssetMetadata],
        isVideo: Bool,
        customWeights: [(String, Double)]?,
        state: inout ScoringState
    ) {
        guard assets.count >= 2 else { return }
        let baseComparisons = state.totalComparisons
        var comparisons = 0
        var lastProgressTime = DispatchTime.now()
        let throttleInterval: UInt64 = 100_000_000  // 100ms
        let startTime = DispatchTime.now()
        let cancelCheckInterval = 100

        let weights = customWeights ?? defaultWeights(isVideo: isVideo)

        // Precompute normalized filenames to avoid redundant regex work per pair
        let normalizedFilenames = Dictionary(
            uniqueKeysWithValues: assets.map { ($0.id, FilenameComparator.normalize($0.filename)) }
        )

        func reportProgress() {
            let now = DispatchTime.now()
            if now.uptimeNanoseconds - lastProgressTime.uptimeNanoseconds >= throttleInterval {
                let current = baseComparisons + comparisons
                let elapsed = Double(now.uptimeNanoseconds - startTime.uptimeNanoseconds) / 1_000_000_000
                let rate = elapsed > 0 ? Double(comparisons) / elapsed : 0
                state.onProgress?(Progress(
                    current: current, total: state.estimatedTotal,
                    pairsFound: state.results.count, rate: rate,
                    cacheHits: state.cachedCount, cacheMisses: current - state.cachedCount
                ))
                lastProgressTime = now
            }
        }

        /// Score a pair, collect into results/allEvaluated, report progress.
        func record(_ a: PhotoAssetMetadata, _ b: PhotoAssetMetadata) {
            comparisons += 1
            if let pair = scorePair(
                a, b, isVideo: isVideo, weights: weights,
                normalizedFilenames: normalizedFilenames
            ) {
                state.allEvaluated.append(pair)
                if pair.score >= state.threshold {
                    state.results.append(pair)
                }
            }
            reportProgress()
        }

        /// Check seen set, insert, and record.
        func evaluate(_ a: PhotoAssetMetadata, _ b: PhotoAssetMetadata) {
            let key = PairKey(a.id, b.id)
            guard !state.seen.contains(key) else { return }
            state.seen.insert(key)
            record(a, b)
        }

        var buckets: [Int: [PhotoAssetMetadata]] = [:]
        for asset in assets {
            let key = isVideo ? videoBucketKey(asset) : imageBucketKey(asset)
            buckets[key, default: []].append(asset)
        }

        // Pass 1: within-bucket pairs
        for (_, bucket) in buckets {
            for i in 0..<bucket.count {
                for j in (i + 1)..<bucket.count {
                    if comparisons % cancelCheckInterval == 0, state.isCancelled?() == true {
                        state.totalComparisons = baseComparisons + comparisons
                        return
                    }
                    evaluate(bucket[i], bucket[j])
                }
            }
        }

        guard state.isCancelled?() != true else {
            state.totalComparisons = baseComparisons + comparisons
            return
        }

        if isVideo {
            // Pass 2 (video): cross-bucket pairs with filename gate ≥0.80
            let allBucketKeys = Array(buckets.keys.sorted())
            for i in 0..<allBucketKeys.count {
                for j in (i + 1)..<allBucketKeys.count {
                    let bucketA = buckets[allBucketKeys[i]]!
                    let bucketB = buckets[allBucketKeys[j]]!
                    for a in bucketA {
                        if state.isCancelled?() == true {
                            state.totalComparisons = baseComparisons + comparisons
                            return
                        }
                        for b in bucketB {
                            let key = PairKey(a.id, b.id)
                            guard !state.seen.contains(key) else { continue }
                            let fnScore = filenameComparator.score(
                                normalizedA: normalizedFilenames[a.id]!,
                                normalizedB: normalizedFilenames[b.id]!
                            )
                            guard fnScore >= minFilenameCrossBucket else { continue }
                            state.seen.insert(key)
                            record(a, b)
                        }
                    }
                }
            }
        } else {
            // Pass 2 (image): filename-indexed cross-bucket with date proximity gate
            var filenameIndex: [String: [PhotoAssetMetadata]] = [:]
            for asset in assets {
                let normalized = normalizedFilenames[asset.id]!
                guard !normalized.isEmpty else { continue }
                filenameIndex[normalized, default: []].append(asset)
            }
            for (_, group) in filenameIndex {
                guard group.count >= 2 else { continue }
                for i in 0..<group.count {
                    if state.isCancelled?() == true {
                        state.totalComparisons = baseComparisons + comparisons
                        return
                    }
                    let bucketI = imageBucketKey(group[i])
                    for j in (i + 1)..<group.count {
                        guard imageBucketKey(group[j]) != bucketI else { continue }
                        if let dateI = group[i].creationDate, let dateJ = group[j].creationDate,
                           abs(dateI.timeIntervalSince(dateJ)) > maxCrossBucketDateDiff
                        {
                            continue
                        }
                        evaluate(group[i], group[j])
                    }
                }
            }
        }

        state.totalComparisons = baseComparisons + comparisons

        // Final progress report
        let finalElapsed = Double(
            DispatchTime.now().uptimeNanoseconds - startTime.uptimeNanoseconds) / 1_000_000_000
        state.onProgress?(Progress(
            current: state.totalComparisons, total: state.estimatedTotal,
            pairsFound: state.results.count,
            rate: finalElapsed > 0 ? Double(comparisons) / finalElapsed : 0,
            cacheHits: state.cachedCount, cacheMisses: state.totalComparisons - state.cachedCount
        ))
    }

    /// Score a single pair. Returns nil when the pair is gated (low filename similarity).
    private static func scorePair(
        _ a: PhotoAssetMetadata,
        _ b: PhotoAssetMetadata,
        isVideo: Bool,
        weights: [(String, Double)],
        normalizedFilenames: [String: String]
    ) -> PhotosScoredPair? {
        var breakdown: [String: Double] = [:]
        var detail: [String: DetailScoreTuple] = [:]
        var total: Double = 0

        for (name, weight) in weights {
            let rawValue = rawScore(name, a, b, normalizedFilenames: normalizedFilenames)
            let contribution = rawValue * weight
            breakdown[name] = contribution
            detail[name] = DetailScoreTuple(raw: rawValue, weight: weight)
            total += contribution

            // Filename gate: low filename similarity means the files are unrelated,
            // regardless of how similar their metadata happens to be.
            if name == "filename" && weight > 0 && rawValue < minFilenameRatio {
                return nil
            }
        }

        return PhotosScoredPair(
            assetA: a.id,
            assetB: b.id,
            score: Int(total.rounded()),
            breakdown: breakdown,
            detail: detail
        )
    }

    /// Compute raw comparator score (0.0-1.0) for a named comparator.
    private static func rawScore(
        _ name: String,
        _ a: PhotoAssetMetadata,
        _ b: PhotoAssetMetadata,
        normalizedFilenames: [String: String]
    ) -> Double {
        switch name {
        case "filename":
            return filenameComparator.score(
                normalizedA: normalizedFilenames[a.id]!,
                normalizedB: normalizedFilenames[b.id]!
            )
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
            // resolution when other EXIF sub-fields are absent.
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
        if pixels <= 153_600 { return 0 }
        if pixels <= 409_920 { return 1 }
        if pixels <= 921_600 { return 2 }
        if pixels <= 2_073_600 { return 3 }
        if pixels <= 3_686_400 { return 4 }
        return 5
    }

    /// Image bucket key: 30-minute creation-date window.
    /// Nil-date assets fall back to resolution tier.
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
