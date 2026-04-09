import AppKit
import SwiftUI

/// Displays what the user can do right now, backed by dependency availability.
///
/// Leads with capability cards ("What You Can Do"), with tool details
/// in a collapsible section below. Auto-advances when minimum requirements are met.
struct DependencyCheckView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.ddColors) private var ddColors
    @ScaledMetric(relativeTo: .title) private var headerIconSize: CGFloat = 40
    @State private var showFilePicker = false
    @State private var toolDetailsExpanded = false
    @State private var installTask: Task<Void, Never>?
    @State private var installer: DependencyInstaller?

    let status: DependencyStatus

    var body: some View {
        ZStack {
            VStack(spacing: DDSpacing.lg) {
                branding
                capabilityGrid
                toolDetails
                guidance
                buttons
            }
            .padding(DDDensity.regular)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(DDColors.surface0)
            .fileImporter(
                isPresented: $showFilePicker,
                allowedContentTypes: [.unixExecutable, .item],
                allowsMultipleSelection: false
            ) { result in
                if case .success(let urls) = result, let url = urls.first {
                    Task {
                        await retryWithPath(url.path(percentEncoded: false))
                    }
                }
            }
            .opacity(appState.installModel == nil ? 1 : 0)

            if let installModel = appState.installModel {
                if installModel.homebrewMissing {
                    HomebrewMissingView(
                        onCopy: {},
                        onBack: { finishInstallation() }
                    )
                    .transition(.opacity)
                } else {
                    InstallProgressView(
                        model: installModel,
                        onCancel: { cancelInstallation() },
                        onDone: { finishInstallation() },
                        onRetryFailed: { Task { await startInstallation() } }
                    )
                    .transition(.opacity)
                }
            }
        }
        .animation(reduceMotion ? .none : DDMotion.snappy, value: appState.installModel != nil)
    }

    // MARK: - Branding

    private var branding: some View {
        VStack(spacing: DDSpacing.sm) {
            Image(systemName: "magnifyingglass.circle")
                .font(.system(size: headerIconSize, weight: .medium))
                .foregroundStyle(DDColors.accent)

            Text("Duplicates Detector")
                .font(DDTypography.heading)

            if let version = status.cli.version {
                Text(version)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textSecondary)
            }
        }
    }

    // MARK: - Capability Grid

    private var capabilityGrid: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("What You Can Do")
                .font(DDTypography.heading)
                .padding(.bottom, DDSpacing.xs)

            LazyVGrid(
                columns: [
                    GridItem(.flexible(), spacing: DDSpacing.sm),
                    GridItem(.flexible(), spacing: DDSpacing.sm),
                    GridItem(.flexible(), spacing: DDSpacing.sm),
                ],
                spacing: DDSpacing.sm
            ) {
                capabilityCard(
                    "Video Scanning",
                    icon: "film.circle.fill", iconOff: "film.circle",
                    available: status.canScanVideo
                )
                capabilityCard(
                    "Image Scanning",
                    icon: "photo.circle.fill", iconOff: "photo.circle",
                    available: status.canScanImage
                )
                capabilityCard(
                    "Audio Scanning",
                    icon: "waveform.circle.fill", iconOff: "waveform.circle",
                    available: status.canScanAudio
                )
                capabilityCard(
                    "Content Hashing",
                    icon: "number.circle.fill", iconOff: "number.circle",
                    available: status.canContentHash
                )
                capabilityCard(
                    "Audio Fingerprinting",
                    icon: "waveform.badge.magnifyingglass", iconOff: "waveform.badge.magnifyingglass",
                    available: status.canFingerprint
                )
            }
        }
    }

    private func capabilityCard(_ label: String, icon: String, iconOff: String, available: Bool) -> some View {
        VStack(spacing: DDSpacing.sm) {
            Image(systemName: available ? icon : iconOff)
                .font(DDTypography.heading)
                .foregroundStyle(available ? DDColors.success : DDColors.surface3)

            Text(label)
                .font(DDTypography.label)
                .foregroundStyle(available ? ddColors.textPrimary : ddColors.textSecondary)
                .multilineTextAlignment(.center)

            Text(available ? "Available" : "Unavailable")
                .font(DDTypography.label)
                .foregroundStyle(available ? DDColors.success : DDColors.warning)
        }
        .frame(maxWidth: .infinity)
        .padding(DDDensity.regular)
        .ddGlassCard()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label), \(available ? "available" : "unavailable")")
    }

    // MARK: - Tool Details

    private var toolDetails: some View {
        DisclosureGroup(isExpanded: $toolDetailsExpanded) {
            VStack(alignment: .leading, spacing: DDSpacing.xs) {
                ForEach(status.allTools, id: \.name) { tool in
                    toolRow(tool)
                }
            }
            .padding(.top, DDSpacing.sm)
        } label: {
            Label("Tool Details", systemImage: "wrench.and.screwdriver")
                .font(DDTypography.body)
        }
        .padding(DDDensity.regular)
        .ddGlassCard()
    }

    private func toolRow(_ tool: ToolStatus) -> some View {
        HStack {
            Image(systemName: tool.isAvailable ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundStyle(toolStatusColor(tool))

            Text(tool.name)
                .font(DDTypography.monospaced)

            Spacer()

            if tool.isAvailable {
                if let version = tool.version {
                    Text(version)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textSecondary)
                        .lineLimit(1)
                }
                if let path = tool.path {
                    Text(abbreviatePath(path))
                        .font(DDTypography.label)
                        .foregroundStyle(ddColors.textMuted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            } else {
                if let command = installCommand(for: tool.name) {
                    Text(command)
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textSecondary)
                        .textSelection(.enabled)

                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(command, forType: .string)
                    } label: {
                        Image(systemName: "doc.on.clipboard")
                            .font(DDTypography.label)
                    }
                    .buttonStyle(.plain)
                    .help("Copy install command")
                    .accessibilityLabel("Copy install command for \(tool.name)")
                } else {
                    Text(tool.isRequired ? "Required" : "Optional")
                        .font(DDTypography.label)
                        .foregroundStyle(tool.isRequired ? DDColors.destructive : DDColors.warning)
                }
            }
        }
        .padding(.vertical, DDSpacing.xs)
        .accessibilityValue(tool.isAvailable ? "Installed" : "Not found")
    }

    private func toolStatusColor(_ tool: ToolStatus) -> Color {
        if tool.isAvailable {
            return DDColors.success
        }
        return tool.isRequired ? DDColors.destructive : DDColors.warning
    }

    // MARK: - Guidance

    @ViewBuilder
    private var guidance: some View {
        if !status.cli.isAvailable {
            guidanceText("Install the CLI: pip install duplicates-detector")
        } else if !status.ffprobe.isAvailable {
            guidanceText("Install FFmpeg for video support: brew install ffmpeg")
        }
    }

    private func guidanceText(_ text: String) -> some View {
        Text(text)
            .font(DDTypography.body)
            .foregroundStyle(ddColors.textSecondary)
    }

    // MARK: - Buttons

    private var buttons: some View {
        HStack(spacing: DDSpacing.md) {
            Button("Retry") {
                Task { await retryWithPath(nil) }
            }
            .buttonStyle(.glass)
            .disabled(appState.isCheckingDependencies || appState.isInstalling)

            if !status.cli.isAvailable {
                Button("Browse\u{2026}") {
                    showFilePicker = true
                }
                .buttonStyle(.glass)
                .disabled(appState.isCheckingDependencies || appState.isInstalling)
            }

            if status.hasMissingDependencies {
                Button {
                    Task { await startInstallation() }
                } label: {
                    Label("Install Missing", systemImage: "arrow.down.circle")
                }
                .buttonStyle(.glassProminent)
                .disabled(appState.isCheckingDependencies || appState.isInstalling)
            }

            Button("Continue \u{2192}") {
                withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                    appState.hasCompletedOnboarding = true
                    appState.hasPassedDependencyCheck = true
                }
            }
            .disabled(!status.meetsMinimumRequirements)
            .buttonStyle(.glassProminent)
        }
    }

    // MARK: - Helpers

    private func retryWithPath(_ path: String?) async {
        appState.isCheckingDependencies = true
        let newStatus = await appState.store.bridge.validateDependencies(
            userConfiguredPath: path,
            refreshShellEnvironment: true
        )
        appState.dependencyStatus = newStatus
        appState.isCheckingDependencies = false
        if newStatus.meetsMinimumRequirements {
            withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                appState.hasCompletedOnboarding = true
                appState.hasPassedDependencyCheck = true
            }
        }
    }

    // MARK: - Installation

    private func startInstallation() async {
        let env = await appState.store.bridge.resolvedEnvironment()
        let installer = DependencyInstaller(shellEnvironment: env)
        self.installer = installer
        let cliPython = await appState.store.bridge.cliPythonPath()
        let brewPath = installer.locateBrew()
        let isBundled = appState.store.bridge.hasBundledCLI()
        let plan = installer.buildPlan(for: status, cliPython: cliPython, brewPath: brewPath, isBundled: isBundled)

        guard !plan.steps.isEmpty || plan.homebrewMissing else { return }

        let model = InstallProgressModel(
            steps: plan.steps.map { ($0.name, $0.displayName) }
        )

        // No runnable steps — show the Homebrew notice immediately.
        if plan.homebrewMissing && plan.steps.isEmpty {
            model.homebrewMissing = true
            withAnimation(reduceMotion ? nil : DDMotion.snappy) {
                appState.installModel = model
            }
            return
        }

        withAnimation(reduceMotion ? nil : DDMotion.snappy) {
            appState.installModel = model
        }

        installTask = Task {
            let stream = await installer.install(plan: plan)
            for await event in stream {
                model.handleEvent(event)
            }
            // Re-check dependencies (without auto-advancing, so the user
            // can see partial-failure state and retry before dismissing).
            appState.isCheckingDependencies = true
            let newStatus = await appState.store.bridge.validateDependencies(
                userConfiguredPath: nil,
                refreshShellEnvironment: true
            )
            appState.dependencyStatus = newStatus
            appState.isCheckingDependencies = false

            // Surface Homebrew notice only when all runnable steps succeeded;
            // otherwise keep the progress view visible so the user can see
            // failures and retry.
            if plan.homebrewMissing && model.overallStatus == .completed {
                model.homebrewMissing = true
            }
        }
    }

    private func cancelInstallation() {
        installTask?.cancel()
        installTask = nil
        Task { await installer?.cancelCurrent() }
        installer = nil
        appState.installModel?.markCancelled()
    }

    private func finishInstallation() {
        // Advance past onboarding when the install succeeded (or partially
        // succeeded) and minimum requirements are met.  For .allFailed,
        // .cancelled, or HomebrewMissing "Back", drop back to the dependency
        // check view instead.
        let shouldAdvance: Bool = {
            guard let model = appState.installModel,
                  !model.homebrewMissing,
                  appState.dependencyStatus?.meetsMinimumRequirements == true
            else { return false }
            switch model.overallStatus {
            case .completed, .partialFailure: return true
            default: return false
            }
        }()

        installTask?.cancel()
        installTask = nil
        installer = nil
        withAnimation(reduceMotion ? nil : DDMotion.snappy) {
            appState.installModel = nil
            if shouldAdvance {
                appState.hasCompletedOnboarding = true
                appState.hasPassedDependencyCheck = true
            }
        }
    }

    private func installCommand(for tool: String) -> String? {
        switch tool {
        case "duplicates-detector": "pip install duplicates-detector"
        case "ffmpeg", "ffprobe": "brew install ffmpeg"
        case "fpcalc": "brew install chromaprint"
        case "mutagen": nil
        default: nil
        }
    }

    private func abbreviatePath(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        if path.hasPrefix(home) {
            return "~" + path.dropFirst(home.count)
        }
        return path
    }
}

#if DEBUG
#Preview("All Available") {
    DependencyCheckView(status: PreviewFixtures.allAvailableDependencyStatus())
        .environment(PreviewFixtures.appState())
        .frame(width: 700, height: 600)
}

#Preview("CLI Missing") {
    DependencyCheckView(status: PreviewFixtures.missingCLIDependencyStatus())
        .environment(PreviewFixtures.appState())
        .frame(width: 700, height: 600)
}
#endif
