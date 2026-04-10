import SwiftUI

/// Horizontal action bar for pair comparison: Keep A / Keep B / Skip / Skip & Ignore.
/// "Keep A" performs the active action (trash/delete/move) on File B, and vice versa.
///
/// When `resolution` is not `.active`, action buttons are hidden and replaced by
/// a read-only receipt banner showing what happened and when.
struct ComparisonActionBar: View {
    let pair: PairResult
    let activeAction: ActionType
    let currentIndex: Int?
    let totalPairs: Int
    var onKeepA: () -> Void
    var onKeepB: () -> Void
    var onPrevious: () -> Void
    var onSkip: () -> Void
    var onSkipAndIgnore: () -> Void
    var isAtFirstPair: Bool = false
    var resolution: PairResolutionStatus = .active
    @Environment(\.ddColors) private var ddColors

    /// Build the pair counter accessibility label. Exposed for unit testing.
    nonisolated static func pairCounterAccessibilityText(index: Int, total: Int) -> String {
        "Pair \(index + 1) of \(total)"
    }

    private var isBothReference: Bool {
        pair.fileAIsReference && pair.fileBIsReference
    }

    private var hasPhotosAsset: Bool {
        pair.fileA.isPhotosAssetURI || pair.fileB.isPhotosAssetURI
    }

    var body: some View {
        if case .active = resolution {
            VStack(spacing: 0) {
                if hasPhotosAsset && (activeAction == .trash || activeAction == .delete) {
                    photosTrashWarning
                }
                activeActionBar
            }
        } else {
            actionReceiptBanner
        }
    }

    // MARK: - Photos Trash Warning

