import SwiftUI

/// Stat capsule displaying a value/label pair in a glass pill.
///
/// Two layout variants:
/// - **With icon**: `HStack { icon, VStack { value, label } }` — used in results screens
/// - **Without icon**: `VStack { value, label }` — used in progress stats
struct DDStatCapsule: View {
    let icon: String?
    let value: String
    let label: String
    var size: DDPillSize
    var isActive: Bool

    @Environment(\.ddColors) private var ddColors

    init(
        icon: String? = nil,
        value: String,
        label: String,
        size: DDPillSize = .medium,
        isActive: Bool = false
    ) {
        self.icon = icon
        self.value = value
        self.label = label
        self.size = size
        self.isActive = isActive
    }

    /// Build the accessibility label text. Exposed for unit testing.
    nonisolated static func accessibilityText(value: String, label: String) -> String {
        "\(value) \(label)"
    }

    var body: some View {
        Group {
            if let icon {
                HStack(spacing: DDSpacing.sm) {
                    Image(systemName: icon)
                        .foregroundStyle(ddColors.textSecondary)
                        .font(DDTypography.metadata)
                    valueLabelStack(innerSpacing: 0, alignment: .leading)
                }
            } else {
                valueLabelStack(innerSpacing: DDSpacing.hairline, alignment: .center)
            }
        }
        .ddGlassPill(size: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.accessibilityText(value: value, label: label))
    }

    private func valueLabelStack(innerSpacing: CGFloat, alignment: HorizontalAlignment) -> some View {
        VStack(alignment: alignment, spacing: innerSpacing) {
            Text(value)
                .font(DDTypography.monospaced)
                .foregroundStyle(isActive ? DDColors.accent : ddColors.textPrimary)
                .contentTransition(.numericText())
            Text(label)
                .font(DDTypography.label)
                .foregroundStyle(isActive ? DDColors.accent : ddColors.textSecondary)
        }
    }
}
