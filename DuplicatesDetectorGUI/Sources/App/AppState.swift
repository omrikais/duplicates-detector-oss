import SwiftUI

/// Application state shared across the app.
///
/// Owns the single `SessionStore` that drives the entire session lifecycle.
/// All windows share this store -- macOS state restoration or duplicate windows
/// cannot create independent scan state.
@Observable
@MainActor
public final class AppState {
    public let store: SessionStore
    let bookmarkManager: BookmarkManager

    var dependencyStatus: DependencyStatus?
    var hasPassedDependencyCheck = false {
        didSet {
            if hasPassedDependencyCheck, let url = pendingReplayURL {
                pendingReplayURL = nil
                store.openReplayFile(url)
            }
        }
    }
    var isCheckingDependencies = false

    /// Replay URL received before dependency gating passed (e.g. Finder open on first launch).
    var pendingReplayURL: URL?

    /// Open a replay file, deferring until dependency gating passes if needed.
    public func openReplayFileWhenReady(_ url: URL) {
        if hasPassedDependencyCheck {
            store.openReplayFile(url)
        } else {
            pendingReplayURL = url
        }
    }

    /// Persisted: the user has completed dependency onboarding at least once.
    /// Prevents nagging returning users who have the CLI but not every optional tool.
    var hasCompletedOnboarding: Bool {
        get { UserDefaults.standard.bool(forKey: "hasCompletedOnboarding") }
        set { UserDefaults.standard.set(newValue, forKey: "hasCompletedOnboarding") }
    }

    /// Active installation progress model (non-nil while installing).
    var installModel: InstallProgressModel?

    /// Convenience: whether an installation is currently running.
    var isInstalling: Bool {
        installModel != nil && installModel?.overallStatus == .installing
    }

    public init() {
        let bridge: any CLIBridgeProtocol
        #if DEBUG
        if let scenario = ProcessInfo.processInfo.environment["DD_UI_TEST_SCENARIO"] {
            bridge = MockCLIBridge(scenario: scenario)
        } else if ProcessInfo.processInfo.environment["DD_UI_TEST_MOCK"] != nil {
            bridge = MockCLIBridge(scenario: "pairs")
        } else {
            bridge = CLIBridge()
        }
        #else
        bridge = CLIBridge()
        #endif
        self.store = SessionStore(bridge: bridge)
        self.bookmarkManager = BookmarkManager()
        bookmarkManager.restoreBookmarks()

        #if DEBUG
        let env = ProcessInfo.processInfo.environment

        if env["DD_UI_TEST_MOCK"] != nil {
            if env["DD_UI_TEST_SOURCE"] == "photos" {
                // Photos Library mock: seed the source picker to Photos Library.
                store.sendSetup(.setScanSource(.photosLibrary(scope: .fullLibrary)))
            } else {
                // Directory mock: seed a temp directory so flow tests don't need NSOpenPanel.
                let tmpDir = FileManager.default.temporaryDirectory
                    .appendingPathComponent("dd-ui-test-media")
                try? FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
                store.sendSetup(.addDirectory(tmpDir))
            }
        }

        // E2E test seeding: set scan directory, mode, content from env vars.
        // Note: hasPassedDependencyCheck is NOT set here — ContentView.checkDependencies()
        // runs validateDependencies() first (populating binaryPath), then auto-advances
        // when it detects E2E env vars.
        if let scanDir = env["DD_UI_TEST_SCAN_DIR"] {
            let url = URL(fileURLWithPath: scanDir)
            store.sendSetup(.addDirectory(url))
        }
        if let modeStr = env["DD_UI_TEST_MODE"],
           let mode = ScanMode(rawValue: modeStr) {
            store.sendSetup(.setMode(mode))
        }
        if env["DD_UI_TEST_CONTENT"] == "1" {
            store.sendSetup(.setContent(true))
        }
        if let replayPath = env["DD_UI_TEST_REPLAY"] {
            let url = URL(fileURLWithPath: replayPath)
            // Deferred: pendingReplayURL is processed by hasPassedDependencyCheck.didSet
            // after ContentView.checkDependencies() completes validation.
            openReplayFileWhenReady(url)
        }
        #endif
    }
}
