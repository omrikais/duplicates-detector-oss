import SwiftUI

/// Displays an error with recovery options.
///
/// Shown when `store.phase == .error(info)`. Offers "New Scan" (reset to setup)
/// and "Try Again" (retry with last config) buttons.
struct ErrorScreen: View {
    let error: ErrorInfo
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        VStack(spacing: DDSpacing.lg) {
            Spacer()

            VStack(spacing: DDSpacing.lg) {
                Image(systemName: error.systemImageName)
                    .font(DDTypography.headerIcon)
                    .foregroundStyle(DDColors.destructive)
                    .accessibilityHidden(true)

                Text(error.displayTitle)
                    .font(DDTypography.heading)
                    .foregroundStyle(ddColors.textPrimary)

                if let suggestion = error.recoverySuggestion {
                    HStack(alignment: .top, spacing: DDSpacing.sm) {
                        Image(systemName: "lightbulb")
                            .foregroundStyle(DDColors.info)
                            .accessibilityHidden(true)
                        Text(suggestion)
                            .font(DDTypography.body)
                            .foregroundStyle(ddColors.textSecondary)
                    }
                    .padding(DDDensity.regular)
                    .frame(maxWidth: DDSpacing.contentMaxWidth * 0.7)
                    .ddGlassCard()
                }

                DisclosureGroup("Details") {
                    Text(error.message)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textMuted)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(DDSpacing.sm)
                }
                .frame(maxWidth: DDSpacing.contentMaxWidth * 0.7)
                .foregroundStyle(ddColors.textMuted)
            }

            HStack(spacing: DDSpacing.md) {
                Button("Back to Configuration") {
                    store.send(.resetToSetup)
                }
                .buttonStyle(.glass)
                .accessibilityHint("Returns to the configuration screen")

                if store.session.lastScanConfig != nil {
                    Button("Try Again") {
                        if let config = store.session.lastScanConfig {
                            store.send(.resetToSetup)
                            store.send(.startScan(config))
                        }
                    }
                    .buttonStyle(.glass)
                    .accessibilityHint("Attempts to run the scan again")
                }
            }

            Spacer()
        }
        .padding(DDSpacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
