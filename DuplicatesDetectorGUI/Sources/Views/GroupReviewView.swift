import SwiftUI

// MARK: - Group Review View

/// Center pane for group mode: filmstrip of member thumbnails with keep/reference
/// badges, and pair relationship list below showing scores and breakdown bars.
struct GroupReviewView: View {
    let group: GroupResult
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Binding var selectedMemberPath: String?
    var actionedPaths: Set<String> = []
    var resolvedPaths: Set<String> = []
    var activeAction: ActionType = .trash
    var currentIndex: Int?
    var totalGroups: Int = 0
    var onAction: ((String) -> Void)?
    var onPrevious: (() -> Void)?
    var onSkip: (() -> Void)?
    @FocusState private var focusedTileIndex: Int?

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: DDSpacing.lg) {
                    groupHeader
                    filmstrip
                    pairRelationships
                }
                .padding(DDDensity.regular)
            }

            if onAction != nil {
                GroupActionBar(
                    group: group,
                    selectedMemberPath: selectedMemberPath,
                    actionedPaths: actionedPaths,
                    resolvedPaths: resolvedPaths,
                    activeAction: activeAction,
                    currentIndex: currentIndex,
                    totalGroups: totalGroups,
                    onAction: { path in onAction?(path) },
                    onPrevious: onPrevious,
                    onSkip: { onSkip?() }
                )
            }
        }
        .background(DDColors.surface1)
    }

    // MARK: - Group Header

    private var groupHeader: some View {
        HStack(spacing: DDSpacing.md) {
            ScoreRing(score: group.maxScore, size: .regular)

            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                Text("Group \(group.groupId)")
                    .font(DDTypography.heading)
                    .foregroundStyle(ddColors.textPrimary)

                Text("\(group.fileCount) files  \u{00B7}  score \(String(format: "%.0f", group.minScore))\u{2013}\(String(format: "%.0f", group.maxScore))  \u{00B7}  avg \(String(format: "%.0f", group.avgScore))")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
            }

            Spacer()

            if let keep = group.keep {
                FileBadges(isKeep: true, isReference: false,
                           style: .label(keepText: "Keep: \(keep.fileName)", referenceText: ""))
            }
        }
    }

    // MARK: - Filmstrip

    private var filmstrip: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Members")
                .font(DDTypography.sectionTitle)
                .foregroundStyle(ddColors.textPrimary)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: DDSpacing.md) {
                    ForEach(Array(group.files.enumerated()), id: \.element.path) { index, file in
                        let isActioned = actionedPaths.contains(file.path) || resolvedPaths.contains(file.path)
                        Button {
                            withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                                selectedMemberPath = file.path
                            }
                        } label: {
                            FilmstripTile(
                                file: file,
                                isKeep: group.keep == file.path,
                                isSelected: selectedMemberPath == file.path,
                                isActioned: isActioned
                            )
                        }
                        .buttonStyle(.plain)
                        .disabled(isActioned)
                        .focusable()
                        .focused($focusedTileIndex, equals: index)
                        .ddFocusRing(focusedTileIndex == index)
                        .accessibilityLabel(file.path.fileName)
                        .accessibilityAddTraits(selectedMemberPath == file.path ? .isSelected : [])
                        .accessibilityHint("Double tap to select for comparison")
                    }
                }
                .padding(.vertical, DDSpacing.xs)
                .onKeyPress(.leftArrow) {
                    guard let current = focusedTileIndex else { return .ignored }
                    if let next = nextActionableIndex(from: current, direction: -1) {
                        focusedTileIndex = next
                        return .handled
                    }
                    return .ignored
                }
                .onKeyPress(.rightArrow) {
                    guard let current = focusedTileIndex else { return .ignored }
                    if let next = nextActionableIndex(from: current, direction: 1) {
                        focusedTileIndex = next
                        return .handled
                    }
                    return .ignored
                }
                .onKeyPress(.return) {
                    guard let index = focusedTileIndex, index < group.files.count else { return .ignored }
                    let file = group.files[index]
                    let isActioned = actionedPaths.contains(file.path) || resolvedPaths.contains(file.path)
                    guard !isActioned else { return .ignored }
                    withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                        selectedMemberPath = file.path
                    }
                    return .handled
                }
            }
        }
    }

    private func nextActionableIndex(from current: Int, direction: Int) -> Int? {
        var candidate = current + direction
        while candidate >= 0 && candidate < group.files.count {
            let path = group.files[candidate].path
            if !actionedPaths.contains(path) && !resolvedPaths.contains(path) {
                return candidate
            }
            candidate += direction
        }
        return nil
    }

    // MARK: - Pair Relationships

    /// Aggregates weighted contributions across all pairs and returns a rationale string.
    private var groupRationale: String? {
        guard !group.pairs.isEmpty else { return nil }
        var contributions: [String: Double] = [:]
        for pair in group.pairs {
            for (key, detail) in pair.detail {
                contributions[key, default: 0] += detail.raw * detail.weight
            }
        }
        let count = Double(group.pairs.count)
        let averaged = contributions.mapValues { $0 / count }
        let top = averaged.sorted { $0.value > $1.value }.prefix(2)
        guard top.first != nil else { return nil }
        let parts = top.map { "\(DDComparators.displayName(for: $0.key)) (\(String(format: "%.0f", $0.value))%)" }
        return "Grouped by \(parts.joined(separator: " and "))"
    }

    private var pairRelationships: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            if let rationale = groupRationale {
                Text(rationale)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
            }

            Text("Pair Relationships")
                .font(DDTypography.sectionTitle)
                .foregroundStyle(ddColors.textPrimary)

            LazyVStack(alignment: .leading, spacing: DDSpacing.md) {
                ForEach(group.pairs) { pair in
                    PairRelationshipRow(pair: pair)
                }
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

}

