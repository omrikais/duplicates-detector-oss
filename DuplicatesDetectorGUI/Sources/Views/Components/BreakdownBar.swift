import SwiftUI

/// Horizontal stacked bar showing score breakdown by comparator.
///
/// Three variants:
/// - `.compact` (8pt) — queue rows. Capsule, no labels.
/// - `.detail` (10pt) — comparison panel summary strip. Capsule, no labels.
/// - `.editorial` (22pt) — prominent breakdown pane. Rounded rect with inset
///   bevel, satin overlay, inline per-segment labels (short name + value),
///   threshold ticks at 50/70/90, hairline segment dividers. Labels hide
///   automatically on segments too narrow to fit them.
struct BreakdownBar: View {
    enum Variant {
        case compact
        case detail
        case editorial

        var height: CGFloat {
            switch self {
            case .compact: DDSpacing.breakdownBarCompact
            case .detail: DDSpacing.breakdownBarDetail
            case .editorial: DDSpacing.breakdownBarEditorial
            }
        }

        var isEditorial: Bool { self == .editorial }
    }

    /// Maps comparator name → weighted score contribution (raw * weight).
    let breakdown: [String: Double?]
    /// Maps comparator name → detail (raw, weight) for tooltip.
    let detail: [String: DetailScore]
    let totalScore: Double
    var variant: Variant = .compact

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                if variant.isEditorial {
                    RoundedRectangle(cornerRadius: DDRadius.small)
                        .fill(LinearGradient(
                            colors: [Color.black.opacity(0.35), Color.black.opacity(0.10)],
                            startPoint: .top,
                            endPoint: .bottom
                        ))
                }

                HStack(spacing: variant.isEditorial ? 0 : DDSpacing.hairline) {
                    ForEach(Array(sortedSegments.enumerated()), id: \.element.key) { index, segment in
                        let fraction = totalScore > 0 ? segment.value / totalScore : 0
                        let width = max(fraction * geo.size.width, variant.isEditorial ? 4 : 2)
                        segmentView(
                            for: segment,
                            width: width,
                            isLast: index == sortedSegments.count - 1
                        )
                    }
                }
                .clipShape(clipShape)

                if variant.isEditorial {
                    thresholdTicks(totalWidth: geo.size.width)

                    RoundedRectangle(cornerRadius: DDRadius.small)
                        .stroke(Color.white.opacity(0.04), lineWidth: 1)
                        .allowsHitTesting(false)
                }
            }
        }
        .frame(height: variant.height)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
    }

    // MARK: - Segment

    @ViewBuilder
    private func segmentView(
        for segment: (key: String, value: Double),
        width: CGFloat,
        isLast: Bool
    ) -> some View {
        let color = DDColors.comparatorColor(for: segment.key)

        if variant.isEditorial {
            ZStack(alignment: .leading) {
                color
                LinearGradient(
                    colors: [
                        Color.white.opacity(0.14),
                        Color.clear,
                        Color.black.opacity(0.12),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                if showsInlineLabel(width: width) {
                    HStack(spacing: 6) {
                        Text(DDComparators.shortName(for: segment.key))
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(Color.white.opacity(0.95))
                            .lineLimit(1)
                            .truncationMode(.tail)
                        Spacer(minLength: 0)
                        Text(String(format: "%.0f", segment.value))
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .monospacedDigit()
                            .foregroundStyle(Color.white.opacity(0.95))
                    }
                    .padding(.horizontal, DDSpacing.sm)
                }
            }
            .frame(width: width, height: variant.height)
            .overlay(alignment: .trailing) {
                if !isLast {
                    Rectangle()
                        .fill(Color.black.opacity(0.35))
                        .frame(width: 1)
                }
            }
            .help(tooltipText(for: segment.key, value: segment.value))
        } else {
            Rectangle()
                .fill(color)
                .frame(width: width)
                .help(tooltipText(for: segment.key, value: segment.value))
        }
    }

    private func showsInlineLabel(width: CGFloat) -> Bool {
        width >= 44
    }

    // MARK: - Threshold ticks (editorial only)

    @ViewBuilder
    private func thresholdTicks(totalWidth: CGFloat) -> some View {
        ZStack(alignment: .leading) {
            tick(at: 0.50, opacity: 0.06, width: totalWidth)
            tick(at: 0.70, opacity: 0.06, width: totalWidth)
            tick(at: 0.90, opacity: 0.09, width: totalWidth)
        }
        .allowsHitTesting(false)
    }

    @ViewBuilder
    private func tick(at fraction: CGFloat, opacity: Double, width: CGFloat) -> some View {
        Rectangle()
            .fill(Color.white.opacity(opacity))
            .frame(width: 1, height: variant.height)
            .offset(x: width * fraction)
    }

    // MARK: - Clip shape

    private var clipShape: AnyShape {
        if variant.isEditorial {
            AnyShape(RoundedRectangle(cornerRadius: DDRadius.small))
        } else {
            AnyShape(Capsule())
        }
    }

    // MARK: - Accessibility & tooltips

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

// MARK: - Score Tier

/// Tier classification mirroring the score scale. Use for the editorial
/// breakdown-bar tier chip and any other surface that needs the score band.
enum ScoreTier: String, CaseIterable {
    case critical
    case high
    case medium
    case low

    init(score: Double) {
        switch score {
        case 90...: self = .critical
        case 70..<90: self = .high
        case 50..<70: self = .medium
        default: self = .low
        }
    }

    /// Short uppercase label — `CRIT` / `HIGH` / `MED` / `LOW`.
    var shortLabel: String {
        switch self {
        case .critical: "CRIT"
        case .high: "HIGH"
        case .medium: "MED"
        case .low: "LOW"
        }
    }

    var color: Color {
        switch self {
        case .critical: DDColors.scoreCritical
        case .high: DDColors.scoreHigh
        case .medium: DDColors.scoreMedium
        case .low: DDColors.scoreLow
        }
    }
}

#if DEBUG
#Preview("Breakdown Bar — Editorial") {
    VStack(spacing: DDSpacing.md) {
        BreakdownBar(
            breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            totalScore: 95.5,
            variant: .editorial
        )

        BreakdownBar(
            breakdown: ["content": 28.0, "filename": 18.0, "resolution": 14.0, "exif": 7.0, "fileSize": 5.0],
            detail: [:],
            totalScore: 72.3,
            variant: .editorial
        )

        BreakdownBar(
            breakdown: ["duration": 18.0, "audio": 14.0, "filename": 12.0, "tags": 8.0, "fileSize": 6.0],
            detail: [:],
            totalScore: 58.1,
            variant: .editorial
        )
    }
    .frame(width: 500)
    .padding()
    .background(DDColors.surface0)
}

#Preview("Breakdown Bar — Compact") {
    VStack(spacing: DDSpacing.md) {
        BreakdownBar(
            breakdown: ["filename": 48.0, "duration": 29.5, "resolution": 10.0, "fileSize": 8.0],
            detail: [
                "filename": DetailScore(raw: 0.96, weight: 50),
                "duration": DetailScore(raw: 0.98, weight: 30),
                "resolution": DetailScore(raw: 1.0, weight: 10),
                "fileSize": DetailScore(raw: 0.8, weight: 10),
            ],
            totalScore: 95.5,
            variant: .compact
        )

        BreakdownBar(
            breakdown: ["filename": 15.0, "duration": 28.0, "resolution": 10.0, "fileSize": 9.3],
            detail: [:],
            totalScore: 72.3,
            variant: .compact
        )
    }
    .frame(width: 300)
    .padding()
    .background(DDColors.surface0)
}
#endif
