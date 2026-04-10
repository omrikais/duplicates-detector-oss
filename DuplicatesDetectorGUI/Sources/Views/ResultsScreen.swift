import SwiftUI
import UniformTypeIdentifiers

/// Focus target for tab cycling between panes.
private enum FocusedPane: Hashable {
    case queue
    case comparison
    case inspector
}

enum ResultsBulkActionConfirmationCopy {
    private static func filePhrase(_ count: Int) -> String {
        count == 1 ? "1 file" : "\(count) files"
    }

    static func message(for action: ActionType, count: Int, destinationName: String?) -> String {
        switch action {
        case .trash:
            return "The selected \(filePhrase(count)) will be moved to the macOS Trash. You can undo this from Finder."
        case .delete:
            return "The selected \(filePhrase(count)) will be permanently deleted. This cannot be undone."
        case .moveTo:
            let destination = destinationName ?? "selected directory"
            return "The selected \(filePhrase(count)) will be moved to \"\(destination)\". Originals will be removed."
        case .hardlink, .symlink, .reflink:
            return ""
        }
    }

    static func confirmButtonTitle(for action: ActionType, count: Int) -> String? {
        switch action {
        case .trash:
            return "Trash \(filePhrase(count).capitalized)"
        case .delete:
            return "Delete \(filePhrase(count).capitalized) Permanently"
        case .moveTo:
            return "Move \(filePhrase(count).capitalized)"
        case .hardlink, .symlink, .reflink:
            return nil
        }
    }
}

struct ResultsSingleDeleteConfirmationState {
    struct PendingAction {
        let title: String
        let message: String
        let confirmButtonTitle: String
        private let performAction: () -> Void

        init(
            title: String = "Permanently Delete File?",
            message: String = "This action cannot be undone.",
            confirmButtonTitle: String = "Delete Permanently",
            performAction: @escaping () -> Void
        ) {
            self.title = title
            self.message = message
            self.confirmButtonTitle = confirmButtonTitle
            self.performAction = performAction
        }

        func perform() {
            performAction()
        }
    }

    private(set) var pendingAction: PendingAction?

    var isPresented: Bool {
        pendingAction != nil
    }

    mutating func present(
        title: String = "Permanently Delete File?",
        message: String = "This action cannot be undone.",
        confirmButtonTitle: String = "Delete Permanently",
        performAction: @escaping () -> Void
    ) {
        pendingAction = PendingAction(
            title: title,
            message: message,
            confirmButtonTitle: confirmButtonTitle,
            performAction: performAction
        )
    }

    mutating func routeInspectorAction(_ action: PairAction, execute: @escaping (PairAction) -> Void) {
        if let confirmation = ResultsScreen.confirmationCopy(for: action) {
            present(
                title: confirmation.title,
                message: confirmation.message,
                confirmButtonTitle: confirmation.button,
                performAction: { execute(action) }
            )
        } else {
            execute(action)
        }
    }

    mutating func confirm() {
        let pendingAction = self.pendingAction
        self.pendingAction = nil
        pendingAction?.perform()
    }

    mutating func cancel() {
        pendingAction = nil
    }
}

/// Results display: three-pane review desk with queue, comparison surface, and inspector.
struct ResultsScreen: View {
    let store: SessionStore
    var showsToolbar: Bool = true
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    // Convenience accessors
    private var results: ResultsSnapshot? { store.session.results }
    private var display: DisplayState { store.session.display }

    private var effectivePairMode: Bool {
        results?.effectivePairMode(for: display.viewMode) ?? true
    }

    private var isPhotosLibraryScan: Bool {
        store.session.metadata.sourceLabel == SessionMetadata.photosLibraryLabel
    }

    @State private var selectedGroupID: Int?
    @State private var selectedMemberPath: String?
    /// Tracks file paths in the selected group for stable identity across synthesized-group rebuilds.
    @State private var currentGroupSiblingPaths: Set<String> = []
    @State private var showInspector: Bool = true
    @State private var showBulkActionConfirmation = false
    @State private var singleDeleteConfirmation = ResultsSingleDeleteConfirmationState()
    @State private var confirmPermanentDelete = false
    @State private var showMoveDestinationPicker = false
    @AppStorage("lastMoveDestination") private var lastMoveDestination: String = ""
    @State private var showUndoScript = false
    @State private var undoScriptContent: String = ""
    @State private var isGeneratingUndo = false
    @State private var showActionLog = false
    @State private var showIgnoreList = false
    @State private var showRefineSheet = false
    @State private var isExporting = false
    @State private var exportError: String?
    @State private var isShowingCopySummaryFeedback = false
    @State private var copySummaryFeedbackTask: Task<Void, Never>?
    @State private var sessionEntries: [SessionRegistry.Entry] = []
    @State private var bothRefSkipTask: Task<Void, Never>?
    /// When true, both-reference pairs are auto-skipped after 1500ms.
    /// False during manual backward navigation so the user can inspect these pairs.
    @State private var autoSkipBothRef = true
    @FocusState private var focusedPane: FocusedPane?

    /// True when any modal (sheet, dialog, alert, file picker, or overlay) is presented.
    private var hasActiveModal: Bool {
        showUndoScript || showActionLog || showIgnoreList || showRefineSheet
            || showBulkActionConfirmation || singleDeleteConfirmation.isPresented
            || showMoveDestinationPicker
            || (results?.pairErrors.isEmpty == false) || isExporting || exportError != nil
    }

    /// The first pair error message, if any.
    private var firstPairError: String? {
        results?.pairErrors.values.first?.message
    }

    var body: some View {
        let bulkCandidates = store.bulkActionCandidates()
        reviewDesk
            .focusedSceneValue(\.isReviewActive, !hasActiveModal)
            .focusedSceneValue(\.isGroupMode, display.viewMode == .groups && !hasActiveModal)
            .confirmationDialog(
                bulkActionConfirmationTitle(bulkCandidates),
                isPresented: $showBulkActionConfirmation,
                titleVisibility: .visible
            ) {
                bulkActionConfirmationButtons(bulkCandidates)
            } message: {
                Text(bulkActionConfirmationMessage(bulkCandidates))
            }
            .onChange(of: showBulkActionConfirmation) { _, isPresented in
                if !isPresented {
                    confirmPermanentDelete = false
                }
            }
            .alert("Action Failed", isPresented: Binding(
                get: { firstPairError != nil },
                set: { if !$0 { clearFirstPairError() } }
            )) {
                Button("OK") { clearFirstPairError() }
            } message: {
                Text(firstPairError ?? "")
            }
            .fileImporter(
                isPresented: $showMoveDestinationPicker,
                allowedContentTypes: [.folder],
                allowsMultipleSelection: false
            ) { result in
                if case .success(let urls) = result, let url = urls.first {
                    lastMoveDestination = url.path
                    store.send(.setMoveDestination(url))
                    showBulkActionConfirmation = true
                }
            }
            .confirmationDialog(
                singleDeleteConfirmation.pendingAction?.title ?? "Permanently Delete File?",
                isPresented: Binding(
                    get: { singleDeleteConfirmation.isPresented },
                    set: { if !$0 { singleDeleteConfirmation.cancel() } }
                ),
                titleVisibility: .visible
            ) {
                Button(singleDeleteConfirmation.pendingAction?.confirmButtonTitle ?? "Delete Permanently",
                       role: .destructive) {
                    singleDeleteConfirmation.confirm()
                }
                Button("Cancel", role: .cancel) {
                    singleDeleteConfirmation.cancel()
                }
            } message: {
                Text(singleDeleteConfirmation.pendingAction?.message ?? "This action cannot be undone.")
            }
            .sheet(isPresented: $showUndoScript) {
                UndoScriptSheet(content: undoScriptContent)
                    .presentationBackground(.ultraThinMaterial)
            }
            .sheet(isPresented: $showActionLog) {
                if let logPath = store.session.lastScanConfig?.log {
                    ActionLogView(logPath: logPath)
                        .presentationBackground(.ultraThinMaterial)
                }
            }
            .sheet(isPresented: $showIgnoreList) {
                IgnoreListView(
                    ignoreFilePath: store.ignoreFilePath,
                    onPairRemoved: { fileA, fileB in
                        store.send(.unignorePair(fileA, fileB))
                    },
                    onAllCleared: {
                        store.send(.clearIgnoredPairs)
                    }
                )
                .presentationBackground(.ultraThinMaterial)
            }
            .sheet(isPresented: $showRefineSheet) {
                RefineResultsSheet(store: store)
                    .presentationBackground(.ultraThinMaterial)
            }
            .overlay {
                if isExporting {
                    ZStack {
                        Color.clear.background(.ultraThinMaterial)
                        VStack(spacing: DDSpacing.md) {
                            ProgressView()
                                .controlSize(.large)
                            Text("Exporting\u{2026}")
                                .font(DDTypography.body)
                                .foregroundStyle(ddColors.textPrimary)
                        }
                        .padding(DDSpacing.xl)
                        .ddGlassCard()
                    }
                }
            }
            .alert("Export Error", isPresented: Binding(
                get: { exportError != nil || store.lastExportError != nil },
                set: { if !$0 { exportError = nil; store.lastExportError = nil } }
            )) {
                Button("OK") { exportError = nil; store.lastExportError = nil }
            } message: {
                Text(exportError ?? store.lastExportError ?? "")
            }
            .onDisappear {
                resetCopySummaryFeedback()
                bothRefSkipTask?.cancel()
            }
    }

