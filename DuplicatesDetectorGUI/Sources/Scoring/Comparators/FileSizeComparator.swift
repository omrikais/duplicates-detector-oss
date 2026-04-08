/// Compares file sizes by byte ratio.
/// Mirrors the Python CLI's FileSizeComparator.
struct FileSizeComparator {
    func score(_ a: Int64, _ b: Int64) -> Double {
        if a == 0 || b == 0 { return 0.0 }
        return Double(min(a, b)) / Double(max(a, b))
    }
}
