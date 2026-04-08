import XCTest

extension XCUIApplication {
    /// Launch the app with mock CLI bridge enabled.
    ///
    /// The ``MockCLIBridge`` is injected when the app detects the
    /// `DD_UI_TEST_MOCK` and `DD_UI_TEST_SCENARIO` environment variables
    /// (see ``AppState.init()``). A temp directory is auto-seeded so the
    /// "Start Scan" button is enabled without user interaction.
    func launchForUITesting(scenario: String = "pairs") {
        launchEnvironment["DD_UI_TEST_MOCK"] = "1"
        launchEnvironment["DD_UI_TEST_SCENARIO"] = scenario
        launch()
    }

    /// Launch the app with Photos Library source and mock CLI bridge.
    ///
    /// Sets `DD_UI_TEST_SOURCE=photos` so the setup screen pre-selects
    /// Photos Library instead of seeding a directory. The mock Photos scan
    /// in ``SessionStore`` returns canned data with `photos://asset/` URIs.
    func launchForPhotosUITesting(scenario: String = "photos-pairs") {
        launchEnvironment["DD_UI_TEST_MOCK"] = "1"
        launchEnvironment["DD_UI_TEST_SCENARIO"] = scenario
        launchEnvironment["DD_UI_TEST_SOURCE"] = "photos"
        launch()
    }

    /// Wait for an element to exist with a timeout.
    ///
    /// - Returns: `true` if the element appeared within the timeout.
    @discardableResult
    func waitForElement(_ element: XCUIElement, timeout: TimeInterval = 10) -> Bool {
        element.waitForExistence(timeout: timeout)
    }

    /// Wait for the main application window to appear.
    ///
    /// On macOS 26, XCUITest's `launch()` may not trigger window creation
    /// for SwiftUI `Window` scenes (unlike a Finder/dock launch). If the
    /// window doesn't appear after a short wait, `open -a` sends the
    /// reopen Apple Event that triggers `applicationShouldHandleReopen`,
    /// which presents the window — same as clicking the dock icon.
    ///
    /// - Returns: `true` if a window appeared within the timeout.
    @discardableResult
    func waitForMainWindow(timeout: TimeInterval = 15) -> Bool {
        activate()
        if windows.firstMatch.waitForExistence(timeout: 5) {
            return true
        }
        // Send the reopen Apple Event via `open -a` (same as dock click)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", "Duplicates Detector"]
        try? process.run()
        process.waitUntilExit()
        return windows.firstMatch.waitForExistence(timeout: timeout - 5)
    }
}
