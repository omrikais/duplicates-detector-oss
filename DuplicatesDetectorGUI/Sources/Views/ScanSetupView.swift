import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Simplified scan setup screen — the "happy path" configuration surface.
///
/// Three-zone vertical flow: hero source picker, mode+presets, session summary.
/// Advanced configuration lives in the CustomizeSheet modal. All content
/// constrained to `DDSpacing.contentMaxWidth` and centered.
/// The Start Scan button is pinned to a glass chrome bottom bar.
struct ScanSetupView: View {
    let store: SessionStore
    @Environment(\.ddColors) private var ddColors
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var activePreset: ScanPreset? = .quick
    @State private var isDropTargeted = false
    @State private var showCustomize = false
    @State private var customizePresenter = CustomizePanelPresenter()
    @State private var showAllErrors = false
    @State private var showAllWarnings = false
    @State private var presetDebounceTask: Task<Void, Never>?
    @State private var showHistorySheet = false
    @State private var showSaveProfileSheet = false
    @State private var saveProfileName = ""
    @State private var profileError: String?

    private var setup: SetupState { store.setupState }

    var body: some View {
        composerLayout
            .modifier(DropTargetOverlay(store: store, isDropTargeted: $isDropTargeted, disabled: setup.scanSource != .directory))
            .onChange(of: setup.presetSignature) { _, _ in
                presetDebounceTask?.cancel()
                presetDebounceTask = Task { @MainActor in
                    try? await Task.sleep(for: .milliseconds(300))
                    guard !Task.isCancelled else { return }
                    detectPresetChange()
                }
            }
            .onChange(of: showCustomize) { _, show in
                if show {
                    customizePresenter.show(store: store) {
                        showCustomize = false
                    }
                } else {
                    customizePresenter.close()
                }
            }
            .sheet(isPresented: $showHistorySheet) {
                ScanHistoryView(store: store)
                    .presentationBackground(.ultraThinMaterial)
            }
            .sheet(isPresented: $showSaveProfileSheet) {
                SetupShared.saveProfileSheet(
                    saveProfileName: $saveProfileName,
                    profileError: profileError,
                    showSheet: $showSaveProfileSheet
                ) {
                    Task { await saveProfile() }
                }
                .presentationBackground(.ultraThinMaterial)
            }
            .task { await SetupShared.refreshProfiles(store: store) }
            .onChange(of: setup.mode) { _, newMode in
                if setup.suppressPresetOnModeChange {
                    store.sendSetup(.setBool(.suppressPresetOnModeChange, false))
                    activePreset = PresetManager.detectPreset(for: newMode, from: setup)
                } else if PresetManager.presetsAvailable(for: newMode) {
                    applyPreset(.quick)
                } else {
                    activePreset = nil
                }
            }
            .onAppear {
                if !setup.hasAppliedInitialPreset {
                    store.sendSetup(.setBool(.hasAppliedInitialPreset, true))
                    if AppDefaults.hasAnyExplicitDefaults {
                        activePreset = PresetManager.detectPreset(for: setup.mode, from: setup)
                    } else {
                        applyPreset(.quick)
                    }
                } else {
                    activePreset = PresetManager.detectPreset(for: setup.mode, from: setup)
                }
            }
    }

    // MARK: - Layout

