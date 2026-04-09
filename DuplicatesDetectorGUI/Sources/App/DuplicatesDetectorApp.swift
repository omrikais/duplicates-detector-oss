import AppKit
import SwiftUI
import UserNotifications

import DuplicatesDetector

/// Ensures the app activates as a regular foreground application and
/// cleans up child processes on termination.
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    /// Callback set by the SwiftUI App to open the main window.
    var openMainWindow: (() -> Void)?

    /// App state reference, set by the SwiftUI App for notification routing.
    var appState: AppState?

    /// Tracked main window -- first-come-wins, used to detect and close duplicates
    /// that macOS state restoration may have created from stale saved state.
    weak var mainWindow: NSWindow?


    // MARK: - Lifecycle

    func applicationWillFinishLaunching(_ notification: Notification) {
        // Disable macOS window state restoration. This single-window app manages
        // its own state via SessionStore. Stale saved state restores deleted UI
        // (old presets, removed pickers) and creates duplicate windows on
        // notification-triggered activation.
        // Skip when running under XCUITest -- clearing saved state can prevent
        // the Window scene from creating its initial window on macOS 26.
        #if DEBUG
        let isUITesting = ProcessInfo.processInfo.environment.keys.contains { $0.hasPrefix("DD_UI_TEST_") }
        if !isUITesting {
            clearSavedApplicationState()
        }
        #else
        clearSavedApplicationState()
        #endif
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Guard against duplicate instances. Stale build products (e.g. from
        // merged branches in DerivedData) can cause macOS Launch Services to
        // launch a second copy when handling notifications. If another instance
        // is already running, activate it and terminate this one immediately.
        #if DEBUG
        let isUITesting = ProcessInfo.processInfo.environment.keys.contains { $0.hasPrefix("DD_UI_TEST_") }
        #else
        let isUITesting = false
        #endif
        if !isUITesting, let bundleID = Bundle.main.bundleIdentifier {
            let running = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
            if running.count > 1,
               let other = running.first(where: { $0 != .current }) {
                other.activate()
                NSApp.terminate(nil)
                return
            }
        }

        AppDefaults.registerDefaults()
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()

        // Mark every existing window as non-restorable so macOS never saves
        // stale window state again.
        for window in NSApp.windows {
            window.isRestorable = false
        }

        UNUserNotificationCenter.current().delegate = self

    }

    // MARK: - UNUserNotificationCenterDelegate

    /// Activates the main window only when the user explicitly taps a watch-mode notification.
    /// Routes to the specific watch session if the notification carries a session UUID.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        if response.notification.request.content.categoryIdentifier == WatchNotificationConstants.categoryID {
            if let sessionIDStr = response.notification.request.content.userInfo[WatchNotificationConstants.sessionIDKey] as? String,
               let sessionID = UUID(uuidString: sessionIDStr) {
                let state = appState
                MainActor.assumeIsolated {
                    state?.store.openWatchNotification(sessionID: sessionID)
                }
            }
            showMainWindow()
        }
        completionHandler()
    }

    func applicationWillTerminate(_ notification: Notification) {
        _killChild()
        appState?.store.teardown()
    }

    /// Handles `.ddscan` / `.json` file opens (double-click, `open` command, drag-to-dock).
    /// `Window` scenes don't reliably receive `onOpenURL`, so URL routing lives here.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            let ext = url.pathExtension.lowercased()
            guard ext == "ddscan" || ext == "json" else { continue }
            MainActor.assumeIsolated {
                appState?.openReplayFileWhenReady(url)
            }
            showMainWindow()
            return
        }
    }

    /// Watch sessions and the menu bar icon outlive the main window --
    /// don't quit the app just because the user closed the window.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    /// Called when user clicks the dock icon with no visible windows.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showMainWindow() }
        return true
    }

    // MARK: - Window Management

    func showMainWindow() {
        NSApp.activate()

        // Close duplicate windows that macOS state restoration may have created.
        closeDuplicateWindows()

        if let window = mainWindow ?? NSApp.windows.first(where: {
            $0.canBecomeKey && !$0.isKind(of: NSPanel.self)
        }) {
            mainWindow = window
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
            // NSApp.activate() is unreliable on macOS 26 when another app has
            // focus. orderFrontRegardless() forces the window to the front of
            // the screen list regardless of app activation state.
            window.orderFrontRegardless()
        } else {
            // Window was closed -- `openWindow(id:)` on a `Window` scene
            // recreates the single instance (never a duplicate).
            openMainWindow?()
        }
    }

    /// Registers the first main window and closes any duplicates.
    /// Called from the scene body's `onAppear` after the hosting NSWindow exists.
    func registerMainWindow() {
        let candidates = NSApp.windows.filter {
            $0.canBecomeKey && !$0.isKind(of: NSPanel.self)
        }

        if let tracked = mainWindow, candidates.contains(where: { $0 === tracked }) {
            // Tracked window still exists -- close any extras.
            for window in candidates where window !== tracked {
                window.close()
            }
        } else {
            // First window (or tracked window was destroyed) -- register it.
            mainWindow = candidates.first
        }

        // Ensure no macOS state is saved for any window.
        for window in candidates {
            window.isRestorable = false
        }
    }

    // MARK: - State Restoration Prevention

    /// Deletes the macOS Saved Application State directory for this bundle.
    /// Called in `applicationWillFinishLaunching` -- before macOS restores windows.
    private func clearSavedApplicationState() {
        guard let bundleID = Bundle.main.bundleIdentifier else { return }
        guard let library = FileManager.default.urls(
            for: .libraryDirectory, in: .userDomainMask
        ).first else { return }
        let savedState = library
            .appendingPathComponent("Saved Application State")
            .appendingPathComponent("\(bundleID).savedState")
        guard FileManager.default.fileExists(atPath: savedState.path) else { return }
        try? FileManager.default.removeItem(at: savedState)
    }

    /// Closes every main-content window except the tracked `mainWindow`.
    private func closeDuplicateWindows() {
        guard let tracked = mainWindow else { return }
        for window in NSApp.windows
            where window !== tracked && window.canBecomeKey && !window.isKind(of: NSPanel.self) {
            window.close()
        }
    }
}