// MARK: - Group Action Bar

/// Horizontal action bar for group review: action button for the selected member + skip.
struct GroupActionBar: View {
    let group: GroupResult
    @Environment(\.ddColors) private var ddColors
    let selectedMemberPath: String?
    var actionedPaths: Set<String> = []
    var resolvedPaths: Set<String> = []
    let activeAction: ActionType
    let currentIndex: Int?
    let totalGroups: Int
    var onAction: (String) -> Void
    var onPrevious: (() -> Void)?
    var onSkip: () -> Void

    /// Build the group counter accessibility label. Exposed for unit testing.
    nonisolated static func groupCounterAccessibilityText(index: Int, total: Int) -> String {
        "Group \(index + 1) of \(total)"
    }

    private var selectedFile: GroupFile? {
        guard let path = selectedMemberPath else { return nil }
        return group.files.first { $0.path == path }
    }

    private var isProtected: Bool {
        guard let file = selectedFile else { return true }
        return group.keep == file.path || file.isReference
    }

    private var isActionCLIOnly: Bool {
        activeAction == .hardlink || activeAction == .symlink || activeAction == .reflink
    }

    private var isActioned: Bool {
        guard let path = selectedMemberPath else { return false }
        return actionedPaths.contains(path) || resolvedPaths.contains(path)
    }

    var body: some View {
        HStack(spacing: DDSpacing.md) {
            groupCounter

            Spacer()

            if isActionCLIOnly {
                Label("File actions for this mode are CLI-only",
                      systemImage: "terminal")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
            } else {
                actionButton
            }

            previousGroupButton
            skipButton
        }
        .padding(DDDensity.compact)
        .ddGlassChrome()
    }

    @ViewBuilder
    private var previousGroupButton: some View {
        if let onPrevious {
            Button { onPrevious() } label: {
                Label("Previous Group", systemImage: "arrow.up.circle")
            }
            .controlSize(.regular)
            .disabled(currentIndex == 0)
            .help("Return to the previous group")
        }
    }