    private var composerLayout: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: DDSpacing.xl) {
                    if let sessionId = store.session.lastPausedSessionId {
                        ResumeSessionCard(
                            sessionId: sessionId,
                            sessionInfo: store.session.pendingSession,
                            onResume: { store.send(.resumeSession(sessionId, setup.buildConfig())) },
                            onDiscard: { store.send(.discardSession(sessionId)) }
                        )
                    }
                    sourceArea
                    modeAndPresetRow
                    summaryCard
                }
                .frame(maxWidth: DDSpacing.contentMaxWidth)
                .frame(maxWidth: .infinity)
                .padding(DDSpacing.lg)
            }
            .scrollContentBackground(.hidden)

            bottomBar
        }
        .background(DDColors.surface0)
    }

    // MARK: - Source Area (Hero)

    private var sourceArea: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                Label("Sources", systemImage: "folder.fill")
                    .font(DDTypography.heading)
                    .foregroundStyle(ddColors.textPrimary)
                Text("Where to look for duplicates")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }

            DirectoryPickerSection(store: store)
                .padding(DDDensity.regular)
                .ddGlassCard()
        }
    }

    // MARK: - Mode + Presets

    private var modeAndPresetRow: some View {
        HStack(spacing: DDSpacing.lg) {
            // Mode picker
            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                Text("Mode")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
                    .textCase(.uppercase)

                Picker("Mode", selection: store.setupBinding(\.mode, action: { .setMode($0) })) {
                    ForEach(ScanMode.allCases, id: \.self) { m in
                        Text(m.rawValue.capitalized).tag(m)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: DDSpacing.modePickerMaxWidth)
                .disabled(setup.scanSource != .directory)
                .accessibilityHint(
                    setup.scanSource == .directory
                        ? "Selects the type of files to scan"
                        : "Mode is set to Auto for Photos Library"
                )
            }

            Spacer()

            // Preset chips
            VStack(alignment: .trailing, spacing: DDSpacing.xs) {
                Text("Preset")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
                    .textCase(.uppercase)

                presetChips
            }
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    private var presetChips: some View {
        HStack(spacing: DDSpacing.sm) {
            if PresetManager.presetsAvailable(for: setup.mode) {
                ForEach(ScanPreset.allCases) { preset in
                    presetChip(preset)
                }
            } else {
                Text("Per-type defaults")
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
                    .padding(.horizontal, DDSpacing.md)
                    .padding(.vertical, DDSpacing.sm)
                    .background(DDColors.surface2, in: Capsule())
            }
        }
    }

    private func presetChip(_ preset: ScanPreset) -> some View {
        Button {
            withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                applyPreset(preset)
            }
        } label: {
            HStack(spacing: DDSpacing.xs) {
                Image(systemName: preset.icon)
                    .font(DDTypography.label)
                Text(preset.displayName)
                    .font(DDTypography.body)
            }
            .foregroundStyle(activePreset == preset ? DDColors.accent : ddColors.textSecondary)
        }
        .fixedSize()
        .ddGlassInteractivePill(size: .large)
        .overlay {
            if activePreset == preset {
                Capsule()
                    .strokeBorder(DDColors.accent, lineWidth: DDSpacing.selectionStroke)
            }
        }
        .accessibilityHint("Applies \(preset.displayName) settings to the scan")
    }

    // MARK: - Summary Card

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            // Header: "Summary" + "Customize" button
            HStack {
                Text("Summary")
                    .font(DDTypography.sectionTitle)
                    .foregroundStyle(ddColors.textPrimary)
                Spacer()
                Button {
                    showCustomize = true
                } label: {
                    Label("Customize", systemImage: "slider.horizontal.3")
                        .font(DDTypography.body)
                }
                .buttonStyle(.plain)
                .foregroundStyle(DDColors.accent)
            }

            // Natural-language summary
            HStack(spacing: DDSpacing.xs) {
                Image(systemName: "info.circle")
                    .foregroundStyle(DDColors.accent)
                summaryText
            }
            .font(DDTypography.body)
            .foregroundStyle(ddColors.textSecondary)

            // Badge pills row
            badgePills
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    private var summaryText: Text {
        let presetStr = activePreset.map { " \u{B7} \($0.displayName)" } ?? ""

        if case .photosLibrary = setup.scanSource {
            return Text("Scan Photos Library for photo and video duplicates\(presetStr)")
        }

        let dirCount = setup.entries.count
        let dirStr = "\(dirCount) director\(dirCount == 1 ? "y" : "ies")"
        let modeStr = setup.mode.rawValue

        if let count = setup.estimatedFileCount {
            let fileStr = count >= 10_000 ? "10,000+" : "\(count)"
            return Text("Scan \(dirStr) for \(modeStr) duplicates \u{B7} ~\(fileStr) files\(presetStr)")
        } else if setup.isCountingFiles {
            return Text("Scan \(dirStr) for \(modeStr) duplicates \u{B7} counting\u{2026}\(presetStr)")
        } else {
            return Text("Scan \(dirStr) for \(modeStr) duplicates\(presetStr)")
        }
    }

    private var badgePills: some View {
        HStack(spacing: DDSpacing.sm) {
            // Threshold always shown
            summaryPill(icon: "gauge.with.dots.needle.50percent", text: "Threshold: \(setup.threshold)", isAccent: true)

            // Conditional badges
            if setup.content {
                summaryPill(icon: "waveform.circle", text: "Content", isAccent: false)
            }
            if setup.audio {
                summaryPill(icon: "music.note", text: "Audio FP", isAccent: false)
            }
            if setup.hasFilters {
                summaryPill(icon: "line.3.horizontal.decrease", text: "Filters: \(setup.activeFilterCount) active", isAccent: false)
            }
        }
    }

    private func summaryPill(icon: String, text: String, isAccent: Bool) -> some View {
        HStack(spacing: DDSpacing.xs) {
            Image(systemName: icon)
                .font(DDTypography.label)
            Text(text)
                .font(DDTypography.label)
        }
        .foregroundStyle(isAccent ? DDColors.accent : ddColors.textSecondary)
        .ddGlassPill(size: .medium)
    }

    // MARK: - Bottom Bar

    private var bottomBar: some View {
        HStack(spacing: DDSpacing.md) {
            // Left zone: Open Scan, History, Profile
            Button { openReplayFile() } label: {
                Label("Open Scan\u{2026}", systemImage: "doc.badge.arrow.up")
                    .font(DDTypography.body)
            }
            .buttonStyle(.plain)
            .foregroundStyle(ddColors.textSecondary)
            .help("Open a previously saved JSON scan envelope for replay")

            Button { showHistorySheet = true } label: {
                Label("History", systemImage: "clock.arrow.circlepath")
                    .font(DDTypography.body)
            }
            .buttonStyle(.plain)
            .foregroundStyle(ddColors.textSecondary)
            .help("Browse and replay past scan results")

            profileMenu

            // Center zone: validation or summary
            if setup.scanSource == .directory, setup.entries.isEmpty {
                Text("Add directories to start")
                    .font(DDTypography.body)
                    .foregroundStyle(ddColors.textMuted)
            } else if !setup.validationErrors.isEmpty {
                validationMessageRow(
                    messages: setup.validationErrors,
                    color: DDColors.destructive,
                    showPopover: $showAllErrors
                )
            } else if !setup.validationWarnings.isEmpty {
                validationMessageRow(
                    messages: setup.validationWarnings,
                    color: DDColors.warning,
                    showPopover: $showAllWarnings
                )
            } else {
                bottomBarSummary
            }

            Spacer()

            // Right zone: Watch toggle + Start Scan
            if setup.scanSource == .directory {
                Toggle(isOn: Binding(
                    get: { store.watchEnabled },
                    set: { store.watchEnabled = $0 }
                )) {
                    Label("Watch", systemImage: "eye")
                        .font(DDTypography.label)
                }
                .toggleStyle(.checkbox)
                .accessibilityLabel("Keep watching for new files after scan completes")
                .overlay(TooltipView(tooltip: "Keep watching directories for new duplicates after scan completes"))
            }

            Button {
                let config = setup.buildConfig()
                if case .photosLibrary(let scope) = setup.scanSource {
                    store.send(.startPhotosScan(scope, config))
                } else {
                    store.send(.startScan(config))
                }
            } label: {
                Label(store.watchEnabled && setup.scanSource == .directory ? "Scan & Watch" : "Start Scan", systemImage: "play.fill")
                    .font(DDTypography.action)
                    .frame(minWidth: DDSpacing.primaryActionMinWidth)
            }
            .buttonStyle(.glassProminent)
            .controlSize(.large)
            .tint(DDColors.accent)
            .disabled(!store.canStartScan)
            .keyboardShortcut(.return, modifiers: .command)
            .accessibilityHint("Begins scanning selected directories for duplicates")
        }
        .padding(.horizontal, DDSpacing.lg)
        .padding(.vertical, DDSpacing.md)
        .ddGlassChrome()
    }

    private func validationMessageRow(
        messages: [String],
        color: Color,
        showPopover: Binding<Bool>
    ) -> some View {
        let icon = "exclamationmark.triangle.fill"
        return HStack(spacing: DDSpacing.sm) {
            Image(systemName: icon)
                .foregroundStyle(color)
                .font(DDTypography.body)
            Text(messages[0])
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textSecondary)
                .lineLimit(1)
            if messages.count > 1 {
                Text("+\(messages.count - 1) more")
                    .font(DDTypography.label)
                    .foregroundStyle(ddColors.textMuted)
                    .onTapGesture { showPopover.wrappedValue = true }
                    .popover(isPresented: showPopover) {
                        VStack(alignment: .leading, spacing: DDSpacing.sm) {
                            ForEach(messages, id: \.self) { msg in
                                Label(msg, systemImage: icon)
                                    .font(DDTypography.body)
                                    .foregroundStyle(color)
                            }
                        }
                        .padding(DDSpacing.md)
                    }
            }
        }
    }

    private var bottomBarSummary: some View {
        let icon: String = {
            if case .photosLibrary = setup.scanSource {
                return "photo.on.rectangle.angled"
            }
            return setup.mode.systemImageName
        }()
        return HStack(spacing: DDSpacing.sm) {
            Image(systemName: icon)
                .foregroundStyle(DDColors.accent)
            Text(bottomBarText)
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textSecondary)
                .lineLimit(1)
        }
    }

    private var bottomBarText: String {
        let presetStr = activePreset.map { " \u{B7} \($0.displayName)" } ?? ""
        if case .photosLibrary = setup.scanSource {
            return "Photos Library \u{B7} threshold \(setup.threshold)\(presetStr)"
        }
        let modeStr = setup.mode.rawValue.capitalized
        let dirCount = setup.entries.count
        return "\(modeStr) scan \u{B7} \(dirCount) dir\(dirCount == 1 ? "" : "s") \u{B7} threshold \(setup.threshold)\(presetStr)"
    }

    // MARK: - Profile

    private var profileMenu: some View {
        SetupShared.profileMenu(
            store: store,
            activePreset: $activePreset,
            profileError: $profileError,
            showSaveProfileSheet: $showSaveProfileSheet,
            saveProfileName: $saveProfileName
        )
    }

    private func saveProfile() async {
        let result = await SetupShared.saveProfile(
            name: saveProfileName,
            store: store
        )
        profileError = result.error
        if result.dismiss { showSaveProfileSheet = false }
    }

    // MARK: - Preset Logic

    private func applyPreset(_ preset: ScanPreset) {
        activePreset = preset
        PresetManager.apply(preset: preset, mode: setup.mode, to: store)
    }

    /// Re-detect whether the current setup state matches any preset.
    /// Called via onChange when any preset-controlled property changes.
    private func detectPresetChange() {
        let detected = PresetManager.detectPreset(for: setup.mode, from: setup)
        if detected != activePreset {
            activePreset = detected
        }
    }

    // MARK: - Replay

    private func openReplayFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.ddScanResults, .json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select a scan envelope to replay"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        store.send(.startReplay(url, setup.buildConfig()))
    }
}

