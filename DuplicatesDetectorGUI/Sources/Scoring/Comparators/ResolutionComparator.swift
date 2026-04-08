/// Compares resolutions by total pixel count ratio.
/// Mirrors the Python CLI's ResolutionComparator.
struct ResolutionComparator {
    func score(_ widthA: Int?, _ heightA: Int?, _ widthB: Int?, _ heightB: Int?) -> Double? {
        guard let wA = widthA, let hA = heightA, let wB = widthB, let hB = heightB else { return nil }
        let pixelsA = wA * hA
        let pixelsB = wB * hB
        if pixelsA == 0 || pixelsB == 0 { return 0.0 }
        return Double(min(pixelsA, pixelsB)) / Double(max(pixelsA, pixelsB))
    }
}