    /// Clear the first pair error.
    private func clearFirstPairError() {
        store.clearFirstPairError()
    }

    // MARK: - Review Desk (main content + toolbar + keyboard)

    private var reviewDesk: some View {
        reviewDeskWithKeyboard
            .onChange(of: selectedGroupID) { _, newID in
                guard let newID,
                      let group = store.filteredGroups.first(where: { $0.groupId == newID }) else { return }
                selectedMemberPath = preferredMember(in: group)
                currentGroupSiblingPaths = Set(group.files.map(\.path))
            }
            .onChange(of: display.viewMode) { _, newMode in handleViewModeChange(newMode) }
            .onChange(of: display.searchText) { _, _ in revalidateSelection(searchChanged: true) }
            .onChange(of: display.sortOrder) { _, _ in revalidateSelection(searchChanged: false) }
            .onChange(of: display.directoryFilter) { _, _ in revalidateSelection(searchChanged: true) }
            .onChange(of: results?.actionedPaths) { _, _ in revalidateAfterAction() }
            .onChange(of: results?.ignoredPairs) { _, _ in revalidateAfterAction() }
            .onChange(of: store.selectedPairID) { _, newID in
                // Auto-skip both-reference pairs after a brief delay, but only
                // during forward sequential review -- not on manual back-navigation
                // or queue clicks, so the user can still inspect these pairs.
                bothRefSkipTask?.cancel()

                // Queue-driven selection (clicking a row) is manual navigation.
                let isManual = !autoSkipBothRef || focusedPane == .queue
                autoSkipBothRef = true  // reset for the next navigation

                guard !isManual,
                      let newID,
                      let pair = store.filteredPairs.first(where: { $0.pairIdentifier == newID }),
                      pair.fileAIsReference && pair.fileBIsReference else { return }
                bothRefSkipTask = Task {
                    try? await Task.sleep(for: .milliseconds(1500))
                    guard !Task.isCancelled else { return }
                    store.send(.skipPair)
                }
            }
            .onAppear { handleOnAppear() }
            .onChange(of: store.lastMenuCommand?.seq) { _, _ in
                guard let cmd = store.lastMenuCommand else { return }
                guard !hasActiveModal, !display.showInsights else { return }
                switch cmd.command {
                case .keepA:
                    focusedPane = .comparison
                    _ = handleComparisonKeyPress(.keepA)
                case .keepB:
                    focusedPane = .comparison
                    _ = handleComparisonKeyPress(.keepB)
                case .skip:
                    focusedPane = .comparison
                    _ = handleComparisonKeyPress(.skipNext)
                case .previous:
                    focusedPane = .comparison
                    _ = handleComparisonKeyPress(.skipPrev)
                case .ignore:
                    focusedPane = .comparison
                    _ = handleComparisonKeyPress(.ignore)
                case .actionMember:
                    focusedPane = .comparison
                    _ = handleComparisonKeyPress(.actionMember)
                case .focusQueue:
                    focusedPane = .queue
                }
            }
    }

    private var reviewDeskWithKeyboard: some View {
        reviewDeskWithToolbar
            .background {
                Group {
                    Button("Quick Look") { handleQuickLook() }
                        .keyboardShortcut(.space, modifiers: [])
                    Button("Reveal in Finder") { handleReveal() }
                        .keyboardShortcut(.return, modifiers: .command)
                }
                .frame(width: 0, height: 0)
                .opacity(0)
            }
            .onKeyPress(.tab) {
                switch focusedPane {
                case .queue: focusedPane = .comparison
                case .comparison: focusedPane = showInspector ? .inspector : .queue
                case .inspector: focusedPane = .queue
                case nil: focusedPane = .queue
                }
                return .handled
            }
            .onKeyPress(.leftArrow) { handleComparisonKeyPress(.keepA) }
            .onKeyPress(.rightArrow) { handleComparisonKeyPress(.keepB) }
            .onKeyPress(.downArrow) { handleComparisonKeyPress(.skipNext) }
            .onKeyPress(.upArrow) { handleComparisonKeyPress(.skipPrev) }
            .onKeyPress(.escape) {
                guard focusedPane == .comparison else { return .ignored }
                return handleComparisonKeyPress(.focusQueue)
            }
            .onKeyPress(characters: CharacterSet(charactersIn: "i")) { _ in
                handleComparisonKeyPress(.ignore)
            }
            .onKeyPress(.delete) { handleComparisonKeyPress(.actionMember) }
    }