// MARK: - Preview

#if DEBUG
#Preview("Scan Setup") {
    ScanSetupView(store: PreviewFixtures.sessionStore())
        .frame(width: 900, height: 700)
        .environment(PreviewFixtures.appState())
}
#endif

// MARK: - Resume Session Card

private struct ResumeSessionCard: View {
    let sessionId: String
    let sessionInfo: SessionInfo?
    let onResume: () -> Void
    let onDiscard: () -> Void
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                HStack(spacing: DDSpacing.sm) {
                    Text("Previous Scan Paused")
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textPrimary)

                    if let info = sessionInfo {
                        Text(info.mode.capitalized)
                            .font(DDTypography.metadata)
                            .foregroundStyle(DDColors.accent)
                            .ddGlassPill(size: .small)
                    }
                }

                if let info = sessionInfo {
                    HStack(spacing: DDSpacing.sm) {
                        // Directory names
                        let dirNames = info.directories.map { ($0 as NSString).lastPathComponent }
                        Text(dirNames.joined(separator: ", "))
                            .font(DDTypography.metadata)
                            .foregroundStyle(ddColors.textSecondary)
                            .lineLimit(1)

                        if info.progressPercent > 0 {
                            Text("\u{2022}")
                                .font(DDTypography.metadata)
                                .foregroundStyle(ddColors.textMuted)
                            Text("\(info.progressPercent)% complete")
                                .font(DDTypography.metadata)
                                .foregroundStyle(DDColors.accent)
                        }

                        if let relativeTime = info.relativePausedAt {
                            Text("\u{2022}")
                                .font(DDTypography.metadata)
                                .foregroundStyle(ddColors.textMuted)
                            Text(relativeTime)
                                .font(DDTypography.metadata)
                                .foregroundStyle(ddColors.textMuted)
                        }
                    }
                } else {
                    Text("Session \(sessionId)")
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textSecondary)
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel(accessibilityText)
            Spacer()
            Button("Discard", action: onDiscard)
                .buttonStyle(.glass)
                .tint(DDColors.destructive)
            Button("Resume", action: onResume)
                .buttonStyle(.glassProminent)
                .tint(DDColors.accent)
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    private var accessibilityText: String {
        guard let info = sessionInfo else {
            return "Previous scan paused. Session \(sessionId)"
        }
        let dirNames = info.directories.map { ($0 as NSString).lastPathComponent }
        var text = "Previous \(info.mode) scan paused. Directories: \(dirNames.joined(separator: ", "))"
        if info.progressPercent > 0 {
            text += ". \(info.progressPercent)% complete"
        }
        if let relativeTime = info.relativePausedAt {
            text += ". Paused \(relativeTime)"
        }
        return text
    }
}

// MARK: - Tooltip Helper

/// Bridges an NSView tooltip to SwiftUI — `.help()` is unreliable on some control types.
private struct TooltipView: NSViewRepresentable {
    let tooltip: String

    func makeNSView(context: Context) -> NSView {
        let view = HitTransparentView()
        view.toolTip = tooltip
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        nsView.toolTip = tooltip
    }

    /// NSView subclass that passes all hit tests through to the view beneath,
    /// allowing the tooltip overlay to sit on top of interactive controls
    /// (like the Watch checkbox) without intercepting clicks.
    private class HitTransparentView: NSView {
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
    }
}