    @ViewBuilder
    private var groupCounter: some View {
        if let index = currentIndex {
            Text("\(index + 1) of \(totalGroups)")
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textSecondary)
                .accessibilityLabel(Self.groupCounterAccessibilityText(index: index, total: totalGroups))
        }
    }

    @ViewBuilder
    private var actionButton: some View {
        if let file = selectedFile {
            Button { onAction(file.path) } label: {
                VStack(spacing: DDSpacing.xxs) {
                    Label("\(activeAction.displayName) Selected",
                          systemImage: activeAction == .trash ? "trash" : activeAction == .delete ? "trash.slash" : "folder.badge.plus")
                    Text(file.path.fileName)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textMuted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
            .controlSize(.regular)
            .disabled(isProtected || isActioned || isActionCLIOnly)
            .tint(activeAction == .delete ? DDColors.destructive : nil)
            .help(isProtected
                  ? (group.keep == file.path ? "Cannot act on the keep file" : "Cannot act on a reference file")
                  : isActioned
                  ? "Already actioned"
                  : "\(activeAction.displayName) \(file.path.fileName)")
        }
    }

    private var skipButton: some View {
        Button { onSkip() } label: {
            Label("Next Group", systemImage: "arrow.down.circle")
        }
        .controlSize(.regular)
        .disabled(currentIndex != nil && currentIndex! >= totalGroups - 1)
        .help("Advance to the next group")
    }
}

// MARK: - Filmstrip Tile

/// Single tile in the filmstrip: thumbnail with badges and basename label.
private struct FilmstripTile: View {
    let file: GroupFile
    @Environment(\.ddColors) private var ddColors
    let isKeep: Bool
    let isSelected: Bool
    var isActioned: Bool = false

    var body: some View {
        VStack(spacing: DDSpacing.sm) {
            ZStack(alignment: .topLeading) {
                ThumbnailView(
                    path: file.path,
                    base64: file.thumbnail,
                    fixedWidth: DDSpacing.filmstripTileWidth, fixedHeight: DDSpacing.filmstripTileHeight,
                    modificationDate: file.mtime.map { Date(timeIntervalSince1970: $0) }
                )

                HStack(spacing: DDSpacing.xs) {
                    if isActioned {
                        Image(systemName: "checkmark.circle.fill")
                            .font(DDTypography.label)
                            .foregroundStyle(DDColors.success)
                            .padding(DDSpacing.xs)
                            .background(DDColors.surface0.opacity(0.7), in: Circle())
                    }
                    FileBadges(isKeep: isKeep, isReference: file.isReference, style: .overlay)
                }
                .padding(DDSpacing.xs)
            }

            Text(file.path.fileName)
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textSecondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(width: DDSpacing.filmstripTileWidth)

            Text(DDFormatters.formatFileSize(file.fileSize))
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
        }
        .padding(DDSpacing.sm)
        .opacity(isActioned ? 0.4 : 1.0)
        .background(
            isSelected ? DDColors.selection : .clear,
            in: RoundedRectangle(cornerRadius: DDRadius.medium)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DDRadius.medium)
                .strokeBorder(
                    isSelected ? DDColors.accent : .clear,
                    lineWidth: DDSpacing.selectionStroke
                )
        )
    }
}

// MARK: - Pair Relationship Row

/// Shows a pair relationship: fileA ← score → fileB with breakdown bar.
private struct PairRelationshipRow: View {
    let pair: GroupPair
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            HStack(spacing: DDSpacing.sm) {
                Text(pair.fileA.fileName)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .frame(maxWidth: .infinity, alignment: .trailing)

                ScoreRing(score: pair.score, size: .compact)

                Text(pair.fileB.fileName)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            BreakdownBar(
                breakdown: pair.breakdown,
                detail: pair.detail,
                totalScore: pair.score
            )
        }
    }
}

#if DEBUG
private struct GroupReviewPreviewHost: View {
    @State private var selectedMemberPath: String?

    var body: some View {
        let groups = PreviewFixtures.sampleGroupResults
        let group = groups[0]
        GroupReviewView(group: group, selectedMemberPath: $selectedMemberPath)
    }
}

#Preview("Group Review — 3 Files") {
    GroupReviewPreviewHost()
        .frame(width: 700, height: 600)
}

private struct GroupReviewSelectedPreviewHost: View {
    @State private var selectedMemberPath: String? = "/Users/demo/Videos/vacation_2024_copy.mp4"

    var body: some View {
        let groups = PreviewFixtures.sampleGroupResults
        let group = groups[0]
        GroupReviewView(group: group, selectedMemberPath: $selectedMemberPath)
    }
}

#Preview("Group Review — Selected Member") {
    GroupReviewSelectedPreviewHost()
        .frame(width: 700, height: 600)
}

private struct GroupReviewActionBarPreviewHost: View {
    @State private var selectedMemberPath: String? = "/Users/demo/Videos/vacation_2024_copy.mp4"

    var body: some View {
        let groups = PreviewFixtures.sampleGroupResults
        let group = groups[0]
        GroupReviewView(
            group: group, selectedMemberPath: $selectedMemberPath,
            activeAction: .trash, currentIndex: 0, totalGroups: 3,
            onAction: { _ in }, onSkip: {}
        )
    }
}

#Preview("Group Review — Action Bar") {
    GroupReviewActionBarPreviewHost()
        .frame(width: 700, height: 600)
}

private struct GroupReviewSmallPreviewHost: View {
    @State private var selectedMemberPath: String?

    var body: some View {
        let groups = PreviewFixtures.sampleGroupResults
        let group = groups[1]
        GroupReviewView(group: group, selectedMemberPath: $selectedMemberPath)
    }
}

#Preview("Group Review — 2 Files") {
    GroupReviewSmallPreviewHost()
        .frame(width: 700, height: 600)
}
#endif