    private var reviewDeskWithToolbar: some View {
        reviewDeskContent
            .toolbar {
                if showsToolbar {
                    ToolbarItem(placement: .navigation) {
                        Button { store.send(.resetToSetup) } label: {
                            Label("New Scan", systemImage: "arrow.left")
                        }
                    }
                    ToolbarItem(placement: .automatic) {
                        Menu {
                            Button(isShowingCopySummaryFeedback ? "Copied!" : "Copy Summary") {
                                handleCopySummary()
                            }
                            .disabled(isShowingCopySummaryFeedback)
                            Divider()
                            Button("Save as JSON\u{2026}") { exportJSON() }
                                .disabled(store.session.results == nil)
                            Button("Export as CSV\u{2026}") { store.exportCSV() }
                            // HTML and shell exports use CLI --replay which can't handle photos:// URIs
                            if !isPhotosLibraryScan {
                                Button("Export as HTML Report\u{2026}") { exportViaReplay(format: .html) }
                                    .disabled(store.session.results == nil)
                                Button("Export as Shell Script\u{2026}") { exportViaReplay(format: .shell) }
                                    .disabled(store.session.results == nil)
                            }
                        } label: {
                            Label("Export", systemImage: "square.and.arrow.up")
                        }
                        .disabled(results?.bulkProgress != nil)
                        .accessibilityIdentifier("exportMenu")
                        .accessibilityHint("Export results in various formats")
                    }
                    // Refine uses CLI --replay which can't handle photos:// URIs
                    if !isPhotosLibraryScan {
                        ToolbarItem(placement: .automatic) {
                            Button { showRefineSheet = true } label: {
                                Label("Refine Results", systemImage: "slider.horizontal.3")
                            }
                            .disabled(store.session.results == nil
                                      || results?.bulkProgress != nil)
                            .help("Re-process results with different settings")
                            .accessibilityHint("Adjust threshold, weights, or filters and re-process results")
                        }
                    }
                    ToolbarItem(placement: .automatic) {
                        Button { showIgnoreList = true } label: {
                            Label("Ignored Pairs", systemImage: "eye.slash")
                        }
                        .badge(results?.uniqueIgnoredPairCount ?? 0)
                    }
                    if results?.canToggleViewMode(for: display.viewMode) ?? false {
                        ToolbarItem(placement: .automatic) {
                            Picker("View", selection: Binding(
                                get: { display.viewMode },
                                set: { store.send(.setViewMode($0)) }
                            )) {
                                ForEach(DisplayState.ViewMode.allCases, id: \.self) { mode in
                                    Text(mode.rawValue).tag(mode)
                                }
                            }
                            .pickerStyle(.segmented)
                            .frame(width: 140)
                        }
                    }
                    ToolbarItem(placement: .automatic) {
                        Toggle(isOn: Binding(
                            get: { display.isSelectMode },
                            set: { _ in store.send(.toggleSelectMode) }
                        )) {
                            Label("Select", systemImage: "checkmark.circle")
                        }
                        .toggleStyle(.button)
                    }
                    if display.isSelectMode {
                        ToolbarItem(placement: .automatic) {
                            Menu {
                                Button("Select All") { store.send(.selectAll) }
                                Button("Deselect All") { store.send(.deselectAll) }
                            } label: {
                                Label("Selection", systemImage: "checklist")
                            }
                        }
                    }
                    ToolbarItem(placement: .automatic) {
                        bulkActionToolbarButton
                    }
                    if store.session.lastScanConfig?.log != nil {
                        ToolbarItem(placement: .automatic) {
                            Menu {
                                Button {
                                    Task {
                                        await store.flushActionLog()
                                        showActionLog = true
                                    }
                                } label: {
                                    Label("View Action Log", systemImage: "doc.text.magnifyingglass")
                                }
                                Button {
                                    generateUndoScript()
                                } label: {
                                    Label("Generate Undo Script", systemImage: "arrow.uturn.backward.circle")
                                }
                                .disabled(isGeneratingUndo || !logFileExists)
                            } label: {
                                Label("Log", systemImage: "doc.text")
                            }
                        }
                    }
                    ToolbarItemGroup(placement: .automatic) {
                        if results?.analyticsData != nil {
                            Button {
                                withAnimation(reduceMotion ? nil : DDMotion.smooth) {
                                    store.send(.toggleInsights)
                                }
                            } label: {
                                Label("Insights", systemImage: "chart.bar.xaxis")
                            }
                            .help(display.showInsights ? "Hide Insights" : "Show Insights")
                            .accessibilityLabel(display.showInsights ? "Hide Insights" : "Show Insights")
                        }

                        if !isPhotosLibraryScan {
                            WatchToggleButton(
                                isWatching: store.watchActive,
                                onStart: { store.send(.setWatchEnabled(true)) },
                                onStop: { store.send(.setWatchEnabled(false)) }
                            )
                            .disabled(store.session.lastScanConfig == nil)
                        }

                        Button {
                            withAnimation(reduceMotion ? nil : DDMotion.smooth) {
                                showInspector.toggle()
                            }
                        } label: {
                            Image(systemName: "sidebar.right")
                        }
                        .help(showInspector ? "Hide Inspector" : "Show Inspector")
                        .accessibilityLabel(showInspector ? "Hide Inspector" : "Show Inspector")
                    }
                }
            }
    }

    private func handleViewModeChange(_ newMode: DisplayState.ViewMode) {
        if newMode == .groups {
            selectedGroupID = store.filteredGroups.first?.groupId
            if let group = store.filteredGroups.first {
                selectedMemberPath = preferredMember(in: group)
                currentGroupSiblingPaths = Set(group.files.map(\.path))
            }
        } else {
            revalidatePairSelection()
        }
    }

    private func handleOnAppear() {
        if effectivePairMode, store.selectedPairID == nil, let first = store.filteredPairs.first {
            store.send(.selectPair(first.pairIdentifier))
        }
        if !effectivePairMode, selectedGroupID == nil, let first = store.filteredGroups.first {
            selectedGroupID = first.groupId
            currentGroupSiblingPaths = Set(first.files.map(\.path))
        }
        if display.moveDestination == nil, !lastMoveDestination.isEmpty {
            store.send(.setMoveDestination(URL(fileURLWithPath: lastMoveDestination)))
        }
    }

    // MARK: - Bulk Action Toolbar Button

    @ViewBuilder
    private var bulkActionToolbarButton: some View {
        let candidates = store.bulkActionCandidates()
        let count = candidates.candidates.count
        let bulkInFlight = results?.bulkProgress != nil

        switch display.activeAction {
        case .trash:
            Button {
                showBulkActionConfirmation = true
            } label: {
                Label("Trash \(count) Files", systemImage: "trash")
            }
            .tint(DDColors.destructive)
            .disabled(count == 0 || bulkInFlight)
            .help(bulkActionTooltip(candidates))
            .accessibilityHint("Choose what to do with duplicate files")

        case .delete:
            Button {
                showBulkActionConfirmation = true
            } label: {
                Label("Delete \(count) Files", systemImage: "trash.slash")
            }
            .tint(DDColors.destructive)
            .disabled(count == 0 || bulkInFlight)
            .help(bulkActionTooltip(candidates))
            .accessibilityHint("Choose what to do with duplicate files")

        case .moveTo:
            Button {
                if display.moveDestination != nil {
                    showBulkActionConfirmation = true
                } else {
                    showMoveDestinationPicker = true
                }
            } label: {
                Label("Move \(count) Files", systemImage: "folder.badge.plus")
            }
            .disabled(count == 0 || bulkInFlight)
            .help(bulkActionTooltip(candidates))
            .accessibilityHint("Choose what to do with duplicate files")

        case .hardlink, .symlink, .reflink:
            EmptyView()
        }
    }

    // MARK: - Bulk Action Helpers

    private func bulkActionConfirmationTitle(
        _ candidates: (candidates: [BulkCandidate], strategy: String?)
    ) -> String {
        let size = DDFormatters.formatFileSize(candidates.candidates.reduce(0) { $0 + $1.size })
        switch display.activeAction {
        case .trash:
            return "Trash \(candidates.candidates.count) files (\(size))?"
        case .delete:
            return "Permanently delete \(candidates.candidates.count) files (\(size))?"
        case .moveTo:
            return "Move \(candidates.candidates.count) files (\(size))?"
        case .hardlink, .symlink, .reflink:
            return "\(candidates.candidates.count) files (\(size))"
        }
    }

    private func bulkActionConfirmationMessage(
        _ candidates: (candidates: [BulkCandidate], strategy: String?)
    ) -> String {
        ResultsBulkActionConfirmationCopy.message(
            for: display.activeAction,
            count: candidates.candidates.count,
            destinationName: display.moveDestination?.lastPathComponent
        )
    }

    @ViewBuilder
    private func bulkActionConfirmationButtons(
        _ candidates: (candidates: [BulkCandidate], strategy: String?)
    ) -> some View {
        let count = candidates.candidates.count

        switch display.activeAction {
        case .trash:
            Button(ResultsBulkActionConfirmationCopy.confirmButtonTitle(for: .trash, count: count) ?? "Trash Files",
                   role: .destructive) {
                executeBulkAction()
            }
            Button("Cancel", role: .cancel) {}

        case .delete:
            if confirmPermanentDelete {
                Button(ResultsBulkActionConfirmationCopy.confirmButtonTitle(for: .delete, count: count)
                       ?? "Delete Files Permanently", role: .destructive) {
                    executeBulkAction()
                }
            }
            Toggle("I understand this cannot be undone", isOn: $confirmPermanentDelete)
            Button("Cancel", role: .cancel) {}

        case .moveTo:
            Button(ResultsBulkActionConfirmationCopy.confirmButtonTitle(for: .moveTo, count: count) ?? "Move Files",
                   role: .destructive) {
                executeBulkAction()
            }
            Button("Change Destination\u{2026}") {
                showMoveDestinationPicker = true
            }
            Button("Cancel", role: .cancel) {}

        case .hardlink, .symlink, .reflink:
            Button("Cancel", role: .cancel) {}
        }
    }

