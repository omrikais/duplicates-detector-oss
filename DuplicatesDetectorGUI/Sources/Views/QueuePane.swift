import SwiftUI

// MARK: - Queue Pane

/// Left pane: scrollable list of pair or group queue rows with search and sort controls.
///
/// Keyboard navigation: List provides built-in arrow key selection.
/// Tab cycling and shortcut wiring are documented but not connected in this phase.
struct QueuePane: View {
    let store: SessionStore
    var selectedGroupID: Binding<Int?>?

    private var effectivePairMode: Bool {
        store.session.results?.effectivePairMode(for: store.session.display.viewMode) ?? true
    }

    var body: some View {
        VStack(spacing: 0) {
            queueToolbar
            Divider()

            if effectivePairMode {
                pairQueue
            } else {
                groupQueue
            }
        }
        .background(DDColors.surface1)
    }

    // MARK: - Toolbar

    private var queueToolbar: some View {
        VStack(spacing: DDSpacing.sm) {
            TextField("Filter\u{2026}", text: Binding(
                get: { store.session.display.searchText },
                set: { store.send(.setSearchText($0)) }
            ))
                .textFieldStyle(.roundedBorder)
                .font(DDTypography.metadata)

            Picker("Sort", selection: Binding(
                get: { store.session.display.sortOrder },
                set: { store.send(.setSortOrder($0)) }
            )) {
                ForEach(ResultSortOrder.allCases, id: \.self) { order in
                    Text(order.rawValue).tag(order)
                }
            }
            .pickerStyle(.menu)
            .font(DDTypography.label)
        }
        .padding(DDDensity.compact)
        .ddGlassChrome()
    }

    // MARK: - Pair Queue

    private var pairQueue: some View {
        List(selection: Binding(
            get: { store.selectedPairID },
            set: { store.send(.selectPair($0)) }
        )) {
            ForEach(store.filteredPairs, id: \.pairIdentifier) { pair in
                let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
                let resolution = store.session.results?.resolutionStatus(for: pairID) ?? .active
                HStack(spacing: DDSpacing.sm) {
                    if store.session.display.isSelectMode, case .active = resolution {
                        Toggle(isOn: Binding(
                            get: { store.session.display.selectedForAction.contains(pair.pairIdentifier) },
                            set: { _ in
                                store.send(.togglePairSelection(pair.pairIdentifier))
                            }
                        )) { EmptyView() }
                        .toggleStyle(.checkbox)
                        .labelsHidden()
                    }
                    PairQueueRow(pair: pair, resolution: resolution.asPairResolutionStatus)
                }
                .tag(pair.pairIdentifier)
            }
        }
        .listStyle(.inset(alternatesRowBackgrounds: true))
        .overlay {
            if store.filteredPairs.isEmpty {
                emptyState(entity: "pairs", emptyIcon: "checkmark.circle", emptyLabel: "No Duplicates Found")
            }
        }
    }

    @ViewBuilder
    private func emptyState(entity: String, emptyIcon: String, emptyLabel: String) -> some View {
        if store.session.display.directoryFilter != nil {
            ContentUnavailableView {
                Label("No Matches in Directory", systemImage: "folder.badge.questionmark")
            } description: {
                Text("No \(entity) match the active directory filter.")
            } actions: {
                Button("Clear Filter") { store.send(.setDirectoryFilter(nil)) }
            }
        } else if store.session.display.searchText.isEmpty {
            ContentUnavailableView {
                Label(emptyLabel, systemImage: emptyIcon)
            } description: {
                Text("No duplicate \(entity) were \(entity == "pairs" ? "detected in the scanned files" : "found").")
            } actions: {
                Button("New Scan") { store.send(.resetToSetup) }
            }
        } else {
            ContentUnavailableView {
                Label("No Matches", systemImage: "magnifyingglass")
            } description: {
                Text("No \(entity) match '\(store.session.display.searchText)'.")
            }
        }
    }

    // MARK: - Group Queue

    private var groupQueue: some View {
        List(selection: selectedGroupID) {
            ForEach(store.filteredGroups, id: \.groupId) { group in
                let isFullyResolved = store.isGroupFullyResolved(group)
                let resolvedCount = store.resolvedMemberCount(in: group)
                let totalCandidates = group.files.filter { $0.path != group.keep && !$0.isReference }.count
                HStack(spacing: DDSpacing.sm) {
                    if store.session.display.isSelectMode, !isFullyResolved {
                        Toggle(isOn: Binding(
                            get: { store.session.display.selectedGroupsForAction.contains(group.groupId) },
                            set: { _ in
                                store.send(.toggleGroupSelection(group.groupId))
                            }
                        )) { EmptyView() }
                        .toggleStyle(.checkbox)
                        .labelsHidden()
                    }
                    GroupQueueRow(
                        group: group,
                        isFullyResolved: isFullyResolved,
                        resolvedCount: resolvedCount,
                        totalCandidates: totalCandidates
                    )
                }
                .tag(group.groupId)
            }
        }
        .listStyle(.inset(alternatesRowBackgrounds: true))
        .overlay {
            if store.filteredGroups.isEmpty {
                emptyState(entity: "groups", emptyIcon: "rectangle.3.group", emptyLabel: "No Groups")
            }
        }
    }
}

