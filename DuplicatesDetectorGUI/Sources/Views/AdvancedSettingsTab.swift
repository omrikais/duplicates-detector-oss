import AppKit
import SwiftUI

/// Advanced preferences: extensions (per-mode), exclude, log, ignore list, debug, reset.
struct AdvancedSettingsTab: View {
    @Environment(AppState.self) private var appState
    @Environment(ObservableDefaults.self) private var defaults
    @Environment(\.ddColors) private var ddColors
    @State private var showResetConfirmation = false
    @State private var showLogPicker = false
    @State private var ignoreListPath = ""
    // Per-mode extensions picker state (view-local, not an AppDefault)
    @State private var extensionsMode: ScanMode = .video

    var body: some View {
        @Bindable var defaults = defaults
        Form {
            extensionsSection(defaults: defaults)
            excludeSection(defaults: defaults)
            loggingSection(defaults: defaults)
            ignoreListSection
            debugSection(defaults: defaults)
            resetSection
        }
        .formStyle(.grouped)
        .task { ignoreListPath = await IgnoreListManager.shared.resolvedDefaultPath().path }
    }

    // MARK: - Sections

    @ViewBuilder
    private func extensionsSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section {
            TextField("Global extensions (comma-separated, e.g. mp4,mkv,avi)", text: $defaults.extensions)
                .textFieldStyle(.roundedBorder)

            Picker("Mode override", selection: $extensionsMode) {
                Text("Video").tag(ScanMode.video)
                Text("Image").tag(ScanMode.image)
                Text("Audio").tag(ScanMode.audio)
                Text("Document").tag(ScanMode.document)
            }
            .pickerStyle(.segmented)

            TextField(
                "Override for \(extensionsMode.rawValue) mode (comma-separated)",
                text: currentModeExtensionsBinding(defaults: defaults)
            )
            .textFieldStyle(.roundedBorder)
        } header: {
            Text("File Extensions")
        } footer: {
            Text("Mode-specific overrides take precedence over the global setting. Leave both empty to use built-in defaults.")
        }
    }

    private func currentModeExtensionsBinding(defaults: ObservableDefaults) -> Binding<String> {
        Binding(
            get: {
                switch extensionsMode {
                case .video: defaults.videoExtensions
                case .image: defaults.imageExtensions
                case .audio: defaults.audioExtensions
                case .document: defaults.documentExtensions
                case .auto: defaults.extensions
                }
            },
            set: {
                switch extensionsMode {
                case .video: defaults.videoExtensions = $0
                case .image: defaults.imageExtensions = $0
                case .audio: defaults.audioExtensions = $0
                case .document: defaults.documentExtensions = $0
                case .auto: defaults.extensions = $0
                }
            }
        )
    }

    @ViewBuilder
    private func excludeSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Exclude Patterns") {
            TextField("Glob patterns (comma-separated, e.g. *.tmp,backup/*)", text: $defaults.exclude)
                .textFieldStyle(.roundedBorder)

            Text("Files matching these patterns will be skipped during scanning.")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
        }
    }

    @ViewBuilder
    private func loggingSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Action Log") {
            HStack {
                TextField("Default log file path", text: $defaults.log)
                    .textFieldStyle(.roundedBorder)
                Button("Browse\u{2026}") { showLogPicker = true }
            }
            .fileImporter(
                isPresented: $showLogPicker,
                allowedContentTypes: [.json, .item],
                allowsMultipleSelection: false
            ) { result in
                if case .success(let urls) = result, let url = urls.first {
                    defaults.log = url.path
                }
            }

            Text("When set, all file actions are logged to this file for undo support.")
                .font(DDTypography.metadata)
                .foregroundStyle(ddColors.textMuted)
        }
    }

    @ViewBuilder
    private var ignoreListSection: some View {
        Section("Ignore List") {
            LabeledContent("Location") {
                Text(ignoreListPath.isEmpty ? "..." : ignoreListPath)
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Button("Open in Finder") {
                let url = URL(fileURLWithPath: ignoreListPath)
                let dir = url.deletingLastPathComponent()
                NSWorkspace.shared.selectFile(
                    url.path,
                    inFileViewerRootedAtPath: dir.path
                )
            }
            .disabled(ignoreListPath.isEmpty)
        }
    }

    @ViewBuilder
    private func debugSection(defaults: ObservableDefaults) -> some View {
        @Bindable var defaults = defaults
        Section("Debug") {
            Toggle("Verbose output by default", isOn: $defaults.verbose)
        }
    }

    @ViewBuilder
    private var resetSection: some View {
        Section {
            Button("Reset All Defaults", role: .destructive) {
                showResetConfirmation = true
            }
            .accessibilityHint("Restores all preferences to factory defaults")
            .confirmationDialog(
                "Reset all preferences to defaults?",
                isPresented: $showResetConfirmation,
                titleVisibility: .visible
            ) {
                Button("Reset", role: .destructive) {
                    AppDefaults.resetAll()
                    CLIBridge.clearPersistedBinaryPath()
                    defaults.reload()
                    Task {
                        let status = await appState.store.bridge.validateDependencies(
                            refreshShellEnvironment: true
                        )
                        appState.dependencyStatus = status
                    }
                }
            } message: {
                Text("This will clear all custom defaults. Your profiles and CLI configuration are not affected.")
            }
        }
    }
}
