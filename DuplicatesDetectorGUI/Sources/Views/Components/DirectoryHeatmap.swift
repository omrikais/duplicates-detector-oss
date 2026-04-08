import SwiftUI

/// Native SwiftUI grid with density-colored cells showing per-directory duplicate statistics.
struct DirectoryHeatmap: View {
    let stats: [DirectoryStat]
    let onTap: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Directory Density")
                .font(DDTypography.sectionTitle)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: DDSpacing.sm) {
                ForEach(stats) { stat in
                    HeatmapCell(stat: stat)
                        .onTapGesture { onTap(stat.path) }
                }
            }
        }
    }
}

/// A single cell in the directory heatmap grid showing density, file counts, and recoverable size.
struct HeatmapCell: View {
    let stat: DirectoryStat

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.xxs) {
            Text(stat.path.split(separator: "/").last.map(String.init) ?? stat.path)
                .font(DDTypography.label)
                .lineLimit(1)
            Text("\(Int(stat.duplicateDensity * 100))% density")
                .font(DDTypography.metadata)
            Text("\(stat.duplicateFiles) of \(stat.totalFiles) files")
                .font(DDTypography.metadata)
                .foregroundStyle(DDColors.textSecondary)
        }
        .padding(DDSpacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(densityColor.opacity(0.25))
        .clipShape(RoundedRectangle(cornerRadius: DDRadius.medium))
        .overlay(RoundedRectangle(cornerRadius: DDRadius.medium).stroke(densityColor, lineWidth: 1))
        .accessibilityElement(children: .combine)
        .accessibilityLabel(HeatmapCell.accessibilityText(for: stat))
    }

    private var densityColor: Color {
        if stat.duplicateDensity < 0.2 { return DDColors.success }
        if stat.duplicateDensity < 0.5 { return DDColors.warning }
        return DDColors.destructive
    }

    /// Testable accessibility label builder.
    nonisolated static func accessibilityText(for stat: DirectoryStat) -> String {
        "\(stat.path), \(Int(stat.duplicateDensity * 100)) percent density, \(stat.duplicateFiles) of \(stat.totalFiles) files"
    }
}