// MARK: - Pair Queue Row

/// Compact queue row for a pair: thumbnail, score ring, filenames, breakdown bar.
struct PairQueueRow: View {
    let pair: PairResult
    var resolution: PairResolutionStatus = .active
    @Environment(\.ddColors) private var ddColors

    /// Build the accessibility label for a pair row. Exposed for unit testing.
    nonisolated static func accessibilityText(
        fileA: String, fileB: String, score: Double,
        resolution: PairResolutionStatus = .active
    ) -> String {
        let base = "\(fileA.fileName) versus \(fileB.fileName), score \(ScoreRing.formattedScore(score))"
        switch resolution {
        case .active:
            return base
        case .resolved:
            return "\(base), resolved"
        case .probablySolved:
            return "\(base), probably solved"
        }
    }

    private var isResolved: Bool {
        switch resolution {
        case .active: false
        case .resolved, .probablySolved: true
        }
    }

    private var resolutionBadge: (icon: String, color: Color)? {
        switch resolution {
        case .active: nil
        case .resolved: ("checkmark.circle.fill", DDColors.success)
        case .probablySolved: ("questionmark.circle.fill", DDColors.warning)
        }
    }

    private var resolvedBadgeText: String? {
        switch resolution {
        case .active: nil
        case .resolved: "Resolved"
        case .probablySolved: "Probably solved"
        }
    }

    var body: some View {
        HStack(spacing: DDSpacing.sm) {
            // Side-by-side thumbnails for File A and File B
            HStack(spacing: DDSpacing.xxs) {
                ThumbnailView(
                    path: pair.fileA,
                    base64: pair.fileAMetadata.thumbnail,
                    fixedWidth: DDSpacing.thumbnailMiniWidth, fixedHeight: DDSpacing.thumbnailMiniHeight,
                    modificationDate: pair.fileAMetadata.mtime.map { Date(timeIntervalSince1970: $0) }
                )
                ThumbnailView(
                    path: pair.fileB,
                    base64: pair.fileBMetadata.thumbnail,
                    fixedWidth: DDSpacing.thumbnailMiniWidth, fixedHeight: DDSpacing.thumbnailMiniHeight,
                    modificationDate: pair.fileBMetadata.mtime.map { Date(timeIntervalSince1970: $0) }
                )
            }

            ScoreRing(score: pair.score, size: .compact)

            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                Text(pair.fileA.displayFileName)
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)

                HStack(spacing: DDSpacing.xs) {
                    Text("vs")
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textMuted)
                    Text(pair.fileB.displayFileName)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }

                if !pair.breakdown.isEmpty {
                    BreakdownBar(
                        breakdown: pair.breakdown,
                        detail: pair.detail,
                        totalScore: pair.score
                    )
                    .padding(.top, DDSpacing.hairline)
                }
            }

            Spacer(minLength: DDSpacing.xs)

            // Indicators
            VStack(alignment: .trailing, spacing: DDSpacing.xs) {
                if let badge = resolutionBadge {
                    Image(systemName: badge.icon)
                        .font(DDTypography.label)
                        .foregroundStyle(badge.color)
                        .padding(DDSpacing.xs)
                        .glassEffect(.regular.tint(badge.color.opacity(0.2)), in: .circle)
                } else {
                    FileBadges(isKeep: pair.keep != nil, isReference: pair.fileAIsReference || pair.fileBIsReference)
                }
                Text(DDFormatters.formatFileSize(pairRecoverableSize))
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }
        }
        .padding(.vertical, DDSpacing.xs)
        .opacity(isResolved ? 0.5 : 1.0)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Self.accessibilityText(
            fileA: pair.fileA, fileB: pair.fileB, score: pair.score, resolution: resolution
        ))
        .accessibilityHint("Double tap to review this pair")
    }

    /// Recoverable space respecting reference files and keep recommendation.
    private var pairRecoverableSize: Int {
        let aRef = pair.fileAIsReference
        let bRef = pair.fileBIsReference
        if aRef && bRef { return 0 }
        if aRef { return pair.fileBMetadata.fileSize }
        if bRef { return pair.fileAMetadata.fileSize }
        // Respect the keep recommendation when present.
        if let keepPath = pair.keepPath {
            if keepPath == pair.fileA { return pair.fileBMetadata.fileSize }
            if keepPath == pair.fileB { return pair.fileAMetadata.fileSize }
        }
        return min(pair.fileAMetadata.fileSize, pair.fileBMetadata.fileSize)
    }

}

// MARK: - Group Queue Row

/// Compact queue row for a group: thumbnail of first file, score ring, group stats.
struct GroupQueueRow: View {
    let group: GroupResult
    var isFullyResolved: Bool = false
    var resolvedCount: Int = 0
    var totalCandidates: Int = 0
    @Environment(\.ddColors) private var ddColors

