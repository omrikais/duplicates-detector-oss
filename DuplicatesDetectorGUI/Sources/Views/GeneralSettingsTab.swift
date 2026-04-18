import SwiftUI
import UniformTypeIdentifiers

/// General preferences: CLI binary path, external tools, default mode/keep/action,
/// notification preferences, CLI config sync, profiles.
struct GeneralSettingsTab: View {
    @Environment(AppState.self) private var appState
    @Environment(ObservableDefaults.self) private var defaults
    @Environment(\.ddColors) private var ddColors
    @State private var binaryPath: String = ""
    @State private var isDetecting = false
    @State private var showFilePicker = false
    @State private var profiles: [ProfileEntry] = []
    @State private var showDeleteConfirmation: String?
    @State private var showImportConfirmation = false
    @State private var showExportConfirmation = false
    @State private var statusMessage: String?
    @State private var profilesDirectoryPath = ""
    @State private var configFilePathDisplay = ""
    // External tools
    @State private var showFFmpegPicker = false
    @State private var showFFprobePicker = false
    @State private var toolRevalidateTask: Task<Void, Never>?
    // CLI config notice
    @State private var showCLIConfigNotice = false
    // Edit profile
    @State private var editingProfileName: String?
    @State private var editingProfileData: ProfileData?
    @State private var editProfileError: String?
    // Snapshot of weight-affecting fields at load time, used to detect
    // changes that invalidate the stored weights table.
    @State private var editProfileOriginalMode: String?
    @State private var editProfileOriginalContent: Bool?
    @State private var editProfileOriginalAudio: Bool?

    var body: some View {
        @Bindable var defaults = defaults
        Form {
            cliBinarySection
            externalToolsSection(defaults: defaults)
            defaultsSection(defaults: defaults)
            profilesSection
            cliConfigSection
        }
        .formStyle(.grouped)
        .onDisappear {
            toolRevalidateTask?.cancel()
        }
        .task { await refreshState() }
        .sheet(isPresented: Binding(
            get: { editingProfileName != nil },
            set: { if !$0 { editingProfileName = nil; editingProfileData = nil; editProfileError = nil } }
        )) {
            if let name = editingProfileName {
                EditProfileSheet(
                    profileName: name,
                    profileData: $editingProfileData,
                    errorMessage: editProfileError,
                    onCancel: {
                        editingProfileName = nil
                        editingProfileData = nil
                        editProfileError = nil
                    },
                    onSave: {
                        Task { await saveEditedProfile() }
                    }
                )
                .presentationBackground(.ultraThinMaterial)
            }
        }
    }

    // MARK: - CLI Binary

