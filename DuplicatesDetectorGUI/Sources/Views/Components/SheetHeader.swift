import SwiftUI

/// Shared header for modal sheet views (Action Log, Ignore List, Scan History).
///
/// Provides a consistent layout: title, optional count badge, spacer, trailing
/// action buttons, and a Done dismiss button.
struct SheetHeader<TrailingActions: View>: View {
    let title: String
    let count: Int?
    @ViewBuilder var trailingActions: () -> TrailingActions
    let onDismiss: () -> Void
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        HStack(spacing: DDSpacing.md) {
            Text(title)
                .font(DDTypography.sectionTitle)
                .foregroundStyle(ddColors.textPrimary)
            if let count {
                Text("(\(count))")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }
            Spacer()
            trailingActions()
            Button("Done") { onDismiss() }
                .keyboardShortcut(.cancelAction)
                .controlSize(.small)
        }
        .padding(DDDensity.regular)
    }
}
