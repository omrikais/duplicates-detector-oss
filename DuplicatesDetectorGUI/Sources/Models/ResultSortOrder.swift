import Foundation

/// Sort order for results display.
enum ResultSortOrder: String, CaseIterable, Sendable {
    case scoreDescending = "Score (High \u{2192} Low)"
    case scoreAscending = "Score (Low \u{2192} High)"
    case sizeDescending = "Size (Largest)"
    case pathAscending = "Path (A \u{2192} Z)"
}
