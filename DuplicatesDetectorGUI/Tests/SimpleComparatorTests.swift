import Testing
@testable import DuplicatesDetector

@Suite("DurationComparator")
struct DurationComparatorTests {
    let comparator = DurationComparator()

    @Test("identical durations score 1.0")
    func identical() {
        #expect(comparator.score(100.0, 100.0) == 1.0)
    }

    @Test("difference >= 5s scores 0.0")
    func beyondMax() {
        #expect(comparator.score(100.0, 105.0) == 0.0)
        #expect(comparator.score(100.0, 106.0) == 0.0)
    }

    @Test("linear falloff within 5s")
    func linearFalloff() {
        #expect(comparator.score(100.0, 102.5) == 0.5)
    }

    @Test("nil durations return nil")
    func nilDuration() {
        #expect(comparator.score(nil, 100.0) == nil)
        #expect(comparator.score(100.0, nil) == nil)
    }

    @Test("both nil returns nil")
    func bothNil() {
        #expect(comparator.score(nil, nil) == nil)
    }

    @Test("zero durations score 1.0")
    func zeroDurations() {
        #expect(comparator.score(0.0, 0.0) == 1.0)
    }

    @Test("boundary precision — 4.99s difference returns small positive score")
    func boundaryPrecision() {
        let result = comparator.score(100.0, 104.99)!
        #expect(result > 0.0)
        #expect(result < 0.01)
    }
}

@Suite("ResolutionComparator")
struct ResolutionComparatorTests {
    let comparator = ResolutionComparator()

    @Test("identical resolutions score 1.0")
    func identical() {
        #expect(comparator.score(1920, 1080, 1920, 1080) == 1.0)
    }

    @Test("4K vs 1080p scores ~0.25")
    func fourKvs1080p() {
        let score = comparator.score(3840, 2160, 1920, 1080)
        #expect(abs(score! - 0.25) < 0.01)
    }

    @Test("zero dimensions return 0.0")
    func zeroDimensions() {
        #expect(comparator.score(0, 0, 1920, 1080) == 0.0)
    }

    @Test("nil dimensions return nil")
    func nilDimensions() {
        #expect(comparator.score(Int?(nil), Int?(nil), 1920, 1080) == nil)
    }

    @Test("both nil returns nil")
    func bothNil() {
        #expect(comparator.score(Int?(nil), Int?(nil), Int?(nil), Int?(nil)) == nil)
    }

    @Test("commutativity — swapped inputs produce same score")
    func commutativity() {
        let forward = comparator.score(1920, 1080, 3840, 2160)
        let reverse = comparator.score(3840, 2160, 1920, 1080)
        #expect(forward == reverse)
    }
}

@Suite("FileSizeComparator")
struct FileSizeComparatorTests {
    let comparator = FileSizeComparator()

    @Test("identical sizes score 1.0")
    func identical() {
        #expect(comparator.score(1_000_000, 1_000_000) == 1.0)
    }

    @Test("double size scores 0.5")
    func doubleSize() {
        #expect(comparator.score(500_000, 1_000_000) == 0.5)
    }

    @Test("zero size returns 0.0")
    func zeroSize() {
        #expect(comparator.score(0, 1_000_000) == 0.0)
    }

    @Test("both zero returns 0.0")
    func bothZero() {
        #expect(comparator.score(0, 0) == 0.0)
    }

    @Test("commutativity — swapped inputs produce same score")
    func commutativity() {
        let forward = comparator.score(500_000, 1_000_000)
        let reverse = comparator.score(1_000_000, 500_000)
        #expect(forward == reverse)
    }

    @Test("very small difference scores close to 1.0")
    func verySmallDifference() {
        let result = comparator.score(1_000_000, 1_000_001)
        #expect(result > 0.999)
    }
}