@main
struct DuplicatesDetectorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var appState = AppState()
    @Environment(\.openWindow) private var openWindow
    @FocusedValue(\.isReviewActive) private var isReviewActive
    @FocusedValue(\.isGroupMode) private var isGroupMode

    private static let mainWindowID = "main"
    private static let settingsWindowID = "settings"

    init() {
        // Wire the shared registry so App Intents can query scan history.
        DuplicatesDetectorShortcuts.sharedRegistry = appState.store.registry
    }
    private var isGroup: Bool { isGroupMode ?? false }

    var body: some Scene {
        // `Window` (not `WindowGroup`) guarantees a single window instance.
        // `openWindow(id:)` brings the existing window to front or recreates
        // it if closed -- it never creates a duplicate.
        Window("Duplicates Detector", id: Self.mainWindowID) {
            ContentView()
                .environment(appState)
                .onReceive(
                    NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)
                ) { _ in
                    // atexit/signal handlers in CLIBridge handle this via _killChild(),
                    // but also send SIGTERM synchronously here for the graceful path.
                    _killChild()
                    // Synchronous teardown -- async Tasks cannot complete during willTerminate.
                    appState.store.teardown()
                }
                .onReceive(
                    NotificationCenter.default.publisher(for: .openScanFromShortcut)
                ) { notification in
                    if let sessionID = notification.userInfo?["sessionID"] as? UUID {
                        appState.store.openWatchNotification(sessionID: sessionID)
                    }
                }
                .onAppear {
                    // Wire the AppDelegate's openMainWindow callback to SwiftUI's openWindow
                    appDelegate.openMainWindow = { [self] in
                        openWindow(id: Self.mainWindowID)
                    }
                    appDelegate.appState = appState
                    // Wire SessionStore's window activation to openWindow —
                    // recreates the window when closed (e.g. watch mode menu bar).
                    appState.store.onActivateMainWindow = { [self] in
                        openWindow(id: Self.mainWindowID)
                    }

                    // Register this window and close any duplicates that macOS
                    // state restoration may have created from stale saved state.
                    // DispatchQueue.main.async ensures the hosting NSWindow exists.
                    DispatchQueue.main.async { [self] in
                        appDelegate.registerMainWindow()
                    }
                }
                .task {
                    await appState.store.start()
                }
        }
        .defaultSize(width: 1100, height: 750)
        .defaultLaunchBehavior(.presented)
        .commands {
            // Single-window app -- suppress File > New Window (Cmd+N).
            CommandGroup(replacing: .newItem) {}

            // Custom Settings window replaces the default non-resizable one.
            CommandGroup(replacing: .appSettings) {
                Button("Settings...") {
                    openWindow(id: Self.settingsWindowID)
                }
                .keyboardShortcut(",", modifiers: .command)
            }

            CommandMenu("Review") {
                // Arrow key shortcuts (left/right/up/down) are handled by onKeyPress in
                // ResultsScreen, gated on focusedPane == .comparison.
                // They must NOT be on CommandMenu items -- global menu shortcuts
                // fire before the focused view and would steal arrow keys from
                // the queue list's built-in navigation.
                Button(isGroup ? "Previous Member  \u{2190}" : "Keep File A  \u{2190}") {
                    appState.store.sendMenuCommand(.keepA)
                }
                .disabled(!(isReviewActive ?? false))

                Button(isGroup ? "Next Member  \u{2192}" : "Keep File B  \u{2192}") {
                    appState.store.sendMenuCommand(.keepB)
                }
                .disabled(!(isReviewActive ?? false))

                Button(isGroup ? "Next Group  \u{2193}" : "Skip Pair  \u{2193}") {
                    appState.store.sendMenuCommand(.skip)
                }
                .disabled(!(isReviewActive ?? false))

                Button(isGroup ? "Previous Group  \u{2191}" : "Previous Pair  \u{2191}") {
                    appState.store.sendMenuCommand(.previous)
                }
                .disabled(!(isReviewActive ?? false))

                Divider()

                Button(isGroup ? "Act on Member  \u{232B}" : "Ignore Pair  I") {
                    if isGroup {
                        appState.store.sendMenuCommand(.actionMember)
                    } else {
                        appState.store.sendMenuCommand(.ignore)
                    }
                }
                .disabled(!(isReviewActive ?? false))

                Button("Return to Queue  Esc") {
                    appState.store.sendMenuCommand(.focusQueue)
                }
                .disabled(!(isReviewActive ?? false))
            }
        }

        Window("Settings", id: Self.settingsWindowID) {
            SettingsView()
                .modifier(DDAdaptiveColorsInjector())
                .environment(appState)
                .preferredColorScheme(.dark)
        }
        .defaultSize(width: 600, height: 650)
        .windowResizability(.contentMinSize)
    }

}
