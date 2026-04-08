import SwiftUI

/// Circular score indicator with color gradient.
struct ScoreRing: View {
    let score: Double
    let size: Size

    nonisolated static func formattedScore(_ score: Double) -> String {
        "\(Int(score.rounded()))"
    }

    enum Size {
        case compact
        case regular

        var diameter: CGFloat {
            switch self {
            case .compact: 32
            case .regular: 56
            }
        }

        var lineWidth: CGFloat {
            switch self {
            case .compact: 3
            case .regular: 5
            }
        }

        var font: Font {
            switch self {
            case .compact: DDTypography.scoreLabelCompact
            case .regular: DDTypography.scoreLabelRegular
            }
        }
    }

    @Environment(\.ddColors) private var ddColors

    var body: some View {
        let color = ddColors.scoreColor(for: score)
        ZStack {
            Circle()
                .stroke(DDColors.surface2, lineWidth: size.lineWidth)

            Circle()
                .trim(from: 0, to: score / 100)
                .stroke(color, style: StrokeStyle(lineWidth: size.lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))

            Text(Self.formattedScore(score))
                .font(size.font)
                .foregroundStyle(color)
        }
        .frame(width: size.diameter, height: size.diameter)
        .glassEffect(.regular.tint(color.opacity(0.15)), in: .circle)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Similarity score")
        .accessibilityValue("\(Self.formattedScore(score)) percent")
    }
}

#if DEBUG
#Preview("Score Rings") {
    HStack(spacing: DDSpacing.lg) {
        VStack(spacing: DDSpacing.sm) {
            ScoreRing(score: 95, size: .compact)
            Text("Compact").font(DDTypography.label)
        }
        VStack(spacing: DDSpacing.sm) {
            ScoreRing(score: 95, size: .regular)
            Text("Regular").font(DDTypography.label)
        }
        VStack(spacing: DDSpacing.sm) {
            ScoreRing(score: 72, size: .regular)
            Text("High").font(DDTypography.label)
        }
        VStack(spacing: DDSpacing.sm) {
            ScoreRing(score: 55, size: .regular)
            Text("Medium").font(DDTypography.label)
        }
        VStack(spacing: DDSpacing.sm) {
            ScoreRing(score: 30, size: .regular)
            Text("Low").font(DDTypography.label)
        }
    }
    .padding()
}
#endif
