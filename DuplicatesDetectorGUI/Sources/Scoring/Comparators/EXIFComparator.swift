import Foundation

/// EXIF metadata for comparison. Fields are optional; missing fields
/// cause weight redistribution to present fields.
struct EXIFData: Sendable, Equatable {
    var creationDate: Date? = nil
    var cameraModel: String? = nil
    var lensModel: String? = nil
    var latitude: Double? = nil
    var longitude: Double? = nil
    var width: Int? = nil
    var height: Int? = nil
}

/// Haversine distance in meters between two GPS coordinates.
private func haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double) -> Double {
    let r = 6_371_000.0
    let dLat = (lat2 - lat1) * .pi / 180
    let dLon = (lon2 - lon1) * .pi / 180
    let a = sin(dLat / 2) * sin(dLat / 2) +
        cos(lat1 * .pi / 180) * cos(lat2 * .pi / 180) *
        sin(dLon / 2) * sin(dLon / 2)
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))
}

/// Scores EXIF similarity with sub-field weights and redistribution.
/// Sub-fields: datetime=0.35, camera=0.20, lens=0.10, GPS=0.25, dimensions=0.10
struct EXIFComparator {

    private struct SubField {
        let name: String
        let weight: Double
        let score: Double?
    }

    func score(_ a: EXIFData, _ b: EXIFData) -> Double? {
        let subFields: [SubField] = [
            SubField(name: "datetime", weight: 0.35, score: scoreDatetime(a, b)),
            SubField(name: "camera", weight: 0.20, score: scoreExact(a.cameraModel, b.cameraModel)),
            SubField(name: "lens", weight: 0.10, score: scoreExact(a.lensModel, b.lensModel)),
            SubField(name: "gps", weight: 0.25, score: scoreGPS(a, b)),
            SubField(name: "dimensions", weight: 0.10, score: scoreDimensions(a, b)),
        ]

        let available = subFields.filter { $0.score != nil }
        if available.isEmpty { return nil }

        let totalWeight = available.reduce(0.0) { $0 + $1.weight }
        return available.reduce(0.0) { $0 + $1.score! * ($1.weight / totalWeight) }
    }

    private func scoreDatetime(_ a: EXIFData, _ b: EXIFData) -> Double? {
        guard let da = a.creationDate, let db = b.creationDate else { return nil }
        let diff = abs(da.timeIntervalSince(db))
        if diff <= 1.0 { return 1.0 }
        if diff >= 3600 { return 0.0 }
        return 1.0 - (diff / 3600.0)
    }

    private func scoreExact(_ a: String?, _ b: String?) -> Double? {
        guard let a, let b else { return nil }
        return a == b ? 1.0 : 0.0
    }

    private func scoreGPS(_ a: EXIFData, _ b: EXIFData) -> Double? {
        guard let latA = a.latitude, let lonA = a.longitude,
              let latB = b.latitude, let lonB = b.longitude else { return nil }
        let dist = haversineMeters(lat1: latA, lon1: lonA, lat2: latB, lon2: lonB)
        return max(0.0, 1.0 - dist / 1000.0)
    }

    private func scoreDimensions(_ a: EXIFData, _ b: EXIFData) -> Double? {
        guard let wA = a.width, let hA = a.height,
              let wB = b.width, let hB = b.height else { return nil }
        return (wA == wB && hA == hB) ? 1.0 : 0.0
    }
}