    /// Build the accessibility label for a group row. Exposed for unit testing.
    nonisolated static func accessibilityText(
        groupId: Int, fileCount: Int, minScore: Double, maxScore: Double,
        isFullyResolved: Bool = false, resolvedCount: Int = 0, totalCandidates: Int = 0
    ) -> String {
        let base = "Group \(groupId), \(fileCount) file\(fileCount == 1 ? "" : "s"), score \(ScoreRing.formattedScore(minScore)) to \(ScoreRing.formattedScore(maxScore))"
        if isFullyResolved {
            return "\(base), fully resolved"
        }
        if resolvedCount > 0 {
            return "\(base), \(resolvedCount) of \(totalCandidates) resolved"
        }
        return base
    }

    var body: some View {
        HStack(spacing: DDSpacing.sm) {
            // Thumbnail of first file
            ThumbnailView(
                path: group.files.first?.path,
                base64: group.files.first?.thumbnail,
                fixedWidth: DDSpacing.thumbnailCompactWidth, fixedHeight: DDSpacing.thumbnailCompactHeight,
                modificationDate: group.files.first?.mtime.map { Date(timeIntervalSince1970: $0) }
            )

            ScoreRing(score: group.maxScore, size: .compact)

            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                Text("Group \(group.groupId)")
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textPrimary)

                Text("\(group.fileCount) files  \u{00B7}  \(String(format: "%.0f", group.minScore))\u{2013}\(String(format: "%.0f", group.maxScore))")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)

                if !isFullyResolved && resolvedCount > 0 {
                    Text("\(resolvedCount)/\(totalCandidates) resolved")
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textMuted)
                }
            }

            Spacer(minLength: DDSpacing.xs)

            VStack(alignment: .trailing, spacing: DDSpacing.xs) {
                if isFullyResolved {
                    Image(systemName: "checkmark.circle.fill")
                        .font(DDTypography.label)
                        .foregroundStyle(DDColors.success)
                        .padding(DDSpacing.xs)
                        .glassEffect(.regular.tint(DDColors.success.opacity(0.2)), in: .circle)
                } else {
                    FileBadges(isKeep: group.keep != nil, isReference: false)
                }
                Text(DDFormatters.formatFileSize(groupRecoverableSize))
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }
        }
        .padding(.vertical, DDSpacing.xs)
        .opacity(isFullyResolved ? 0.5 : 1.0)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Self.accessibilityText(
            groupId: group.groupId, fileCount: group.fileCount,
            minScore: group.minScore, maxScore: group.maxScore,
            isFullyResolved: isFullyResolved, resolvedCount: resolvedCount,
            totalCandidates: totalCandidates
        ))
        .accessibilityHint("Double tap to review this group")
    }

    /// Size of non-keep, non-reference files (recoverable space).
    /// When no explicit keeper is set and no reference file serves as
    /// the kept item, reserves the largest non-reference file as an
    /// implicit keeper so the badge doesn't overstate savings.
    private var groupRecoverableSize: Int {
        let deletable = group.files.filter { $0.path != group.keep && !$0.isReference }
        let total = deletable.reduce(0) { $0 + $1.fileSize }
        let hasReferenceKeeper = group.files.contains(where: \.isReference)
        if group.keep == nil && !hasReferenceKeeper,
           let implicitKeep = deletable.max(by: { $0.fileSize < $1.fileSize }) {
            return total - implicitKeep.fileSize
        }
        return total
    }
}

// MARK: - Previews
//
// QueuePane uses List (backed by NSOutlineView on macOS), which crashes in
// Xcode preview windows during key-view-loop setup. Previewing individual
// rows and the toolbar avoids this while still covering visual appearance.

#if DEBUG
#Preview("Pair Queue Rows") {
    let pairs = PreviewFixtures.samplePairResults
    ScrollView {
        VStack(spacing: 0) {
            ForEach(pairs, id: \.pairIdentifier) { pair in
                PairQueueRow(pair: pair)
                    .padding(.horizontal, DDSpacing.sm)
                Divider()
            }
        }
    }
    .frame(width: 300, height: 300)
    .background(DDColors.surface1)
}

#Preview("Group Queue Rows") {
    let groups = PreviewFixtures.sampleGroupResults
    ScrollView {
        VStack(spacing: 0) {
            ForEach(groups, id: \.groupId) { group in
                GroupQueueRow(group: group)
                    .padding(.horizontal, DDSpacing.sm)
                Divider()
            }
        }
    }
    .frame(width: 300, height: 200)
    .background(DDColors.surface1)
}

#Preview("Queue -- Empty State") {
    ContentUnavailableView {
        Label("No Duplicates Found", systemImage: "checkmark.circle")
    } description: {
        Text("No duplicate pairs were detected in the scanned files.")
    } actions: {
        Button("New Scan") {}
    }
    .frame(width: 300, height: 300)
    .background(DDColors.surface1)
}
#endif