    @ViewBuilder
    private var cliBinarySection: some View {
        Section("CLI Binary") {
            LabeledContent("Path") {
                Text(binaryPath.isEmpty ? "Not found" : binaryPath)
                    .foregroundStyle(binaryPath.isEmpty ? ddColors.textSecondary : ddColors.textPrimary)
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            HStack {
                Button("Browse\u{2026}") { showFilePicker = true }
                Button("Auto-detect") {
                    Task { await autoDetect() }
                }
                .disabled(isDetecting)
            }
            .fileImporter(
                isPresented: $showFilePicker,
                allowedContentTypes: [.unixExecutable, .item],
                allowsMultipleSelection: false
            ) { result in
                guard case .success(let urls) = result, let url = urls.first else { return }
                Task { await selectBinary(url.path) }
            }
        }
    }

    // MARK: - External Tools

    @ViewBuilder
    private func externalToolsSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section {
            LabeledContent("ffmpeg") {
                HStack {
                    TextField("Auto-detect from PATH", text: $defaults.ffmpegPath)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: defaults.ffmpegPath) { _, _ in
                            scheduleToolRevalidation()
                        }
                    Button("Browse\u{2026}") { showFFmpegPicker = true }
                }
            }
            .fileImporter(
                isPresented: $showFFmpegPicker,
                allowedContentTypes: [.unixExecutable, .item],
                allowsMultipleSelection: false
            ) { result in
                if case .success(let urls) = result, let url = urls.first {
                    defaults.ffmpegPath = url.path
                }
            }

            LabeledContent("ffprobe") {
                HStack {
                    TextField("Auto-detect from PATH", text: $defaults.ffprobePath)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: defaults.ffprobePath) { _, _ in
                            scheduleToolRevalidation()
                        }
                    Button("Browse\u{2026}") { showFFprobePicker = true }
                }
            }
            .fileImporter(
                isPresented: $showFFprobePicker,
                allowedContentTypes: [.unixExecutable, .item],
                allowsMultipleSelection: false
            ) { result in
                if case .success(let urls) = result, let url = urls.first {
                    defaults.ffprobePath = url.path
                }
            }
        } header: {
            Text("External Tools")
        } footer: {
            Text("Leave empty to auto-detect from PATH. These paths help verify the correct binaries are found.")
        }
    }

    // MARK: - Defaults

    @ViewBuilder
    private func defaultsSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Default Settings") {
            Picker("Scan Mode", selection: $defaults.mode) {
                ForEach(ScanMode.allCases, id: \.self) { mode in
                    Text(mode.rawValue.capitalized).tag(mode)
                }
            }
            .onChange(of: defaults.mode) { _, _ in
                AppDefaults.normalizeStoredDefaults()
                defaults.reload()
            }

            Picker("Keep Strategy", selection: $defaults.keep) {
                Text("None").tag(nil as KeepStrategy?)
                ForEach(KeepStrategy.allCases, id: \.self) { strategy in
                    Text(strategy.displayName)
                        .tag(strategy as KeepStrategy?)
                }
            }

            Picker("Action", selection: $defaults.action) {
                // moveTo excluded: requires a per-session destination that
                // Preferences cannot capture (apply(to:) normalizes it to .trash).
                ForEach([ActionType.delete, .trash], id: \.self) { action in
                    Text(action.displayName).tag(action)
                }
            }
            .accessibilityHint("Sets the default action when duplicates are found")

            Picker("Confirmations", selection: $defaults.confirmationPref) {
                Text("Always").tag(ConfirmationPreference.always)
                Text("High-risk only").tag(ConfirmationPreference.highRiskOnly)
                Text("Never").tag(ConfirmationPreference.never)
            }
            .accessibilityHint("Controls when confirmation dialogs appear before file actions")

        }
    }

    // MARK: - Profiles

    @ViewBuilder
    private var profilesSection: some View {
        Section("Profiles") {
            if profiles.isEmpty {
                Text("No profiles found")
                    .foregroundStyle(ddColors.textSecondary)
            } else {
                ForEach(profiles) { profile in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(profile.name)
                            Text(profile.lastModified, style: .date)
                                .font(DDTypography.metadata)
                                .foregroundStyle(ddColors.textMuted)
                        }
                        Spacer()
                        Button {
                            Task { await startEditingProfile(profile.name) }
                        } label: {
                            Image(systemName: "pencil")
                        }
                        .buttonStyle(.borderless)
                        .accessibilityLabel("Edit profile \(profile.name)")

                        Button(role: .destructive) {
                            showDeleteConfirmation = profile.name
                        } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.borderless)
                        .accessibilityLabel("Delete profile \(profile.name)")
                        .confirmationDialog(
                            "Delete profile \"\(profile.name)\"?",
                            isPresented: Binding(
                                get: { showDeleteConfirmation == profile.name },
                                set: { if !$0 { showDeleteConfirmation = nil } }
                            ),
                            titleVisibility: .visible
                        ) {
                            Button("Delete", role: .destructive) {
                                Task { await deleteProfile(profile.name) }
                            }
                        }
                    }
                }
            }

            Text("Profiles are stored at \(profilesDirectoryPath.isEmpty ? "..." : profilesDirectoryPath) and shared with the CLI.")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textSecondary)
        }
    }

    // MARK: - CLI Config Sync

    @ViewBuilder
    private var cliConfigSection: some View {
        Section("CLI Configuration") {
            if showCLIConfigNotice {
                HStack(alignment: .top) {
                    Image(systemName: "info.circle.fill")
                        .foregroundStyle(DDColors.info)
                    VStack(alignment: .leading, spacing: DDSpacing.xxs) {
                        Text("CLI configuration file found")
                            .font(DDTypography.metadata).bold()
                        Text("The GUI uses its own defaults. Use \u{201C}Import CLI Config\u{201D} below to apply CLI settings.")
                            .font(DDTypography.metadata)
                    }
                    Spacer()
                    Button {
                        dismissCLIConfigNotice()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(ddColors.textSecondary)
                    }
                    .buttonStyle(.borderless)
                }
            }

            HStack {
                Button("Import CLI Config\u{2026}") { showImportConfirmation = true }
                    .confirmationDialog(
                        "Import CLI configuration?",
                        isPresented: $showImportConfirmation,
                        titleVisibility: .visible
                    ) {
                        Button("Import") { Task { await importCLIConfig() } }
                    } message: {
                        Text("This will replace your current app defaults with the CLI's config.toml settings.")
                    }

                Button("Export to CLI Config\u{2026}") { showExportConfirmation = true }
                    .confirmationDialog(
                        "Export to CLI configuration?",
                        isPresented: $showExportConfirmation,
                        titleVisibility: .visible
                    ) {
                        Button("Export") { Task { await exportCLIConfig() } }
                    } message: {
                        Text("This will overwrite the CLI's config.toml with your current app defaults.")
                    }
            }

            if let message = statusMessage {
                Text(message)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
            }

            Text("CLI config file: \(configFilePathDisplay.isEmpty ? "..." : configFilePathDisplay)")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
                .textSelection(.enabled)
        }
    }

    // MARK: - Actions

    private func refreshState() async {
        binaryPath = await appState.store.bridge.binaryPath ?? ""
        profilesDirectoryPath = await ProfileManager.shared.resolvedProfilesDirectory().path
        let configURL = await ProfileManager.shared.resolvedConfigFilePath()
        configFilePathDisplay = configURL.path
        do {
            profiles = try await ProfileManager.shared.listProfiles()
        } catch {
            profiles = []
        }
        // Launch-time CLI config notice
        if !AppDefaults.hasSeenCLIConfigNotice {
            if FileManager.default.fileExists(atPath: configURL.path) {
                showCLIConfigNotice = true
            }
        }
    }

    private func autoDetect() async {
        isDetecting = true
        defer { isDetecting = false }
        await appState.store.bridge.clearPersistedUserConfiguredPath()
        let status = await appState.store.bridge.validateDependencies(refreshShellEnvironment: true)
        appState.dependencyStatus = status
        binaryPath = await appState.store.bridge.binaryPath ?? ""
    }

    private func scheduleToolRevalidation() {
        toolRevalidateTask?.cancel()
        toolRevalidateTask = Task {
            try? await Task.sleep(for: .milliseconds(800))
            guard !Task.isCancelled else { return }
            let status = await appState.store.bridge.validateDependencies()
            appState.dependencyStatus = status
        }
    }

    private func selectBinary(_ path: String) async {
        let status = await appState.store.bridge.validateDependencies(userConfiguredPath: path)
        appState.dependencyStatus = status
        binaryPath = await appState.store.bridge.binaryPath ?? ""
    }

    private func deleteProfile(_ name: String) async {
        do {
            try await ProfileManager.shared.deleteProfile(name: name)
            profiles = (try? await ProfileManager.shared.listProfiles()) ?? []
        } catch {
            statusMessage = "Failed to delete: \(error.localizedDescription)"
        }
    }

    private func dismissCLIConfigNotice() {
        showCLIConfigNotice = false
        AppDefaults.hasSeenCLIConfigNotice = true
    }

    private func startEditingProfile(_ name: String) async {
        do {
            let data = try await ProfileManager.shared.loadProfile(name: name)
            editingProfileData = data
            editProfileError = nil
            editProfileOriginalMode = data.mode
            editProfileOriginalContent = data.content
            editProfileOriginalAudio = data.audio
            editingProfileName = name
        } catch {
            statusMessage = "Failed to load profile: \(error.localizedDescription)"
        }
    }

    private func saveEditedProfile() async {
        guard let name = editingProfileName, var data = editingProfileData else { return }
        // Clear stale weights when mode/content/audio changed — the sheet
        // displays weights read-only, so they can't be manually corrected.
        // Clearing lets applyProfile() regenerate mode-appropriate defaults.
        if data.mode != editProfileOriginalMode
            || data.content != editProfileOriginalContent
            || data.audio != editProfileOriginalAudio
        {
            data.weights = nil
        }
        // Normalize mode-incompatible fields unconditionally — the sheet
        // exposes toggles for content/audio/keep that the user can set to
        // combinations the CLI rejects.
        data.normalizeModeIncompatibilities()
        do {
            try await ProfileManager.shared.saveProfile(name: name, data: data)
            editingProfileName = nil
            editingProfileData = nil
            editProfileError = nil
            profiles = (try? await ProfileManager.shared.listProfiles()) ?? []
        } catch {
            editProfileError = "Save failed: \(error.localizedDescription)"
        }
    }

    private func importCLIConfig() async {
        do {
            guard await ProfileManager.shared.cliConfigExists() else {
                statusMessage = "No CLI config file found."
                return
            }
            let data = try await ProfileManager.shared.loadCLIConfig()
            guard !data.isEmpty else {
                statusMessage = "CLI config contains no settings to import."
                return
            }
            // Preserve GUI-only settings that config.toml can never restore.
            let savedFFmpegPath = AppDefaults.ffmpegPath
            let savedFFprobePath = AppDefaults.ffprobePath
            let savedConfirmationPref = AppDefaults.confirmationPref
            let savedHasSeenNotice = AppDefaults.hasSeenCLIConfigNotice
            // Reset to factory defaults first so keys absent from the CLI
            // config revert instead of keeping stale GUI customizations.
            // Per-mode extensions (videoExtensions, imageExtensions, audioExtensions)
            // are intentionally NOT preserved — they have no CLI equivalent and would
            // shadow the imported global `extensions` value via the mode→global fallback.
            AppDefaults.resetAll()
            AppDefaults.registerDefaults()
            // Restore GUI-only settings
            AppDefaults.ffmpegPath = savedFFmpegPath
            AppDefaults.ffprobePath = savedFFprobePath
            AppDefaults.confirmationPref = savedConfirmationPref
            AppDefaults.hasSeenCLIConfigNotice = savedHasSeenNotice
            let hadMoveTo = data.action == "move-to"
            AppDefaults.apply(from: data)
            defaults.reload()
            if hadMoveTo {
                statusMessage = "CLI config imported. Note: \"move-to\" action was changed to \"trash\" (destination cannot be saved as a default)."
            } else {
                statusMessage = "CLI config imported successfully."
            }
        } catch {
            statusMessage = "Import failed: \(error.localizedDescription)"
        }
    }

    private func exportCLIConfig() async {
        do {
            // Load existing config first so we preserve CLI-only keys
            // (weights, filters, hash_size, etc.) that AppDefaults doesn't track.
            var existing = (try? await ProfileManager.shared.loadCLIConfig()) ?? ProfileData()
            let overlay = ProfileData.fromAppDefaults()
            existing.merge(from: overlay)
            try await ProfileManager.shared.saveCLIConfig(existing)
            statusMessage = "Exported to CLI config successfully."
        } catch {
            statusMessage = "Export failed: \(error.localizedDescription)"
        }
    }
}

