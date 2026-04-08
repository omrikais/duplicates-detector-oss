/// Compares durations with linear falloff within MAX_DIFF seconds.
/// Mirrors the Python CLI's DurationComparator.
struct DurationComparator {
    static let maxDiff: Double = 5.0

    func score(_ a: Double?, _ b: Double?) -> Double? {
        guard let a, let b else { return nil }
        let diff = abs(a - b)
        if diff >= Self.maxDiff { return 0.0 }
        return 1.0 - (diff / Self.maxDiff)
    }
}
