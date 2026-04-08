import Testing
@testable import DuplicatesDetector

@Suite("LevenshteinRatio")
struct LevenshteinRatioTests {

    @Test("identical strings score 1.0")
    func identical() {
        #expect(tokenSortRatio("hello world", "hello world") == 1.0)
    }

    @Test("completely different strings score 0.0")
    func completelyDifferent() {
        #expect(tokenSortRatio("abc", "xyz") == 0.0)
    }

    @Test("empty strings score 1.0")
    func bothEmpty() {
        #expect(tokenSortRatio("", "") == 1.0)
    }

    @Test("one empty string scores 0.0")
    func oneEmpty() {
        #expect(tokenSortRatio("hello", "") == 0.0)
    }

    @Test("token sort handles reordered words")
    func reorderedTokens() {
        #expect(tokenSortRatio("beach vacation 2024", "2024 beach vacation") == 1.0)
    }

    @Test("similar strings score high")
    func similar() {
        let score = tokenSortRatio("vacation photo", "vacation photos")
        #expect(score > 0.9)
    }

    @Test("case sensitive comparison")
    func caseSensitive() {
        #expect(tokenSortRatio("ABC", "abc") < 1.0)
    }

    @Test("levenshteinDistance: kitten to sitting is 3")
    func kittenSitting() {
        #expect(levenshteinDistance("kitten", "sitting") == 3)
    }

    @Test("levenshteinRatio: identical strings return 1.0")
    func ratioIdentical() {
        #expect(levenshteinRatio("abc", "abc") == 1.0)
    }

    @Test("levenshteinRatio: completely different returns 0.0")
    func ratioDifferent() {
        #expect(levenshteinRatio("abc", "xyz") == 0.0)
    }

    @Test("tokenSortRatio: single different character returns 0.0")
    func singleCharDifferent() {
        #expect(tokenSortRatio("a", "b") == 0.0)
    }

    @Test("tokenSortRatio: single identical character returns 1.0")
    func singleCharIdentical() {
        #expect(tokenSortRatio("a", "a") == 1.0)
    }
}
