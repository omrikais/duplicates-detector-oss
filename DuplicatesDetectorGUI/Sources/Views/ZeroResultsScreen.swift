import SwiftUI

/// Dedicated screen for scans that complete with zero duplicates found.
/// Intercepted in `ScanFlowView` before entering the full `ResultsScreen`.
struct ZeroResultsScreen: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors

    private var results: ResultsSnapshot? { store.session.results }

    var body: some View {
        VStack(spacing: DDSpacing.lg) {
            Spacer()

            heroSection

            statsRow

            Spacer()
        }
        .padding(DDSpacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DDColors.surface0)
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Button { store.send(.resetToSetup) } label: {
                    Label("New Scan", systemImage: "arrow.left")
                }
            }
        }
    }

    // MARK: - Hero

    private var heroSection: some View {
        VStack(spacing: DDSpacing.md) {
            Image(systemName: "checkmark.seal.fill")
                .font(DDTypography.headerIcon)
                .foregroundStyle(DDColors.success)
                .accessibilityHidden(true)

            Text("No Duplicates Found")
                .font(DDTypography.heading)
                .foregroundStyle(ddColors.textPrimary)

            Text("Scanned \(results?.filesScanned ?? 0) files — no duplicates detected.")
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textSecondary)
                .multilineTextAlignment(.center)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.heroAccessibilityLabel(filesScanned: results?.filesScanned ?? 0))
    }

    /// Build the hero accessibility label. Exposed for unit testing.
    nonisolated static func heroAccessibilityLabel(filesScanned: Int) -> String {
        "No Duplicates Found. Scanned \(filesScanned) files, no duplicates detected."
    }

    // MARK: - Stats

    private var statsRow: some View {
        HStack(spacing: DDSpacing.md) {
            DDStatCapsule(icon: "doc.on.doc", value: "\(results?.filesScanned ?? 0)", label: "scanned")
            if let r = results, r.filesAfterFilter != r.filesScanned, r.filesAfterFilter > 0 {
                DDStatCapsule(icon: "line.3.horizontal.decrease", value: "\(r.filesAfterFilter)", label: "after filter")
            }
            DDStatCapsule(icon: "clock", value: results?.totalTime ?? "0s", label: "elapsed")
        }
    }
}

#if DEBUG
#Preview("Zero Results") {
    ZeroResultsScreen(
        store: PreviewFixtures.sessionStore()
    )
    .frame(width: 800, height: 600)
}

#endif