    private func executeBulkAction() {
        store.send(.startBulk)
    }

    private func bulkActionTooltip(
        _ candidates: (candidates: [BulkCandidate], strategy: String?)
    ) -> String {
        if !(results?.hasKeepStrategy ?? false) && effectivePairMode {
            return "Set a keep strategy via Refine Results to enable bulk actions"
        }
        if candidates.candidates.isEmpty {
            return "No duplicate files to process"
        }
        return "\(display.activeAction.displayName) \(candidates.candidates.count) duplicate files"
    }

    // MARK: - Summary Header

    private var summaryHeader: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            GlassEffectContainer(spacing: DDSpacing.sm) {
                HStack(spacing: DDSpacing.sm) {
                    DDStatCapsule(icon: "doc.on.doc", value: "\(results?.filesScanned ?? 0)", label: "scanned")
                    DDStatCapsule(icon: "line.3.horizontal.decrease",
                                value: "\(results?.filesAfterFilter ?? 0)", label: "after filter")
                    DDStatCapsule(icon: "arrow.triangle.merge",
                                value: "\(results?.totalPairsScored ?? 0)", label: "scored")
                    DDStatCapsule(icon: "checkmark.circle",
                                value: "\(results?.pairsAboveThreshold ?? 0)", label: "above threshold")
                    if let groups = results?.groupsCount {
                        DDStatCapsule(icon: "rectangle.3.group", value: "\(groups)", label: "groups")
                    }
                    if let space = results?.spaceRecoverable {
                        DDStatCapsule(icon: "externaldrive", value: space, label: "recoverable")
                    }
                    DDStatCapsule(icon: "clock", value: results?.totalTime ?? "0s", label: "total")
                }
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    // MARK: - Review Desk Content

    private var reviewDeskContent: some View {
        VStack(spacing: 0) {
            if let summary = results?.dryRunSummary {
                DryRunBanner(summary: summary, onExecuteForReal: store.session.lastScanConfig?.dryRun == true ? {
                    rerunWithoutDryRun()
                } : nil)
                    .padding(.horizontal, DDSpacing.md)
                    .padding(.top, DDSpacing.sm)
            }

            if results?.bulkProgress != nil {
                bulkProgressOverlay
                    .padding(.horizontal, DDSpacing.md)
                    .padding(.top, DDSpacing.sm)
            }

            summaryHeader
                .padding(.horizontal, DDSpacing.md)
                .padding(.vertical, DDSpacing.sm)

            if let filterDir = display.directoryFilter {
                directoryFilterPill(filterDir)
                    .padding(.horizontal, DDSpacing.md)
                    .padding(.bottom, DDSpacing.xs)
            }

            Divider()

            if display.showInsights, let analytics = results?.analyticsData {
                InsightsTab(
                    analyticsData: analytics,
                    currentDirectories: store.session.lastScanConfig?.directories ?? [],
                    currentMode: store.session.lastScanConfig?.mode ?? .video,
                    sessionEntries: sessionEntries,
                    currentSessionDate: parseSessionDate(results?.envelope.generatedAt),
                    onDirectoryTap: { path in
                        store.send(.setDirectoryFilter(path))
                        store.send(.toggleInsights)
                    }
                )
                .task {
                    await loadSessionEntries()
                }
            } else {
                HSplitView {
                    QueuePane(
                        store: store,
                        selectedGroupID: $selectedGroupID
                    )
                    .frame(minWidth: 250, idealWidth: 280, maxWidth: 350)
                    .focusable()
                    .focused($focusedPane, equals: .queue)
                    .ddFocusRing(focusedPane == .queue, cornerRadius: DDRadius.large)

                    centerPane
                        .frame(minWidth: 400)
                        .focusable()
                        .focused($focusedPane, equals: .comparison)
                        .ddFocusRing(focusedPane == .comparison, cornerRadius: DDRadius.large)

                    if showInspector {
                        inspectorPane
                            .frame(minWidth: 200, idealWidth: 280, maxWidth: 350)
                            .focusable()
                            .focused($focusedPane, equals: .inspector)
                            .ddFocusRing(focusedPane == .inspector, cornerRadius: DDRadius.large)
                    }
                }
                .disabled(results?.bulkProgress != nil)
            }
        }
    }

    private static let isoFormatterFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let isoFormatterPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func parseSessionDate(_ isoString: String?) -> Date? {
        guard let isoString else { return nil }
        return Self.isoFormatterFractional.date(from: isoString)
            ?? Self.isoFormatterPlain.date(from: isoString)
    }

    /// Load session entries from the registry for trend analysis.
    private func loadSessionEntries() async {
        do {
            sessionEntries = try await store.registry.listEntries()
        } catch {
            sessionEntries = []
        }
    }

    // MARK: - Directory Filter Pill

    private func directoryFilterPill(_ directory: String) -> some View {
        HStack(spacing: DDSpacing.xs) {
            Image(systemName: "line.3.horizontal.decrease.circle.fill")
                .foregroundStyle(DDColors.accent)
            Text("Filtered: \(Self.shortenPath(directory))")
                .font(DDTypography.label)
                .lineLimit(1)
            Button {
                store.send(.setDirectoryFilter(nil))
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(ddColors.textSecondary)
            }
            .buttonStyle(.plain)
        }
        .ddGlassPill()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Directory filter: \(directory). Activate to clear.")
        .accessibilityAddTraits(.isButton)
    }

    /// Shorten an absolute path by replacing the home directory prefix with `~`.
    nonisolated static func shortenPath(_ path: String) -> String {
        let home = NSHomeDirectory()
        guard path.hasPrefix(home) else { return path }
        return "~" + path.dropFirst(home.count)
    }

    // MARK: - Center Pane

    @ViewBuilder
    private var centerPane: some View {
        if effectivePairMode {
            if let pair = store.selectedPair {
                let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
                let resolution = results?.resolutionStatus(for: pairID) ?? .active
                ComparisonPanel(
                    pair: pair,
                    scanMode: ScanMode(rawValue: results?.scanArgs.mode ?? "video") ?? .video,
                    activeAction: display.activeAction,
                    currentPairIndex: store.currentPairIndex,
                    totalFilteredPairs: store.totalFilteredPairs,
                    onKeepA: { performKeepA(pair: pair) },
                    onKeepB: { performKeepB(pair: pair) },
                    onPrevious: { autoSkipBothRef = false; store.send(.previousPair) },
                    onSkip: { store.send(.skipPair) },
                    onSkipAndIgnore: { performSkipAndIgnore(pair: pair) },
                    isAtFirstPair: (store.currentPairIndex ?? 0) == 0,
                    resolution: resolution.asPairResolutionStatus
                )
            } else {
                ContentUnavailableView(
                    "Select a Pair",
                    systemImage: "arrow.left.circle",
                    description: Text("Choose a pair from the queue to compare")
                )
            }
        } else {
            if let groupID = selectedGroupID,
               let group = store.filteredGroups.first(where: { $0.groupId == groupID }) {
                GroupReviewView(
                    group: group, selectedMemberPath: $selectedMemberPath,
                    actionedPaths: results?.actionedPaths ?? [],
                    resolvedPaths: results?.resolvedActionPaths ?? [],
                    activeAction: display.activeAction,
                    currentIndex: store.filteredGroups.firstIndex(where: { $0.groupId == groupID }),
                    totalGroups: store.filteredGroups.count,
                    onAction: { path in
                        guard let action = actionForPath(path) else { return }
                        dispatchGroupMemberAction(action, memberPath: path, group: group)
                    },
                    onPrevious: { advanceToPreviousGroup() },
                    onSkip: { advanceToNextGroup() }
                )
            } else {
                ContentUnavailableView(
                    "Select a Group",
                    systemImage: "rectangle.3.group",
                    description: Text("Choose a group from the queue to review")
                )
            }
        }
    }

    // MARK: - Inspector Pane

    @ViewBuilder
    private var inspectorPane: some View {
        if effectivePairMode {
            if let pair = store.selectedPair {
                let pairResolution = results?.resolutionStatus(
                    for: PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
                ) ?? .active
                PairInspectorPane(pair: pair, activeAction: display.activeAction,
                                  resolution: pairResolution.asPairResolutionStatus) { action in
                    handleInspectorAction(action)
                }
            } else {
                inspectorPlaceholder
            }
        } else {
            if let memberPath = selectedMemberPath,
               let groupID = selectedGroupID,
               let group = store.filteredGroups.first(where: { $0.groupId == groupID }),
               let file = group.files.first(where: { $0.path == memberPath }) {
                GroupInspectorPane(file: file, isKeep: group.keep == file.path,
                                   hasKeepStrategy: group.keep != nil,
                                   activeAction: display.activeAction,
                                   resolvedPaths: results?.resolvedActionPaths ?? []) { action in
                    handleInspectorAction(action)
                }
            } else {
                inspectorPlaceholder
            }
        }
    }

    private var inspectorPlaceholder: some View {
        ContentUnavailableView(
            "No Selection",
            systemImage: "sidebar.right",
            description: Text("Select an item to inspect")
        )
        .background(DDColors.surface1)
    }

    // MARK: - Selection Revalidation

    /// Returns the path of the group member matching the search query, or the first member.
    /// Excludes files that have already been actioned.
    private func preferredMember(in group: GroupResult) -> String? {
        let actionedPaths = results?.actionedPaths ?? []
        let alive = group.files.filter { !actionedPaths.contains($0.path) }
        let query = display.searchText
        if !query.isEmpty,
           let match = alive.first(where: { $0.path.localizedCaseInsensitiveContains(query) }) {
            return match.path
        }
        return alive.first?.path
    }

    // MARK: - Keyboard Shortcut Handlers

    private func handleQuickLook() {
        guard let path = currentInspectedPath else { return }
        store.quickLook(path)
    }

    private func handleReveal() {
        guard let path = currentInspectedPath else { return }
        store.revealInFinder(path)
    }

    /// The path targeted by global keyboard shortcuts (Space = Quick Look, Cmd-Return = Reveal).
    private var currentInspectedPath: String? {
        if effectivePairMode {
            return store.selectedPair?.fileA
        } else {
            return selectedMemberPath
        }
    }

    // MARK: - Comparison Key Handling

    private enum ComparisonKey {
        case keepA, keepB, skipNext, skipPrev, focusQueue, ignore, actionMember
    }

    private func handleComparisonKeyPress(_ key: ComparisonKey) -> KeyPress.Result {
        guard !hasActiveModal, !display.showInsights else { return .ignored }
        if key == .focusQueue {
            focusedPane = .queue
            return .handled
        }
        guard focusedPane == .comparison, results?.bulkProgress == nil else { return .ignored }

        if effectivePairMode {
            return handlePairKeyPress(key)
        } else {
            return handleGroupKeyPress(key)
        }
    }

    // MARK: - Pair Key Handling

    /// Whether the currently selected pair has an active (actionable) resolution status.
    private var isSelectedPairActive: Bool {
        guard let pair = store.selectedPair else { return false }
        let pairID = PairIdentifier(fileA: pair.fileA, fileB: pair.fileB)
        if case .active = results?.resolutionStatus(for: pairID) ?? .active { return true }
        return false
    }

    private func handlePairKeyPress(_ key: ComparisonKey) -> KeyPress.Result {
        switch key {
        case .keepA:
            guard isSelectedPairActive else { return .ignored }
            guard let pair = store.selectedPair, !pair.fileBIsReference else { return .ignored }
            performKeepA(pair: pair)
            return .handled
        case .keepB:
            guard isSelectedPairActive else { return .ignored }
            guard let pair = store.selectedPair, !pair.fileAIsReference else { return .ignored }
            performKeepB(pair: pair)
            return .handled
        case .skipNext:
            store.send(.skipPair)
            return .handled
        case .skipPrev:
            autoSkipBothRef = false
            store.send(.previousPair)
            return .handled
        case .ignore:
            guard isSelectedPairActive else { return .ignored }
            guard let pair = store.selectedPair else { return .ignored }
            performSkipAndIgnore(pair: pair)
            return .handled
        case .focusQueue, .actionMember:
            return .ignored
        }
    }

    // MARK: - Group Key Handling

    private func handleGroupKeyPress(_ key: ComparisonKey) -> KeyPress.Result {
        let groups = store.filteredGroups
        guard !groups.isEmpty else { return .ignored }

        switch key {
        case .keepA:
            // left arrow = previous filmstrip member
            cycleFilmstripMember(direction: -1)
            return .handled
        case .keepB:
            // right arrow = next filmstrip member
            cycleFilmstripMember(direction: 1)
            return .handled
        case .skipNext:
            advanceToNextGroup()
            return .handled
        case .skipPrev:
            advanceToPreviousGroup()
            return .handled
        case .actionMember:
            performGroupMemberAction()
            return .handled
        case .ignore, .focusQueue:
            return .ignored
        }
    }

    /// Cycle the selected filmstrip member within the current group.
    /// Direction: -1 = previous, +1 = next. Stops at boundaries, skips actioned files.
    private func cycleFilmstripMember(direction: Int) {
        guard let groupID = selectedGroupID,
              let group = store.filteredGroups.first(where: { $0.groupId == groupID })
        else { return }

        let actionedPaths = results?.actionedPaths ?? []
        let alive = group.files.filter { !actionedPaths.contains($0.path) }
        guard !alive.isEmpty else { return }

        guard let current = selectedMemberPath,
              let idx = alive.firstIndex(where: { $0.path == current }) else {
            selectedMemberPath = alive.first?.path
            return
        }

        let next = idx + direction
        guard next >= 0, next < alive.count else { return }
        withAnimation(reduceMotion ? nil : DDMotion.snappy) {
            selectedMemberPath = alive[next].path
        }
    }

    /// Advance to the next group in the filtered list. No wrap.
    private func advanceToNextGroup() {
        let groups = store.filteredGroups
        guard !groups.isEmpty else { return }
        guard let currentID = selectedGroupID,
              let idx = groups.firstIndex(where: { $0.groupId == currentID }) else {
            selectGroup(groups[0])
            return
        }
        if idx + 1 < groups.count { selectGroup(groups[idx + 1]) }
    }

    /// Move to the previous group in the filtered list. No wrap.
    private func advanceToPreviousGroup() {
        let groups = store.filteredGroups
        guard !groups.isEmpty else { return }
        guard let currentID = selectedGroupID,
              let idx = groups.firstIndex(where: { $0.groupId == currentID }) else {
            selectGroup(groups[0])
            return
        }
        if idx > 0 { selectGroup(groups[idx - 1]) }
    }

    private func selectGroup(_ group: GroupResult) {
        selectedGroupID = group.groupId
        selectedMemberPath = preferredMember(in: group)
        currentGroupSiblingPaths = Set(group.files.map(\.path))
    }

    /// Perform the active action (trash/delete/move) on the selected group member.
    private func performGroupMemberAction() {
        guard let memberPath = selectedMemberPath,
              let groupID = selectedGroupID,
              let group = store.filteredGroups.first(where: { $0.groupId == groupID }),
              let file = group.files.first(where: { $0.path == memberPath })
        else { return }

        // Cannot act on keep or reference files
        let isKeep = group.keep == file.path
        guard !isKeep, !file.isReference else { return }

        guard let action = actionForPath(memberPath) else { return }
        dispatchGroupMemberAction(action, memberPath: memberPath, group: group)
    }

    /// Dispatch an action on a group member from the GroupActionBar.
    /// Reused by both the action bar's onAction callback and performGroupMemberAction (keyboard).
    private func dispatchGroupMemberAction(_ action: PairAction, memberPath: String, group: GroupResult) {
        let actionedPaths = results?.actionedPaths ?? []
        let alive = group.files.filter { !actionedPaths.contains($0.path) && $0.path != memberPath }
        let nextMember = alive.first(where: { $0.path != group.keep && !$0.isReference })?.path

        // Find a real pair from the group that contains the member path,
        // so handleAction has a valid pairID (selectedPair is nil in group mode).
        let pairID: PairIdentifier? = group.pairs
            .first { $0.fileA == memberPath || $0.fileB == memberPath }
            .map { PairIdentifier(fileA: $0.fileA, fileB: $0.fileB) }

        // Pre-capture the next group before the action, in case this action removes
        // the current group from filteredGroups (last actionable member being removed).
        let nextGroupAfterRemoval: GroupResult? = {
            guard nextMember == nil else { return nil }
            let groups = store.filteredGroups
            guard let idx = groups.firstIndex(where: { $0.groupId == group.groupId }) else { return nil }
            if idx + 1 < groups.count { return groups[idx + 1] }
            if idx > 0 { return groups[idx - 1] }
            return nil
        }()

        let executeAsync = {
            let task = Task {
                let success = await self.store.handleAction(action, pairID: pairID)
                if success {
                    await MainActor.run {
                        if let next = nextMember {
                            self.selectedMemberPath = next
                        } else if let nextGroup = nextGroupAfterRemoval {
                            self.selectGroup(nextGroup)
                        } else {
                            self.advanceToNextGroup()
                        }
                    }
                }
            }
            self.store.trackActionTask(task)
        }

        let groupAction: PairAction = switch action {
        case .permanentDelete: .permanentDelete(memberPath)
        case .trash: .trash(memberPath)
        case .moveTo: .moveTo(memberPath)
        default: action
        }
        if let confirmation = Self.confirmationCopy(for: groupAction) {
            singleDeleteConfirmation.present(
                title: confirmation.title,
                message: confirmation.message,
                confirmButtonTitle: confirmation.button,
                performAction: executeAsync
            )
        } else {
            executeAsync()
        }
    }

    // MARK: - Comparison Action Helpers

    private func performKeepA(pair: PairResult) {
        guard let action = actionForPath(pair.fileB) else { return }
        dispatchAction(action)
    }

    private func performKeepB(pair: PairResult) {
        guard let action = actionForPath(pair.fileA) else { return }
        dispatchAction(action)
    }

    /// Dispatch a destructive action with confirmation.
    /// The pair ID and action context are captured upfront so the correct pair
    /// is referenced even if the user navigates before a confirmation dialog
    /// completes. Navigation advances only after the file operation succeeds.
    private func dispatchAction(_ action: PairAction) {
        let preCtx: ActionContext? = switch action {
        case .trash(let p), .permanentDelete(let p), .moveTo(let p):
            store.actionContext(for: p)
        default: nil
        }
        let pairID = store.selectedPairID
        let autoAdvancedTo = store.nextPairAfterAction
        let executeAsync = {
            let task = Task<Void, Never> {
                let success = await store.handleAction(action, pairID: pairID, context: preCtx)
                if success, let next = autoAdvancedTo {
                    store.send(.selectPair(next))
                }
            }
            store.trackActionTask(task)
        }
        if let confirmation = Self.confirmationCopy(for: action) {
            singleDeleteConfirmation.present(
                title: confirmation.title,
                message: confirmation.message,
                confirmButtonTitle: confirmation.button,
                performAction: executeAsync
            )
        } else {
            executeAsync()
        }
    }

    private func handleInspectorAction(_ action: PairAction) {
        // In group mode, route destructive actions through dispatchGroupMemberAction
        // so next-member/next-group navigation is pre-computed correctly.
        if !effectivePairMode,
           let memberPath = selectedMemberPath,
           let groupID = selectedGroupID,
           let group = store.filteredGroups.first(where: { $0.groupId == groupID }) {
            switch action {
            case .trash, .permanentDelete, .moveTo:
                dispatchGroupMemberAction(action, memberPath: memberPath, group: group)
                return
            default:
                break
            }
        }
        // Only auto-advance for destructive actions that remove a file from the pair.
        // Non-destructive actions (reveal, copy path, quick look) should not navigate away.
        let shouldAdvance: Bool = switch action {
        case .trash, .permanentDelete, .moveTo: true
        default: false
        }
        let autoAdvancedTo = shouldAdvance ? store.nextPairAfterAction : nil
        singleDeleteConfirmation.routeInspectorAction(action) { action in
            store.trackActionTask(Task {
                let success = await store.handleAction(action)
                if success, let next = autoAdvancedTo {
                    store.send(.selectPair(next))
                }
            })
        }
    }

    private func performSkipAndIgnore(pair: PairResult) {
        let task = Task<Void, Never> {
            _ = await store.handleAction(.ignorePair(pair.fileA, pair.fileB))
        }
        store.trackActionTask(task)
    }

    private func actionForPath(_ path: String) -> PairAction? {
        switch display.activeAction {
        case .trash: .trash(path)
        case .delete: .permanentDelete(path)
        case .moveTo: .moveTo(path)
        case .hardlink, .symlink, .reflink: nil
        }
    }

    // MARK: - Confirmation Copy

    /// Returns confirmation dialog copy for destructive actions, or nil for
    /// non-destructive ones (ignore, reveal, copy, etc.).
    nonisolated static func confirmationCopy(for action: PairAction) -> (title: String, message: String, button: String)? {
        switch action {
        case .trash:
            return nil
        case .permanentDelete(let path):
            let name = path.fileName
            return (
                title: "Permanently Delete \"\(name)\"?",
                message: "\(path)\nThis action cannot be undone.",
                button: "Delete \"\(name)\""
            )
        case .moveTo(let path):
            let name = path.fileName
            return (
                title: "Move \"\(name)\"?",
                message: "\(path)\nThe original will be removed.",
                button: "Move \"\(name)\""
            )
        default:
            return nil
        }
    }

    /// Ensures the selected pair is still visible in the filtered list; selects the first if not.
    private func revalidatePairSelection() {
        let isValid = store.selectedPairID.map { id in
            store.filteredPairs.contains { $0.pairIdentifier == id }
        } ?? false
        if !isValid {
            store.send(.selectPair(store.filteredPairs.first?.pairIdentifier))
        }
    }

    /// After an action (trash/delete/move/ignore), revalidate pair selection and group member selection.
    private func revalidateAfterAction() {
        let actionedPaths = results?.actionedPaths ?? []
        if effectivePairMode {
            revalidatePairSelection()
        } else {
            let matchedGroup: GroupResult? = findGroupContaining(
                primaryPath: selectedMemberPath,
                siblingPaths: currentGroupSiblingPaths
            )

            if let group = matchedGroup {
                selectedGroupID = group.groupId
                currentGroupSiblingPaths = Set(group.files.map(\.path))
                if let path = selectedMemberPath, actionedPaths.contains(path) {
                    selectedMemberPath = group.files.first { !actionedPaths.contains($0.path) }?.path
                }
            } else {
                let first = store.filteredGroups.first
                selectedGroupID = first?.groupId
                selectedMemberPath = first?.files.first?.path
                currentGroupSiblingPaths = first.map { Set($0.files.map(\.path)) } ?? []
            }
        }
    }

    /// Re-selects a visible item when filtering removes the current selection.
    /// Only recomputes the selected group member when the search query changed,
    /// preserving manual filmstrip selection on sort-only changes.
    private func revalidateSelection(searchChanged: Bool) {
        if effectivePairMode {
            revalidatePairSelection()
        } else {
            let currentGroup = findGroupContaining(
                primaryPath: selectedMemberPath,
                siblingPaths: currentGroupSiblingPaths
            )

            if let group = currentGroup {
                selectedGroupID = group.groupId
                currentGroupSiblingPaths = Set(group.files.map(\.path))
                if searchChanged {
                    selectedMemberPath = preferredMember(in: group)
                }
            } else {
                // Group filtered out -- jump to first visible group
                let first = store.filteredGroups.first
                selectedGroupID = first?.groupId
                selectedMemberPath = first.flatMap { preferredMember(in: $0) }
                currentGroupSiblingPaths = first.map { Set($0.files.map(\.path)) } ?? []
            }
        }
    }

    /// Find the group containing the primary path, or failing that, any sibling path.
    /// This provides stable group identity across synthesized-group rebuilds where
    /// the selected member may have been actioned/removed.
    private func findGroupContaining(
        primaryPath: String?,
        siblingPaths: Set<String>
    ) -> GroupResult? {
        // Try primary path first (most common case: member is still present)
        if let path = primaryPath,
           let group = store.filteredGroups.first(where: { g in g.files.contains { $0.path == path } }) {
            return group
        }
        // Fall back to any sibling still in a group (e.g., actioned member removed but cluster survives)
        guard !siblingPaths.isEmpty else { return nil }
        return store.filteredGroups.first { g in g.files.contains { siblingPaths.contains($0.path) } }
    }

    // MARK: - Undo Script Generation

    private var logFileExists: Bool {
        guard let path = store.session.lastScanConfig?.log else { return false }
        return FileManager.default.fileExists(atPath: path)
    }

    private func generateUndoScript() {
        guard let logPath = store.session.lastScanConfig?.log else { return }
        let bridge = store.bridge
        isGeneratingUndo = true
        Task {
            await store.flushActionLog()
            do {
                let script = try await bridge.generateUndoScript(logPath: logPath)
                undoScriptContent = script
                showUndoScript = true
            } catch {
                store.send(.fileActionFailed(
                    PairIdentifier(fileA: "", fileB: ""),
                    "Failed to generate undo script: \(error.localizedDescription)"
                ))
            }
            isGeneratingUndo = false
        }
    }

    // MARK: - Dry-Run Re-execution

    private func rerunWithoutDryRun() {
        guard var config = store.session.lastScanConfig else { return }
        config.dryRun = false
        store.send(.startScan(config))
    }

    // MARK: - Bulk Progress Overlay

    @ViewBuilder
    private var bulkProgressOverlay: some View {
        if let progress = results?.bulkProgress {
            HStack(spacing: DDSpacing.md) {
                ProgressView(value: Double(progress.completed), total: Double(progress.total))
                    .frame(maxWidth: 200)
                Text("Processing \(progress.completed) of \(progress.total) files\u{2026}")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                Button("Cancel") { store.send(.cancelBulk) }
                    .controlSize(.small)
            }
            .padding(DDDensity.regular)
            .ddGlassCard()
        }
    }

    // MARK: - Export Helpers

    private func exportJSON() {
        // Prefer original CLI bytes; fall back to re-encoding the current envelope
        // (e.g., after pair-mode watch alerts invalidate the raw sidecar cache).
        let data: Data
        if let original = store.session.lastOriginalEnvelope {
            data = original
        } else if let envelope = store.session.results?.envelope {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            guard let encoded = try? encoder.encode(envelope) else { return }
            data = encoded
        } else {
            return
        }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.ddScanResults, .json]
        panel.nameFieldStringValue = "scan-results.ddscan"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try data.write(to: url, options: .atomic)
        } catch {
            exportError = "Failed to save JSON: \(error.localizedDescription)"
        }
    }

    private func exportViaReplay(format: ExportFormat) {
        guard let cliFormat = format.cliFormatString else { return }
        let bridge = store.bridge
        let panel = NSSavePanel()
        panel.allowedContentTypes = [format.contentType]
        panel.nameFieldStringValue = format.defaultFileName
        guard panel.runModal() == .OK, let outputURL = panel.url else { return }
        isExporting = true
        Task {
            defer { isExporting = false }
            do {
                let tempURL = try store.writeFilteredReplayEnvelopeToTempFile()
                defer { try? FileManager.default.removeItem(at: tempURL) }
                try await bridge.exportAsFormat(
                    envelopePath: tempURL.path,
                    format: cliFormat,
                    outputPath: outputURL.path,
                    keep: store.session.lastScanConfig?.keep?.rawValue,
                    embedThumbnails: false,
                    group: display.viewMode == .groups,
                    ignoreFile: store.session.lastScanConfig?.ignoreFile
                )
            } catch {
                exportError = "Failed to export \(format.displayName): \(error.localizedDescription)"
            }
        }
    }

    private func handleCopySummary() {
        store.copySummaryToClipboard()
        isShowingCopySummaryFeedback = true
        copySummaryFeedbackTask?.cancel()
        copySummaryFeedbackTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            isShowingCopySummaryFeedback = false
            copySummaryFeedbackTask = nil
        }
    }

    private func resetCopySummaryFeedback() {
        isShowingCopySummaryFeedback = false
        copySummaryFeedbackTask?.cancel()
        copySummaryFeedbackTask = nil
    }
}