// MARK: - EditProfileSheet

/// Sheet for editing a single CLI profile's fields.
///
/// Extracted from `GeneralSettingsTab.editProfileSheet(name:)` to
/// eliminate inline Binding gymnastics and improve readability.
private struct EditProfileSheet: View {
    let profileName: String
    @Binding var profileData: ProfileData?
    let errorMessage: String?
    let onCancel: () -> Void
    let onSave: () -> Void

    /// Non-optional binding derived from the parent's optional `profileData`.
    private var data: Binding<ProfileData> {
        Binding(
            get: { profileData ?? ProfileData() },
            set: { profileData = $0 }
        )
    }

    var body: some View {
        VStack(spacing: DDSpacing.md) {
            Text("Edit Profile: \(profileName)")
                .font(DDTypography.sectionTitle)

            Form {
                Picker("Mode", selection: Binding(
                    get: { ScanMode(rawValue: data.wrappedValue.mode ?? "video") ?? .video },
                    set: { data.wrappedValue.mode = $0.rawValue }
                )) {
                    ForEach(ScanMode.allCases, id: \.self) { mode in
                        Text(mode.rawValue.capitalized).tag(mode)
                    }
                }

                LabeledContent("Threshold") {
                    HStack {
                        Slider(value: Binding(
                            get: { Double(data.wrappedValue.threshold ?? 50) },
                            set: { data.wrappedValue.threshold = Int($0.rounded()) }
                        ), in: 0...100)
                        Text("\(data.wrappedValue.threshold ?? 50)")
                            .font(DDTypography.sliderReadout)
                            .frame(width: 30, alignment: .trailing)
                    }
                }

                Picker("Keep Strategy", selection: Binding(
                    get: { data.wrappedValue.keep.flatMap(KeepStrategy.init(rawValue:)) },
                    set: { data.wrappedValue.keep = $0?.rawValue }
                )) {
                    Text("None").tag(nil as KeepStrategy?)
                    ForEach(KeepStrategy.allCases, id: \.self) { strategy in
                        Text(strategy.displayName)
                            .tag(strategy as KeepStrategy?)
                    }
                }

                Picker("Action", selection: Binding(
                    get: { ActionType(rawValue: data.wrappedValue.action ?? "delete") ?? .delete },
                    set: { data.wrappedValue.action = $0.rawValue }
                )) {
                    // Only actions that need no extra context — move-to
                    // requires a destination field this sheet doesn't have;
                    // hardlink/symlink/reflink are CLI-side only.
                    ForEach([ActionType.delete, .trash], id: \.self) { action in
                        Text(action.displayName).tag(action)
                    }
                }

                Toggle("Content hashing", isOn: Binding(
                    get: { data.wrappedValue.content ?? false },
                    set: { data.wrappedValue.content = $0 }
                ))

                Toggle("Audio fingerprinting", isOn: Binding(
                    get: { data.wrappedValue.audio ?? false },
                    set: { data.wrappedValue.audio = $0 }
                ))

                if let weights = data.wrappedValue.weights, !weights.isEmpty {
                    Section("Weights") {
                        ForEach(weights.sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                            LabeledContent(key) {
                                Text(value == value.rounded(.towardZero)
                                     ? "\(Int(value))"
                                     : String(format: "%.1f", value))
                                    .font(DDTypography.sliderReadout)
                            }
                        }
                    }
                }
            }
            .formStyle(.grouped)
            .frame(height: 360)

            if let error = errorMessage {
                Text(error)
                    .font(DDTypography.metadata)
                    .foregroundStyle(DDColors.destructive)
            }

            HStack {
                Button("Cancel") { onCancel() }
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Save") { onSave() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding()
        .frame(width: 420)
    }
}
