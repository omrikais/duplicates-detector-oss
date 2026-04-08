import XCTest

/// Tests the error flow: scan -> error screen -> recovery options.
///
/// Uses the `"error"` scenario in ``MockCLIBridge`` which throws a
/// simulated CLI failure partway through the pipeline.
@MainActor
final class ErrorFlowTests: XCTestCase {
    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Error Display

    func testScanError_showsErrorScreen() throws {
        app.launchForUITesting(scenario: "error")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        // Start a scan -- the error scenario fails mid-pipeline.
        let startScanButton = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScanButton, timeout: 10))
        startScanButton.click()

        // The ErrorScreen displays "Back to Configuration" button.
        let backButton = app.buttons["Back to Configuration"]
        XCTAssertTrue(
            app.waitForElement(backButton, timeout: 15),
            "Error screen should display 'Back to Configuration' button"
        )

        // The "Try Again" button should also exist since the last scan
        // config is preserved.
        let tryAgainButton = app.buttons["Try Again"]
        XCTAssertTrue(
            tryAgainButton.exists,
            "'Try Again' button should be available on error screen"
        )
    }

    // MARK: - Recovery

    func testRecoverFromError_backToConfiguration() throws {
        app.launchForUITesting(scenario: "error")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScanButton = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScanButton, timeout: 10))
        startScanButton.click()

        // Wait for the error screen.
        let backButton = app.buttons["Back to Configuration"]
        XCTAssertTrue(
            app.waitForElement(backButton, timeout: 15),
            "Error screen should appear after scan failure"
        )

        // Navigate back to configuration.
        backButton.click()

        // Should return to the setup screen with "Start Scan" visible.
        XCTAssertTrue(
            app.waitForElement(app.buttons["Start Scan"], timeout: 10),
            "Should navigate back to configuration screen"
        )
    }
}
