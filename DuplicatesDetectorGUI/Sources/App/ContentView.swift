import SwiftUI

/// Root view -- gates workspace behind the dependency check, then shows the scan flow directly.
///
/// No per-window scan state -- `ScanFlowView` reads `appState.store` directly.
/// This prevents macOS state restoration or duplicate windows from creating
/// independent scan lifecycles.
public struct ContentView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.ddColors) private var ddColors

    public init() {}

    public var body: some View {
        NavigationStack {
            ScanFlowView()
        }
        .modifier(DDAdaptiveColorsInjector())
        .toolbar(appState.hasPassedDependencyCheck ? .visible : .hidden, for: .windowToolbar)
        .overlay {
            if !appState.hasPassedDependencyCheck {
                ZStack {
                    DDColors.surface0
                        .ignoresSafeArea()

                    Group {
                        if let status = appState.dependencyStatus {
                            DependencyCheckView(status: status)
                        } else {
                            loadingView
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .background(DDColors.surface0.opacity(0.82))
        .frame(minWidth: 1000, minHeight: 700)
        .task {
            await checkDependencies()
        }
    }

    // MARK: - Loading

    private var loadingView: some View {
        VStack(spacing: DDSpacing.md) {
            ProgressView()
                .controlSize(.large)
            Text("Checking dependencies\u{2026}")
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DDColors.surface0)
    }

    // MARK: - Dependency Check

    private func checkDependencies() async {
        guard appState.dependencyStatus == nil else { return }
        await appState.store.bridge.cleanupOrphanedProcess()
        appState.isCheckingDependencies = true
        let status = await appState.store.bridge.validateDependencies()
        appState.dependencyStatus = status
        appState.isCheckingDependencies = false

        // Forward dependency status to the session store's setup state
        appState.store.sendSetup(.setDependencyStatus(status))

        // UI tests: auto-advance unconditionally after validation — binaryPath is
        // now populated, so the scan/replay/mock flow can safely proceed.
        // Covers DD_UI_TEST_MOCK, DD_UI_TEST_SCAN_DIR, DD_UI_TEST_REPLAY, etc.
        #if DEBUG
        let isUITest = ProcessInfo.processInfo.environment.keys.contains { $0.hasPrefix("DD_UI_TEST_") }
        #else
        let isUITest = false
        #endif

        // Bundled app: everything is self-contained, auto-advance unconditionally.
        // Non-bundled: auto-advance when CLI works and either all deps present or
        // the user has completed onboarding before.
        if isUITest || appState.store.bridge.hasBundledCLI()
            || (status.meetsMinimumRequirements
                && (!status.hasMissingDependencies || appState.hasCompletedOnboarding))
        {
            // Don't persist onboarding completion from UI-test runs — they use
            // the same bundle ID and would permanently flip the real app's flag.
            if !isUITest {
                appState.hasCompletedOnboarding = true
            }
            appState.hasPassedDependencyCheck = true
        }
    }
}

#if DEBUG
#Preview("Workspace") {
    let state = PreviewFixtures.appState()
    let _ = {
        state.hasPassedDependencyCheck = true
        state.dependencyStatus = PreviewFixtures.allAvailableDependencyStatus()
    }()
    ContentView()
        .environment(state)
        .frame(width: 1100, height: 750)
}
#endif
