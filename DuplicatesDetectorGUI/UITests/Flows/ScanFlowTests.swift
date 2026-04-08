import XCTest

/// Tests the primary scan flow: configuration -> scanning -> results.
///
/// Each test launches the app with a ``MockCLIBridge`` scenario via
/// `launchForUITesting(scenario:)`. The mock bridge auto-seeds a temp
/// directory so the "Start Scan" button is enabled without NSOpenPanel.
///
/// **Note:** On macOS 26 (Tahoe) beta, the SwiftUI `Window` scene may
/// take a moment to appear in the XCUITest accessibility hierarchy. Tests
/// use `waitForMainWindow()` and fail if it doesn't appear.
@MainActor
final class ScanFlowTests: XCTestCase {
    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Happy Path

    func testHappyPath_launchToResults() throws {
        app.launchForUITesting(scenario: "pairs")

        // The dependency check auto-advances (MockCLIBridge meets minimum
        // requirements). Wait for the window to be accessible.
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        // The setup screen shows a "Start Scan" button.
        let startScanButton = app.buttons["Start Scan"]
        XCTAssertTrue(
            app.waitForElement(startScanButton, timeout: 10),
            "Start Scan button should appear after dependency check auto-advance"
        )

        // Tap Start Scan — the mock completes quickly so we skip asserting
        // on transient progress-screen elements (Cancel is tested separately
        // in testCancelMidScan_returnsToConfiguration with the slow-pairs
        // scenario).
        startScanButton.click()

        // Wait for results: the toolbar shows "New Scan" once results load.
        let newScanButton = app.buttons["New Scan"]
        XCTAssertTrue(
            app.waitForElement(newScanButton, timeout: 15),
            "New Scan button should appear once results load"
        )

        // Verify the comparison action bar is visible (confirms pairs loaded).
        let keepA = app.buttons["Keep A"]
        XCTAssertTrue(
            app.waitForElement(keepA, timeout: 5),
            "Keep A button should be visible on results screen"
        )
    }

    // MARK: - Empty Results

    func testEmptyResults_showsZeroResultsScreen() throws {
        app.launchForUITesting(scenario: "empty")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScanButton = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScanButton, timeout: 10))
        startScanButton.click()

        // The empty scenario produces 0 pairs. Wait for the
        // ZeroResultsScreen's "New Scan" toolbar button.
        let newScanButton = app.buttons["New Scan"]
        XCTAssertTrue(
            app.waitForElement(newScanButton, timeout: 15),
            "New Scan button should appear on zero results screen"
        )

        // The hero section uses .accessibilityElement(children: .ignore)
        // with a combined label, so query by predicate on any element type.
        let nodupsElement = app.descendants(matching: .any).matching(
            NSPredicate(format: "label BEGINSWITH 'No Duplicates Found'")
        ).firstMatch
        XCTAssertTrue(
            nodupsElement.exists,
            "Zero results screen should display 'No Duplicates Found' accessibility label"
        )
    }

    // MARK: - Cancel Mid-Scan

    func testCancelMidScan_returnsToConfiguration() throws {
        app.launchForUITesting(scenario: "slow-pairs")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScanButton = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScanButton, timeout: 10))
        startScanButton.click()

        // Wait for the progress screen.
        let cancelButton = app.buttons["Cancel Scan"]
        XCTAssertTrue(
            app.waitForElement(cancelButton, timeout: 10),
            "Cancel Scan button should appear during scanning"
        )

        // Cancel the scan.
        cancelButton.click()

        // The slow-pairs mock delays long enough for cancel to take effect.
        let returnedToSetup = app.buttons["Start Scan"].waitForExistence(timeout: 10)
        XCTAssertTrue(
            returnedToSetup,
            "Should return to configuration screen after cancel"
        )
    }

    // MARK: - Group Mode

    func testGroupMode_showsGroupView() throws {
        app.launchForUITesting(scenario: "groups")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScanButton = app.buttons["Start Scan"]
        XCTAssertTrue(app.waitForElement(startScanButton, timeout: 10))
        startScanButton.click()

        // Wait for results to load.
        let newScanButton = app.buttons["New Scan"]
        XCTAssertTrue(
            app.waitForElement(newScanButton, timeout: 15),
            "Results screen should appear for groups scenario"
        )

        // Groups envelope sets group=true. The view mode picker should
        // be visible. Depending on macOS version, the Picker renders as
        // segmented buttons, a popup button, or radio buttons.
        let hasViewPicker = app.buttons["Groups"].exists
            || app.buttons["Pairs"].exists
            || app.popUpButtons["View"].exists
            || app.segmentedControls.firstMatch.exists
            || app.radioButtons["Groups"].exists
            || app.radioButtons["Pairs"].exists
        XCTAssertTrue(
            hasViewPicker,
            "View mode picker (Pairs/Groups) should be visible for grouped results"
        )
    }
}