    private var photosTrashWarning: some View {
        HStack(spacing: DDSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(DDColors.warning)
            Text("Photos items are moved to Recently Deleted (recoverable for 30 days)")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textSecondary)
        }
        .padding(DDDensity.compact)
    }

    // MARK: - Active Action Bar

    private var activeActionBar: some View {
        HStack(spacing: DDSpacing.md) {
            pairCounter

            Spacer()

            if isBothReference {
                Label("Both files are reference files \u{2014} no action needed",
                      systemImage: "pin.fill")
                    .font(DDTypography.label)
                    .foregroundStyle(DDColors.warning)
            } else if isActionCLIOnly {
                Label("File actions for this mode are CLI-only",
                      systemImage: "terminal")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
            } else {
                keepAButton
                keepBButton

                Divider()
                    .frame(height: 20)
            }

            previousButton
            skipButton
            skipAndIgnoreButton
        }
        .padding(DDDensity.compact)
        .ddGlassChrome()
    }

    // MARK: - Action Receipt Banner

    private var actionReceiptBanner: some View {
        HStack(spacing: DDSpacing.md) {
            pairCounter

            Spacer()

            receiptContent

            Spacer()

            previousButton
            skipButton
        }
        .padding(DDDensity.compact)
        .ddGlassChrome()
    }

    @ViewBuilder
    private var receiptContent: some View {
        switch resolution {
        case .active:
            EmptyView()
        case .resolved(let action):
            HStack(spacing: DDSpacing.sm) {
                Image(systemName: "checkmark.circle.fill")
                    .font(DDTypography.body)
                    .foregroundStyle(DDColors.success)
                VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                    Text(resolvedDescription(action))
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textPrimary)
                    HStack(spacing: DDSpacing.sm) {
                        if action.bytesFreed > 0 {
                            Text("Saved \(DDFormatters.formatFileSize(action.bytesFreed))")
                                .font(DDTypography.metadata)
                                .foregroundStyle(ddColors.textSecondary)
                        }
                        Text(relativeTimestamp(action.timestamp))
                            .font(DDTypography.metadata)
                            .foregroundStyle(ddColors.textMuted)
                    }
                }
            }
        case .probablySolved(let missing):
            HStack(spacing: DDSpacing.sm) {
                Image(systemName: "questionmark.circle.fill")
                    .font(DDTypography.body)
                    .foregroundStyle(DDColors.warning)
                VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                    if missing.count >= 2 {
                        Text("Both files are no longer on disk")
                            .font(DDTypography.label)
                            .foregroundStyle(ddColors.textPrimary)
                    } else if let missingPath = missing.first {
                        Text("\(missingPath.fileName) is no longer on disk")
                            .font(DDTypography.label)
                            .foregroundStyle(ddColors.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Text("This pair was likely resolved outside the app")
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textMuted)
                }
            }
        }
    }

    // MARK: - Receipt Helpers

    private func resolvedDescription(_ action: HistoryAction) -> String {
        let verb = action.fileAction?.pastTenseCapitalized ?? action.action.capitalized
        if let kept = action.kept {
            return "Kept \(kept.fileName), \(verb.lowercased()) \(action.path.fileName)"
        }
        return "\(verb) \(action.path.fileName)"
    }

    private static let iso8601Fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let iso8601Basic: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func relativeTimestamp(_ timestamp: String) -> String {
        // Try with fractional seconds first, then without
        guard let date = Self.iso8601Fractional.date(from: timestamp)
                ?? Self.iso8601Basic.date(from: timestamp) else {
            return timestamp
        }
        let interval = Date.now.timeIntervalSince(date)
        if interval < 60 { return "just now" }
        if interval < 3600 { return "\(Int(interval / 60))m ago" }
        if interval < 86400 { return "\(Int(interval / 3600))h ago" }
        return "\(Int(interval / 86400))d ago"
    }

    // MARK: - Pair Counter

    @ViewBuilder
    private var pairCounter: some View {
        if let index = currentIndex {
            Text("\(index + 1) of \(totalPairs)")
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textSecondary)
                .accessibilityLabel(Self.pairCounterAccessibilityText(index: index, total: totalPairs))
                .accessibilityHint("Use arrow keys to navigate pairs")
        }
    }

    // MARK: - Keep Buttons

    private var isActionCLIOnly: Bool {
        activeAction == .hardlink || activeAction == .symlink || activeAction == .reflink
    }

    private var keepAButton: some View {
        let labels = ComparisonPanel.fileLabels(fileA: pair.fileA, fileB: pair.fileB)
        return keepButton(side: "A", icon: "arrow.left.circle.fill",
                          keptLabel: labels.a, targetLabel: labels.b,
                          targetPath: pair.fileB, targetIsProtected: pair.fileBIsReference,
                          onKeep: onKeepA)
    }

    private var keepBButton: some View {
        let labels = ComparisonPanel.fileLabels(fileA: pair.fileA, fileB: pair.fileB)
        return keepButton(side: "B", icon: "arrow.right.circle.fill",
                          keptLabel: labels.b, targetLabel: labels.a,
                          targetPath: pair.fileA, targetIsProtected: pair.fileAIsReference,
                          onKeep: onKeepB)
    }

    private func keepButton(
        side: String, icon: String,
        keptLabel: String, targetLabel: String,
        targetPath: String, targetIsProtected: Bool,
        onKeep: @escaping () -> Void
    ) -> some View {
        let isDisabled = targetIsProtected || isActionCLIOnly
        return Button { onKeep() } label: {
            VStack(spacing: DDSpacing.xxs) {
                Label("Keep \(side)", systemImage: icon)
                Text("\(activeAction.displayName) \(targetPath.fileName)")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        .controlSize(.regular)
        .disabled(isDisabled)
        .help(isActionCLIOnly
              ? "\(activeAction.displayName) is available in the CLI only"
              : targetIsProtected
              ? "Cannot act on reference file"
              : "\(activeAction.displayName) \(targetPath.fileName)")
        .accessibilityIdentifier("Keep \(side)")
        .accessibilityLabel("Keep \(keptLabel)")
        .accessibilityHint(
            isActionCLIOnly ? "\(activeAction.displayName) is available in the CLI only"
            : targetIsProtected ? "Cannot act on reference file"
            : "Keeps this file and \(activeAction.displayName.lowercased())s \(targetLabel)"
        )
    }

    // MARK: - Navigation Buttons

    private var previousButton: some View {
        Button { onPrevious() } label: {
            Label("Previous", systemImage: "arrow.up.circle")
        }
        .controlSize(.regular)
        .disabled(isAtFirstPair)
        .help("Return to the previous pair")
    }

    private var skipButton: some View {
        Button { onSkip() } label: {
            Label("Skip", systemImage: "arrow.down.circle")
        }
        .controlSize(.regular)
        .help("Advance to the next pair without acting")
    }

    private var skipAndIgnoreButton: some View {
        Button { onSkipAndIgnore() } label: {
            Label("Ignore", systemImage: "xmark.circle")
        }
        .controlSize(.regular)
        .help("Add this pair to the ignore list and advance")
        .accessibilityHint("Marks this pair as not duplicates")
    }

}

#if DEBUG
#Preview("Action Bar — Trash") {
    let pair = PreviewFixtures.samplePairResults[0]
    ComparisonActionBar(
        pair: pair, activeAction: .trash,
        currentIndex: 0, totalPairs: 5,
        onKeepA: {}, onKeepB: {}, onPrevious: {}, onSkip: {}, onSkipAndIgnore: {}
    )
    .padding()
}

#Preview("Action Bar — Reference B") {
    let pair = PreviewFixtures.samplePairResults[1] // fileB is reference
    ComparisonActionBar(
        pair: pair, activeAction: .trash,
        currentIndex: 1, totalPairs: 2,
        onKeepA: {}, onKeepB: {}, onPrevious: {}, onSkip: {}, onSkipAndIgnore: {}
    )
    .padding()
}
#endif
