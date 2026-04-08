import Charts
import SwiftUI

/// Main insights view composing trend summary, chart, heatmap, score distribution, and filetype breakdown.
///
/// Displayed as an overlay replacing the review desk content when `DisplayState.showInsights` is true.
struct InsightsTab: View {
    let analyticsData: AnalyticsData
    let currentDirectories: [String]
    let currentMode: ScanMode
    let sessionEntries: [SessionRegistry.Entry]
    /// Anchor date for trend comparisons — only scans up to this date are considered.
    let currentSessionDate: Date?
    let onDirectoryTap: (String) -> Void

    @Environment(\.ddColors) private var ddColors

    var body: some View {
        let scans = matchingScans
        ScrollView {
            VStack(spacing: DDSpacing.lg) {
                // 1. Trend Summary Card
                trendSummaryCard(scans: scans)

                // 2. Trend Chart (if >= 2 data points)
                if scans.count >= 2 {
                    TrendChart(entries: scans)
                        .padding(DDSpacing.md)
                        .ddGlassCard()
                }

                // 3. Directory Heatmap
                if !analyticsData.directoryStats.isEmpty {
                    DirectoryHeatmap(stats: analyticsData.directoryStats, onTap: onDirectoryTap)
                        .padding(DDSpacing.md)
                        .ddGlassCard()
                }

                // 4. Score Distribution
                if !analyticsData.scoreDistribution.isEmpty {
                    scoreDistributionChart
                        .padding(DDSpacing.md)
                        .ddGlassCard()
                }

                // 5. Filetype Breakdown
                if !analyticsData.filetypeBreakdown.isEmpty {
                    filetypeChart
                        .padding(DDSpacing.md)
                        .ddGlassCard()
                }
            }
            .padding(DDSpacing.md)
        }
    }

    // MARK: - Matching Scans

    private var matchingScans: [SessionRegistry.Entry] {
        SessionRegistry.findMatchingScans(for: currentDirectories, mode: currentMode, in: sessionEntries, upTo: currentSessionDate)
    }

    // MARK: - Trend Summary Card

    @ViewBuilder private func trendSummaryCard(scans: [SessionRegistry.Entry]) -> some View {
        VStack(spacing: DDSpacing.sm) {
            if scans.count >= 2 {
                let current = scans.last!
                let previous = scans[scans.count - 2]
                let delta = current.pairCount - previous.pairCount
                let percentChange: Int? = previous.pairCount > 0
                    ? Int(round(Double(abs(delta)) / Double(previous.pairCount) * 100))
                    : nil

                HStack(spacing: DDSpacing.sm) {
                    Image(systemName: trendIcon(delta: delta))
                        .font(DDIcon.largeFont)
                        .foregroundStyle(trendColor(delta: delta))
                    VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                        Text(trendHeadline(delta: delta, percent: percentChange))
                            .font(DDTypography.sectionTitle)
                            .foregroundStyle(ddColors.textPrimary)
                        Text("Compared to previous scan on \(formattedDate(previous.createdAt))")
                            .font(DDTypography.metadata)
                            .foregroundStyle(ddColors.textSecondary)
                    }
                    Spacer()
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(trendAccessibilityLabel(delta: delta, percent: percentChange, previous: previous))
            } else if scans.count == 1 {
                HStack(spacing: DDSpacing.sm) {
                    Image(systemName: "chart.line.uptrend.xyaxis")
                        .font(DDIcon.largeFont)
                        .foregroundStyle(DDColors.info)
                    Text("First scan \u{2014} trends will appear after future scans of these directories")
                        .font(DDTypography.body)
                        .foregroundStyle(ddColors.textSecondary)
                    Spacer()
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("First scan, trends will appear after future scans")
            } else {
                HStack(spacing: DDSpacing.sm) {
                    Image(systemName: "chart.line.uptrend.xyaxis")
                        .font(DDIcon.largeFont)
                        .foregroundStyle(ddColors.textMuted)
                    Text("Not enough scan history for trend analysis")
                        .font(DDTypography.body)
                        .foregroundStyle(ddColors.textSecondary)
                    Spacer()
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Not enough scan history for trend analysis")
            }
        }
        .padding(DDSpacing.md)
        .ddGlassCard()
    }

    // MARK: - Score Distribution Chart

    @ViewBuilder private var scoreDistributionChart: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Score Distribution")
                .font(DDTypography.sectionTitle)
            Chart(analyticsData.scoreDistribution) { bucket in
                BarMark(x: .value("Range", bucket.range), y: .value("Count", bucket.count))
                    .foregroundStyle(DDColors.accent)
            }
            .frame(height: 200)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "Score distribution chart with \(analyticsData.scoreDistribution.count) buckets"
        )
    }

    // MARK: - Filetype Breakdown Chart

    @ViewBuilder private var filetypeChart: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("File Types")
                .font(DDTypography.sectionTitle)
            Chart(Array(analyticsData.filetypeBreakdown.prefix(8))) { entry in
                SectorMark(angle: .value("Count", entry.count), innerRadius: .ratio(0.618))
                    .foregroundStyle(by: .value("Type", entry.ext))
            }
            .frame(height: 200)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(filetypeAccessibilityLabel)
    }

    private var filetypeAccessibilityLabel: String {
        let types = analyticsData.filetypeBreakdown.prefix(8)
            .map { "\($0.ext): \($0.count)" }
            .joined(separator: ", ")
        return "File types chart: \(types)"
    }

    // MARK: - Trend Helpers

    private func trendIcon(delta: Int) -> String {
        if delta < 0 { return "arrow.down.right" }
        if delta > 0 { return "arrow.up.right" }
        return "equal"
    }

    private func trendColor(delta: Int) -> Color {
        if delta < 0 { return DDColors.success }
        if delta > 0 { return DDColors.warning }
        return DDColors.info
    }

    private func trendHeadline(delta: Int, percent: Int?) -> String {
        if delta == 0 { return "No change in duplicate count" }
        let direction = delta < 0 ? "fewer" : "more"
        if let percent {
            return "\(delta < 0 ? "\u{2193}" : "\u{2191}") \(percent)% \(direction) duplicates"
        }
        return "\(abs(delta)) \(direction) duplicates"
    }

    private func trendAccessibilityLabel(delta: Int, percent: Int?, previous: SessionRegistry.Entry) -> String {
        let headline = trendHeadline(delta: delta, percent: percent)
        return "\(headline), compared to previous scan on \(formattedDate(previous.createdAt))"
    }

    private func formattedDate(_ date: Date) -> String {
        date.formatted(.dateTime.month(.abbreviated).day().year())
    }
}
