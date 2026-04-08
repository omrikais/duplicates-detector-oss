import SwiftUI

/// Horizontal stacked bar showing score breakdown by comparator.
struct BreakdownBar: View {
    /// Maps comparator name → weighted score contribution (raw * weight).
    let breakdown: [String: Double?]
    /// Maps comparator name → detail (raw, weight) for tooltip.
    let detail: [String: DetailScore]
    let totalScore: Double

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: DDSpacing.hairline) {
                ForEach(sortedSegments, id: \.key) { segment in
                    let fraction = totalScore > 0 ? segment.value / totalScore : 0
                    let width = max(fraction * geo.size.width, 2)
                    Rectangle()
                        .fill(DDColors.comparatorColor(for: segment.key))
                        .frame(width: width)
                        .help(tooltipText(for: segment.key, value: segment.value))
                }
            }
        }
        .frame(height: DDSpacing.breakdownBarCompact)
        .clipShape(Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
    }

    private var accessibilitySummary: String {
        Self.buildAccessibilitySummary(breakdown: breakdown)
    }

    /// Build the accessibility summary string from a breakdown dictionary.
    /// Exposed as `internal` for unit testing.
    nonisolated static func buildAccessibilitySummary(breakdown: [String: Double?]) -> String {
        let sorted = breakdown.compactMap { key, value -> (key: String, value: Double)? in
            guard let v = value, v > 0 else { return nil }
            return (key: key, value: v)
        }
        .sorted {
            if $0.value != $1.value { return $0.value > $1.value }
            return $0.key < $1.key
        }
        let parts = sorted.map { "\(DDComparators.displayName(for: $0.key)) \(Int($0.value))" }
        if parts.isEmpty { return "No score breakdown" }
        return "Score breakdown: \(parts.joined(separator: ", "))"
    }

    private var sortedSegments: [(key: String, value: Double)] {
        breakdown.compactMap { key, value in
            guard let v = value, v > 0 else { return nil }
            return (key: key, value: v)
        }
        .sorted {
            if $0.value != $1.value { return $0.value > $1.value }
            return $0.key < $1.key
        }
    }

    private func tooltipText(for key: String, value: Double) -> String {
        let displayName = DDComparators.displayName(for: key)
        if let d = detail[key] {
            return "\(displayName): \(String(format: "%.0f", d.raw * 100))% × \(String(format: "%.0f", d.weight))"
        }
        return "\(displayName): \(String(format: "%.1f", value))"
    }
}

#if DEBUG
#Preview("Breakdown Bar") {
    VStack(spacing: DDSpacing.md) {
        BreakdownBar(
            breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            totalScore: 95.5
        )

        BreakdownBar(
            breakdown: ["filename": 15.0, "duration": 28.0, "resolution": 10.0, "fileSize": 9.3],
            detail: [
                "filename": DetailScore(raw: 0.30, weight: 50),
                "duration": DetailScore(raw: 0.93, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.93, weight: 10),
            ],
            totalScore: 72.3
        )
    }
    .frame(width: 300)
    .padding()
}
#endif
