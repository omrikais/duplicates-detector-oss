import Foundation
import Testing
@testable import DuplicatesDetector

@Suite("EXIFComparator")
struct EXIFComparatorTests {

    let comparator = EXIFComparator()

    @Test("identical EXIF scores 1.0")
    func identical() {
        let a = EXIFData(
            creationDate: Date(timeIntervalSince1970: 1000),
            cameraModel: "iPhone 15 Pro", lensModel: "6.765mm",
            latitude: 40.7128, longitude: -74.0060,
            width: 4032, height: 3024
        )
        #expect(comparator.score(a, a) == 1.0)
    }

    @Test("GPS within 10m scores near 1.0 (1km linear falloff)")
    func gpsClose() {
        let a = EXIFData(latitude: 40.7128, longitude: -74.0060)
        let b = EXIFData(latitude: 40.71284, longitude: -74.0060)
        let score = comparator.score(a, b)
        #expect(score! > 0.9)
    }

    @Test("GPS > 1km scores 0.0 (1km linear falloff)")
    func gpsFar() {
        // ~5.5km apart — well beyond 1km cutoff
        let a = EXIFData(latitude: 40.7128, longitude: -74.0060)
        let b = EXIFData(latitude: 40.7628, longitude: -74.0060)
        let score = comparator.score(a, b)
        #expect(score! == 0.0)
    }

    @Test("GPS at 500m scores ~0.5")
    func gpsMedium() {
        // ~444m apart (0.004 degrees latitude ≈ 445m)
        let a = EXIFData(latitude: 40.7128, longitude: -74.0060)
        let b = EXIFData(latitude: 40.7168, longitude: -74.0060)
        let score = comparator.score(a, b)
        #expect(score! > 0.3 && score! < 0.7)
    }

    @Test("missing fields redistribute weight")
    func missingFields() {
        let a = EXIFData(cameraModel: "iPhone 15 Pro")
        let b = EXIFData(cameraModel: "iPhone 15 Pro")
        #expect(comparator.score(a, b) == 1.0)
    }

    @Test("all fields nil returns nil")
    func allNil() {
        let a = EXIFData()
        let b = EXIFData()
        #expect(comparator.score(a, b) == nil)
    }

    @Test("datetime within 1s scores 1.0 for datetime sub-field")
    func datetimeClose() {
        let now = Date()
        let a = EXIFData(creationDate: now)
        let b = EXIFData(creationDate: now.addingTimeInterval(0.5))
        #expect(comparator.score(a, b)! > 0.9)
    }

    @Test("different camera models score 0 for camera sub-field")
    func differentCamera() {
        let a = EXIFData(cameraModel: "iPhone 15 Pro")
        let b = EXIFData(cameraModel: "Canon EOS R5")
        #expect(comparator.score(a, b) == 0.0)
    }

    @Test("datetime at exactly 3600s boundary scores 0.0")
    func datetimeAtBoundary() {
        let now = Date()
        let a = EXIFData(creationDate: now)
        let b = EXIFData(creationDate: now.addingTimeInterval(3600))
        #expect(comparator.score(a, b) == 0.0)
    }

    @Test("datetime at 1800s scores approximately 0.5 for datetime sub-field")
    func datetimeHalfway() {
        let now = Date()
        let a = EXIFData(creationDate: now)
        let b = EXIFData(creationDate: now.addingTimeInterval(1800))
        // Only datetime sub-field is available, so overall score equals datetime score.
        // 1800/3600 = 0.5 → score = 1.0 - 0.5 = 0.5
        let score = comparator.score(a, b)!
        #expect(abs(score - 0.5) < 0.01)
    }

    @Test("matching lens models score 1.0 for lens sub-field")
    func lensMatching() {
        let a = EXIFData(lensModel: "6.765mm")
        let b = EXIFData(lensModel: "6.765mm")
        #expect(comparator.score(a, b) == 1.0)
    }

    @Test("different lens models score 0.0 for lens sub-field")
    func lensDifferent() {
        let a = EXIFData(lensModel: "6.765mm")
        let b = EXIFData(lensModel: "24-70mm f/2.8")
        #expect(comparator.score(a, b) == 0.0)
    }

    @Test("matching dimensions score 1.0 for dimensions sub-field")
    func dimensionsMatching() {
        let a = EXIFData(width: 4032, height: 3024)
        let b = EXIFData(width: 4032, height: 3024)
        #expect(comparator.score(a, b) == 1.0)
    }

    @Test("different dimensions score 0.0 for dimensions sub-field")
    func dimensionsDifferent() {
        let a = EXIFData(width: 4032, height: 3024)
        let b = EXIFData(width: 1920, height: 1080)
        #expect(comparator.score(a, b) == 0.0)
    }

    @Test("GPS at exactly 1000m scores 0.0")
    func gpsAtExactBoundary() {
        // 1000m / 1000m = 1.0 → score = max(0, 1.0 - 1.0) = 0.0
        // ~0.009 degrees latitude ≈ 1000m
        let a = EXIFData(latitude: 0.0, longitude: 0.0)
        let b = EXIFData(latitude: 0.00899, longitude: 0.0)
        let score = comparator.score(a, b)!
        // Haversine may not land exactly at 1000m; verify score is at or near 0.0
        #expect(score < 0.01)
    }

    @Test("only GPS present — weight redistributes from all other sub-fields")
    func onlyGPSRedistribution() {
        // Only GPS is available (weight 0.25 out of 0.25 total = 1.0 after redistribution).
        // Same GPS → score 1.0 for GPS → overall 1.0
        let a = EXIFData(latitude: 40.7128, longitude: -74.0060)
        let b = EXIFData(latitude: 40.7128, longitude: -74.0060)
        #expect(comparator.score(a, b) == 1.0)
    }
}
