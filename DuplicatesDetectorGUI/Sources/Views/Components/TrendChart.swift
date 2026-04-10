import Charts
import SwiftUI

/// Swift Charts view showing historical scan data.
///
/// Splits into two stacked charts with independent Y-axes:
/// 1. Duplicate pairs found over time
/// 2. Space recoverable (MB) over time (when data is available)
struct TrendChart: View {
    let entries: [SessionRegistry.Entry]

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Scan Trends")
                .font(DDTypography.sectionTitle)

            Text("Duplicate Pairs")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.textSecondary)
            Chart(entries) { entry in
                LineMark(
                    x: .value("Date", entry.createdAt),
                    y: .value("Pairs", entry.pairCount)
                )
            }
            .foregroundStyle(.blue)
            .frame(height: 120)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Duplicate pairs trend chart")

            let entriesWithSpace = entries.filter { $0.spaceRecoverable != nil }
            if !entriesWithSpace.isEmpty {
                Text("Space Recoverable")
                    .font(DDTypography.label)
                    .foregroundStyle(DDColors.textSecondary)
                Chart(entriesWithSpace) { entry in
                    LineMark(
                        x: .value("Date", entry.createdAt),
                        y: .value("MB", Double(entry.spaceRecoverable ?? 0) / (1024 * 1024))
                    )
                }
                .foregroundStyle(.orange)
                .frame(height: 120)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Space recoverable trend chart")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Trend charts showing scan history")
    }
}
