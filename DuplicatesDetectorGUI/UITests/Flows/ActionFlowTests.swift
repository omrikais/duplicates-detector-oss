import XCTest

/// Tests file action flows: trash execution and export accessibility.
///
/// The mock pairs use `action: "delete"` in the canned args, but
/// ``ScanCoordinator`` overrides this to `.trash` for GUI safety.
/// Trash executes immediately (reversible), while permanent delete
/// and move require confirmation dialogs.
@MainActor
final class ActionFlowTests: XCTestCase {
    let app = XCUIApplication()

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// Navigate from launch through scan to results, ready for review.
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
            XCTFail("Results screen did not load")
            return
        }
    }

    // MARK: - Trash Action

    func testTrashAction_keepsFileAndAdvances() throws {
        try navigateToResults()

        // The default action is trash (GUI safety override). Clicking
        // "Keep A" trashes file B immediately (no confirmation for trash).
        let keepAButton = app.buttons["Keep A"]
        XCTAssertTrue(
            app.waitForElement(keepAButton, timeout: 5),
            "Keep A button should be visible"
        )
        XCTAssertTrue(keepAButton.isEnabled, "Keep A should be enabled for non-reference files")

        keepAButton.click()

        // After trash, the pair is resolved and we advance.
        let skipButton = app.buttons["Skip"]
        XCTAssertTrue(
            app.waitForElement(skipButton, timeout: 5),
            "Should advance to next pair after trash action"
        )
    }

    // MARK: - Export Menu

    func testExportMenu_isAccessible() throws {
        try navigateToResults()

        // The toolbar has an "Export" menu. The element type varies by
        // macOS version (button, menuButton, popUpButton), so search by
        // accessibility identifier across all element types.
        let exportElement = app.descendants(matching: .any).matching(
            identifier: "exportMenu"
        ).firstMatch
        XCTAssertTrue(
            app.waitForElement(exportElement, timeout: 5),
            "Export menu should be accessible in the results toolbar"
        )
    }
}
