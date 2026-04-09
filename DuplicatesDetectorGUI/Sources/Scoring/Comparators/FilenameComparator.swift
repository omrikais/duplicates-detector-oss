import Foundation

/// Regex patterns matching the Python CLI's comparators.py.
private nonisolated(unsafe) let qualityMarkerPattern = try! Regex(
    // swiftlint:disable:next line_length
    "(?i)(1080p|720p|480p|2160p|4k|8k|uhd|hdr|hevc|h\\.?264|h\\.?265|x264|x265|aac|ac3|dts|bluray|brrip|dvdrip|webrip|web-?dl|hdtv|remux|repack|proper)"
)
private nonisolated(unsafe) let separatorPattern = try! Regex("[._\\-\\[\\](){}]")
private nonisolated(unsafe) let digitRunPattern = try! Regex("\\d+")

/// Returns true if >50% of the string's non-whitespace characters are digits.
private func isNumericID(_ s: String) -> Bool {
    let stripped = s.filter { !$0.isWhitespace }
    guard !stripped.isEmpty else { return false }
    let digitCount = stripped.filter(\.isNumber).count
    return Double(digitCount) / Double(stripped.count) > 0.5
}

/// Strip extension, quality markers, separators; lowercase and collapse whitespace.
private func normalizeFilename(_ filename: String) -> String {
    let name = (filename as NSString).deletingPathExtension
    var cleaned = name.replacing(qualityMarkerPattern, with: " ")
    cleaned = cleaned.replacing(separatorPattern, with: " ")
    return cleaned.lowercased().split(separator: " ").joined(separator: " ")
}

/// Scores filename similarity with CLI-matching heuristics.
///
/// Guards (in order):
/// 1. Numeric ID: >50% digits -> exact digit match or 0.0
/// 2. Numbered series: identical text skeleton + different digit runs -> 0.0
/// 3. Token-sort Levenshtein ratio
/// 4. Distinct content words: ratio < 0.85 + unique 3+ char alpha words on both sides -> 0.0
struct FilenameComparator {

    func score(_ filenameA: String, _ filenameB: String) -> Double {
        score(normalizedA: normalizeFilename(filenameA), normalizedB: normalizeFilename(filenameB))
    }

    /// Score pre-normalized filenames (avoids redundant normalization when the
    /// caller has already called `FilenameComparator.normalize()`).
    func score(normalizedA na: String, normalizedB nb: String) -> Double {
        guard !na.isEmpty, !nb.isEmpty else { return 0.0 }

        // Guard 1: Numeric ID detection
        if isNumericID(na) && isNumericID(nb) {
            let digitsA = na.filter(\.isNumber)
            let digitsB = nb.filter(\.isNumber)
            if digitsA != digitsB { return 0.0 }
        }

        // Guard 2: Numbered series detection
        let textA = na.replacing(digitRunPattern, with: "")
            .split(separator: " ").joined(separator: " ")
        let textB = nb.replacing(digitRunPattern, with: "")
            .split(separator: " ").joined(separator: " ")
        if !textA.isEmpty && textA == textB {
            let numsA = na.matches(of: digitRunPattern).map { String(na[$0.range]) }
            let numsB = nb.matches(of: digitRunPattern).map { String(nb[$0.range]) }
            if numsA != numsB { return 0.0 }
        }

        // Core: token-sort Levenshtein ratio
        let ratio = tokenSortRatio(na, nb)

        // Guard 4: Distinct content words
        if ratio < 0.85 {
            let tokensA = Set(na.split(separator: " ").map(String.init))
            let tokensB = Set(nb.split(separator: " ").map(String.init))
            let uniqueA = tokensA.subtracting(tokensB)
            let uniqueB = tokensB.subtracting(tokensA)
            let hasWordA = uniqueA.contains { $0.count >= 3 && $0.allSatisfy(\.isLetter) }
            let hasWordB = uniqueB.contains { $0.count >= 3 && $0.allSatisfy(\.isLetter) }
            if hasWordA && hasWordB { return 0.0 }
        }

        return ratio
    }

    /// Expose filename normalization for use by the scorer's filename index.
    static func normalize(_ filename: String) -> String {
        normalizeFilename(filename)
    }
}