// MARK: - Refine Results Sheet

/// Sheet for adjusting replay-compatible settings and re-running the scan.
private struct RefineResultsSheet: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors
    @Environment(\.dismiss) private var dismiss

    @State private var keep: KeepStrategy?
    @State private var sort: SortField = .score
    @State private var limitText = ""
    @State private var minScore: Double = 0
    @State private var group = false

    private var isLimitValid: Bool {
        if limitText.isEmpty { return true }
        guard let value = Int(limitText) else { return false }
        return value > 0
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Refine Results")
                    .font(DDTypography.sectionTitle)
                    .foregroundStyle(ddColors.textPrimary)
                Spacer()
                Button("Cancel") { dismiss() }
                    .controlSize(.small)
            }
            .padding(DDDensity.regular)
            Divider()

            Form {
                Picker("Keep Strategy", selection: $keep) {
                    Text("None").tag(nil as KeepStrategy?)
                    ForEach(KeepStrategy.allCases, id: \.self) { strategy in
                        Text(strategy.displayName).tag(strategy as KeepStrategy?)
                    }
                }

                Picker("Sort By", selection: $sort) {
                    ForEach(SortField.allCases, id: \.self) { field in
                        Text(field.rawValue).tag(field)
                    }
                }

                HStack {
                    Text("Limit")
                    TextField("No limit", text: $limitText)
                        .frame(width: 80)
                        .foregroundStyle(isLimitValid ? ddColors.textPrimary : DDColors.destructive)
                        .overlay(
                            RoundedRectangle(cornerRadius: DDRadius.small)
                                .strokeBorder(isLimitValid ? .clear : DDColors.destructive, lineWidth: 1)
                        )
                }

                HStack {
                    Text("Min Score")
                    Slider(value: $minScore, in: 0...100)
                    Text("\(Int(minScore))%")
                        .font(DDTypography.monospaced)
                        .frame(minWidth: 36, alignment: .trailing)
                }

                Toggle("Group Mode", isOn: $group)
            }
            .formStyle(.grouped)

            HStack {
                Spacer()
                Button("Refine") {
                    applyRefine()
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!isLimitValid)
            }
            .padding(DDDensity.regular)
        }
        .frame(width: 400, height: 350)
        .onAppear { loadCurrentSettings() }
    }

    private func loadCurrentSettings() {
        if let config = store.session.lastScanConfig {
            keep = config.keep
            sort = config.sort
            if let limit = config.limit { limitText = "\(limit)" }
            if let ms = config.minScore { minScore = Double(ms) }
        }
        // Seed from the active view mode, not the original scan setting
        group = store.session.display.viewMode == .groups
    }

    private func applyRefine() {
        do {
            // Use a filtered envelope that excludes resolved/ignored pairs so
            // refine doesn't reintroduce pairs the user already handled. The
            // CLI replay applies the new min-score/limit/sort to this set.
            let tempURL = try store.writeFilteredReplayEnvelopeToTempFile()
            var config = ScanConfig()
            config.replayPath = tempURL.path
            config.keep = keep
            config.sort = sort
            config.limit = Int(limitText)
            config.minScore = minScore > 0 ? Int(minScore) : nil
            config.group = group
            // Preserve session-identity settings so ignore/action/log/reference stay consistent
            config.ignoreFile = store.session.lastScanConfig?.ignoreFile
            if let action = store.session.lastScanConfig?.action {
                config.action = action
                config.actionExplicitlySet = store.session.lastScanConfig?.actionExplicitlySet ?? false
            }
            config.moveToDir = store.session.lastScanConfig?.moveToDir
            config.log = store.session.lastScanConfig?.log
            config.reference = store.session.lastScanConfig?.reference ?? []
            config.embedThumbnails = store.session.lastScanConfig?.embedThumbnails ?? false
            config.thumbnailSize = store.session.lastScanConfig?.thumbnailSize
            store.send(.startScan(config))
        } catch {
            store.send(.fileActionFailed(
                PairIdentifier(fileA: "", fileB: ""),
                "Failed to prepare results for refinement: \(error.localizedDescription)"
            ))
        }
    }
}

