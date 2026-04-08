import Testing
@testable import DuplicatesDetector

@Suite("FilenameComparator")
struct FilenameComparatorTests {

    let comparator = FilenameComparator()

    @Test("identical filenames score 1.0")
    func identical() {
        #expect(comparator.score("vacation_photo.jpg", "vacation_photo.jpg") == 1.0)
    }

    @Test("similar filenames score high")
    func similar() {
        let score = comparator.score("vacation_photo.jpg", "vacation_photos.jpg")
        #expect(score > 0.9)
    }

    @Test("completely different filenames score 0.0")
    func different() {
        let score = comparator.score("sunset.jpg", "receipt.pdf")
        #expect(score == 0.0)
    }

    @Test("numeric ID — identical digits match")
    func numericIDMatch() {
        let score = comparator.score("IMG_20240615_123456.jpg", "IMG_20240615_123456.heic")
        #expect(score > 0.8)
    }

    @Test("numeric ID — different digits score 0")
    func numericIDDifferent() {
        let score = comparator.score("IMG_20240615_123456.jpg", "IMG_20240615_789012.jpg")
        #expect(score == 0.0)
    }

    @Test("numbered series — same text different numbers score 0")
    func numberedSeries() {
        let score = comparator.score("Movie Part 1.mp4", "Movie Part 2.mp4")
        #expect(score == 0.0)
    }

    @Test("distinct content words — each has unique word")
    func distinctContentWords() {
        let score = comparator.score("Mexico Guadalupe.jpg", "Mexico Izamal.jpg")
        #expect(score == 0.0)
    }

    @Test("reordered tokens score high")
    func reorderedTokens() {
        let score = comparator.score("beach vacation 2024.jpg", "2024 beach vacation.jpg")
        #expect(score == 1.0)
    }

    @Test("empty filenames score 0")
    func empty() {
        #expect(comparator.score("", "") == 0.0)
    }

    @Test("quality markers stripped")
    func qualityMarkers() {
        let score = comparator.score("movie 1080p.mp4", "movie.mp4")
        #expect(score > 0.8)
    }

    @Test("normalize strips extension, quality markers, separators, and lowercases")
    func normalizeMethod() {
        let result = FilenameComparator.normalize("Movie_1080p.mp4")
        #expect(result == "movie")
    }

    @Test("extension-only difference scores high")
    func extensionOnlyDifference() {
        let score = comparator.score("photo.heic", "photo.jpg")
        #expect(score == 1.0)
    }

    @Test("unicode filenames do not crash")
    func unicodeFilenames() {
        let score = comparator.score("cafe\u{0301}.jpg", "caf\u{00E9}.jpg")
        // Just verify it produces a valid score without crashing
        #expect(score >= 0.0 && score <= 1.0)
    }
}
