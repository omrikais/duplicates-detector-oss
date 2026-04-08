/// Compute the Levenshtein edit distance between two strings.
func levenshteinDistance(_ s: String, _ t: String) -> Int {
    let s = Array(s)
    let t = Array(t)
    let m = s.count
    let n = t.count
    if m == 0 { return n }
    if n == 0 { return m }

    var prev = Array(0...n)
    var curr = [Int](repeating: 0, count: n + 1)

    for i in 1...m {
        curr[0] = i
        for j in 1...n {
            let cost = s[i - 1] == t[j - 1] ? 0 : 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        }
        swap(&prev, &curr)
    }
    return prev[n]
}

/// Levenshtein ratio: 1.0 for identical, 0.0 for completely different.
func levenshteinRatio(_ s: String, _ t: String) -> Double {
    let maxLen = max(s.count, t.count)
    if maxLen == 0 { return 1.0 }
    let dist = levenshteinDistance(s, t)
    return 1.0 - Double(dist) / Double(maxLen)
}

/// Token-sort ratio: tokenize both strings, sort tokens, then compute
/// Levenshtein ratio. Handles reordered words (e.g. "beach vacation 2024"
/// vs "2024 beach vacation" → 1.0).
///
/// Mirrors `rapidfuzz.fuzz.token_sort_ratio` from the Python CLI.
func tokenSortRatio(_ s: String, _ t: String) -> Double {
    let sortedS = s.split(separator: " ").sorted().joined(separator: " ")
    let sortedT = t.split(separator: " ").sorted().joined(separator: " ")
    return levenshteinRatio(sortedS, sortedT)
}