// MARK: - Undo Script Sheet

private struct UndoScriptSheet: View {
    let content: String
    @Environment(\.ddColors) private var ddColors
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Undo Script")
                    .font(DDTypography.sectionTitle)
                    .foregroundStyle(ddColors.textPrimary)
                Spacer()
                Button("Copy to Clipboard") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(content, forType: .string)
                }
                .controlSize(.small)
                Button("Save As\u{2026}") { saveScript() }
                    .controlSize(.small)
                Button("Done") { dismiss() }
                    .controlSize(.small)
            }
            .padding(DDDensity.regular)

            Divider()

            ScrollView {
                Text(content)
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textPrimary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(DDDensity.regular)
            }
        }
        .frame(minWidth: 600, idealWidth: 700, minHeight: 400, idealHeight: 500)
    }

    private func saveScript() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.shellScript]
        panel.nameFieldStringValue = "undo-duplicates.sh"
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            try? content.write(to: url, atomically: true, encoding: .utf8)
            // Make executable
            try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        }
    }
}

// MARK: - Dry Run Banner

struct DryRunBanner: View {
    let summary: DryRunSummary
    var onExecuteForReal: (() -> Void)?
    @Environment(\.ddColors) private var ddColors

    @State private var showExecuteConfirmation = false

    var body: some View {
        HStack {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(DDColors.accent)
            VStack(alignment: .leading) {
                Text("Dry Run")
                    .font(DDTypography.action)
                    .foregroundStyle(ddColors.textPrimary)
                Text("\(summary.totalFiles) files, \(summary.totalBytesHuman) would be freed")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
            }
            Spacer()
            if let strategy = summary.strategy {
                Text(strategy)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
            }
            if onExecuteForReal != nil {
                Button("Execute for Real") { showExecuteConfirmation = true }
                    .controlSize(.small)
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
        .confirmationDialog(
            "Execute Scan for Real?",
            isPresented: $showExecuteConfirmation,
            titleVisibility: .visible
        ) {
            Button("Execute for Real", role: .destructive) {
                onExecuteForReal?()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will re-run the scan and perform file actions. Depending on the configured action, files may be moved or deleted.")
        }
    }
}

// MARK: - Watch Toggle Button

/// Toolbar button that starts/stops a background watch session from the results screen.
private struct WatchToggleButton: View {
    let isWatching: Bool
    let onStart: () -> Void
    let onStop: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isPulsing = false

    var body: some View {
        Button {
            if isWatching { onStop() } else { onStart() }
        } label: {
            HStack(spacing: DDSpacing.xs) {
                if isWatching {
                    Circle()
                        .fill(.green)
                        .frame(width: 8, height: 8)
                        .scaleEffect(isPulsing ? 1.3 : 1.0)
                        .animation(
                            reduceMotion ? nil : .easeInOut(duration: 1.0).repeatForever(),
                            value: isPulsing
                        )
                        .task {
                            // Reset first so the false->true transition always
                            // produces an animation tick, even on re-insertion.
                            isPulsing = false
                            // Yield a frame so SwiftUI commits the false state
                            // before animating to true.
                            try? await Task.sleep(for: .milliseconds(16))
                            isPulsing = true
                        }
                }
                Text(isWatching ? "Watching" : "Watch")
            }
        }
        .ddGlassPill()
        .accessibilityLabel(isWatching ? "Stop watching for duplicates" : "Start watching for duplicates")
        .onChange(of: isWatching) { _, watching in
            if !watching {
                // Cancel any in-flight repeatForever animation before the
                // Circle is re-inserted, preventing glitches on rapid toggle.
                var t = Transaction(animation: nil)
                t.disablesAnimations = true
                withTransaction(t) { isPulsing = false }
            }
        }
    }
}

// MARK: - Previews
//
// ResultsScreen embeds QueuePane which uses List (NSOutlineView on macOS).
// NSOutlineView crashes in Xcode preview windows during key-view-loop setup.
// Preview the sub-panes individually instead; the full three-pane layout is
// verified at runtime.

#if DEBUG
#Preview("Summary Header") {
    let store = PreviewFixtures.sessionStore()
    let results = store.session.results
    ScrollView(.horizontal, showsIndicators: false) {
        HStack(spacing: DDSpacing.sm) {
            DDStatCapsule(icon: "doc.on.doc", value: "\(results?.filesScanned ?? 0)", label: "scanned")
            DDStatCapsule(icon: "line.3.horizontal.decrease",
                        value: "\(results?.filesAfterFilter ?? 0)", label: "after filter")
            DDStatCapsule(icon: "arrow.triangle.merge",
                        value: "\(results?.totalPairsScored ?? 0)", label: "scored")
            DDStatCapsule(icon: "checkmark.circle",
                        value: "\(results?.pairsAboveThreshold ?? 0)", label: "above threshold")
            DDStatCapsule(icon: "clock", value: results?.totalTime ?? "0s", label: "total")
        }
    }
    .padding(DDDensity.regular)
    .ddGlassCard()
    .padding()
    .frame(width: 800)
}

#Preview("Dry Run Banner") {
    DryRunBanner(summary: DryRunSummary(
        filesToDelete: [],
        totalFiles: 12,
        totalBytes: 1_288_490_188,
        totalBytesHuman: "1.2 GB",
        strategy: "trash"
    ))
    .padding()
    .frame(width: 600)
}

#Preview("DDStatCapsule") {
    HStack(spacing: DDSpacing.sm) {
        DDStatCapsule(icon: "doc.on.doc", value: "120", label: "scanned")
        DDStatCapsule(icon: "checkmark.circle", value: "5", label: "above threshold")
        DDStatCapsule(icon: "clock", value: "5.6s", label: "total")
    }
    .padding()
}
#endif
