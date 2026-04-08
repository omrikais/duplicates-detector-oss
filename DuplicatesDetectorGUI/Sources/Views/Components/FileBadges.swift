import SwiftUI

/// Reusable crown (keep) and pin (reference) badge indicators.
///
/// Three visual styles cover all current usage:
/// - `.inline` — standard inline icons (InspectorPane, QueuePane)
/// - `.overlay` — translucent circle background for thumbnail overlays (GroupReviewView)
/// - `.label` — full `Label` with text (ComparisonPanel score header)
struct FileBadges: View {
    let isKeep: Bool
    let isReference: Bool
    var style: Style = .inline

    enum Style: Sendable {
        case inline
        case overlay
        case label(keepText: String, referenceText: String)
    }

    var body: some View {
        switch style {
        case .inline:
            inlineBadges
        case .overlay:
            overlayBadges
        case .label(let keepText, let referenceText):
            labelBadges(keepText: keepText, referenceText: referenceText)
        }
    }

    @ViewBuilder
    private var inlineBadges: some View {
        if isKeep {
            Image(systemName: "crown.fill")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.accent)
                .accessibilityLabel("Kept file")
        }
        if isReference {
            Image(systemName: "pin.fill")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.warning)
                .accessibilityLabel("Reference file")
        }
    }

    @ViewBuilder
    private var overlayBadges: some View {
        if isKeep {
            Image(systemName: "crown.fill")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.accent)
                .padding(DDSpacing.xs)
                .glassEffect(.regular.tint(DDColors.accent.opacity(0.2)), in: .circle)
                .accessibilityLabel("Kept file")
        }
        if isReference {
            Image(systemName: "pin.fill")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.warning)
                .padding(DDSpacing.xs)
                .glassEffect(.regular.tint(DDColors.warning.opacity(0.2)), in: .circle)
                .accessibilityLabel("Reference file")
        }
    }

    @ViewBuilder
    private func labelBadges(keepText: String, referenceText: String) -> some View {
        if isKeep {
            Label(keepText, systemImage: "crown.fill")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.accent)
        }
        if isReference {
            Label(referenceText, systemImage: "pin.fill")
                .font(DDTypography.label)
                .foregroundStyle(DDColors.warning)
        }
    }
}
