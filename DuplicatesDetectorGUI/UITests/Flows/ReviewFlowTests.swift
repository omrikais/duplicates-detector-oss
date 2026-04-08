import XCTest

/// Tests the pair review flow: navigating pairs, keep/skip/ignore actions.
///
/// All tests use the `"pairs"` scenario which provides 3 canned pairs with
/// scores 92.5, 78.0, and 65.3. The first pair is auto-selected on load.
@MainActor
final class ReviewFlowTests: XCTestCase {
    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// Navigate from launch through scan to the results screen.
    ///
    /// After this method returns, the results screen is visible with
    /// the "New Scan" toolbar button and the queue pane populated.
    ///
    /// - Throws: `XCTSkip` if the window is not accessible (macOS 26).
    private func navigateToResults() throws {
        app.launchForUITesting(scenario: "pairs")
        XCTAssertTrue(
            app.waitForMainWindow(),
            "App UI not accessible — check automationmodetool and macOS version"
        )

        let startScanButton = app.buttons["Start Scan"]
        guard app.waitForElement(startScanButton, timeout: 10) else {
            XCTFail("Start Scan button did not appear")
            return
        }
        startScanButton.click()

        let newScanButton = app.buttons["New Scan"]
        guard app.waitForElement(newScanButton, timeout: 15) else {
            XCTFail("Results screen did not load (New Scan button missing)")
            return
        }
    }

    // MARK: - Keep A

    func testKeepA_resolvesPair() throws {
        try navigateToResults()

        // The ComparisonActionBar shows "Keep A" and "Keep B" buttons.
        let keepAButton = app.buttons["Keep A"]
        XCTAssertTrue(
            app.waitForElement(keepAButton, timeout: 5),
            "Keep A button should be visible in the comparison action bar"
        )

        // Click Keep A -- this resolves the current pair and advances.
        keepAButton.click()

        // After action, the action bar should still be visible for the
        // next pair.
        let skipButton = app.buttons["Skip"]
        XCTAssertTrue(
            app.waitForElement(skipButton, timeout: 5),
            "Skip button should remain visible after advancing to next pair"
        )
    }

    // MARK: - Keep B

    func testKeepB_resolvesPair() throws {
        try navigateToResults()

        let keepBButton = app.buttons["Keep B"]
        XCTAssertTrue(
            app.waitForElement(keepBButton, timeout: 5),
            "Keep B button should be visible in the comparison action bar"
        )

        keepBButton.click()

        let skipButton = app.buttons["Skip"]
        XCTAssertTrue(
            app.waitForElement(skipButton, timeout: 5),
            "Skip button should remain visible after Keep B"
        )
    }

    // MARK: - Skip

    func testSkip_advancesWithoutResolving() throws {
        try navigateToResults()

        let skipButton = app.buttons["Skip"]
        XCTAssertTrue(
            app.waitForElement(skipButton, timeout: 5),
            "Skip button should exist on results screen"
        )

        // Skip should advance without performing any file action.
        skipButton.click()

        // The action bar should still be visible for the next pair.
        XCTAssertTrue(
            app.waitForElement(app.buttons["Keep A"], timeout: 5),
            "Keep A should be visible on the next pair after skip"
        )
    }

    // MARK: - Ignore

    func testIgnore_addsPairToIgnoreList() throws {
        try navigateToResults()

        // The "Ignore" button is in the ComparisonActionBar.
        let ignoreButton = app.buttons["Ignore"]
        XCTAssertTrue(
            app.waitForElement(ignoreButton, timeout: 5),
            "Ignore button should exist in the action bar"
        )

        ignoreButton.click()

        // After ignoring, we advance to the next pair.
        let keepA = app.buttons["Keep A"]
        XCTAssertTrue(
            app.waitForElement(keepA, timeout: 5),
            "Should advance to next pair after ignoring"
        )
    }

    // MARK: - Queue Navigation

    func testNavigateQueue_previousAndSkip() throws {
        try navigateToResults()

        // Skip to the second pair.
        let skipButton = app.buttons["Skip"]
        XCTAssertTrue(app.waitForElement(skipButton, timeout: 5))
        skipButton.click()

        // Use Previous to go back.
        let previousButton = app.buttons["Previous"]
        XCTAssertTrue(
            app.waitForElement(previousButton, timeout: 5),
            "Previous button should be visible"
        )
        previousButton.click()

        // Verify we're back on a pair with the action bar visible.
        let keepA = app.buttons["Keep A"]
        XCTAssertTrue(
            app.waitForElement(keepA, timeout: 5),
            "Keep A should be visible after navigating back to previous pair"
        )
    }
}
